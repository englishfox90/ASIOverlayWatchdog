"""
Output Manager - Handles Web/RTSP/Discord output modes
Extracted from main_window.py to improve modularity
"""
import io
from tkinter import messagebox
from datetime import datetime

from services.logger import app_logger
from services.web_output import WebOutputServer
from services.rtsp_output import RTSPStreamServer
from services.discord_alerts import DiscordAlerts
from services.camera_utils import is_within_scheduled_window
from .theme import SPACING


class OutputManager:
    """Manages Web Server, RTSP, and Discord output modes"""
    
    def __init__(self, app):
        self.app = app
        self.web_server = None
        self.rtsp_server = None
        self.discord_alerts = None
        self.discord_periodic_job = None
        
        # Initialize Discord alerts
        self.initialize_discord()
    
    def initialize_discord(self):
        """Initialize Discord alerts with current config"""
        self.discord_alerts = DiscordAlerts(self.app.config.data)
    
    def on_output_mode_change(self):
        """Handle output mode change (wrapper for apply_output_mode)"""
        self.apply_output_mode()
    
    def apply_output_mode(self):
        """Start/stop output servers based on selected mode"""
        mode = self.app.output_mode_var.get()
        
        # Stop any running servers
        if self.web_server and self.web_server.running:
            self.web_server.stop()
            self.web_server = None
        
        if self.rtsp_server and self.rtsp_server.running:
            self.rtsp_server.stop()
            self.rtsp_server = None
        
        # Hide copy button by default
        self.app.output_mode_copy_btn.pack_forget()
        
        # Hide all mode-specific frames first
        self.app.file_frame.pack_forget()
        self.app.webserver_frame.pack_forget()
        self.app.rtsp_frame.pack_forget()
        
        # Show the appropriate frame for selected mode
        if mode == 'file':
            self.app.file_frame.pack(fill='x', pady=(0, SPACING['section_gap']))
            self.app.output_mode_status_var.set("Mode: File (Saving to output directory)")
        elif mode == 'webserver':
            self.app.webserver_frame.pack(fill='x', pady=(0, SPACING['section_gap']))
            self._start_web_server()
        elif mode == 'rtsp':
            self.app.rtsp_frame.pack(fill='x', pady=(0, SPACING['section_gap']))
            self._start_rtsp_server()
    
    def _start_web_server(self):
        """Start web server with current settings"""
        host = self.app.webserver_host_var.get()
        port = self.app.webserver_port_var.get()
        image_path = self.app.webserver_path_var.get()
        status_path = self.app.config.get('output', {}).get('webserver_status_path', '/status')
        
        self.web_server = WebOutputServer(host, port, image_path, status_path)
        if self.web_server.start():
            url = self.web_server.get_url()
            status_url = self.web_server.get_status_url()
            self.app.output_mode_status_var.set(f"✓ Web Server: {url}")
            self.app.output_mode_copy_btn.pack(side='right')  # Show copy button
            app_logger.info(f"Web server started: {url}")
            app_logger.info(f"Status endpoint: {status_url}")
        else:
            self.app.output_mode_status_var.set("❌ Failed to start web server (check logs)")
            self.web_server = None
    
    def _start_rtsp_server(self):
        """Start RTSP server with current settings"""
        host = self.app.rtsp_host_var.get()
        port = self.app.rtsp_port_var.get()
        stream_name = self.app.rtsp_stream_name_var.get()
        fps = self.app.rtsp_fps_var.get()
        
        self.rtsp_server = RTSPStreamServer(host, port, stream_name, fps)
        if self.rtsp_server.start():
            url = self.rtsp_server.get_url()
            self.app.output_mode_status_var.set(f"✓ RTSP Stream: {url}")
            self.app.output_mode_copy_btn.pack(side='right')  # Show copy button
            app_logger.info(f"RTSP server started: {url}")
            app_logger.info(f"Connect with VLC or NINA using above URL")
        else:
            self.app.output_mode_status_var.set("❌ ffmpeg not found - Install ffmpeg and add to PATH (see Logs)")
            self.rtsp_server = None
            # Show helpful dialog
            messagebox.showwarning(
                "ffmpeg Required",
                "RTSP streaming requires ffmpeg.\n\n"
                "Steps to enable RTSP:\n"
                "1. Download ffmpeg from https://ffmpeg.org/download.html\n"
                "2. Extract and add ffmpeg.exe to your system PATH\n"
                "3. Restart ASIOverlayWatchDog\n\n"
                "Check the Logs tab for more details."
            )
    
    def ensure_output_mode_started(self):
        """Ensure output mode servers are started if configured (called when capture begins)"""
        mode = self.app.output_mode_var.get()
        
        # If webserver mode and not running, start it
        if mode == 'webserver':
            if not self.web_server or not self.web_server.running:
                app_logger.info("Starting webserver automatically (configured as output mode)")
                self.apply_output_mode()
        
        # If RTSP mode and not running, start it
        elif mode == 'rtsp':
            if not self.rtsp_server or not self.rtsp_server.running:
                app_logger.info("Starting RTSP server automatically (configured as output mode)")
                self.apply_output_mode()
    
    def push_to_output_servers(self, image_path, processed_img=None):
        """Push processed image to active output servers
        
        Args:
            image_path: Path to the saved image file
            processed_img: Optional PIL Image. If None, will load from image_path
        """
        try:
            # Load image from file if not provided (PERF-001: avoid keeping in memory)
            if processed_img is None:
                from PIL import Image
                processed_img = Image.open(image_path)
                should_close = True
            else:
                should_close = False
            
            try:
                # Convert PIL Image to bytes for web server
                if self.web_server and self.web_server.running:
                    img_bytes = io.BytesIO()
                    # Use configured output format and quality for web server
                    output_format = self.app.output_format_var.get().upper()
                    if output_format == 'JPG' or output_format == 'JPEG':
                        quality = int(round(self.app.jpg_quality_var.get()))
                        processed_img.save(img_bytes, format='JPEG', quality=quality, optimize=True)
                        content_type = 'image/jpeg'
                    else:
                        processed_img.save(img_bytes, format='PNG', optimize=True)
                        content_type = 'image/png'
                    
                    self.web_server.update_image(image_path, img_bytes.getvalue(), content_type=content_type)
                
                # Push PIL Image to RTSP server
                if self.rtsp_server and self.rtsp_server.running:
                    self.rtsp_server.update_image(processed_img)
            finally:
                # Close image if we loaded it
                if should_close and hasattr(processed_img, 'close'):
                    processed_img.close()
                    
        except Exception as e:
            app_logger.error(f"Error pushing to output servers: {e}")
    
    def copy_output_url(self):
        """Copy the output server URL to clipboard"""
        mode = self.app.output_mode_var.get()
        url = None
        
        if mode == 'webserver' and self.web_server:
            url = self.web_server.get_url()
        elif mode == 'rtsp' and self.rtsp_server:
            url = self.rtsp_server.get_url()
        
        if url:
            self.app.root.clipboard_clear()
            self.app.root.clipboard_append(url)
            self.app.root.update()  # Ensure clipboard is updated
            app_logger.info(f"Copied to clipboard: {url}")
            
            # Visual feedback
            original_text = self.app.output_mode_status_var.get()
            self.app.output_mode_status_var.set(f"📋 Copied: {url}")
            self.app.root.after(2000, lambda: self.app.output_mode_status_var.set(original_text))
        else:
            app_logger.warning("No URL to copy - server may not be running")
    
    def stop_all_servers(self):
        """Stop all output servers (called on application close)"""
        try:
            if self.web_server:
                self.web_server.stop()
        except Exception as e:
            app_logger.debug(f"Error stopping web server: {e}")
        
        try:
            if self.rtsp_server:
                self.rtsp_server.stop()
        except Exception as e:
            app_logger.debug(f"Error stopping RTSP server: {e}")
    
    # ===== Discord Alert Methods =====
    
    def save_discord_settings(self):
        """Save Discord settings"""
        # Debug: Log what we're about to save
        webhook = self.app.discord_webhook_var.get()
        app_logger.info(f"Saving Discord webhook: {webhook[:50]}..." if len(webhook) > 50 else f"Saving Discord webhook: {webhook}")
        app_logger.info(f"Discord enabled: {self.app.discord_enabled_var.get()}")
        
        self.app.save_config()
        app_logger.info("Discord settings saved")
        self.app.discord_test_status_var.set("✓ Settings saved")
        self.app.root.after(3000, lambda: self.app.discord_test_status_var.set(""))
        
        # Update Discord alerts instance with new config
        self.discord_alerts = DiscordAlerts(self.app.config.data)
        
        # Reschedule periodic updates if interval changed
        self.schedule_discord_periodic()
    
    def test_discord_webhook(self):
        """Test Discord webhook connection"""
        if not self.app.discord_webhook_var.get():
            self.app.discord_test_status_var.set("❌ Please enter webhook URL")
            app_logger.error("Discord webhook URL not set")
            return
        
        # Auto-save settings before testing
        self.save_discord_settings()
        
        # Temporarily enable Discord for testing if not enabled
        was_enabled = self.app.discord_enabled_var.get()
        if not was_enabled:
            self.app.discord_enabled_var.set(True)
            self.save_discord_settings()
        
        # Send test message
        success = self.discord_alerts.send_discord_message(
            "🧪 Test Alert",
            "This is a test message from ASIOverlayWatchDog. If you see this, your webhook is configured correctly!",
            level="info"
        )
        
        # Restore original enabled state if we changed it
        if not was_enabled:
            self.app.discord_enabled_var.set(False)
            self.save_discord_settings()
        
        if success:
            self.app.discord_test_status_var.set("✓ Test successful!")
        else:
            self.app.discord_test_status_var.set("❌ Test failed - check logs")
        
        # Update status display if status var exists
        if hasattr(self.app, 'discord_status_var'):
            self.app.discord_status_var.set(self.discord_alerts.get_last_status())
        
        # Clear test status after 5 seconds
        self.app.root.after(5000, lambda: self.app.discord_test_status_var.set(""))
    
    def send_test_discord_alert(self):
        """Send a full test alert with image if available"""
        if not self.app.discord_enabled_var.get():
            messagebox.showwarning("Discord Disabled", 
                                 "Please enable Discord alerts first")
            return
        
        if not self.app.discord_webhook_var.get():
            messagebox.showwarning("No Webhook", 
                                 "Please configure webhook URL first")
            return
        
        # Auto-save settings before testing
        self.save_discord_settings()
        
        # Get latest image path
        image_path = None
        if self.app.discord_include_image_var.get() and self.app.last_processed_image:
            image_path = self.app.last_processed_image
        elif self.app.discord_include_image_var.get() and self.app.last_captured_image:
            image_path = self.app.last_captured_image
        
        # Send test alert
        success = self.discord_alerts.send_discord_message(
            "🧪 Test Alert from ASIOverlayWatchDog",
            f"""**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

This is a test alert with your current configuration.""",
            level="info",
            image_path=image_path
        )
        
        if success:
            messagebox.showinfo("Test Sent", 
                              "Test alert sent successfully! Check your Discord channel.")
        else:
            messagebox.showerror("Test Failed", 
                               "Failed to send test alert. Check the Logs tab for details.")
    
    def on_discord_color_change(self, *args):
        """Handle Discord embed color change"""
        # Color changes are automatically saved when config is saved
        # This is just a callback placeholder for trace_add
        pass
    
    def on_discord_enabled_change(self):
        """Handle Discord enable/disable"""
        enabled = self.app.discord_enabled_var.get()
        
        # Enable/disable all option widgets
        state = 'normal' if enabled else 'disabled'
        
        for child in self.app.discord_options_frame.winfo_children():
            self._set_widget_state_recursive(child, state)
        
        # Reschedule periodic updates
        self.schedule_discord_periodic()
    
    def on_discord_periodic_change(self):
        """Handle periodic posting enable/disable"""
        enabled = self.app.discord_periodic_enabled_var.get()
        
        # Enable/disable periodic options
        state = 'normal' if enabled else 'disabled'
        
        for child in self.app.discord_periodic_options_frame.winfo_children():
            self._set_widget_state_recursive(child, state)
        
        # Reschedule periodic updates
        self.schedule_discord_periodic()
    
    def _set_widget_state_recursive(self, widget, state):
        """Recursively set state for widget and children"""
        try:
            widget.config(state=state)
        except:
            pass  # Some widgets don't support state
        
        for child in widget.winfo_children():
            self._set_widget_state_recursive(child, state)
    
    def schedule_discord_periodic(self, send_initial=False):
        """Schedule periodic Discord posting
        
        Args:
            send_initial: If True, send an initial message immediately before scheduling periodic posts
        """
        # Cancel existing job
        if self.discord_periodic_job:
            try:
                self.app.root.after_cancel(self.discord_periodic_job)
            except:
                pass
            self.discord_periodic_job = None
        
        # Send initial message if requested
        if send_initial and self.app.discord_enabled_var.get() and self.app.discord_periodic_enabled_var.get():
            self.send_discord_start_notification()
        
        # Schedule new job if enabled
        if (self.app.discord_enabled_var.get() and 
            self.app.discord_periodic_enabled_var.get() and
            (self.app.is_capturing or (self.app.watcher and self.app.watcher.observer))):
            
            interval_minutes = self.app.discord_interval_var.get()
            interval_ms = interval_minutes * 60 * 1000
            
            def periodic_post():
                self._post_periodic_discord_update()
                # Reschedule
                self.schedule_discord_periodic()
            
            self.discord_periodic_job = self.app.root.after(interval_ms, periodic_post)
            app_logger.info(f"Discord periodic posting scheduled every {interval_minutes} minutes")
    
    def _post_periodic_discord_update(self):
        """Post a periodic update to Discord"""
        if not self.discord_alerts:
            app_logger.warning("Discord alerts not initialized")
            return
        
        # Check if scheduled capture is enabled and we're in off-peak hours
        scheduled_enabled = self.app.config.get('scheduled_capture_enabled', False)
        if scheduled_enabled:
            scheduled_start = self.app.config.get('scheduled_start_time', '17:00')
            scheduled_end = self.app.config.get('scheduled_end_time', '09:00')
            
            if not is_within_scheduled_window(scheduled_enabled, scheduled_start, scheduled_end):
                app_logger.info("Skipping Discord periodic update - outside scheduled capture hours")
                return
        
        # Get latest image if available
        image_path = None
        if self.app.discord_include_image_var.get():
            if self.app.last_processed_image:
                image_path = self.app.last_processed_image
                app_logger.debug(f"Using last_processed_image: {image_path}")
            elif self.app.last_captured_image:
                image_path = self.app.last_captured_image
                app_logger.debug(f"Using last_captured_image: {image_path}")
            else:
                app_logger.warning("No image available for Discord post")
        else:
            app_logger.debug("Discord image inclusion disabled")
        
        # Build status message
        mode = "Camera Capture" if self.app.is_capturing else "Directory Watch"
        count = self.app.image_count
        
        message = f"""**Periodic Status Update**

**Mode:** {mode}
**Images Processed:** {count}
**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        
        app_logger.info(f"Sending Discord update with image: {image_path if image_path else 'None'}")
        self.discord_alerts.send_discord_message(
            "📊 Status Update",
            message,
            level="info",
            image_path=image_path
        )
    
    def send_discord_start_notification(self):
        """Send initial Discord notification when capture/watching starts"""
        if not self.discord_alerts:
            return
        
        # Get latest image if available
        image_path = None
        if self.app.discord_include_image_var.get():
            if self.app.last_processed_image:
                image_path = self.app.last_processed_image
            elif self.app.last_captured_image:
                image_path = self.app.last_captured_image
        
        # Build start message
        mode = "Camera Capture" if self.app.is_capturing else "Directory Watch"
        
        message = f"""**Capture Started**

**Mode:** {mode}
**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        
        self.discord_alerts.send_discord_message(
            "🚀 Capture Started",
            message,
            level="info",
            image_path=image_path
        )
        app_logger.info("Discord start notification sent")
    
    def check_discord_periodic_send(self, image_path):
        """
        Check if it's time to send a periodic Discord update.
        This is called after each image is processed.
        
        Args:
            image_path: Path to the processed image
        """
        # Only send if Discord is enabled and periodic posting is enabled
        if not self.app.discord_enabled_var.get():
            return
        
        if not self.app.discord_periodic_enabled_var.get():
            return
        
        if not self.discord_alerts:
            return
        
        # Check if we should send based on interval
        # This is handled by the scheduled job, but we update last_processed_image
        # so the scheduled post uses the latest image
        self.app.last_processed_image = image_path
    
    def send_discord_error(self, error_text):
        """
        Send an error alert to Discord
        
        Args:
            error_text: Error message to send
        """
        if not self.app.discord_enabled_var.get():
            return
        
        if not self.discord_alerts:
            return
        
        self.discord_alerts.send_discord_message(
            "❌ Error Alert",
            f"**Error occurred:**\n{error_text}\n\n**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            level="error"
        )
