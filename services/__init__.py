"""
Services package for AllSky Overlay Watchdog
Contains core processing and hardware integration modules
"""
from .config import Config
from .logger import app_logger
from .processor import process_image, add_overlays
from .watcher import FileWatcher
from .zwo_camera import ZWOCamera
from .cleanup import run_cleanup

__all__ = [
    'Config',
    'app_logger',
    'process_image',
    'add_overlays',
    'FileWatcher',
    'ZWOCamera',
    'run_cleanup'
]
