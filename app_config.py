"""
Application Configuration - Central place for app identity
Change these values when renaming the application
"""

# Application Identity
APP_NAME = "ASIOverlayWatchDog"
APP_DISPLAY_NAME = "ASI Overlay WatchDog"
APP_DESCRIPTION = "Astrophotography image overlay and monitoring application"
APP_AUTHOR = "Paul Fox-Reeks"
APP_URL = "https://github.com/englishfox90/ASIOverlayWatchdog"

# Directory names (used for AppData paths)
APP_DATA_FOLDER = APP_NAME  # %LOCALAPPDATA%\{APP_DATA_FOLDER}

# File names
MAIN_CONFIG_FILE = "config.json"
LOG_FILE = "watchdog.log"

# Default paths
DEFAULT_OUTPUT_SUBFOLDER = "Images"

# SDK/Driver info
ZWO_SDK_DLL = "ASICamera2.dll"

# Build identifiers
INNO_SETUP_APP_ID = "{{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}"  # Generate new GUID if renaming


def get_window_title(version: str = None) -> str:
    """Get formatted window title with optional version"""
    if version:
        return f"{APP_DISPLAY_NAME} v{version}"
    return APP_DISPLAY_NAME


def get_user_agent() -> str:
    """Get user agent string for HTTP requests"""
    from version import __version__
    return f"{APP_NAME}/{__version__}"
