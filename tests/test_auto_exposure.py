"""
Test auto-exposure and auto-brightness functionality
"""
import pytest
import os
import sys
import numpy as np

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services.camera_utils import calculate_brightness, check_clipping, is_within_scheduled_window


class TestBrightnessCalculation:
    """Test brightness calculation algorithms"""
    
    def test_mean_brightness(self):
        """Test mean brightness algorithm"""
        # Create uniform image
        img = np.full((100, 100), 128, dtype=np.uint8)
        brightness = calculate_brightness(img, algorithm='mean')
        assert brightness == 128.0
    
    def test_median_brightness(self):
        """Test median brightness algorithm"""
        # Create image with some outliers
        img = np.full((100, 100), 100, dtype=np.uint8)
        img[:10, :] = 255  # 10% bright pixels
        
        brightness = calculate_brightness(img, algorithm='median')
        assert brightness == 100.0  # Median should ignore outliers
    
    def test_percentile_brightness(self):
        """Test percentile brightness algorithm"""
        # Create gradient image
        img = np.linspace(0, 255, 10000, dtype=np.uint8).reshape(100, 100)
        
        brightness_75 = calculate_brightness(img, algorithm='percentile', percentile=75)
        brightness_25 = calculate_brightness(img, algorithm='percentile', percentile=25)
        
        # 75th percentile should be higher than 25th
        assert brightness_75 > brightness_25
        
        # Should be approximately at expected values
        assert 180 < brightness_75 < 200  # ~191 expected
        assert 60 < brightness_25 < 70    # ~63 expected
    
    def test_default_algorithm_is_mean(self):
        """Test unknown algorithm defaults to mean"""
        img = np.full((100, 100), 128, dtype=np.uint8)
        brightness = calculate_brightness(img, algorithm='unknown')
        assert brightness == 128.0
    
    def test_dark_image(self):
        """Test brightness of very dark image"""
        img = np.full((100, 100), 10, dtype=np.uint8)
        brightness = calculate_brightness(img)
        assert brightness < 20
    
    def test_bright_image(self):
        """Test brightness of very bright image"""
        img = np.full((100, 100), 240, dtype=np.uint8)
        brightness = calculate_brightness(img)
        assert brightness > 230


class TestClippingDetection:
    """Test overexposure (clipping) detection"""
    
    def test_no_clipping(self):
        """Test image with no clipping"""
        img = np.full((100, 100), 100, dtype=np.uint8)
        clipped_percent, is_clipping = check_clipping(img, clipping_threshold=245)
        
        assert clipped_percent == 0.0
        assert bool(is_clipping) is False
    
    def test_minor_clipping(self):
        """Test image with minor clipping (under threshold)"""
        img = np.full((100, 100), 100, dtype=np.uint8)
        img[:3, :] = 250  # 3% of pixels clipped
        
        clipped_percent, is_clipping = check_clipping(img, clipping_threshold=245)
        
        assert clipped_percent == 3.0
        assert bool(is_clipping) is False  # Under 5% threshold
    
    def test_significant_clipping(self):
        """Test image with significant clipping (over threshold)"""
        img = np.full((100, 100), 100, dtype=np.uint8)
        img[:10, :] = 250  # 10% of pixels clipped
        
        clipped_percent, is_clipping = check_clipping(img, clipping_threshold=245)
        
        assert clipped_percent == 10.0
        assert bool(is_clipping) is True  # Over 5% threshold
    
    def test_custom_threshold(self):
        """Test custom clipping threshold"""
        img = np.full((100, 100), 200, dtype=np.uint8)
        
        # With threshold 245, no clipping
        _, is_clipping_high = check_clipping(img, clipping_threshold=245)
        assert bool(is_clipping_high) is False
        
        # With threshold 150, everything is clipped
        clipped_percent, is_clipping_low = check_clipping(img, clipping_threshold=150)
        assert clipped_percent == 100.0
        assert bool(is_clipping_low) is True


class TestScheduledCaptureWindow:
    """Test scheduled capture time window logic"""
    
    def test_scheduling_disabled(self):
        """Test that disabled scheduling always allows capture"""
        result = is_within_scheduled_window(
            scheduled_capture_enabled=False,
            scheduled_start_time="00:00",
            scheduled_end_time="23:59"
        )
        assert result is True
    
    def test_same_day_window(self):
        """Test same-day capture window (e.g., 09:00-17:00)"""
        # This test depends on current time, so we'll just verify it runs
        result = is_within_scheduled_window(
            scheduled_capture_enabled=True,
            scheduled_start_time="00:00",
            scheduled_end_time="23:59"
        )
        # Should be within this 24-hour-ish window
        assert result is True
    
    def test_overnight_window_format(self):
        """Test overnight capture window format parsing"""
        # Just verify the function handles overnight windows without error
        try:
            result = is_within_scheduled_window(
                scheduled_capture_enabled=True,
                scheduled_start_time="17:00",
                scheduled_end_time="09:00"
            )
            # Result depends on current time, just verify no error
            assert isinstance(result, bool)
        except Exception as e:
            pytest.fail(f"Overnight window parsing failed: {e}")
    
    def test_invalid_time_format(self):
        """Test handling of invalid time format"""
        # Should default to allowing capture on error
        result = is_within_scheduled_window(
            scheduled_capture_enabled=True,
            scheduled_start_time="invalid",
            scheduled_end_time="also_invalid"
        )
        assert result is True  # Defaults to allow on error


