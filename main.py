"""
PFR Sentinel - Live Camera Monitoring & Overlay System for Observatories
Main entry point - Modern UI Edition
"""
# Initialize logging FIRST before any other imports that might log
from logging_config import setup_logging
setup_logging()

from gui.main_window import main
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
  python main.py --auto-stop        # Stop capture after N seconds
  python main.py --auto-start --auto-stop 3600  # Capture for 1 hour then stop
        """)
    
    parser.add_argument('--auto-start', action='store_true',
                       help='Automatically start camera capture on launch (uses saved camera)')
    parser.add_argument('--auto-stop', type=int, metavar='SECONDS', nargs='?', const=0,
                       help='Automatically stop capture after N seconds (0 = run until closed)')
    parser.add_argument('--headless', action='store_true',
                       help='Run without GUI (requires --auto-start, experimental)')
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.headless and not args.auto_start:
        print("Error: --headless requires --auto-start", file=sys.stderr)
        sys.exit(1)
    
    # Pass arguments to main
    main(auto_start=args.auto_start, auto_stop=args.auto_stop, headless=args.headless)
