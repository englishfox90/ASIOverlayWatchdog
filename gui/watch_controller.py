"""
Directory watch controller for monitoring folders and processing images.
Handles FileWatcher lifecycle, callbacks, and directory browsing.
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox
from services.watcher import FileWatcher
from services.logger import app_logger


class WatchController:
    """Manages directory watch operations"""
    
    def __init__(self, app):
        """
        Initialize watch controller.
        
        Args:
            app: Main application instance (provides access to config, overlay_manager, vars, etc.)
        """
        self.app = app
        self.watcher = None
        
    # ===== DIRECTORY BROWSING =====
    
    def browse_watch_dir(self):
        """Browse for watch directory"""
        dir_path = filedialog.askdirectory(title="Select directory to watch")
        if dir_path:
            self.app.watch_dir_var.set(dir_path)
    
    def browse_output_dir(self):
        """Browse for output directory"""
        dir_path = filedialog.askdirectory(title="Select output directory")
        if dir_path:
            self.app.output_dir_var.set(dir_path)
    
    # ===== DIRECTORY WATCHING =====
    
    def start_watching(self):
        """Start directory watching"""
        watch_dir = self.app.watch_dir_var.get()
        
        if not watch_dir or not os.path.exists(watch_dir):
            messagebox.showerror("Error", "Please select a valid directory to watch")
            return
        
        try:
            # Ensure output servers are started if configured
            self.app.output_manager.ensure_output_mode_started()
            
            overlays = self.app.overlay_manager.get_overlays_config()
            output_dir = self.app.output_dir_var.get()
            recursive = self.app.watch_recursive_var.get()
            
            self.watcher = FileWatcher(
                watch_directory=watch_dir,
                output_directory=output_dir,
                overlays=overlays,
                recursive=recursive,
                callback=self.on_image_processed
            )
            
            self.watcher.start()
            
            # Update UI
            self.app.start_watch_button.config(state='disabled')
            self.app.stop_watch_button.config(state='normal')
            
            # Schedule Discord periodic updates with initial message
            self.app.output_manager.schedule_discord_periodic(send_initial=True)
            
            app_logger.info(f"Started watching: {watch_dir}")
            
        except Exception as e:
            app_logger.error(f"Failed to start watching: {e}")
            messagebox.showerror("Error", f"Failed to start watching:\n{str(e)}")
    
    def stop_watching(self):
        """Stop directory watching"""
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
            
            self.app.start_watch_button.config(state='normal')
            self.app.stop_watch_button.config(state='disabled')
            app_logger.info("Stopped watching")
    
    def on_image_processed(self, output_path, processed_img=None):
        """
        Callback when watcher processes an image.
        
        Args:
            output_path: Path to saved output image
            processed_img: PIL Image object (optional)
        """
        self.app.image_count += 1
        self.app.root.after(0, lambda: self.app.image_count_var.set(str(self.app.image_count)))
        
        # Push to output servers if active
        if processed_img:
            self.app.output_manager.push_to_output_servers(output_path, processed_img)
