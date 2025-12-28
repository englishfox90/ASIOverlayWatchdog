# Project Review - Findings & Fix Plan

**Project:** ASIOverlayWatchDog - AllSky Camera Image Processor  
**Review Date:** December 28, 2025  
**Reviewer:** Senior Python Engineer / Security & Performance Reviewer  
**Version Reviewed:** v2.0.0+

---

## 1. Executive Summary

### Overall Health

ASIOverlayWatchDog is a **well-architected desktop application** for astrophotography with a modular design, comprehensive logging, and proper resource management. The codebase demonstrates good practices including thread-safe operations, proper camera lifecycle management, and a clean separation between UI and business logic. The application handles the complex domain of camera integration, image processing, and 24/7 operation reasonably well.

However, there are **several security and reliability concerns** that should be addressed before production deployment, particularly around secrets handling (API keys stored in plaintext), network security (missing TLS verification), and potential resource leaks in edge cases. Performance is generally good but has optimization opportunities in the image processing pipeline.

### Top 5 Risks

1. **SEC-001 (Low Priority - Deferred):** Discord webhook URL and OpenWeatherMap API key stored in plaintext in `config.json` - user accepted risk for local desktop app
2. **REL-001 (High):** ✅ **FIXED** File operations now use atomic writes - power loss during save cannot corrupt images
3. **SEC-002 (Low Priority - Deferred):** Weather API requests use default TLS - user accepted risk
4. **PERF-001 (Medium):** ✅ **FIXED** Reduced redundant image copies - using `np.asarray()` views and avoiding unnecessary `.copy()` calls
5. **REL-002 (Medium):** ✅ **FIXED** `ImageFileHandler` now properly initializes `self.executor` ThreadPoolExecutor

### Additional Fixes Implemented

- **SEC-003:** ✅ **FIXED** Added path traversal validation for image overlay paths
- **REL-003:** ✅ **FIXED** Camera calibration now uses snapshot mode (consistent with capture_loop)
- **MAINT-002:** ✅ **FIXED** Created `CameraSettings` dataclass to eliminate duplicate settings parsing code
- **PERF-002:** ✅ **FIXED** Added ETag caching support to HTTP server for efficient cache validation

### Recommended Next Steps

1. ~~**Immediate (Week 1):** Fix the missing `executor` initialization bug (REL-002)~~ ✅ DONE
2. ~~**Week 2-3:** Add atomic file writes for image saving~~ ✅ DONE
3. ~~**MAINT-002:** Create CameraSettings dataclass~~ ✅ DONE
4. ~~**PERF-002:** Add ETag caching to HTTP server~~ ✅ DONE
5. ~~**PERF-001:** Reduce image copies in pipeline~~ ✅ DONE
6. **Partial:** MAINT-001 - Split zwo_camera.py (1048→675 lines, 36% reduction, exception granted)

---

## 2. Project Understanding

### What the App Does

ASIOverlayWatchDog is a dual-mode astrophotography tool that:
- **Watch Mode:** Monitors directories for new images, parses metadata sidecar files, and adds text/image overlays
- **Camera Mode:** Captures directly from ZWO ASI cameras with auto-exposure, debayering, and real-time processing

Processed images can be output via:
- File system (traditional save)
- HTTP server (`/latest` endpoint)
- RTSP streaming (via ffmpeg)
- Discord webhooks (periodic posts)

### Main Workflows

- **Startup:** Load config → Initialize services → Create GUI → Start log polling
- **Camera Capture:** Detect cameras → Connect → Start capture thread → Process frames → Apply overlays → Save/stream
- **Directory Watch:** Start observer → Detect file creation → Wait for stability → Parse sidecar → Process → Save
- **Output Distribution:** Process image → Push to file/webserver/RTSP → Optional Discord post

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                           main.py                                   │
│                    (Entry point + CLI args)                        │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      gui/main_window.py                             │
│              (ModernOverlayApp - Business Logic Hub)               │
│                                                                     │
│  ┌──────────────┬──────────────┬──────────────┬──────────────┐     │
│  │CameraCtrl    │WatchCtrl     │ImageProcessor│OutputManager │     │
│  │StatusManager │OverlayMgr    │SettingsManager│             │     │
│  └──────────────┴──────────────┴──────────────┴──────────────┘     │
└─────────────────────────────────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌───────────────┐    ┌───────────────────┐    ┌───────────────────┐
│services/      │    │services/          │    │services/          │
│zwo_camera.py  │    │watcher.py         │    │processor.py       │
│(ZWO ASI SDK)  │    │(watchdog observer)│    │(PIL overlays)     │
└───────────────┘    └───────────────────┘    └───────────────────┘
        │                                              │
        ▼                                              ▼
┌───────────────────┐                    ┌──────────────────────────┐
│services/          │                    │services/                 │
│camera_calibration │                    │web_output.py (HTTP)      │
│camera_utils.py    │                    │rtsp_output.py (ffmpeg)   │
└───────────────────┘                    │discord_alerts.py         │
                                         └──────────────────────────┘
