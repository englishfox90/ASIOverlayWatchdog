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
from .zwo_camera import ZWOCamera
from .web_output import WebOutputServer
from .processor import add_overlays
from .cleanup import run_cleanup


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
        self.image_count = 0
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
        
        # Log key settings
        self._log(f"  SDK Path: {self.config.get('zwo_sdk_path')}")
        self._log(f"  Camera: {self.config.get('zwo_camera_name', 'Default')}")
        self._log(f"  Exposure: {self.config.get('zwo_exposure_ms', 100)}ms")
        self._log(f"  Gain: {self.config.get('zwo_gain', 100)}")
        self._log(f"  Interval: {self.config.get('zwo_interval', 5.0)}s")
        self._log(f"  Output Mode: {self.config.get('output', {}).get('mode', 'file')}")
        self._log(f"  Output Dir: {self.config.get('output_directory')}")
    
    def _start_webserver(self):
        """Start web server for image output"""
        output_config = self.config.get('output', {})
        
        host = output_config.get('webserver_host', '127.0.0.1')
        port = output_config.get('webserver_port', 8080)
        image_path = output_config.get('webserver_path', '/latest')
        status_path = output_config.get('webserver_status_path', '/status')
        
        self._log(f"Starting web server on {host}:{port}...")
        
        self.web_server = WebOutputServer(host, port, image_path, status_path)
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
            
            # Get camera settings from config
            exposure_ms = self.config.get('zwo_exposure_ms', 100.0)
            exposure_sec = exposure_ms / 1000.0
            
            self.zwo_camera = ZWOCamera(
                sdk_path=sdk_path,
                camera_index=self.config.get('zwo_selected_camera', 0),
                camera_name=self.config.get('zwo_camera_name'),
                exposure_sec=exposure_sec,
                gain=self.config.get('zwo_gain', 100),
                white_balance_r=self.config.get('zwo_wb_r', 75),
                white_balance_b=self.config.get('zwo_wb_b', 99),
                offset=self.config.get('zwo_offset', 20),
                flip=self.config.get('zwo_flip', 0),
                auto_exposure=self.config.get('zwo_auto_exposure', False),
                max_exposure_sec=self.config.get('zwo_max_exposure_ms', 30000) / 1000.0,
                bayer_pattern=self.config.get('zwo_bayer_pattern', 'BGGR'),
                wb_mode=self.config.get('white_balance', {}).get('mode', 'asi_auto'),
                wb_config=self.config.get('white_balance', {}),
                scheduled_capture_enabled=self.config.get('scheduled_capture_enabled', False),
                scheduled_start_time=self.config.get('scheduled_start_time', '17:00'),
                scheduled_end_time=self.config.get('scheduled_end_time', '09:00')
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
            
            self._log(f"✓ Connected to camera: {cameras[camera_index]}")
            return True
            
        except Exception as e:
            self._log(f"ERROR initializing camera: {e}")
            import traceback
            self._log(traceback.format_exc())
            return False
    
    def _capture_loop(self):
        """Main capture loop"""
        interval = self.config.get('zwo_interval', 5.0)
        
        while self.running and not self._shutdown_event.is_set():
            try:
                # Check scheduled capture window
                if not self.zwo_camera.is_within_scheduled_window():
                    self._log("Outside scheduled capture window, waiting...")
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
                self._log(f"Frame {self.image_count}: {metadata.get('FILENAME', 'unknown')} "
                         f"(capture: {capture_time:.2f}s, process: {process_time:.2f}s)")
                
                # Run cleanup if enabled
                self._run_cleanup()
                
                # Wait for next interval
                elapsed = time.time() - start_time
                wait_time = max(0, interval - elapsed)
                if wait_time > 0:
                    self._shutdown_event.wait(wait_time)
                    
            except Exception as e:
                self._log(f"ERROR in capture loop: {e}")
                import traceback
                self._log(traceback.format_exc())
                # Wait before retrying
                self._shutdown_event.wait(5)
    
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
