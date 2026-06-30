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
import faulthandler
import sys
import os
import argparse
import threading
import traceback

# Add project root to path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QFont, QPixmap, QIcon
from qfluentwidgets import SplashScreen, FluentIcon

from ui.main_window import MainWindow
from ui.theme import apply_theme
from services.logger import app_logger
from services.posthog_service import posthog, get_distinct_id, capture_event, is_enabled as posthog_enabled
from version import __version__
from services.app_config import APP_DISPLAY_NAME, APP_SUBTITLE


def _install_crash_handlers():
    """Install global exception handlers so crashes are always logged.

    Without these, unhandled exceptions in threads or the main loop
    print to stderr (invisible in a PyInstaller build) and the app
    dies silently with no log entry.
    """
    # Enable faulthandler so native segfaults (C extensions, Qt, numpy)
    # dump a traceback to the crash log instead of vanishing.
    crash_log_path = str(app_logger.log_dir / 'crash.log')
    _crash_file = open(crash_log_path, 'a')
    faulthandler.enable(file=_crash_file)
    # Keep reference alive so file stays open for process lifetime
    _install_crash_handlers._crash_file = _crash_file

    def _excepthook(exc_type, exc_value, exc_tb):
        msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        app_logger.error(f"UNHANDLED EXCEPTION (main thread):\n{msg}")
        try:
            from services.posthog_service import capture_error
            capture_error(exc_value, context='unhandled_main_thread')
        except Exception:
            pass

    def _threading_excepthook(args):
        msg = ''.join(traceback.format_exception(
            args.exc_type, args.exc_value, args.exc_traceback,
        ))
        app_logger.error(
            f"UNHANDLED EXCEPTION (thread '{args.thread.name}'):\n{msg}"
        )
        try:
            from services.posthog_service import capture_error
            capture_error(args.exc_value, context=f'unhandled_thread_{args.thread.name}')
        except Exception:
            pass

    sys.excepthook = _excepthook
    threading.excepthook = _threading_excepthook


def _check_admin_privileges():
    """Check if running with Administrator privileges and log appropriately."""
    try:
        import ctypes
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        is_admin = False
    
    if is_admin:
        app_logger.info("Running with Administrator privileges")
    else:
        app_logger.warning(
            "Not running as Administrator - USB device disable/enable recovery "
            "will not be available. To enable full camera recovery, run as Administrator."
        )
    return is_admin


