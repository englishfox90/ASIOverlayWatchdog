# Project Structure and Organization

## Overview

The AllSky Overlay Watchdog project has been reorganized into a clean, modular structure for better maintainability and scalability.

## Directory Structure

### `/gui` - User Interface
Modern modular GUI built with ttkbootstrap:
- `main_window.py` (1024 lines) - Application core with all business logic
- `header.py` (87 lines) - Status and live monitoring components
- `capture_tab.py` (218 lines) - Directory watch and camera capture UI
- `settings_tab.py` (153 lines) - Configuration settings UI
- `overlay_tab.py` (185 lines) - Overlay editor with master/detail layout
- `preview_tab.py` (45 lines) - Image preview with zoom controls
- `logs_tab.py` (37 lines) - Log viewer with color-coded levels
- `overlay_list_item.py` (48 lines) - Reusable list item widget
- `README.md` - GUI architecture documentation

**Design Philosophy**: Separation of UI (tab files) from business logic (main_window.py)

### `/services` - Core Services
Backend processing and hardware integration:
- `config.py` - JSON-based configuration with merge-on-load pattern
- `logger.py` - Thread-safe queue-based logging system
- `processor.py` - Image overlay engine (PIL Image input/file path dual support)
- `watcher.py` - watchdog-based directory monitoring with file stability checks
- `cleanup.py` - Disk space management (never deletes folders, only files)

**ZWO Camera Modules** (split for maintainability):
- `zwo_camera.py` (675 lines) - Core ZWOCamera class, capture loop (**exception to 550-line limit**)
- `camera_connection.py` (505 lines) - SDK initialization, camera detection, connection/reconnection
- `camera_calibration.py` (330 lines) - Auto-exposure calibration algorithms
- `camera_utils.py` (230 lines) - Shared utilities (debayer, white balance, stats)

> ⚠️ **Note**: `zwo_camera.py` exceeds the 550-line limit due to tightly-coupled capture loop state.
> **New camera functionality must be added to companion modules, not zwo_camera.py.**

**Design Philosophy**: Reusable, testable modules with clear single responsibilities

### `/docs` - Documentation
Project documentation:
- `README.md` - Complete feature documentation and usage guide
- `QUICKSTART.md` - 5-minute setup guide for new users
- `ZWO_SETUP_GUIDE.md` - ZWO ASI camera configuration walkthrough
- `MODERNIZATION.md` - UI development notes and design decisions
- `PROJECT_STRUCTURE.md` (this file) - Architecture overview

### `/archive` - Legacy Code
Deprecated code retained for reference:
- `gui_modern.py` - Previous monolithic GUI (1573 lines)
- `gui_new.py` - Earlier GUI implementation

**Note**: These files are kept for historical reference but are not used by the application.

### Root Directory
- `main.py` - Application entry point (8 lines)
- `config.json` - Runtime configuration (generated, not version controlled)
- `requirements.txt` - Python package dependencies
- `start.bat` - Quick-launch script for Windows
- `ASICamera2.dll` - ZWO ASI SDK library
- `README.md` - Project overview and quick start

## Import Structure

### From Application Code
```python
from gui.main_window import main  # Entry point

from services.config import Config
from services.logger import app_logger
from services.processor import process_image, add_overlays
from services.watcher import FileWatcher
from services.zwo_camera import ZWOCamera
from services.cleanup import run_cleanup
```

### Within Services Package
Services use relative imports:
```python
from .logger import app_logger
from .processor import process_image
```

## Benefits of New Structure

1. **Modularity**: Each file has 37-218 lines instead of one 1573-line monolith
2. **Maintainability**: Clear separation of concerns makes changes easier
3. **Testability**: Individual components can be unit tested
4. **Collaboration**: Multiple developers can work on different modules
5. **Documentation**: Each folder has its own README explaining its purpose
6. **Reusability**: Service modules can be imported independently
7. **Clarity**: New developers can quickly understand the codebase

## Development Workflow

### Adding a New Feature
1. Identify which service module(s) need changes
2. Update business logic in `gui/main_window.py` if needed
3. Update UI in appropriate tab file(s)
4. Test the feature end-to-end
5. Update relevant documentation

### Debugging
- Check `gui/main_window.py` for business logic issues
- Check specific tab files for UI rendering issues
- Check service modules for processing/hardware issues
- Use the Logs tab for runtime diagnostics

### Testing
1. Run application: `python main.py` or `.\start.bat`
2. Check all tabs load correctly
3. Test both capture modes (directory watch and camera)
4. Verify overlays render correctly
5. Check configuration persistence

## Migration Notes

### Changes from Previous Version
- **Old**: Single `gui_modern.py` file (1573 lines)
- **New**: Modular `gui/` package with 9 files

### Import Changes
- **Old**: `from gui_modern import main`
- **New**: `from gui.main_window import main`

### Service Module Changes
- **Old**: Services in root directory
- **New**: Services in `/services` package with `__init__.py`

### Documentation Changes
- **Old**: All docs in root directory
- **New**: Organized in `/docs` folder

## Future Enhancements

Potential areas for expansion:
- `/tests` - Unit and integration tests
- `/plugins` - Custom overlay generators or processors
- `/themes` - Custom ttkbootstrap themes
- `/presets` - Saved configuration presets

## Maintenance Guidelines

1. **Keep business logic in `main_window.py`**: Tab files should only contain UI layout
2. **Use relative imports within packages**: Services use `from .module import`
3. **Document public APIs**: All service modules should have clear docstrings
4. **Preserve backward compatibility**: Old `config.json` files should still load
5. **Test both capture modes**: Changes should work for watch and camera modes
6. **Update documentation**: Keep README files current with code changes
7. **Respect 550-line limit**: Files should not exceed 550 lines (soft target: 500)
8. **Do NOT inflate zwo_camera.py**: New camera logic goes in companion modules:
   - Connection/SDK → `camera_connection.py`
   - Calibration/auto-exposure → `camera_calibration.py`
   - Utilities/helpers → `camera_utils.py`

## Version History

- **v2.0.0** (Nov 2025): Modular refactoring, organized folder structure
- **v1.x**: Monolithic GUI implementation (archived)

---

For detailed component documentation, see:
- [GUI Architecture](../gui/README.md)
- [Main README](../README.md)
- [Quick Start Guide](QUICKSTART.md)
