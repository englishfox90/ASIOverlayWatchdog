"""
ZWO ASI Camera capture module
Provides interface to capture images from ZWO cameras using the ASI SDK
"""
import os
import time
import threading
import numpy as np
from datetime import datetime
from PIL import Image
from .camera_utils import simple_debayer_rggb, is_within_scheduled_window as check_scheduled_window
from .camera_calibration import CameraCalibration


class ZWOCamera:
    """Interface to ZWO ASI camera using zwoasi library"""
    
    def __init__(self, sdk_path=None, camera_index=0, exposure_sec=1.0, gain=100,
                 white_balance_r=75, white_balance_b=99, offset=20, flip=0,
                 auto_exposure=False, max_exposure_sec=30.0, auto_wb=False,
                 wb_mode='asi_auto', wb_config=None, bayer_pattern='BGGR',
                 scheduled_capture_enabled=False, scheduled_start_time="17:00",
                 scheduled_end_time="09:00", status_callback=None, camera_name=None,
                 config_callback=None):
        self.sdk_path = sdk_path
        self.camera_index = camera_index
        self.camera_name = camera_name  # Persistent camera identifier
        self.config_callback = config_callback  # Callback to save config
        self.camera = None
        self.asi = None
        self.cameras = []
        self.is_capturing = False
        self.capture_thread = None
        self.on_frame_callback = None
        self.on_log_callback = None
        self.status_callback = status_callback  # Callback for schedule status updates
        self._cleanup_lock = threading.Lock()  # Prevent multiple simultaneous disconnects
        
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
        """Initialize the ZWO ASI SDK"""
        self.log("=== Initializing ZWO ASI SDK ===")
        try:
            import zwoasi as asi
            self.asi = asi
            self.log("zwoasi module imported successfully")
            
            if self.sdk_path and os.path.exists(self.sdk_path):
                self.log(f"Attempting SDK init with configured path: {self.sdk_path}")
                asi.init(self.sdk_path)
                self.log(f"✓ ZWO SDK initialized successfully from: {self.sdk_path}")
            else:
                # Try default locations
                self.log("SDK path not configured or not found, trying default location")
                if os.path.exists('ASICamera2.dll'):
                    self.log("Found ASICamera2.dll in application directory")
                    asi.init('ASICamera2.dll')
                    self.log("✓ ZWO SDK initialized from: ASICamera2.dll")
                else:
                    self.log("ERROR: ASICamera2.dll not found in application directory")
                    self.log("Please configure SDK path in Capture tab settings")
                    return False
            
            return True
        
        except ImportError as e:
            self.log(f"ERROR: zwoasi library not installed: {e}")
            self.log("Run: pip install zwoasi")
            return False
        except Exception as e:
            self.log(f"ERROR initializing ZWO SDK: {e}")
            import traceback
            self.log(f"Stack trace: {traceback.format_exc()}")
            return False
    
    def reset_sdk_completely(self):
        """
        Completely reset the SDK state (nuclear option).
        Use this when SDK gets into an inconsistent state.
        Returns True if successful, False otherwise.
        """
        self.log("=== Complete SDK Reset ===")
        
        try:
            # Close camera if connected
            if self.camera:
                self.log("Disconnecting camera before SDK reset...")
                self.disconnect_camera()
            
            # Clear SDK reference
            self.log("Clearing SDK reference...")
            self.asi = None
            
            # Wait for cleanup
            import time
            time.sleep(1.0)
            
            # Reinitialize SDK
            self.log("Reinitializing SDK...")
            if not self.initialize_sdk():
                self.log("✗ SDK reinitialization failed")
                return False
            
            self.log("✓ SDK reset complete")
            return True
            
        except Exception as e:
            self.log(f"✗ ERROR during SDK reset: {e}")
            import traceback
            self.log(f"Stack trace: {traceback.format_exc()}")
            return False
    
    def detect_cameras(self):
        """Detect connected ZWO cameras"""
        self.log("=== Starting Camera Detection ===")
        
        if not self.asi:
            self.log("SDK not initialized, initializing now...")
            if not self.initialize_sdk():
                self.log("Camera detection failed: SDK initialization failed")
                return []
        
        try:
            self.log("Querying SDK for number of connected cameras...")
            num_cameras = self.asi.get_num_cameras()
            self.cameras = []
            
            if num_cameras == 0:
                self.log("⚠ No ZWO cameras detected by SDK")
                self.log("Check: 1) USB cable connected, 2) Camera powered, 3) USB drivers installed")
                return []
            
            self.log(f"✓ Found {num_cameras} ZWO camera(s) connected")
            self.log("Enumerating camera details...")
            
            for i in range(num_cameras):
                try:
                    camera_info = self.asi.list_cameras()[i]
                    self.cameras.append({
                        'index': i,
                        'name': camera_info
                    })
                    self.log(f"  ✓ Camera {i}: {camera_info}")
                except Exception as cam_err:
                    self.log(f"  ⚠ Warning: Could not get info for camera {i}: {cam_err}")
            
            self.log(f"Camera detection complete: {len(self.cameras)} camera(s) enumerated")
            return self.cameras
        
        except Exception as e:
            self.log(f"ERROR during camera detection: {e}")
            import traceback
            self.log(f"Stack trace: {traceback.format_exc()}")
            return []
    
    def reconnect_camera_safe(self):
        """
        Safely reconnect to camera by re-detecting available cameras first.
        This is necessary after disconnection (e.g., during off-peak hours) 
        because camera indices may change.
        Returns True if successful, False otherwise.
        """
        self.log("=== Safe Camera Reconnection ===")
        
        # First attempt: Normal reconnection
        self.log("Re-detecting cameras to find valid indices...")
        detected = self.detect_cameras()
        
        if not detected:
            self.log("✗ No cameras detected during reconnection attempt")
            self.log("Attempting SDK reinitialization as fallback...")
            
            # Try reinitializing SDK to clear stale state
            self.asi = None
            if not self.initialize_sdk():
                self.log("✗ SDK reinitialization failed")
                return False
            
            # Try detection again after SDK reset
            detected = self.detect_cameras()
            if not detected:
                self.log("✗ No cameras detected even after SDK reset")
                return False
            else:
                self.log("✓ Cameras detected after SDK reset")
        
        # Try to find camera by stored name (most reliable with multiple cameras)
        target_index = None
        
        if self.camera_name:
            self.log(f"Looking for camera by name: {self.camera_name}")
            for cam in detected:
                if self.camera_name in cam['name']:
                    target_index = cam['index']
                    self.log(f"✓ Found camera '{self.camera_name}' at new index {target_index}")
                    break
            
            if target_index is None:
                self.log(f"⚠ Warning: Could not find camera '{self.camera_name}' by name")
        
        # If we couldn't find by name, use the first available camera
        if target_index is None:
            target_index = detected[0]['index']
            self.log(f"Using first available camera at index {target_index}: {detected[0]['name']}")
        
        # Update camera_index for future use
        self.camera_index = target_index
        
        # Attempt to connect to the camera
        self.log(f"Attempting to connect to camera at index {target_index}...")
        connection_success = self.connect_camera(target_index)
        
        # If connection failed, try complete SDK reset as last resort
        if not connection_success:
            self.log("⚠ Initial connection failed, attempting complete SDK reset...")
            if self.reset_sdk_completely():
                self.log("Retrying camera detection after SDK reset...")
                detected = self.detect_cameras()
                if detected:
                    # Find camera again after reset
                    target_index = None
                    if self.camera_name:
                        for cam in detected:
                            if self.camera_name in cam['name']:
                                target_index = cam['index']
                                break
                    if target_index is None:
                        target_index = detected[0]['index']
                    
                    self.camera_index = target_index
                    self.log(f"Retrying connection to camera at index {target_index}...")
                    connection_success = self.connect_camera(target_index)
                    
                    if connection_success:
                        self.log("✓ Connection successful after SDK reset")
                    else:
                        self.log("✗ Connection still failed after SDK reset")
                else:
                    self.log("✗ No cameras detected after SDK reset")
            else:
                self.log("✗ SDK reset failed")
        
        return connection_success
    
    def connect_camera(self, camera_index=0):
        """Connect to a specific camera"""
        self.log(f"=== Connecting to Camera (Index: {camera_index}) ===")
        
        if not self.asi:
            self.log("SDK not initialized, initializing now...")
            if not self.initialize_sdk():
                self.log("Connection failed: SDK initialization failed")
                return False
        
        try:
            if self.camera:
                self.log("Existing camera connection detected, disconnecting first...")
                self.disconnect_camera()
            
            # Add a small delay to allow SDK cleanup after disconnect
            # This helps prevent "Invalid ID" errors when reconnecting
            import time
            time.sleep(0.2)
            
            self.log(f"Opening camera at index {camera_index}...")
            
            # Try to open the camera with retry logic for transient SDK errors
            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                try:
                    self.camera = self.asi.Camera(camera_index)
                    break  # Success - exit retry loop
                except Exception as e:
                    if attempt < max_attempts:
                        self.log(f"⚠ Attempt {attempt}/{max_attempts} failed: {e}")
                        self.log(f"Waiting 0.5s before retry...")
                        time.sleep(0.5)
                    else:
                        # Final attempt failed - re-raise the exception
                        raise
            camera_info = self.camera.get_camera_property()
            
            # Store camera name for future reconnection
            self.camera_name = camera_info['Name']
            
            # Save camera name to config for persistence across restarts
            if self.config_callback:
                self.config_callback('zwo_selected_camera_name', self.camera_name)
                self.log(f"Saved camera name to config: {self.camera_name}")
            
            self.log(f"✓ Connected to camera: {camera_info['Name']}")
            self.log(f"  Camera ID: {camera_info.get('CameraID', 'N/A')}")
            self.log(f"  Max Resolution: {camera_info['MaxWidth']}x{camera_info['MaxHeight']}")
            self.log(f"  Pixel Size: {camera_info['PixelSize']} µm")
            
            # Get controls info
            controls = self.camera.get_controls()
            self.log(f"  Available controls: {len(controls)}")
            
            self.log("Configuring camera settings...")
            # Set initial camera settings with validation
            # SDK best practice: validate values are within camera's supported ranges
            controls = self.camera.get_controls()
            
            # Set gain with range validation
            gain_ctrl = next((c for c in controls.values() if c['ControlType'] == self.asi.ASI_GAIN), None)
            if gain_ctrl:
                validated_gain = max(gain_ctrl['MinValue'], min(gain_ctrl['MaxValue'], self.gain))
                if validated_gain != self.gain:
                    self.log(f"  ⚠ Gain {self.gain} out of range [{gain_ctrl['MinValue']}-{gain_ctrl['MaxValue']}], using {validated_gain}")
                    self.gain = validated_gain
                self.camera.set_control_value(self.asi.ASI_GAIN, self.gain)
                self.log(f"  Gain: {self.gain} (range: {gain_ctrl['MinValue']}-{gain_ctrl['MaxValue']})")
            else:
                self.camera.set_control_value(self.asi.ASI_GAIN, self.gain)
                self.log(f"  Gain: {self.gain}")
            
            # Set exposure with range validation
            exposure_us = int(self.exposure_seconds * 1000000)
            exp_ctrl = next((c for c in controls.values() if c['ControlType'] == self.asi.ASI_EXPOSURE), None)
            if exp_ctrl:
                validated_exp = max(exp_ctrl['MinValue'], min(exp_ctrl['MaxValue'], exposure_us))
                if validated_exp != exposure_us:
                    self.log(f"  ⚠ Exposure {exposure_us}µs out of range [{exp_ctrl['MinValue']}-{exp_ctrl['MaxValue']}], using {validated_exp}µs")
                    exposure_us = validated_exp
                    self.exposure_seconds = exposure_us / 1000000.0
                self.camera.set_control_value(self.asi.ASI_EXPOSURE, exposure_us)
                self.log(f"  Exposure: {self.exposure_seconds}s ({self.exposure_seconds * 1000}ms, range: {exp_ctrl['MinValue']/1000000:.6f}s-{exp_ctrl['MaxValue']/1000000:.1f}s)")
            else:
                self.camera.set_control_value(self.asi.ASI_EXPOSURE, exposure_us)
                self.log(f"  Exposure: {self.exposure_seconds}s ({self.exposure_seconds * 1000}ms)")
            
            # Configure white balance based on mode
            if self.wb_mode == 'asi_auto':
                # Enable SDK auto WB
                try:
                    self.camera.set_control_value(self.asi.ASI_AUTO_MAX_BRIGHTNESS, 1)
                    self.log("White balance mode: ASI Auto")
                except:
                    pass
            elif self.wb_mode == 'manual':
                # Disable SDK auto WB, use manual values
                try:
                    self.camera.set_control_value(self.asi.ASI_AUTO_MAX_BRIGHTNESS, 0)
                except:
                    pass
                self.camera.set_control_value(self.asi.ASI_WB_R, self.white_balance_r)
                self.camera.set_control_value(self.asi.ASI_WB_B, self.white_balance_b)
                self.log(f"White balance mode: Manual (R={self.white_balance_r}, B={self.white_balance_b})")
            elif self.wb_mode == 'gray_world':
                # Disable SDK auto WB, set neutral values
                try:
                    self.camera.set_control_value(self.asi.ASI_AUTO_MAX_BRIGHTNESS, 0)
                except:
                    pass
                # Set neutral WB (mid-range)
                self.camera.set_control_value(self.asi.ASI_WB_R, 50)
                self.camera.set_control_value(self.asi.ASI_WB_B, 50)
                self.log("White balance mode: Gray World (software)")
            
            self.camera.set_control_value(self.asi.ASI_BANDWIDTHOVERLOAD, 40)
            self.camera.set_control_value(self.asi.ASI_BRIGHTNESS, self.offset)
            
            # Set flip if needed
            if self.flip == 1 or self.flip == 3:
                self.camera.set_control_value(self.asi.ASI_FLIP, 1)  # Horizontal
            if self.flip == 2 or self.flip == 3:
                self.camera.set_control_value(self.asi.ASI_FLIP, 2)  # Vertical
            
            # Set ROI to full frame (SDK best practice: always set ROI explicitly)
            self.camera.set_roi(start_x=0, start_y=0, width=camera_info['MaxWidth'], 
                               height=camera_info['MaxHeight'], bins=1, image_type=self.asi.ASI_IMG_RAW8)
            self.log(f"  ROI: Full frame {camera_info['MaxWidth']}x{camera_info['MaxHeight']}, 1x1 binning")
            
            # Set image format to RAW8
            self.camera.set_image_type(self.asi.ASI_IMG_RAW8)
            
            # Initialize calibration manager
            self.log("Initializing calibration manager...")
            self.calibration_manager = CameraCalibration(self.camera, self.asi, self.log)
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
            
            self.log(f"✓ Camera connection successful")
            if self.scheduled_capture_enabled:
                self.log(f"Scheduled capture enabled: {self.scheduled_start_time} - {self.scheduled_end_time}")
            return True
        
        except Exception as e:
            self.log(f"✗ ERROR connecting to camera: {e}")
            import traceback
            self.log(f"Stack trace: {traceback.format_exc()}")
            
            # Add diagnostic information for "Invalid ID" errors
            if "Invalid ID" in str(e):
                self.log("=== Diagnostic Information ===")
                self.log(f"Attempted camera index: {camera_index}")
                self.log("This error typically occurs when:")
                self.log("  1. Camera was not properly closed by another process")
                self.log("  2. SDK is in an inconsistent state")
                self.log("  3. Camera index changed (hot plug event)")
                self.log("Recommended action: Try stopping/restarting the application")
                
                # Try to get current camera list for diagnostics
                try:
                    num_cameras = self.asi.get_num_cameras()
                    self.log(f"Current SDK state: {num_cameras} camera(s) reported by SDK")
                    listed_cameras = self.asi.list_cameras()
                    for idx, name in enumerate(listed_cameras):
                        self.log(f"  Camera {idx}: {name}")
                except Exception as diag_err:
                    self.log(f"  Could not query camera list for diagnostics: {diag_err}")
            
            return False
    
    def _configure_camera(self):
        """Configure camera settings (used for initial connection and reconnection)"""
        if not self.camera:
            return
        
        try:
            # Get camera info
            camera_info = self.camera.get_camera_property()
            
            # Set ROI to full frame (SDK best practice: always set ROI explicitly)
            self.camera.set_roi(start_x=0, start_y=0, width=camera_info['MaxWidth'], 
                               height=camera_info['MaxHeight'], bins=1, image_type=self.asi.ASI_IMG_RAW8)
            
            # Set image format
            self.camera.set_image_type(self.asi.ASI_IMG_RAW8)
            
            # Set camera controls
            self.camera.set_control_value(self.asi.ASI_GAIN, self.gain)
            self.camera.set_control_value(self.asi.ASI_EXPOSURE, int(self.exposure_seconds * 1000000))
            
            # Configure white balance
            if self.wb_mode == 'asi_auto':
                try:
                    self.camera.set_control_value(self.asi.ASI_AUTO_MAX_BRIGHTNESS, 1)
                except:
                    pass
            elif self.wb_mode == 'manual':
                try:
                    self.camera.set_control_value(self.asi.ASI_AUTO_MAX_BRIGHTNESS, 0)
                except:
                    pass
                self.camera.set_control_value(self.asi.ASI_WB_R, self.white_balance_r)
                self.camera.set_control_value(self.asi.ASI_WB_B, self.white_balance_b)
            elif self.wb_mode == 'gray_world':
                try:
                    self.camera.set_control_value(self.asi.ASI_AUTO_MAX_BRIGHTNESS, 0)
                except:
                    pass
                self.camera.set_control_value(self.asi.ASI_WB_R, 50)
                self.camera.set_control_value(self.asi.ASI_WB_B, 50)
            
            # Set other controls
            self.camera.set_control_value(self.asi.ASI_BANDWIDTHOVERLOAD, 40)
            self.camera.set_control_value(self.asi.ASI_BRIGHTNESS, self.offset)
            
            # Set flip
            if self.flip == 1 or self.flip == 3:
                self.camera.set_control_value(self.asi.ASI_FLIP, 1)
            if self.flip == 2 or self.flip == 3:
                self.camera.set_control_value(self.asi.ASI_FLIP, 2)
            
            self.log("Camera configuration applied")
        except Exception as e:
            self.log(f"Error configuring camera: {e}")
    
    def disconnect_camera(self):
        """Disconnect from camera gracefully (idempotent - safe to call multiple times)"""
        with self._cleanup_lock:
            if not self.camera:
                self.log("Disconnect called but camera already disconnected")
                return  # Already disconnected
            
            self.log("=== Disconnecting Camera ===")
            
            try:
                # Stop capture first if active
                if self.is_capturing:
                    self.log("Stopping active capture before disconnect...")
                    self.stop_capture()
                
                # Abort any in-progress exposure (snapshot mode)
                # SDK documentation: Must call ASIStopExposure() before closing camera
                # if an exposure is in progress, otherwise the camera may hang
                try:
                    if self.exposure_start_time is not None:
                        self.log("Aborting in-progress exposure...")
                        self.camera.stop_exposure()
                        self.exposure_start_time = None
                        self.exposure_remaining = 0.0
                        self.log("Exposure aborted")
                except Exception as e:
                    # Camera may not be in exposure state - this is expected
                    self.log(f"Exposure stop skipped (no exposure active): {e}")
                
                # Note: We use snapshot mode (start_exposure/get_data_after_exposure)
                # NOT video mode (start_video_capture/get_video_data), so no need to stop video capture
                # Calling stop_video_capture when not in video mode can cause undefined behavior
                
                # Close camera connection
                try:
                    self.log("Closing camera connection...")
                    self.camera.close()
                    self.log("✓ Camera disconnected successfully")
                except Exception as e:
                    self.log(f"⚠ Warning during camera close: {e}")
                    
            except Exception as e:
                self.log(f"✗ ERROR during camera disconnect: {e}")
                import traceback
                self.log(f"Stack trace: {traceback.format_exc()}")
            finally:
                # Always clear camera reference even if close failed
                self.camera = None
                self.exposure_start_time = None
                self.exposure_remaining = 0.0
                self.log("Camera reference cleared")
    
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
            # SDK best practice: timeout should be exposure time + reasonable buffer
            timeout = self.exposure_seconds + 5.0
            start_time = time.time()
            self.exposure_start_time = start_time
            
            while time.time() - start_time < timeout:
                status = self.camera.get_exposure_status()
                if status == self.asi.ASI_EXP_SUCCESS:
                    break
                elif status == self.asi.ASI_EXP_FAILED:
                    raise Exception("Exposure failed (camera returned ASI_EXP_FAILED status)")
                elif status == self.asi.ASI_EXP_IDLE:
                    # Camera not exposing - shouldn't happen after start_exposure
                    raise Exception("Exposure error: camera returned to IDLE state unexpectedly")
                # status == ASI_EXP_WORKING: exposure in progress, continue waiting
                
                # Update remaining time for UI (no logging)
                elapsed = time.time() - start_time
                self.exposure_remaining = max(0, self.exposure_seconds - elapsed)
                
                time.sleep(0.05)  # 50ms update rate for smoother countdown
            
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
            
            # Get current temperature if available
            temperature = "N/A"
            temp_c = "N/A"
            temp_f = "N/A"
            try:
                temp_value = self.camera.get_control_value(self.asi.ASI_TEMPERATURE)[0]
                temp_celsius = temp_value / 10.0
                temp_fahrenheit = (temp_celsius * 9/5) + 32
                temperature = f"{temp_celsius:.1f} C"
                temp_c = f"{temp_celsius:.1f}"
                temp_f = f"{temp_fahrenheit:.1f}"
            except:
                pass
            
            # Convert to PIL Image
            # For RAW8, data is single channel Bayer pattern
            img_array = np.frombuffer(img_data, dtype=np.uint8)
            img_array = img_array.reshape((height, width))
            
            # Debayer the raw Bayer data to RGB (simple bilinear debayering)
            # Bayer pattern configurable (RGGB, BGGR, GRBG, GBRG)
            try:
                import cv2
                # Map bayer pattern to OpenCV constant
                bayer_map = {
                    'RGGB': cv2.COLOR_BayerRG2RGB,
                    'BGGR': cv2.COLOR_BayerBG2RGB,
                    'GRBG': cv2.COLOR_BayerGR2RGB,
                    'GBRG': cv2.COLOR_BayerGB2RGB
                }
                bayer_code = bayer_map.get(self.bayer_pattern, cv2.COLOR_BayerBG2RGB)
                img_rgb = cv2.cvtColor(img_array, bayer_code)
                
                # Apply software white balance if needed (gray_world or manual)
                # Note: img_rgb is RGB, need to convert to BGR for cv2 functions
                if hasattr(self, 'wb_config') and self.wb_config:
                    wb_mode = self.wb_config.get('mode', 'asi_auto')
                    if wb_mode == 'gray_world':
                        from services.color_balance import apply_gray_world_robust
                        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
                        img_bgr = apply_gray_world_robust(
                            img_bgr,
                            low_pct=self.wb_config.get('gray_world_low_pct', 5),
                            high_pct=self.wb_config.get('gray_world_high_pct', 95)
                        )
                        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
                    elif wb_mode == 'manual' and self.wb_config.get('apply_software_gains', False):
                        # Optional: apply software gains on top of SDK WB
                        from services.color_balance import apply_manual_gains
                        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
                        img_bgr = apply_manual_gains(
                            img_bgr,
                            red_gain=self.wb_config.get('manual_red_gain', 1.0),
                            blue_gain=self.wb_config.get('manual_blue_gain', 1.0)
                        )
                        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
                
                img = Image.fromarray(img_rgb, mode='RGB')
            except ImportError:
                # Fallback: simple debayering without OpenCV
                img_rgb = simple_debayer_rggb(img_array, width, height)
                img = Image.fromarray(img_rgb, mode='RGB')
            
            # Calculate image statistics for metadata
            img_array_rgb = np.array(img)
            mean_brightness = np.mean(img_array_rgb)
            median_brightness = np.median(img_array_rgb)
            min_pixel = np.min(img_array_rgb)
            max_pixel = np.max(img_array_rgb)
            std_dev = np.std(img_array_rgb)
            
            # Calculate percentiles for better exposure info
            p25 = np.percentile(img_array_rgb, 25)
            p75 = np.percentile(img_array_rgb, 75)
            p95 = np.percentile(img_array_rgb, 95)
            
            # Build metadata dictionary
            metadata = {
                'CAMERA': camera_info['Name'],
                'EXPOSURE': f"{self.exposure_seconds}s",
                'GAIN': str(self.gain),
                'TEMP': temperature,
                'TEMPERATURE': temperature,
                'TEMP_C': f"{temp_c}°C" if temp_c != "N/A" else "N/A",
                'TEMP_F': f"{temp_f}°F" if temp_f != "N/A" else "N/A",
                'RES': f"{width}x{height}",
                'CAPTURE AREA SIZE': f"{width} * {height}",
                'FILENAME': f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                'SESSION': datetime.now().strftime('%Y-%m-%d'),
                'DATETIME': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                # Image statistics
                'BRIGHTNESS': f"{mean_brightness:.1f}",
                'MEAN': f"{mean_brightness:.1f}",
                'MEDIAN': f"{median_brightness:.1f}",
                'MIN': f"{min_pixel}",
                'MAX': f"{max_pixel}",
                'STD_DEV': f"{std_dev:.2f}",
                'P25': f"{p25:.1f}",
                'P75': f"{p75:.1f}",
                'P95': f"{p95:.1f}"
            }
            
            return img, metadata
        
        except Exception as e:
            self.log(f"ERROR capturing frame: {e}")
            raise
    
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
                                    
                                    # Disconnect camera gracefully
                                    # Note: We use snapshot mode, not video mode - no need to stop_video_capture
                                    self.log("Closing camera connection...")
                                    self.camera.close()
                                    self.camera = None
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
                    if self.auto_exposure:
                        img_array = np.array(img)
                        self.adjust_exposure_auto(img_array)
                    
                    # Call callback with image and metadata
                    if self.on_frame_callback:
                        self.on_frame_callback(img, metadata)
                    
                    self.log(f"Captured frame: {metadata['FILENAME']}")
                    
                    # Reset error counter on successful capture
                    consecutive_errors = 0
                    
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
                    self.log(f"✗ ERROR in capture loop: {e}")
                    self.log(f"Consecutive errors: {consecutive_errors}/{max_reconnect_attempts}")
                    import traceback
                    self.log(f"Stack trace: {traceback.format_exc()}")
                    
                    # Try to recover from camera disconnect
                    if consecutive_errors <= max_reconnect_attempts:
                        self.log(f"Initiating reconnection attempt {consecutive_errors}/{max_reconnect_attempts}...")
                        try:
                            # Clean up existing camera first
                            if self.camera:
                                self.log("Cleaning up existing camera connection...")
                                # Note: We use snapshot mode, not video mode - no need to stop_video_capture
                                try:
                                    self.camera.close()
                                    self.log("Closed camera")
                                except Exception as close_err:
                                    self.log(f"Camera already closed: {close_err}")
                                finally:
                                    self.camera = None
                                    self.log("Camera reference cleared")
                            
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
        
        # Wait for capture thread to finish
        if self.capture_thread and self.capture_thread.is_alive():
            self.log("Waiting for capture thread to finish...")
            self.capture_thread.join(timeout=10.0)  # Increased timeout for long exposures
            
            if self.capture_thread.is_alive():
                self.log("Warning: Capture thread did not finish in time")
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
        
        # Run calibration using the calibration manager
        success = self.calibration_manager.run_calibration(max_attempts=15)
        
        # Update our exposure from calibration manager
        self.exposure_seconds = self.calibration_manager.exposure_seconds
        
        self.calibration_complete = True
        self.calibration_mode = False
    
    def adjust_exposure_auto(self, img_array):
        """Adjust exposure based on image brightness with intelligent step sizing"""
        if not self.auto_exposure or not self.calibration_manager:
            return
        
        # Use calibration manager to adjust exposure
        self.calibration_manager.adjust_exposure_auto(img_array)
        
        # Update our exposure from calibration manager
        self.exposure_seconds = self.calibration_manager.exposure_seconds