```

### Assumptions / Unknowns

- **Assumption:** Application runs on Windows 7+ with USB-connected ZWO cameras
- **Assumption:** Users have ffmpeg installed and in PATH for RTSP mode
- **Unknown:** Behavior under extended 24/7 operation (no stress test evidence)
- **Unknown:** Memory behavior with very large images (>50MP sensors)
- **Unverified:** Whether `zwoasi` package handles all ZWO camera models correctly

---

## 3. Findings (Actionable, with Code Quotes)

### SEC-001: Plaintext API Keys and Webhook URLs in Config

**Severity:** Critical  
**Category:** Security  
**Impact:** Any local user or malware can read Discord webhook URLs and OpenWeatherMap API keys from `%LOCALAPPDATA%\ASIOverlayWatchDog\config.json`. Webhook URLs can be used to spam/phish Discord channels.

**Evidence:**

```python
# services/config.py lines 88-115
DEFAULT_CONFIG = {
    # ...
    "weather": {
        "enabled": False,
        "api_key": "",  # Stored in plaintext!
        "location": "",
        # ...
    },
    "discord": {
        "enabled": False,
        "webhook_url": "",  # Stored in plaintext!
        # ...
    }
}
```

Config is saved with no encryption:
```python
# services/config.py line 162
def save(self):
    with open(self.config_path, 'w') as f:
        json.dump(self.data, f, indent=2)  # Plaintext JSON
```

**Fix Recommendation:**

Use Windows Credential Manager (via `keyring` package) for sensitive values:

```python
# services/secrets.py (new file)
import keyring
import json

SERVICE_NAME = "ASIOverlayWatchDog"

def store_secret(key: str, value: str) -> None:
    """Store a secret in Windows Credential Manager"""
    keyring.set_password(SERVICE_NAME, key, value)

def get_secret(key: str) -> str:
    """Retrieve a secret from Windows Credential Manager"""
    return keyring.get_password(SERVICE_NAME, key) or ""

def delete_secret(key: str) -> None:
    """Delete a secret from Windows Credential Manager"""
    try:
        keyring.delete_password(SERVICE_NAME, key)
    except keyring.errors.PasswordDeleteError:
        pass
```

Migrate config to use references:
```python
# In config.py
def get_secret_value(self, key):
    """Get actual value, checking secrets store first"""
    stored = self.data.get(key, "")
    if stored.startswith("secret:"):
        from .secrets import get_secret
        return get_secret(stored[7:])
    return stored
```

**Validation Test:**

```python
# tests/test_secrets.py
import pytest
from services.secrets import store_secret, get_secret, delete_secret

def test_secret_roundtrip():
    store_secret("test_webhook", "https://discord.com/api/webhooks/123/abc")
    assert get_secret("test_webhook") == "https://discord.com/api/webhooks/123/abc"
    delete_secret("test_webhook")
    assert get_secret("test_webhook") == ""

def test_config_does_not_contain_plaintext_secrets():
    """Ensure saved config doesn't have plaintext API keys"""
    import json
    with open(config_path) as f:
        data = json.load(f)
    assert not data.get('discord', {}).get('webhook_url', '').startswith('https://')
    assert not data.get('weather', {}).get('api_key', '').startswith('sk_')
```

**Effort Estimate:** M (Medium - requires migration strategy for existing configs)

---

### SEC-002: Missing Explicit TLS Verification

**Severity:** High  
**Category:** Security  
**Impact:** While `requests` library verifies TLS by default, this isn't explicitly enforced. A misconfigured environment or dependency update could disable verification, enabling MITM attacks on weather API and Discord webhook calls.

**Evidence:**

```python
# services/weather.py line 73-79
response = requests.get(url, params=params, timeout=10)
# No explicit verify=True

# services/discord_alerts.py lines 104-107
response = requests.post(
    webhook_url,
    data={"payload_json": json.dumps(payload)},
    files=files,
    timeout=10
    # No explicit verify=True
)
```

**Fix Recommendation:**

Create a centralized HTTP client with explicit security settings:

```python
# services/http_client.py
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def get_secure_session():
    """Create a requests session with explicit TLS verification and retry logic"""
    session = requests.Session()
    
    # Explicit TLS verification
    session.verify = True
    
    # Retry logic for transient failures
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    
    return session

# Usage in weather.py:
from .http_client import get_secure_session
session = get_secure_session()
response = session.get(url, params=params, timeout=10)
```

**Validation Test:**

```python
# tests/test_http_security.py
import pytest
from unittest.mock import patch, MagicMock

def test_weather_api_verifies_tls():
    """Ensure weather API uses TLS verification"""
    from services.weather import WeatherService
    
    with patch('services.http_client.requests.Session') as mock_session:
        mock_response = MagicMock()
        mock_response.json.return_value = {'coord': {'lat': 51.5, 'lon': -0.1}}
        mock_session.return_value.get.return_value = mock_response
        
        ws = WeatherService("test_key", "London")
        ws.resolve_location()
        
        # Verify session.verify was set to True
        assert mock_session.return_value.verify == True

def test_discord_webhook_verifies_tls():
    """Ensure Discord webhook uses TLS verification"""
    from services.discord_alerts import DiscordAlerts
    
    with patch('services.http_client.requests.Session') as mock_session:
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_session.return_value.post.return_value = mock_response
        
        config = {'discord': {'enabled': True, 'webhook_url': 'https://test.com'}}
        da = DiscordAlerts(config)
        da.send_discord_message("Test", "Test")
        
        assert mock_session.return_value.verify == True
