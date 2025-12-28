# AI Agent Instructions for ASIOverlayWatchDog

## Project Overview
Dual-mode astrophotography application: (1) watches directories for new images and adds metadata overlays, or (2) captures directly from ZWO ASI cameras with real-time processing. Built for 24/7 unattended operation with modern modular architecture.

## Project Structure (v2.0.0+)

### Modular Organization
```
ASIOverlayWatchDog/
├── gui/                    # Modern modular GUI (9 files)
│   ├── main_window.py     # Application core + business logic (1024 lines)
│   ├── header.py          # Status & live monitoring components
│   ├── capture_tab.py     # Directory watch & camera UI
│   ├── settings_tab.py    # Configuration UI
│   ├── overlay_tab.py     # Overlay editor with master/detail
│   ├── preview_tab.py     # Image preview with auto-fit zoom
│   ├── logs_tab.py        # Log viewer
│   └── overlays/          # Modular overlay system (NEW)
│       ├── __init__.py
│       ├── constants.py   # Token defs, presets, defaults
│       ├── overlay_list.py # Treeview-based list
│       ├── text_editor.py # Text overlay editor
│       └── preview.py     # Canvas preview
├── services/               # Core processing modules
│   ├── config.py          # JSON persistence with merge pattern
│   ├── logger.py          # Thread-safe queue-based logging
│   ├── processor.py       # Image overlay engine
│   ├── watcher.py         # Directory monitoring
│   ├── zwo_camera.py      # ZWO ASI camera core (675 lines - exception granted)
│   ├── camera_connection.py # SDK init, detection, connect/reconnect
│   ├── camera_calibration.py # Auto-exposure algorithms
│   ├── camera_utils.py    # Shared camera utilities
│   └── cleanup.py         # Disk space management
├── docs/                   # Documentation (6 files)
├── archive/                # Legacy code (gui_modern.py, gui_new.py)
├── main.py                 # Application entry point
└── config.json             # Runtime state (auto-generated)
```

### Core Components
- **`gui/main_window.py`**: Main application class with ALL business logic. Tab files contain ONLY UI layout.
- **`services/processor.py`**: Image overlay engine. **Critical**: Accepts EITHER PIL Image objects OR file paths, metadata dict OR sidecar parsing.
- **`services/watcher.py`**: watchdog-based FileSystemEventHandler for directory monitoring mode.
- **`services/zwo_camera.py`**: ZWO ASI SDK wrapper for direct camera capture with debayering.
- **`services/config.py`**: JSON persistence (`config.json`) with merge-on-load pattern for new defaults.
- **`services/logger.py`**: Thread-safe queue-based logging (`app_logger` global singleton).
- **`services/cleanup.py`**: Disk space management - **NEVER deletes folders**, only files.

### Critical Data Flow Patterns
1. **Directory Watch Mode**: `services/watcher.py` → detects file → waits for stability → reads sidecar → `services/processor.py` (file path) → saves annotated image → callback to `gui/main_window.py` increments counter
2. **Camera Capture Mode**: `services/zwo_camera.py` → captures RAW8 Bayer → debayer with OpenCV (BGGR pattern) → creates PIL Image + metadata dict → `gui/main_window.py` process_and_save_image() → `services/processor.py` (PIL Image) → saves → callback increments counter
3. **Dual Input Pattern in processor.py**: 
   ```python
   def add_overlays(image_input, overlays, metadata):
       # Accept PIL Image OR file path
       if isinstance(image_input, str):
           img = Image.open(image_input)
       else:
           img = image_input  # Already PIL Image from camera
   ```
4. **GUI Architecture**: Tab files (`capture_tab.py`, `settings_tab.py`, etc.) create UI layout ONLY. All event handlers and business logic live in `gui/main_window.py`. Tabs receive `app` reference to call main window methods.

## Key Technical Decisions

### Threading Architecture
- **Background threads**: Camera capture loop, directory watcher observer run in separate threads
- **GUI safety**: All GUI updates via `root.after()` callbacks, never direct from worker threads
- **Logger design**: Queue-based message passing (`logger.py`) to avoid race conditions
- **Image counter**: Atomic increments via callback pattern from both watcher and camera threads

