# AI Agent Instructions for PFR Sentinel

## Project Overview
Dual-mode astrophotography application: (1) watches directories for new images and adds metadata overlays, or (2) captures directly from ZWO ASI cameras with real-time processing. Built for 24/7 unattended operation with modern Fluent Design UI (PySide6 + qfluentwidgets).

**Recent Major Update (v3.1.1)**: Complete UI rewrite from Tkinter/ttkbootstrap to PySide6 + qfluentwidgets, Discord integration with weather data, multi-output simultaneous operation, proper installer packaging, and config moved to %APPDATA%.

## Project Structure (v3.1.1+)

### Modular Organization
```
PFRSentinel/
├── ui/                     # PySide6 + qfluentwidgets UI (v3.1.1 rewrite)
│   ├── main_window.py     # Application core with Qt MainWindow
│   ├── system_tray_qt.py  # Qt system tray with notifications
│   ├── components/        # Reusable UI components
│   │   ├── header.py      # Status bar with live indicators
│   │   ├── monitoring_panel.py # Live preview, histogram, mini-logs
│   │   └── status_indicator.py # Visual state badges
│   ├── panels/            # Main content pages
│   │   ├── monitoring.py  # Monitoring page (real-time feed)
│   │   ├── capture.py     # Capture settings page
│   │   ├── output.py      # Output modes page (File/Web/Discord/RTSP)
│   │   ├── overlays.py    # Overlay editor page
│   │   └── logs.py        # Log viewer page
│   ├── controllers/       # Business logic controllers
│   │   ├── capture_controller.py  # Watch/camera mode control
│   │   ├── output_controller.py   # Output server management
│   │   └── overlay_controller.py  # Overlay CRUD operations
│   └── theme/             # Fluent Design theming
│       ├── colors.py      # Color palette constants
│       └── styles.py      # QSS stylesheets
├── services/              # Core processing modules
│   ├── config.py          # JSON persistence (now in %APPDATA%\PFRSentinel)
│   ├── logger.py          # Thread-safe queue-based logging
│   ├── processor.py       # Image overlay engine with weather tokens
│   ├── watcher.py         # Directory monitoring
│   ├── zwo_camera.py      # ZWO ASI camera core
│   ├── camera_connection.py # SDK init, detection, reconnect
│   ├── camera_calibration.py # Auto-exposure algorithms
│   ├── camera_utils.py    # Shared camera utilities
│   ├── cleanup.py         # Disk space management
│   ├── discord_alerts.py  # Discord webhook integration (NEW v3.1.1)
│   ├── weather.py         # OpenWeatherMap API client (NEW v3.1.1)
│   ├── web_output.py      # HTTP server with /latest and /status
│   └── rtsp_output.py     # RTSP streaming via ffmpeg
├── docs/                  # Documentation
├── archive/               # Legacy Tkinter GUI (archived in v3.1.1)
│   ├── gui_tkinter/       # Old ttkbootstrap implementation
│   └── main_pyside.py     # Old PySide6 entry point
├── installer/             # Inno Setup packaging (NEW v3.1.1)
│   └── PFRSentinel.iss    # Installer script
├── main.py                # Application entry point
├── app_config.py          # Config location management (%APPDATA%)
└── version.py             # Version constants for installer
```