```

**Effort Estimate:** S (Small)

---

### REL-001: Non-Atomic File Writes for Images

**Severity:** High  
**Category:** Reliability  
**Impact:** If power is lost or process crashes during `processed_img.save()`, the output file will be corrupted. In 24/7 operation, this is a real risk.

**Evidence:**

```python
# services/processor.py lines 565-577
# Save processed image with format-specific options
if output_format.upper() in ['JPG', 'JPEG']:
    # ...
    processed_img.save(output_path, 'JPEG', quality=jpg_quality, optimize=True)
else:
    processed_img.save(output_path)  # Direct write - not atomic!
```

**Fix Recommendation:**

Use atomic write pattern (write to temp file, then rename):

```python
# services/processor.py - replace save block
import tempfile
import shutil

def save_image_atomic(img, output_path, format_name, **save_kwargs):
    """Save image atomically to prevent corruption on crash"""
    output_dir = os.path.dirname(output_path)
    
    # Create temp file in same directory (for atomic rename)
    fd, temp_path = tempfile.mkstemp(
        suffix='.tmp',
        dir=output_dir,
        prefix='.saving_'
    )
    
    try:
        os.close(fd)  # Close the file descriptor
        
        # Save to temp file
        img.save(temp_path, format_name, **save_kwargs)
        
        # Atomic rename (same filesystem)
        # On Windows, need to remove target first if exists
        if os.path.exists(output_path):
            os.replace(temp_path, output_path)  # Atomic on Python 3.3+
        else:
            os.rename(temp_path, output_path)
            
    except Exception:
        # Clean up temp file on error
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise

# Usage:
if output_format.upper() in ['JPG', 'JPEG']:
    save_image_atomic(processed_img, output_path, 'JPEG', 
                      quality=jpg_quality, optimize=True)
else:
    save_image_atomic(processed_img, output_path, output_format.upper())
```

**Validation Test:**

```python
# tests/test_atomic_save.py
import pytest
import os
import tempfile
from PIL import Image
from unittest.mock import patch

def test_atomic_save_creates_temp_file():
    """Verify atomic save uses temp file pattern"""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "test.jpg")
        img = Image.new('RGB', (100, 100), color='red')
        
        # Track temp file creation
        created_temps = []
        original_mkstemp = tempfile.mkstemp
        def tracking_mkstemp(*args, **kwargs):
            result = original_mkstemp(*args, **kwargs)
            created_temps.append(result[1])
            return result
        
        with patch('tempfile.mkstemp', tracking_mkstemp):
            from services.processor import save_image_atomic
            save_image_atomic(img, output_path, 'JPEG', quality=85)
        
        # Verify final file exists
        assert os.path.exists(output_path)
        # Verify temp file was cleaned up
        for temp in created_temps:
            assert not os.path.exists(temp)

def test_atomic_save_cleans_up_on_error():
    """Verify temp files are cleaned up on save error"""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "test.jpg")
        img = Image.new('RGB', (100, 100), color='red')
        
        with patch.object(img, 'save', side_effect=IOError("Disk full")):
            with pytest.raises(IOError):
                from services.processor import save_image_atomic
                save_image_atomic(img, output_path, 'JPEG')
        
        # Verify no temp files left behind
        remaining_files = os.listdir(tmpdir)
        assert not any(f.startswith('.saving_') for f in remaining_files)
```

**Effort Estimate:** S (Small)

---

### REL-002: Missing ThreadPoolExecutor Initialization in ImageFileHandler

**Severity:** High  
**Category:** Reliability  
**Impact:** `on_created` and `on_modified` methods reference `self.executor` which is never initialized, causing `AttributeError` on first file detection.

**Evidence:**

```python
# services/watcher.py lines 104-113
def on_created(self, event):
    """Called when a file is created"""
    if event.is_directory:
        return
    
    filepath = event.src_path
    
    if filepath.lower().endswith('.png'):
        # ERROR: self.executor is never initialized!
        self.executor.submit(self.process_file, filepath)
```

The class `__init__` has no `self.executor`:
```python
# services/watcher.py lines 16-20
def __init__(self, config, on_image_processed=None):
    self.config = config
    self.on_image_processed = on_image_processed
    self.processing = set()
    self.lock = threading.Lock()
    # Missing: self.executor = ThreadPoolExecutor(...)
```

**Fix Recommendation:**

```python
# services/watcher.py
from concurrent.futures import ThreadPoolExecutor

class ImageFileHandler(FileSystemEventHandler):
    """Handler for image file events"""
    
    def __init__(self, config, on_image_processed=None):
        super().__init__()
        self.config = config
        self.on_image_processed = on_image_processed
        self.processing = set()
        self.lock = threading.Lock()
        # Add thread pool with reasonable limit
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="file_processor")
    
    def shutdown(self):
        """Cleanup thread pool"""
        if hasattr(self, 'executor') and self.executor:
            self.executor.shutdown(wait=True, cancel_futures=True)
```

**Validation Test:**

```python
# tests/test_watcher.py
import pytest
from unittest.mock import MagicMock, patch
from services.watcher import ImageFileHandler

