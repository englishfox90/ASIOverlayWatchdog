"""
Camera calibration and auto-exposure algorithms for ZWO ASI cameras
"""
import numpy as np
from .camera_utils import calculate_brightness, check_clipping


class CameraCalibration:
    """Handles camera calibration and auto-exposure adjustments"""
    
    def __init__(self, camera, asi, logger_callback=None):
        """
        Initialize calibration manager
        
        Args:
            camera: ZWO camera instance
            asi: ZWO ASI SDK instance
            logger_callback: Optional callback for logging
        """
        self.camera = camera
        self.asi = asi
        self.logger_callback = logger_callback
        
        # Auto-exposure settings
        self.target_brightness = 30
        self.max_exposure_sec = 30.0
        self.exposure_seconds = 1.0
        self.gain = 300
        
        # Algorithm settings
        self.exposure_algorithm = 'percentile'  # 'mean', 'median', or 'percentile'
        self.exposure_percentile = 75  # Use 75th percentile
        self.clipping_threshold = 245
        self.clipping_prevention = True
        
    def log(self, message):
        """Log message via callback"""
        if self.logger_callback:
            self.logger_callback(message)
        else:
            print(message)
    
    def run_calibration(self, max_attempts=15):
        """
        Rapid auto-exposure calibration before starting normal capture
        Uses intelligent exposure adjustments with interpolation to reach target brightness quickly
        
        Args:
            max_attempts: Maximum calibration attempts
            
        Returns:
            True if calibration successful, False otherwise
        """
        self.log("Starting rapid calibration...")
        
        # Track exposure/brightness pairs for interpolation
        calibration_history = []
        previous_brightness = None
        stalled_count = 0  # Track consecutive attempts with no brightness change
        
        for attempt in range(max_attempts):
            try:
                # REL-003: Use snapshot mode (consistent with capture_loop)
                # Start exposure
                self.camera.start_exposure()
                
                # Wait for exposure to complete
                import time
                timeout = self.exposure_seconds + 2.0
                start_time = time.time()
                
                while time.time() - start_time < timeout:
                    status = self.camera.get_exposure_status()
                    if status == self.asi.ASI_EXP_SUCCESS:
                        break
                    elif status == self.asi.ASI_EXP_FAILED:
                        raise Exception("Calibration exposure failed")
                    time.sleep(0.05)
                
                # Check for timeout
                if time.time() - start_time >= timeout:
                    raise Exception(f"Calibration exposure timeout ({timeout}s)")
                
                # Get the captured data
                data = self.camera.get_data_after_exposure()
                
                # Get camera dimensions for reshaping
                camera_info = self.camera.get_camera_property()
                width = camera_info['MaxWidth']
                height = camera_info['MaxHeight']
                
                # Convert to numpy array for brightness calculation
                img_array = np.frombuffer(data, dtype=np.uint8).reshape((height, width))
                
                # Calculate brightness
                brightness = calculate_brightness(
                    img_array, 
                    self.exposure_algorithm, 
                    self.exposure_percentile
                )
                
                # Detect stalled progress (brightness not changing enough)
                if previous_brightness is not None:
                    brightness_change = abs(brightness - previous_brightness)
                    if brightness_change < 0.5:  # Less than 0.5 change = stalled
                        stalled_count += 1
                    else:
                        stalled_count = 0
                
                previous_brightness = brightness
                
                # Store this measurement
                calibration_history.append((self.exposure_seconds, brightness))
                
                self.log(f"Calibration attempt {attempt + 1}/{max_attempts}: brightness={brightness:.1f} (target={self.target_brightness})")
                
                # Check if we're within acceptable range (±20% of target)
                if abs(brightness - self.target_brightness) < (self.target_brightness * 0.2):
                    self.log(f"Calibration complete! Final brightness: {brightness:.1f}")
                    return True
                
                # Try interpolation if we have at least 2 points with different brightness
                new_exposure = None
                if len(calibration_history) >= 2:
                    # Check if we have points on both sides of target
                    points_below = [(exp, b) for exp, b in calibration_history if b < self.target_brightness]
                    points_above = [(exp, b) for exp, b in calibration_history if b > self.target_brightness]
                    
                    if points_below and points_above:
                        # Get the closest point on each side
                        closest_below = max(points_below, key=lambda x: x[1])  # Highest brightness below target
                        closest_above = min(points_above, key=lambda x: x[1])  # Lowest brightness above target
                        
                        exp1, bright1 = closest_below
                        exp2, bright2 = closest_above
                        
                        # Linear interpolation: exposure = exp1 + (target - bright1) * (exp2 - exp1) / (bright2 - bright1)
                        if bright2 != bright1:
                            interpolated_exp = exp1 + (self.target_brightness - bright1) * (exp2 - exp1) / (bright2 - bright1)
                            
                            # Validate interpolated value is reasonable
                            if 0.000032 <= interpolated_exp <= self.max_exposure_sec:
                                new_exposure = interpolated_exp
                                self.log(f"  Using interpolation: {exp1*1000:.2f}ms (b={bright1:.0f}) <-> {exp2*1000:.2f}ms (b={bright2:.0f}) => {interpolated_exp*1000:.2f}ms")
                
                # If interpolation didn't work, use adaptive adjustment
                if new_exposure is None:
                    brightness_ratio = self.target_brightness / max(brightness, 1)  # Avoid divide by zero
                    
                    # Apply stall multiplier if progress has stalled
                    stall_multiplier = 1.0
                    if stalled_count >= 3:
                        # If stalled for 3+ attempts, be much more aggressive
                        stall_multiplier = 4.0
                        self.log(f"  Progress stalled ({stalled_count} attempts) - applying 4x multiplier")
                    elif stalled_count >= 2:
                        # If stalled for 2 attempts, increase aggressiveness
                        stall_multiplier = 2.5
                        self.log(f"  Progress stalled ({stalled_count} attempts) - applying 2.5x multiplier")
                    
                    # Use more conservative adjustments to avoid overshooting
                    if brightness < self.target_brightness * 0.5:
                        # Very dark - significant increase
                        adjustment_factor = min(brightness_ratio * 1.2 * stall_multiplier, 5.0)  # Increased cap with stall multiplier
                    elif brightness < self.target_brightness * 0.8:
                        # Somewhat dark - moderate increase
                        adjustment_factor = min(brightness_ratio * 0.9 * stall_multiplier, 2.0)
                    elif brightness > self.target_brightness * 2.0:
                        # Very bright - significant decrease
                        adjustment_factor = max(brightness_ratio * 0.8, 0.5)
                    elif brightness > self.target_brightness * 1.2:
                        # Somewhat bright - moderate decrease
                        adjustment_factor = max(brightness_ratio * 0.9, 0.7)
                    else:
                        # Close to target - fine tune
                        adjustment_factor = brightness_ratio * 0.95
                    
                    new_exposure = self.exposure_seconds * adjustment_factor
                    new_exposure = max(0.000032, min(self.max_exposure_sec, new_exposure))
                    self.log(f"  Adjusting exposure: {self.exposure_seconds*1000:.2f}ms -> {new_exposure*1000:.2f}ms (factor: {adjustment_factor:.2f})")
                
                self.exposure_seconds = new_exposure
                self.camera.set_control_value(self.asi.ASI_EXPOSURE, int(new_exposure * 1000000))
                
            except Exception as e:
                self.log(f"Calibration error on attempt {attempt + 1}: {e}")
                continue
        
        self.log(f"Calibration did not converge after {max_attempts} attempts. Continuing with current settings.")
        return False
    
    def adjust_exposure_auto(self, img_array):
        """
        Adjust exposure based on image brightness
        Uses configurable algorithm (mean/median/percentile) and prevents overexposure
        Automatically switches between aggressive and conservative adjustments based on deviation
        
        Args:
            img_array: Image as numpy array
        """
        try:
            # Calculate brightness using selected algorithm
            brightness = calculate_brightness(
                img_array, 
                self.exposure_algorithm, 
                self.exposure_percentile
            )
            
            # Check for clipping
            clipped_percent, is_clipping = check_clipping(img_array, self.clipping_threshold)
            
            # Calculate how far off target we are
            deviation_percent = abs(brightness - self.target_brightness) / self.target_brightness
            
            # Calculate acceptable range (±20% of target)
            lower_bound = self.target_brightness * 0.8
            upper_bound = self.target_brightness * 1.2
            
            # Determine if we need aggressive or conservative adjustment
            # If brightness is >50% off target, use aggressive adjustment (like calibration)
            # This handles sunset/sunrise or major lighting changes
            needs_aggressive_adjustment = deviation_percent > 0.5
            
            if brightness < lower_bound:
                # Image too dark - increase exposure
                # But respect clipping prevention
                if self.clipping_prevention and is_clipping:
                    self.log(f"Image dark but clipping detected ({clipped_percent:.1f}%) - not increasing exposure")
                    return
                
                if needs_aggressive_adjustment:
                    # Significant deviation - use aggressive adjustment
                    brightness_ratio = self.target_brightness / max(brightness, 1)
                    
                    if brightness < self.target_brightness * 0.3:
                        # Extremely dark - very aggressive increase
                        adjustment_factor = min(brightness_ratio * 1.5, 5.0)
                    elif brightness < self.target_brightness * 0.5:
                        # Very dark - aggressive increase  
                        adjustment_factor = min(brightness_ratio * 1.2, 3.0)
                    else:
                        # Moderately dark - moderate increase
                        adjustment_factor = min(brightness_ratio * 0.9, 2.0)
                    
                    new_exposure = self.exposure_seconds * adjustment_factor
                    new_exposure = min(new_exposure, self.max_exposure_sec)
                    
                    self.log(f"Auto-exposure AGGRESSIVE: {self.exposure_seconds*1000:.2f}ms -> {new_exposure*1000:.2f}ms (x{adjustment_factor:.2f}) brightness={brightness:.1f}, target={self.target_brightness}")
                else:
                    # Minor deviation - conservative adjustment
                    new_exposure = self.exposure_seconds * 1.3
                    new_exposure = min(new_exposure, self.max_exposure_sec)
                    self.log(f"Auto-exposure: increased to {new_exposure*1000:.2f}ms (brightness={brightness:.1f}, target={self.target_brightness})")
                
                if new_exposure != self.exposure_seconds:
                    self.exposure_seconds = new_exposure
                    self.camera.set_control_value(self.asi.ASI_EXPOSURE, int(new_exposure * 1000000))
            
            elif brightness > upper_bound:
                # Image too bright - decrease exposure
                
                if needs_aggressive_adjustment:
                    # Significant deviation - use aggressive adjustment
                    brightness_ratio = self.target_brightness / max(brightness, 1)
                    
                    if brightness > self.target_brightness * 3.0:
                        # Extremely bright - very aggressive decrease
                        adjustment_factor = max(brightness_ratio * 0.8, 0.2)
                    elif brightness > self.target_brightness * 2.0:
                        # Very bright - aggressive decrease
                        adjustment_factor = max(brightness_ratio * 0.9, 0.3)
                    else:
                        # Moderately bright - moderate decrease
                        adjustment_factor = max(brightness_ratio * 0.95, 0.5)
                    
                    new_exposure = self.exposure_seconds * adjustment_factor
                    new_exposure = max(new_exposure, 0.000032)
                    
                    self.log(f"Auto-exposure AGGRESSIVE: {self.exposure_seconds*1000:.2f}ms -> {new_exposure*1000:.2f}ms (x{adjustment_factor:.2f}) brightness={brightness:.1f}, target={self.target_brightness}")
                else:
                    # Minor deviation - conservative adjustment
                    new_exposure = self.exposure_seconds * 0.7
                    new_exposure = max(new_exposure, 0.000032)
                    self.log(f"Auto-exposure: decreased to {new_exposure*1000:.2f}ms (brightness={brightness:.1f}, target={self.target_brightness})")
                
                if new_exposure != self.exposure_seconds:
                    self.exposure_seconds = new_exposure
                    self.camera.set_control_value(self.asi.ASI_EXPOSURE, int(new_exposure * 1000000))
                    
                    if is_clipping:
                        self.log(f"  Clipping detected: {clipped_percent:.1f}% of pixels above {self.clipping_threshold}")
            else:
                # Within acceptable range - no adjustment needed
                self.log(f"Auto-exposure: maintaining {self.exposure_seconds*1000:.2f}ms (brightness={brightness:.1f} within target range)")
            
        except Exception as e:
            self.log(f"Error adjusting exposure: {e}")
    
    def update_settings(self, exposure_seconds=None, gain=None, target_brightness=None,
                       max_exposure_sec=None, algorithm=None, percentile=None,
                       clipping_threshold=None, clipping_prevention=None):
        """
        Update calibration settings
        
        Args:
            exposure_seconds: Exposure time in seconds
            gain: Gain value
            target_brightness: Target brightness (0-255)
            max_exposure_sec: Maximum exposure in seconds
            algorithm: Brightness algorithm ('mean', 'median', 'percentile')
            percentile: Percentile value for percentile algorithm
            clipping_threshold: Pixel value threshold for clipping detection
            clipping_prevention: Enable clipping prevention
        """
        if exposure_seconds is not None:
            self.exposure_seconds = exposure_seconds
        if gain is not None:
            self.gain = gain
        if target_brightness is not None:
            self.target_brightness = target_brightness
        if max_exposure_sec is not None:
            self.max_exposure_sec = max_exposure_sec
        if algorithm is not None:
            self.exposure_algorithm = algorithm
        if percentile is not None:
            self.exposure_percentile = percentile
        if clipping_threshold is not None:
            self.clipping_threshold = clipping_threshold
        if clipping_prevention is not None:
            self.clipping_prevention = clipping_prevention