### Core Components
- **`ui/main_window.py`**: Qt MainWindow with QStackedWidget for page navigation. Uses controller pattern for business logic separation.
- **`ui/panels/*.py`**: Page classes (Monitoring, Capture, Output, Overlays, Logs) - each panel is self-contained with its own layout and controller interaction.
- **`ui/controllers/*.py`**: Business logic controllers handle capture, output servers, and overlay management. Called from panels via signals/slots.
- **`services/processor.py`**: Image overlay engine with weather token support. **Critical**: Accepts EITHER PIL Image objects OR file paths, metadata dict OR sidecar parsing.
- **`services/watcher.py`**: watchdog-based FileSystemEventHandler for directory monitoring mode.
- **`services/zwo_camera.py`**: ZWO ASI SDK wrapper for direct camera capture with debayering.
- **`services/discord_alerts.py`**: Discord webhook client for periodic posts and event notifications (NEW v3.1.1).
- **`services/weather.py`**: OpenWeatherMap API client for weather data in overlays and Discord (NEW v3.1.1).
- **`services/web_output.py`**: HTTP server with ImageHTTPHandler for `/latest` (image) and `/status` (JSON) endpoints.
- **`services/config.py`**: JSON persistence now stored in `%APPDATA%\PFRSentinel\config.json` with merge-on-load pattern.
- **`services/logger.py`**: Thread-safe queue-based logging (`app_logger` global singleton), logs in `%APPDATA%\PFRSentinel\logs`.
- **`services/cleanup.py`**: Disk space management - **NEVER deletes folders**, only files.

### Critical Data Flow Patterns
1. **Directory Watch Mode**: `services/watcher.py` → detects file → waits for stability → reads sidecar → `services/processor.py` (file path) → processes with weather data → `_push_to_output_servers()` → outputs (file/web/discord/rtsp)
2. **Camera Capture Mode**: `services/zwo_camera.py` → captures RAW8 Bayer → debayer with OpenCV (BGGR pattern) → creates PIL Image + metadata dict → `ui/controllers/capture_controller.py` → `services/processor.py` (PIL Image) → processes → output servers
3. **Output Server Push**: After processing, `_push_to_output_servers()` checks config for enabled outputs:
   - **File**: `processor.save_processed_image()` to output_directory
   - **Web**: `web_output.WebOutputServer.update_image(image_path, image_bytes, metadata, content_type)`
   - **Discord**: `discord_alerts.post_image()` with weather embed (periodic timer-based)
   - **RTSP**: `rtsp_output.RTSPServer.update_frame()` for live streaming
4. **Dual Input Pattern in processor.py**: 
   ```python
   def add_overlays(image_input, overlays, metadata):
       # Accept PIL Image OR file path
       if isinstance(image_input, str):
           img = Image.open(image_input)
       else:
           img = image_input  # Already PIL Image from camera
   ```
5. **Qt UI Architecture**: Panel classes in `ui/panels/` create layouts. Controllers in `ui/controllers/` handle business logic. Communication via Qt signals/slots pattern. Main window coordinates navigation between pages.
6. **Config Location (v3.1.1)**: Config and logs now in `%APPDATA%\PFRSentinel` for proper multi-user support. Old root-level `config.json` files automatically migrated on first run.

## Key Technical Decisions

### Threading Architecture
- **Background threads**: Camera capture loop, directory watcher observer, Discord periodic posting run in separate threads
- **Qt thread safety**: All GUI updates via Qt signals/slots or `QMetaObject.invokeMethod()`, never direct from worker threads
- **Logger design**: Queue-based message passing (`logger.py`) to avoid race conditions
- **Image counter**: Atomic increments via callback pattern from both watcher and camera threads
- **Output servers**: Web server, RTSP server, Discord poster run in separate threads with proper shutdown handling

### ZWO Camera Integration
- **Debayering**: RAW8 Bayer BGGR → RGB using `cv2.cvtColor(data, cv2.COLOR_BayerBG2RGB)` with fallback `simple_debayer_rggb()`. **CRITICAL**: ASI676MC uses BGGR pattern, NOT RGGB - using wrong pattern causes red/blue color swap!
- **Auto Exposure**: Monitors mean brightness (target: 100), adjusts ±30% when outside 80-120 range, respects `max_exposure` limit. Logs changes in milliseconds.
- **Exposure Units**: GUI uses **milliseconds** (0.032ms to 3600000ms range), internally converted to seconds for SDK (0.000032s to 3600s)
- **SDK Location**: `ASICamera2.dll` in app root OR custom path via Capture tab
- **Camera Settings**: exposure, gain, white_balance_r/b (1-99), offset, flip (0-3), all persisted to config
- **Live Monitoring**: Dedicated Monitoring page with large preview (400x400), RGB histogram, and last 10 log lines for real-time feedback
- **Discord Integration**: Periodic image posting with configurable interval (1-60 min), weather data embeds, event notifications
- **Weather Data**: Optional OpenWeatherMap integration adds `{WEATHER}`, `{WEATHER_ICON}`, `{TEMP}`, `{HUMIDITY}` tokens