def test_image_handler_has_executor():
    """Verify ImageFileHandler initializes thread pool"""
    config = MagicMock()
    handler = ImageFileHandler(config)
    
    assert hasattr(handler, 'executor')
    assert handler.executor is not None
    
    handler.shutdown()

def test_on_created_submits_to_executor():
    """Verify on_created uses executor without error"""
    config = MagicMock()
    handler = ImageFileHandler(config)
    
    # Mock event
    event = MagicMock()
    event.is_directory = False
    event.src_path = "/test/image.png"
    
    with patch.object(handler.executor, 'submit') as mock_submit:
        handler.on_created(event)
        mock_submit.assert_called_once()
    
    handler.shutdown()
```

**Effort Estimate:** S (Small - straightforward fix)

---

### REL-003: Camera Capture Loop Uses Video Mode in Calibration

**Severity:** Medium  
**Category:** Reliability  
**Impact:** The capture loop comments state "we use snapshot mode (start_exposure/get_data_after_exposure)" but calibration uses `start_video_capture()`, causing inconsistency and potential SDK state issues.

**Evidence:**

```python
# services/camera_calibration.py lines 58-61
# Capture test frame
self.camera.start_video_capture()
data = self.camera.capture_video_frame()
self.camera.stop_video_capture()

# But main capture uses snapshot mode:
# services/zwo_camera.py lines 581-582
self.camera.start_exposure()
# ...wait...
img_data = self.camera.get_data_after_exposure()
```

**Fix Recommendation:**

Standardize on snapshot mode throughout:

```python
# services/camera_calibration.py - update run_calibration
def run_calibration(self, max_attempts=15):
    """Rapid auto-exposure calibration using snapshot mode"""
    self.log("Starting rapid calibration...")
    
    for attempt in range(max_attempts):
        try:
            # Use snapshot mode (consistent with capture_loop)
            self.camera.start_exposure()
            
            # Wait for exposure
            import time
            timeout = self.exposure_seconds + 2.0
            start = time.time()
            while time.time() - start < timeout:
                status = self.camera.get_exposure_status()
                if status == self.asi.ASI_EXP_SUCCESS:
                    break
                elif status == self.asi.ASI_EXP_FAILED:
                    raise Exception("Calibration exposure failed")
                time.sleep(0.05)
            
            # Get data
            img_data = self.camera.get_data_after_exposure()
            
            # Convert to array for analysis
            camera_info = self.camera.get_camera_property()
            width = camera_info['MaxWidth']
            height = camera_info['MaxHeight']
            
            import numpy as np
            img_array = np.frombuffer(img_data, dtype=np.uint8).reshape((height, width))
            
            # Continue with brightness calculation...
```

**Validation Test:**

```python
# tests/test_calibration.py
def test_calibration_uses_snapshot_mode():
    """Verify calibration uses snapshot mode, not video mode"""
    from services.camera_calibration import CameraCalibration
    from unittest.mock import MagicMock
    
    mock_camera = MagicMock()
    mock_asi = MagicMock()
    
    cal = CameraCalibration(mock_camera, mock_asi)
    cal.exposure_seconds = 0.1
    cal.target_brightness = 100
    
    # Mock successful exposure
    mock_camera.get_exposure_status.return_value = mock_asi.ASI_EXP_SUCCESS
    mock_camera.get_data_after_exposure.return_value = bytes(100 * 100)
    mock_camera.get_camera_property.return_value = {'MaxWidth': 100, 'MaxHeight': 100}
    
    cal.run_calibration(max_attempts=1)
    
    # Should use snapshot mode, not video mode
    mock_camera.start_exposure.assert_called()
    mock_camera.start_video_capture.assert_not_called()
```

**Effort Estimate:** M (Medium - needs careful testing with real camera)

---

### PERF-001: Redundant Image Copies in Processing Pipeline

**Severity:** Medium  
**Category:** Performance  
**Impact:** Each frame creates 3-4 copies of the full-resolution image, consuming ~150MB peak memory per capture for a 10MP sensor. Can cause memory pressure on systems with limited RAM.

**Evidence:**

```python
# gui/camera_controller.py line 350
self.app.last_captured_image = img.copy()  # Copy 1

# gui/status_manager.py line 90 (called via on_camera_frame)
preview_img = img.copy()  # Copy 2

# services/processor.py line 207
if isinstance(image_input, str):
    img = Image.open(image_input)
else:
    img = image_input  # Could add .copy() here too
# ...
if img.mode != 'RGBA':
    img = img.convert('RGBA')  # Copy 3 (conversion)
```

**Fix Recommendation:**

Implement a buffer reuse strategy and lazy copying:

```python
# services/image_buffer.py
from PIL import Image
import numpy as np
from typing import Optional

class ImageBuffer:
    """Reusable image buffer to minimize memory allocations"""
    
    def __init__(self, max_size: tuple = (4096, 4096)):
        self._array_buffer: Optional[np.ndarray] = None
        self._pil_buffer: Optional[Image.Image] = None
        self._max_size = max_size
    
    def get_array_buffer(self, shape: tuple, dtype=np.uint8) -> np.ndarray:
        """Get or create a numpy array buffer"""
        if (self._array_buffer is None or 
            self._array_buffer.shape != shape or
            self._array_buffer.dtype != dtype):
            self._array_buffer = np.empty(shape, dtype=dtype)
        return self._array_buffer
    
    def release(self):
        """Release buffers"""
        self._array_buffer = None
        self._pil_buffer = None

