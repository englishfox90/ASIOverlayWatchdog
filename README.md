# PFR Sentinel

**Live Camera Monitoring & Overlay System for Observatories**

A modern astrophotography application with a Fluent Design UI (PySide6 + qfluentwidgets) that watches directories for new images or captures directly from ZWO ASI cameras, adding customizable metadata overlays with weather data and serving output through multiple channels.

**Current Version:** 3.6.8

---

## Key Features

### Capture Modes
- **Directory Watch Mode**: Monitor folders for new images from any camera/software
- **ZWO Camera Mode**: Direct capture from ZWO ASI cameras with auto-exposure and debayering

### Output Modes (can run simultaneously)
- **File Output**: Save processed images to disk
- **Web Server**: HTTP server with `/latest` (image) and `/status` (JSON) endpoints
- **Discord Integration**: Periodic image posts with weather data embeds

### Processing
- Auto-stretch (MAD-based histogram stretching)
- Customizable text overlays with metadata tokens
- Weather data integration (OpenWeatherMap)
- Resize and format options (PNG/JPEG)

### User Interface
- Modern Fluent Design UI (Windows 11 styling)
- Live monitoring panel with preview, RGB histogram, and mini-log
- System tray support with notifications
- Command-line automation support (`--headless`, `--auto-start`, `--tray`)

---

## Installation

### Windows Installer (Recommended)

Download `PFRSentinel_Setup.exe` from the `releases/` folder and run it.

**Self-contained** - includes Python runtime, all dependencies, and ZWO ASI SDK.

**Optional:**
- **ffmpeg** - Needed for timelapse recording
- **OpenWeatherMap API Key** - For weather data overlays

### Running from Source

```powershell
git clone <repository-url>
cd PFRSentinel
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

---

## Quick Start

1. **Choose Capture Mode** (Capture page):
   - **Directory Watch**: Select folder to monitor for new images
   - **ZWO Camera**: Click "Detect Cameras", configure exposure/gain

2. **Configure Outputs** (Output page):
   - Enable desired outputs (File, Web, Discord)
   - Configure settings for each

3. **Add Overlays** (Overlays page):
   - Add text overlays with tokens like `{CAMERA}`, `{EXPOSURE}`, `{WEATHER}`

4. **Monitor** (Monitoring page):
   - View live preview, histogram, and recent logs

---

## Command Line Options

```powershell
python main.py --auto-start              # Auto-start capture
python main.py --auto-stop 3600          # Stop after N seconds
python main.py --headless                # No GUI (server mode)
python main.py --tray                    # Start minimized to tray
```

---

## Project Structure

```
PFRSentinel/
├── ui/                        # PySide6 + qfluentwidgets UI
│   ├── main_window.py         # Main application window
│   ├── system_tray_qt.py      # System tray integration
│   ├── components/            # Reusable UI components (app_bar, cards, nav_rail)
│   ├── panels/                # Main pages
│   │   ├── capture_settings.py
│   │   ├── output_settings.py
│   │   ├── overlay_settings.py
│   │   ├── live_monitoring.py
│   │   └── logs_panel.py
│   ├── controllers/           # Business logic
│   │   ├── camera_controller.py
│   │   ├── watch_controller.py
│   │   └── image_processor.py
│   └── theme/                 # Fluent Design theming
├── services/                  # Core processing modules
│   ├── config.py              # JSON persistence (%APPDATA%\PFRSentinel)
│   ├── logger.py              # Thread-safe logging
│   ├── processor.py           # Image overlay engine
│   ├── watcher.py             # Directory monitoring
│   ├── zwo_camera.py          # ZWO ASI SDK wrapper
│   ├── discord_alerts.py      # Discord webhook client
│   ├── weather.py             # OpenWeatherMap integration
│   └── web_output.py          # HTTP server
├── main.py                    # Application entry point
├── app_config.py              # App identity configuration
└── version.py                 # Version info
```

---

## Configuration

Settings stored in `%APPDATA%\PFRSentinel\config.json`

Logs in `%APPDATA%\PFRSentinel\logs` (7-day rotation)

---

## Overlay Tokens

| Token | Description |
|-------|-------------|
| `{CAMERA}` | Camera name |
| `{EXPOSURE}` | Exposure time |
| `{GAIN}` | Gain value |
| `{TEMP}` | Camera/weather temperature |
| `{FILENAME}` | Original filename |
| `{DATETIME}` | Current date/time |
| `{WEATHER}` | Weather description |
| `{WEATHER_ICON}` | Weather icon emoji |

---

## Troubleshooting

- **No cameras detected**: Verify USB connection, check SDK path in Capture page
- **Weather shows N/A**: Configure API key and location in settings
- **Check logs**: Use Logs page or open `%APPDATA%\PFRSentinel\logs`

---

## Building

```powershell
.\build_sentinel.bat           # Build executable
.\build_sentinel_installer.bat # Build installer
```

---

## License

MIT License - See [LICENSE](LICENSE) for details.

**Author:** Paul Fox-Reeks

