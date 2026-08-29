"""
Web server for serving latest processed image via HTTP.
Provides endpoints for NINA and other remote applications to fetch latest frame.
"""

import os
import io
import json
import hashlib
import re
import threading
import time
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from PIL import Image
from .logger import app_logger
from . import api_auth, web_control, web_library

# Maximum image size served by the web endpoint (5 MB)
WEB_IMAGE_MAX_BYTES = 5 * 1024 * 1024

# Matches a GENUINE absolute filesystem path anywhere in a string (W5). The
# POSIX form is rooted at a string/whitespace boundary and needs ≥2 segments,
# so it scrubs real paths like ``/home/observer/data`` without clobbering
# benign slash-bearing values such as a date ``06/28/2026`` or ratio ``16/9``
# (whose inner slashes are preceded by digits, not a boundary). Matched spans
# are redacted in place so the rest of the value (and unrelated keys) survive.
_REDACTED_PATH = "<redacted-path>"
_ABS_PATH_RE = re.compile(
    r'[A-Za-z]:[\\/]\S*'             # Windows drive: C:\... or C:/...
    r'|\\\\\S+'                      # UNC: \\host\share
    r'|(?:^|(?<=\s))/[^\s/]+/\S*'    # POSIX absolute, boundary-rooted, 2+ segments
)


def _safe_image_label(path):
    """Reduce an image path to a bare filename for the /status payload."""
    if not path:
        return "None"
    return os.path.basename(path) or "None"


def _scrub_metadata(metadata):
    """Redact absolute filesystem paths out of metadata string values.

    Defense-in-depth for the local-only /status endpoint: overlay/capture
    metadata can carry source paths (e.g. the saved-file path) that would
    otherwise expose the drive + Windows username + folder layout. Only the
    matched path span is replaced, so the key and any surrounding text are
    preserved and benign slash-bearing values (dates, ratios) are untouched.
    """
    if not isinstance(metadata, dict):
        return {}
    return {
        k: (_ABS_PATH_RE.sub(_REDACTED_PATH, v) if isinstance(v, str) else v)
        for k, v in metadata.items()
    }


class ImageHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for serving images and status."""

    # Per-request socket timeout (applied by StreamRequestHandler.setup). Bounds
    # how long a stalled client can tie up a request thread — without it a dead
    # socket mid-response blocks forever, which used to hang server shutdown.
    timeout = 30

    # Class-level variables shared between all handler instances
    latest_image_path = None
    latest_metadata = {}
    # Single immutable snapshot of the served image body, assigned atomically by
    # update_image() and bound to a local exactly once by each reader. Tuple of
    # (data, content_type, etag, update_time). A reference swap is atomic under
    # CPython, so a request thread can never observe a Content-Length that
    # belongs to a different frame than the body it writes (W3 torn-read fix).
    latest_image_snapshot = None
    server_start_time = None
    image_count = 0
    # Images older than this are flagged as stale in /status and via
    # X-PFR-Image-Stale header so consumers (NINA, dashboards) can detect
    # capture outages instead of silently serving hours-old frames.
    stale_threshold_sec = 300
    # Discrete capture snapshot pushed by the app (MainWindow / HeadlessRunner)
    # via update_capture_status(). The server stays ignorant of capture; it just
    # reports what was last pushed plus request-time derived fields. See
    # services/api_status.py.
    capture_status = {}

    def do_POST(self):
        """Handle POST requests — capture control only.

        Control routes are authenticated and CORS-free; see
        services/web_control.py for the security posture. Anything else 404s
        with no hint that other verbs exist.
        """
        control_path = getattr(self.server, 'control_path', '/capture')
        try:
            if not web_control.route_post(self, control_path):
                self.send_error(404, "Path not found.")
        except Exception as e:
            # Without this a handler bug is a bare connection reset and a
            # traceback to a stderr that is None under a windowed PyInstaller
            # build. Answer with a redacted 500 instead.
            app_logger.error(f"Unhandled error in control route: {api_auth.redact(e)}")
            try:
                self.send_error(500, "Internal error handling control request.")
            except Exception:
                pass

    @classmethod
    def update_image(cls, image_data: bytes, content_type: str, path: str = None, metadata: dict = None):
        """
        Update the latest image with ETag generation.
        PERF-002: Centralized image update with caching support.

        Args:
            image_data: Raw image bytes
            content_type: MIME type (e.g., 'image/jpeg')
            path: Optional file path for logging
            metadata: Optional metadata dict
        """
        # Assemble the full snapshot first, then publish with a single atomic
        # reference assignment so readers see all four fields together or not
        # at all. Never mutate the tuple in place.
        cls.latest_image_snapshot = (
            image_data,
            content_type,
            hashlib.md5(image_data).hexdigest(),  # ETag for cache validation
            time.time(),
        )
        cls.latest_image_path = path
        if metadata:
            cls.latest_metadata = metadata
        cls.image_count += 1

    @classmethod
    def update_capture_status(cls, snapshot: dict):
        """Store the latest capture snapshot pushed by the app.

        Plain dict assignment — the only cross-thread surface between the Qt/app
        side and the HTTP server thread. Derived/time-relative fields are
        computed at request time in _serve_status(), not here.
        """
        cls.capture_status = snapshot or {}

    @classmethod
    def _image_age_seconds(cls):
        """Seconds since the last update_image() call, or None if never set."""
        snapshot = cls.latest_image_snapshot
        if snapshot is None:
            return None
        return max(0.0, time.time() - snapshot[3])
    
    def log_message(self, format, *args):
        """Override to use our logger instead of stderr."""
        app_logger.info(f"HTTP {self.address_string()} - {format % args}")
    
    def do_GET(self):
        """Handle GET requests."""
        config_path = self.server.config_path
        status_path = self.server.status_path
        docs_path = getattr(self.server, 'docs_path', '/docs')
        openapi_path = getattr(self.server, 'openapi_path', '/openapi.json')
        library_path = getattr(self.server, 'library_path', '/library')
        control_path = getattr(self.server, 'control_path', '/capture')

        # Parse URL to strip query parameters (e.g., ?t=1764384123178)
        parsed_url = urlparse(self.path)
        clean_path = parsed_url.path
        query_params = parse_qs(parsed_url.query)

        # Debug logging to diagnose path matching issues
        app_logger.debug(f"Request: original='{self.path}', clean='{clean_path}', config='{config_path}', status='{status_path}'")
        if query_params:
            app_logger.debug(f"Query params: {query_params}")

        # Library endpoints are delegated to services/web_library.py (keeps this
        # module under the size cap). The library gate reads the live config, so
        # only evaluate it for paths that could actually be library routes — the
        # hot /latest and /status paths must not pay for it on every request.
        if clean_path == config_path:
            self._serve_image()
        elif clean_path == status_path:
            self._serve_status()
        elif clean_path == openapi_path:
            self._serve_openapi()
        elif clean_path == docs_path:
            self._serve_docs()
        elif clean_path == control_path:
            web_control.serve_capture_state(self)
        elif clean_path == library_path + '/image' and self._library_api_enabled():
            web_library.serve_image(self, self._library(), query_params)
        elif clean_path == library_path and self._library_api_enabled():
            web_library.serve_list(self, self._library(), library_path, query_params)
        else:
            available = ", ".join([config_path, status_path, openapi_path, docs_path])
            if getattr(self.server, 'control_token', ''):
                available += f", {control_path}"
            if self._library_api_enabled():
                available += f", {library_path}, {library_path}/image"
            self.send_error(404, f"Path not found. Available: {available}")
    
    # ACCEPTED RISK (W4): wildcard CORS (`Access-Control-Allow-Origin: *`) and
    # the lack of Host-header validation allow a DNS-rebinding page to read
    # /status and /library. Accepted because the server binds loopback
    # (127.0.0.1) by default and is local-only by design (auth is out of
    # scope). Revisit — add Host allow-listing and drop the wildcard ACAO —
    # only if the server is ever bound to a non-loopback host.
    def do_OPTIONS(self):
        """Handle OPTIONS requests for CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()
    
    def _serve_image(self):
        """Serve the latest processed image with ETag caching support."""
        # Bind the snapshot once: every field below (404 guard, ETag,
        # Content-Length, body) comes from this single local, so a concurrent
        # update_image() swap can't tear the response (W3).
        snapshot = self.latest_image_snapshot
        if snapshot is None or not snapshot[0]:
            try:
                self.send_error(404, "No image available yet")
            except (ConnectionAbortedError, BrokenPipeError):
                # Client disconnected while we were sending 404 - ignore
                pass
            return

        image_data, content_type, image_etag, update_time = snapshot

        try:
            # PERF-002: Check If-None-Match header for ETag-based caching
            client_etag = self.headers.get('If-None-Match')
            if client_etag and client_etag == image_etag:
                # Client has current version - return 304 Not Modified
                self.send_response(304)
                self.send_header("ETag", image_etag)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                app_logger.debug(f"Served 304 Not Modified (ETag match)")
                return

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", len(image_data))
            # ETag for cache validation (an md5 hexdigest, always present).
            self.send_header("ETag", image_etag)
            self.send_header("Cache-Control", "no-cache, must-revalidate")  # Allow conditional requests
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            # CORS headers for cross-origin requests (portals, web apps)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, If-None-Match")
            # Staleness signalling — consumers that want to know whether the
            # served image is current can check these headers instead of
            # having to diff ETags over time.
            age = max(0.0, time.time() - update_time)
            self.send_header("X-PFR-Image-Age-Seconds", f"{int(age)}")
            if age >= self.stale_threshold_sec:
                self.send_header("X-PFR-Image-Stale", "true")
            self.end_headers()
            self.wfile.write(image_data)
            app_logger.debug(f"Served image: {len(image_data)} bytes ({content_type})")
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError) as e:
            # Client disconnected - this is normal, don't log as error
            app_logger.debug(f"Client disconnected during image transfer: {e.__class__.__name__}")
        except Exception as e:
            app_logger.error(f"Error serving image: {e}")
    
    @classmethod
    def _build_status_dict(cls):
        """Assemble the /status JSON payload (no socket I/O — unit-testable).

        Never exposes filesystem paths: ``latest_image`` is reduced to a bare
        filename and ``metadata`` is scrubbed of absolute-path values so the
        endpoint can't leak the drive layout / Windows username (W5).
        """
        uptime = 0
        if cls.server_start_time:
            uptime = int(time.time() - cls.server_start_time)

        age = cls._image_age_seconds()
        image_stale = age is not None and age >= cls.stale_threshold_sec

        status = {
            "server": "PFR Sentinel HTTP Server",
            "status": "running",
            "uptime_seconds": uptime,
            "images_served": cls.image_count,
            "latest_image": _safe_image_label(cls.latest_image_path),
            "image_age_seconds": int(age) if age is not None else None,
            "image_stale": image_stale,
            "stale_threshold_seconds": cls.stale_threshold_sec,
            # Scrub at the egress boundary (not at write) so a path can't leak
            # regardless of how latest_metadata was set — security over the small
            # per-request regex cost on a local-only, low-frequency endpoint.
            "metadata": _scrub_metadata(cls.latest_metadata),
            "timestamp": datetime.now().isoformat()
        }

        # Merge the capture + health view derived from the latest pushed snapshot.
        # Kept additive so existing consumers relying on the flat keys above are
        # unaffected. See services/api_status.py.
        try:
            from . import api_status
            view = api_status.derive_status_view(
                cls.capture_status,
                image_age=age,
                now=time.time(),
                stale_threshold=cls.stale_threshold_sec,
            )
            status["capture"] = view["capture"]
            status["health"] = view["health"]
        except Exception as e:
            app_logger.error(f"Error deriving capture status: {e}")

        return status

    def _serve_status(self):
        """Serve server status as JSON."""
        status = self._build_status_dict()

        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache")
            # CORS headers for cross-origin requests
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            self.wfile.write(json.dumps(status, indent=2).encode('utf-8'))
        except Exception as e:
            app_logger.error(f"Error serving status: {e}")

    def _build_openapi_spec(self):
        """Build the OpenAPI spec for this server's actual routes."""
        from . import api_docs
        # Only advertise the library routes when the API is actually enabled,
        # so the docs never describe an endpoint that 404s.
        library_path = getattr(self.server, 'library_path', '/library') \
            if self._library_api_enabled() else None
        # Control routes are advertised only when a token is configured — with
        # none they fail closed, so documenting them would describe a 503.
        control_path = getattr(self.server, 'control_path', '/capture') \
            if getattr(self.server, 'control_token', '') else None
        return api_docs.build_openapi_spec(
            image_path=self.server.config_path,
            status_path=self.server.status_path,
            docs_path=getattr(self.server, 'docs_path', '/docs'),
            openapi_path=getattr(self.server, 'openapi_path', '/openapi.json'),
            library_path=library_path,
            control_path=control_path,
        )

    def _serve_openapi(self):
        """Serve the machine-readable OpenAPI 3.0 spec as JSON."""
        try:
            spec = self._build_openapi_spec()
            payload = json.dumps(spec, indent=2).encode('utf-8')
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(payload))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            self.wfile.write(payload)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass
        except Exception as e:
            app_logger.error(f"Error serving OpenAPI spec: {e}")

    def _serve_docs(self):
        """Serve the self-contained HTML API reference (no external deps)."""
        try:
            from . import api_docs
            spec = self._build_openapi_spec()
            payload = api_docs.render_docs_html(spec).encode('utf-8')
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(payload))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass
        except Exception as e:
            app_logger.error(f"Error serving API docs: {e}")

    # --- image library endpoints ------------------------------------------

    def _library(self):
        """The ImageLibrary instance attached to the server, or None."""
        return getattr(self.server, 'image_library', None)

    def _library_api_enabled(self):
        lib = self._library()
        return bool(lib and lib.api_enabled())


