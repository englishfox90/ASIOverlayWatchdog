"""
Application Configuration - Central place for app identity
Change these values when renaming the application
"""
import os

# Application Identity
APP_NAME = "PFRSentinel"  # Internal name (no spaces, used for paths)
APP_DISPLAY_NAME = "PFR Sentinel"  # Display name (shown to users)
APP_SUBTITLE = "Live Camera Monitoring & Overlay System for Observatories"
APP_DESCRIPTION = "Astrophotography image overlay and monitoring application"
APP_AUTHOR = "Paul Fox-Reeks"
APP_URL = "https://github.com/englishfox90/PFRSentinel"

# Directory names (used for AppData paths)
APP_DATA_FOLDER = "PFRSentinel"  # %LOCALAPPDATA%\PFRSentinel

# File names
MAIN_CONFIG_FILE = "config.json"
LOG_FILE = "sentinel.log"

# Default paths
DEFAULT_OUTPUT_SUBFOLDER = "Images"

# SDK/Driver info (keep ASI reference - it's the actual SDK name)
ZWO_SDK_DLL = "ASICamera2.dll"

# Build identifiers - New GUID for renamed app
INNO_SETUP_APP_ID = "{{7F8E9A0B-1C2D-3E4F-5A6B-7C8D9E0F1A2B}"


def get_window_title(version: str = None) -> str:
    """Get formatted window title with optional version"""
    if version:
        return f"{APP_DISPLAY_NAME} v{version}"
    return APP_DISPLAY_NAME


def get_user_agent() -> str:
    """Get user agent string for HTTP requests"""
    from version import __version__
    return f"{APP_NAME}/{__version__}"


def get_app_data_dir() -> str:
    """Canonical %LOCALAPPDATA%\\PFRSentinel directory (created if missing)."""
    base = os.path.join(os.getenv('LOCALAPPDATA', ''), APP_DATA_FOLDER)
    os.makedirs(base, exist_ok=True)
    return base


def get_calibration_path() -> str:
    """Canonical path to the all-sky calibration JSON.

    Per .claude/rules/allsky.md this lives in %LOCALAPPDATA%\\PFRSentinel
    (NOT %APPDATA% where config.json lives) — user-generated, never bundled.
    Single source of truth so the background service, the manual-cal
    controller, and dev tools never diverge.
    """
    return os.path.join(get_app_data_dir(), 'allsky_calibration.json')


def get_calibration_backup_path() -> str:
    """Where the previous calibration goes before an automatic save
    overwrites it — the one-step undo for a bad model replacement."""
    return os.path.join(get_app_data_dir(), 'allsky_calibration.previous.json')
