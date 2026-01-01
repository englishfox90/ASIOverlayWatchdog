# PFR Sentinel UI Comparison Report
## OLD (Tkinter `gui/`) vs NEW (PySide6 `ui/`) Implementation

**Generated:** January 2026  
**Purpose:** Identify backend calls, missing connections, and config gaps between the two UI implementations

---

## 1. Executive Summary

| Area | OLD UI (Tkinter) | NEW UI (PySide6) | Gap Status |
|------|------------------|------------------|------------|
| Camera Detection | ✅ Full implementation | ⚠️ Basic - no spinner/timeout | **NEEDS WORK** |
| Camera Capture | ✅ Full with callbacks | ⚠️ Basic - missing features | **NEEDS WORK** |
| Discord Webhook Test | ✅ Full with status feedback | ❌ Not connected | **MISSING** |
| Web Server Start/Stop | ✅ Full implementation | ❌ Not implemented | **MISSING** |
| RTSP Server | ✅ Full implementation | ❌ Not implemented | **MISSING** |
| Directory Watch | ✅ Full with callbacks | ⚠️ Basic | **NEEDS WORK** |
| Config Loading | ✅ Full load_config() | ✅ load_from_config() | OK |
| Output Mode Manager | ✅ Full OutputManager class | ❌ Not created | **MISSING** |

---

## 2. Camera Detection Differences

### OLD UI Implementation ([gui/camera_controller.py](../gui/camera_controller.py#L21-L101))

```python
def detect_cameras(self):
    # 1. Show spinner in UI
    self.app.capture_tab.show_detection_spinner()
    self.app.capture_tab.clear_detection_error()
    
    # 2. Run detection in background thread
    def detect_thread():
        # Validate SDK path
        # Initialize ASI SDK
        # Query cameras via asi.get_num_cameras()
        # Build camera list with names
        # Call _on_detection_complete() via root.after()
    
    # 3. Timeout monitor (10 seconds)
    def timeout_monitor():
        # Kill thread if taking too long
    
    # 4. _on_detection_complete() updates:
    #    - Hide spinner
    #    - Show error OR populate combo
    #    - Restore previously selected camera by NAME (not just index)
    #    - Enable/disable start button
```

**Key Features:**
- ✅ Shows loading spinner during detection
- ✅ 10-second timeout with error message
- ✅ Restores camera selection by **name** (not just index) for stability
- ✅ Saves `zwo_selected_camera_name` config key
- ✅ Shows detailed error messages in UI

### NEW UI Implementation ([ui/controllers/camera_controller.py](../ui/controllers/camera_controller.py#L77-L114))

```python
def detect_cameras(self):
    # Runs synchronously - BLOCKS UI
    sdk_path = self.config.get('zwo_sdk_path', '')
    # Initialize SDK
    # Query cameras
    self.cameras_detected.emit(camera_list)  # Signal emitted but NOT connected
```

**Missing Features:**
- ❌ No loading spinner shown
- ❌ No timeout handling
- ❌ Synchronous execution blocks UI
- ❌ `cameras_detected` signal **NOT CONNECTED** to UI
- ❌ No camera name persistence
- ❌ No detailed error display in UI

### Required Changes

1. **Connect signal in `ui/main_window.py`:**
```python
def _setup_connections(self):
    # Add these connections:
    self.capture_panel.detect_cameras_clicked.connect(self._detect_cameras)

def _detect_cameras(self):
    if not self.camera_controller:
        from .controllers.camera_controller import CameraControllerQt
        self.camera_controller = CameraControllerQt(self)
    
    # Connect signal to panel update
    self.camera_controller.cameras_detected.connect(self.capture_panel.set_cameras)
    self.camera_controller.error.connect(self._on_camera_error)
    
    # Show spinner in capture panel
    self.capture_panel.show_detection_spinner()
    
    # Run in QThread or use QTimer.singleShot for async
    QTimer.singleShot(0, self.camera_controller.detect_cameras)
```

2. **Add to `ui/panels/capture_settings.py`:**
```python
def show_detection_spinner(self):
    self.detect_btn.setEnabled(False)
    self.detect_btn.setText("Detecting...")

def hide_detection_spinner(self):
    self.detect_btn.setEnabled(True)
    self.detect_btn.setText("Detect")
```

---

## 3. Discord Webhook Testing

