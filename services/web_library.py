"""
HTTP handlers for the image library endpoints.

Kept out of ``web_output.py`` so that module stays focused on the core
image/status server (and under the per-file size cap). These functions take the
active ``BaseHTTPRequestHandler`` plus the ``ImageLibrary`` and write the
response directly — the routing/gating lives in ``ImageHTTPHandler.do_GET``.
"""
import json
from datetime import datetime

from .logger import app_logger


def parse_time_param(values):
    """Parse a since/until query value (epoch seconds or ISO 8601) to int epoch."""
    if not values:
        return None
    raw = values[0]
    try:
        return int(float(raw))
    except (TypeError, ValueError, OverflowError):
        # OverflowError: float('inf')/'-inf' parses but int() overflows.
        pass
    try:
        return int(datetime.fromisoformat(raw).timestamp())
    except (TypeError, ValueError):
        return None


def _int_param(values, default):
    try:
        return int(values[0])
    except (TypeError, ValueError, IndexError):
        return default


def _write_cors(handler, with_etag=False):
    """Emit the standard CORS headers shared by the library responses."""
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
    handler.send_header(
        "Access-Control-Allow-Headers",
        "Content-Type, If-None-Match" if with_etag else "Content-Type",
    )


def serve_list(handler, library, library_path, query_params):
    """Serve the paginated library manifest as JSON."""
    try:
        since = parse_time_param(query_params.get('since'))
        until = parse_time_param(query_params.get('until'))
        limit = _int_param(query_params.get('limit'), 100)
        offset = _int_param(query_params.get('offset'), 0)

        total, rows = library.list_images(since=since, until=until, limit=limit, offset=offset)
        images = [
            {**r, 'url': f"{library_path}/image?id={r['id']}"}
            for r in rows
        ]
        payload = json.dumps({
            "total": total,
            "limit": max(1, min(limit, library.MAX_PAGE)),
            "offset": max(0, offset),
            "images": images,
        }, indent=2).encode('utf-8')

        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", len(payload))
        handler.send_header("Cache-Control", "no-cache")
        _write_cors(handler)
        handler.end_headers()
        handler.wfile.write(payload)
    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
        pass
    except Exception as e:
        app_logger.error(f"Error serving library list: {e}")


def serve_image(handler, library, query_params):
    """Serve one archived library image by id, with ETag caching."""
    try:
        id_values = query_params.get('id')
        if not id_values:
            handler.send_error(400, "Missing required 'id' query parameter")
            return
        image_id = _int_param(id_values, None)
        if image_id is None:
            handler.send_error(400, "'id' must be an integer")
            return

        # Answer conditional requests from the index alone — a 304 never touches
        # the JPEG on disk.
        etag = library.image_etag(image_id)
        if etag is None:
            handler.send_error(404, f"No library image with id {image_id}")
            return

        client_etag = handler.headers.get('If-None-Match')
        if client_etag and client_etag == etag:
            handler.send_response(304)
            handler.send_header("ETag", etag)
            handler.send_header("Access-Control-Allow-Origin", "*")
            handler.end_headers()
            return

        result = library.read_image(image_id)
        if result is None:
            # File vanished between the index lookup and the read.
            handler.send_error(404, f"No library image with id {image_id}")
            return
        data, etag = result

        handler.send_response(200)
        handler.send_header("Content-Type", "image/jpeg")
        handler.send_header("Content-Length", len(data))
        handler.send_header("ETag", etag)
        # Archived frames are immutable, so the bytes for an id never change.
        handler.send_header("Cache-Control", "public, max-age=31536000, immutable")
        _write_cors(handler, with_etag=True)
        handler.end_headers()
        handler.wfile.write(data)
    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
        pass
    except Exception as e:
        app_logger.error(f"Error serving library image: {e}")
