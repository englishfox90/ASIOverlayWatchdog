import os
import sys
import traceback

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QSplitter, QApplication
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QIcon

# Add parent directory for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from services.app_config import APP_DISPLAY_NAME, APP_SUBTITLE, APP_AUTHOR
from services.config import Config
from services.logger import app_logger
from services.web_output import WebOutputServer
from services.ml_data_collector import init_ml_collector
from version import __version__

from ..theme import apply_theme, apply_accent_theme, get_stylesheet
from ..theme.tokens import Colors, Typography, Spacing, Layout
from ..components.app_bar import AppBar
from ..components.nav_rail import NavRail
from ..panels.live_monitoring import LiveMonitoringPanel
from ..panels.capture_settings import CaptureSettingsPanel
from ..panels.output_settings import OutputSettingsPanel
from ..panels.image_processing import ImageProcessingPanel
from ..panels.overlay_settings import OverlaySettingsPanel
from ..panels.timelapse_panel import TimelapsePanel
from ..panels.settings_panel import SettingsPanel
from ..panels.logs_panel import LogsPanel
from ..panels.allsky_settings import AllSkySettingsPanel
from ..panels.meteor_panel import MeteorPanel
from ..controllers.image_processor import ImageProcessor
from ..controllers.timelapse_controller import TimelapseController
from ..controllers.allsky_controller import AllSkyController
from ..controllers.meteor_controller import MeteorController

from .capture import _MainWindowCaptureMixin
from .output import _MainWindowOutputMixin
from .settings import _MainWindowSettingsMixin
from .lifecycle import _MainWindowLifecycleMixin


