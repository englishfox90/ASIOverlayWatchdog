"""
Camera connection management for ZWO ASI cameras

Handles SDK initialization, camera detection, connection/reconnection, and configuration.
This module is used internally by ZWOCamera - do not import directly.
"""
import os
import time
import threading
from typing import Optional, List, Dict, Callable, Any


class CameraConnection:
    """
    Manages ZWO ASI SDK and camera connection lifecycle.
    
    This class handles:
    - SDK initialization and reset
    - Camera detection and enumeration
    - Camera connection with retry logic
    - Camera configuration (gain, exposure, WB, etc.)
    - Safe reconnection after disconnects
    """
    
    def __init__(self, sdk_path: Optional[str] = None, logger: Optional[Callable[[str], None]] = None):
        """
        Initialize connection manager.
        
        Args:
            sdk_path: Path to ASICamera2.dll (optional, will search defaults)
            logger: Callback function for logging messages
        """
        self.sdk_path = sdk_path
        self._logger = logger
        
        # SDK state
        self.asi = None
        self.camera = None
        self.cameras: List[Dict[str, Any]] = []
        
        # Camera identification for reconnection
        self.camera_name: Optional[str] = None
        self.camera_index: int = 0
        
        # Camera capabilities (populated on connect)
        self.camera_info: dict = {}
        self.supports_raw16: bool = False
        self.bit_depth: int = 8  # Sensor ADC bit depth
        
        # Current capture mode
        self.current_image_type = None  # ASI_IMG_RAW8 or ASI_IMG_RAW16
        self.current_bit_depth: int = 8  # 8 for RAW8, 16 for RAW16
        
        # Thread safety
        self._cleanup_lock = threading.Lock()
        
        # Callback for persisting camera name to config
        self.config_callback: Optional[Callable[[str, Any], None]] = None
    
    def log(self, message: str) -> None:
        """Log message via callback or print"""
        if self._logger:
            self._logger(message)
        else:
            print(message)
    
    # =========================================================================
    # SDK Initialization
    # =========================================================================
    
    def initialize_sdk(self) -> bool:
        """
        Initialize the ZWO ASI SDK.
        
        Returns:
            True if successful, False otherwise
        """
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
    
    def reset_sdk_completely(self) -> bool:
        """
        Completely reset the SDK state (nuclear option).
        Use this when SDK gets into an inconsistent state.
        
        Returns:
            True if successful, False otherwise
        """
        self.log("=== Complete SDK Reset ===")
        
        try:
            # Close camera if connected
            if self.camera:
                self.log("Disconnecting camera before SDK reset...")
                self.disconnect()
            
            # Clear SDK reference
            self.log("Clearing SDK reference...")
            self.asi = None
            
            # Wait for cleanup
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
    
    # =========================================================================
    # Camera Detection
    # =========================================================================
    
    def detect_cameras(self) -> List[Dict[str, Any]]:
        """
        Detect connected ZWO cameras.
        
        Returns:
            List of camera info dicts with 'index' and 'name' keys
        """
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
    
    # =========================================================================
    # Camera Connection
    # =========================================================================
    
    def connect(self, camera_index: int = 0, settings: Optional[Dict[str, Any]] = None) -> bool:
        """
        Connect to a specific camera.
        
        Args:
            camera_index: Index of camera to connect to
            settings: Optional dict with camera settings (gain, exposure_sec, wb_r, wb_b, etc.)
            
        Returns:
            True if successful, False otherwise
        """
        self.log(f"=== Connecting to Camera (Index: {camera_index}) ===")
        
        if not self.asi:
            self.log("SDK not initialized, initializing now...")
            if not self.initialize_sdk():
                self.log("Connection failed: SDK initialization failed")
                return False
        
        try:
            if self.camera:
                self.log("Existing camera connection detected, disconnecting first...")
                self.disconnect()
            
            # Add delay to allow SDK cleanup (especially important after other apps like ASICap)
            time.sleep(0.5)  # Increased from 0.2s
            
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
                        if attempt == 1:
                            self.log(f"⚠ If you recently used ASICap or other ZWO software, please wait 10-15 seconds before retrying")
                        self.log(f"Waiting 1.0s before retry...")
                        time.sleep(1.0)  # Increased from 0.5s
                    else:
                        # Final attempt failed - re-raise the exception
                        raise
            
            camera_info = self.camera.get_camera_property()
            
            # Store camera name for future reconnection
            self.camera_name = camera_info['Name']
            self.camera_index = camera_index
            
            # Save camera name to config for persistence across restarts
            if self.config_callback:
                self.config_callback('zwo_selected_camera_name', self.camera_name)
                self.log(f"Saved camera name to config: {self.camera_name}")
            
            # Store camera capabilities for later access
            self.camera_info = camera_info
            self.supports_raw16 = 2 in camera_info.get('SupportedVideoFormat', [0])  # ASI_IMG_RAW16 = 2
            self.bit_depth = camera_info.get('BitDepth', 8)
            
            self.log(f"✓ Connected to camera: {camera_info['Name']}")
            self.log(f"  Camera ID: {camera_info.get('CameraID', 'N/A')}")
            self.log(f"  Max Resolution: {camera_info['MaxWidth']}x{camera_info['MaxHeight']}")
            self.log(f"  Pixel Size: {camera_info['PixelSize']} µm")
            self.log(f"  Sensor ADC: {self.bit_depth}-bit")
            self.log(f"  RAW16 Support: {'Yes' if self.supports_raw16 else 'No'}")
            
            # Get controls info
            controls = self.camera.get_controls()
            self.log(f"  Available controls: {len(controls)}")
            
            # Brief stabilization delay - camera needs time to fully initialize
            # This helps prevent "Camera closed" errors immediately after connection
            time.sleep(0.3)
            
            # Apply settings if provided (sets ROI, gain, exposure, etc.)
            if settings:
                self.configure(settings)
            else:
                # CRITICAL: Always set ROI to full frame even without settings
                # Without this, camera may use default ROI causing resolution mismatch
                self.log("No settings provided - setting ROI to full frame (default)")
                self.camera.set_roi(
                    start_x=0, start_y=0,
                    width=camera_info['MaxWidth'],
                    height=camera_info['MaxHeight'],
                    bins=1,
                    image_type=self.asi.ASI_IMG_RAW8
                )
                self.camera.set_image_type(self.asi.ASI_IMG_RAW8)
                self.log(f"  ROI: Full frame {camera_info['MaxWidth']}x{camera_info['MaxHeight']}")
            
            self.log(f"✓ Camera connection successful")
            return True
        
        except Exception as e:
            self.log(f"✗ ERROR connecting to camera: {e}")
            import traceback
            self.log(f"Stack trace: {traceback.format_exc()}")
            
            # Add diagnostic information for "Invalid ID" errors
            if "Invalid ID" in str(e):
                self._log_invalid_id_diagnostics(camera_index)
            
            return False
    
    def _log_invalid_id_diagnostics(self, camera_index: int) -> None:
        """Log diagnostic information for Invalid ID errors"""
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
    
    def _find_camera_index(self, cameras: List[Dict[str, Any]], camera_name: Optional[str]) -> int:
        """Find camera index by name, or return first camera index if not found."""
        if camera_name:
            for cam in cameras:
                if camera_name in cam['name']:
                    self.log(f"✓ Found camera '{camera_name}' at index {cam['index']}")
                    return cam['index']
            self.log(f"⚠ Warning: Could not find camera '{camera_name}' by name")
        
        # Fall back to first camera
        self.log(f"Using first available camera at index {cameras[0]['index']}: {cameras[0]['name']}")
        return cameras[0]['index']
    
    def reconnect_safe(self, target_camera_name: Optional[str] = None,
                       settings: Optional[Dict[str, Any]] = None) -> bool:
        """
        Safely reconnect to camera by re-detecting available cameras first.
        
        Args:
            target_camera_name: Name of camera to reconnect to (defaults to last connected)
            settings: Camera settings dict to apply after reconnection (ROI, gain, etc.)
                     CRITICAL: Without settings, camera may use default ROI causing
                     resolution mismatch and reshape errors during capture.
        """
        self.log("=== Safe Camera Reconnection ===")
        camera_to_find = target_camera_name or self.camera_name
        
        # Detect cameras (with SDK reset fallback)
        detected = self.detect_cameras()
        if not detected:
            self.log("✗ No cameras detected, attempting SDK reset...")
            self.asi = None
            if not self.initialize_sdk():
                return False
            detected = self.detect_cameras()
            if not detected:
                self.log("✗ No cameras detected even after SDK reset")
                return False
        
        # Find target camera
        target_index = self._find_camera_index(detected, camera_to_find)
        self.camera_index = target_index
        
        # Connect with settings (with SDK reset fallback on failure)
        if self.connect(target_index, settings):
            return True
        
        self.log("⚠ Connection failed, attempting complete SDK reset...")
        if not self.reset_sdk_completely():
            return False
        
        detected = self.detect_cameras()
        if not detected:
            self.log("✗ No cameras detected after SDK reset")
            return False
        
        target_index = self._find_camera_index(detected, camera_to_find)
        self.camera_index = target_index
        return self.connect(target_index, settings)
    
    # =========================================================================
    # Camera Configuration
    # =========================================================================
    
    def _validate_control(self, controls, control_type, value, name):
        """Validate and clamp a control value to camera's supported range."""
        ctrl = next((c for c in controls.values() if c['ControlType'] == control_type), None)
        if ctrl:
            validated = max(ctrl['MinValue'], min(ctrl['MaxValue'], value))
            if validated != value:
                self.log(f"  ⚠ {name} {value} out of range [{ctrl['MinValue']}-{ctrl['MaxValue']}], using {validated}")
            return validated, ctrl
        return value, None

    def configure(self, settings: Dict[str, Any]) -> None:
        """Configure camera settings."""
        if not self.camera:
            self.log("Cannot configure: camera not connected")
            return
        
        self.log("Configuring camera settings...")
        
        try:
            camera_info = self.camera.get_camera_property()
            controls = self.camera.get_controls()
            
            # Set gain with range validation
            if 'gain' in settings:
                gain, ctrl = self._validate_control(controls, self.asi.ASI_GAIN, settings['gain'], "Gain")
                self.camera.set_control_value(self.asi.ASI_GAIN, gain)
                rng = f" (range: {ctrl['MinValue']}-{ctrl['MaxValue']})" if ctrl else ""
                self.log(f"  Gain: {gain}{rng}")
            
            # Set exposure with range validation
            if 'exposure_sec' in settings:
                exposure_us = int(settings['exposure_sec'] * 1000000)
                exposure_us, ctrl = self._validate_control(controls, self.asi.ASI_EXPOSURE, exposure_us, "Exposure")
                self.camera.set_control_value(self.asi.ASI_EXPOSURE, exposure_us)
                self.log(f"  Exposure: {exposure_us/1000000}s ({exposure_us/1000}ms)")
            
            # Configure white balance
            self._configure_white_balance(settings)
            
            # Set other controls
            self.camera.set_control_value(self.asi.ASI_BANDWIDTHOVERLOAD, 40)
            if 'offset' in settings:
                self.camera.set_control_value(self.asi.ASI_BRIGHTNESS, settings['offset'])
            
            # Set flip
            flip = settings.get('flip', 0)
            if flip in (1, 3):
                self.camera.set_control_value(self.asi.ASI_FLIP, 1)
            if flip in (2, 3):
                self.camera.set_control_value(self.asi.ASI_FLIP, 2)
            
            # Determine image type (RAW8 or RAW16)
            use_raw16 = settings.get('use_raw16', False) and self.supports_raw16
            image_type = self.asi.ASI_IMG_RAW16 if use_raw16 else self.asi.ASI_IMG_RAW8
            self.current_image_type = image_type
            self.current_bit_depth = 16 if use_raw16 else 8
            
            # Set ROI to full frame
            self.camera.set_roi(start_x=0, start_y=0, width=camera_info['MaxWidth'], 
                               height=camera_info['MaxHeight'], bins=1, image_type=image_type)
            self.camera.set_image_type(image_type)
            
            mode_str = "RAW16" if use_raw16 else "RAW8"
            self.log(f"  ROI: Full frame {camera_info['MaxWidth']}x{camera_info['MaxHeight']} ({mode_str})")
            self.log("Camera configuration applied")
            
        except Exception as e:
            self.log(f"Error configuring camera: {e}")
    
    def _configure_white_balance(self, settings: Dict[str, Any]) -> None:
        """Configure white balance based on mode."""
        wb_mode = settings.get('wb_mode', 'asi_auto')
        
        if wb_mode == 'asi_auto':
            try:
                self.camera.set_control_value(self.asi.ASI_AUTO_MAX_BRIGHTNESS, 1)
                self.log("  White balance: ASI Auto")
            except:
                pass
        else:
            try:
                self.camera.set_control_value(self.asi.ASI_AUTO_MAX_BRIGHTNESS, 0)
            except:
                pass
            
            if wb_mode == 'manual':
                wb_r, wb_b = settings.get('wb_r', 75), settings.get('wb_b', 99)
                self.camera.set_control_value(self.asi.ASI_WB_R, wb_r)
                self.camera.set_control_value(self.asi.ASI_WB_B, wb_b)
                self.log(f"  White balance: Manual (R={wb_r}, B={wb_b})")
            elif wb_mode == 'gray_world':
                self.camera.set_control_value(self.asi.ASI_WB_R, 50)
                self.camera.set_control_value(self.asi.ASI_WB_B, 50)
                self.log("  White balance: Gray World (software)")
    
    # =========================================================================
    # Camera Disconnection
    # =========================================================================
    
    def disconnect(self, stop_exposure_callback: Optional[Callable[[], None]] = None) -> None:
        """
        Disconnect from camera gracefully (idempotent - safe to call multiple times).
        
        CRITICAL: Resets camera to factory defaults before closing to prevent SDK
        contamination that causes other apps (like NINA) to see wrong camera properties.
        
        Args:
            stop_exposure_callback: Optional callback to stop any in-progress exposure
        """
        with self._cleanup_lock:
            if not self.camera:
                self.log("Disconnect called but camera already disconnected")
                return
            
            self.log("=== Disconnecting Camera ===")
            
            try:
                # Call stop exposure callback if provided
                if stop_exposure_callback:
                    try:
                        stop_exposure_callback()
                    except Exception as e:
                        self.log(f"Exposure stop callback error: {e}")
                
                # CRITICAL: Reset camera properties to factory defaults BEFORE closing
                # This prevents SDK state contamination that affects other applications
                try:
                    self.log("Resetting camera to factory defaults...")
                    camera_info = self.camera.get_camera_property()
                    
                    # Reset ROI to full frame (most important - prevents size errors)
                    self.camera.set_roi(
                        start_x=0, 
                        start_y=0,
                        width=camera_info['MaxWidth'],
                        height=camera_info['MaxHeight'],
                        bins=1,
                        image_type=self.asi.ASI_IMG_RAW8
                    )
                    self.log(f"  ✓ ROI reset to full frame: {camera_info['MaxWidth']}x{camera_info['MaxHeight']}")
                    
                    # Reset common controls to safe defaults
                    try:
                        self.camera.set_control_value(self.asi.ASI_GAIN, 0)
                        self.camera.set_control_value(self.asi.ASI_EXPOSURE, 100000)  # 100ms
                        self.camera.set_control_value(self.asi.ASI_WB_R, 52)  # Factory default
                        self.camera.set_control_value(self.asi.ASI_WB_B, 95)  # Factory default
                        self.camera.set_control_value(self.asi.ASI_BRIGHTNESS, 50)  # Mid-range offset
                        self.camera.set_control_value(self.asi.ASI_FLIP, 0)  # No flip
                        self.camera.set_control_value(self.asi.ASI_AUTO_MAX_GAIN, 0)  # Disable auto
                        self.camera.set_control_value(self.asi.ASI_AUTO_MAX_EXP, 0)  # Disable auto
                        self.camera.set_control_value(self.asi.ASI_AUTO_TARGET_BRIGHTNESS, 100)
                        self.log("  ✓ Camera controls reset to factory defaults")
                    except Exception as e:
                        self.log(f"  ⚠ Some controls could not be reset (camera may be monochrome): {e}")
                    
                except Exception as e:
                    self.log(f"⚠ Warning: Could not reset camera properties: {e}")
                    # Continue with disconnect even if reset fails
                
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
                self.log("Camera reference cleared")
    
    # =========================================================================
    # Properties
    # =========================================================================
    
    @property
    def is_connected(self) -> bool:
        """Check if camera is connected"""
        return self.camera is not None
    
    def get_camera_property(self) -> Optional[Dict[str, Any]]:
        """Get camera properties if connected"""
        if self.camera:
            return self.camera.get_camera_property()
        return None
    
    def get_controls(self) -> Optional[Dict[str, Any]]:
        """Get camera controls if connected"""
        if self.camera:
            return self.camera.get_controls()
        return None