### Configuration Management
- **Location**: `%APPDATA%\PFRSentinel\config.json` (v3.1.1+) - managed by `app_config.py` for proper user data isolation
- **Migration**: Old root-level `config.json` automatically moved to AppData on first v3.1.1 run
- **Merge pattern**: `config.load()` merges saved JSON with `DEFAULT_CONFIG` to handle new keys from updates
- **Save timing**: After any settings change in panels (controller calls `config.save()`)
- **Critical keys**: 
  - `capture_mode` ("watch" or "camera")
  - `window.geometry` (persisted on close)
  - `output.webserver_enabled`, `output.discord_enabled`, `output.rtsp_enabled` (v3.1.1 nested structure)
  - `discord.webhook_url`, `discord.post_interval` (NEW v3.1.1)
  - `weather.api_key`, `weather.location` (NEW v3.1.1)
  - Overlay token patterns, ZWO camera settings
- **Import pattern**: Use `from services.config import Config` - config singleton in services package
- **CRITICAL BUG FIX (v3.1.1)**: Always use nested config keys `output_config.get('webserver_enabled')` NOT `config.get('web_enabled')`

## Code Quality Standards

### Qt Fluent Design Theming (v3.1.1)
- **Framework**: PySide6 + qfluentwidgets for Windows 11 Fluent Design styling
- **Theme module**: `ui/theme/` contains color palettes and QSS stylesheets
- **Color usage**: Use `ui/theme/colors.py` constants for consistent color palette
- **Widget library**: Use qfluentwidgets components (PushButton, CardWidget, FluentWindow, etc.) for native Fluent Design
- **Icons**: FluentIcon enum provides Microsoft Fluent icons (FluentIcon.CAMERA, FluentIcon.SETTING, etc.)
- **Signals/Slots**: Use Qt signal/slot pattern for event handling, NOT callbacks
- **Benefits**: Native Windows 11 look, smooth animations, consistent with OS design language

### File Size & Modularity
- **Target max: 500 lines per file** (hard cap: **550**) to keep modules focused and maintainable.
- If a file approaches limits, **split by responsibility** (not arbitrary chunks). Prefer extracting:
  - `models.py` (dataclasses / pydantic models)
  - `service.py` (core orchestration / use-cases)
  - `handlers.py` (API/CLI/UI entrypoints)
  - `repo.py` or `adapters/` (I/O, persistence, external integrations)
  - `errors.py` (feature-specific exceptions)
- For larger features, use a **package-per-feature folder** and grow via submodules:
  - `features/<feature_name>/...`
  - Add `features/<feature_name>/subflows/` or `features/<feature_name>/adapters/` when complexity increases.
- Avoid “catch-all” files like `utils.py`. Shared helpers must live in clearly named modules (e.g., `common/logging.py`, `common/datetime.py`) and stay single-purpose.
- Keep dependency direction clean: **domain/service code should not depend on UI/adapters**, and I/O should live at the edges.
- **Exceptions:** large constant data structures, generated code, or vendor schemas may exceed limits (document why at the top of the file).
- **Benefits:** easier testing, debugging, code review, and reuse.

## Developer Workflows

### Running the Application
```powershell
# Quick start (activates venv, runs app)
.\start.bat

# Manual (recommended for development)
.\venv\Scripts\Activate.ps1
python main.py
```

### Testing Changes
- **No automated tests exist** - manual testing required
- **Test both modes**: Switch `capture_mode` in Capture tab between "Directory Watch" and "ZWO Camera"
- **Verify thread safety**: Check Logs tab for any exceptions during concurrent operations
- **Camera testing**: Requires physical ZWO ASI camera connected via USB