### ZWO Camera Integration
- **Debayering**: RAW8 Bayer BGGR → RGB using `cv2.cvtColor(data, cv2.COLOR_BayerBG2RGB)` with fallback `simple_debayer_rggb()`. **CRITICAL**: ASI676MC uses BGGR pattern, NOT RGGB - using wrong pattern causes red/blue color swap!
- **Auto Exposure**: Monitors mean brightness (target: 100), adjusts ±30% when outside 80-120 range, respects `max_exposure` limit. Logs changes in milliseconds.
- **Exposure Units**: GUI uses **milliseconds** (0.032ms to 3600000ms range), internally converted to seconds for SDK (0.000032s to 3600s)
- **SDK Location**: `ASICamera2.dll` in app root OR custom path via Capture tab
- **Camera Settings**: exposure, gain, white_balance_r/b (1-99), offset, flip (0-3), all persisted to config
- **Live Monitoring**: Header includes mini preview (200x200), RGB histogram, and last 10 log lines for quick feedback without tab switching

### Configuration Management
- **Merge pattern**: `config.load()` merges saved JSON with `DEFAULT_CONFIG` to handle new keys from updates
- **Save timing**: After any settings change in GUI (`apply_settings()` in `gui/main_window.py`)
- **Critical keys**: `capture_mode` ("watch" or "camera"), `window_geometry` (persisted on close), overlay token patterns, ZWO settings
- **Import pattern**: Use `from services.config import Config` - config is in services package

## Code Quality Standards

### Theme Consistency Requirements
- **ALWAYS use `gui/theme.py` constants** - never hardcode colors, fonts, or spacing
- **Color usage**: Import `COLORS` dict and reference by key (e.g., `COLORS['bg_card']`, `COLORS['accent_primary']`)
- **Font usage**: Import `FONTS` dict and reference by key (e.g., `FONTS['body']`, `FONTS['title']`)
- **Spacing usage**: Import `SPACING` dict for all padding/margins (e.g., `SPACING['element_gap']`, `SPACING['section_gap']`)
- **Button creation**: Use `theme.create_primary_button()`, `theme.create_secondary_button()`, `theme.create_destructive_button()`
- **Card creation**: Use `theme.create_card(parent, title)` for consistent card containers
- **Import pattern**: `from .theme import COLORS, FONTS, SPACING` and `from . import theme`
- **Benefits**: Consistent UI, easy theme updates, maintainable styling

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
- **Logs tab**: All components use `app_logger` - check for ERROR/WARN messages
- **Config issues**: Delete `config.json` to reset to defaults
- **Camera not detected**: Verify `ASICamera2.dll` path, check USB connection, try `Detect Cameras` button
- **Thread deadlocks**: Never call GUI methods directly from worker threads - use `root.after(0, callback)`

## Project-Specific Conventions

### Overlay Token System
- **Format**: `{CAMERA}`, `{EXPOSURE}`, `{GAIN}`, `{TEMP}`, `{RES}`, `{FILENAME}`, `{SESSION}`, `{DATETIME}`
- **Implementation**: `replace_tokens()` in `processor.py` does case-insensitive regex replacement
- **Metadata sources**: Sidecar files (watch mode) OR camera properties dict (camera mode)

### Output Filename Patterns
- **Tokens**: `{filename}`, `{session}`, `{timestamp}` (YYYYMMDD_HHMMSS)
- **Default**: `{session}_{filename}` - preserves original name with session prefix
- **Session derivation**: Parent folder name in watch mode, current date in camera mode

### Image Processing Pipeline
1. Load/capture image
2. **Resize first** (if `resize_percent` < 100) to reduce processing on overlays
3. Add timestamp corner (optional, top-right by default)
4. Add all configured overlays with token replacement
5. Convert to output format (PNG lossless or JPG with quality setting)
6. Save to `output_directory`

### Cleanup Strategy
- **Only deletes files**: `cleanup.py` uses `os.path.isfile()` check before any deletion
- **Size calculation**: Walks directory tree, sums file sizes, checks against `cleanup_max_size_gb`
- **Strategy**: "Delete oldest files in watch directory" - sorts by mtime, deletes oldest first
- **Safety**: Never touches subdirectories themselves, preserves folder structure

## Critical Files & Their Roles

### GUI Package (`gui/`)
- **`theme.py` (234 lines)**: **CRITICAL - Centralized styling module**
  - **COLORS dict** (36 entries): All color constants - backgrounds, text, accents, status indicators
  - **FONTS dict** (6 entries): Typography scale - title, heading, body, body_bold, small, tiny
  - **SPACING dict** (7 entries): Layout spacing constants - card padding/margins, gaps between elements
  - **LAYOUT dict** (3 entries): Structural constants - label widths, button padding
  - **Button factories**: `create_primary_button()`, `create_secondary_button()`, `create_destructive_button()`
  - **Card factory**: `create_card(parent, title)` - Creates themed card containers
  - **Style configurator**: `configure_dark_input_styles()` - TTK widget theming
  - **USAGE MANDATE**: ALL GUI files MUST import and use theme constants - never hardcode colors/spacing/fonts
  - **Import pattern**: `from .theme import COLORS, FONTS, SPACING` and `from . import theme` for factories
