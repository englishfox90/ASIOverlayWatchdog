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


class ZWOCamera:
    """Interface to ZWO ASI camera using zwoasi library"""
    
    def __init__(self, sdk_path=None, camera_index=0, exposure_sec=1.0, gain=100,
                 white_balance_r=75, white_balance_b=99, offset=20, flip=0,
                 auto_exposure=False, max_exposure_sec=30.0, auto_wb=False,
                 wb_mode='asi_auto', wb_config=None, bayer_pattern='BGGR',
                 scheduled_capture_enabled=False, scheduled_start_time="17:00",
                 scheduled_end_time="09:00", status_callback=None):
        self.sdk_path = sdk_path
        self.camera_index = camera_index
        self.camera = None
        self.asi = None
        self.cameras = []
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
        self.target_brightness = 100  # Target mean brightness for auto exposure
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
        if not self.scheduled_capture_enabled:
            return True  # Always capture if scheduling is disabled
        
        try:
            from datetime import datetime
            now = datetime.now()
            current_time = now.time()
            
            # Parse start and end times
            start_hour, start_min = map(int, self.scheduled_start_time.split(':'))
            end_hour, end_min = map(int, self.scheduled_end_time.split(':'))
            
            start_time = now.replace(hour=start_hour, minute=start_min, second=0, microsecond=0).time()
            end_time = now.replace(hour=end_hour, minute=end_min, second=0, microsecond=0).time()
            
            # Check if this is an overnight window (e.g., 17:00 - 09:00)
            if start_time > end_time:
                # Overnight: capture if after start OR before end (exclusive)
                return current_time >= start_time or current_time < end_time
            else:
                # Same day: capture if between start and end (end exclusive)
                return start_time <= current_time < end_time
                
        except Exception as e:
            self.log(f"Error checking scheduled window: {e}")
            return True  # Default to allowing capture on error
    
    def initialize_sdk(self):
        """Initialize the ZWO ASI SDK"""
        try:
            import zwoasi as asi
            self.asi = asi
            
            if self.sdk_path and os.path.exists(self.sdk_path):
                asi.init(self.sdk_path)
                self.log(f"ZWO SDK initialized from: {self.sdk_path}")
            else:
                # Try default locations
                if os.path.exists('ASICamera2.dll'):
                    asi.init('ASICamera2.dll')
                    self.log("ZWO SDK initialized from: ASICamera2.dll")
                else:
                    self.log("ERROR: ASICamera2.dll not found. Please configure SDK path.")
                    return False
            
            return True
        
        except ImportError:
            self.log("ERROR: zwoasi library not installed. Run: pip install zwoasi")
            return False
        except Exception as e:
            self.log(f"ERROR initializing ZWO SDK: {e}")
            return False
    
    def detect_cameras(self):
        """Detect connected ZWO cameras"""
        if not self.asi:
            if not self.initialize_sdk():
                return []
        
        try:
            num_cameras = self.asi.get_num_cameras()
            self.cameras = []
            
            if num_cameras == 0:
                self.log("No ZWO cameras detected")
                return []
            
            self.log(f"Found {num_cameras} ZWO camera(s)")
            
            for i in range(num_cameras):
                camera_info = self.asi.list_cameras()[i]
                self.cameras.append({
                    'index': i,
                    'name': camera_info
                })
                self.log(f"  Camera {i}: {camera_info}")
            
            return self.cameras
        
        except Exception as e:
            self.log(f"ERROR detecting cameras: {e}")
            return []
    
    def connect_camera(self, camera_index=0):
        """Connect to a specific camera"""
        if not self.asi:
            if not self.initialize_sdk():
                return False
        
        try:
            if self.camera:
                self.disconnect_camera()
            
            self.camera = self.asi.Camera(camera_index)
            camera_info = self.camera.get_camera_property()
            
            self.log(f"Connected to: {camera_info['Name']}")
            self.log(f"  Max Resolution: {camera_info['MaxWidth']}x{camera_info['MaxHeight']}")
            self.log(f"  Pixel Size: {camera_info['PixelSize']} µm")
            
            # Get controls info
            controls = self.camera.get_controls()
            self.log(f"  Available controls: {len(controls)}")
            
            # Set initial camera settings
            self.camera.set_control_value(self.asi.ASI_GAIN, self.gain)
            self.camera.set_control_value(self.asi.ASI_EXPOSURE, int(self.exposure_seconds * 1000000))
            
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
            
            # Set image format to RAW8
            self.camera.set_image_type(self.asi.ASI_IMG_RAW8)
            
            return True
        
        except Exception as e:
            self.log(f"ERROR connecting to camera: {e}")
            return False
    
    def _configure_camera(self):
        """Configure camera settings (used for initial connection and reconnection)"""
        if not self.camera:
            return
        
        try:
            # Get camera info
            camera_info = self.camera.get_camera_property()
            
            # Set image format
            self.camera.set_image_type(self.asi.ASI_IMG_RAW8)
            
            # Set ROI to full frame (if needed during reconnection)
            # This is usually done in connect_camera, but helpful for reconnections
            
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
        """Disconnect from camera"""
        if self.camera:
            try:
                if self.is_capturing:
                    self.stop_capture()
                self.camera.close()
                self.log("Camera disconnected")
            except Exception as e:
                self.log(f"Error disconnecting camera: {e}")
            finally:
                self.camera = None
    
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
                status = self.camera.get_exposure_status()
                if status == self.asi.ASI_EXP_SUCCESS:
                    break
                elif status == self.asi.ASI_EXP_FAILED:
                    raise Exception("Exposure failed")
                
                # Update remaining time for UI (no logging)
                elapsed = time.time() - start_time
                self.exposure_remaining = max(0, self.exposure_seconds - elapsed)
                
                time.sleep(0.05)  # 50ms update rate for smoother countdown
            
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
                img_rgb = self.simple_debayer_rggb(img_array)
                img = Image.fromarray(img_rgb, mode='RGB')
            
            # Build metadata dictionary
            metadata = {
                'CAMERA': camera_info['Name'],
                'EXPOSURE': f"{self.exposure_seconds}s",
                'GAIN': str(self.gain),
                'TEMP': temperature,
                'TEMPERATURE': temperature,
                'TEMP_C': temp_c,
                'TEMP_F': temp_f,
                'RES': f"{width}x{height}",
                'CAPTURE AREA SIZE': f"{width} * {height}",
                'FILENAME': f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                'SESSION': datetime.now().strftime('%Y-%m-%d'),
                'DATETIME': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            return img, metadata
        
        except Exception as e:
            self.log(f"ERROR capturing frame: {e}")
            raise
    
    def capture_loop(self):
        """Background capture loop with automatic recovery and scheduled capture support"""
        self.log("Capture loop started")
        consecutive_errors = 0
        max_reconnect_attempts = 5
        last_schedule_log = None  # Track last schedule status to avoid log spam
        
        while self.is_capturing:
            try:
                # Check if we're within the scheduled capture window
                within_window = self.is_within_scheduled_window()
                
                if not within_window:
                    # Outside scheduled window - disconnect camera to reduce load
                    current_status = "outside_window"
                    if last_schedule_log != current_status:
                        self.log(f"Outside scheduled capture window ({self.scheduled_start_time} - {self.scheduled_end_time}). Disconnecting camera...")
                        last_schedule_log = current_status
                        
                        # Disconnect camera to reduce load during off-peak hours
                        if self.camera:
                            try:
                                self.camera.stop_video_capture()
                                self.camera.close()
                                self.camera = None
                                self.log("Camera disconnected during off-peak hours")
                                
                                # Update UI status to reflect disconnection
                                if self.status_callback:
                                    self.status_callback(f"Idle (off-peak until {self.scheduled_start_time})")
                            except Exception as e:
                                self.log(f"Error disconnecting camera: {e}")
                    
                    # Sleep and continue loop without capturing
                    time.sleep(self.capture_interval)
                    continue
                else:
                    # Within window - reconnect camera if needed
                    if last_schedule_log == "outside_window":
                        self.log(f"Entered scheduled capture window ({self.scheduled_start_time} - {self.scheduled_end_time}). Reconnecting camera...")
                        last_schedule_log = "inside_window"
                        
                        # Update UI status
                        if self.status_callback:
                            self.status_callback("Reconnecting for scheduled window...")
                        
                        # Reconnect camera for scheduled window
                        if not self.camera:
                            if not self.connect_camera():
                                self.log("ERROR: Failed to reconnect camera for scheduled window")
                                time.sleep(5)  # Wait before retrying
                                continue
                            self.log("Camera reconnected for scheduled captures")
                
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
                
                # Wait for next capture interval
                if self.is_capturing:  # Check again in case stopped during capture
                    time.sleep(self.capture_interval)
            
            except Exception as e:
                consecutive_errors += 1
                self.log(f"ERROR in capture loop: {e} (attempt {consecutive_errors}/{max_reconnect_attempts})")
                
                # Try to recover from camera disconnect
                if consecutive_errors <= max_reconnect_attempts:
                    self.log(f"Attempting to reconnect camera...")
                    try:
                        # Try to reconnect
                        if self.camera:
                            try:
                                self.camera.close()
                            except:
                                pass
                        
                        # Reinitialize camera
                        self.camera = self.asi.Camera(self.camera_index)
                        self._configure_camera()
                        self.log("Camera reconnected successfully")
                        consecutive_errors = 0  # Reset counter on successful reconnection
                        time.sleep(1.0)
                        continue
                    except Exception as reconnect_error:
                        self.log(f"Reconnection failed: {reconnect_error}")
                        # Exponential backoff: 2, 4, 8, 16, 32 seconds
                        backoff_time = min(2 ** consecutive_errors, 32)
                        self.log(f"Waiting {backoff_time}s before retry...")
                        time.sleep(backoff_time)
                else:
                    # Max attempts reached - stop capture
                    self.log(f"ERROR: Maximum reconnection attempts ({max_reconnect_attempts}) reached. Stopping capture.")
                    self.is_capturing = False
                    # Notify via callback that capture failed
                    if hasattr(self, 'on_error_callback') and self.on_error_callback:
                        self.on_error_callback("Camera disconnected - failed to reconnect after multiple attempts")
                    break
        
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
        """Stop continuous capture"""
        if not self.is_capturing:
            return
        
        self.is_capturing = False
        
        if self.capture_thread:
            self.capture_thread.join(timeout=5.0)
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
    
    def simple_debayer_rggb(self, bayer):
        """Simple debayering for RGGB Bayer pattern (fallback method)"""
        height, width = bayer.shape
        rgb = np.zeros((height, width, 3), dtype=np.uint8)
        
        # R channel (top-left pixels)
        rgb[0::2, 0::2, 0] = bayer[0::2, 0::2]
        rgb[0::2, 1::2, 0] = bayer[0::2, 0::2]
        rgb[1::2, 0::2, 0] = bayer[0::2, 0::2]
        rgb[1::2, 1::2, 0] = bayer[0::2, 0::2]
        
        # G channel (average of both green positions)
        rgb[0::2, 1::2, 1] = bayer[0::2, 1::2]
        rgb[1::2, 0::2, 1] = bayer[1::2, 0::2]
        rgb[0::2, 0::2, 1] = (bayer[0::2, 1::2].astype(int) + bayer[1::2, 0::2].astype(int)) // 2
        rgb[1::2, 1::2, 1] = (bayer[0::2, 1::2].astype(int) + bayer[1::2, 0::2].astype(int)) // 2
        
        # B channel (bottom-right pixels)
        rgb[1::2, 1::2, 2] = bayer[1::2, 1::2]
        rgb[0::2, 0::2, 2] = bayer[1::2, 1::2]
        rgb[0::2, 1::2, 2] = bayer[1::2, 1::2]
        rgb[1::2, 0::2, 2] = bayer[1::2, 1::2]
        
        return rgb
    
    def adjust_exposure_auto(self, img_array):
        """Adjust exposure based on image brightness with intelligent step sizing"""
        if not self.auto_exposure:
            return
        
        # Calculate mean brightness
        mean_brightness = np.mean(img_array)
        
        # Calculate how far off we are from target
        brightness_ratio = mean_brightness / self.target_brightness
        
        # Adjust exposure to reach target brightness
        if mean_brightness < self.target_brightness * 0.9:  # Too dark (below 90% of target)
            # Calculate adjustment factor based on how dark it is
            if brightness_ratio < 0.3:  # Very dark (< 30% of target)
                adjustment = 3.0  # Triple exposure
            elif brightness_ratio < 0.5:  # Dark (< 50% of target)
                adjustment = 2.0  # Double exposure
            elif brightness_ratio < 0.7:  # Somewhat dark (< 70% of target)
                adjustment = 1.5  # Increase by 50%
            else:  # Slightly dark (70-90% of target)
                adjustment = 1.2  # Increase by 20%
            
            new_exposure = min(self.exposure_seconds * adjustment, self.max_exposure)
            if new_exposure != self.exposure_seconds:
                # Check if we hit the max limit
                if new_exposure >= self.max_exposure:
                    self.log(f"Auto exposure: MAX LIMIT REACHED at {new_exposure*1000:.2f}ms (brightness: {mean_brightness:.1f}/{self.target_brightness})")
                else:
                    self.log(f"Auto exposure: increased to {new_exposure*1000:.2f}ms (brightness: {mean_brightness:.1f}/{self.target_brightness})")
                self.exposure_seconds = new_exposure
        
        elif mean_brightness > self.target_brightness * 1.1:  # Too bright (above 110% of target)
            # Calculate adjustment factor based on how bright it is
            if brightness_ratio > 3.0:  # Very bright (> 300% of target)
                adjustment = 0.33  # Reduce to 1/3
            elif brightness_ratio > 2.0:  # Bright (> 200% of target)
                adjustment = 0.5  # Halve exposure
            elif brightness_ratio > 1.5:  # Somewhat bright (> 150% of target)
                adjustment = 0.7  # Reduce by 30%
            else:  # Slightly bright (110-150% of target)
                adjustment = 0.85  # Reduce by 15%
            
            new_exposure = max(self.exposure_seconds * adjustment, 0.000032)  # Min 32µs
            if new_exposure != self.exposure_seconds:
                self.exposure_seconds = new_exposure
                self.log(f"Auto exposure: decreased to {new_exposure*1000:.2f}ms (brightness: {mean_brightness:.1f}/{self.target_brightness})")