### Adding New Features

#### Adding New Camera Controls
1. Add to `DEFAULT_CONFIG` in `services/config.py`
2. Add to `ZWOCamera.__init__()` in `services/zwo_camera.py`
3. Add GUI control in `gui/capture_tab.py` - create UI only
4. Add business logic in `gui/main_window.py` methods
5. Wire to `apply_settings()` method in `gui/main_window.py`
6. Use in `capture_single_frame()` or auto-exposure methods

#### Adding New Tab
1. Create `gui/new_tab.py` with class accepting `(notebook, app)`
2. Call `self.app.method_name()` to interact with business logic
3. Store widget references as `self.app.widget_var` for main window access
4. Import and instantiate in `gui/main_window.py` create_gui()
5. Add business logic methods to `gui/main_window.py`

### Debugging Tips
- **Logs page**: All components use `app_logger` - check for ERROR/WARN messages
- **Config issues**: Delete `%APPDATA%\PFRSentinel\config.json` to reset to defaults (v3.1.1 new location)
- **Camera not detected**: Verify `ASICamera2.dll` path, check USB connection, try `Detect Cameras` button in Capture page
- **Thread deadlocks**: Never call GUI methods directly from worker threads - use Qt signals/slots or `QMetaObject.invokeMethod()`
- **Web server 404**: Verify `output.webserver_enabled` is True in config (NOT `web_enabled` - v3.1.1 fix)
- **Discord not posting**: Check `discord.webhook_url` is valid, verify `output.discord_enabled` is True
- **Weather data N/A**: Verify `weather.api_key` and `weather.location` in config, check API quota
- **PyInstaller build issues**: Python 3.13 requires manual email module workaround - see `build_sentinel.bat`

## Project-Specific Conventions

### Overlay Token System
- **Standard tokens**: `{CAMERA}`, `{EXPOSURE}`, `{GAIN}`, `{TEMP}`, `{RES}`, `{FILENAME}`, `{SESSION}`, `{DATETIME}`
- **Weather tokens (NEW v3.1.1)**: `{WEATHER}`, `{WEATHER_ICON}`, `{TEMP}`, `{HUMIDITY}`, `{PRESSURE}`, `{WIND_SPEED}`
  - Requires `weather.api_key` and `weather.location` in config
  - Returns "N/A" if weather service unavailable
- **Implementation**: `replace_tokens()` in `processor.py` does case-insensitive regex replacement
- **Metadata sources**: Sidecar files (watch mode) OR camera properties dict (camera mode) OR weather API (when enabled)

### Output Filename Patterns
- **Tokens**: `{filename}`, `{session}`, `{timestamp}` (YYYYMMDD_HHMMSS)
- **Default**: `{session}_{filename}` - preserves original name with session prefix
- **Session derivation**: Parent folder name in watch mode, current date in camera mode

### Image Processing Pipeline
1. Load/capture image (PIL Image or file path)
2. Fetch weather data if enabled (cached for 10 minutes to avoid API spam)
3. **Resize first** (if `resize_percent` < 100) to reduce processing on overlays
4. Add timestamp corner (optional, top-right by default)
5. Add all configured overlays with token replacement (including weather tokens)
6. Convert to output format (PNG lossless or JPG with quality setting)
7. Push to all enabled outputs (file/web/discord/rtsp) via `_push_to_output_servers()`
8. Update monitoring panel with preview and histogram

### Cleanup Strategy
- **Only deletes files**: `cleanup.py` uses `os.path.isfile()` check before any deletion
- **Size calculation**: Walks directory tree, sums file sizes, checks against `cleanup_max_size_gb`
- **Strategy**: "Delete oldest files in watch directory" - sorts by mtime, deletes oldest first
- **Safety**: Never touches subdirectories themselves, preserves folder structure

## Critical Files & Their Roles (v3.1.1)

