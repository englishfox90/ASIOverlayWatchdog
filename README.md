# ASIOverlayWatchDog - AllSky Camera Image Processor

**Professional astrophotography tool for automated image processing with ZWO ASI camera support**

A modern, production-ready application that either watches directories for new images or captures directly from ZWO ASI cameras, adding customizable metadata overlays and serving output through multiple channels (file, web server, or RTSP streaming).

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

**ASIOverlayWatchDog** is designed for 24/7 unattended astrophotography operations. It provides two distinct capture modes:

1. **Directory Watch Mode**: Monitors a folder for new images (from any camera/software), reads sidecar metadata files, and adds overlays
2. **ZWO Camera Mode**: Captures directly from ZWO ASI cameras with auto-exposure, debayering, and real-time processing

The application features multiple output modes:
- **File Mode**: Save processed images to disk (traditional workflow)
- **Webserver Mode**: Serve latest image via HTTP (http://127.0.0.1:8080/latest)
- **RTSP Streaming Mode**: Live H.264 stream for video applications (rtsp://127.0.0.1:8554/stream)

Built with a modern dark-themed GUI using ttkbootstrap, ASIOverlayWatchDog includes live monitoring (preview, RGB histogram, recent logs), 7-day rotating file logs for troubleshooting, and command-line automation support for scheduled tasks.

---

## Key Features

### Capture & Processing
- ✅ **Dual Capture Modes**: Directory monitoring or direct ZWO ASI camera capture
- ✅ **Auto-Exposure**: Intelligent brightness adjustment targeting optimal exposure levels
- ✅ **Debayering**: Automatic Bayer pattern conversion (BGGR) for ZWO color cameras
- ✅ **Customizable Overlays**: Text overlays with metadata tokens (camera name, exposure, gain, temperature, resolution, filename, session, datetime)
- ✅ **Resize Processing**: Optional image resizing before overlay processing
- ✅ **Output Formats**: PNG (lossless) or JPEG (adjustable quality)

### Output Modes
- ✅ **File Output**: Traditional save-to-disk workflow
- ✅ **Web Server**: HTTP server with `/latest` (image) and `/status` (JSON) endpoints
- ✅ **RTSP Streaming**: Live H.264 video stream via ffmpeg (requires ffmpeg installation)
- ✅ **Smart Detection**: Automatic ffmpeg availability check with helpful UI feedback

### User Interface
- ✅ **Modern Dark Theme**: Professional ttkbootstrap-based interface
- ✅ **Live Monitoring Header**: Mini preview, RGB histogram, and recent log messages
- ✅ **Tabbed Navigation**: Capture, Settings, Overlays, Preview, Logs
- ✅ **Real-time Preview**: Auto-fit zoom with manual controls
- ✅ **Status Indicators**: Visual feedback for all operations

### Automation & Reliability
- ✅ **Command Line Support**: `--auto-start`, `--auto-stop`, `--headless` flags for scripting
- ✅ **Automatic Camera Detection**: Retry logic ensures reliable unattended startup
- ✅ **7-Day Rotating Logs**: File-based logging in `%APPDATA%\ASIOverlayWatchDog\logs`
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

## Installation for End Users

### Download the Executable (Recommended)

**→ [Download Latest Release](releases/) ← Click here for portable ZIP**

1. **Download**: Get `ASIOverlayWatchDog-v2.0.0-Portable.zip` from the `releases/` folder
2. **Extract**: Unzip to a permanent location (e.g., `C:\Program Files\ASIOverlayWatchDog\` or `C:\ASIWatchdog\`)
3. **Run**: Double-click `ASIOverlayWatchDog.exe` - **That's it!**

**✅ Completely Self-Contained - No Installation Required:**
- ✅ Python runtime embedded (no Python installation needed)
- ✅ All dependencies included (Pillow, OpenCV, NumPy, ttkbootstrap, etc.)
- ✅ ZWO ASI SDK bundled (`ASICamera2.dll` included)
- ✅ Works on any Windows 7+ machine (64-bit recommended)
- ✅ No admin rights required (unless installing to Program Files)

**Optional Dependencies:**
- **ffmpeg** - Only needed for RTSP streaming mode (see [ffmpeg installation](#ffmpeg-installation) below)
  - File and Webserver modes work without ffmpeg
  - RTSP button will be disabled if ffmpeg not found

### First Run Setup

On first launch, the application will:
- Create a default `config.json` in the same folder
- Create a log directory at `%APPDATA%\ASIOverlayWatchDog\logs`
- Show the Capture tab with default settings

**No installation or Python required** - it's a standalone executable!

---

## Quick Start Usage

### Step 1: Choose Your Capture Mode

**Option A: Directory Watch Mode**
1. Open the **Capture** tab
2. Select "Directory Watch" mode
3. Click "Browse" for "Watch Directory" and select a folder containing images
4. Click "Browse" for "Output Directory" and select where processed images should be saved
5. Click "Start Watching"

**Option B: ZWO Camera Mode**
1. Connect your ZWO ASI camera via USB
2. Open the **Capture** tab
3. Select "ZWO Camera Capture" mode
4. Click "Detect Cameras" - your camera should appear in the dropdown
5. Adjust exposure/gain settings as needed
6. Click "Start Capture"

### Step 2: Configure Output Mode (Optional)

By default, images are saved to files. To use web server or RTSP streaming:

1. Open the **Settings** tab
2. Scroll to "Output Mode" card
3. Select your preferred mode:
   - **File**: Save to disk (default)
   - **Webserver**: Serve via HTTP at http://127.0.0.1:8080/latest
   - **RTSP Stream**: Video stream at rtsp://127.0.0.1:8554/stream (requires ffmpeg)
4. Click "Apply" and "Start Webserver" or "Start RTSP"
5. Use "Copy URL" button to copy the server address

### Step 3: Customize Overlays (Optional)

1. Open the **Overlay** tab
2. Add overlays using the "+" button
3. Edit text, position, font, and color
4. Use tokens like `{CAMERA}`, `{EXPOSURE}`, `{GAIN}` to show metadata
5. See live preview on the right side
6. Changes save automatically

### Step 4: Monitor Operation

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

# Experimental headless mode (no GUI, requires auto-start)
python main.py --auto-start --headless

# View all options
python main.py --help
```

### Command Line Behavior

- `--auto-start`: Waits 3 seconds for camera initialization, then automatically switches to camera mode and starts capture using the previously saved camera selection
- `--auto-stop SECONDS`: Stops capture after the specified duration (0 = run indefinitely)
- `--headless`: Experimental mode that runs without GUI (must use with `--auto-start`)

**Example: Scheduled Task**
```batch
@echo off
cd /d "C:\Program Files\ASIOverlayWatchDog"
ASIOverlayWatchDog.exe --auto-start --auto-stop 3600
```

This captures for 1 hour and exits automatically - perfect for Windows Task Scheduler!

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
ASIOverlayWatchDog/
├── gui/                    # Modern modular GUI (9 modules)
│   ├── main_window.py     # Application core + business logic
│   ├── header.py          # Status & live monitoring components
│   ├── capture_tab.py     # Capture controls UI
│   ├── settings_tab.py    # Configuration UI
│   ├── overlay_tab.py     # Overlay editor coordinator
│   ├── preview_tab.py     # Image preview with zoom
│   ├── logs_tab.py        # Log viewer with file access
│   ├── theme.py           # Centralized styling (CRITICAL)
│   └── overlays/          # Modular overlay system
├── services/               # Core processing modules (10 services)
│   ├── config.py          # JSON persistence
│   ├── logger.py          # 7-day rotating file logs
│   ├── processor.py       # Image overlay engine
│   ├── watcher.py         # Directory monitoring
│   ├── zwo_camera.py      # ZWO ASI SDK wrapper
│   ├── cleanup.py         # Disk space management
│   ├── web_output.py      # HTTP server
│   ├── rtsp_output.py     # RTSP streaming server
│   └── ...
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

