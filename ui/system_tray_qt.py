"""
System Tray integration for PFR Sentinel (PySide6 version)
Allows running minimized to system tray with context menu controls

Requires: pystray (pip install pystray)
"""
import os
from PIL import Image
from PySide6.QtCore import QTimer, QObject, Signal
from services.logger import app_logger
from utils_paths import resource_path

# Try to import pystray
try:
    import pystray
    from pystray import MenuItem as item
    PYSTRAY_AVAILABLE = True
except ImportError:
    PYSTRAY_AVAILABLE = False
    pystray = None
    item = None


class SystemTrayQt(QObject):
    """System tray integration for PySide6 UI
    
    Allows minimizing the app to system tray instead of taskbar.
    Right-click menu provides quick access to common actions.
    """
    
    # Signals for thread-safe communication from tray to main thread
    show_window_signal = Signal()
    hide_window_signal = Signal()
    start_capture_signal = Signal()
    stop_capture_signal = Signal()
    exit_app_signal = Signal()
    
    def __init__(self, window, app, auto_start=False, auto_stop=None):
        """
        Args:
            window: MainWindow instance
            app: QApplication instance
            auto_start: Start capture automatically
            auto_stop: Stop after N seconds
        """
        super().__init__()
        
        if not PYSTRAY_AVAILABLE:
            raise ImportError("pystray is not installed")
        
        self.window = window
        self.app = app
        self.auto_start = auto_start
        self.auto_stop = auto_stop
        self.tray_icon = None
        self._is_visible = False
        
        # Connect signals to slots
        self.show_window_signal.connect(self._do_show_window)
        self.hide_window_signal.connect(self._do_hide_window)
        self.start_capture_signal.connect(self._do_start_capture)
        self.stop_capture_signal.connect(self._do_stop_capture)
        self.exit_app_signal.connect(self._do_exit_app)
        
        # Load icon
        self.icon_image = self._load_icon()
        
        # Setup tray icon
        self._setup_tray()
        
        # Start minimized to tray
        self.window.hide()
        
        # Auto-start capture if requested
        if auto_start:
            QTimer.singleShot(3000, self._auto_start_capture)
    
    def _load_icon(self) -> Image.Image:
        """Load icon image for tray"""
        try:
            # Try to load from assets
            icon_path = resource_path("assets/app_icon.png")
            if os.path.exists(icon_path):
                img = Image.open(icon_path)
                return img.resize((64, 64), Image.LANCZOS)
        except Exception as e:
            app_logger.warning(f"Could not load tray icon: {e}")
        
        # Create a simple default icon
        img = Image.new('RGBA', (64, 64), (0, 120, 200, 255))
        return img
    
    def _setup_tray(self):
        """Setup system tray icon with menu"""
        # Create menu with proper visible/enabled state
        def create_menu():
            return pystray.Menu(
                item('Show Window', self._show_window, default=True, visible=lambda _: not self._is_visible),
                item('Hide Window', self._hide_window, visible=lambda _: self._is_visible),
                pystray.Menu.SEPARATOR,
                item('Start Capture', self._start_capture, enabled=lambda _: not self.window.is_capturing),
                item('Stop Capture', self._stop_capture, enabled=lambda _: self.window.is_capturing),
                pystray.Menu.SEPARATOR,
                item('Exit', self._exit_app)
            )
        
        # Create tray icon
        self.tray_icon = pystray.Icon(
            "PFRSentinel",
            self.icon_image,
            "PFR Sentinel - All-Sky Camera Monitor",
            menu=create_menu()
        )
        
        # Run tray icon in background thread (pystray blocks, so must be in thread)
        import threading
        self._tray_thread = threading.Thread(target=self.tray_icon.run, daemon=True)
        self._tray_thread.start()
        
        app_logger.info("System tray initialized - app running in background")
    
    def _show_window(self, icon=None, item=None):
        """Show the main window"""
        self.show_window_signal.emit()
        app_logger.debug("Window restore requested from tray")
    
    def _do_show_window(self):
        """Actually show the window (called from Qt main thread via signal)"""
        self.window.show()
        self.window.activateWindow()
        self.window.raise_()
        self._is_visible = True
    
    def _hide_window(self, icon=None, item=None):
        """Hide the main window to tray"""
        self.hide_window_signal.emit()
    
    def _do_hide_window(self):
        """Actually hide the window"""
        self.window.hide()
        self._is_visible = False
        app_logger.debug("Window minimized to tray")
    
    def _start_capture(self, icon=None, item=None):
        """Start camera capture"""
        self.start_capture_signal.emit()
    
    def _do_start_capture(self):
        """Actually start capture (from Qt thread)"""
        try:
            if not self.window.is_capturing:
                self.window.start_capture()
                app_logger.info("Capture started from tray menu")
        except Exception as e:
            app_logger.error(f"Error starting capture from tray: {e}")
    
    def _stop_capture(self, icon=None, item=None):
        """Stop camera capture"""
        self.stop_capture_signal.emit()
    
    def _do_stop_capture(self):
        """Actually stop capture (from Qt thread)"""
        try:
            if self.window.is_capturing:
                self.window.stop_capture()
                app_logger.info("Capture stopped from tray menu")
        except Exception as e:
            app_logger.error(f"Error stopping capture from tray: {e}")
    
    def _auto_start_capture(self):
        """Auto-start capture after delay"""
        try:
            self.window.start_capture()
            app_logger.info("Auto-started capture from tray")
            
            # Auto-stop if requested
            if self.auto_stop and self.auto_stop > 0:
                QTimer.singleShot(self.auto_stop * 1000, self._auto_stop_capture)
        except Exception as e:
            app_logger.error(f"Error auto-starting capture: {e}")
    
    def _auto_stop_capture(self):
        """Auto-stop capture"""
        try:
            self.window.stop_capture()
            app_logger.info(f"Auto-stopped capture after {self.auto_stop}s")
        except Exception as e:
            app_logger.error(f"Error auto-stopping capture: {e}")
    
    def _exit_app(self, icon=None, item=None):
        """Exit the application"""
        app_logger.info("Exiting from system tray")
        self.exit_app_signal.emit()
    
    def _do_exit_app(self):
        """Actually exit the app (from Qt thread)"""
        
        # Stop tray icon
        if self.tray_icon:
            self.tray_icon.stop()
        
        # Properly quit application (will trigger shutdown notifications)
        self.window.quit_application()