### UI Package (`ui/`) - PySide6 + qfluentwidgets
- **`main_window.py`**: Qt FluentWindow with QStackedWidget for page navigation, connects controllers to panels
- **`system_tray_qt.py`**: QSystemTrayIcon with notifications, context menu for quick controls
- **`components/header.py`**: Status bar with visual indicators (waiting/capturing/calibrating/processing/sending)
- **`components/monitoring_panel.py`**: Live preview QLabel (400x400), RGB histogram QChart, mini-log QPlainTextEdit
- **`panels/monitoring.py`**: Monitoring page - dedicated real-time feed view
- **`panels/capture.py`**: Capture settings page - watch/camera mode selection, camera controls
- **`panels/output.py`**: Output modes page - File/Web/Discord/RTSP cards with enable/disable buttons
- **`panels/overlays.py`**: Overlay editor page - list + editor split view
- **`panels/logs.py`**: Log viewer page - searchable log display with filter/save
- **`controllers/capture_controller.py`**: Business logic for watch/camera mode, starts/stops capture threads
- **`controllers/output_controller.py`**: Manages output servers (web/discord/rtsp), handles start/stop/status
- **`controllers/overlay_controller.py`**: CRUD operations for overlays, updates preview
- **`theme/colors.py`**: Fluent Design color palette constants
- **`theme/styles.py`**: QSS stylesheets for custom widget styling

### Services Package (`services/`)
- **`zwo_camera.py`**: `ZWOCamera` class, SDK wrapper, BGGR debayering, auto exposure
- **`processor.py`**: Image overlay engine with weather token support, `add_overlays()` dual-input handler, `process_image()` pipeline
- **`watcher.py`**: `FileWatcher` class with file stability checks for directory watch mode
- **`discord_alerts.py` (NEW v3.1.1)**: Discord webhook client, `post_image()` with embed, periodic posting thread
- **`weather.py` (NEW v3.1.1)**: OpenWeatherMap API client, 10-minute caching, provides weather data for tokens
- **`web_output.py`**: `WebOutputServer` with ImageHTTPHandler, `/latest` (image) and `/status` (JSON metadata) endpoints
- **`rtsp_output.py`**: `RTSPServer` using ffmpeg for H.264 streaming at rtsp://127.0.0.1:8554/stream
- **`config.py`**: JSON persistence in `%APPDATA%\PFRSentinel\config.json` with merge pattern
- **`logger.py`**: Thread-safe queue-based logging singleton, logs in `%APPDATA%\PFRSentinel\logs`
- **`cleanup.py`**: Disk space management (files only, never folders)
- **`camera_connection.py`**: ZWO SDK initialization, camera detection, connect/disconnect logic
- **`camera_calibration.py`**: Auto-exposure algorithms for ZWO cameras
- **`camera_utils.py`**: Shared camera utility functions

### Root Files
- **`main.py`**: Entry point - imports `from ui.main_window import main`, initializes Qt application
- **`app_config.py`**: Config location management, returns `%APPDATA%\PFRSentinel` path, handles migration
- **`version.py`**: Version constants (VERSION, BUILD_DATE) used by installer and about dialog
- **`requirements.txt`**: Dependencies (PySide6, qfluentwidgets, watchdog, Pillow, opencv-python, requests, etc.)
- **`PFRSentinel.spec`**: PyInstaller spec file for building standalone executable
- **`start.bat`**: Quick launch script for development (activates venv, runs main.py)
- **`build_sentinel.bat`**: PyInstaller build script (creates dist/PFRSentinel.exe)
- **`build_sentinel_installer.bat`**: Inno Setup build script (creates PFRSentinel_Setup.exe)
- **`version.iss`**: Inno Setup installer configuration

### Documentation (`docs/`)
- **`README.md`**: Full feature documentation
- **`QUICKSTART.md`**: 5-minute setup guide
- **`ZWO_SETUP_GUIDE.md`**: Camera configuration
- **`PROJECT_STRUCTURE.md`**: Architecture overview
- **`PROJECT_TREE.md`**: Visual file organization

## Common Pitfalls

