"""
PFR Sentinel - Live Camera Monitoring & Overlay System for Observatories
Main entry point - Modern UI Edition
"""
# Initialize logging FIRST before any other imports that might log
from logging_config import setup_logging
setup_logging()

from app_config import APP_DISPLAY_NAME, APP_SUBTITLE
import argparse
import sys

if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description=f'{APP_DISPLAY_NAME} - {APP_SUBTITLE}',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python main.py                    # Normal GUI mode
  python main.py --auto-start       # Start camera capture automatically  
  python main.py --auto-stop 3600   # Stop capture after N seconds
  python main.py --auto-start --auto-stop 3600  # Capture for 1 hour then stop
  python main.py --auto-start --headless        # Headless mode (no GUI)
  python main.py --tray                         # Start minimized to system tray
        """)
    
    parser.add_argument('--auto-start', action='store_true',
                       help='Automatically start camera capture on launch (uses saved camera)')
    parser.add_argument('--auto-stop', type=int, metavar='SECONDS', nargs='?', const=0,
                       help='Automatically stop capture after N seconds (0 = run until closed)')
    parser.add_argument('--headless', action='store_true',
                       help='Run without GUI - captures images based on saved config')
    parser.add_argument('--tray', action='store_true',
                       help='Start minimized to system tray (Windows only)')
    
    args = parser.parse_args()
    
    # Headless mode - no GUI at all
    if args.headless:
        from services.headless_runner import run_headless
        success = run_headless(auto_stop=args.auto_stop)
        sys.exit(0 if success else 1)
    
    # System tray mode - GUI but starts minimized to tray
    if args.tray:
        try:
            from gui.system_tray import run_with_tray
            run_with_tray(auto_start=args.auto_start, auto_stop=args.auto_stop)
        except ImportError as e:
            print(f"Error: System tray mode requires pystray. Install with: pip install pystray", file=sys.stderr)
            print(f"Details: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Normal GUI mode
        from gui.main_window import main
        main(auto_start=args.auto_start, auto_stop=args.auto_stop, headless=False)
