"""
ZWO ASI Camera capture module
Provides interface to capture images from ZWO cameras using the ASI SDK

This is the main public interface. Connection management is delegated to
camera_connection.py, calibration to camera_calibration.py.
"""
import time
import threading
import numpy as np
from datetime import datetime
from PIL import Image
from .camera_utils import (
    simple_debayer_rggb, 
    is_within_scheduled_window as check_scheduled_window,
    debayer_raw_image,
    apply_white_balance,
    calculate_image_stats
)
from .camera_calibration import CameraCalibration
from .camera_connection import CameraConnection


class ZWOCamera:
    """Interface to ZWO ASI camera using zwoasi library"""
    
    def __init__(self, sdk_path=None, camera_index=0, exposure_sec=1.0, gain=100,
                 white_balance_r=75, white_balance_b=99, offset=20, flip=0,
                 auto_exposure=False, max_exposure_sec=30.0, auto_wb=False,
                 wb_mode='asi_auto', wb_config=None, bayer_pattern='BGGR',
                 scheduled_capture_enabled=False, scheduled_start_time="17:00",
                 scheduled_end_time="09:00", status_callback=None, camera_name=None,
                 config_callback=None):
        # Initialize connection manager (delegates SDK/connection logic)
        self._connection = CameraConnection(sdk_path=sdk_path, logger=self.log)
        self._connection.config_callback = config_callback
        self._connection.camera_name = camera_name
        self._connection.camera_index = camera_index
        
        # Legacy attribute aliases (for backward compatibility)
        self.sdk_path = sdk_path
        self.camera_index = camera_index
        self.camera_name = camera_name
        self.config_callback = config_callback
        
        # Capture state
        self.is_capturing = False
        self.capture_thread = None
        self.on_frame_callback = None
        self.on_log_callback = None
        self.status_callback = status_callback  # Callback for schedule status updates
        
        # Capture settings
        self.exposure_seconds = exposure_sec
        self.gain = gain
        self.capture_interval = 5.0  # Seconds between captures
        self.auto_exposure = auto_exposure
        self.max_exposure = max_exposure_sec  # Max exposure for auto mode
        self.target_brightness = 100  # Target brightness for auto exposure
        self.exposure_algorithm = 'percentile'  # 'mean', 'median', or 'percentile'
        self.exposure_percentile = 75  # Use 75th percentile (focuses on brighter areas)
        self.clipping_threshold = 245  # Consider pixels > this value as clipped
        self.clipping_prevention = True  # Prevent further exposure increase if clipping detected
        self.white_balance_r = white_balance_r
        self.white_balance_b = white_balance_b
        self.auto_wb = auto_wb
        self.wb_mode = wb_mode  # 'asi_auto', 'manual', or 'gray_world'
        self.wb_config = wb_config if wb_config else {'mode': wb_mode}  # Full WB config
        self.flip = flip  # 0=none, 1=horizontal, 2=vertical, 3=both
        self.offset = offset
        self.bayer_pattern = bayer_pattern  # RGGB, BGGR, GRBG, GBRG
        self.use_raw16 = False  # Use RAW16 mode for full bit depth (set by dev mode)
        
        # Scheduled capture settings
        self.scheduled_capture_enabled = scheduled_capture_enabled
        self.scheduled_start_time = scheduled_start_time  # Format: "HH:MM"
        self.scheduled_end_time = scheduled_end_time      # Format: "HH:MM"
        
        # Exposure tracking for UI
        self.exposure_start_time = None
        self.exposure_remaining = 0.0
        
        # Rapid calibration mode
        self.calibration_mode = False  # Fast convergence before normal capture
        self.calibration_complete = False
        
        # Initialize calibration manager
        self.calibration_manager = None  # Will be initialized after camera connection
    
    # =========================================================================
    # Property aliases for backward compatibility (delegate to connection manager)
    # =========================================================================
    
    @property
    def camera(self):
        """Camera instance (delegated to connection manager)"""
        return self._connection.camera
    
    @camera.setter
    def camera(self, value):
        """Set camera instance"""
        self._connection.camera = value
    
    @property
    def asi(self):
        """ASI SDK instance (delegated to connection manager)"""
        return self._connection.asi
    
    @asi.setter
    def asi(self, value):
        """Set ASI SDK instance"""
        self._connection.asi = value
    
    @property
    def cameras(self):
        """List of detected cameras"""
        return self._connection.cameras
    
    @cameras.setter
    def cameras(self, value):
        """Set cameras list"""
        self._connection.cameras = value
    
    @property
    def supports_raw16(self) -> bool:
        """Whether camera supports RAW16 mode (delegated to connection manager)"""
        return self._connection.supports_raw16
    
    @property
    def sensor_bit_depth(self) -> int:
        """Camera's native ADC bit depth (delegated to connection manager)"""
        return self._connection.bit_depth
    
    @property
    def camera_info(self) -> dict:
        """Camera properties dict (delegated to connection manager)"""
        return self._connection.camera_info
    
    @property
    def current_bit_depth(self) -> int:
        """Current capture bit depth (8 for RAW8, 16 for RAW16)"""
        return self._connection.current_bit_depth
    
    def __del__(self):
        """Destructor to ensure camera is disconnected when object is destroyed"""
        try:
            self.disconnect_camera()
        except Exception:
            pass  # Ignore errors during cleanup in destructor
    
    def __enter__(self):
        """Context manager entry - allows use with 'with' statement"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures cleanup even if exception occurs"""
        self.disconnect_camera()
        return False  # Don't suppress exceptions
        
    def log(self, message):
        """Send log message via callback"""
        if self.on_log_callback:
            self.on_log_callback(message)
        print(message)
    
    def is_within_scheduled_window(self):
        """
        Check if current time is within the scheduled capture window.
        Handles overnight captures (e.g., 17:00 - 09:00).
        Returns True if scheduled capture is disabled or if within window.
        """
        return check_scheduled_window(
            self.scheduled_capture_enabled,
            self.scheduled_start_time,
            self.scheduled_end_time
        )
    
    def initialize_sdk(self):
        """Initialize the ZWO ASI SDK (delegates to connection manager)"""
        # Update connection manager's logger to use our log method
        self._connection._logger = self.log
        return self._connection.initialize_sdk()
    
    def reset_sdk_completely(self):
        """
        Completely reset the SDK state (nuclear option).
        Delegates to connection manager.
        """
        return self._connection.reset_sdk_completely()
    
    def detect_cameras(self):
        """Detect connected ZWO cameras (delegates to connection manager)"""
        return self._connection.detect_cameras()
    
    def reconnect_camera_safe(self):
        """
        Safely reconnect to camera by re-detecting available cameras first.
        Delegates to connection manager, but handles calibration manager init.
        
        IMPORTANT: This passes current camera settings to ensure ROI and other
        settings are properly restored after reconnection. Without this, the
        camera may capture at wrong resolution causing reshape errors.
        """
        # Build settings dict from current properties to restore after reconnection
        settings = {
            'gain': self.gain,
            'exposure_sec': self.exposure_seconds,
            'wb_r': self.white_balance_r,
            'wb_b': self.white_balance_b,
            'wb_mode': self.wb_mode,
            'offset': self.offset,
            'flip': self.flip,
            'use_raw16': self.use_raw16,  # Preserve RAW16 mode after reconnection
        }
        
        success = self._connection.reconnect_safe(
            target_camera_name=self.camera_name,
            settings=settings
        )
        
        if success:
            # Sync camera_name and camera_index from connection manager
            self.camera_name = self._connection.camera_name
            self.camera_index = self._connection.camera_index
            
            # Initialize calibration manager for the reconnected camera
            self._init_calibration_manager()
        
        return success
    
    def connect_camera(self, camera_index=0):
        """
        Connect to a specific camera.
        Delegates connection to connection manager, then initializes calibration.
        """
        # Build settings dict from our properties
        settings = {
            'gain': self.gain,
            'exposure_sec': self.exposure_seconds,
            'wb_r': self.white_balance_r,
            'wb_b': self.white_balance_b,
            'wb_mode': self.wb_mode,
            'offset': self.offset,
            'flip': self.flip,
            'use_raw16': self.use_raw16,  # RAW16 mode for full bit depth
        }
        
        # Delegate connection to connection manager
        success = self._connection.connect(camera_index, settings)
        
        if success:
            # Sync camera_name and camera_index from connection manager
            self.camera_name = self._connection.camera_name
            self.camera_index = self._connection.camera_index
            
            # Initialize calibration manager
            self._init_calibration_manager()
            
            self.log(f"✓ Camera connection successful")
            if self.scheduled_capture_enabled:
                self.log(f"Scheduled capture enabled: {self.scheduled_start_time} - {self.scheduled_end_time}")
        
        return success
    
    def _init_calibration_manager(self):
        """Initialize the calibration manager for connected camera"""
        if not self.camera:
            return
        
        self.log("Initializing calibration manager...")
        self.calibration_manager = CameraCalibration(
            self.camera, self.asi, self.log, 
            bit_depth=self.current_bit_depth  # Pass current RAW mode bit depth
        )
        self.calibration_manager.update_settings(
            exposure_seconds=self.exposure_seconds,
            gain=self.gain,
            target_brightness=self.target_brightness,
            max_exposure_sec=self.max_exposure,
            algorithm=self.exposure_algorithm,
            percentile=self.exposure_percentile,
            clipping_threshold=self.clipping_threshold,
            clipping_prevention=self.clipping_prevention
        )
    
    def _configure_camera(self):
        """Configure camera settings (delegates to connection manager)"""
        if not self.camera:
            return
        
        settings = {
            'gain': self.gain,
            'exposure_sec': self.exposure_seconds,
            'wb_r': self.white_balance_r,
            'wb_b': self.white_balance_b,
            'wb_mode': self.wb_mode,
            'offset': self.offset,
            'flip': self.flip,
            'use_raw16': self.use_raw16,  # RAW16 mode for full bit depth
        }
        self._connection.configure(settings)
    
    def set_raw16_mode(self, enabled: bool) -> bool:
        """
        Change RAW mode (RAW8/RAW16) during live capture.
        
        Args:
            enabled: True for RAW16, False for RAW8
            
        Returns:
            True if mode changed successfully
        """
        if not self.camera:
            self.log("Cannot change RAW mode: camera not connected")
            return False
        
        if enabled and not self.supports_raw16:
            self.log("Camera does not support RAW16 mode")
            return False
        
        try:
            # Update our setting
            self.use_raw16 = enabled
            
            # Get camera info for ROI
            camera_info = self.camera.get_camera_property()
            width = camera_info['MaxWidth']
            height = camera_info['MaxHeight']
            
            # Set new image type
            image_type = self.asi.ASI_IMG_RAW16 if enabled else self.asi.ASI_IMG_RAW8
            self.camera.set_roi(start_x=0, start_y=0, width=width, height=height, 
                               bins=1, image_type=image_type)
            self.camera.set_image_type(image_type)
            
            # Update connection manager state
            self._connection.current_image_type = image_type
            self._connection.current_bit_depth = 16 if enabled else 8
            
            # Update calibration manager bit depth
            if self.calibration_manager:
                self.calibration_manager.bit_depth = self.current_bit_depth
            
            mode_str = "RAW16" if enabled else "RAW8"
            self.log(f"Switched to {mode_str} mode ({self.current_bit_depth}-bit capture)")
            return True
            
        except Exception as e:
            self.log(f"Error changing RAW mode: {e}")
            return False

    def disconnect_camera(self):
        """Disconnect from camera gracefully (idempotent - safe to call multiple times)"""
        # Stop capture first if active
        if self.is_capturing:
            self.log("Stopping active capture before disconnect...")
            self.stop_capture()
        
        # Create callback to stop exposure before disconnect
        def stop_exposure_callback():
            if self.exposure_start_time is not None:
                self.log("Aborting in-progress exposure...")
                try:
                    self._connection.camera.stop_exposure()
                except Exception:
                    pass
                self.exposure_start_time = None
                self.exposure_remaining = 0.0
                self.log("Exposure aborted")
        
        # Delegate to connection manager
        self._connection.disconnect(stop_exposure_callback=stop_exposure_callback)
        
        # Clear exposure tracking
        self.exposure_start_time = None
        self.exposure_remaining = 0.0
    
    def capture_single_frame(self):
        """Capture a single frame and return image + metadata"""
        if not self.camera:
            raise Exception("Camera not connected")
        
        try:
            # Update exposure and gain
            self.camera.set_control_value(self.asi.ASI_EXPOSURE, int(self.exposure_seconds * 1000000))
            self.camera.set_control_value(self.asi.ASI_GAIN, self.gain)
            
            # Capture frame
            self.camera.start_exposure()
            
            # Wait for exposure to complete
            timeout = self.exposure_seconds + 5.0
            start_time = time.time()
            self.exposure_start_time = start_time
            
            while time.time() - start_time < timeout:
                # Check if camera was disconnected during wait
                if self.camera is None:
                    raise Exception("Camera disconnected during exposure")
                
                status = self.camera.get_exposure_status()
                if status == self.asi.ASI_EXP_SUCCESS:
                    break
                elif status == self.asi.ASI_EXP_FAILED:
                    raise Exception("Exposure failed (camera returned ASI_EXP_FAILED status)")
                elif status == self.asi.ASI_EXP_IDLE:
                    raise Exception("Exposure error: camera returned to IDLE state unexpectedly")
                
                # Update remaining time for UI
                elapsed = time.time() - start_time
                self.exposure_remaining = max(0, self.exposure_seconds - elapsed)
                time.sleep(0.05)
            
            # Check if we timed out
            if time.time() - start_time >= timeout:
                self.exposure_remaining = 0.0
                self.exposure_start_time = None
                raise Exception(f"Exposure timeout: camera did not complete {self.exposure_seconds}s exposure within {timeout}s")
            
            # Reset exposure tracking
            self.exposure_remaining = 0.0
            self.exposure_start_time = None
            
            # Get the image data
            img_data = self.camera.get_data_after_exposure()
            
            # Get camera info
            camera_info = self.camera.get_camera_property()
            width = camera_info['MaxWidth']
            height = camera_info['MaxHeight']
            
            # Get temperature
            temp_info = self._get_temperature()
            
            # Convert raw Bayer to RGB using utility functions
            # Pass bit_depth for RAW16 mode support, request raw16 for dev mode
            img_rgb, img_rgb_raw16 = debayer_raw_image(
                img_data, width, height, self.bayer_pattern, 
                bit_depth=self.current_bit_depth,
                return_raw16=(self.current_bit_depth == 16)  # Get raw uint16 for RAW16 mode
            )
            img_rgb_no_wb = img_rgb.copy()  # 8-bit pre-WB version for display
            img_rgb = apply_white_balance(img_rgb, self.wb_config)
            img = Image.fromarray(img_rgb, mode='RGB')
            
            # Calculate image statistics using utility function
            stats = calculate_image_stats(np.array(img))
            
            # Build metadata dictionary
            metadata = {
                'CAMERA': camera_info['Name'],
                'EXPOSURE': f"{self.exposure_seconds}s",
                'GAIN': str(self.gain),
                'TEMP': temp_info['display'],
                'TEMPERATURE': temp_info['display'],
                'TEMP_C': temp_info['celsius_str'],
                'TEMP_F': temp_info['fahrenheit_str'],
                'RES': f"{width}x{height}",
                'CAPTURE AREA SIZE': f"{width} * {height}",
                'FILENAME': f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                'SESSION': datetime.now().strftime('%Y-%m-%d'),
                'DATETIME': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'BRIGHTNESS': f"{stats['mean']:.1f}",
                'MEAN': f"{stats['mean']:.1f}",
                'MEDIAN': f"{stats['median']:.1f}",
                'MIN': f"{stats['min']}",
                'MAX': f"{stats['max']}",
                'STD_DEV': f"{stats['std_dev']:.2f}",
                'P25': f"{stats['p25']:.1f}",
                'P75': f"{stats['p75']:.1f}",
                'P95': f"{stats['p95']:.1f}",
                'RAW_RGB_NO_WB': img_rgb_no_wb,  # Pre-white-balance RGB (uint8) for display
                'RAW_RGB_16BIT': img_rgb_raw16,  # Full uint16 RGB for dev mode (None if RAW8)
                # Camera sensor info for proper FITS saving
                'CAMERA_BIT_DEPTH': camera_info.get('BitDepth', 8),  # ADC bit depth (e.g., 12)
                'IMAGE_BIT_DEPTH': self.current_bit_depth,  # Current capture mode (RAW8=8, RAW16=16)
                'BAYER_PATTERN': self.bayer_pattern,
                'PIXEL_SIZE': camera_info.get('PixelSize', 0),
                'ELEC_PER_ADU': camera_info.get('ElecPerADU', 1.0),
            }
            
            return img, metadata
        
        except Exception as e:
            self.log(f"ERROR capturing frame: {e}")
            raise
    
    def _get_temperature(self):
        """Get camera temperature info as dict"""
        try:
            temp_value = self.camera.get_control_value(self.asi.ASI_TEMPERATURE)[0]
            temp_celsius = temp_value / 10.0
            temp_fahrenheit = (temp_celsius * 9/5) + 32
            return {
                'display': f"{temp_celsius:.1f} C",
                'celsius_str': f"{temp_celsius:.1f}°C",
                'fahrenheit_str': f"{temp_fahrenheit:.1f}°F"
            }
        except:
            return {'display': "N/A", 'celsius_str': "N/A", 'fahrenheit_str': "N/A"}
    
    def capture_loop(self):
        """Background capture loop with automatic recovery and scheduled capture support"""
        self.log("=== Capture Loop Started ===")
        if self.scheduled_capture_enabled:
            self.log(f"Scheduled capture enabled: {self.scheduled_start_time} - {self.scheduled_end_time}")
        else:
            self.log("Scheduled capture disabled: will run continuously")
        
        consecutive_errors = 0
        max_reconnect_attempts = 5
        last_schedule_log = None  # Track last schedule status to avoid log spam
        
        # Recalibration rate limiting to prevent infinite loops
        # (e.g., someone turning lights on/off repeatedly)
        last_recalibration_time = 0
        recalibration_cooldown_sec = 60  # Minimum 60 seconds between recalibrations
        recalibration_count = 0  # Count recalibrations in current window
        recalibration_window_start = time.time()
        max_recalibrations_per_window = 3  # Max 3 recalibrations per 10-minute window
        recalibration_window_sec = 600  # 10-minute window
        
        try:
            # Run rapid calibration if auto exposure is enabled
            if self.auto_exposure and not self.calibration_complete:
                try:
                    self.run_calibration()
                except Exception as e:
                    self.log(f"Calibration failed: {e}. Continuing with current settings.")
                    self.calibration_complete = True
        except Exception as e:
            self.log(f"Error during calibration: {e}")
        
        try:
            while self.is_capturing:
                try:
                    # Check if we're within the scheduled capture window
                    within_window = self.is_within_scheduled_window()
                    
                    if not within_window:
                        # Outside scheduled window - disconnect camera to reduce load
                        current_status = "outside_window"
                        if last_schedule_log != current_status:
                            self.log(f"⏸ Outside scheduled capture window ({self.scheduled_start_time} - {self.scheduled_end_time})")
                            self.log("Entering off-peak mode: disconnecting camera to reduce hardware load...")
                            last_schedule_log = current_status
                            
                            # Disconnect camera to reduce load during off-peak hours
                            if self.camera:
                                try:
                                    # Temporarily stop capturing flag
                                    was_capturing = self.is_capturing
                                    self.is_capturing = False
                                    
                                    # Abort any in-progress exposure before disconnect
                                    try:
                                        if self.exposure_start_time is not None:
                                            self.camera.stop_exposure()
                                            self.exposure_start_time = None
                                            self.exposure_remaining = 0.0
                                    except Exception as exp_err:
                                        pass  # No exposure active
                                    
                                    # Disconnect camera gracefully using connection manager
                                    self._connection.disconnect()
                                    self.log("✓ Camera disconnected for off-peak hours (reducing hardware load)")
                                    
                                    # Restore capturing flag for reconnection logic
                                    self.is_capturing = was_capturing
                                    
                                    # Update UI status to reflect disconnection
                                    if self.status_callback:
                                        self.status_callback(f"Idle (off-peak until {self.scheduled_start_time})")
                                except Exception as e:
                                    self.log(f"Error disconnecting camera: {e}")
                                    self.is_capturing = was_capturing  # Restore flag even on error
                        continue
                    else:
                        # Within window - reconnect camera if needed
                        if last_schedule_log == "outside_window":
                            self.log(f"▶ Entered scheduled capture window ({self.scheduled_start_time} - {self.scheduled_end_time})")
                            self.log("Transitioning to active capture mode: reconnecting camera...")
                            last_schedule_log = "inside_window"
                            
                            # Update UI status
                            if self.status_callback:
                                self.status_callback("Reconnecting for scheduled window...")
                            
                            # Reconnect camera for scheduled window
                            if not self.camera:
                                self.log("Attempting to reconnect camera (re-detecting cameras)...")
                                if not self.reconnect_camera_safe():
                                    self.log("✗ ERROR: Failed to reconnect camera for scheduled window")
                                    self.log("Will retry in 5 seconds...")
                                    time.sleep(5)  # Wait before retrying
                                    continue
                                self.log("✓ Camera reconnected successfully for scheduled captures")
                    
                    # Check if camera is still connected
                    if not self.camera:
                        raise Exception("Camera disconnected")
                    
                    # Capture frame
                    img, metadata = self.capture_single_frame()
                    
                    # Reset error counter on successful capture
                    consecutive_errors = 0
                    
                    # Auto-adjust exposure based on image brightness
                    # Check if drastic brightness change requires recalibration
                    if self.auto_exposure:
                        img_array = np.array(img)
                        exposure_result = self.adjust_exposure_auto(img_array)
                        if exposure_result and exposure_result.get('needs_recalibration', False):
                            current_time = time.time()
                            
                            # Reset recalibration window if expired
                            if current_time - recalibration_window_start > recalibration_window_sec:
                                recalibration_count = 0
                                recalibration_window_start = current_time
                            
                            # Check rate limits before allowing recalibration
                            time_since_last = current_time - last_recalibration_time
                            can_recalibrate = (
                                time_since_last >= recalibration_cooldown_sec and
                                recalibration_count < max_recalibrations_per_window
                            )
                            
                            if can_recalibrate:
                                self.log(f"⚠ Drastic scene change detected - running rapid calibration")
                                self.log(f"  (Recalibration {recalibration_count + 1}/{max_recalibrations_per_window} in current window)")
                                
                                # Notify calibration starting
                                if self.on_calibration_callback:
                                    self.on_calibration_callback(True)
                                
                                # Run rapid calibration to quickly find optimal exposure
                                try:
                                    self.run_calibration()
                                    last_recalibration_time = time.time()
                                    recalibration_count += 1
                                except Exception as cal_error:
                                    self.log(f"Recalibration error: {cal_error} - continuing with adjusted exposure")
                                
                                # Notify calibration complete
                                if self.on_calibration_callback:
                                    self.on_calibration_callback(False)
                                
                                # Skip publishing this badly-exposed frame
                                # Next iteration will capture with calibrated exposure
                                continue
                            else:
                                # Rate limited - log why and continue with normal aggressive adjustment
                                if time_since_last < recalibration_cooldown_sec:
                                    wait_time = int(recalibration_cooldown_sec - time_since_last)
                                    self.log(f"⚠ Scene change detected but recalibration on cooldown ({wait_time}s remaining)")
                                else:
                                    self.log(f"⚠ Scene change detected but max recalibrations reached ({max_recalibrations_per_window} per {recalibration_window_sec//60}min window)")
                                self.log(f"  Using aggressive auto-exposure adjustment instead")
                                # Don't skip frame - let normal aggressive adjustment handle it
                    
                    # Call callback with image and metadata
                    if self.on_frame_callback:
                        self.on_frame_callback(img, metadata)
                    
                    self.log(f"Captured frame: {metadata['FILENAME']}")
                    
                    # Check for dropped frames (helps diagnose USB bandwidth issues)
                    try:
                        dropped = self.camera.get_dropped_frames()
                        if dropped > 0:
                            self.log(f"⚠ USB performance warning: {dropped} dropped frames detected")
                            self.log("  Consider: reducing bandwidth_overload, lowering frame rate, or checking USB connection")
                    except Exception:
                        pass  # Not all cameras/modes support dropped frame reporting
                    
                    # Wait for next capture interval
                    if self.is_capturing:  # Check again in case stopped during capture
                        time.sleep(self.capture_interval)
                
                except Exception as e:
                    consecutive_errors += 1
                    error_msg = str(e)
                    self.log(f"✗ ERROR in capture loop: {error_msg}")
                    self.log(f"Consecutive errors: {consecutive_errors}/{max_reconnect_attempts}")
                    import traceback
                    self.log(f"Stack trace: {traceback.format_exc()}")
                    
                    # Notify error callback on first error (for Discord alerts etc.)
                    if consecutive_errors == 1 and hasattr(self, 'on_error_callback') and self.on_error_callback:
                        self.on_error_callback(f"Capture error: {error_msg} - attempting recovery...")
                    
                    # Try to recover from camera disconnect
                    if consecutive_errors <= max_reconnect_attempts:
                        self.log(f"Initiating reconnection attempt {consecutive_errors}/{max_reconnect_attempts}...")
                        try:
                            # Clean up existing camera using connection manager
                            # This ensures proper cleanup via the thread-safe disconnect method
                            if self.camera:
                                self.log("Cleaning up existing camera connection...")
                                self._connection.disconnect()
                            
                            # Reinitialize camera using safe reconnection
                            self.log("Waiting 0.5s before reconnection attempt...")
                            time.sleep(0.5)  # Brief delay before reconnecting
                            
                            # Use safe reconnection method that re-detects cameras
                            if self.reconnect_camera_safe():
                                self.log("✓ Camera reconnected successfully")
                                consecutive_errors = 0  # Reset counter on successful reconnection
                                self.log("Waiting 1s before resuming capture...")
                                time.sleep(1.0)
                                continue
                            else:
                                raise Exception("Failed to reconnect camera")
                        except Exception as reconnect_error:
                            self.log(f"✗ Reconnection attempt failed: {reconnect_error}")
                            import traceback
                            self.log(f"Stack trace: {traceback.format_exc()}")
                            # Exponential backoff: 2, 4, 8, 16, 32 seconds
                            backoff_time = min(2 ** consecutive_errors, 32)
                            self.log(f"Using exponential backoff: waiting {backoff_time}s before retry {consecutive_errors + 1}/{max_reconnect_attempts}...")
                            time.sleep(backoff_time)
                    else:
                        # Max attempts reached - stop capture
                        self.log(f"✗ CRITICAL: Maximum reconnection attempts ({max_reconnect_attempts}) reached")
                        self.log("Camera appears to be disconnected or unresponsive")
                        self.log("Stopping capture loop. Manual intervention required.")
                        self.log("Troubleshooting: 1) Check USB cable, 2) Check camera power, 3) Check USB drivers, 4) Restart application")
                        self.is_capturing = False
                        # Notify via callback that capture failed
                        if hasattr(self, 'on_error_callback') and self.on_error_callback:
                            self.on_error_callback("Camera disconnected - failed to reconnect after multiple attempts")
                        break
        finally:
            # Ensure camera is properly stopped on all exit paths (normal, error, or thread interrupt)
            self.log("Capture loop exiting - cleaning up...")
            # Note: We use snapshot mode (start_exposure/get_data_after_exposure)
            # NOT video mode (start_video_capture/get_video_data)
            # Camera cleanup is handled by disconnect_camera() which is called by stop_capture()
        
        self.log("Capture loop stopped")
    
    def start_capture(self, on_frame_callback, on_log_callback=None):
        """Start continuous capture"""
        if self.is_capturing:
            self.log("Capture already running")
            return False
        
        if not self.camera:
            self.log("ERROR: Camera not connected")
            return False
        
        self.on_frame_callback = on_frame_callback
        self.on_log_callback = on_log_callback
        self.is_capturing = True
        
        # Start capture thread
        self.capture_thread = threading.Thread(target=self.capture_loop, daemon=True)
        self.capture_thread.start()
        
        return True
    
    def stop_capture(self):
        """Stop continuous capture and wait for thread to finish"""
        if not self.is_capturing:
            return
        
        self.log("Stopping capture...")
        self.is_capturing = False
        
        # Wait briefly for capture thread to finish
        if self.capture_thread and self.capture_thread.is_alive():
            self.log("Waiting for capture thread to finish...")
            self.capture_thread.join(timeout=2.0)  # Reduced timeout for faster stop
            
            if self.capture_thread.is_alive():
                self.log("Warning: Capture thread still running (will finish in background)")
            else:
                self.log("Capture thread finished successfully")
            
            self.capture_thread = None
        
        self.log("Capture stopped")
    
    def set_exposure(self, seconds):
        """Set exposure time in seconds"""
        self.exposure_seconds = max(0.000001, min(3600, seconds))
    
    def set_gain(self, gain):
        """Set gain value"""
        self.gain = max(0, min(600, int(gain)))
    
    def set_capture_interval(self, seconds):
        """Set interval between captures"""
        self.capture_interval = max(1.0, seconds)
    
    def update_exposure(self, exposure_seconds):
        """Update exposure setting and apply immediately to camera if connected"""
        self.exposure_seconds = exposure_seconds
        
        # If camera is connected and not in auto exposure mode, apply immediately
        if self.camera and not self.auto_exposure:
            try:
                self.camera.set_control_value(self.asi.ASI_EXPOSURE, int(exposure_seconds * 1000000))
                self.log(f"Exposure updated to {exposure_seconds*1000:.2f}ms")
            except Exception as e:
                self.log(f"Failed to update camera exposure: {e}")
    
    def run_calibration(self):
        """Rapid calibration to find optimal exposure before starting interval captures"""
        if not self.auto_exposure or not self.camera or not self.calibration_manager:
            return
        
        self.log("Starting rapid auto-exposure calibration...")
        self.calibration_mode = True
        
        # Notify UI that calibration is starting
        if self.on_calibration_callback:
            self.on_calibration_callback(True)
        
        # Run calibration using the calibration manager
        success = self.calibration_manager.run_calibration(max_attempts=15)
        
        # Update our exposure from calibration manager
        self.exposure_seconds = self.calibration_manager.exposure_seconds
        
        self.calibration_complete = True
        self.calibration_mode = False
        
        # Notify UI that calibration is complete
        if self.on_calibration_callback:
            self.on_calibration_callback(False)
    
    def adjust_exposure_auto(self, img_array):
        """
        Adjust exposure based on image brightness with intelligent step sizing.
        
        Returns:
            dict with 'needs_recalibration' flag and brightness info, or None if auto-exposure disabled
        """
        if not self.auto_exposure or not self.calibration_manager:
            return None
        
        # Use calibration manager to adjust exposure
        result = self.calibration_manager.adjust_exposure_auto(img_array)
        
        # Update our exposure from calibration manager
        self.exposure_seconds = self.calibration_manager.exposure_seconds
        
        return result
