"""
Watch Controller for Qt UI
Adapter between PySide6 UI and existing FileWatcher service
"""
from PySide6.QtCore import QObject, Signal, QThread

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.logger import app_logger
from services.watcher import FileWatcher


class WatchControllerQt(QObject):
    """
    Qt-compatible watch controller
    Wraps existing FileWatcher service for use with PySide6 UI
    """
    
    started = Signal()
    stopped = Signal()
    file_detected = Signal(str)  # File path
    error = Signal(str)
    
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.config = main_window.config
        
        self.watcher = None
        self.is_watching = False
    
    def start_watching(self, directory: str):
        """Start watching directory for new files"""
        if self.is_watching:
            return
        
        if not os.path.isdir(directory):
            self.error.emit(f"Invalid directory: {directory}")
            return
        
        try:
            recursive = self.config.get('watch_recursive', True)
            
            self.watcher = FileWatcher(
                watch_directory=directory,
                recursive=recursive,
                on_new_file_callback=self._on_new_file
            )
            
            self.watcher.start()
            self.is_watching = True
            self.started.emit()
            
            app_logger.info(f"Started watching: {directory}")
            
        except Exception as e:
            self.error.emit(str(e))
            app_logger.error(f"Failed to start watching: {e}")
    
    def stop_watching(self):
        """Stop watching"""
        if not self.is_watching:
            return
        
        try:
            if self.watcher:
                self.watcher.stop()
                self.watcher = None
            
            self.is_watching = False
            self.stopped.emit()
            
            app_logger.info("Stopped watching")
            
        except Exception as e:
            app_logger.error(f"Error stopping watcher: {e}")
    
    def _on_new_file(self, file_path: str):
        """Handle new file detected by watcher"""
        self.file_detected.emit(file_path)
        
        # Process file
        if self.main_window:
            # File processing will be handled by main window
            pass