- **`main_window.py` (1224 lines)**: Main application class `ModernOverlayApp`, ALL business logic, event handlers, camera/watch operations
- **`header.py` (195 lines)**: `StatusHeader` and `LiveMonitoringHeader` components - uses SPACING constants
- **`capture_tab.py` (527 lines)**: Directory watch & camera capture UI - themed with button factories
- **`settings_tab.py` (319 lines)**: Output, processing, cleanup settings - all themed components
- **`overlay_tab.py` (103 lines)**: Overlay editor coordinator - 2-column layout with theme spacing
- **`preview_tab.py` (133 lines)**: Image preview with auto-fit zoom - themed controls
- **`logs_tab.py` (105 lines)**: Log display UI - themed buttons and layout
- **`overlays/` package**: Modular overlay system (NEW v2.0)
  - **`constants.py` (59 lines)**: Token definitions, presets, defaults
  - **`overlay_list.py` (72 lines)**: Treeview-based list panel
  - **`text_editor.py` (345 lines)**: Complete text overlay editor
  - **`preview.py` (38 lines)**: Canvas preview component
  - **`overlay_tab.py` (119 lines)**: Main coordinator (modular)

### Services Package (`services/`)
- **`zwo_camera.py` (354 lines)**: `ZWOCamera` class, SDK wrapper, BGGR debayering, auto exposure
- **`processor.py` (380 lines)**: `add_overlays()` dual-input handler, `process_image()` pipeline
- **`watcher.py` (177 lines)**: `FileWatcher` class with file stability checks
- **`config.py`**: JSON persistence with merge pattern
- **`logger.py`**: Thread-safe queue-based logging singleton
- **`cleanup.py`**: Disk space management (files only, never folders)

### Root Files
- **`main.py` (8 lines)**: Entry point - imports `from gui.main_window import main`
- **`config.json`**: Runtime state - DO NOT commit to git, regenerated from defaults
- **`requirements.txt`**: Dependencies (watchdog, Pillow, ttkbootstrap, zwoasi, numpy, opencv-python)
- **`start.bat`**: Quick launch script for Windows

### Documentation (`docs/`)
- **`README.md`**: Full feature documentation
- **`QUICKSTART.md`**: 5-minute setup guide
- **`ZWO_SETUP_GUIDE.md`**: Camera configuration
- **`PROJECT_STRUCTURE.md`**: Architecture overview
- **`PROJECT_TREE.md`**: Visual file organization

## Common Pitfalls

1. **Don't modify config.json directly** - always use `config.set()` and `config.save()`
2. **Don't add GUI calls in worker threads** - use callbacks or `root.after()`
3. **Don't assume PIL Image input in processor** - check type first (str vs Image)
4. **Don't delete folders in cleanup** - filter with `os.path.isfile()`
5. **Don't skip debayering** - ZWO cameras output RAW8 Bayer, not RGB
6. **Don't use wrong Bayer pattern** - ASI676MC is BGGR (COLOR_BayerBG2RGB), not RGGB
7. **Don't forget to increment image_count** - both watch and camera callbacks must update
8. **Don't put business logic in tab files** - tabs are UI only, logic goes in `main_window.py`
9. **Don't use absolute imports within packages** - use relative imports (`.module`) in gui/ and services/
10. **Don't break backward compatibility** - old config.json files must still load via merge pattern

## External Dependencies

- **ZWO ASI SDK**: `ASICamera2.dll` (Windows) from https://astronomy-imaging-camera.com/software-drivers
- **Python 3.7+**: Uses Tkinter (built-in), threading (built-in)
- **ttkbootstrap**: Modern dark theme for Tkinter (darkly theme used)
- **OpenCV**: `opencv-python` for Bayer debayering (`cv2.cvtColor` with COLOR_BayerBG2RGB)
- **zwoasi**: Unofficial Python wrapper for ZWO SDK (pip package)
- **Pillow (PIL)**: Image processing library
- **watchdog**: File system monitoring for directory watch mode
- **numpy**: Array operations for image data

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