def main():
    """Launch PFR Sentinel with PySide6 Fluent UI"""
    _install_crash_handlers()

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
    parser.add_argument('--register-startup', action='store_true',
                       help='Register the app to run on Windows logon, then exit')
    parser.add_argument('--unregister-startup', action='store_true',
                       help='Remove the Windows logon task, then exit')
    parser.add_argument('--shutdown', action='store_true',
                       help='Ask a running instance to quit cleanly, then exit '
                            '(used by the installer before an upgrade)')

    args = parser.parse_args()

    # Startup registration - perform the action and exit before any GUI work.
    # Reused by the installer so the schtasks logic lives in one place.
    if args.register_startup or args.unregister_startup:
        from services import autostart
        if args.register_startup:
            ok = autostart.enable(auto_start=True)
        else:
            ok = autostart.disable()
        sys.exit(0 if ok else 1)

    # Ask a running instance to quit cleanly (installer upgrade path). Needs a
    # Qt event loop for the local-socket round-trip, but no GUI.
    if args.shutdown:
        from PySide6.QtCore import QCoreApplication
        from services.single_instance import request_shutdown
        # Bind to a name so the application object isn't GC'd mid round-trip.
        _shutdown_app = QCoreApplication(sys.argv)
        signalled = request_shutdown()
        app_logger.info(
            "Shutdown request: "
            + ("signalled the running instance" if signalled
               else "no running instance found")
        )
        sys.exit(0 if signalled else 1)

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

    # Enforce single instance before any heavy startup work. A second launch
    # (easy to do when we're sitting in the tray) signals the running instance
    # to surface its window, then exits here. GUI-mode only — headless,
    # --shutdown, and --register-startup all exit above, so a headless instance
    # has no single-instance server and can't be asked to quit via --shutdown
    # (the auto-start path uses --tray, which does run the guard).
    from services.single_instance import SingleInstanceGuard
    instance_guard = SingleInstanceGuard()
    if instance_guard.already_running():
        app_logger.info("Exiting: PFR Sentinel is already running.")
        sys.exit(0)

    # Set default font
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    
    # Apply theme
    apply_theme()
    
    # Create splash screen FIRST (before heavy window creation)
    splash_icon = QIcon('assets/app_icon.png')
    splash = SplashScreen(splash_icon, None)
    splash.setIconSize(QSize(200, 200))
    splash.titleBar.hide()  # Hide title bar for cleaner look
    splash.resize(1400, 900)  # Match main window size
    splash.show()
    QApplication.processEvents()  # Force splash to render immediately
    
    app_logger.info(f"Starting {APP_DISPLAY_NAME} v{__version__} (PySide6 UI)")
    is_admin = _check_admin_privileges()
    if posthog_enabled():
        _did = get_distinct_id()
        posthog.set_once(distinct_id=_did, properties={
            'first_seen_version': __version__,
            'os': 'Windows',
        })
        posthog.set(distinct_id=_did, properties={
            'app_version': __version__,
            'is_admin': is_admin,
        })
    capture_event('app_started', {'version': __version__, 'is_admin': is_admin})

    # Mirror app logs to PostHog (best-effort; no-op if opted out / OTel absent).
    from services.posthog_logs import attach_posthog_log_handler
    attach_posthog_log_handler()

    # Create main window (this takes time - splash stays visible)
    window = MainWindow()
    window._is_admin = is_admin  # Pass admin status to window for UI notifications
    QApplication.processEvents()
    
    # Check if tray mode should be enabled (from config or --tray argument)
    tray_enabled = args.tray or window.config.get('tray_mode_enabled', False)

    # Start hidden in the tray ONLY when --tray was explicitly passed (the
    # autostart-on-logon task). A manual launch with tray_mode_enabled in config
    # just means "hide to tray on close" — the window must stay visible so it
    # doesn't look like the app failed to open. See closeEvent in
    # ui/main_window/lifecycle.py for the hide-to-tray-on-close behaviour.
    start_hidden = args.tray

    if tray_enabled:
        try:
            from ui.system_tray_qt import SystemTrayQt
            tray = SystemTrayQt(
                window, app, auto_start=args.auto_start, auto_stop=args.auto_stop,
                start_hidden=start_hidden,
            )
            window.system_tray = tray  # Store reference so window knows it's in tray mode

            # NOTE: --tray is a per-launch directive (the logon task passes it),
            # NOT a persistent preference — don't write tray_mode_enabled here.
            # Doing so clobbered a user's explicit "tray off" every reboot.

            if not start_hidden:
                window.show()

            splash.finish()

            # When start_hidden, the window is shown by the tray's "Show Window"
        except ImportError as e:
            app_logger.error(f"System tray mode requires pystray: {e}")
            print(f"Error: Install pystray with: pip install pystray", file=sys.stderr)
            sys.exit(1)
    else:
        # Show main window and close splash
        window.show()
        splash.finish()
    
    # When a second launch pokes us, restore and raise the window (handles the
    # tray case where it's hidden, and the minimized-taskbar case).
    def _surface_window():
        window.show()
        window.setWindowState(
            (window.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive
        )
        window.activateWindow()
        window.raise_()
        if window.system_tray is not None:
            window.system_tray._is_visible = True
    instance_guard.activate_requested.connect(_surface_window)
    # A clean-quit request — from the installer's --shutdown before an upgrade,
    # or from Windows ending the session (logoff/shutdown, or the installer's
    # Restart Manager) — must tear down for real (release the camera, save
    # config) instead of hiding to the tray, so locked files don't block an
    # upgrade and the camera is released gracefully.
    instance_guard.quit_requested.connect(window.quit_application)
    try:
        app.commitDataRequest.connect(lambda _sm: window.quit_application())
    except (AttributeError, TypeError):
        app_logger.debug(
            "commitDataRequest unavailable — session-end teardown falls back to closeEvent"
        )

    # Load configuration
    window.load_config()
    
    # Auto-start capture if requested
    if args.auto_start and not args.tray:
        # Delay start to allow UI to initialize
        QTimer.singleShot(2000, lambda: window.start_capture())
        
        # Auto-stop after timeout if specified
        if args.auto_stop and args.auto_stop > 0:
            QTimer.singleShot(args.auto_stop * 1000, lambda: window.stop_capture())
    
    # Show admin privilege warning after UI is fully visible (one-time)
    if not is_admin:
        def _show_admin_warning():
            if not window.config.get('admin_warning_dismissed', False):
                try:
                    from qfluentwidgets import InfoBar, InfoBarPosition
                    InfoBar.warning(
                        title="Not running as Administrator",
                        content=(
                            "USB camera recovery (disable/enable) requires admin privileges. "
                            "Right-click the app shortcut > Properties > Compatibility > "
                            "'Run as administrator' to enable."
                        ),
                        orient=Qt.Horizontal,
                        isClosable=True,
                        position=InfoBarPosition.TOP,
                        duration=15000,
                        parent=window
                    )
                    window.config.set('admin_warning_dismissed', True)
                    window.config.save()
                except Exception:
                    pass
        QTimer.singleShot(3000, _show_admin_warning)
    
    # Run event loop
    exit_code = app.exec()

    # Fallback force-exit watchdog for the post-event-loop cleanup below. The
    # ZWO SDK DLL can block DllMain(DLL_PROCESS_DETACH) indefinitely when a
    # capture thread is wedged in native code — sys.exit() then hangs and
    # Windows shows "Not Responding". This is a no-op if the watchdog was
    # already armed at the start of teardown (the usual case — see
    # window.quit_application / closeEvent); it only matters for an exit path
    # that reaches here without having armed it. 10 s, since teardown is done.
    from services.shutdown_watchdog import arm_force_exit
    arm_force_exit(10.0)

    capture_event('app_shutdown')
    # Best-effort flush — don't let a slow network stall the exit.
    from services.posthog_logs import shutdown_posthog_logs

    def _flush_posthog():
        shutdown_posthog_logs()  # flush queued log records first
        posthog.shutdown()

    _pht = threading.Thread(target=_flush_posthog, daemon=True)
    _pht.start()
    _pht.join(timeout=3.0)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
