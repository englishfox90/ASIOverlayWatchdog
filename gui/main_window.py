"""
Main window for PFR Sentinel
Modern GUI with modular tab components and delegated business logic
"""
import tkinter as tk
from tkinter import filedialog, messagebox
import ttkbootstrap as ttk
import os
import gc
from datetime import datetime

from app_config import APP_DISPLAY_NAME, APP_SUBTITLE, APP_AUTHOR
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
from .output_manager import OutputManager
from .watch_controller import WatchController
from .theme import COLORS, FONTS, SPACING
from . import theme
from .settings_manager import SettingsManager
from version import __version__
from app_config import APP_DISPLAY_NAME, APP_AUTHOR

# Application metadata
APP_VERSION = __version__


class ModernOverlayApp:
    """Modern themed AllSky Overlay application"""
    
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_DISPLAY_NAME} v{APP_VERSION}")
        
        # Set application icon
        try:
            from utils_paths import resource_path
            from PIL import Image, ImageTk
            icon_path = resource_path('assets/app_icon.ico')
            # Fallback to root for compatibility
            if not os.path.exists(icon_path):
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
        
        # Initialize Weather Service (if configured)
        self.weather_service = None
        self._init_weather_service()
        
        # Set window geometry with validation
        geometry = self.config.get('window_geometry', '1400x1300')
        self._set_window_geometry(geometry)
        self.root.minsize(1100, 1300)
        
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
        self.output_manager = OutputManager(self)
        self.watch_controller = WatchController(self)
        self.settings_manager = SettingsManager(self)
        
        # Set Discord error callback
        app_logger.set_error_callback(self.send_discord_error)
        
        # Load configuration
        self.settings_manager.load_config()
        
        # Start log polling
        self.status_manager.poll_logs()
        
        # Start status updates
        self.status_manager.update_status_header()
        
        # Start periodic garbage collection (every 5 minutes)
        self.schedule_garbage_collection()
    
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
        
        # Bind tab selection to auto-fit preview when Preview tab is selected
        self.notebook.bind('<<NotebookTabChanged>>', self.on_tab_changed)
        
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
        about_text = f"""{APP_DISPLAY_NAME}
{APP_SUBTITLE}

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
    
    def schedule_garbage_collection(self):
        """Schedule periodic garbage collection to prevent memory leaks"""
        try:
            # Force garbage collection
            collected = gc.collect()
            if collected > 0:
                app_logger.debug(f"Garbage collection: freed {collected} objects")
        except Exception as e:
            app_logger.debug(f"Garbage collection error: {e}")
        finally:
            # Schedule next collection in 5 minutes (300000 ms)
            self.root.after(300000, self.schedule_garbage_collection)
    
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
    
    def on_tab_changed(self, event=None):
        """Handle notebook tab change - auto-fit preview when Preview tab is selected"""
        try:
            # Get the currently selected tab index
            current_tab = self.notebook.index(self.notebook.select())
            # Preview tab is at index 3 (Capture=0, Overlays=1, Settings=2, Preview=3)
            if current_tab == 3 and self.preview_image:
                # Delay slightly to ensure canvas is sized
                self.root.after(100, lambda: self.refresh_preview(auto_fit=True))
        except Exception as e:
            # Silently ignore errors (e.g., during initialization)
            pass
    
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
    
    def on_scheduled_capture_toggle(self):
        """Delegate to camera_controller"""
        self.camera_controller.on_scheduled_capture_toggle()
    
    def on_schedule_time_change(self, *args):
        """Delegate to camera_controller"""
        self.camera_controller.on_schedule_time_change(*args)
    
    def update_camera_status_for_schedule(self, status_text):
        """Delegate to camera_controller"""
        self.camera_controller.update_camera_status_for_schedule(status_text)
    
    def on_wb_mode_change(self):
        """Delegate to camera_controller"""
        self.camera_controller.on_wb_mode_change()
    
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
        """Show type selection dialog and delegate to overlay_manager"""
        from tkinter import simpledialog
        
        # Create semi-transparent overlay on main window
        overlay = tk.Frame(self.root, bg='black')
        overlay.place(x=0, y=0, relwidth=1, relheight=1)
        overlay.lift()
        
        # Set transparency (0.0 to 1.0, where 0.5 = 50% opaque)
        # Note: This sets the opacity of the overlay frame itself
        try:
            overlay.winfo_toplevel().attributes('-alpha', 0.5)
        except:
            pass  # Fallback if transparency not supported
        
        # Make overlay semi-transparent by using a canvas with alpha
        overlay_canvas = tk.Canvas(overlay, bg='black', highlightthickness=0)
        overlay_canvas.pack(fill='both', expand=True)
        # Set background with some transparency effect
        overlay_canvas.configure(bg='#000000')
        overlay.configure(bg='#000000')
        
        # Reset root alpha (overlay frame handles transparency differently)
        self.root.attributes('-alpha', 1.0)
        
        # Create actual overlay effect by updating
        self.root.update()
        
        # Create type selection dialog
        dialog = tk.Toplevel(self.root)
        dialog.title("Select Overlay Type")
        dialog.resizable(False, False)
        dialog.configure(bg=COLORS['bg_card'])
        
        # Set transient and grab
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Set size and center over parent window
        dialog_width = 450
        dialog_height = 150
        
        # Update to calculate proper size
        dialog.update_idletasks()
        
        # Get parent window position and size
        parent_x = self.root.winfo_x()
        parent_y = self.root.winfo_y()
        parent_width = self.root.winfo_width()
        parent_height = self.root.winfo_height()
        
        # Calculate centered position
        x = parent_x + (parent_width - dialog_width) // 2
        y = parent_y + (parent_height - dialog_height) // 2
        
        dialog.geometry(f"{dialog_width}x{dialog_height}+{x}+{y}")
        
        # Lift dialog above overlay
        dialog.lift()
        dialog.focus_force()
        
        # Result variable
        selected_type = tk.StringVar(value='text')
        
        # Title label
        title_label = tk.Label(dialog, text="Choose overlay type:",
                              font=FONTS['heading'],
                              bg=COLORS['bg_card'],
                              fg=COLORS['text_primary'])
        title_label.pack(pady=(20, 10))
        
        # Buttons frame
        btn_frame = tk.Frame(dialog, bg=COLORS['bg_card'])
        btn_frame.pack(pady=20)
        
        def select_and_close(overlay_type):
            selected_type.set(overlay_type)
            dialog.destroy()
            overlay.destroy()  # Remove overlay when dialog closes
        
        # Handle window close button (X)
        def on_close():
            dialog.destroy()
            overlay.destroy()
        
        dialog.protocol("WM_DELETE_WINDOW", on_close)
        
        # Text overlay button
        text_btn = theme.create_primary_button(btn_frame, "📝 Text Overlay",
                                                     lambda: select_and_close('text'))
        text_btn.pack(side='left', padx=5)
        
        # Image overlay button
        image_btn = theme.create_secondary_button(btn_frame, "🖼️ Image Overlay",
                                                        lambda: select_and_close('image'))
        image_btn.pack(side='left', padx=5)
        
        # Wait for dialog to close
        self.root.wait_window(dialog)
        
        # Ensure overlay is removed if still exists
        try:
            overlay.destroy()
        except:
            pass
        
        # Add overlay with selected type
        self.overlay_manager.add_new_overlay(selected_type.get())
    
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
        """Delegate to watch_controller"""
        self.watch_controller.browse_watch_dir()
    
    def browse_output_dir(self):
        """Delegate to watch_controller"""
        self.watch_controller.browse_output_dir()
    
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
        """Delegate to watch_controller"""
        self.watch_controller.start_watching()
    
    def stop_watching(self):
        """Delegate to watch_controller"""
        self.watch_controller.stop_watching()
    
    def on_image_processed(self, output_path, processed_img=None):
        """Delegate to watch_controller"""
        self.watch_controller.on_image_processed(output_path, processed_img)
    
    # ===== CONFIGURATION =====
    
    def load_config(self):
        """Delegate to settings_manager"""
        self.settings_manager.load_config()
    
    def save_config(self):
        """Delegate to settings_manager"""
        self.settings_manager.save_config()
    
    def apply_settings(self):
        """Delegate to settings_manager"""
        self.settings_manager.apply_settings()
    
    # ===== Weather Service Methods =====
    
    def _init_weather_service(self):
        """Initialize weather service from config"""
        try:
            from services.weather import WeatherService
            
            weather_config = self.config.get('weather', {})
            api_key = weather_config.get('api_key', '')
            location = weather_config.get('location', '')
            latitude = weather_config.get('latitude', '')
            longitude = weather_config.get('longitude', '')
            units = weather_config.get('units', 'metric')
            
            # Need API key AND (coordinates OR location)
            has_coords = bool(latitude and longitude)
            has_location = bool(location)
            
            if api_key and (has_coords or has_location):
                self.weather_service = WeatherService(
                    api_key, location, units,
                    latitude=latitude if latitude else None,
                    longitude=longitude if longitude else None
                )
                loc_info = f"({latitude}, {longitude})" if has_coords else location
                app_logger.info(f"Weather service initialized: {loc_info}, {units} units")
            else:
                self.weather_service = None
                app_logger.debug("Weather service not configured (missing API key or location/coordinates)")
        except Exception as e:
            app_logger.error(f"Failed to initialize weather service: {e}")
            self.weather_service = None
    
    def _set_window_geometry(self, geometry):
        """
        Set window geometry with validation.
        Centers the window if saved position is invalid or off-screen.
        
        Args:
            geometry: Geometry string in format 'WIDTHxHEIGHT+X+Y' or 'WIDTHxHEIGHT'
        """
        try:
            # Parse geometry string
            if '+' in geometry or '-' in geometry:
                # Has position info: WIDTHxHEIGHT+X+Y
                size_part = geometry.split('+')[0].split('-')[0]
                width, height = map(int, size_part.split('x'))
                
                # Extract x, y coordinates (handle negative positions)
                parts = geometry.replace('-', '+-').split('+')
                x = int(parts[1]) if len(parts) > 1 else 0
                y = int(parts[2]) if len(parts) > 2 else 0
            else:
                # Only size: WIDTHxHEIGHT
                width, height = map(int, geometry.split('x'))
                x, y = None, None
            
            # Get screen dimensions
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            
            # Validate dimensions
            if width < 800 or height < 600:
                app_logger.warning(f"Invalid window size {width}x{height}, using defaults")
                width, height = 1280, 1300
                x, y = None, None
            
            # Check if position is valid (title bar visible)
            position_valid = True
            if x is not None and y is not None:
                # Check if window would be off-screen or title bar not visible
                title_bar_height = 30  # Approximate title bar height
                
                if (x < -width + 100 or  # Too far left
                    y < -title_bar_height or  # Title bar above screen
                    x > screen_width - 100 or  # Too far right
                    y > screen_height - title_bar_height):  # Too far down
                    position_valid = False
                    app_logger.info(f"Window position {x},{y} is off-screen, centering")
            
            # Set geometry
            if x is None or y is None or not position_valid:
                # Center the window
                x = (screen_width - width) // 2
                y = (screen_height - height) // 2
                app_logger.debug(f"Centering window at {x},{y}")
            
            self.root.geometry(f"{width}x{height}+{x}+{y}")
            
        except (ValueError, IndexError) as e:
            # Invalid geometry string, use defaults and center
            app_logger.warning(f"Invalid geometry string '{geometry}': {e}")
            width, height = 1280, 1300
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            x = (screen_width - width) // 2
            y = (screen_height - height) // 2
            self.root.geometry(f"{width}x{height}+{x}+{y}")
    
    def test_weather_connection(self):
        """Test weather API connection and update status"""
        try:
            # Get current settings from UI
            api_key = self.weather_api_key_var.get().strip()
            location = self.weather_location_var.get().strip()
            latitude = self.weather_lat_var.get().strip() if hasattr(self, 'weather_lat_var') else ''
            longitude = self.weather_lon_var.get().strip() if hasattr(self, 'weather_lon_var') else ''
            units = self.weather_units_var.get()
            
            if not api_key:
                self.weather_status_var.set("❌ Error: API key required")
                return
            
            # Need either coordinates or location
            has_coords = bool(latitude and longitude)
            has_location = bool(location)
            
            if not has_coords and not has_location:
                self.weather_status_var.set("❌ Error: Coordinates or location required")
                return
            
            # Validate coordinates if provided
            if has_coords:
                try:
                    lat_float = float(latitude)
                    lon_float = float(longitude)
                    if not (-90 <= lat_float <= 90):
                        self.weather_status_var.set("❌ Error: Latitude must be -90 to 90")
                        return
                    if not (-180 <= lon_float <= 180):
                        self.weather_status_var.set("❌ Error: Longitude must be -180 to 180")
                        return
                except ValueError:
                    self.weather_status_var.set("❌ Error: Invalid coordinate format")
                    return
            
            self.weather_status_var.set("🔄 Testing connection...")
            self.root.update_idletasks()
            
            # Test connection
            from services.weather import WeatherService
            test_service = WeatherService(
                api_key, location, units,
                latitude=latitude if latitude else None,
                longitude=longitude if longitude else None
            )
            weather_data = test_service.fetch_weather()
            
            if weather_data:
                temp = weather_data['temp']
                desc = weather_data['description']
                city = weather_data['city']
                self.weather_status_var.set(f"✅ Connected: {city} - {temp}, {desc}")
                app_logger.info(f"Weather API test successful: {city}")
            else:
                self.weather_status_var.set("❌ Error: Failed to fetch weather data")
                
        except Exception as e:
            self.weather_status_var.set(f"❌ Error: {str(e)[:50]}")
            app_logger.error(f"Weather API test failed: {e}")
    
    def add_weather_icon_overlay(self):
        """Add weather icon as an image overlay with text label (helper method)"""
        if not self.weather_service or not self.weather_service.is_configured():
            messagebox.showwarning("Weather Not Configured",
                                 "Please configure weather API key and location in Settings first.")
            return
        
        try:
            # Verify weather icon can be downloaded
            icon_path = self.weather_service.get_weather_icon_path()
            
            if not icon_path or not os.path.exists(icon_path):
                messagebox.showerror("Error", "Failed to download weather icon.")
                return
            
            overlays = self.overlay_manager.get_overlays_config()
            
            # Create text label overlay "Weather Conditions:"
            from .overlays.constants import DEFAULT_TEXT_OVERLAY
            text_overlay = DEFAULT_TEXT_OVERLAY.copy()
            text_overlay['name'] = 'Weather Label'
            text_overlay['text'] = 'Weather Conditions:'
            text_overlay['anchor'] = 'Top-Right'
            text_overlay['offset_x'] = 110  # Position to left of icon
            text_overlay['offset_y'] = 20   # Vertically align near top
            text_overlay['font_size'] = 48
            text_overlay['font_style'] = 'bold'
            
            # Create image overlay with dynamic weather icon
            # Use special 'WEATHER_ICON' placeholder that resolves at render time
            from .overlays.constants import DEFAULT_IMAGE_OVERLAY
            icon_overlay = DEFAULT_IMAGE_OVERLAY.copy()
            icon_overlay['name'] = 'Weather Icon'
            icon_overlay['image_path'] = 'WEATHER_ICON'  # Special dynamic placeholder
            icon_overlay['width'] = 100
            icon_overlay['height'] = 100
            icon_overlay['anchor'] = 'Top-Right'
            icon_overlay['offset_x'] = 0   # Right edge
            icon_overlay['offset_y'] = 0   # Top edge
            
            # Add both overlays to list
            overlays.append(text_overlay)
            overlays.append(icon_overlay)
            self.config.set('overlays', overlays)
            self.overlay_manager.rebuild_overlay_list()
            
            # Select the icon overlay (last added)
            new_index = len(overlays) - 1
            self.overlay_tree.selection_set(str(new_index))
            self.selected_overlay_index = new_index
            self.overlay_manager.load_overlay_into_editor(icon_overlay)
            
            messagebox.showinfo("Success", "Weather overlays added!\n\n"
                              "Added:\n"
                              "• Text label: 'Weather Conditions:'\n"
                              "• Dynamic weather icon\n\n"
                              "✨ Icon updates with current weather conditions.\n"
                              "🔄 Refreshes every 10 minutes automatically.\n"
                              "🌤️ Supports all OpenWeatherMap condition icons.")
            
        except Exception as e:
            app_logger.error(f"Failed to add weather icon overlay: {e}")
            messagebox.showerror("Error", f"Failed to add weather icon: {str(e)}")
    
    # ===== Output Mode Methods (Delegated to OutputManager) =====
    
    def on_output_mode_change(self):
        """Delegate to output_manager"""
        self.output_manager.on_output_mode_change()
    
    def apply_output_mode(self):
        """Delegate to output_manager"""
        self.output_manager.apply_output_mode()
    
    def ensure_output_mode_started(self):
        """Delegate to output_manager"""
        self.output_manager.ensure_output_mode_started()
    
    def _push_to_output_servers(self, image_path, processed_img=None):
        """Delegate to output_manager"""
        self.output_manager.push_to_output_servers(image_path, processed_img)
    
    def copy_output_url(self):
        """Delegate to output_manager"""
        self.output_manager.copy_output_url()
    
    # ===== Discord Methods (Delegated to OutputManager) =====
    
    def save_discord_settings(self):
        """Delegate to output_manager"""
        self.output_manager.save_discord_settings()
    
    def test_discord_webhook(self):
        """Delegate to output_manager"""
        self.output_manager.test_discord_webhook()
    
    def send_test_discord_alert(self):
        """Delegate to output_manager"""
        self.output_manager.send_test_discord_alert()
    
    def on_discord_enabled_change(self):
        """Delegate to output_manager"""
        self.output_manager.on_discord_enabled_change()
    
    def on_discord_periodic_change(self):
        """Delegate to output_manager"""
        self.output_manager.on_discord_periodic_change()
    
    def on_discord_color_change(self, *args):
        """Delegate to output_manager"""
        self.output_manager.on_discord_color_change(*args)
    
    def schedule_discord_periodic(self):
        """Delegate to output_manager"""
        self.output_manager.schedule_discord_periodic()
    
    def check_discord_periodic_send(self, image_path):
        """Delegate to output_manager"""
        self.output_manager.check_discord_periodic_send(image_path)
    
    def send_discord_error(self, error_text):
        """Delegate to output_manager"""
        self.output_manager.send_discord_error(error_text)


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