### OLD UI Implementation ([gui/output_manager.py](../gui/output_manager.py#L229-L262))

```python
def test_discord_webhook(self):
    # 1. Validate webhook URL exists
    if not self.app.discord_webhook_var.get():
        self.app.discord_test_status_var.set("❌ Please enter webhook URL")
        return
    
    # 2. Auto-save settings before testing
    self.save_discord_settings()
    
    # 3. Temporarily enable Discord if disabled
    was_enabled = self.app.discord_enabled_var.get()
    if not was_enabled:
        self.app.discord_enabled_var.set(True)
        self.save_discord_settings()
    
    # 4. Send test message via DiscordAlerts service
    success = self.discord_alerts.send_discord_message(
        "🧪 Test Alert",
        "This is a test message...",
        level="info"
    )
    
    # 5. Restore original enabled state
    # 6. Show success/failure status
    # 7. Clear status after 5 seconds
```

### NEW UI Implementation ([ui/panels/output_settings.py](../ui/panels/output_settings.py#L354-L377))

```python
def _test_discord(self):
    # Creates NEW DiscordAlerts instance (wrong!)
    alerts = DiscordAlerts(webhook_url)  # Should use config dict, not just URL
    success = alerts.send_test_message()  # Method doesn't exist in service!
```

**Issues:**
- ❌ Creates `DiscordAlerts(webhook_url)` but constructor expects `config_data` dict
- ❌ Calls `send_test_message()` which doesn't exist - should use `send_discord_message()`
- ❌ No auto-save before testing
- ❌ No temporary enable if disabled
- ❌ No status auto-clear timer

### Required Fix

```python
def _test_discord(self):
    self.discord_status_label.setText("Testing...")
    
    webhook_url = self.webhook_input.text().strip()
    if not webhook_url:
        self.discord_status_label.setText("❌ Webhook URL required")
        return
    
    # Save settings first
    self._on_discord_settings_changed()
    if self.main_window:
        self.main_window.save_config()
    
    try:
        # Get full config for DiscordAlerts
        config_data = self.main_window.config.data if self.main_window else {}
        
        # Temporarily set webhook for test
        if 'discord' not in config_data:
            config_data['discord'] = {}
        config_data['discord']['webhook_url'] = webhook_url
        config_data['discord']['enabled'] = True  # Temp enable
        
        alerts = DiscordAlerts(config_data)
        success = alerts.send_discord_message(
            "🧪 Test Alert",
            "Test message from PFR Sentinel. Webhook configured correctly!",
            level="info"
        )
        
        if success:
            self.discord_status_label.setText("✓ Test successful!")
        else:
            self.discord_status_label.setText("❌ Failed - check logs")
            
    except Exception as e:
        self.discord_status_label.setText(f"❌ {str(e)[:30]}")
```

---

## 4. Output Server Management (MISSING in NEW UI)

### OLD UI Has Full OutputManager ([gui/output_manager.py](../gui/output_manager.py))

| Feature | OLD Implementation | NEW UI Status |
|---------|-------------------|---------------|
| Web Server Start | `_start_web_server()` with status feedback | ❌ Missing |
| Web Server Stop | `stop_all_servers()` | ❌ Missing |
| RTSP Server Start | `_start_rtsp_server()` with ffmpeg check | ❌ Missing |
| RTSP Server Stop | `stop_all_servers()` | ❌ Missing |
| Push to Servers | `push_to_output_servers(image_path, img)` | ❌ Missing |
| Discord Periodic Posts | `schedule_discord_periodic()` | ❌ Missing |
| Output Mode Toggle | `apply_output_mode()` | ❌ Missing |
| URL Copy | `copy_output_url()` | ❌ Missing |

### Required: Create `ui/controllers/output_manager.py`