class MainWindow(
    _MainWindowCaptureMixin,
    _MainWindowOutputMixin,
    _MainWindowSettingsMixin,
    _MainWindowLifecycleMixin,
    QMainWindow,
):
    # Signals for cross-component communication
    capture_started = Signal()
    capture_stopped = Signal()
    config_changed = Signal()
    image_captured = Signal(object)  # PIL Image
    cameras_detected = Signal(list, str)  # cameras list, error string

    def __init__(self):
        super().__init__()

        apply_theme()

        self.config = Config()

        self.is_capturing = False
        self.image_count = 0
        self.is_loading_config = False  # Prevent saves during load
        self._cached_raw_image = None      # Last raw frame for instant reprocess
        self._cached_raw_metadata = None

        self.camera_controller = None
        self.watch_controller = None
        self.output_manager = None
        self.discord_alerts = None
        self.web_server = None
        self._last_capture_error = None  # Most recent capture error, for /status health
        self._capture_status_timer = None  # Periodic /status snapshot push
        self.weather_service = None
        self.timelapse_controller = None
        self.meteor_controller = None
        self.system_tray = None  # Set by main_pyside.py when in tray mode

        self._init_weather_service()

        init_ml_collector(lambda: self.config.data)

        self.image_processor = ImageProcessor(self)
        self.image_processor.set_main_window(self)
        self.image_processor.start()

        self._setup_window()
        self._setup_ui()
        self._setup_connections()
        self._apply_styles()

        from ..theme import configure_widget_cursors
        configure_widget_cursors(self)

        self._start_timers()

        # Check admin privilege once at startup — without it, the USB
        # disable/enable recovery step is dead weight. Warn the user so
        # they don't silently lose that capability.
        self._check_admin_privileges()

        self._init_update_checker()

        self.load_config()

        QTimer.singleShot(500, self._auto_detect_cameras)

        QTimer.singleShot(1000, self._send_discord_startup)

        self._validate_config_on_startup()

        app_logger.info(f"PFR Sentinel v{__version__} initialized")

    def _setup_window(self):
        self.setWindowTitle(f"{APP_DISPLAY_NAME} v{__version__}")

        geometry = self.config.get('window_geometry', '1400x900')
        try:
            w, h = map(int, geometry.lower().split('x')[:2])
            self.resize(w, h)
        except (ValueError, IndexError):
            self.resize(1400, 900)

        self.setMinimumSize(900, 600)

        try:
            from services.utils_paths import resource_path
            icon_path = resource_path('assets/app_icon.ico')
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception as e:
            app_logger.debug(f"Could not set window icon: {e}")

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # === APP BAR (Top) ===
        self.app_bar = AppBar(self)
        main_layout.addWidget(self.app_bar)

        # === CONTENT AREA (Below app bar) ===
        # Stored as instance attribute so InfoBars can parent to it (below the app bar)
        self.content_area = QWidget()
        content_widget = self.content_area
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        main_layout.addWidget(content_widget, 1)

        # --- Navigation Rail (Left edge) ---
        self.nav_rail = NavRail(self)
        content_layout.addWidget(self.nav_rail)

        # --- Main Content Splitter ---
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(6)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {Colors.border_subtle};
            }}
            QSplitter::handle:hover {{
                background-color: {Colors.accent_default};
            }}
        """)
        content_layout.addWidget(self.splitter, 1)

        # --- Live Monitoring Panel (Left) ---
        self.live_panel = LiveMonitoringPanel(self)
        self.live_panel.setMinimumWidth(250)
        self.splitter.addWidget(self.live_panel)

        # --- Inspector Panel Stack (Right) ---
        self.inspector_stack = QStackedWidget()
        self.inspector_stack.setMinimumWidth(300)
        self.splitter.addWidget(self.inspector_stack)

        for i in range(self.splitter.count()):
            handle = self.splitter.handle(i)
            if handle:
                handle.setCursor(Qt.SplitHCursor)

        self.capture_panel = CaptureSettingsPanel(self)
        self.output_panel = OutputSettingsPanel(self)
        self.processing_panel = ImageProcessingPanel(self)
        self.overlay_panel = OverlaySettingsPanel(self)
        self.timelapse_panel = TimelapsePanel(self)
        self.allsky_panel = AllSkySettingsPanel(self)
        self.meteor_panel = MeteorPanel(self)
        self.logs_panel = LogsPanel(self)
        self.settings_panel = SettingsPanel(self)

        self.timelapse_controller = TimelapseController(self)

        self.allsky_controller = AllSkyController(self)
        self.allsky_controller.status_changed.connect(self.allsky_panel.set_status)
        self.allsky_controller.quality_changed.connect(self.allsky_panel.set_quality)
        self.allsky_controller.settings_changed.connect(self._on_allsky_settings_changed)
        self.allsky_panel.settings_changed.connect(self._on_allsky_panel_changed)

        self.image_processor.set_calibration_service(
            self.allsky_controller.calibration_service,
        )

        self.meteor_controller = MeteorController(self)
        self.meteor_controller.status_updated.connect(self.meteor_panel.update_status)

        self.inspector_stack.addWidget(self.capture_panel)       # Index 0
        self.inspector_stack.addWidget(self.output_panel)        # Index 1
        self.inspector_stack.addWidget(self.processing_panel)    # Index 2
        self.inspector_stack.addWidget(self.overlay_panel)       # Index 3
        self.inspector_stack.addWidget(self.timelapse_panel)     # Index 4
        self.inspector_stack.addWidget(self.allsky_panel)        # Index 5
        self.inspector_stack.addWidget(self.meteor_panel)        # Index 6
        self.inspector_stack.addWidget(self.logs_panel)          # Index 7
        self.inspector_stack.addWidget(self.settings_panel)      # Index 8

        # Defer splitter restoration until window is shown
        # This ensures we have accurate available width
        QTimer.singleShot(100, self._restore_splitter_sizes)

        inspector_visible = self.config.get('inspector_visible', True)
        if not inspector_visible:
            self.inspector_stack.hide()

        last_section = self.config.get('last_nav_section', 'capture')
        if last_section:
            self.nav_rail.set_active_section(last_section)
            self._on_nav_changed(last_section)
        else:
            self.inspector_stack.setCurrentIndex(0)

    def _setup_connections(self):
        self.splitter.splitterMoved.connect(self._on_splitter_moved)

        self.nav_rail.section_changed.connect(self._on_nav_changed)

        self.app_bar.start_clicked.connect(self.start_capture)
        self.app_bar.stop_clicked.connect(self.stop_capture)

        self.capture_panel.settings_changed.connect(self._on_settings_changed)
        self.output_panel.settings_changed.connect(self._on_settings_changed)
        self.processing_panel.settings_changed.connect(self._on_settings_changed)
        self.overlay_panel.settings_changed.connect(self._on_settings_changed)
        self.timelapse_panel.settings_changed.connect(self._on_settings_changed)
        self.meteor_panel.settings_changed.connect(self._on_settings_changed)
        self.settings_panel.settings_changed.connect(self._on_settings_changed)

        # Reprocess last frame instantly when image processing or overlay settings change
        self.processing_panel.settings_changed.connect(self.reprocess_last_frame)
        self.overlay_panel.settings_changed.connect(self.reprocess_last_frame)
        self.settings_panel.accent_changed.connect(self.set_accent_theme)

        self.image_processor.processing_time.connect(
            self.live_panel.update_processing_time
        )

        self.image_processor.timelapse_ready.connect(
            self.timelapse_controller.on_timelapse_ready
        )
        self.timelapse_controller.status_updated.connect(
            self.timelapse_panel.update_status
        )
        self.timelapse_controller.finalizing_started.connect(
            self._on_timelapse_finalizing_started
        )
        self.timelapse_controller.finalizing_finished.connect(
            self._on_timelapse_finalizing_finished
        )
        self.timelapse_controller.youtube_upload_status_changed.connect(
            self.timelapse_panel._youtube_card.set_status
        )

        self.image_processor.detection_frame_ready.connect(
            self.meteor_controller.on_frame_ready
        )
        self.meteor_panel.detection_rejected.connect(
            self.meteor_controller.on_detection_rejected
        )
        self.meteor_panel.detection_confirmed.connect(
            self.meteor_controller.on_detection_confirmed
        )

        # RAW16 mode toggle - update camera on the fly if capturing
        self.capture_panel.raw16_mode_changed.connect(self._on_raw16_mode_changed)

        self.capture_panel.detect_cameras_clicked.connect(self._on_detect_cameras)
        self.capture_panel.revive_camera_clicked.connect(self._on_revive_camera)

        self.cameras_detected.connect(self._on_cameras_detected)

        self.output_panel.test_discord_requested.connect(self._on_test_discord)

        self.image_processor.processing_complete.connect(self._on_image_processed)
        self.image_processor.preview_ready.connect(self._on_preview_ready)
        self.image_processor.error_occurred.connect(self._on_processing_error)

    def _apply_styles(self):
        saved_accent = self.config.get('ui_accent', 'iris')
        apply_accent_theme(saved_accent)
        self.setStyleSheet(get_stylesheet())
        self.nav_rail.refresh_styles()

    def set_accent_theme(self, name: str) -> None:
        """Switch accent colour at runtime and refresh all styled widgets."""
        apply_accent_theme(name)
        self.setStyleSheet(get_stylesheet())
        if hasattr(self, 'nav_rail'):
            self.nav_rail.refresh_styles()

    def _start_timers(self):
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(1000)

        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self._poll_logs)
        self.log_timer.start(250)

        # Capture-thread watchdog: detects wedged SDK calls where the loop
        # is "running" but no frames are arriving. Runs on the main Qt
        # thread so it can't be blocked by the capture thread's wedge.
        self.watchdog_timer = QTimer(self)
        self.watchdog_timer.timeout.connect(self._check_capture_watchdog)
        self.watchdog_timer.start(60_000)  # 60s
        self._watchdog_first_fire_ts = None
        self._watchdog_ui_fatal_sent = False

    def _check_admin_privileges(self):
        """Warn once at startup if the app lacks Administrator rights.

        The USB Device Manager disable/enable recovery step requires admin.
        Previously this was only logged deep inside a failed recovery chain,
        by which point the user was already wondering why recovery didn't
        work. Surface it at startup instead.
        """
        if sys.platform != 'win32':
            return

        try:
            import ctypes
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return

        if is_admin:
            app_logger.info("✓ Running with Administrator privileges — full USB recovery available")
            return

        app_logger.warning(
            "⚠ Not running as Administrator. USB Device Manager recovery "
            "(disable/enable) will be skipped if a ZWO camera gets stuck in "
            "a bad USB state. To enable full recovery, right-click the PFR "
            "Sentinel shortcut → Properties → Compatibility → 'Run as administrator'."
        )
        self._notify(
            "Running without Admin — USB recovery is limited. See logs.",
            "warning",
        )
        try:
            self._send_discord_error(
                "Started without Administrator privileges — USB recovery is limited."
            )
        except Exception:
            pass

    # =========================================================================
    # UI STATE MANAGEMENT
    # =========================================================================

    def _on_splitter_moved(self, pos, index):
        sizes = self.splitter.sizes()
        total = sum(sizes) if sizes else 1

        if total > 0 and len(sizes) >= 2:
            ratio = sizes[0] / total
            self.config.set('splitter_sizes', sizes)
            self.config.set('splitter_ratio', ratio)

    def _restore_splitter_sizes(self):
        """Restore splitter sizes after window is shown

        Uses saved ratio as primary method, falls back to absolute sizes.
        This prevents dramatic shifts when window size differs from saved state.
        """
        try:
            available_width = self.splitter.width()
            if available_width <= 0:
                self.splitter.setSizes([400, 500])
                return

            saved_ratio = self.config.get('splitter_ratio', None)
            if saved_ratio is not None and 0.1 <= saved_ratio <= 0.9:
                left_size = int(available_width * saved_ratio)
                right_size = available_width - left_size

                left_size = max(250, left_size)
                right_size = max(300, right_size)

                self.splitter.setSizes([left_size, right_size])
                app_logger.debug(f"Splitter restored via ratio: {saved_ratio:.2f} -> [{left_size}, {right_size}]")
                return

            saved_sizes = self.config.get('splitter_sizes', None)
            if saved_sizes and isinstance(saved_sizes, list) and len(saved_sizes) >= 2:
                if all(s >= 100 for s in saved_sizes[:2]):
                    total_saved = sum(saved_sizes[:2])
                    if total_saved > available_width * 1.5 or total_saved < available_width * 0.5:
                        ratio = saved_sizes[0] / total_saved
                        left_size = int(available_width * ratio)
                        right_size = available_width - left_size
                        self.splitter.setSizes([max(250, left_size), max(300, right_size)])
                    else:
                        self.splitter.setSizes(saved_sizes)
                    return

            left_size = int(available_width * 0.4)
            right_size = available_width - left_size
            self.splitter.setSizes([left_size, right_size])

        except Exception as e:
            app_logger.warning(f"Error restoring splitter sizes: {e}")
            self.splitter.setSizes([400, 500])

    # =========================================================================
    # NAVIGATION
    # =========================================================================

    def _on_nav_changed(self, section: str):
        section_map = {
            'monitoring': -1,  # Special: hide inspector panel, show live panel
            'capture': 0,
            'output': 1,
            'processing': 2,
            'overlays': 3,
            'timelapse': 4,
            'allsky': 5,
            'meteor': 6,
            'logs': 7,
            'settings': 8,
        }

        index = section_map.get(section, 0)

        if section == 'settings':
            self.nav_rail.set_badge('settings', False)

        if index == -1:
            self.live_panel.show()
            self.live_panel.set_preview_only(True)
            self.inspector_stack.hide()
            self.config.set('inspector_visible', False)
            self.config.set('last_nav_section', section)
            self.config.save()
        elif section in ('overlays', 'settings'):
            # Overlays/Settings: hide live panel, show panel full width
            self.live_panel.hide()
            self.live_panel.set_preview_only(False)
            self.inspector_stack.show()
            self.inspector_stack.setCurrentIndex(index)
            self.config.set('inspector_visible', True)
            self.config.set('last_nav_section', section)
            self.config.save()
        else:
            self.live_panel.show()
            self.live_panel.set_preview_only(False)
            self.inspector_stack.show()
            self.inspector_stack.setCurrentIndex(index)
            self.config.set('inspector_visible', True)
            self.config.set('last_nav_section', section)
            self.config.save()

        app_logger.debug(f"Navigation: {section}")

        from services.posthog_service import capture_event
        capture_event('$pageview', {'$current_url': f'/app/{section}'})

    # =========================================================================
    # NOTIFICATIONS & TIMELAPSE CALLBACKS
    # =========================================================================

    def _notify(self, message, category='info'):
        try:
            from services.notification_store import get_notification_store
            get_notification_store().add(message, category)
        except Exception:
            pass

    def _on_timelapse_finalizing_started(self):
        self._notify("Finalizing timelapse video…", "info")

    def _on_timelapse_finalizing_finished(self, session_path: str):
        name = os.path.basename(session_path) if session_path else 'timelapse'
        self._notify(f"Timelapse saved: {name}", "info")

    def _validate_config_on_startup(self):
        try:
            warnings = self.config.validate()
            for w in warnings:
                app_logger.warning(f"Config: {w}")
                self._notify(w, "warning")
        except Exception as e:
            app_logger.debug(f"Config validation skipped: {e}")

    # =========================================================================
    # STATUS UPDATES
    # =========================================================================

    def _update_status(self):
        try:
            self.app_bar.update_status(
                is_capturing=self.is_capturing,
                image_count=self.image_count,
                camera_controller=self.camera_controller,
                live_panel=self.live_panel
            )

            if self.is_capturing and self.camera_controller:
                self.live_panel.update_from_camera(self.camera_controller)
                zwo = getattr(self.camera_controller, 'zwo_camera', None)
                sprite_state = self.app_bar.status_sprite._state
                if zwo and zwo.exposure_start_time is not None:
                    if sprite_state == 'waiting':
                        self.app_bar.set_status('capturing')
                elif sprite_state == 'capturing':
                    pass

            if self.timelapse_controller:
                recording = self.timelapse_controller.get_status().get('recording', False)
                self.nav_rail.set_badge('timelapse', recording)

            self.app_bar.update_notification_badge()

        except Exception as e:
            app_logger.debug(f"Status update error: {e}")

    def _poll_logs(self):
        try:
            messages = app_logger.get_messages()
            if messages:
                self.live_panel.append_logs(messages)
                self.logs_panel.append_logs(messages)
        except Exception as e:
            print(f"_poll_logs crashed: {traceback.format_exc()}", file=sys.stderr)