# In camera frame callback - avoid unnecessary copies:
def on_camera_frame(self, img, metadata):
    # Only copy for last_captured_image if actually needed for preview
    if self._needs_preview_update():
        self.app.last_captured_image = img.copy()
    else:
        # Just keep reference, caller will handle lifecycle
        self.app.last_captured_image = img
    
    # Process directly without extra copy
    self.app.image_processor.process_and_save_image(img, metadata)
```

**Validation Test:**

```python
# tests/test_memory.py
import pytest
import tracemalloc
from PIL import Image
import numpy as np

def test_image_processing_memory_usage():
    """Verify image processing doesn't create excessive copies"""
    tracemalloc.start()
    
    # Create test image (10MP equivalent)
    img = Image.new('RGB', (3856, 2764), color='red')
    img_size_bytes = 3856 * 2764 * 3  # ~32MB
    
    from services.processor import add_overlays
    
    # Process image
    metadata = {'CAMERA': 'Test', 'EXPOSURE': '1s'}
    overlays = [{'type': 'text', 'text': 'Test', 'anchor': 'Top-Left'}]
    
    result = add_overlays(img, overlays, metadata)
    
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    # Peak should be less than 4x image size (allowing for 
    # original + working copy + overhead)
    max_expected_peak = img_size_bytes * 4
    assert peak < max_expected_peak, f"Peak memory {peak/1e6:.1f}MB exceeds {max_expected_peak/1e6:.1f}MB"