```python
"""
Output Manager for Qt UI
Handles Web Server, RTSP, and Discord outputs
"""
from PySide6.QtCore import QObject, Signal, QTimer
from services.web_output import WebOutputServer
from services.rtsp_output import RTSPStreamServer
from services.discord_alerts import DiscordAlerts
from services.logger import app_logger


class OutputManagerQt(QObject):
    """Manages output servers and Discord alerts"""
    
    server_started = Signal(str, str)  # type, url
    server_stopped = Signal(str)  # type
    server_error = Signal(str, str)  # type, error
    
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.config = main_window.config
        
        self.web_server = None
        self.rtsp_server = None
        self.discord_alerts = None
        self._periodic_timer = None
    
    def start_web_server(self):
        """Start web server with config settings"""
        output_config = self.config.get('output', {})
        host = output_config.get('webserver_host', '127.0.0.1')
        port = output_config.get('webserver_port', 8080)
        path = output_config.get('webserver_path', '/latest')
        
        self.web_server = WebOutputServer(host, port, path)
        if self.web_server.start():
            url = self.web_server.get_url()
            self.server_started.emit('web', url)
            app_logger.info(f"Web server started: {url}")
        else:
            self.server_error.emit('web', 'Failed to start')
    
    def stop_web_server(self):
        if self.web_server:
            self.web_server.stop()
            self.web_server = None
            self.server_stopped.emit('web')
    
    def start_rtsp_server(self):
        """Start RTSP server (requires ffmpeg)"""
        # Similar to web server
        pass
    
    def push_image(self, image_path, pil_image=None):
        """Push image to active servers"""
        if self.web_server and self.web_server.running:
            # Convert and push
            pass
        if self.rtsp_server and self.rtsp_server.running:
            # Push frame
            pass
    
    def initialize_discord(self):
        """Initialize Discord alerts"""
        self.discord_alerts = DiscordAlerts(self.config.data)
    
    def schedule_periodic_discord(self, interval_minutes: int):
        """Schedule periodic Discord posts"""
        if self._periodic_timer:
            self._periodic_timer.stop()
        
        self._periodic_timer = QTimer(self)
        self._periodic_timer.timeout.connect(self._post_periodic_update)
        self._periodic_timer.start(interval_minutes * 60 * 1000)
```

---

## 5. Capture Start/Stop - Missing Backend Calls

### OLD UI `start_camera_capture()` Does:

1. ✅ `ensure_output_mode_started()` - Start web/RTSP if configured
2. ✅ Show "Connecting..." status
3. ✅ Validate camera selection exists
4. ✅ Create `CameraSettings` dataclass from all UI vars
5. ✅ Log settings summary
6. ✅ Create `ZWOCamera` with **full parameter list** (20+ params)
7. ✅ Set target brightness
8. ✅ Connect camera
9. ✅ Set capture interval
10. ✅ Set error callback for disconnect recovery
11. ✅ Start capture with `on_frame_callback`
12. ✅ Reset `first_image_posted_to_discord` flag
13. ✅ Update all UI buttons states
14. ✅ Schedule Discord periodic updates

### NEW UI `start_capture()` Does:

1. ⚠️ Creates `ZWOCamera` with only **10 params** (missing many)
2. ⚠️ No output server initialization
3. ❌ No `CameraSettings` dataclass usage
4. ❌ No settings summary logging
5. ❌ No error callback for disconnect
6. ❌ No Discord scheduling
7. ❌ No first image flag reset

### Missing ZWOCamera Parameters in NEW UI:

| Parameter | OLD | NEW | Impact |
|-----------|-----|-----|--------|
| `auto_wb` | ✅ | ❌ | White balance won't work |
| `wb_mode` | ✅ | ❌ | WB mode selection ignored |
| `wb_config` | ✅ | ❌ | Gray world settings ignored |
| `scheduled_capture_enabled` | ✅ | ❌ | Scheduling won't work |
| `scheduled_start_time` | ✅ | ❌ | |
| `scheduled_end_time` | ✅ | ❌ | |
| `status_callback` | ✅ | ❌ | No schedule status updates |
| `camera_name` | ✅ | ❌ | Camera name not persisted |
| `config_callback` | ✅ | ❌ | Auto-exposure changes not saved |
| `on_error_callback` | ✅ | ❌ | No disconnect recovery |

---

## 6. Config Key Differences

### Keys Used in OLD UI but Not in NEW UI

| Config Key | Description | Used In OLD | Used In NEW |
|------------|-------------|-------------|-------------|
| `zwo_selected_camera_name` | Camera name for restore | ✅ | ❌ |
| `output_mode` | file/webserver/rtsp | ✅ | ❌ |
| `webserver_host` | Direct key | ✅ | Nested in `output` |
| `webserver_port` | Direct key | ✅ | Nested in `output` |
| `rtsp_*` | RTSP settings | ✅ | Nested in `output` |
| `discord_enabled_var` | Tkinter var | ✅ (mapped) | ❌ |
| `first_image_posted_to_discord` | State flag | ✅ | ❌ |