class WebOutputServer:
    """Manages HTTP server for serving latest processed images."""
    
    def __init__(self, host='0.0.0.0', port=8080, image_path='/latest', status_path='/status',
                 docs_path='/docs', openapi_path='/openapi.json', library_path='/library',
                 image_library=None, control_path='/capture', control_token='',
                 control_allowed_hosts=None):
        """
        Initialize web server.

        Args:
            host: Interface to bind to (0.0.0.0 for all interfaces)
            port: Port to listen on
            image_path: URL path for image endpoint
            status_path: URL path for status endpoint
            docs_path: URL path for the human-readable HTML API docs
            openapi_path: URL path for the machine-readable OpenAPI spec
            library_path: Base URL path for the image library endpoints
                (``<library_path>`` lists, ``<library_path>/image`` fetches)
            image_library: Optional ImageLibrary the library endpoints read from
            control_path: Base URL path for the capture-control endpoints
                (``<control_path>`` reads state, ``/start`` and ``/stop`` mutate)
            control_token: Bearer token required on every control route. Empty
                means control fails closed — never open.
            control_allowed_hosts: Extra Host header values accepted on control
                routes, beyond loopback and `host`. Only needed for a non-
                loopback bind, where the wildcard address names no host.
        """
        self.host = host
        self.port = port
        self.image_path = image_path
        self.status_path = status_path
        self.docs_path = docs_path
        self.openapi_path = openapi_path
        self.library_path = library_path
        self.image_library = image_library
        self.control_path = control_path
        self._control_token = control_token or ''
        self._control_allowed_hosts = list(control_allowed_hosts or ())
        # Set by the app via register_capture_command_handler(). Until then the
        # control routes 503 — the server never starts capture on its own.
        self._capture_command_handler = None
        self.server = None
        self.server_thread = None
        self.running = False
    
    def start(self):
        """Start the HTTP server in a background thread."""
        if self.running:
            app_logger.warning("Web server already running")
            return False
        
        try:
            # Threaded server: each request runs on its own daemon thread, so a
            # single stalled client can't block the accept loop — that block is
            # what made server.shutdown() hang for minutes on exit. block_on_close
            # is off so server_close() abandons (rather than joins) any in-flight
            # request thread; daemon threads + the handler timeout above bound how
            # long a straggler can linger.
            # ACCEPTED RISK (W6): ThreadingHTTPServer spawns one (unbounded)
            # thread per connection, so a connection flood could exhaust
            # threads. Accepted under the local-only/loopback deployment — the
            # only clients are the operator's own monitoring tools. If the
            # server is ever exposed on a non-loopback host, cap concurrency
            # with a bounded pool or an active-connection 503.
            self.server = ThreadingHTTPServer((self.host, self.port), ImageHTTPHandler)
            self.server.daemon_threads = True
            self.server.block_on_close = False
            self.server.config_path = self.image_path
            self.server.status_path = self.status_path
            self.server.docs_path = self.docs_path
            self.server.openapi_path = self.openapi_path
            self.server.library_path = self.library_path
            self.server.image_library = self.image_library
            self.server.control_path = self.control_path
            self.server.control_host = self.host
            self.server.control_token = self._control_token
            self.server.control_allowed_hosts = self._control_allowed_hosts
            self.server.capture_command_handler = self._capture_command_handler
            
            # Set class variables
            ImageHTTPHandler.server_start_time = time.time()
            ImageHTTPHandler.image_count = 0
            
            # Start in daemon thread
            self.server_thread = threading.Thread(target=self._run_server, daemon=True)
            self.server_thread.start()
            self.running = True
            
            # Get actual address (useful if port was 0 for auto-assign)
            actual_port = self.server.server_port
            app_logger.info(f"Web server started on http://{self.host}:{actual_port}")
            app_logger.info(f"  - Image endpoint: http://{self.host}:{actual_port}{self.image_path}")
            app_logger.info(f"  - Status endpoint: http://{self.host}:{actual_port}{self.status_path}")
            app_logger.info(f"  - API docs: http://{self.host}:{actual_port}{self.docs_path}")
            return True
            
        except OSError as e:
            if "Address already in use" in str(e):
                app_logger.error(f"Port {self.port} already in use. Choose a different port.")
            else:
                app_logger.error(f"Failed to start web server: {e}")
            return False
        except Exception as e:
            app_logger.error(f"Unexpected error starting web server: {e}")
            return False
    
    def _run_server(self):
        """Run the HTTP server (called in background thread)."""
        try:
            app_logger.debug("Web server thread started")
            self.server.serve_forever()
        except Exception as e:
            app_logger.error(f"Web server error: {e}")
        finally:
            app_logger.debug("Web server thread stopped")
    
    def stop(self):
        """Stop the HTTP server."""
        if not self.running:
            return
        
        try:
            app_logger.info("Stopping web server...")
            self.running = False
            if self.server:
                self.server.shutdown()
                self.server.server_close()
            if self.server_thread:
                self.server_thread.join(timeout=2.0)
            app_logger.info("Web server stopped")
        except Exception as e:
            app_logger.error(f"Error stopping web server: {e}")
    
    def update_image(self, image_path, image_data_bytes, metadata=None, content_type='image/jpeg'):
        """
        Update the latest image to serve.

        If the image exceeds WEB_IMAGE_MAX_BYTES (5 MB), it is progressively
        downsized to fit within the limit before being served.

        Args:
            image_path: Path to the saved image file (for reference)
            image_data_bytes: Image data as bytes (JPEG or PNG)
            metadata: Optional dict with image metadata
            content_type: MIME type (default: 'image/jpeg')
        """
        if not self.running:
            return

        try:
            # Downsize if image exceeds the web endpoint size limit
            if len(image_data_bytes) > WEB_IMAGE_MAX_BYTES:
                result = self._downsize_image(image_data_bytes, content_type)
                if result is None:
                    # Downsize failed — keep serving the previous image
                    app_logger.warning("Web image over 5 MB and downsize failed, keeping previous image")
                    return
                image_data_bytes, content_type = result

            # PERF-002: Use centralized update method with ETag generation
            ImageHTTPHandler.update_image(
                image_data=image_data_bytes,
                content_type=content_type,
                path=image_path,
                metadata=metadata
            )
            app_logger.debug(f"Web server updated with new image: {os.path.basename(image_path)} ({len(image_data_bytes)} bytes, {content_type})")
        except Exception as e:
            app_logger.error(f"Error updating web server image: {e}")

    def update_capture_status(self, snapshot: dict):
        """Push the latest capture snapshot to the status endpoint.

        Safe to call even when the server isn't running (no-op); the app pushes
        on a timer and on capture state changes regardless of server state.
        """
        if not self.running:
            return
        ImageHTTPHandler.update_capture_status(snapshot)

    def register_capture_command_handler(self, handler):
        """Register the callable that executes a capture command.

        The inverse of update_capture_status(): status is *pushed* into the
        server, control is *pulled* back out through a handler the app owns.
        The server stays ignorant of capture either way.

        ``handler(command)`` is invoked on an HTTP request thread with
        ``'start'`` or ``'stop'``. It is the handler's job to marshal onto the
        thread that owns capture — QueuedConnection under the GUI, a direct
        call under HeadlessRunner — and to return promptly. Confirmation of the
        resulting state comes from the pushed snapshot, not the return value.
        """
        self._capture_command_handler = handler
        if self.server is not None:
            self.server.capture_command_handler = handler

    def set_control_token(self, token):
        """Set the bearer token required on control routes.

        Safe to call before or after start(). An empty token disables control
        (fail closed) rather than opening it.
        """
        self._control_token = token or ''
        if self.server is not None:
            self.server.control_token = self._control_token

    @staticmethod
    def _downsize_image(image_data_bytes: bytes, content_type: str):
        """Downscale an image to fit within WEB_IMAGE_MAX_BYTES.

        Estimates the initial scale from the ratio of target to actual file
        size (file size ~ pixel count, so scale = sqrt(target / actual)),
        then refines with a few extra passes if JPEG compression doesn't
        hit the estimate exactly.  Returns (new_bytes, new_content_type)
        on success, or None if the image could not be brought under the limit.
        """
        import math

        try:
            img = Image.open(io.BytesIO(image_data_bytes))
            if img.mode == 'RGBA':
                img = img.convert('RGB')

            original_size = len(image_data_bytes)

            # First pass: estimate scale from byte ratio
            # file_size ∝ width × height ∝ scale², so scale = sqrt(target / actual)
            # Use 0.85× target as headroom since JPEG isn't perfectly linear
            scale = math.sqrt((WEB_IMAGE_MAX_BYTES * 0.85) / original_size)
            scale = min(scale, 0.99)  # Always shrink at least a little

            for attempt in range(5):
                new_w = max(1, int(img.width * scale))
                new_h = max(1, int(img.height * scale))
                resized = img.resize((new_w, new_h), Image.LANCZOS)

                buf = io.BytesIO()
                resized.save(buf, format='JPEG', quality=90)
                result_size = buf.tell()

                if result_size <= WEB_IMAGE_MAX_BYTES:
                    app_logger.info(
                        f"Web image downsized: {original_size / (1024*1024):.1f} MB → "
                        f"{result_size / (1024*1024):.1f} MB "
                        f"({new_w}x{new_h}, attempt {attempt + 1})"
                    )
                    return buf.getvalue(), 'image/jpeg'

                # Refine: adjust scale based on how far off we are
                scale *= math.sqrt((WEB_IMAGE_MAX_BYTES * 0.85) / result_size)

            app_logger.warning("Web image still above 5 MB after downscale attempts")
            return None
        except Exception as e:
            app_logger.warning(f"Web image downsize failed: {e}")
            return None
    
    def get_url(self):
        """Get the full URL for the image endpoint."""
        if self.running and self.server:
            actual_port = self.server.server_port
            return f"http://{self.host}:{actual_port}{self.image_path}"
        return None
    
    def get_status_url(self):
        """Get the full URL for the status endpoint."""
        if self.running and self.server:
            actual_port = self.server.server_port
            return f"http://{self.host}:{actual_port}{self.status_path}"
        return None

    def get_docs_url(self):
        """Get the full URL for the human-readable API docs page."""
        if self.running and self.server:
            actual_port = self.server.server_port
            return f"http://{self.host}:{actual_port}{self.docs_path}"
        return None
