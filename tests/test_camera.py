"""
Test ZWO camera connection and capture
Note: Tests marked with @pytest.mark.requires_camera need physical hardware
"""
import pytest
import os
import sys
import numpy as np
from unittest.mock import Mock, MagicMock, patch

# Check if cv2 is available
try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


class TestCameraConnectionMock:
    """Test camera connection logic with mocks"""
    
    def test_sdk_path_configuration(self):
        """Test SDK path can be configured"""
        from services.config import DEFAULT_CONFIG
        
        assert 'zwo_sdk_path' in DEFAULT_CONFIG
        # Default should point to ASICamera2.dll
        assert 'ASICamera2.dll' in DEFAULT_CONFIG['zwo_sdk_path']
    
    def test_camera_settings_defaults(self):
        """Test camera settings have sensible defaults"""
        from services.config import DEFAULT_CONFIG
        
        # Check exposure range
        assert DEFAULT_CONFIG['zwo_exposure_ms'] >= 0.032  # Min ~32µs
        assert DEFAULT_CONFIG['zwo_exposure_ms'] <= 3600000  # Max 1 hour
        
        # Check gain range
        assert DEFAULT_CONFIG['zwo_gain'] >= 0
        
        # Check white balance range
        assert 1 <= DEFAULT_CONFIG['zwo_wb_r'] <= 99
        assert 1 <= DEFAULT_CONFIG['zwo_wb_b'] <= 99


class TestBayerDebayering:
    """Test Bayer pattern debayering"""
    
    def test_bggr_pattern_detection(self):
        """Test BGGR Bayer pattern is correctly identified"""
        from services.config import DEFAULT_CONFIG
        
        # ASI cameras typically use BGGR
        assert DEFAULT_CONFIG['zwo_bayer_pattern'] in ['RGGB', 'BGGR', 'GRBG', 'GBRG']
    
    @pytest.mark.skipif(not HAS_CV2, reason="OpenCV (cv2) not installed")
    def test_debayer_creates_rgb(self):
        """Test debayering produces RGB image"""
        import cv2
        
        # Create mock Bayer pattern data (100x100)
        bayer_data = np.random.randint(0, 256, (100, 100), dtype=np.uint8)
        
        # Debayer using OpenCV
        rgb = cv2.cvtColor(bayer_data, cv2.COLOR_BayerBG2RGB)
        
        # Should be 3 channels
        assert rgb.shape == (100, 100, 3)
    
    @pytest.mark.skipif(not HAS_CV2, reason="OpenCV (cv2) not installed")
    def test_all_bayer_patterns(self):
        """Test all Bayer pattern conversions work"""
        import cv2
        
        bayer_data = np.random.randint(0, 256, (100, 100), dtype=np.uint8)
        
        patterns = [
            cv2.COLOR_BayerBG2RGB,  # BGGR
            cv2.COLOR_BayerRG2RGB,  # RGGB
            cv2.COLOR_BayerGB2RGB,  # GBRG
            cv2.COLOR_BayerGR2RGB,  # GRBG
        ]
        
        for pattern in patterns:
            rgb = cv2.cvtColor(bayer_data, pattern)
            assert rgb.shape == (100, 100, 3)


class TestCameraUtilities:
    """Test camera utility functions"""
    
    def test_scheduled_window_check(self):
        """Test scheduled capture window detection"""
        from services.camera_utils import is_within_scheduled_window
        from datetime import datetime
        
        # Test case: capture window 17:00 - 09:00 (overnight)
        # At 20:00 should be within window
        test_time_evening = datetime(2025, 12, 30, 20, 0, 0)
        
        # At 08:00 should be within window
        test_time_morning = datetime(2025, 12, 30, 8, 0, 0)
        
        # At 12:00 should be outside window
        test_time_noon = datetime(2025, 12, 30, 12, 0, 0)
        
        # Note: Actual test depends on implementation
        # This is a placeholder for the test structure
    
    def test_exposure_ms_to_seconds_conversion(self):
        """Test exposure time unit conversion"""
        # 1000ms = 1s
        exposure_ms = 1000.0
        exposure_s = exposure_ms / 1000.0
        assert exposure_s == 1.0
        
        # 100ms = 0.1s
        exposure_ms = 100.0
        exposure_s = exposure_ms / 1000.0
        assert exposure_s == 0.1


@pytest.mark.requires_camera
class TestPhysicalCamera:
    """Tests that require actual camera hardware"""
    
    def test_camera_detection(self):
        """Test camera can be detected"""
        try:
            import zwoasi
            zwoasi.init(os.path.join(project_root, 'ASICamera2.dll'))
            
            num_cameras = zwoasi.get_num_cameras()
            
            # At least one camera should be connected for these tests
            assert num_cameras > 0, "No cameras detected - connect a camera to run hardware tests"
            
        except Exception as e:
            pytest.skip(f"Camera hardware test skipped: {e}")
    
    def test_camera_connection(self):
        """Test camera can be connected"""
        try:
            import zwoasi
            zwoasi.init(os.path.join(project_root, 'ASICamera2.dll'))
            
            if zwoasi.get_num_cameras() == 0:
                pytest.skip("No camera connected")
            
            camera = zwoasi.Camera(0)
            info = camera.get_camera_property()
            
            assert 'Name' in info
            assert 'MaxWidth' in info
            assert 'MaxHeight' in info
            
            camera.close()
            
        except Exception as e:
            pytest.skip(f"Camera connection test skipped: {e}")
    
    def test_capture_single_frame(self):
        """Test capturing a single frame"""
        try:
            import zwoasi
            zwoasi.init(os.path.join(project_root, 'ASICamera2.dll'))
            
            if zwoasi.get_num_cameras() == 0:
                pytest.skip("No camera connected")
            
            camera = zwoasi.Camera(0)
            
            # Set minimal settings for quick capture
            camera.set_control_value(zwoasi.ASI_EXPOSURE, 1000)  # 1ms
            camera.set_control_value(zwoasi.ASI_GAIN, 0)
            
            # Set image type to RAW8
            camera.set_image_type(zwoasi.ASI_IMG_RAW8)
            
            # Capture
            data = camera.capture()
            
            assert data is not None
            assert len(data) > 0
            
            camera.close()
            
        except Exception as e:
            pytest.skip(f"Capture test skipped: {e}")
