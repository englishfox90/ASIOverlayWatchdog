"""
Headless runner for PFR Sentinel
Runs camera capture without GUI for server/scheduled task deployments

Usage:
    python main.py --auto-start --headless                   # Run until Ctrl+C
    python main.py --auto-start --headless --auto-stop 3600  # Run for 1 hour
"""
import os
import io
import signal
import threading
import time
from datetime import datetime

from .logger import app_logger
from .config import Config
from .camera import ZWOCamera
from .camera.camera_utils import get_selected_camera_name
from .web_output import WebOutputServer
from .processor import add_overlays
from .cleanup import run_cleanup
from .library import ImageLibrary


class HeadlessRunner:
    """Runs camera capture without a GUI
    
    Loads config, initializes camera, captures images, and serves via webserver.
    Designed for background/server operation.
    """
    
    def __init__(self, auto_stop: int = None):
        """
        Args:
            auto_stop: Stop after this many seconds (None = run forever)
        """
        self.auto_stop = auto_stop
        self.running = False
        self.config = Config()
        self.zwo_camera = None
        self.web_server = None
        self.image_library = None
        self.image_count = 0
        self._last_capture_epoch = None  # Unix ts of last successful frame (for /status)
        self._last_error = None          # Most recent capture error (for /status health)
        self._last_webserver_retry = 0.0  # Throttles web-server bind re-attempts
        self._shutdown_event = threading.Event()
        
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals (Ctrl+C, kill)"""
        app_logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.stop()
    
    def _log(self, message: str):
        """Log message to app logger"""
        app_logger.info(message)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
    
    def start(self):
        """Start headless capture"""
        self._log("=" * 60)
        self._log("PFR Sentinel - Headless Mode")
        self._log("=" * 60)
        
        try:
            # Load configuration
            self._log("Loading configuration...")
            self._load_config()

            # Rolling image library — archives downscaled frames off the hot
            # path and backs the /library endpoints. Start before the web server
            # so it can be handed in. enqueue() no-ops while library.enabled is
            # false, so this is safe to start unconditionally.
            self.image_library = ImageLibrary(lambda: self.config.data)
            self.image_library.start()

            # Start web server if configured
            if self.config.get('output', {}).get('mode') == 'webserver':
                self._start_webserver()
            
            # Initialize camera
            self._log("Initializing camera...")
            if not self._init_camera():
                self._log("ERROR: Failed to initialize camera")
                return False
            
            # Start capture loop
            self.running = True
            self._log(f"Starting capture loop (interval: {self.config.get('zwo_interval', 5.0)}s)")
            
            if self.auto_stop and self.auto_stop > 0:
                self._log(f"Auto-stop scheduled in {self.auto_stop} seconds")
                # Schedule auto-stop
                threading.Timer(self.auto_stop, self.stop).start()
            else:
                self._log("Running until Ctrl+C or kill signal...")
            
            self._capture_loop()
            
            return True
            
        except Exception as e:
            self._log(f"ERROR: {e}")
            import traceback
            self._log(traceback.format_exc())
            return False
        finally:
            self._cleanup()
    
    def stop(self):
        """Stop headless capture"""
        self._log("Stopping capture...")
        self.running = False
        self._shutdown_event.set()
    
    def _load_config(self):
        """Load and validate configuration"""
        self.config.load()

        cam_name = get_selected_camera_name(self.config)
        profile = self._active_profile()

        # Log key settings
        self._log(f"  SDK Path: {self.config.get('zwo_sdk_path')}")
        self._log(f"  Camera: {cam_name or 'Default'}")
        self._log(f"  Exposure: {profile.get('exposure_ms', 100)}ms")
        self._log(f"  Gain: {profile.get('gain', 100)}")
        self._log(f"  Interval: {self.config.get('zwo_interval', 5.0)}s")
        self._log(f"  Output Mode: {self.config.get('output', {}).get('mode', 'file')}")
        self._log(f"  Output Dir: {self.config.get('output_directory')}")

    def _active_profile(self) -> dict:
        """Return the active camera's profile, or DEFAULT_CAMERA_PROFILE if no camera selected."""
        from services.config import DEFAULT_CAMERA_PROFILE
        cam_name = get_selected_camera_name(self.config)
        if not cam_name:
            return dict(DEFAULT_CAMERA_PROFILE)
        return self.config.get_camera_profile(cam_name) or dict(DEFAULT_CAMERA_PROFILE)
    
    # Minimum seconds between web-server bind re-attempts.
    _WEBSERVER_RETRY_SEC = 15.0

    def _webserver_mode_enabled(self) -> bool:
        return self.config.get('output', {}).get('mode') == 'webserver'

    def _ensure_webserver(self):
        """Re-attempt a failed web-server bind from the capture loop.

        At logon autostart the configured bind address (a Tailscale/LAN IP)
        may not be up on any interface yet, so the initial start in start()
        fails. Without this, web output stays off for the whole session even
        though capture and file output keep working. Throttled so a persistent
        failure doesn't re-attempt (and re-log) on every frame.
        """
        if not self._webserver_mode_enabled():
            return
        if self.web_server and self.web_server.running:
            return
        if (time.time() - self._last_webserver_retry) < self._WEBSERVER_RETRY_SEC:
            return
        self._log("Retrying web server start...")
        self._start_webserver()

    def _start_webserver(self):
        """Start web server for image output"""
        # Stamp every attempt so the loop's retry throttle counts from here,
        # whether this is the initial start or a re-attempt.
        self._last_webserver_retry = time.time()
        output_config = self.config.get('output', {})

        host = output_config.get('webserver_host', '127.0.0.1')
        port = output_config.get('webserver_port', 8080)
        image_path = output_config.get('webserver_path', '/latest')
        status_path = output_config.get('webserver_status_path', '/status')
        docs_path = output_config.get('webserver_docs_path', '/docs')
        library_path = output_config.get('webserver_library_path', '/library')

        self._log(f"Starting web server on {host}:{port}...")

        self.web_server = WebOutputServer(
            host, port, image_path, status_path, docs_path,
            library_path=library_path, image_library=self.image_library,
        )
        if self.web_server.start():
            self._log(f"✓ Web server running: {self.web_server.get_url()}")
            self._log(f"  Status endpoint: {self.web_server.get_status_url()}")
        else:
            self._log("⚠ Failed to start web server")
            self.web_server = None
    
    def _init_camera(self) -> bool:
        """Initialize ZWO camera"""
        try:
            sdk_path = self.config.get('zwo_sdk_path')
            if not sdk_path or not os.path.exists(sdk_path):
                self._log(f"ERROR: SDK not found at: {sdk_path}")
                return False
            
            # Get camera settings from the active camera's profile.
            from services.config import DEFAULT_CAMERA_PROFILE
            profile = self._active_profile()
            exposure_ms = profile.get('exposure_ms', DEFAULT_CAMERA_PROFILE['exposure_ms'])
            exposure_sec = exposure_ms / 1000.0

            self.zwo_camera = ZWOCamera(
                sdk_path=sdk_path,
                camera_index=self.config.get('zwo_selected_camera', 0),
                camera_name=get_selected_camera_name(self.config),
                camera_serial=self.config.get('zwo_selected_camera_serial', ''),
                exposure_sec=exposure_sec,
                gain=profile.get('gain', DEFAULT_CAMERA_PROFILE['gain']),
                white_balance_r=profile.get('wb_r', DEFAULT_CAMERA_PROFILE['wb_r']),
                white_balance_b=profile.get('wb_b', DEFAULT_CAMERA_PROFILE['wb_b']),
                offset=profile.get('offset', DEFAULT_CAMERA_PROFILE['offset']),
                flip=profile.get('flip', DEFAULT_CAMERA_PROFILE['flip']),
                auto_exposure=self.config.get('zwo_auto_exposure', False),
                max_exposure_sec=profile.get('max_exposure_ms', DEFAULT_CAMERA_PROFILE['max_exposure_ms']) / 1000.0,
                bayer_pattern=profile.get('bayer_pattern', DEFAULT_CAMERA_PROFILE['bayer_pattern']),
                wb_mode=self.config.get('white_balance', {}).get('mode', 'asi_auto'),
                wb_config=self.config.get('white_balance', {}),
                scheduled_capture_mode=self.config.get('scheduled_capture_mode', 'always'),
                scheduled_start_time=self.config.get('scheduled_start_time', '17:00'),
                scheduled_end_time=self.config.get('scheduled_end_time', '09:00'),
                scheduled_window_interval=self.config.get('scheduled_window_interval', 5.0)
            )
            
            # Set capture interval
            self.zwo_camera.capture_interval = self.config.get('zwo_interval', 5.0)
            
            # Set logging callback
            self.zwo_camera.on_log_callback = lambda msg: app_logger.info(msg)
            
            # Initialize SDK and connect
            if not self.zwo_camera.initialize_sdk():
                self._log("ERROR: Failed to initialize ZWO SDK")
                return False
            
            cameras = self.zwo_camera.detect_cameras()
            if not cameras:
                self._log("ERROR: No cameras detected")
                return False
            
            self._log(f"Found {len(cameras)} camera(s): {cameras}")
            
            # Connect to configured camera
            camera_index = self.config.get('zwo_selected_camera', 0)
            if camera_index >= len(cameras):
                camera_index = 0
            
            if not self.zwo_camera.connect_camera(camera_index):
                self._log(f"ERROR: Failed to connect to camera {camera_index}")
                return False

            # Persist the serial learned on connect so it survives a restart and
            # can reject the wrong camera if the index later shifts.
            from services.camera.camera_identity import persist_camera_serial
            serial = getattr(self.zwo_camera, 'camera_serial', None)
            if persist_camera_serial(self.config, serial):
                self._log(f"Persisted camera serial: {serial}")

            self._log(f"✓ Connected to camera: {cameras[camera_index]}")
            return True
            
        except Exception as e:
            self._log(f"ERROR initializing camera: {e}")
            import traceback
            self._log(traceback.format_exc())
            return False
    
    def _capture_loop(self):
        """Main capture loop"""
        while self.running and not self._shutdown_event.is_set():
            try:
                # Self-heal a web server that failed its initial bind (e.g. the
                # Tailscale/LAN IP wasn't up yet at logon autostart).
                self._ensure_webserver()

                # Check scheduled capture window
                if not self.zwo_camera.is_within_scheduled_window():
                    self._log("Outside scheduled capture window, waiting...")
                    self._push_capture_status(running=True, state="outside_window")
                    self._shutdown_event.wait(60)  # Check every minute
                    continue

                # Capture frame
                start_time = time.time()
                img, metadata = self.zwo_camera.capture_single_frame()
                capture_time = time.time() - start_time

                # Process and save
                self._process_and_save(img, metadata)
                process_time = time.time() - start_time - capture_time

                self.image_count += 1
                self._last_capture_epoch = time.time()
                self._last_error = None
                self._log(f"Frame {self.image_count}: {metadata.get('FILENAME', 'unknown')} "
                         f"(capture: {capture_time:.2f}s, process: {process_time:.2f}s)")
                self._push_capture_status(running=True, state="capturing")

                # Run cleanup if enabled
                self._run_cleanup()

                # Wait for next interval (honours variable-rate schedules)
                elapsed = time.time() - start_time
                wait_time = max(0, self.zwo_camera.effective_capture_interval - elapsed)
                if wait_time > 0:
                    self._shutdown_event.wait(wait_time)

            except Exception as e:
                self._log(f"ERROR in capture loop: {e}")
                import traceback
                self._log(traceback.format_exc())
                self._last_error = str(e)
                self._push_capture_status(running=False, state="error")
                # Wait before retrying
                self._shutdown_event.wait(5)

    def _push_capture_status(self, *, running: bool, state: str):
        """Push the current capture snapshot to the web server (headless)."""
        if not self.web_server or not self.web_server.running:
            return
        try:
            from services import api_status

            sched_mode = self.config.get('scheduled_capture_mode', 'always')
            in_window = True
            if sched_mode != 'always':
                try:
                    in_window = self.zwo_camera.is_in_time_window()
                except Exception:
                    in_window = True
            schedule = {
                "mode": sched_mode,
                "start_time": self.config.get('scheduled_start_time', '17:00'),
                "end_time": self.config.get('scheduled_end_time', '09:00'),
                "in_window": in_window,
                "window_interval_seconds": (
                    self.config.get('scheduled_window_interval', 5.0)
                    if sched_mode == 'variable' else None
                ),
            }
            interval = self.config.get('zwo_interval', 5.0)
            try:
                effective_interval = self.zwo_camera.effective_capture_interval
            except Exception:
                effective_interval = interval

            snapshot = api_status.build_capture_snapshot(
                mode="camera", enabled=True, running=running, state=state,
                interval_seconds=interval, effective_interval_seconds=effective_interval,
                schedule=schedule,
                last_capture_epoch=getattr(self, '_last_capture_epoch', None),
                last_error=getattr(self, '_last_error', None),
            )
            self.web_server.update_capture_status(snapshot)
        except Exception as e:
            self._log(f"Error pushing capture status: {e}")
    
    def _process_and_save(self, img, metadata):
        """Process image with overlays and save/publish"""
        from PIL import Image
        
        try:
            # Apply resize if configured
            resize_percent = self.config.get('resize_percent', 100)
            if resize_percent < 100:
                new_size = (
                    int(img.width * resize_percent / 100),
                    int(img.height * resize_percent / 100)
                )
                img = img.resize(new_size, Image.LANCZOS)
            
            # Add overlays
            overlays = self.config.get('overlays', [])
            if overlays:
                img = add_overlays(img, overlays, metadata)
            
            # Generate filename
            output_dir = self.config.get('output_directory')
            os.makedirs(output_dir, exist_ok=True)
            
            filename_pattern = self.config.get('filename_pattern', 'latestImage')
            output_format = self.config.get('output_format', 'jpg').lower()
            
            # Replace tokens in filename
            filename = filename_pattern
            filename = filename.replace('{timestamp}', datetime.now().strftime('%Y%m%d_%H%M%S'))
            filename = filename.replace('{session}', datetime.now().strftime('%Y-%m-%d'))
            
            output_path = os.path.join(output_dir, f"{filename}.{output_format}")
            
            # Save image
            if output_format in ('jpg', 'jpeg'):
                quality = self.config.get('jpg_quality', 85)
                img.save(output_path, 'JPEG', quality=quality, optimize=True)
            else:
                img.save(output_path, 'PNG', optimize=True)
            
            # Archive a downscaled copy to the rolling image library (non-blocking).
            if self.image_library:
                self.image_library.enqueue(img, metadata)

            # Push to web server if running
            if self.web_server and self.web_server.running:
                img_bytes = io.BytesIO()
                if output_format in ('jpg', 'jpeg'):
                    img.save(img_bytes, format='JPEG', quality=self.config.get('jpg_quality', 85))
                    content_type = 'image/jpeg'
                else:
                    img.save(img_bytes, format='PNG')
                    content_type = 'image/png'
                
                self.web_server.update_image(output_path, img_bytes.getvalue(), content_type=content_type)
            
        except Exception as e:
            self._log(f"ERROR processing image: {e}")
            import traceback
            self._log(traceback.format_exc())
    
    def _run_cleanup(self):
        """Run cleanup if enabled"""
        if self.config.get('cleanup_enabled', False):
            try:
                run_cleanup(self.config.data)
            except Exception as e:
                self._log(f"Cleanup error: {e}")
    
    def _cleanup(self):
        """Cleanup resources on shutdown"""
        self._log("Cleaning up resources...")
        
        try:
            if self.zwo_camera:
                self.zwo_camera.disconnect_camera()
                self._log("Camera disconnected")
        except Exception as e:
            self._log(f"Error disconnecting camera: {e}")
        
        try:
            if self.web_server:
                self.web_server.stop()
                self._log("Web server stopped")
        except Exception as e:
            self._log(f"Error stopping web server: {e}")

        try:
            if self.image_library:
                self.image_library.stop()
                self._log("Image library stopped")
        except Exception as e:
            self._log(f"Error stopping image library: {e}")
        
        self._log(f"Headless session complete. Captured {self.image_count} images.")
        self._log("=" * 60)


def run_headless(auto_stop: int = None) -> bool:
    """
    Run PFR Sentinel in headless mode
    
    Args:
        auto_stop: Stop after this many seconds (None = run forever)
    
    Returns:
        True if completed successfully, False on error
    """
    runner = HeadlessRunner(auto_stop=auto_stop)
    return runner.start()
