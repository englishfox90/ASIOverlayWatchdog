"""
File system watcher using watchdog
"""
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from .processor import process_image
from .cleanup import run_cleanup
from .logger import app_logger


class ImageFileHandler(FileSystemEventHandler):
    """Handler for image file events"""
    
    def __init__(self, config, on_image_processed=None):
        super().__init__()  # Initialize parent class
        self.config = config
        self.on_image_processed = on_image_processed
        self.processing = set()  # Track files being processed
        self.lock = threading.Lock()
        # Thread pool for concurrent file processing (REL-002 fix)
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="file_processor")
    
    def update_status(self, message):
        """Update status via callback"""
        app_logger.info(message)
    
    def wait_for_file_stable(self, filepath, timeout=10, check_interval=0.5):
        """
        Wait until file size is stable (file finished writing).
        Returns True if stable, False if timeout.
        """
        if not os.path.exists(filepath):
            return False
        
        last_size = -1
        stable_checks = 0
        elapsed = 0
        
        while elapsed < timeout:
            try:
                current_size = os.path.getsize(filepath)
                
                if current_size == last_size:
                    stable_checks += 1
                    if stable_checks >= 2:  # Stable for 2 checks
                        return True
                else:
                    stable_checks = 0
                    last_size = current_size
                
                time.sleep(check_interval)
                elapsed += check_interval
            
            except Exception as e:
                print(f"Error checking file stability: {e}")
                return False
        
        return False
    
    def process_file(self, filepath):
        """Process a single image file"""
        with self.lock:
            if filepath in self.processing:
                return  # Already processing
            self.processing.add(filepath)
        
        try:
            filename = os.path.basename(filepath)
            self.update_status(f"Detected: {filename}")
            
            # Wait for file to be fully written
            self.update_status(f"Waiting for {filename} to stabilize...")
            if not self.wait_for_file_stable(filepath):
                self.update_status(f"Timeout waiting for {filename}")
                return
            
            # Process the image
            self.update_status(f"Processing: {filename}")
            success, output_path, error, processed_img = process_image(filepath, self.config)
            
            if success:
                self.update_status(f"✓ Saved: {os.path.basename(output_path)}")
                
                # Notify callback with both path and image
                if self.on_image_processed:
                    self.on_image_processed(output_path, processed_img)
                
                # Run cleanup if enabled
                if self.config.get('cleanup_enabled', False):
                    cleanup_success, cleanup_msg = run_cleanup(self.config)
                    if cleanup_success:
                        self.update_status(f"Cleanup: {cleanup_msg}")
                    else:
                        self.update_status(f"Cleanup error: {cleanup_msg}")
            else:
                self.update_status(f"✗ Error processing {filename}: {error}")
        
        except Exception as e:
            self.update_status(f"✗ Exception processing {filepath}: {e}")
        
        finally:
            with self.lock:
                self.processing.discard(filepath)
    
    def on_created(self, event):
        """Called when a file is created"""
        if event.is_directory:
            return
        
        filepath = event.src_path
        
        # Check if it's an image file (PNG for now)
        if filepath.lower().endswith('.png'):
            # Submit to thread pool instead of spawning new thread (limits concurrent processing)
            self.executor.submit(self.process_file, filepath)
    
    def on_modified(self, event):
        """Called when a file is modified - we'll also catch files here"""
        # Some systems trigger modified instead of created
        if event.is_directory:
            return
        
        filepath = event.src_path
        
        # Only process if it's a new file we haven't seen
        if filepath.lower().endswith('.png'):
            with self.lock:
                if filepath not in self.processing:
                    # Submit to thread pool instead of spawning new thread
                    self.executor.submit(self.process_file, filepath)


    def shutdown(self):
        """Cleanup thread pool (called when stopping watcher)"""
        try:
            if hasattr(self, 'executor') and self.executor:
                # Use wait=True to allow current tasks to complete gracefully
                self.executor.shutdown(wait=True)
                app_logger.debug("File processing thread pool shut down")
        except Exception as e:
            app_logger.debug(f"Error shutting down thread pool: {e}")


class FileWatcher:
    """Main file watcher class"""
    
    def __init__(self, config, on_image_processed=None):
        self.config = config
        self.on_image_processed = on_image_processed
        self.observer = None
        self.handler = None
    
    def start(self):
        """Start watching the directory"""
        watch_dir = self.config.get('watch_directory', '')
        
        if not watch_dir or not os.path.exists(watch_dir):
            raise ValueError("Invalid watch directory")
        
        recursive = self.config.get('watch_recursive', True)
        
        # Create handler
        self.handler = ImageFileHandler(self.config, self.on_image_processed)
        
        # Create observer
        self.observer = Observer()
        self.observer.schedule(self.handler, watch_dir, recursive=recursive)
        self.observer.start()
        
        mode = "recursively" if recursive else "non-recursively"
        app_logger.info(f"Watching {watch_dir} ({mode})")
    
    def stop(self):
        """Stop watching"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None
        
        app_logger.info("Stopped watching")
    
    def is_running(self):
        """Check if watcher is running"""
        return self.observer is not None and self.observer.is_alive()
