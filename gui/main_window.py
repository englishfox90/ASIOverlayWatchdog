"""
Main window for AllSky Overlay Watchdog
Modern GUI with modular tab components and delegated business logic
"""
import tkinter as tk
from tkinter import filedialog, messagebox
import ttkbootstrap as ttk
import os
from datetime import datetime

from services.config import Config
from services.watcher import FileWatcher
from services.logger import app_logger
from services.discord_alerts import DiscordAlerts
from services.web_output import WebOutputServer
from services.rtsp_output import RTSPStreamServer

from .header import StatusHeader, LiveMonitoringHeader
from .capture_tab import CaptureTab
from .settings_tab import SettingsTab
from .overlay_tab import OverlayTab
from .preview_tab import PreviewTab
from .logs_tab import LogsTab
from .discord_tab import DiscordTab
from .overlay_manager import OverlayManager
from .camera_controller import CameraController
from .image_processor import ImageProcessor
from .status_manager import StatusManager
from version import __version__

# Application metadata
APP_VERSION = __version__
APP_AUTHOR = "Paul Fox-Reeks"


class ModernOverlayApp:
    """Modern themed AllSky Overlay application"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("AllSky Overlay Watchdog - ZWO Camera Edition")
        
        # Set application icon
        try:
            from utils_paths import resource_path
            from PIL import Image, ImageTk
            icon_path = resource_path('app_icon.ico')
            if os.path.exists(icon_path):
                # Set window icon (title bar)
                self.root.iconbitmap(icon_path)
                
                # Set taskbar icon (convert ICO to PhotoImage)
                try:
                    icon_image = Image.open(icon_path)
                    # Use largest size from ICO
                    if hasattr(icon_image, 'size'):
                        photo = ImageTk.PhotoImage(icon_image)
                        self.root.iconphoto(True, photo)
                        # Keep reference to prevent garbage collection
                        self._icon_photo = photo
                except Exception as e:
                    app_logger.debug(f"Could not set taskbar icon: {e}")
        except Exception as e:
            # Icon is optional, don't fail if it's missing
            pass
        
        # Load config
        self.config = Config()
        
        # Initialize Discord alerts
        self.discord_alerts = DiscordAlerts(self.config.data)
        
        # Set window geometry
        geometry = self.config.get('window_geometry', '1280x1300')
        self.root.geometry(geometry)
        self.root.minsize(1024, 1300)
        
        # Save geometry on close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Initialize state
        self.watcher = None
        self.web_server = None  # HTTP server for web output mode
        self.rtsp_server = None  # RTSP server for streaming mode
        self.last_processed_image = None
        self.last_captured_image = None
        self.image_count = 0
        self.selected_camera_index = 0
        self.selected_overlay_index = None
        self.preview_image = None
        self.is_capturing = False
        self.is_loading_config = False  # Flag to prevent saving during load
        
        # Initialize preview variables (will be set by PreviewTab)
        self.auto_refresh_var = tk.BooleanVar(value=True)
        self.preview_zoom_var = tk.IntVar(value=100)
        
        # Initialize logs variables (will be set by LogsTab)
        self.auto_scroll_var = tk.BooleanVar(value=True)
        
        # Initialize exposure unit (needed before GUI creation for load_config)
        self.exposure_unit_var = tk.StringVar(value='s')
        
        # Create GUI
        self.create_gui()
        
        # Initialize managers (after GUI creation so they have access to widgets)
        self.overlay_manager = OverlayManager(self)
        self.camera_controller = CameraController(self)
        self.image_processor = ImageProcessor(self)
        self.status_manager = StatusManager(self)
        
        # Set Discord error callback
        app_logger.set_error_callback(self.send_discord_error)
        
        # Load configuration
        self.load_config()
        
        # Start log polling
        self.status_manager.poll_logs()
        
        # Start status updates
        self.status_manager.update_status_header()
    
    def create_gui(self):
        """Create the modern tabbed GUI layout"""
        # Create status header
        self.status_header = StatusHeader(self.root)
        
        # Create live monitoring header
        self.live_monitoring = LiveMonitoringHeader(self.root)
        
        # Store references to header components
        self.mode_status_var = self.status_header.mode_status_var
        self.capture_info_var = self.status_header.capture_info_var
        self.session_var = self.status_header.session_var
        self.image_count_var = self.status_header.image_count_var
        self.output_info_var = self.status_header.output_info_var
        self.mini_preview_label = self.live_monitoring.mini_preview_label
        self.mini_preview_image = None
        self.histogram_canvas = self.live_monitoring.histogram_canvas
        self.mini_log_text = self.live_monitoring.mini_log_text
        
        # Create notebook for tabs
        self.notebook = ttk.Notebook(self.root, bootstyle="dark")
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Initialize ALL Discord vars BEFORE creating Discord tab (prevents them being overwritten)
        self.discord_enabled_var = tk.BooleanVar(value=False)
        self.discord_webhook_var = tk.StringVar(value="")
        self.discord_color_var = tk.StringVar(value="#0EA5E9")
        self.discord_post_errors_var = tk.BooleanVar(value=False)
        self.discord_post_lifecycle_var = tk.BooleanVar(value=False)
        self.discord_periodic_enabled_var = tk.BooleanVar(value=False)
        self.discord_interval_var = tk.IntVar(value=60)
        self.discord_include_image_var = tk.BooleanVar(value=True)
        self.discord_username_var = tk.StringVar(value="")
        self.discord_avatar_var = tk.StringVar(value="")
        self.discord_test_status_var = tk.StringVar(value="")
        
        # Create tabs
        self.capture_tab = CaptureTab(self.notebook, self)
        self.overlays_tab = OverlayTab(self.notebook, self)
        self.settings_tab = SettingsTab(self.notebook, self)
        self.preview_tab = PreviewTab(self.notebook, self)
        self.discord_tab = DiscordTab(self.notebook, self)
        self.logs_tab = LogsTab(self.notebook, self)
        
        # Create menu bar
        self.create_menu()
        
        # Setup live settings bindings
        self.setup_live_settings_bindings()
    
    def setup_live_settings_bindings(self):
        """Setup variable traces to update camera settings live during capture"""
        def on_setting_change(*args):
            # Only update if camera is actively capturing
            if self.camera_controller and self.camera_controller.zwo_camera and \
               hasattr(self, 'is_capturing') and self.is_capturing:
                self.camera_controller.update_live_settings()
        
        # Bind all camera setting variables
        self.exposure_var.trace_add('write', on_setting_change)
        self.gain_var.trace_add('write', on_setting_change)
        self.wb_r_var.trace_add('write', on_setting_change)
        self.wb_b_var.trace_add('write', on_setting_change)
        self.offset_var.trace_add('write', on_setting_change)
        self.flip_var.trace_add('write', on_setting_change)
        self.bayer_pattern_var.trace_add('write', on_setting_change)
        self.target_brightness_var.trace_add('write', on_setting_change)
        self.wb_mode_var.trace_add('write', on_setting_change)
        self.wb_gw_low_var.trace_add('write', on_setting_change)
        self.wb_gw_high_var.trace_add('write', on_setting_change)
    
    def create_menu(self):
        """Create menu bar"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Save Settings", command=self.save_config)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_closing)
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self.show_about)
    
    def show_about(self):
        """Show about dialog"""
        about_text = f"""AllSky Overlay Watchdog
ZWO Camera Edition

Version: {APP_VERSION}
Author: {APP_AUTHOR}

A modern astrophotography tool for adding
metadata overlays to sky images.

Supports:
• ZWO ASI cameras (direct capture)
• Directory watching (auto-processing)
• Customizable text overlays
• Auto brightness adjustment
• Automated cleanup"""
        
        messagebox.showinfo("About", about_text)
    
    # ===== EVENT HANDLERS =====
    
    def on_closing(self):
        """Handle window close event"""
        # Send shutdown message to Discord if enabled
        discord_config = self.config.get('discord', {})
        if discord_config.get('enabled') and discord_config.get('post_startup_shutdown'):
            try:
                self.discord_alerts.send_shutdown_message()
            except Exception as e:
                app_logger.debug(f"Discord shutdown message failed: {e}")
        
        # Save window geometry
        try:
            self.config.set('window_geometry', self.root.geometry())
            self.save_config()
        except Exception as e:
            app_logger.debug(f"Failed to save window geometry: {e}")
        
        # Stop any active processes
        try:
            self.stop_watching()
        except Exception as e:
            app_logger.debug(f"Error stopping watcher: {e}")
        
        try:
            self.camera_controller.stop_camera_capture()
        except Exception as e:
            app_logger.debug(f"Error stopping camera: {e}")
        
        # Stop output servers
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
        
        # Cancel Discord periodic job if active
        try:
            if hasattr(self, 'discord_periodic_job') and self.discord_periodic_job:
                self.root.after_cancel(self.discord_periodic_job)
        except Exception as e:
            app_logger.debug(f"Error canceling Discord job: {e}")
        
        # Flush file logs before exit
        try:
            if hasattr(app_logger, 'file_handler'):
                app_logger.file_handler.flush()
        except Exception as e:
            app_logger.debug(f"Error flushing logs: {e}")
        
        self.root.destroy()
    
    def auto_start_capture(self, auto_stop=None):
        """Auto-start camera capture (called from command line args)
        
        Args:
            auto_stop: If set, schedule stop after this many seconds (0 = no auto-stop)
        """
        # Check if in camera mode
        if self.capture_mode_var.get() != 'camera':
            app_logger.warning("Auto-start: Not in camera mode, switching to camera mode")
            self.capture_mode_var.set('camera')
            self.on_mode_change()
            # Wait a bit for mode change to complete
            self.root.after(500, lambda: self._do_auto_start(auto_stop))
        else:
            self._do_auto_start(auto_stop)
    
    def _do_auto_start(self, auto_stop):
        """Internal method to actually start capture"""
        # Check if cameras are available (check combo box values)
        if not self.camera_combo.get() or not self.camera_combo['values']:
            app_logger.warning("Auto-start: Cameras not ready yet, waiting 1 more second...")
            # Try again in 1 second
            self.root.after(1000, lambda: self._do_auto_start(auto_stop))
            return
        
        # Check if already capturing
        if self.is_capturing:
            app_logger.warning("Auto-start: Already capturing")
            return
        
        app_logger.info(f"Auto-start: Starting camera capture with saved camera: {self.camera_combo.get()}")
        
        # Start capture
        self.camera_controller.start_camera_capture()
        
        # Schedule auto-stop if requested
        if auto_stop is not None and auto_stop > 0:
            app_logger.info(f"Auto-stop: Scheduled to stop capture in {auto_stop} seconds")
            self.root.after(auto_stop * 1000, self._do_auto_stop)
        elif auto_stop == 0:
            app_logger.info("Auto-stop: Will run until manually stopped or closed")
    
    def _do_auto_stop(self):
        """Internal method to stop capture (from auto-stop timer)"""
        if self.is_capturing:
            app_logger.info("Auto-stop: Stopping camera capture")
            self.camera_controller.stop_camera_capture()
        else:
            app_logger.warning("Auto-stop: Not currently capturing")
    
    def on_mode_change(self):
        """Handle capture mode change"""
        mode = self.capture_mode_var.get()
        
        if mode == 'watch':
            self.watch_frame.pack(fill='x', pady=(5, 10))
            self.camera_frame.pack_forget()
        else:
            self.camera_frame.pack(fill='x', pady=(5, 10))
            self.watch_frame.pack_forget()
            # Only auto-detect if SDK is properly initialized and no cameras listed
            if not self.camera_combo.get() and self.camera_controller.is_sdk_available():
                self.root.after(100, self.camera_controller.detect_cameras)
    
    def on_auto_brightness_toggle(self):
        """Handle auto brightness checkbox"""
        enabled = self.auto_brightness_var.get()
        if enabled:
            self.brightness_scale.config(state='normal')
            if hasattr(self, 'brightness_value_label'):
                self.brightness_value_label.config(fg='#FFFFFF')
            app_logger.info("Auto brightness enabled - brightness factor slider active")
        else:
            self.brightness_scale.config(state='disabled')
            if hasattr(self, 'brightness_value_label'):
                self.brightness_value_label.config(fg='#888888')
            app_logger.info("Auto brightness disabled - brightness factor has no effect")
    
    # ===== DELEGATE METHODS (for backward compatibility with tabs) =====
    
    def detect_cameras(self):
        """Delegate to camera_controller"""
        self.camera_controller.detect_cameras()
    
    def start_camera_capture(self):
        """Delegate to camera_controller"""
        self.camera_controller.start_camera_capture()
    
    def stop_camera_capture(self):
        """Delegate to camera_controller"""
        self.camera_controller.stop_camera_capture()
    
    def on_camera_selected(self, event=None):
        """Delegate to camera_controller"""
        self.camera_controller.on_camera_selected(event)
    
    def on_auto_exposure_toggle(self):
        """Delegate to camera_controller"""
        self.camera_controller.on_auto_exposure_toggle()
    
    def on_wb_mode_change(self):
        """Handle white balance mode change - show/hide appropriate controls"""
        mode = self.wb_mode_var.get()
        
        # Update hint label
        hints = {
            'asi_auto': '(SDK Auto WB)',
            'manual': '(Manual R/B gains)',
            'gray_world': '(Software algorithm)'
        }
        self.wb_mode_hint_label.config(text=hints.get(mode, ''))
        
        # Show/hide appropriate control frames
        if mode == 'manual':
            self.wb_manual_frame.pack(fill='x', pady=(0, 0))
            self.wb_gray_world_frame.pack_forget()
        elif mode == 'gray_world':
            self.wb_manual_frame.pack_forget()
            self.wb_gray_world_frame.pack(fill='x', pady=(0, 0))
        else:  # asi_auto
            self.wb_manual_frame.pack_forget()
            self.wb_gray_world_frame.pack_forget()
        
        # Save to config
        self.save_config()
    
    def get_overlays_config(self):
        """Delegate to overlay_manager"""
        return self.overlay_manager.get_overlays_config()
    
    def rebuild_overlay_list(self):
        """Delegate to overlay_manager"""
        self.overlay_manager.rebuild_overlay_list()
    
    def on_overlay_tree_select(self, event=None):
        """Delegate to overlay_manager"""
        self.overlay_manager.on_overlay_tree_select(event)
    
    def add_new_overlay(self):
        """Delegate to overlay_manager"""
        self.overlay_manager.add_new_overlay()
    
    def duplicate_overlay(self):
        """Delegate to overlay_manager"""
        self.overlay_manager.duplicate_overlay()
    
    def delete_overlay(self):
        """Delegate to overlay_manager"""
        self.overlay_manager.delete_overlay()
    
    def clear_all_overlays(self):
        """Delegate to overlay_manager"""
        self.overlay_manager.clear_all_overlays()
    
    def apply_overlay_changes(self):
        """Delegate to overlay_manager"""
        self.overlay_manager.apply_overlay_changes()
    
    def reset_overlay_editor(self):
        """Delegate to overlay_manager"""
        self.overlay_manager.reset_overlay_editor()
    
    def on_overlay_edit(self):
        """Delegate to overlay_manager"""
        self.overlay_manager.on_overlay_edit()
    
    def on_datetime_mode_change(self):
        """Delegate to overlay_manager"""
        self.overlay_manager.on_datetime_mode_change()
    
    def update_datetime_preview(self):
        """Delegate to overlay_manager"""
        self.overlay_manager.update_datetime_preview()
    
    def on_background_toggle(self):
        """Delegate to overlay_manager"""
        self.overlay_manager.on_background_toggle()
    
    def insert_token(self):
        """Delegate to overlay_manager"""
        self.overlay_manager.insert_token()
    
    def refresh_preview(self, auto_fit=True):
        """Delegate to image_processor"""
        self.image_processor.refresh_preview(auto_fit)
    
    def clear_logs(self):
        """Delegate to status_manager"""
        self.status_manager.clear_logs()
    
    def save_logs(self):
        """Delegate to status_manager"""
        self.status_manager.save_logs()
    
    # ===== DIRECTORY/FILE BROWSING =====
    
    def browse_watch_dir(self):
        """Browse for watch directory"""
        dir_path = filedialog.askdirectory(title="Select directory to watch")
        if dir_path:
            self.watch_dir_var.set(dir_path)
    
    def browse_output_dir(self):
        """Browse for output directory"""
        dir_path = filedialog.askdirectory(title="Select output directory")
        if dir_path:
            self.output_dir_var.set(dir_path)
    
    def browse_sdk_path(self):
        """Browse for SDK DLL"""
        file_path = filedialog.askopenfilename(
            title="Select ASICamera2.dll",
            filetypes=[("DLL files", "*.dll"), ("All files", "*.*")]
        )
        if file_path:
            self.sdk_path_var.set(file_path)
    
    # ===== DIRECTORY WATCHING =====
    
    def start_watching(self):
        """Start directory watching"""
        watch_dir = self.watch_dir_var.get()
        
        if not watch_dir or not os.path.exists(watch_dir):
            messagebox.showerror("Error", "Please select a valid directory to watch")
            return
        
        try:
            overlays = self.overlay_manager.get_overlays_config()
            output_dir = self.output_dir_var.get()
            recursive = self.watch_recursive_var.get()
            
            self.watcher = FileWatcher(
                watch_directory=watch_dir,
                output_directory=output_dir,
                overlays=overlays,
                recursive=recursive,
                callback=self.on_image_processed
            )
            
            self.watcher.start()
            
            # Update UI
            self.start_watch_button.config(state='disabled')
            self.stop_watch_button.config(state='normal')
            app_logger.info(f"Started watching: {watch_dir}")
            
        except Exception as e:
            app_logger.error(f"Failed to start watching: {e}")
            messagebox.showerror("Error", f"Failed to start watching:\n{str(e)}")
    
    def stop_watching(self):
        """Stop directory watching"""
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
            
            self.start_watch_button.config(state='normal')
            self.stop_watch_button.config(state='disabled')
            app_logger.info("Stopped watching")
    
    def on_image_processed(self, output_path, processed_img=None):
        """Callback when watcher processes an image"""
        self.image_count += 1
        self.root.after(0, lambda: self.image_count_var.set(str(self.image_count)))
        
        # Push to output servers if active
        if processed_img:
            self._push_to_output_servers(output_path, processed_img)
    
    # ===== CONFIGURATION =====
    
    def load_config(self):
        """Load configuration into GUI"""
        self.is_loading_config = True  # Prevent saves during load
        
        self.capture_mode_var.set(self.config.get('capture_mode', 'watch'))
        self.watch_dir_var.set(self.config.get('watch_directory', ''))
        self.watch_recursive_var.set(self.config.get('watch_recursive', True))
        self.output_dir_var.set(self.config.get('output_directory', ''))
        
        # Handle old config keys
        filename_pattern = self.config.get('filename_pattern', self.config.get('output_pattern', '{session}_{filename}'))
        self.filename_pattern_var.set(filename_pattern)
        
        output_format = self.config.get('output_format', 'png')
        if output_format.upper() == 'JPG':
            output_format = 'jpg'
        elif output_format.upper() == 'PNG':
            output_format = 'png'
        self.output_format_var.set(output_format.lower())
        
        self.jpg_quality_var.set(self.config.get('jpg_quality', 95))
        self.resize_percent_var.set(self.config.get('resize_percent', 100))
        self.auto_brightness_var.set(self.config.get('auto_brightness', False))
        
        # Handle old brightness keys
        brightness = self.config.get('brightness_factor', 
                                    self.config.get('auto_brightness_factor',
                                                   self.config.get('preview_brightness', 1.5)))
        self.brightness_var.set(brightness)
        
        # Saturation
        self.saturation_var.set(self.config.get('saturation_factor', 1.0))
        
        # Handle old timestamp corner key
        timestamp = self.config.get('timestamp_corner', False)
        if isinstance(timestamp, bool):
            self.timestamp_corner_var.set(timestamp)
        else:
            self.timestamp_corner_var.set(self.config.get('show_timestamp_corner', False))
        
        self.cleanup_enabled_var.set(self.config.get('cleanup_enabled', False))
        self.cleanup_max_size_var.set(self.config.get('cleanup_max_size_gb', 10.0))
        
        # ZWO settings
        from utils_paths import resource_path
        self.sdk_path_var.set(self.config.get('zwo_sdk_path', resource_path('ASICamera2.dll')))
        
        # Handle exposure in both ms and seconds - default to seconds for better UX
        exposure_ms = self.config.get('zwo_exposure_ms', self.config.get('zwo_exposure', 100.0))
        self.exposure_var.set(exposure_ms / 1000.0)
        self.exposure_unit_var.set('s')
        self.capture_tab.set_exposure_unit('s')
        
        self.gain_var.set(self.config.get('zwo_gain', 100))
        self.wb_r_var.set(self.config.get('zwo_wb_r', 75))
        self.wb_b_var.set(self.config.get('zwo_wb_b', 99))
        
        # Load white balance config (replaces old auto_wb_var)
        wb_config = self.config.get('white_balance', {
            'mode': 'asi_auto',
            'manual_red_gain': 1.0,
            'manual_blue_gain': 1.0,
            'gray_world_low_pct': 5,
            'gray_world_high_pct': 95
        })
        self.wb_mode_var.set(wb_config.get('mode', 'asi_auto'))
        self.wb_gw_low_var.set(wb_config.get('gray_world_low_pct', 5))
        self.wb_gw_high_var.set(wb_config.get('gray_world_high_pct', 95))
        
        self.offset_var.set(self.config.get('zwo_offset', 20))
        self.bayer_pattern_var.set(self.config.get('zwo_bayer_pattern', 'BGGR'))
        
        # Handle flip - convert string to int if needed
        flip_val = self.config.get('zwo_flip', 0)
        flip_map_reverse = {'None': 'None', 0: 'None', 1: 'Horizontal', 2: 'Vertical', 3: 'Both'}
        if isinstance(flip_val, str):
            self.flip_var.set(flip_val)
        else:
            self.flip_var.set(flip_map_reverse.get(flip_val, 'None'))
        
        # Handle interval
        interval = self.config.get('zwo_interval', self.config.get('zwo_capture_interval', 5.0))
        self.interval_var.set(interval)
        
        self.auto_exposure_var.set(self.config.get('zwo_auto_exposure', False))
        
        # Handle max exposure - convert from ms to seconds for new UI
        max_exp_ms = self.config.get('zwo_max_exposure_ms', self.config.get('zwo_max_exposure', 30000.0))
        self.max_exposure_var.set(max_exp_ms / 1000.0)
        
        # Load target brightness
        self.target_brightness_var.set(self.config.get('zwo_target_brightness', 100))
        
        # Update UI states
        self.on_mode_change()
        self.camera_controller.on_auto_exposure_toggle()
        self.on_auto_brightness_toggle()
        self.on_wb_mode_change()  # Set initial WB mode UI state
        
        # Update mode button styling
        self.capture_tab.update_mode_button_styling()
        
        # Load overlays - handle old field names
        overlays = self.config.get('overlays', [])
        for overlay in overlays:
            if 'x_offset' in overlay and 'offset_x' not in overlay:
                overlay['offset_x'] = overlay['x_offset']
            if 'y_offset' in overlay and 'offset_y' not in overlay:
                overlay['offset_y'] = overlay['y_offset']
            if 'font_style' not in overlay:
                overlay['font_style'] = 'normal'
            # Add default name if missing
            if 'name' not in overlay:
                overlay['name'] = overlay.get('text', 'Overlay')[:30]
        
        self.overlay_manager.rebuild_overlay_list()
        
        # Load Discord settings
        discord_config = self.config.get('discord', {})
        app_logger.info(f"Loading Discord webhook: {discord_config.get('webhook_url', '')[:50]}..." if len(discord_config.get('webhook_url', '')) > 50 else f"Loading Discord webhook: {discord_config.get('webhook_url', '')}")
        app_logger.info(f"Discord enabled: {discord_config.get('enabled', False)}")
        
        self.discord_enabled_var.set(discord_config.get('enabled', False))
        self.discord_webhook_var.set(discord_config.get('webhook_url', ''))
        self.discord_color_var.set(discord_config.get('embed_color_hex', '#0EA5E9'))
        self.discord_post_errors_var.set(discord_config.get('post_errors', False))
        self.discord_post_lifecycle_var.set(discord_config.get('post_startup_shutdown', False))
        self.discord_periodic_enabled_var.set(discord_config.get('periodic_enabled', False))
        self.discord_interval_var.set(discord_config.get('periodic_interval_minutes', 60))
        self.discord_include_image_var.set(discord_config.get('include_latest_image', True))
        self.discord_username_var.set(discord_config.get('username_override', ''))
        self.discord_avatar_var.set(discord_config.get('avatar_url', ''))
        
        # Update Discord UI state
        self.on_discord_enabled_change()
        self.on_discord_periodic_change()
        
        # Load output mode settings
        output_config = self.config.get('output', {})
        self.output_mode_var.set(output_config.get('mode', 'file'))
        self.webserver_host_var.set(output_config.get('webserver_host', '127.0.0.1'))
        self.webserver_port_var.set(output_config.get('webserver_port', 8080))
        self.webserver_path_var.set(output_config.get('webserver_path', '/latest'))
        self.rtsp_host_var.set(output_config.get('rtsp_host', '127.0.0.1'))
        self.rtsp_port_var.set(output_config.get('rtsp_port', 8554))
        self.rtsp_stream_name_var.set(output_config.get('rtsp_stream_name', 'asiwatchdog'))
        self.rtsp_fps_var.set(output_config.get('rtsp_fps', 1.0))
        
        # Update output mode UI state
        self.on_output_mode_change()
        
        # Start periodic Discord scheduler
        self.discord_periodic_job = None
        self.schedule_discord_periodic()
        
        # Send startup message if enabled
        if discord_config.get('enabled') and discord_config.get('post_startup_shutdown'):
            self.root.after(2000, self.discord_alerts.send_startup_message)  # Delay 2s to let UI settle
        
        self.is_loading_config = False  # Config loading complete
    
    def save_config(self):
        """Save current configuration"""
        # Don't save during initial config load
        if hasattr(self, 'is_loading_config') and self.is_loading_config:
            return
        
        self.config.set('capture_mode', self.capture_mode_var.get())
        self.config.set('watch_directory', self.watch_dir_var.get())
        self.config.set('watch_recursive', self.watch_recursive_var.get())
        self.config.set('output_directory', self.output_dir_var.get())
        self.config.set('filename_pattern', self.filename_pattern_var.get())
        self.config.set('output_format', self.output_format_var.get())
        self.config.set('jpg_quality', self.jpg_quality_var.get())
        self.config.set('resize_percent', self.resize_percent_var.get())
        self.config.set('auto_brightness', self.auto_brightness_var.get())
        self.config.set('brightness_factor', self.brightness_var.get())
        self.config.set('saturation_factor', self.saturation_var.get())
        self.config.set('timestamp_corner', self.timestamp_corner_var.get())
        self.config.set('cleanup_enabled', self.cleanup_enabled_var.get())
        self.config.set('cleanup_max_size_gb', self.cleanup_max_size_var.get())
        
        # ZWO settings - save exposure in milliseconds for consistency
        self.config.set('zwo_sdk_path', self.sdk_path_var.get())
        
        # Convert exposure to ms for storage
        exposure_value = self.exposure_var.get()
        if self.exposure_unit_var.get() == 's':
            exposure_ms = exposure_value * 1000.0
        else:
            exposure_ms = exposure_value
        self.config.set('zwo_exposure_ms', exposure_ms)
        
        self.config.set('zwo_gain', self.gain_var.get())
        self.config.set('zwo_wb_r', self.wb_r_var.get())
        self.config.set('zwo_wb_b', self.wb_b_var.get())
        
        # Save white balance config structure (replaces old zwo_auto_wb)
        self.config.set('white_balance', {
            'mode': self.wb_mode_var.get(),
            'manual_red_gain': 1.0,  # Not used in current UI, but kept for future
            'manual_blue_gain': 1.0,
            'gray_world_low_pct': self.wb_gw_low_var.get(),
            'gray_world_high_pct': self.wb_gw_high_var.get()
        })
        
        self.config.set('zwo_offset', self.offset_var.get())
        self.config.set('zwo_bayer_pattern', self.bayer_pattern_var.get())
        flip_map = {'None': 0, 'Horizontal': 1, 'Vertical': 2, 'Both': 3}
        self.config.set('zwo_flip', flip_map.get(self.flip_var.get(), 0))
        self.config.set('zwo_interval', self.interval_var.get())
        self.config.set('zwo_auto_exposure', self.auto_exposure_var.get())
        
        # Max exposure is now in seconds in UI
        max_exp_value = self.max_exposure_var.get()
        self.config.set('zwo_max_exposure_ms', max_exp_value * 1000.0)
        
        # Save target brightness
        self.config.set('zwo_target_brightness', self.target_brightness_var.get())
        
        # Save Discord settings
        self.config.set('discord', {
            'enabled': self.discord_enabled_var.get(),
            'webhook_url': self.discord_webhook_var.get(),
            'embed_color_hex': self.discord_color_var.get(),
            'post_errors': self.discord_post_errors_var.get(),
            'post_startup_shutdown': self.discord_post_lifecycle_var.get(),
            'periodic_enabled': self.discord_periodic_enabled_var.get(),
            'periodic_interval_minutes': self.discord_interval_var.get(),
            'include_latest_image': self.discord_include_image_var.get(),
            'username_override': self.discord_username_var.get(),
            'avatar_url': self.discord_avatar_var.get()
        })
        
        # Save output mode settings
        self.config.set('output', {
            'mode': self.output_mode_var.get(),
            'webserver_enabled': self.output_mode_var.get() == 'webserver',
            'webserver_host': self.webserver_host_var.get(),
            'webserver_port': self.webserver_port_var.get(),
            'webserver_path': self.webserver_path_var.get(),
            'webserver_status_path': self.config.get('output', {}).get('webserver_status_path', '/status'),
            'rtsp_enabled': self.output_mode_var.get() == 'rtsp',
            'rtsp_host': self.rtsp_host_var.get(),
            'rtsp_port': self.rtsp_port_var.get(),
            'rtsp_stream_name': self.rtsp_stream_name_var.get(),
            'rtsp_fps': self.rtsp_fps_var.get()
        })
        
        # Debug: Verify it's in self.config.data before saving
        app_logger.info(f"Before save - webhook in config.data: {self.config.data.get('discord', {}).get('webhook_url', '')[:50]}...")
        
        self.config.save()
        app_logger.info("Configuration saved")
    
    def apply_settings(self):
        """Apply all settings"""
        self.save_config()
        # Apply output mode changes (start/stop servers as needed)
        self.apply_output_mode()
        messagebox.showinfo("Success", "Settings applied and saved")
    
    # ===== Output Mode Methods =====
    
    def on_output_mode_change(self):
        """Handle output mode selection change"""
        from .theme import SPACING
        mode = self.output_mode_var.get()
        
        # Show/hide mode-specific settings
        if mode == 'file':
            self.webserver_frame.pack_forget()
            self.rtsp_frame.pack_forget()
            self.file_frame.pack(fill='x', pady=(0, SPACING['element_gap']))
            self.output_mode_status_var.set("Mode: File (Save to output directory)")
            self.output_mode_copy_btn.pack_forget()
        elif mode == 'webserver':
            self.file_frame.pack_forget()
            self.rtsp_frame.pack_forget()
            self.webserver_frame.pack(fill='x', pady=(0, SPACING['element_gap']))
            
            host = self.webserver_host_var.get()
            port = self.webserver_port_var.get()
            path = self.webserver_path_var.get()
            self.output_mode_status_var.set(f"Mode: Web Server (Click Apply to start)")
            self.output_mode_copy_btn.pack_forget()
        elif mode == 'rtsp':
            self.file_frame.pack_forget()
            self.webserver_frame.pack_forget()
            self.rtsp_frame.pack(fill='x', pady=(0, SPACING['element_gap']))
            
            host = self.rtsp_host_var.get()
            port = self.rtsp_port_var.get()
            stream = self.rtsp_stream_name_var.get()
            self.output_mode_status_var.set(f"Mode: RTSP Stream (Click Apply to start)")
            self.output_mode_copy_btn.pack_forget()
    
    def apply_output_mode(self):
        """Start/stop output servers based on selected mode"""
        mode = self.output_mode_var.get()
        
        # Stop any running servers
        if self.web_server and self.web_server.running:
            self.web_server.stop()
            self.web_server = None
        
        if self.rtsp_server and self.rtsp_server.running:
            self.rtsp_server.stop()
            self.rtsp_server = None
        
        # Hide copy button by default
        self.output_mode_copy_btn.pack_forget()
        
        # Start server for selected mode
        if mode == 'webserver':
            host = self.webserver_host_var.get()
            port = self.webserver_port_var.get()
            image_path = self.webserver_path_var.get()
            status_path = self.config.get('output', {}).get('webserver_status_path', '/status')
            
            self.web_server = WebOutputServer(host, port, image_path, status_path)
            if self.web_server.start():
                url = self.web_server.get_url()
                status_url = self.web_server.get_status_url()
                self.output_mode_status_var.set(f"✓ Web Server: {url}")
                self.output_mode_copy_btn.pack(side='right')  # Show copy button
                app_logger.info(f"Web server started: {url}")
                app_logger.info(f"Status endpoint: {status_url}")
            else:
                self.output_mode_status_var.set("❌ Failed to start web server (check logs)")
                self.web_server = None
        
        elif mode == 'rtsp':
            host = self.rtsp_host_var.get()
            port = self.rtsp_port_var.get()
            stream_name = self.rtsp_stream_name_var.get()
            fps = self.rtsp_fps_var.get()
            
            self.rtsp_server = RTSPStreamServer(host, port, stream_name, fps)
            if self.rtsp_server.start():
                url = self.rtsp_server.get_url()
                self.output_mode_status_var.set(f"✓ RTSP Stream: {url}")
                self.output_mode_copy_btn.pack(side='right')  # Show copy button
                app_logger.info(f"RTSP server started: {url}")
                app_logger.info(f"Connect with VLC or NINA using above URL")
            else:
                self.output_mode_status_var.set("❌ ffmpeg not found - Install ffmpeg and add to PATH (see Logs)")
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
        
        else:  # file mode
            self.output_mode_status_var.set("Mode: File (Saving to output directory)")
    
    def _push_to_output_servers(self, image_path, processed_img):
        """Push processed image to active output servers"""
        import io
        
        try:
            # Convert PIL Image to PNG bytes for web server
            if self.web_server and self.web_server.running:
                img_bytes = io.BytesIO()
                processed_img.save(img_bytes, format='PNG')
                self.web_server.update_image(image_path, img_bytes.getvalue())
            
            # Push PIL Image to RTSP server
            if self.rtsp_server and self.rtsp_server.running:
                self.rtsp_server.update_image(processed_img)
        except Exception as e:
            app_logger.error(f"Error pushing to output servers: {e}")
    
    def copy_output_url(self):
        """Copy the output server URL to clipboard"""
        mode = self.output_mode_var.get()
        url = None
        
        if mode == 'webserver' and self.web_server:
            url = self.web_server.get_url()
        elif mode == 'rtsp' and self.rtsp_server:
            url = self.rtsp_server.get_url()
        
        if url:
            self.root.clipboard_clear()
            self.root.clipboard_append(url)
            self.root.update()  # Ensure clipboard is updated
            app_logger.info(f"Copied to clipboard: {url}")
            
            # Visual feedback
            original_text = self.output_mode_status_var.get()
            self.output_mode_status_var.set(f"📋 Copied: {url}")
            self.root.after(2000, lambda: self.output_mode_status_var.set(original_text))
        else:
            app_logger.warning("No URL to copy - server may not be running")
    
    # ===== Discord Alert Methods =====
    
    def save_discord_settings(self):
        """Save Discord settings"""
        # Debug: Log what we're about to save
        app_logger.info(f"Saving Discord webhook: {self.discord_webhook_var.get()[:50]}..." if len(self.discord_webhook_var.get()) > 50 else f"Saving Discord webhook: {self.discord_webhook_var.get()}")
        app_logger.info(f"Discord enabled: {self.discord_enabled_var.get()}")
        
        self.save_config()
        app_logger.info("Discord settings saved")
        self.discord_test_status_var.set("✓ Settings saved")
        self.root.after(3000, lambda: self.discord_test_status_var.set(""))
        
        # Update Discord alerts instance with new config
        self.discord_alerts = DiscordAlerts(self.config.data)
        
        # Reschedule periodic updates if interval changed
        self.schedule_discord_periodic()
    
    def test_discord_webhook(self):
        """Test Discord webhook connection"""
        if not self.discord_webhook_var.get():
            self.discord_test_status_var.set("❌ Please enter webhook URL")
            app_logger.error("Discord webhook URL not set")
            return
        
        # Auto-save settings before testing
        self.save_discord_settings()
        
        # Temporarily enable Discord for testing if not enabled
        was_enabled = self.discord_enabled_var.get()
        if not was_enabled:
            self.discord_enabled_var.set(True)
            self.save_discord_settings()
        
        # Send test message
        success = self.discord_alerts.send_discord_message(
            "🧪 Test Alert",
            "This is a test message from ASIOverlayWatchDog. If you see this, your webhook is configured correctly!",
            level="info"
        )
        
        # Restore original enabled state if we changed it
        if not was_enabled:
            self.discord_enabled_var.set(False)
            self.save_discord_settings()
        
        if success:
            self.discord_test_status_var.set("✓ Test successful!")
        else:
            self.discord_test_status_var.set("❌ Test failed - check logs")
        
        # Update status display if status var exists
        if hasattr(self, 'discord_status_var'):
            self.discord_status_var.set(self.discord_alerts.get_last_status())
        
        # Clear test status after 5 seconds
        self.root.after(5000, lambda: self.discord_test_status_var.set(""))
    
    def send_test_discord_alert(self):
        """Send a full test alert with image if available"""
        if not self.discord_enabled_var.get():
            messagebox.showwarning("Discord Disabled", 
                                 "Please enable Discord alerts first")
            return
        
        if not self.discord_webhook_var.get():
            messagebox.showwarning("No Webhook", 
                                 "Please configure webhook URL first")
            return
        
        # Auto-save settings before testing
        self.save_discord_settings()
        
        # Get latest image path
        image_path = None
        if self.discord_include_image_var.get() and self.last_processed_image:
            image_path = self.last_processed_image
        elif self.discord_include_image_var.get() and self.last_captured_image:
            image_path = self.last_captured_image
        
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
    
    def on_discord_enabled_change(self):
        """Handle Discord enable/disable"""
        enabled = self.discord_enabled_var.get()
        
        # Enable/disable all option widgets
        state = 'normal' if enabled else 'disabled'
        
        for child in self.discord_options_frame.winfo_children():
            self._set_widget_state_recursive(child, state)
        
        # Reschedule periodic updates
        self.schedule_discord_periodic()
    
    def on_discord_periodic_change(self):
        """Handle periodic posting enable/disable"""
        enabled = self.discord_periodic_enabled_var.get()
        
        # Enable/disable periodic options
        state = 'normal' if enabled else 'disabled'
        
        for child in self.discord_periodic_options_frame.winfo_children():
            self._set_widget_state_recursive(child, state)
        
        # Reschedule periodic updates
        self.schedule_discord_periodic()
    
    def on_discord_color_change(self, *args):
        """Update color preview when hex value changes"""
        hex_color = self.discord_color_var.get()
        
        try:
            # Validate hex color
            if hex_color.startswith('#') and len(hex_color) == 7:
                int(hex_color[1:], 16)  # Test if valid hex
                self.discord_color_preview.configure(bg=hex_color)
            else:
                # Invalid, revert to default
                self.discord_color_preview.configure(bg='#0EA5E9')
        except (ValueError, tk.TclError):
            # Invalid hex, revert to default
            self.discord_color_preview.configure(bg='#0EA5E9')
    
    def _set_widget_state_recursive(self, widget, state):
        """Recursively set state for all child widgets"""
        try:
            if isinstance(widget, (ttk.Entry, ttk.Spinbox, ttk.Combobox)):
                widget.configure(state=state)
            elif isinstance(widget, (tk.Checkbutton, tk.Radiobutton)):
                widget.configure(state=state)
        except:
            pass
        
        # Recurse into children
        for child in widget.winfo_children():
            self._set_widget_state_recursive(child, state)
    
    def schedule_discord_periodic(self):
        """Schedule or cancel periodic Discord updates"""
        # Cancel existing job if any
        if hasattr(self, 'discord_periodic_job') and self.discord_periodic_job:
            self.root.after_cancel(self.discord_periodic_job)
            self.discord_periodic_job = None
        
        # Schedule new job if enabled
        discord_config = self.config.get('discord', {})
        if discord_config.get('enabled') and discord_config.get('periodic_enabled'):
            interval_min = discord_config.get('periodic_interval_minutes', 60)
            interval_ms = interval_min * 60 * 1000  # Convert to milliseconds
            
            def periodic_task():
                # Send periodic update
                image_path = self.last_processed_image or self.last_captured_image
                self.discord_alerts.send_periodic_update(image_path)
                
                # Reschedule
                self.discord_periodic_job = self.root.after(interval_ms, periodic_task)
            
            # Start the periodic task
            self.discord_periodic_job = self.root.after(interval_ms, periodic_task)
            app_logger.info(f"Discord periodic updates scheduled every {interval_min} minutes")
    
    def send_discord_error(self, error_text):
        """Send error to Discord if enabled"""
        discord_config = self.config.get('discord', {})
        if discord_config.get('enabled') and discord_config.get('post_errors'):
            self.discord_alerts.send_error_message(error_text)


def main(auto_start=False, auto_stop=None, headless=False):
    """Main entry point for the application
    
    Args:
        auto_start: If True, automatically start camera capture after initialization
        auto_stop: If set, stop capture after this many seconds (0 = run until closed)
        headless: If True, run without GUI (experimental, requires auto_start)
    """
    # Create root window with ttkbootstrap theme
    root = ttk.Window(themename="darkly")
    
    # Create app
    app = ModernOverlayApp(root)
    
    # Schedule auto-start if requested
    if auto_start:
        app_logger.info(f"Command line: Auto-start capture requested")
        # Wait for camera initialization (3 seconds after startup to ensure cameras are detected)
        root.after(3000, lambda: app.auto_start_capture(auto_stop))
    
    # Run
    root.mainloop()


if __name__ == "__main__":
    main()
