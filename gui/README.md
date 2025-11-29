# GUI Module Structure

The AllSky Overlay Watchdog GUI has been refactored into a modular structure for better maintainability.

## File Organization

```
gui/
├── __init__.py               # Package entry point
├── main_window.py            # Main application class with business logic
├── header.py                 # Status and live monitoring headers
├── capture_tab.py            # Directory watch and camera capture controls
├── settings_tab.py           # Output, processing, and cleanup settings
├── overlay_tab.py            # Overlay list and editor with preview
├── preview_tab.py            # Image preview with zoom controls
├── logs_tab.py               # Log display with controls
└── overlay_list_item.py      # Overlay list item widget
```

## Module Responsibilities

### main_window.py
- Application lifecycle (initialization, closing)
- Business logic for all operations
- Event handlers (mode changes, toggles, selections)
- Camera operations (detect, start/stop capture, capture loop)
- Directory watching (start/stop, file processing callback)
- Image processing (resize, brightness, overlays, save)
- Overlay management (CRUD operations, preview generation)
- Configuration loading/saving
- Status updates and log polling

### header.py
- `StatusHeader`: Session info, image count, output directory
- `LiveMonitoringHeader`: Last capture preview, RGB histogram, recent logs

### capture_tab.py
- Mode selection (Directory Watch vs ZWO Camera)
- Directory watch settings (path, recursive option, start/stop buttons)
- ZWO camera settings (SDK path, detection, camera selection, parameters)
- Camera controls (exposure, gain, white balance, offset, flip)

### settings_tab.py
- Output settings (directory, filename pattern, format, JPG quality)
- Image processing (resize, auto brightness, timestamp corner)
- Cleanup settings (enabled, max size, strategy)

### overlay_tab.py
- Master/detail layout with overlay list
- Toolbar (add, duplicate, delete all)
- Overlay editor (text, position, color, font, offsets)
- Token insertion for metadata
- Live preview of selected overlay

### preview_tab.py
- Image preview canvas with scrollbars
- Zoom controls (10% to 200%)
- Refresh button

### logs_tab.py
- Log display with color-coded levels (ERROR, WARNING, INFO, DEBUG)
- Controls (clear, save, auto-scroll toggle)

### overlay_list_item.py
- Individual overlay list entry widget
- Shows overlay preview text, position, and color
- Selection highlighting
- Delete button

## Benefits of Modular Structure

1. **Maintainability**: Each file has a single, focused responsibility
2. **Readability**: Reduced file sizes (200-300 lines vs 1573 lines)
3. **Reusability**: Tab components can be tested or reused independently
4. **Collaboration**: Multiple developers can work on different tabs simultaneously
5. **Testing**: Easier to write unit tests for individual components

## Usage

Import from the gui package:

```python
from gui.main_window import main

if __name__ == '__main__':
    main()
```

All business logic remains in `main_window.py`, while tab components focus only on UI layout.