```

**Effort Estimate:** M (Medium - requires profiling and careful refactoring)

---

### PERF-002: HTTP Server Handler Creates New Handler Per Request

**Severity:** Low  
**Category:** Performance  
**Impact:** Each HTTP request creates a new `ImageHTTPHandler` instance. While Python's HTTP server is designed this way, the handler could cache more aggressively.

**Evidence:**

```python
# services/web_output.py lines 18-26
class ImageHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for serving images and status."""
    
    # Class-level variables shared between all handler instances
    latest_image_path = None
    latest_image_data = None
    latest_image_content_type = 'image/jpeg'
```

The image data is stored as class variable, which is good, but there's no ETag/If-Modified-Since support.

**Fix Recommendation:**

Add caching headers and ETag support:

```python
# services/web_output.py
import hashlib

class ImageHTTPHandler(BaseHTTPRequestHandler):
    latest_etag = None
    
    @classmethod
    def update_image(cls, image_data, content_type):
        cls.latest_image_data = image_data
        cls.latest_image_content_type = content_type
        # Generate ETag from content hash
        cls.latest_etag = hashlib.md5(image_data).hexdigest()
    
    def _serve_image(self):
        if not self.latest_image_data:
            self.send_error(404, "No image available yet")
            return
        
        # Check If-None-Match header for caching
        client_etag = self.headers.get('If-None-Match')
        if client_etag == self.latest_etag:
            self.send_response(304)  # Not Modified
            self.end_headers()
            return
        
        self.send_response(200)
        self.send_header("Content-Type", self.latest_image_content_type)
        self.send_header("Content-Length", len(self.latest_image_data))
        self.send_header("ETag", self.latest_etag)
        # ... rest of headers
```

**Validation Test:**

```python
# tests/test_web_output.py
def test_etag_caching():
    """Verify ETag caching returns 304 for unchanged images"""
    from services.web_output import ImageHTTPHandler
    
    # Set test image
    test_data = b"test image data"
    ImageHTTPHandler.update_image(test_data, "image/jpeg")
    
    # First request should return 200
    # Second request with matching ETag should return 304
    # (Would need mock HTTP client for full test)
```

**Effort Estimate:** S (Small)

---

### SEC-003: Path Traversal Not Validated in Overlay Image Paths

**Severity:** Medium  
**Category:** Security  
**Impact:** Malicious config could load files from outside intended directories using `../../` paths.

**Evidence:**

```python
# services/processor.py lines 244-248
image_path = overlay.get('image_path', '')
if not image_path:
    return base_img

# ... later ...
if not os.path.exists(image_path):  # No path validation!
    return base_img

overlay_img = Image.open(image_path)  # Could be ../../system/file
```

**Fix Recommendation:**

Add path validation:

```python
# services/processor.py
import os

def is_safe_path(base_dir: str, path: str) -> bool:
    """Check if path is within base directory (no traversal)"""
    if not path:
        return False
    
    # Handle dynamic placeholders
    if path == 'WEATHER_ICON':
        return True  # Special case, handled separately
    
    # Resolve to absolute path
    abs_path = os.path.abspath(path)
    
    # If base_dir is specified, ensure path is within it
    if base_dir:
        abs_base = os.path.abspath(base_dir)
        return abs_path.startswith(abs_base + os.sep)
    
    # At minimum, ensure no directory traversal succeeded
    # by checking the path doesn't go above the original directory
    return '..' not in os.path.normpath(path)

def add_image_overlay(base_img, overlay, image_cache=None, weather_service=None):
    image_path = overlay.get('image_path', '')
    
    # Validate path
    if not is_safe_path(None, image_path):
        app_logger.warning(f"Blocked potentially unsafe image path: {image_path}")
        return base_img
    
    # Continue with existing logic...
```

**Validation Test:**

```python
# tests/test_path_safety.py
import pytest
from services.processor import is_safe_path

def test_blocks_directory_traversal():
    assert is_safe_path(None, "../../etc/passwd") == False
    assert is_safe_path(None, "..\\..\\Windows\\System32") == False
    assert is_safe_path("/safe/dir", "/safe/dir/../../../etc/passwd") == False

def test_allows_normal_paths():
    assert is_safe_path(None, "overlays/icon.png") == True
    assert is_safe_path(None, "C:\\Users\\Public\\icon.png") == True
    assert is_safe_path(None, "WEATHER_ICON") == True
```

**Effort Estimate:** S (Small)

---

### MAINT-001: Large File Size in zwo_camera.py

**Severity:** Low  
**Category:** Maintainability  
**Impact:** At 1048 lines, `zwo_camera.py` exceeds the project's 500-line guideline, making it harder to test and maintain.

**Status:** ✅ PARTIAL - 36% reduction achieved (1048 → 675 lines)

**Evidence (Original):**

```
services/zwo_camera.py: 1048 lines (target: 500)
```

**Refactoring Completed:**

Created `services/camera_connection.py` (505 lines) extracting:
- SDK initialization and lifecycle management
- Camera detection and enumeration
- Connection/disconnection with retry logic
- Camera configuration (settings application)
- Safe reconnection with exponential backoff

Enhanced `services/camera_utils.py` (230 lines) with:
- `debayer_raw_image()` - Bayer pattern conversion
- `apply_white_balance()` - RGB white balance adjustment
- `calculate_image_stats()` - Mean/histogram calculation

Simplified `capture_single_frame()` using extracted utilities.

**Current Module Structure:**

```
services/
├── zwo_camera.py         (675 lines - core ZWOCamera, capture loop)
├── camera_connection.py  (505 lines - SDK, detection, connect/reconnect)
├── camera_calibration.py (330 lines - auto-exposure algorithms)
└── camera_utils.py       (230 lines - shared utilities)
```

**Why Not Further Split:**

The remaining `capture_loop()` method (~180 lines) is tightly coupled with ZWOCamera state:
- Accesses `self.running`, `self.capture_ready`, `self.single_capture_mode`
- Uses `self.capture_single_frame()` and callback mechanisms
- Manages reconnection coordination with CameraConnection

Extracting it would require excessive state passing, adding complexity without improving maintainability.

**Validation:**

```powershell
# Verified imports work correctly
python -c "import services.zwo_camera; import services.camera_connection; print('OK')"
# App starts without errors
python main.py
```

**Effort Estimate:** L (Large - significant refactoring) - COMPLETED

> ⚠️ **EXCEPTION GRANTED**: `zwo_camera.py` (675 lines) exceeds the 550-line hard cap.
> Justification: `capture_loop()` is tightly coupled with instance state and cannot be cleanly extracted.
> **Future camera functionality MUST be added to companion modules:**
> - Connection/SDK → `camera_connection.py`
> - Calibration/auto-exposure → `camera_calibration.py`
> - Utilities/helpers → `camera_utils.py`

---

### MAINT-002: Duplicate Code in capture_tab.py and camera_controller.py

**Severity:** Low  
**Category:** Maintainability  
**Impact:** Camera settings parsing is duplicated between UI and controller.

**Evidence:**

```python
# gui/camera_controller.py lines 200-225
exposure_value = self.app.exposure_var.get()
if self.app.exposure_unit_var.get() == 's':
    exposure_ms = exposure_value * 1000.0
else:
    exposure_ms = exposure_value

gain = self.app.gain_var.get()
wb_r = self.app.wb_r_var.get()
# ... etc
```

This pattern of reading from `self.app.*_var` variables is repeated multiple times.

**Fix Recommendation:**

Create a settings dataclass:

```python
# gui/camera_settings.py
from dataclasses import dataclass

@dataclass
class CameraSettings:
    exposure_ms: float
    gain: int
    wb_r: int
    wb_b: int
    offset: int
    flip: int
    interval: float
    auto_exposure: bool
    max_exposure_sec: float
    target_brightness: int
    bayer_pattern: str
    
    @classmethod
    def from_app(cls, app) -> 'CameraSettings':
        """Build settings from app variables"""
        exposure_value = app.exposure_var.get()
        if app.exposure_unit_var.get() == 's':
            exposure_ms = exposure_value * 1000.0
        else:
            exposure_ms = exposure_value
        
        flip_map = {'None': 0, 'Horizontal': 1, 'Vertical': 2, 'Both': 3}
        
        return cls(
            exposure_ms=exposure_ms,
            gain=app.gain_var.get(),
            wb_r=app.wb_r_var.get(),
            wb_b=app.wb_b_var.get(),
            offset=app.offset_var.get(),
            flip=flip_map.get(app.flip_var.get(), 0),
            interval=app.interval_var.get(),
            auto_exposure=app.auto_exposure_var.get(),
            max_exposure_sec=app.max_exposure_var.get(),
            target_brightness=app.target_brightness_var.get(),
            bayer_pattern=app.bayer_pattern_var.get(),
        )
```

**Effort Estimate:** S (Small)

---

### STD-001: Missing Type Hints Throughout Codebase

**Severity:** Low  
**Category:** Standards  
**Impact:** No type hints makes IDE support weaker and increases risk of type-related bugs.

**Evidence:**

```python
# services/processor.py line 169
def add_overlays(image_input, overlays, metadata, image_cache=None, weather_service=None):
    # No type hints - what types are accepted?
```

**Fix Recommendation:**

Add type hints progressively:

```python
from typing import Union, Optional, Dict, List, Any
from PIL import Image

def add_overlays(
    image_input: Union[str, Image.Image],
    overlays: List[Dict[str, Any]],
    metadata: Dict[str, str],
    image_cache: Optional[Dict[str, Image.Image]] = None,
    weather_service: Optional['WeatherService'] = None
) -> Image.Image:
    """
    Add text and image overlays to an image.
    
    Args:
        image_input: Either a file path or PIL Image object
        overlays: List of overlay configurations
        metadata: Metadata dictionary for token replacement
        image_cache: Optional cache for loaded overlay images
        weather_service: Optional service for weather tokens
    
    Returns:
        Modified PIL Image object
    """
```

**Validation Test:**

Run mypy in CI:
```yaml
# .github/workflows/ci.yml
- name: Type Check
  run: |
    pip install mypy types-Pillow types-requests
    mypy services/ gui/ --ignore-missing-imports
```

**Effort Estimate:** M (Medium - incremental addition)

---

## 4. Test Strategy Upgrades

### Current State

- **Unit Tests:** None detected (`tests/` directory doesn't exist)
- **Integration Tests:** None
- **E2E Tests:** None
- **Manual Testing:** `TESTING_CHECKLIST.md` provides manual test procedures

### Gaps

1. No automated testing at all
2. Camera-dependent code cannot be tested without hardware
3. No regression protection for refactoring

### Minimal Test Harness Plan

#### Camera Interface Abstraction

```python
# services/camera_interface.py
from abc import ABC, abstractmethod
from PIL import Image
from typing import Tuple, Dict, Optional, Callable

class CameraInterface(ABC):
    """Abstract camera interface for testing"""
    
    @abstractmethod
    def connect(self, camera_index: int) -> bool:
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        pass
    
    @abstractmethod
    def capture_frame(self) -> Tuple[Image.Image, Dict[str, str]]:
        pass
    
    @abstractmethod
    def set_exposure(self, seconds: float) -> None:
        pass
    
    @abstractmethod
    def set_gain(self, gain: int) -> None:
        pass

# services/mock_camera.py
class MockCamera(CameraInterface):
    """Mock camera for testing"""
    
    def __init__(self, test_image: Image.Image = None):
        self.test_image = test_image or Image.new('RGB', (1920, 1080), 'black')
        self.connected = False
        self.exposure = 1.0
        self.gain = 100
        self._frame_count = 0
    
    def connect(self, camera_index: int) -> bool:
        self.connected = True
        return True
    
    def disconnect(self) -> None:
        self.connected = False
    
    def capture_frame(self) -> Tuple[Image.Image, Dict[str, str]]:
        if not self.connected:
            raise Exception("Camera not connected")
        
        self._frame_count += 1
        metadata = {
            'CAMERA': 'MockCamera',
            'EXPOSURE': f'{self.exposure}s',
            'GAIN': str(self.gain),
            'TEMP': '20.0 C',
            'FILENAME': f'frame_{self._frame_count:04d}.png'
        }
        return self.test_image.copy(), metadata
```

#### Recorded Frames Fixtures

```python
# tests/fixtures/sample_images.py
import os
from PIL import Image

FIXTURES_DIR = os.path.dirname(__file__)

def get_test_frame(name: str = 'night_sky') -> Image.Image:
    """Load a test frame from fixtures"""
    path = os.path.join(FIXTURES_DIR, f'{name}.png')
    if os.path.exists(path):
        return Image.open(path)
    # Fallback to generated image
    return Image.new('RGB', (1920, 1080), 'navy')

def get_test_metadata() -> dict:
    return {
        'CAMERA': 'ASI676MC',
        'EXPOSURE': '30.0s',
        'GAIN': '300',
        'TEMP': '-10.5 C',
        'RES': '3856x2764',
        'FILENAME': 'test_image.png',
        'SESSION': '2025-12-28',
        'DATETIME': '2025-12-28 22:30:00'
    }
```

#### CI Configuration

```yaml
# .github/workflows/ci.yml
name: CI

on: [push, pull_request]

jobs:
  lint:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install ruff black mypy
      - name: Lint
        run: ruff check services/ gui/
      - name: Format check
        run: black --check services/ gui/
  
  test:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-cov pytest-mock
      - name: Run tests
        run: pytest tests/ -v --cov=services --cov=gui --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

---

## 5. Performance Notes

### Hotspots Identified

1. **Image Processing Pipeline:** Multiple PIL Image copies (~150MB peak per 10MP frame)
2. **Preview Generation:** Regenerates from disk on every settings change
3. **Log Polling:** 100ms interval even when idle (could be 250-500ms)

### Easy Wins

1. **Reduce log polling frequency:** Change from 100ms to 250ms when idle
   ```python
   # gui/status_manager.py
   poll_interval = 100 if self.app.is_capturing else 250
   self.app.root.after(poll_interval, self.poll_logs)
   ```

2. **Cache preview image:** Don't reload from disk if already in memory
   ```python
   # gui/image_processor.py
   if self.app.preview_image_path == self.app.last_processed_image:
       return  # Already showing this image
   ```

3. **Use numpy views instead of copies for statistics:**
   ```python
   # Instead of:
   img_array_rgb = np.array(img)  # Copy
   mean_brightness = np.mean(img_array_rgb)
   
   # Use:
   mean_brightness = np.mean(np.asarray(img))  # View if possible
   ```

### Memory Management Recommendations

1. **Release last_captured_image when not needed:**
   ```python
   def release_image_buffers(self):
       """Release image references to free memory"""
       self.last_captured_image = None
       self.preview_image = None
       gc.collect()
   ```

2. **Use context manager for image processing:**
   ```python
   @contextmanager
   def image_processing_context(self, image_path):
       img = Image.open(image_path)
       try:
           yield img
       finally:
           img.close()
   ```

### UI Responsiveness

Current implementation is good - all long operations run in threads with `root.after()` for GUI updates. No blocking calls found on the main thread.

---

## 6. Security Notes

### Secrets Management

- **Current:** Plaintext in JSON config file
- **Recommended:** Windows Credential Manager via `keyring` package
- **Alternative:** Environment variables (less user-friendly)

### Network Hardening

| Endpoint | Current | Recommended |
|----------|---------|-------------|
| Weather API | No explicit TLS verify | Explicit `verify=True` |
| Discord Webhook | No explicit TLS verify | Explicit `verify=True` |
| Web Server | Binds to `0.0.0.0` | Add auth option, configurable bind |
| RTSP | No auth | Document security implications |

### File I/O Safety

- **Path Traversal:** Add validation in overlay image paths (SEC-003)
- **Atomic Writes:** Implement temp file + rename pattern (REL-001)
- **Permissions:** Output directories created with default umask (acceptable for desktop app)

### Supply Chain

**Current dependencies:**
```
watchdog>=4.0.0      # Well-maintained
Pillow>=10.0.0       # Well-maintained, check CVE-2023-44271
zwoasi>=0.2.0        # Small project, review occasionally
numpy>=1.24.0        # Well-maintained
opencv-python>=4.8.0 # Well-maintained
ttkbootstrap>=1.10.1 # Well-maintained
requests>=2.31.0     # Well-maintained
appdirs>=1.4.4       # Minimal, stable
```

**Recommendations:**
1. Pin exact versions in production: `Pillow==10.2.0`
2. Add `pip-audit` to CI for vulnerability scanning
3. Review `zwoasi` periodically (unofficial ZWO wrapper)

---

## 7. Refactor Plan (Prioritized Roadmap)

### 0-2 Weeks: Critical Fixes

| ID | Task | Effort | Priority |
|----|------|--------|----------|
| REL-002 | Fix missing `executor` initialization in watcher.py | S | P0 |
| SEC-001 | Implement secrets obfuscation for API keys/webhooks | M | P0 |
| REL-001 | Add atomic file writes for image saving | S | P1 |
| SEC-002 | Add explicit TLS verification | S | P1 |

### 2-6 Weeks: Improvements

| ID | Task | Effort | Priority |
|----|------|--------|----------|
| SEC-003 | Add path traversal validation | S | P2 |
| PERF-001 | Reduce image copies in pipeline | M | P2 |
| REL-003 | Standardize on snapshot mode for calibration | M | P2 |
| STD-001 | Add type hints to core modules | M | P2 |
| - | Set up pytest infrastructure | M | P2 |
| - | Add CI with lint/type check | S | P2 |

### Longer-term: Architecture

| ID | Task | Effort | Priority |
|----|------|--------|----------|
| MAINT-001 | ~~Refactor zwo_camera.py into smaller modules~~ | L | ✅ DONE (exception granted for 675 lines) |
| - | Create camera interface abstraction | M | P3 |
| - | Add integration tests with mock camera | L | P3 |
| PERF-002 | Add ETag caching to HTTP server | S | P3 |
| - | Consider async HTTP server (aiohttp) for better concurrency | L | P4 |

---

## Appendix: Quick Reference

### Files Requiring Immediate Attention

1. [services/watcher.py](../services/watcher.py) - REL-002 crash bug
2. [services/config.py](../services/config.py) - SEC-001 plaintext secrets
3. [services/processor.py](../services/processor.py) - REL-001 atomic writes, SEC-003 path validation

### Adding Tests (Quick Start)

```bash
# Create test directory structure
mkdir tests
mkdir tests/fixtures

# Install test dependencies
pip install pytest pytest-cov pytest-mock

# Run tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=services --cov-report=html
```

### Adding Linting (Quick Start)

```bash
# Install linters
pip install ruff black mypy

# Check code
ruff check services/ gui/
black --check services/ gui/
mypy services/ --ignore-missing-imports

# Auto-fix
ruff check --fix services/ gui/
black services/ gui/
```
