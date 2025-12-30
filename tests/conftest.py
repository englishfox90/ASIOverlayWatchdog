"""
Pytest configuration and fixtures
"""
import pytest
import os
import sys
import tempfile
import shutil

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files"""
    temp_path = tempfile.mkdtemp(prefix="asiwd_test_")
    yield temp_path
    # Cleanup after test
    if os.path.exists(temp_path):
        shutil.rmtree(temp_path)


@pytest.fixture
def temp_config(temp_dir):
    """Create a temporary config file"""
    config_path = os.path.join(temp_dir, "config.json")
    return config_path


@pytest.fixture
def sample_image():
    """Create a sample test image"""
    from PIL import Image
    img = Image.new('RGB', (640, 480), color=(100, 100, 100))
    return img


@pytest.fixture
def sample_metadata():
    """Sample camera metadata for testing"""
    return {
        'camera': 'ASI294MC Pro',
        'exposure': '5.0s',
        'gain': '200',
        'temperature': '-10.5°C',
        'resolution': '4144x2822',
        'filename': 'test_image.fit',
        'session': 'TestSession',
        'datetime': '2025-12-30 15:30:00'
    }


@pytest.fixture
def mock_camera_info():
    """Mock camera info structure"""
    return {
        'Name': 'ZWO ASI294MC Pro',
        'CameraID': 0,
        'MaxHeight': 2822,
        'MaxWidth': 4144,
        'IsColorCam': True,
        'BayerPattern': 'RGGB',
        'SupportedBins': [1, 2, 3, 4],
        'SupportedVideoFormat': [0, 1, 2],
        'PixelSize': 4.63,
        'MechanicalShutter': False,
        'ST4Port': True,
        'IsCoolerCam': True,
        'IsUSB3Host': True,
        'IsUSB3Camera': True,
        'ElecPerADU': 0.399,
        'BitDepth': 14
    }


# Mark slow tests
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "requires_camera: marks tests that need a physical camera"
    )
    config.addinivalue_line(
        "markers", "requires_network: marks tests that need network access"
    )
