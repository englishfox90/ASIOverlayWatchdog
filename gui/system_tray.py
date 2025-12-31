"""
System Tray integration for PFR Sentinel
Allows running minimized to Windows system tray with context menu controls

Requires: pystray (pip install pystray)
"""
import os
import threading
import tkinter as tk
from PIL import Image
from services.logger import app_logger
from utils_paths import resource_path

# Try to import pystray - will fail gracefully if not installed
try:
    import pystray
    from pystray import MenuItem as item
    PYSTRAY_AVAILABLE = True
except ImportError:
    PYSTRAY_AVAILABLE = False
    pystray = None
    item = None


class SystemTrayApp:
    """Manages system tray icon and menu for PFR Sentinel
    
    The app runs normally but can be minimized to tray instead of taskbar.
    Right-click menu provides quick access to common actions.
    """
    
    def __init__(self, root, app, auto_start=False, auto_stop=None):
        """
        Args:
            root: Tkinter root window
            app: ModernOverlayApp instance
            auto_start: Start capture automatically
            auto_stop: Stop after N seconds
        """
        self.root = root
        self.app = app
        self.auto_start = auto_start
        self.auto_stop = auto_stop
        self.tray_icon = None
        self._tray_thread = None
        self._is_visible = True
        
        # Load icon
        self.icon_image = self._load_icon()
        
        # Setup tray icon
        self._setup_tray()
        
        # Bind window close to minimize to tray instead of exit
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_button)
        
        # Start minimized to tray
        self.root.after(100, self._minimize_to_tray)
        
        # Auto-start if requested
        if auto_start:
            self.root.after(3000, lambda: self.app.auto_start_capture(auto_stop))
    
    def _load_icon(self) -> Image.Image:
        """Load icon image for tray"""
        try:
            # Try to load from assets
            icon_path = resource_path("assets/app_icon.png")
            if os.path.exists(icon_path):
                img = Image.open(icon_path)
                # Resize to typical tray icon size
                return img.resize((64, 64), Image.LANCZOS)
        except Exception as e:
            app_logger.warning(f"Could not load tray icon: {e}")
        
        # Create a simple default icon
        img = Image.new('RGBA', (64, 64), (0, 120, 200, 255))
        return img
    
    def _setup_tray(self):
        """Setup system tray icon with menu"""
        if not PYSTRAY_AVAILABLE:
            app_logger.warning("pystray not available - system tray disabled")
            return
        
        # Create menu
        menu = pystray.Menu(
            item('Show Window', self._show_window, default=True),
            item('─────────────', None, enabled=False),  # Separator
            item('Start Capture', self._start_capture),
            item('Stop Capture', self._stop_capture),
            item('─────────────', None, enabled=False),  # Separator
            item('Status', pystray.Menu(
                item(lambda text: f"Images: {self.app.image_count if self.app else 0}", None, enabled=False),
                item(lambda text: f"Mode: {self.app.capture_mode_var.get() if self.app else 'N/A'}", None, enabled=False),
            )),
            item('─────────────', None, enabled=False),  # Separator
            item('Exit', self._exit_app)
        )
        
        # Create tray icon
        self.tray_icon = pystray.Icon(
            "PFR Sentinel",
            self.icon_image,
            "PFR Sentinel",
            menu
        )
        
        # Run tray icon in separate thread
        self._tray_thread = threading.Thread(target=self._run_tray, daemon=True)
        self._tray_thread.start()
        
        app_logger.info("System tray icon initialized")
    
    def _run_tray(self):
        """Run the tray icon (blocking - runs in thread)"""
        try:
            self.tray_icon.run()
        except Exception as e:
            app_logger.error(f"Tray icon error: {e}")
    
    def _on_close_button(self):
        """Handle window close button - minimize to tray instead of exit"""
        self._minimize_to_tray()
    
    def _minimize_to_tray(self):
        """Minimize window to system tray"""
        self._is_visible = False
        self.root.withdraw()  # Hide window
        
        # Show notification on first minimize
        if self.tray_icon and hasattr(self, '_first_minimize'):
            pass  # Don't show notification every time
        else:
            self._first_minimize = True
            if self.tray_icon:
                try:
                    self.tray_icon.notify(
                        "PFR Sentinel minimized to tray",
                        "Right-click the tray icon for options"
                    )
                except Exception:
                    pass  # Notifications not supported on all platforms
        
        app_logger.info("Window minimized to system tray")
    
    def _show_window(self, icon=None, item=None):
        """Show/restore the main window"""
        self._is_visible = True
        # Schedule GUI update on main thread
        self.root.after(0, self._do_show_window)
    
    def _do_show_window(self):
        """Actually show the window (must run on main thread)"""
        self.root.deiconify()  # Show window
        self.root.lift()  # Bring to front
        self.root.focus_force()  # Focus the window
        app_logger.info("Window restored from tray")
    
    def _start_capture(self, icon=None, item=None):
        """Start camera capture from tray menu"""
        self.root.after(0, self._do_start_capture)
    
    def _do_start_capture(self):
        """Start capture on main thread"""
        if self.app and hasattr(self.app, 'camera_controller'):
            if not self.app.is_capturing:
                self.app.camera_controller.start_camera_capture()
                app_logger.info("Capture started from tray menu")
                if self.tray_icon:
                    try:
                        self.tray_icon.notify("Capture Started", "Camera capture is now running")
                    except Exception:
                        pass
    
    def _stop_capture(self, icon=None, item=None):
        """Stop camera capture from tray menu"""
        self.root.after(0, self._do_stop_capture)
    
    def _do_stop_capture(self):
        """Stop capture on main thread"""
        if self.app and hasattr(self.app, 'camera_controller'):
            if self.app.is_capturing:
                self.app.camera_controller.stop_camera_capture()
                app_logger.info("Capture stopped from tray menu")
                if self.tray_icon:
                    try:
                        self.tray_icon.notify("Capture Stopped", "Camera capture has stopped")
                    except Exception:
                        pass
    
    def _exit_app(self, icon=None, item=None):
        """Exit the application completely"""
        app_logger.info("Exit requested from tray menu")
        
        # Stop tray icon
        if self.tray_icon:
            self.tray_icon.stop()
        
        # Close application on main thread
        self.root.after(0, self._do_exit)
    
    def _do_exit(self):
        """Perform exit on main thread"""
        # Stop any running capture
        if self.app and hasattr(self.app, 'on_close'):
            self.app.on_close()
        
        # Destroy root window
        try:
            self.root.destroy()
        except Exception:
            pass
    
    def update_tooltip(self, text: str):
        """Update the tray icon tooltip text"""
        if self.tray_icon:
            self.tray_icon.title = text
    
    def show_notification(self, title: str, message: str):
        """Show a system tray notification"""
        if self.tray_icon:
            try:
                self.tray_icon.notify(title, message)
            except Exception as e:
                app_logger.debug(f"Could not show notification: {e}")


def run_with_tray(auto_start=False, auto_stop=None):
    """
    Run PFR Sentinel with system tray integration
    
    Args:
        auto_start: Start capture automatically
        auto_stop: Stop after N seconds
    """
    if not PYSTRAY_AVAILABLE:
        raise ImportError("pystray is required for system tray mode. Install with: pip install pystray")
    
    import ttkbootstrap as ttk
    from gui.main_window import ModernOverlayApp
    
    app_logger.info("Starting PFR Sentinel in system tray mode")
    
    # Create root window with ttkbootstrap theme
    root = ttk.Window(themename="darkly")
    
    # Create main app
    app = ModernOverlayApp(root)
    
    # Create tray integration (will minimize to tray after init)
    tray_app = SystemTrayApp(root, app, auto_start=auto_start, auto_stop=auto_stop)
    
    # Store reference for access
    app.tray_app = tray_app
    
    # Run main loop
    root.mainloop()
