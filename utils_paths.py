"""
Path utilities for PyInstaller resource handling
Resolves paths correctly whether running from source or as bundled EXE
"""
import os
import sys

# Import app configuration for centralized naming
try:
    from app_config import APP_DATA_FOLDER
except ImportError:
    APP_DATA_FOLDER = "PFRSentinel"  # Fallback


def resource_path(relative_path):
    """
    Get absolute path to resource, works for dev and for PyInstaller
    
    Args:
        relative_path: Path relative to application root
        
    Returns:
        Absolute path to resource
    """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        # Running from source - use script directory
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    return os.path.join(base_path, relative_path)


def get_app_data_dir():
    r"""
    Get application data directory (for logs, user config, etc.)
    
    Returns:
        Path to %LOCALAPPDATA%\{APP_DATA_FOLDER} (Windows)
    """
    if sys.platform == 'win32':
        # Use LOCALAPPDATA on Windows
        local_app_data = os.environ.get('LOCALAPPDATA')
        if not local_app_data:
            # Fallback to APPDATA if LOCALAPPDATA not available
            local_app_data = os.environ.get('APPDATA', os.path.expanduser('~'))
        app_dir = os.path.join(local_app_data, APP_DATA_FOLDER)
    else:
        # Fallback for other platforms (though this is Windows-focused)
        app_dir = os.path.join(os.path.expanduser('~'), f'.{APP_DATA_FOLDER}')
    
    # Create directory if it doesn't exist
    os.makedirs(app_dir, exist_ok=True)
    
    return app_dir


def get_log_dir():
    r"""
    Get log directory path
    
    Returns:
        Path to %LOCALAPPDATA%\{APP_DATA_FOLDER}\Logs
    """
    log_dir = os.path.join(get_app_data_dir(), 'Logs')
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def get_exe_dir():
    """
    Get the directory where the EXE is installed/running from.
    
    Returns:
        Absolute path to the directory containing the executable (or script in dev mode)
    """
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        return os.path.dirname(sys.executable)
    else:
        # Running from source
        return os.path.dirname(os.path.abspath(__file__))
