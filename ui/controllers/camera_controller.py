"""
Camera Controller for Qt UI
Adapter between PySide6 UI and existing ZWO camera service.

Uses ZWOCamera.start_capture() with callbacks - NO reimplementation of capture logic.
All auto-exposure, calibration, scheduled windows, etc. are handled by ZWOCamera.
"""
from PySide6.QtCore import QObject, Signal
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.logger import app_logger
from services.zwo_camera import ZWOCamera


class CameraControllerQt(QObject):
    """
    Qt-compatible camera controller.
    
    Uses existing ZWOCamera.start_capture() with callbacks.
    All capture logic (auto-exposure, calibration, etc.) is handled by ZWOCamera.
    """
    
    cameras_detected = Signal(list)  # List of camera names
    capture_started = Signal()
    capture_stopped = Signal()
    frame_ready = Signal(object, dict)  # PIL Image, metadata
    error = Signal(str)
    calibration_status = Signal(bool)  # True=calibrating, False=complete
    
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.config = main_window.config
        
        self.zwo_camera = None
        self.is_connected = False
        self.is_capturing = False
    
    def detect_cameras(self):
        """Detect connected ZWO cameras"""
        app_logger.info("Detecting cameras...")
        
        sdk_path = self.config.get('zwo_sdk_path', '')
        
        if not sdk_path or not os.path.exists(sdk_path):
            self.error.emit("SDK path not found")
            return
        
        try:
            import zwoasi as asi
            
            try:
                asi.init(sdk_path)
            except Exception as e:
                if "already" not in str(e).lower():
                    self.error.emit(f"SDK init failed: {e}")
                    return
            
            num_cameras = asi.get_num_cameras()
            
            if num_cameras == 0:
                self.cameras_detected.emit([])
                return
            
            camera_list = []
            for i in range(num_cameras):
                try:
                    name = asi.list_cameras()[i]
                    camera_list.append(f"{name} (Index: {i})")
                except:
                    camera_list.append(f"Camera {i}")
            
            self.cameras_detected.emit(camera_list)
            app_logger.info(f"Detected {len(camera_list)} camera(s)")
            
        except Exception as e:
            self.error.emit(f"Detection failed: {e}")
            app_logger.error(f"Camera detection failed: {e}")
    
    def start_capture(self):
        """Start camera capture using ZWOCamera's built-in capture loop"""
        if self.is_capturing:
            return
        
        try:
            sdk_path = self.config.get('zwo_sdk_path', '')
            camera_index = self.config.get('zwo_selected_camera', 0)
            
            # Get settings from config
            exposure_ms = self.config.get('zwo_exposure_ms', 100.0)
            exposure_sec = exposure_ms / 1000.0
            gain = self.config.get('zwo_gain', 100)
            auto_exposure = self.config.get('zwo_auto_exposure', False)
            
            app_logger.debug(f"Camera config: exposure_ms={exposure_ms}, gain={gain}, auto_exposure={auto_exposure}")
            
            # Initialize camera with all settings
            self.zwo_camera = ZWOCamera(
                sdk_path=sdk_path,
                camera_index=camera_index,
                exposure_sec=exposure_sec,
                gain=gain,
                white_balance_r=self.config.get('zwo_wb_r', 75),
                white_balance_b=self.config.get('zwo_wb_b', 99),
                offset=self.config.get('zwo_offset', 20),
                flip=self.config.get('zwo_flip', 0),
                auto_exposure=auto_exposure,
                max_exposure_sec=self.config.get('zwo_max_exposure_ms', 30000.0) / 1000.0,
                bayer_pattern=self.config.get('zwo_bayer_pattern', 'BGGR'),
                scheduled_capture_enabled=self.config.get('scheduled_capture_enabled', False),
                scheduled_start_time=self.config.get('scheduled_start_time', '17:00'),
                scheduled_end_time=self.config.get('scheduled_end_time', '09:00'),
            )
            
            # Set target brightness and interval
            self.zwo_camera.target_brightness = self.config.get('zwo_target_brightness', 100)
            self.zwo_camera.set_capture_interval(self.config.get('zwo_interval', 5.0))
            
            # Set error callback for disconnect recovery
            self.zwo_camera.on_error_callback = self._on_camera_error
            
            # Set calibration callback for status updates
            self.zwo_camera.on_calibration_callback = self._on_calibration_status
            
            # Connect to camera
            if not self.zwo_camera.connect_camera(camera_index):
                raise Exception("Failed to connect to camera")
            
            self.is_connected = True
            
            # Start capture using ZWOCamera's built-in capture loop with callbacks
            # This runs in its own thread inside ZWOCamera and handles:
            # - Auto-exposure calibration
            # - Scheduled capture windows
            # - Error recovery and reconnection
            app_logger.info("Starting capture loop...")
            self.zwo_camera.start_capture(
                on_frame_callback=self._on_frame_captured,
                on_log_callback=lambda msg: app_logger.info(msg)
            )
            
            self.is_capturing = True
            self.capture_started.emit()
            app_logger.info("Camera capture started")
            
        except Exception as e:
            self.error.emit(str(e))
            app_logger.error(f"Failed to start capture: {e}")
            import traceback
            app_logger.debug(f"Stack trace: {traceback.format_exc()}")
    
    def stop_capture(self):
        """Stop camera capture"""
        if not self.is_capturing:
            return
        
        try:
            # Update state immediately
            self.is_capturing = False
            self.is_connected = False
            
            # Stop capture using ZWOCamera's method (non-blocking)
            if self.zwo_camera:
                self.zwo_camera.stop_capture()
                # Disconnect in background to avoid blocking UI
                import threading
                def disconnect():
                    try:
                        self.zwo_camera.disconnect_camera()
                    except Exception as e:
                        app_logger.debug(f"Error disconnecting camera: {e}")
                threading.Thread(target=disconnect, daemon=True).start()
                self.zwo_camera = None
            
            self.capture_stopped.emit()
            app_logger.info("Camera capture stopped")
            
        except Exception as e:
            app_logger.error(f"Error stopping capture: {e}")
    
    def _on_frame_captured(self, pil_image, metadata):
        """Callback from ZWOCamera when a frame is captured.
        
        This is called from the ZWOCamera's capture thread.
        We emit a Qt signal to safely update the UI.
        """
        # Add UI-specific metadata fields
        if metadata is None:
            metadata = {}
        metadata['filename'] = f"capture_{datetime.now().strftime('%H%M%S')}.jpg"
        metadata['timestamp'] = datetime.now().strftime('%H:%M:%S')
        
        # Emit signal (thread-safe way to update Qt UI)
        self.frame_ready.emit(pil_image, metadata)
        
        # Also notify main window directly
        if self.main_window:
            self.main_window.on_image_captured(pil_image, metadata)
    
    def _on_camera_error(self, error_msg):
        """Callback from ZWOCamera on errors"""
        app_logger.error(f"Camera error: {error_msg}")
        self.error.emit(error_msg)
    
    def _on_calibration_status(self, is_calibrating: bool):
        """Callback from ZWOCamera when calibration status changes
        
        Args:
            is_calibrating: True when calibration starts, False when complete
        """
        self.calibration_status.emit(is_calibrating)
    
    def update_settings(self):
        """Update camera settings from config (live update)"""
        if not self.zwo_camera:
            return
        
        try:
            # Update exposure
            exposure_ms = self.config.get('zwo_exposure_ms', 100.0)
            self.zwo_camera.set_exposure(exposure_ms / 1000.0)
            
            # Update gain
            self.zwo_camera.set_gain(self.config.get('zwo_gain', 100))
            
            # Update auto-exposure settings
            self.zwo_camera.auto_exposure = self.config.get('zwo_auto_exposure', False)
            self.zwo_camera.target_brightness = self.config.get('zwo_target_brightness', 100)
            self.zwo_camera.max_exposure_sec = self.config.get('zwo_max_exposure_ms', 30000.0) / 1000.0
            
        except Exception as e:
            app_logger.error(f"Failed to update camera settings: {e}")