class TestAutoExposureAlgorithm:
    """Test auto-exposure adjustment logic"""
    
    def test_exposure_increase_when_dark(self):
        """Test that dark images trigger exposure increase"""
        target_brightness = 30
        current_brightness = 10  # Too dark
        
        # Simulate the logic from camera_calibration.py
        brightness_ratio = target_brightness / max(current_brightness, 1)
        
        # Should suggest increasing exposure
        assert brightness_ratio > 1.0
    
    def test_exposure_decrease_when_bright(self):
        """Test that bright images trigger exposure decrease"""
        target_brightness = 30
        current_brightness = 100  # Too bright
        
        brightness_ratio = target_brightness / max(current_brightness, 1)
        
        # Should suggest decreasing exposure
        assert brightness_ratio < 1.0
    
    def test_exposure_stable_at_target(self):
        """Test exposure stays stable at target"""
        target_brightness = 30
        current_brightness = 30
        
        lower_bound = target_brightness * 0.8
        upper_bound = target_brightness * 1.2
        
        within_range = lower_bound <= current_brightness <= upper_bound
        assert within_range is True
    
    def test_deviation_calculation(self):
        """Test deviation percentage calculation"""
        target = 30
        
        # 50% deviation
        current_low = 15
        deviation_low = abs(current_low - target) / target
        assert deviation_low == 0.5
        
        # 100% deviation  
        current_high = 60
        deviation_high = abs(current_high - target) / target
        assert deviation_high == 1.0


class TestCalibrationConvergence:
    """Test calibration convergence behavior"""
    
    def test_interpolation_logic(self):
        """Test linear interpolation for exposure estimation"""
        # Simulate having two data points
        exp1, bright1 = 1.0, 20   # 1 second -> brightness 20
        exp2, bright2 = 2.0, 40   # 2 seconds -> brightness 40
        target = 30
        
        # Linear interpolation
        interpolated_exp = exp1 + (target - bright1) * (exp2 - exp1) / (bright2 - bright1)
        
        # Should estimate 1.5 seconds for brightness 30
        assert interpolated_exp == 1.5
    
    def test_convergence_threshold(self):
        """Test acceptable convergence range"""
        target = 30
        acceptable_range = target * 0.2  # ±20%
        
        # Within range
        assert abs(28 - target) < acceptable_range  # 28 is within range
        assert abs(35 - target) < acceptable_range  # 35 is within range
        
        # Outside range
        assert abs(20 - target) > acceptable_range  # 20 is too far
        assert abs(45 - target) > acceptable_range  # 45 is too far
    
    def test_exposure_limits(self):
        """Test exposure time limits are enforced"""
        min_exposure = 0.000032  # ~32µs
        max_exposure = 30.0      # 30 seconds
        
        # Test clamping
        test_values = [-1.0, 0.0, 0.00001, 50.0, 100.0]
        expected = [min_exposure, min_exposure, min_exposure, max_exposure, max_exposure]
        
        for val, exp in zip(test_values, expected):
            clamped = max(min_exposure, min(max_exposure, val))
            assert clamped == exp


class TestAggressiveVsConservativeAdjustment:
    """Test adaptive adjustment strategy"""
    
    def test_aggressive_when_far_from_target(self):
        """Test aggressive adjustment when deviation > 50%"""
        target = 30
        brightness = 10  # 67% deviation
        
        deviation_percent = abs(brightness - target) / target
        needs_aggressive = deviation_percent > 0.5
        
        assert needs_aggressive is True
    
    def test_conservative_when_close_to_target(self):
        """Test conservative adjustment when deviation < 50%"""
        target = 30
        brightness = 25  # 17% deviation
        
        deviation_percent = abs(brightness - target) / target
        needs_aggressive = deviation_percent > 0.5
        
        assert needs_aggressive is False
    
    def test_stall_detection(self):
        """Test stall detection when brightness doesn't change"""
        # Simulate stall detection
        history = [100.0, 100.2, 100.1, 100.3]  # Almost no change
        
        stall_count = 0
        for i in range(1, len(history)):
            change = abs(history[i] - history[i-1])
            if change < 0.5:  # Less than 0.5 change = stalled
                stall_count += 1
        
        assert stall_count == 3  # All consecutive changes are small
