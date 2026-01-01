"""
PFR Sentinel - PySide6 Fluent UI Entry Point
Run this to launch the new modern UI

Supports command-line flags:
  python main_pyside.py                         # Normal GUI mode
  python main_pyside.py --auto-start            # Start capture automatically
  python main_pyside.py --auto-stop 3600        # Stop after 1 hour
  python main_pyside.py --headless              # No GUI (headless mode)
  python main_pyside.py --tray                  # Start minimized to system tray
"""
import sys
import os
import argparse

# Add project root to path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ui.main_window import MainWindow
from ui.theme import apply_theme
from services.logger import app_logger
from version import __version__
from app_config import APP_DISPLAY_NAME, APP_SUBTITLE


def main():
    """Launch PFR Sentinel with PySide6 Fluent UI"""
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description=f'{APP_DISPLAY_NAME} - {APP_SUBTITLE} (PySide6 UI)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python main_pyside.py                         # Normal GUI mode
  python main_pyside.py --auto-start            # Start capture automatically
  python main_pyside.py --auto-stop 3600        # Stop after 1 hour
  python main_pyside.py --auto-start --auto-stop 3600  # Capture for 1 hour then stop
  python main_pyside.py --headless              # Headless mode (no GUI)
  python main_pyside.py --tray                  # Start minimized to system tray
        """)
    
    parser.add_argument('--auto-start', action='store_true',
                       help='Automatically start camera capture on launch')
    parser.add_argument('--auto-stop', type=int, metavar='SECONDS', nargs='?', const=0,
                       help='Automatically stop capture after N seconds (0 = run until closed)')
    parser.add_argument('--headless', action='store_true',
                       help='Run without GUI - captures images based on saved config')
    parser.add_argument('--tray', action='store_true',
                       help='Start minimized to system tray (requires pystray)')
    
    args = parser.parse_args()
    
    # Headless mode - no GUI at all
    if args.headless:
        from services.headless_runner import run_headless
        success = run_headless(auto_stop=args.auto_stop)
        sys.exit(0 if success else 1)
    
    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    
    # Create application
    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationVersion(__version__)
    
    # Set default font
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    
    # Apply theme
    apply_theme()
    
    app_logger.info(f"Starting {APP_DISPLAY_NAME} v{__version__} (PySide6 UI)")
    
    # Create and show main window
    window = MainWindow()
    
    # System tray mode - start minimized to tray
    if args.tray:
        try:
            from ui.system_tray_qt import SystemTrayQt
            tray = SystemTrayQt(window, app, auto_start=args.auto_start, auto_stop=args.auto_stop)
            # Window will be shown by tray when user clicks "Show Window"
        except ImportError as e:
            app_logger.error(f"System tray mode requires pystray: {e}")
            print(f"Error: Install pystray with: pip install pystray", file=sys.stderr)
            sys.exit(1)
    else:
        window.show()
    
    # Load configuration
    window.load_config()
    
    # Auto-start capture if requested
    if args.auto_start and not args.tray:
        # Delay start to allow UI to initialize
        from PySide6.QtCore import QTimer
        QTimer.singleShot(2000, lambda: window.start_capture())
        
        # Auto-stop after timeout if specified
        if args.auto_stop and args.auto_stop > 0:
            QTimer.singleShot(args.auto_stop * 1000, lambda: window.stop_capture())
    
    # Run event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