1. **Don't modify config.json directly** - always use `config.set()` and `config.save()`
2. **Don't add GUI calls in worker threads** - use Qt signals/slots or `QMetaObject.invokeMethod()` for thread safety
3. **Don't use wrong config keys** - CRITICAL: Use nested paths like `output_config.get('webserver_enabled')` NOT top-level `config.get('web_enabled')` (v3.1.1 bug fix)
4. **Don't pass wrong parameter order** - `WebOutputServer.update_image(image_path, image_bytes, metadata=..., content_type=...)` (v3.1.1 bug fix)
5. **Don't assume PIL Image input in processor** - check type first (str vs Image)
6. **Don't delete folders in cleanup** - filter with `os.path.isfile()`
7. **Don't skip debayering** - ZWO cameras output RAW8 Bayer, not RGB
8. **Don't use wrong Bayer pattern** - ASI676MC is BGGR (COLOR_BayerBG2RGB), not RGGB
9. **Don't forget to increment image_count** - both watch and camera callbacks must update
10. **Don't put business logic in panel files** - panels are UI only, logic goes in controllers
11. **Don't use absolute imports within packages** - use relative imports (`.module`) in ui/ and services/
12. **Don't break backward compatibility** - old config.json files must still load via merge pattern
13. **Don't spam weather API** - use 10-minute caching in `weather.py` to avoid rate limits
14. **Don't hardcode config paths** - use `app_config.get_config_dir()` for proper AppData location

## External Dependencies

- **Python 3.13.5**: Latest Python with async support
- **PySide6 6.8.1**: Qt6 bindings for Python (replaces Tkinter in v3.1.1)
- **qfluentwidgets 1.10.5**: Fluent Design components for PySide6 (replaces ttkbootstrap in v3.1.1)
- **ZWO ASI SDK**: `ASICamera2.dll` (Windows) from https://astronomy-imaging-camera.com/software-drivers
- **OpenCV**: `opencv-python` for Bayer debayering (`cv2.cvtColor` with COLOR_BayerBG2RGB)
- **zwoasi**: Unofficial Python wrapper for ZWO SDK (pip package)
- **Pillow (PIL)**: Image processing library
- **watchdog**: File system monitoring for directory watch mode
- **numpy**: Array operations for image data
- **requests**: HTTP client for weather API and Discord webhooks (NEW v3.1.1)
- **ffmpeg** (optional): External binary for RTSP streaming, auto-detected by application
- **PyInstaller 6.17.0**: Packaging tool for standalone executable (requires manual email module workaround for Python 3.13)

## When Modifying Code

### General Guidelines
- **Preserve backward compatibility**: Old `config.json` files should still load (merge pattern handles this)
- **Update both modes**: Changes to overlay processing must work for watch AND camera modes
- **Test thread safety**: Use `app_logger` for all logging, never print() from threads
- **Document new tokens**: Update `docs/README.md` "Available Tokens" section if adding metadata fields
- **Verify cleanup safety**: Any changes to file handling must check `os.path.isfile()` before deletion

### Module-Specific Guidelines
- **GUI modules**: Keep UI layout in tab files, move business logic to `main_window.py`
- **Services modules**: Use relative imports (`.logger`, `.config`) within services package
- **Import pattern**: `from services.module import Class` from outside, `from .module import Class` from within
- **Auto-fit preview**: `refresh_preview(auto_fit=True)` calculates best zoom, `auto_fit=False` respects manual zoom
- **Window geometry**: Saved on close, loaded on start - stored in config.json as `window_geometry`

### Testing Checklist
- [ ] Test directory watch mode with new files
- [ ] Test camera capture mode with physical camera
- [ ] Verify overlays render correctly in both modes
- [ ] Check logs tab for errors/warnings
- [ ] Verify settings persistence (close/reopen app)
- [ ] Test preview auto-fit zoom with various image sizes
- [ ] Check live monitoring header updates (preview, histogram, mini-logs)
- [ ] Verify cleanup doesn't delete folders
