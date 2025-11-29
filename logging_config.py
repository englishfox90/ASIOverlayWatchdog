r"""
Logging configuration with 7-day rolling file retention
Writes to %LOCALAPPDATA%\ASIOverlayWatchDog\Logs with automatic cleanup
"""
import os
import sys
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timedelta
from utils_paths import get_log_dir


def cleanup_old_logs(log_dir, days_to_keep=7):
    """
    Remove log files older than specified days
    
    Args:
        log_dir: Directory containing log files
        days_to_keep: Number of days to retain (default: 7)
    """
    if not os.path.exists(log_dir):
        return
    
    cutoff_date = datetime.now() - timedelta(days=days_to_keep)
    
    try:
        for filename in os.listdir(log_dir):
            file_path = os.path.join(log_dir, filename)
            
            # Only process files, not directories
            if not os.path.isfile(file_path):
                continue
            
            # Check file modification time
            file_mtime = datetime.fromtimestamp(os.path.getmtime(file_path))
            
            if file_mtime < cutoff_date:
                try:
                    os.remove(file_path)
                    print(f"Removed old log file: {filename}")
                except Exception as e:
                    print(f"Failed to remove {filename}: {e}")
    
    except Exception as e:
        print(f"Error during log cleanup: {e}")


def setup_logging():
    r"""
    Configure application logging with file rotation and cleanup
    
    Sets up:
    - Console logging (INFO level)
    - File logging with daily rotation (DEBUG level)
    - Automatic cleanup of logs older than 7 days
    
    Log location: %LOCALAPPDATA%\ASIOverlayWatchDog\Logs\watchdog.log
    """
    # Get log directory
    log_dir = get_log_dir()
    log_file = os.path.join(log_dir, 'watchdog.log')
    
    # Clean up old logs first
    cleanup_old_logs(log_dir, days_to_keep=7)
    
    # Create root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # Capture everything, handlers filter
    
    # Remove any existing handlers (in case setup_logging is called multiple times)
    logger.handlers.clear()
    
    # Console handler - INFO and above
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        '[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # File handler - Daily rotation, keep 7 days
    try:
        file_handler = TimedRotatingFileHandler(
            log_file,
            when='midnight',      # Rotate at midnight
            interval=1,           # Every 1 day
            backupCount=7,        # Keep 7 days of logs
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)  # Log everything to file
        file_format = logging.Formatter(
            '[%(asctime)s] %(levelname)-8s [%(name)s:%(funcName)s:%(lineno)d] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
        
        # Log startup message
        logger.info(f"Logging initialized - Log file: {log_file}")
        logger.info(f"Log rotation: Daily, keeping 7 days")
        
    except Exception as e:
        # If file logging fails, at least we have console
        logger.error(f"Failed to initialize file logging: {e}")
        logger.warning("Continuing with console logging only")
    
    return logger


def get_logger(name=None):
    """
    Get a logger instance
    
    Args:
        name: Logger name (typically __name__), None for root logger
        
    Returns:
        Logger instance
    """
    return logging.getLogger(name)
