"""
Services package for PFR Sentinel
Contains core processing and hardware integration modules
"""
from .config import Config
from .logger import app_logger

__all__ = [
    'Config',
    'app_logger',
    'process_image',
    'add_overlays',
    'FileWatcher',
    'ZWOCamera',
    'run_cleanup'
]


def __getattr__(name):
    """Lazy-load heavier service exports only when requested."""
    if name in ('process_image', 'add_overlays'):
        from .processor import process_image, add_overlays
        return {'process_image': process_image, 'add_overlays': add_overlays}[name]
    if name == 'FileWatcher':
        from .watcher import FileWatcher
        return FileWatcher
    if name == 'ZWOCamera':
        from .camera import ZWOCamera
        return ZWOCamera
    if name == 'run_cleanup':
        from .cleanup import run_cleanup
        return run_cleanup
    raise AttributeError(name)