### Config Structure Differences

**OLD UI** uses flat keys:
```python
config.get('webserver_host', '127.0.0.1')
config.get('webserver_port', 8080)
config.get('discord_webhook_var', '')  # Via StringVar
```

**NEW UI** uses nested structure:
```python
config.get('output', {}).get('webserver_host', '127.0.0.1')
config.get('discord', {}).get('webhook_url', '')
```

**Recommendation:** Align both UIs to use nested structure (new approach is cleaner).

---

## 7. Signals Not Connected in NEW UI

### `ui/panels/capture_settings.py`:

| Signal | Declared | Connected | Handler |
|--------|----------|-----------|---------|
| `settings_changed` | ✅ | ✅ | `main_window._on_settings_changed()` |
| `detect_cameras_clicked` | ✅ | ❌ | **NEEDS CONNECTION** |

### `ui/panels/output_settings.py`:

| Signal | Declared | Connected | Handler |
|--------|----------|-----------|---------|
| `settings_changed` | ✅ | ✅ | `main_window._on_settings_changed()` |

Note: Output panel has UI but no actual server start/stop logic connected.

### `ui/controllers/camera_controller.py`:

| Signal | Declared | Connected | Handler |
|--------|----------|-----------|---------|
| `cameras_detected` | ✅ | ❌ | Needs `capture_panel.set_cameras()` |
| `capture_started` | ✅ | ❌ | Needs `main_window/app_bar` update |
| `capture_stopped` | ✅ | ❌ | Needs `main_window/app_bar` update |
| `frame_ready` | ✅ | ❌ | Needs `main_window.on_image_captured()` |
| `error` | ✅ | ❌ | Needs error display |

---

## 8. Controllers Needed

### Must Create or Complete:

1. **`ui/controllers/output_manager.py`** (NEW FILE)
   - Web server start/stop
   - RTSP server start/stop
   - Discord alerts initialization
   - Periodic Discord scheduling
   - Image push to servers

2. **`ui/controllers/camera_controller.py`** (ENHANCE)
   - Add all missing ZWOCamera parameters
   - Add timeout for detection
   - Add error callback
   - Add config callback for auto-exposure saves

3. **`ui/controllers/watch_controller.py`** (ENHANCE)
   - Add output server initialization
   - Add Discord scheduling
   - Add image processing callback that pushes to servers

4. **`ui/controllers/discord_controller.py`** (OPTIONAL)
   - Test webhook
   - Send alerts
   - Schedule periodic posts
   - Manage embed colors

---

## 9. Priority Action Items

### HIGH Priority (Blocking basic functionality):

1. **Connect `detect_cameras_clicked` signal** to actual detection
2. **Connect `cameras_detected` signal** to update UI combo
3. **Add `OutputManagerQt` class** for server management
4. **Fix Discord test** - use correct API

### MEDIUM Priority (Features work but missing feedback):

5. **Add detection spinner/timeout** in capture panel
6. **Add full ZWOCamera parameters** to controller
7. **Add disconnect error recovery** callback
8. **Add Discord periodic scheduling**

### LOW Priority (Polish):

9. **Add URL copy button** functionality
10. **Add first-image-to-Discord** logic
11. **Align config key structure** between UIs
12. **Add CameraSettings dataclass** usage in Qt controller

---

## 10. Quick Reference: Backend Services

| Service | Location | Used By OLD | Used By NEW |
|---------|----------|-------------|-------------|
| `ZWOCamera` | `services/zwo_camera.py` | ✅ Full | ⚠️ Partial |
| `FileWatcher` | `services/watcher.py` | ✅ Full | ⚠️ Partial |
| `WebOutputServer` | `services/web_output.py` | ✅ Full | ❌ Not used |
| `RTSPStreamServer` | `services/rtsp_output.py` | ✅ Full | ❌ Not used |
| `DiscordAlerts` | `services/discord_alerts.py` | ✅ Full | ⚠️ Wrong usage |
| `Config` | `services/config.py` | ✅ Full | ✅ Full |
| `app_logger` | `services/logger.py` | ✅ Full | ✅ Full |
| `ImageProcessor` | `gui/image_processor.py` | ✅ Full | ❌ Not created for Qt |

---

*End of Report*
