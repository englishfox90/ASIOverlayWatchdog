# PFR Sentinel

**Live Camera Monitoring & Overlay System for Observatories**

A modern, production-ready application with a Fluent Design UI that either watches directories for new images or captures directly from ZWO ASI cameras, adding customizable metadata overlays with weather data and serving output through multiple channels (file, web server, Discord, or RTSP streaming).

---

## Table of Contents
1. [Overview](#overview)
2. [Key Features](#key-features)
3. [Installation for End Users](#installation-for-end-users)
4. [Quick Start Usage](#quick-start-usage)
5. [Advanced: Command Line Options](#advanced-command-line-options)
6. [Running from Source (Developers)](#running-from-source-developers)
7. [Building the Executable](#building-the-executable)
8. [Getting Support & Sharing Logs](#getting-support--sharing-logs)
9. [License & Credits](#license--credits)

---

## Overview

**PFR Sentinel** is designed for 24/7 unattended astrophotography operations. It provides two distinct capture modes:

1. **Directory Watch Mode**: Monitors a folder for new images (from any camera/software), reads sidecar metadata files, and adds overlays
2. **ZWO Camera Mode**: Captures directly from ZWO ASI cameras with auto-exposure, debayering, and real-time processing

The application features multiple output modes:
- **File Mode**: Save processed images to disk (traditional workflow)
- **Webserver Mode**: Serve latest image via HTTP (http://127.0.0.1:8080/latest)
- **Discord Integration**: Periodic image posts with weather data and overlay information
- **RTSP Streaming Mode**: Live H.264 stream for video applications (rtsp://127.0.0.1:8554/stream)

Built with a modern Fluent Design UI using PySide6 and qfluentwidgets, PFR Sentinel includes live monitoring (preview, RGB histogram, recent logs), weather integration with OpenWeatherMap, 7-day rotating file logs for troubleshooting, and command-line automation support for scheduled tasks.

---

## Key Features

### Capture & Processing
- ✅ **Dual Capture Modes**: Directory monitoring or direct ZWO ASI camera capture
- ✅ **Auto-Exposure**: Intelligent brightness adjustment targeting optimal exposure levels
- ✅ **Debayering**: Automatic Bayer pattern conversion (BGGR) for ZWO color cameras
- ✅ **Auto-Stretch**: MAD-based histogram stretch for optimal image visibility
- ✅ **Customizable Overlays**: Text overlays with metadata tokens (camera name, exposure, gain, temperature, resolution, filename, session, datetime)
- ✅ **Resize Processing**: Optional image resizing before overlay processing
- ✅ **Output Formats**: PNG (lossless) or JPEG (adjustable quality)

### Output Modes
- ✅ **File Output**: Traditional save-to-disk workflow
- ✅ **Web Server**: HTTP server with `/latest` (image) and `/status` (JSON) endpoints, ETag caching support
- ✅ **Discord Integration**: Periodic image posts with capture info, weather data, and event notifications
- ✅ **RTSP Streaming**: Live H.264 video stream via ffmpeg (requires ffmpeg installation)
- ✅ **Smart Detection**: Automatic ffmpeg availability check with helpful UI feedback
- ✅ **Weather Data**: Optional OpenWeatherMap integration for weather overlays and Discord embeds

### User Interface
- ✅ **Modern Fluent Design UI**: Professional PySide6 + qfluentwidgets interface with Windows 11 styling
- ✅ **Live Monitoring Panel**: Real-time preview, RGB histogram, and mini-log viewer in dedicated panel
- ✅ **Navigation Interface**: Monitoring, Capture, Output, Overlays, and Logs pages with smooth transitions
- ✅ **Real-time Preview**: Auto-fit zoom with manual controls and metadata display
- ✅ **Status Bar**: Visual indicators for capture, calibration, processing, and sending states
- ✅ **System Tray**: Native Qt system tray with notifications and quick controls

### Automation & Reliability
- ✅ **Command Line Support**: `--auto-start`, `--auto-stop`, `--headless`, `--tray` flags for scripting
- ✅ **Headless Mode**: Run without GUI for servers, Docker, or scheduled tasks
- ✅ **System Tray Mode**: Minimize to Windows system tray with right-click menu controls
- ✅ **Automatic Camera Detection**: Retry logic ensures reliable unattended startup
- ✅ **7-Day Rotating Logs**: File-based logging in `%APPDATA%\PFRSentinel\Logs`
- ✅ **Disk Space Management**: Automated cleanup with configurable size limits
- ✅ **Thread-Safe Architecture**: Robust multi-threaded design for 24/7 operation
- ✅ **Error Recovery**: Discord webhook integration for critical error alerts (optional)

### Camera Features (ZWO Mode)
- ✅ **ZWO ASI SDK Integration**: Native support for all ZWO ASI cameras
- ✅ **Adjustable Settings**: Exposure (0.032ms - 3600000ms), gain, offset, white balance
- ✅ **Flip Controls**: Rotate image 0°/90°/180°/270°
- ✅ **SDK Path Selection**: Custom ASICamera2.dll location support
- ✅ **Camera Selection**: Dropdown for multi-camera setups

---

## Installation fInstaller (Recommended)

**→ [Download Latest Release](releases/) ← Get PFRSentinel_Setup.exe**

1. **Download**: Get `PFRSentinel_Setup.exe` from the `releases/` folder
2. **Install**: Run the installer - it will install to `Program Files\PFR Sentinel` by default
3. **Run**: Launch from Start Menu or desktop shortcut - **That's it!**

**✅ Completely Self-Contained - No Installation Required:**
- ✅ Python runtime embedded (no Python installation needed)
- ✅ All dependencies included (PySide6, qfluentwidgets, Pillow, OpenCV, NumPy, etc.)
- ✅ ZWO ASI SDK bundled (`ASICamera2.dll` included)
- ✅ Works on Windows 10/11 (64-bit, Windows 7 may work but untested)
- ✅ Installer handles Start Menu shortcuts and uninstaller registration

**Optional Dependencies:**
- **ffmpeg** - Only needed for RTSP streaming mode (see [ffmpeg installation](#ffmpeg-installation) below)
  - File, Webserver, and Discord modes work without ffmpeg
  - RTSP option will be unavailable if ffmpeg not found
- **OpenWeatherMap API Key** - Free key for weather data overlays and Discord embeds (optional)see [ffmpeg installation](#ffmpeg-installation) below)
  - File and Webserver modes work without ffmpeg
  - RTSP button will be disabled if ffmpeg not found

### First Run Setup

On first launch, the application will:
- Create a default `config.json` in `%APPDATA%\PFRSentinel`
- Create a log directory at `%APPDATA%\PFRSentinel\logs`
- Show the Monitoring panel with live preview and histogram

**No Python required** - it's a standalone application with installer!

#### Windows SmartScreen Warning
the installer or `PFRSentinel.exe`, Windows may show a security warning:

```
Windows protected your PC
Microsoft Defender SmartScreen prevented an unrecognized app from starting.
```

**This is normal for unsigned software.** PFR Sentinel
**This is normal for unsigned software.** ASIOverlayWatchDog is open-source and safe.

**To proceed:**
1. Click **"More info"** link
2. Click **"Run anyway"** button

The warning appears because the executable isn't code-signed (costs $200-500/year). See [docs/CODE_SIGNING.md](docs/CODE_SIGNING.md) for details.

---

## Quick Start Usage

### Step 1: Choose Your Capture Mode

**Option A: Directory Watch Mode**
1. Navigate to the **Capture** page
2. Select "Directory Watch" mode
3. Click "Browse" for "Watch Directory" and select a folder containing images
4. Configure sidecar file settings if needed (optional)
5. Click "Start Watching"

**Option B: ZWO Camera Mode**
1. Connect your ZWO ASI camera via USB
2. Navigate to the **Capture** page
3. Select "ZWO Camera Capture" mode
4. Click "Detect Cameras" - your camera should appear in the dropdown
5. Adjust exposure/gain/white balance settings as needed
6. Enable "Auto Exposure" for automatic brightness calibration
7. Click "Start Capture"
s (Optional)

By default, images are saved to files. Multiple output modes can be enabled simultaneously:

1. Navigate to the **Output** page
2. Configure your preferred outputs:
   - **File Output**: Set output directory, format (PNG/JPEG), and filename pattern
   - **Web Server**: Enable HTTP server, set host/port, copy URLs for `/latest` and `/status` endpoints
   - **Discord**: Configure webhook URL, enable periodic posting with interval, weather location
   - **RTSP Stream**: Video stream at rtsp://127.0.0.1:8554/stream (requires ffmpeg)
3. Click "Apply Settings" to save changes
4. Use "Start/Stop" buttons to control each output service
5. Status indicators show green when services are activeSP"
5. Use "Copy URL" button to copy the server address

###Navigate to the **Overlays** page
2. Add text overlays using the "Add Text Overlay" button
3. Select an overlay from the list on the left
4. Edit text, position, font size, and color in the editor panel
5. Use tokens like `{CAMERA}`, `{EXPOSURE}`, `{GAIN}`, `{WEATHER}`, `{WEATHER_ICON}` to show metadata
6. Enable/disable overlays with the checkbox
7. See live preview on the right side (updates automatically)
8. Changes save automatically to config, `{EXPOSURE}`, `{GAIN}` to show metadata
5. See live preview on the right side
6. CMonitoring Page**: Dedicated page with real-time preview (200x200), RGB histogram, and last 10 log entries
- **Status Bar**: Visual indicators at top show current operation state (waiting, capturing, calibrating, processing, sending)
- **Logs Page**: Full log viewer with search, filter, save, and open log folder options
- **System Tray**: Minimize to tray with right-click menu for quick status and controls

- **Header**: Check live preview, RGB histogram, and recent logs
- **Preview Tab**: View latest processed image
- **Logs Tab**: Monitor all operations, save logs, or open log folder

---

## Advanced: Command Line Options

For automation, scheduled tasks, or headless operation:

```powershell
# Start with automatic camera capture
python main.py --auto-start

# Auto-start and stop after 1 hour (3600 seconds)
python main.py --auto-start --auto-stop 3600

# Auto-start and run indefinitely (stop manually or with SIGTERM)
python main.py --auto-start --auto-stop 0

# Headless mode - no GUI, uses saved config (great for servers)
python main.py --headless

# Headless with auto-stop after 1 hour
python main.py --headless --auto-stop 3600

# System tray mode - starts minimized to tray
python main.py --tray

# Tray mode with auto-start capture
python main.py --tray --auto-start

# View all options
python main.py --help
```

### Command Line Arguments

| Flag | Description |
|------|-------------|
| `--auto-start` | Automatically start camera capture on launch (uses saved camera settings) |
| `--auto-stop SECONDS` | Stop capture after N seconds (0 = run indefinitely) |
| `--headless` | Run without GUI - captures based on saved config. Ideal for servers, Docker, Raspberry Pi |
| `--tray` | Start minimized to Windows system tray with right-click menu controls |

### Headless Mode

Runs without any GUI - perfect for:
- Headless servers (Linux/Windows Server)
- Docker containers
- Raspberry Pi deployments
- Windows Task Scheduler automation

```powershell
# Run until Ctrl+C
python main.py --headless

# Run for 1 hour then exit
python main.py --headless --auto-stop 3600
```

Headless mode:
- Loads camera settings from saved `config.json`
- Starts web server automatically if configured as output mode
- Applies overlays and saves to output directory
- Handles graceful shutdown on Ctrl+C or SIGTERM
- Respects scheduled capture windows if configured

### System Tray Mode

Runs with full GUI but starts minimized to the Windows system tray:

```powershell
python main.py --tray
```

Tray mode features:
- **Right-click menu**: Show Window, Start/Stop Capture, Status, Exit
- **Double-click**: Restore the main window
- **X button**: Minimizes to tray instead of closing
- **Notifications**: Alerts when capture starts/stops

Ideal for 24/7 observatory computers where you want the app running but not cluttering the taskbar.

### Example: Windows Task Scheduler

```batch
@echo off
cd /d "C:\Program Files\PFRSentinel"
PFRSentinel.exe --headless --auto-stop 3600
```

This captures for 1 hour and exits automatically - perfect for scheduled tasks!

---

## Running from Source (Developers)

### Prerequisites

- Python 3.7 or higher
- Windows OS (for ZWO SDK support)
- Git (for cloning the repository)

### Setup

1. **Clone the repository**:
   ```powershell
   git clone <repository-url>
   cd ASIOverlayWatchDog
   ```

2. **Create virtual environment**:
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

3. **Install dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

4. **Add ZWO SDK** (for camera mode):
   - Download `ASICamera2.dll` from https://astronomy-imaging-camera.com/software-drivers
   - Place in project root directory

5. **Run the application**:
   ```powershell
   python main.py
   ```

   Or use the convenience script:
   ```powershell
   .\start.bat
   ```

### Project Structure

```
PFRSentinel/
├── gui/                    # Modern modular GUI
│   ├── main_window.py     # Application core + business logic
│   ├── header.py          # Status & live monitoring components
│   ├── capture_tab.py     # Capture controls UI
│   ├── settings_tab.py    # Configuration UI
│   ├── overlay_tab.py     # Overlay editor coordinator
│   ├── preview_tab.py     # Image preview with zoom
│   ├── logs_tab.py        # Log viewer with file access
│   ├── theme.py           # Centralized styling (CRITICAL)
│   ├── system_tray.py     # Windows system tray integration
│   └── overlays/          # Modular overlay system
├── services/               # Core processing modules
│   ├── config.py          # JSON persistence
│   ├── logger.py          # 7-day rotating file logs
│   ├── processor.py       # Image overlay engine
│   ├── watcher.py         # Directory monitoring
│   ├── zwo_camera.py      # ZWO ASI SDK wrapper
│   ├── headless_runner.py # Headless mode capture engine
│   ├── cleanup.py         # Disk space management
│   ├── web_output.py      # HTTP server
│   ├── rtsp_output.py     # RTSP streaming server
│   └── ...
├── tests/                  # Pytest test suite (94 tests)
├── docs/                   # Additional documentation
├── main.py                 # Application entry point
├── config.json             # Runtime state (auto-generated)
└── requirements.txt        # Python dependencies
```

---

## Building the Executable

To create a standalone `.exe` file for distribution:

### Prerequisites

- Running from source (see above)
- PyInstaller installed (included in `requirements.txt`)

### Build Steps

1. **Activate virtual environment**:
   ```powershell
   .\venv\Scripts\Activate.ps1
   ```

2. **Run PyInstaller**:
   ```powershell
   pyinstaller --clean ASIOverlayWatchDog.spec
   ```

   Or use the build script:
   ```powershell
   build_exe.bat
   ```

3. **Output location**:
   ```
   dist/ASIOverlayWatchDog/ASIOverlayWatchDog.exe
   ```

4. **Distribution**:
   - Copy the entire `dist/ASIOverlayWatchDog/` folder
   - Ensure `ASICamera2.dll` is included
   - Optionally include README and documentation

### Build Notes

- The `.spec` file is configured for a windowed application (no console popup)
- All dependencies (ttkbootstrap themes, GUI modules, services) are bundled
- Logs will still be created in `%APPDATA%\ASIOverlayWatchDog\logs` even when running the executable
- The executable size is approximately 50-80MB due to bundled Python runtime and libraries

---

## Getting Support & Sharing Logs

### Viewing Logs

1. Open the **Logs** tab
2. Monitor real-time log messages
3. Click "Open Log Folder" to access persistent log files
4. Logs are kept for 7 days and automatically rotate

### Saving Logs for Support

1. Go to the **Logs** tab
2. Click "💾 Save Logs..." button
3. This will consolidate all log files (up to 7 days) into a single `.txt` file
4. Save to your Desktop or Downloads folder
5. Attach this file when requesting support

### Log File Locations

- **Source mode**: `<project-root>/logs/watchdog.log`
- **Executable mode**: `%APPDATA%\ASIOverlayWatchDog\logs\watchdog.log`
- **Rotation**: Daily at midnight, keeps 7 days of history

### Common Issues

**"No cameras detected"**:
- Verify camera is connected via USB
- Check `ASICamera2.dll` is in the correct location
- Try "Detect Cameras" button again
- Check Logs tab for SDK errors

**"RTSP button disabled"**:
- ffmpeg is not installed or not in PATH
- See [ffmpeg installation](#ffmpeg-installation) below
- Verify with `ffmpeg -version` in Command Prompt

**"Images not processing"**:
- Check output directory has write permissions
- Verify sufficient disk space
- Review Logs tab for processing errors
- Ensure overlay settings are valid

**"Auto-start not working"**:
- Ensure a camera was previously selected and saved
- Check the 3-second initialization delay is sufficient
- Review logs for camera detection failures
- Try manual start first to save camera selection

### ffmpeg Installation

If you want to use RTSP streaming mode:

1. Download ffmpeg from https://www.gyan.dev/ffmpeg/builds/ (get the "release build")
2. Extract the zip file to a folder (e.g., `C:\ffmpeg`)
3. Add the `bin` folder to your PATH:
   - Right-click "This PC" → Properties → Advanced System Settings
   - Click "Environment Variables"
   - Under "System Variables", find "Path" and click Edit
   - Click "New" and add `C:\ffmpeg\bin` (or your extraction path)
   - Click OK on all dialogs
4. Restart Command Prompt and verify: `ffmpeg -version`
5. Restart ASIOverlayWatchDog - the RTSP button will now be enabled

---

## License & Credits

### License

This project is licensed under the [MIT License](LICENSE) - see the LICENSE file for details.

### Author

**Paul Fox-Reeks**
- Developer and maintainer of ASIOverlayWatchDog

### Credits

This application uses the following open-source libraries:

- **Python 3.7+**: Core programming language
- **ttkbootstrap**: Modern themed UI framework (https://github.com/israel-dryer/ttkbootstrap)
- **Pillow (PIL)**: Image processing library (https://python-pillow.org/)
- **watchdog**: File system monitoring (https://github.com/gorakhargosh/watchdog)
- **zwoasi**: ZWO ASI camera Python wrapper (https://github.com/python-zwoasi/python-zwoasi)
- **OpenCV (cv2)**: Bayer debayering and image operations (https://opencv.org/)
- **NumPy**: Numerical operations (https://numpy.org/)
- **ffmpeg**: Video encoding for RTSP streaming (https://ffmpeg.org/) - optional

### Special Thanks

- ZWO Astronomy Imaging for the ASI SDK
- The Python astrophotography community
- Contributors and testers

### Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly (both source and executable builds)
5. Submit a pull request with detailed description

### Reporting Issues

Please report bugs or request features via the issue tracker. When reporting bugs, include:
- Your Windows version
- Camera model (if applicable)
- Complete log file (from "Save Logs" button)
- Steps to reproduce the issue
- Screenshots if relevant

---

## Additional Documentation

For more detailed information, see the `docs/` folder:
- [Full Documentation](docs/README.md) - Complete feature reference
- [Quick Start Guide](docs/QUICKSTART.md) - Fast setup walkthrough
- [ZWO Camera Setup](docs/ZWO_SETUP_GUIDE.md) - Camera configuration details
- [Output Modes Guide](docs/OUTPUT_MODES.md) - Web server and RTSP streaming setup
- [GUI Architecture](gui/README.md) - Developer reference for modular UI

---

**Ready to get started? Download the executable or clone from source and launch your first capture!**

