"""
Thread-safe logging module for GUI with 7-day rotating file logs
"""
import queue
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path


class AppLogger:
    """Thread-safe logger with GUI queue and 7-day rotating file logs"""
    
    def __init__(self):
        self.message_queue = queue.Queue()
        self.log_callbacks = []
        self.error_callback = None  # Callback for Discord error alerts
        
        # Set up file logging
        self.log_dir = self._get_log_directory()
        self._setup_file_logging()
        self._cleanup_old_logs()
    
    def _get_log_directory(self):
        """Get the log directory path (APPDATA or fallback)"""
        # Try %APPDATA%\ASIOverlayWatchDog\logs first
        appdata = os.getenv('APPDATA')
        if appdata:
            log_dir = Path(appdata) / 'ASIOverlayWatchDog' / 'logs'
        else:
            # Fallback: ./logs relative to executable or script
            if getattr(sys, 'frozen', False):
                # Running as PyInstaller executable
                base_dir = Path(sys.executable).parent
            else:
                # Running from source
                base_dir = Path(__file__).parent.parent
            log_dir = base_dir / 'logs'
        
        # Create directory if it doesn't exist
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir
    
    def _setup_file_logging(self):
        """Set up rotating file handler for 7-day logs"""
        # Create logger (use root logger to catch all messages)
        self.file_logger = logging.getLogger('ASIOverlayWatchDog')
        self.file_logger.setLevel(logging.DEBUG)
        
        # Prevent propagation to root logger to avoid duplicate messages
        # (main.py sets up root logger via logging_config.py)
        self.file_logger.propagate = False
        
        # Check if handlers already exist (prevent duplicates on re-import)
        # Remove any existing watchdog.log handlers to avoid conflicts
        for handler in list(self.file_logger.handlers):
            if hasattr(handler, 'baseFilename') and 'watchdog.log' in str(handler.baseFilename):
                self.file_logger.removeHandler(handler)
                handler.close()
        
        # If there are still other handlers, just use the first one
        if self.file_logger.handlers:
            self.file_handler = self.file_logger.handlers[0]
            return
        
        # Daily rotating file handler (keeps last 7 days)
        log_file = self.log_dir / 'watchdog.log'
        handler = logging.handlers.TimedRotatingFileHandler(
            log_file,
            when='midnight',
            interval=1,
            backupCount=7,  # Keep 7 days
            encoding='utf-8'
        )
        
        # Format: 2025-01-15 14:32:15 - INFO - Message
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        
        self.file_logger.addHandler(handler)
        self.file_handler = handler
    
    def _cleanup_old_logs(self):
        """Delete log files older than 7 days"""
        if not self.log_dir.exists():
            return
        
        cutoff = datetime.now() - timedelta(days=7)
        for log_file in self.log_dir.glob('watchdog.log*'):
            try:
                mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                if mtime < cutoff:
                    log_file.unlink()
                    print(f"Deleted old log file: {log_file.name}")
            except Exception as e:
                print(f"Error cleaning up old log: {e}")
    
    def get_log_dir(self):
        """Get the log directory path for UI display"""
        return str(self.log_dir)
    
    def set_error_callback(self, callback):
        """Set callback for error messages (used for Discord alerts)"""
        self.error_callback = callback
    
    def log(self, message, level="INFO"):
        """Add a log message to queue AND file"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        formatted_message = f"[{timestamp}] {level}: {message}"
        
        # Queue for GUI
        self.message_queue.put(formatted_message)
        
        # Console
        print(formatted_message)
        
        # File logging
        log_level = getattr(logging, level, logging.INFO)
        self.file_logger.log(log_level, message)
        
        # Call error callback if this is an error
        if level == "ERROR" and self.error_callback:
            try:
                self.error_callback(message)
            except Exception as e:
                print(f"Error in Discord callback: {e}")

    
    def info(self, message):
        """Log info message"""
        self.log(message, "INFO")
    
    def error(self, message):
        """Log error message"""
        self.log(message, "ERROR")
    
    def warning(self, message):
        """Log warning message"""
        self.log(message, "WARN")
    
    def debug(self, message):
        """Log debug message"""
        self.log(message, "DEBUG")
    
    def get_messages(self):
        """Get all queued messages (non-blocking)"""
        messages = []
        while not self.message_queue.empty():
            try:
                messages.append(self.message_queue.get_nowait())
            except queue.Empty:
                break
        return messages


# Singleton pattern to ensure only one logger instance
_logger_instance = None

def get_app_logger():
    """Get or create the singleton logger instance"""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = AppLogger()
    return _logger_instance

# Global logger instance (singleton)
app_logger = get_app_logger()
