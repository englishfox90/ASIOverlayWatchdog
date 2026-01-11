"""
Main Window for PFR Sentinel
Control Console layout with navigation rail and dual-panel design
"""
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QSplitter, QFrame, QSizePolicy, QApplication
)
from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QIcon, QAction
from qfluentwidgets import (
    FluentWindow, NavigationInterface, NavigationItemPosition,
    FluentIcon, setTheme, Theme, setThemeColor, isDarkTheme,
    NavigationWidget, PushButton, ToolButton, SplitFluentWindow
)

import os
import sys

# Add parent directory for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app_config import APP_DISPLAY_NAME, APP_SUBTITLE, APP_AUTHOR
from services.config import Config
from services.logger import app_logger
from services.web_output import WebOutputServer
from version import __version__

from .theme import apply_theme, get_stylesheet
from .theme.tokens import Colors, Typography, Spacing, Layout
from .components.app_bar import AppBar
from .components.nav_rail import NavRail
from .panels.live_monitoring import LiveMonitoringPanel
from .panels.capture_settings import CaptureSettingsPanel
from .panels.output_settings import OutputSettingsPanel
from .panels.image_processing import ImageProcessingPanel
from .panels.overlay_settings import OverlaySettingsPanel
from .panels.settings_panel import SettingsPanel
from .panels.logs_panel import LogsPanel
from .controllers.image_processor import ImageProcessor


class MainWindow(QMainWindow):
    """
    Main application window with Control Console layout:
    - Top: App bar with status chips and primary action
    - Left: Live monitoring panel (always visible)
    - Right: Navigation + Inspector panels (contextual)
    """
    
    # Signals for cross-component communication
    capture_started = Signal()
    capture_stopped = Signal()
    config_changed = Signal()
    image_captured = Signal(object)  # PIL Image
    cameras_detected = Signal(list, str)  # cameras list, error string
    
    def __init__(self):
        super().__init__()
        
        # Apply theme first
        apply_theme()
        
        # Load config
        self.config = Config()
        
        # Application state
        self.is_capturing = False
        self.image_count = 0
        self.is_loading_config = False  # Prevent saves during load
        
        # Service references (will be initialized later)
        self.camera_controller = None
        self.watch_controller = None
        self.output_manager = None
        self.discord_alerts = None
        self.web_server = None
        self.rtsp_server = None
        self.weather_service = None
        self.system_tray = None  # Set by main_pyside.py when in tray mode
        
        # Initialize weather service from config
        self._init_weather_service()
        
        # Image processor (background thread for processing)
        self.image_processor = ImageProcessor(self)
        self.image_processor.set_main_window(self)
        self.image_processor.start()
        
        # Setup window
        self._setup_window()
        self._setup_ui()
        self._setup_connections()
        self._apply_styles()
        
        # Configure cursor shapes for all widgets
        from .theme import configure_widget_cursors
        configure_widget_cursors(self)
        
        # Start periodic updates
        self._start_timers()
        
        # Load config into UI panels
        self.load_config()
        
        # Auto-detect cameras after UI is ready (delay to ensure window is shown)
        QTimer.singleShot(500, self._auto_detect_cameras)
        
        # Send Discord startup notification if enabled
        QTimer.singleShot(1000, self._send_discord_startup)
        
        app_logger.info(f"PFR Sentinel v{__version__} initialized")
    
    def _setup_window(self):
        """Configure main window properties"""
        self.setWindowTitle(f"{APP_DISPLAY_NAME} v{__version__}")
        
        # Load saved geometry or set default
        geometry = self.config.get('window_geometry', '1400x900')
        try:
            w, h = map(int, geometry.lower().split('x')[:2])
            self.resize(w, h)
        except:
            self.resize(1400, 900)
        
        self.setMinimumSize(900, 600)
        
        # Set window icon
        try:
            from utils_paths import resource_path
            icon_path = resource_path('assets/app_icon.ico')
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception as e:
            app_logger.debug(f"Could not set window icon: {e}")
    
    def _setup_ui(self):
        """Build the main UI layout"""
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        
        # Main vertical layout (app bar + content)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # === APP BAR (Top) ===
        self.app_bar = AppBar(self)
        main_layout.addWidget(self.app_bar)
        
        # === CONTENT AREA (Below app bar) ===
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        main_layout.addWidget(content_widget, 1)  # Stretch factor 1
        
        # --- Navigation Rail (Left edge) ---
        self.nav_rail = NavRail(self)
        content_layout.addWidget(self.nav_rail)
        
        # --- Main Content Splitter ---
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(6)  # Wider handle for easier dragging
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
        self.live_panel.setMinimumWidth(250)  # Minimum for preview
        self.splitter.addWidget(self.live_panel)
        
        # --- Inspector Panel Stack (Right) ---
        self.inspector_stack = QStackedWidget()
        self.inspector_stack.setMinimumWidth(300)
        self.splitter.addWidget(self.inspector_stack)
        
        # Set resize cursor on splitter handle (after widgets added)
        for i in range(self.splitter.count()):
            handle = self.splitter.handle(i)
            if handle:
                handle.setCursor(Qt.SplitHCursor)
        
        # Create inspector panels
        self.capture_panel = CaptureSettingsPanel(self)
        self.output_panel = OutputSettingsPanel(self)
        self.processing_panel = ImageProcessingPanel(self)
        self.overlay_panel = OverlaySettingsPanel(self)
        self.logs_panel = LogsPanel(self)
        self.settings_panel = SettingsPanel(self)
        
        # Add to stack
        self.inspector_stack.addWidget(self.capture_panel)      # Index 0
        self.inspector_stack.addWidget(self.output_panel)       # Index 1
        self.inspector_stack.addWidget(self.processing_panel)   # Index 2
        self.inspector_stack.addWidget(self.overlay_panel)      # Index 3
        self.inspector_stack.addWidget(self.logs_panel)         # Index 4
        self.inspector_stack.addWidget(self.settings_panel)     # Index 5
        
        # Defer splitter restoration until window is shown
        # This ensures we have accurate available width
        QTimer.singleShot(100, self._restore_splitter_sizes)
        
        # Restore inspector visibility from config
        inspector_visible = self.config.get('inspector_visible', True)
        if not inspector_visible:
            self.inspector_stack.hide()
        
        # Restore last navigation section
        last_section = self.config.get('last_nav_section', 'capture')
        if last_section:
            # Set nav rail selection without emitting signal
            self.nav_rail.set_active_section(last_section)
            # Manually trigger the layout update
            self._on_nav_changed(last_section)
        else:
            # Default to Capture panel
            self.inspector_stack.setCurrentIndex(0)
    
    def _setup_connections(self):
        """Connect signals and slots"""
        # Save splitter position when moved
        self.splitter.splitterMoved.connect(self._on_splitter_moved)
        # Connect signals between components
        # Navigation
        self.nav_rail.section_changed.connect(self._on_nav_changed)
        
        # App bar actions
        self.app_bar.start_clicked.connect(self.start_capture)
        self.app_bar.stop_clicked.connect(self.stop_capture)
        
        # Config changes from panels
        self.capture_panel.settings_changed.connect(self._on_settings_changed)
        self.output_panel.settings_changed.connect(self._on_settings_changed)
        self.processing_panel.settings_changed.connect(self._on_settings_changed)
        self.overlay_panel.settings_changed.connect(self._on_settings_changed)
        self.settings_panel.settings_changed.connect(self._on_settings_changed)
        
        # RAW16 mode toggle - update camera on the fly if capturing
        self.capture_panel.raw16_mode_changed.connect(self._on_raw16_mode_changed)
        
        # Settings panel actions
        self.settings_panel.test_discord_requested.connect(self._on_test_discord)
        
        # Camera panel actions
        self.capture_panel.detect_cameras_clicked.connect(self._on_detect_cameras)
        
        # Camera detection results (from background thread)
        self.cameras_detected.connect(self._on_cameras_detected)
        
        # Output panel actions
        self.output_panel.test_discord_requested.connect(self._on_test_discord)
        
        # Image processor signals
        # Camera controller signals
        self.image_processor.processing_complete.connect(self._on_image_processed)
        self.image_processor.preview_ready.connect(self._on_preview_ready)
        self.image_processor.error_occurred.connect(self._on_processing_error)
    
    def _auto_detect_cameras(self):
        """Auto-detect cameras on startup if SDK path is configured"""
        sdk_path = self.config.get('zwo_sdk_path', '')
        if sdk_path and os.path.exists(sdk_path):
            app_logger.info("Auto-detecting cameras on startup...")
            self._on_detect_cameras()
    
    def _on_detect_cameras(self):
        """Handle camera detection request from capture panel"""
        app_logger.info("=== Camera Detection Initiated ===")
        
        sdk_path = self.config.get('zwo_sdk_path', '')
        
        if not sdk_path:
            self.capture_panel.set_detection_error("SDK path not specified")
            return
        
        if not os.path.exists(sdk_path):
            self.capture_panel.set_detection_error(f"SDK not found: {sdk_path}")
            return
        
        # Show spinner/loading state
        self.capture_panel.set_detecting(True)
        
        # Store reference to self for use in thread
        main_window = self
        
        # Run detection in thread
        import threading
        def detect_thread():
            cameras = []
            error = None
            try:
                import zwoasi as asi
                
                try:
                    asi.init(sdk_path)
                    app_logger.info(f"ASI SDK initialized: {sdk_path}")
                except Exception as e:
                    if "already" not in str(e).lower():
                        error = f"SDK init failed: {e}"
                        main_window.cameras_detected.emit([], error)
                        return
                
                num_cameras = asi.get_num_cameras()
                app_logger.info(f"SDK reports {num_cameras} camera(s)")
                
                if num_cameras == 0:
                    main_window.cameras_detected.emit([], "No cameras detected")
                    return
                
                for i in range(num_cameras):
                    try:
                        name = asi.list_cameras()[i]
                        cameras.append(f"{name} (Index: {i})")
                        app_logger.info(f"Camera {i}: {name}")
                    except:
                        cameras.append(f"Camera {i}")
                
                app_logger.info(f"Detection complete: {len(cameras)} camera(s)")
                main_window.cameras_detected.emit(cameras, "")
                
            except Exception as e:
                app_logger.error(f"Detection failed: {e}")
                main_window.cameras_detected.emit([], str(e))
        
        threading.Thread(target=detect_thread, daemon=True).start()
    
    def _on_cameras_detected(self, cameras: list, error: str):
        """Handle camera detection results (called via signal from thread)"""
        self.capture_panel.set_detecting(False)
        
        if error:
            self.capture_panel.set_detection_error(error)
            app_logger.error(f"Camera detection error: {error}")
            # Update camera chip to show error/idle
            self.app_bar.camera_chip.set_status('idle')
            self.app_bar.camera_chip.set_label('Camera')
        else:
            self.capture_panel.set_cameras(cameras)
            
            # Store detected cameras in config to prevent re-detection in start_capture
            self.config.set('available_cameras', cameras)
            
            # Update camera chip to show ready
            if cameras:
                self.app_bar.camera_chip.set_status('connected')
                self.app_bar.camera_chip.set_label('Ready')
            
            # Restore camera selection - prioritize name match over index
            # (index can change if cameras are plugged in different order)
            saved_name = self.config.get('zwo_selected_camera_name', '')
            
            self.capture_panel.camera_combo.blockSignals(True)
            
            if saved_name and cameras:
                # Try to find camera by name (name is embedded in the combo text)
                found = False
                for i, cam in enumerate(cameras):
                    # cam format: "ZWO ASI676MC (Index: 2)"
                    # saved_name could be full text or just camera name
                    if saved_name in cam or cam.split(' (Index:')[0] in saved_name:
                        self.capture_panel.camera_combo.setCurrentIndex(i)
                        # Extract actual camera index from the string (e.g., "ZWO ASI676MC (Index: 1)" -> 1)
                        # The combo box index i may differ from actual camera SDK index
                        actual_index = i  # Default to combo index
                        if '(Index: ' in cam:
                            try:
                                actual_index = int(cam.split('(Index: ')[1].rstrip(')'))
                            except (IndexError, ValueError):
                                pass
                        # Update config with the actual camera index
                        self.config.set('zwo_selected_camera', actual_index)
                        self.config.set('zwo_selected_camera_name', cam)
                        self.config.save()
                        app_logger.info(f"Restored camera by name: {cam} (SDK Index: {actual_index})")
                        found = True
                        break
                
                if not found:
                    app_logger.warning(f"Saved camera '{saved_name}' not found in detected cameras")
            
            self.capture_panel.camera_combo.blockSignals(False)
    
    def _on_test_discord(self):
        """Test Discord webhook"""
        # Get discord config from config
        discord_config = self.config.get('discord', {})
        webhook_url = discord_config.get('webhook_url', '')
        
        if not webhook_url:
            self.output_panel.set_discord_test_result(False, "Webhook URL required")
            return
        
        try:
            from services.discord_alerts import DiscordAlerts
            
            # Create alerts with proper config structure
            test_config = {
                'discord': {
                    'enabled': True,
                    'webhook_url': webhook_url,
                    'embed_color_hex': discord_config.get('embed_color_hex', '#0EA5E9'),
                    'username_override': discord_config.get('username_override', ''),
                    'avatar_url': discord_config.get('avatar_url', ''),
                    'include_latest_image': False  # Don't include image for test
                }
            }
            alerts = DiscordAlerts(test_config)
            
            # Send test message using correct method
            success = alerts.send_discord_message(
                title="🧪 Webhook Test",
                description="PFR Sentinel webhook test successful!",
                level="success"
            )
            
            if success:
                self.output_panel.set_discord_test_result(True, "Test message sent!")
                app_logger.info("Discord test message sent successfully")
            else:
                self.output_panel.set_discord_test_result(False, alerts.last_send_status)
                app_logger.warning(f"Discord test failed: {alerts.last_send_status}")
                
        except Exception as e:
            app_logger.error(f"Discord test error: {e}")
            self.output_panel.set_discord_test_result(False, str(e)[:50])
    
    def _apply_styles(self):
        """Apply stylesheet to window"""
        self.setStyleSheet(get_stylesheet())
    
    def _start_timers(self):
        """Start periodic update timers"""
        # Status update timer (fast when capturing)
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start(1000)  # 1 second default
        
        # Log polling timer
        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self._poll_logs)
        self.log_timer.start(250)  # 250ms for responsive logs
    
    # =========================================================================
    # UI STATE MANAGEMENT
    # =========================================================================
    
    def _on_splitter_moved(self, pos, index):
        """Save splitter sizes when user adjusts divider"""
        sizes = self.splitter.sizes()
        total = sum(sizes) if sizes else 1
        
        # Save both absolute sizes and ratio for better restoration
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
            # Get current available width
            available_width = self.splitter.width()
            if available_width <= 0:
                # Splitter not ready yet, use defaults
                self.splitter.setSizes([400, 500])
                return
            
            # Try ratio-based restoration first (more reliable across window sizes)
            saved_ratio = self.config.get('splitter_ratio', None)
            if saved_ratio is not None and 0.1 <= saved_ratio <= 0.9:
                # Apply ratio to current width
                left_size = int(available_width * saved_ratio)
                right_size = available_width - left_size
                
                # Ensure minimum sizes
                left_size = max(250, left_size)
                right_size = max(300, right_size)
                
                self.splitter.setSizes([left_size, right_size])
                app_logger.debug(f"Splitter restored via ratio: {saved_ratio:.2f} -> [{left_size}, {right_size}]")
                return
            
            # Fallback to absolute sizes with validation
            saved_sizes = self.config.get('splitter_sizes', None)
            if saved_sizes and isinstance(saved_sizes, list) and len(saved_sizes) >= 2:
                # Validate sizes are reasonable
                if all(s >= 100 for s in saved_sizes[:2]):
                    # Scale sizes proportionally if they don't fit current width
                    total_saved = sum(saved_sizes[:2])
                    if total_saved > available_width * 1.5 or total_saved < available_width * 0.5:
                        # Saved sizes are way off, use ratio instead
                        ratio = saved_sizes[0] / total_saved
                        left_size = int(available_width * ratio)
                        right_size = available_width - left_size
                        self.splitter.setSizes([max(250, left_size), max(300, right_size)])
                    else:
                        self.splitter.setSizes(saved_sizes)
                    return
            
            # Default: 40% left, 60% right
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
        """Handle navigation section change"""
        section_map = {
            'monitoring': -1,  # Special: hide inspector panel, show live panel
            'capture': 0,
            'output': 1,
            'processing': 2,
            'overlays': 3,  # Show overlay panel, hide live panel
            'logs': 4,
            'settings': 5,  # Settings panel (hide live panel)
        }
        
        index = section_map.get(section, 0)
        
        if index == -1:
            # Live Monitoring: hide the inspector panel, show live panel (preview only)
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
            # Normal tabs: show both panels with histogram and activity log
            self.live_panel.show()
            self.live_panel.set_preview_only(False)
            self.inspector_stack.show()
            self.inspector_stack.setCurrentIndex(index)
            self.config.set('inspector_visible', True)
            self.config.set('last_nav_section', section)
            self.config.save()
        
        app_logger.debug(f"Navigation: {section}")
    
    # =========================================================================
    # CAPTURE CONTROL
    # =========================================================================
    
    def _send_discord_startup(self):
        """Send Discord startup notification if enabled"""
        try:
            discord_config = self.config.get('discord', {})
            if not discord_config.get('enabled', False):
                return
            
            if not discord_config.get('startup_enabled', True):
                return
            
            from services.discord_alerts import DiscordAlerts
            alerts = DiscordAlerts(self.config)
            
            if alerts.is_enabled():
                alerts.send_startup_message()
                app_logger.info("Discord startup notification sent")
        except Exception as e:
            app_logger.error(f"Failed to send Discord startup notification: {e}")
    
    def _send_discord_error(self, error_msg: str):
        """Send Discord error notification if enabled"""
        try:
            discord_config = self.config.get('discord', {})
            if not discord_config.get('enabled', False):
                return
            
            # Check post_errors setting (config key is 'post_errors', not 'error_enabled')
            if not discord_config.get('post_errors', False):
                return
            
            from services.discord_alerts import DiscordAlerts
            alerts = DiscordAlerts(self.config)
            
            if alerts.is_enabled():
                alerts.send_error_message(error_msg)
                app_logger.debug("Discord error notification sent")
        except Exception as e:
            app_logger.error(f"Failed to send Discord error notification: {e}")
    
    def _on_camera_error(self, error_msg: str):
        """Handle camera error signal - update UI and send Discord notification"""
        app_logger.error(f"Camera error received: {error_msg}")
        
        # Update UI status
        if hasattr(self, 'app_bar') and self.app_bar:
            self.app_bar.camera_chip.set_status('error')
            self.app_bar.camera_chip.set_label('Camera Error')
        
        # Send Discord notification
        self._send_discord_error(f"Camera Error: {error_msg}")
    
    def _send_discord_shutdown(self):
        """Send Discord shutdown notification if enabled"""
        try:
            discord_config = self.config.get('discord', {})
            if not discord_config.get('enabled', False):
                return
            
            if not discord_config.get('post_startup_shutdown', False):
                return
            
            from services.discord_alerts import DiscordAlerts
            alerts = DiscordAlerts(self.config)
            
            if alerts.is_enabled():
                alerts.send_shutdown_message()
                app_logger.info("Discord shutdown notification sent")
        except Exception as e:
            app_logger.error(f"Failed to send Discord shutdown notification: {e}")
    
    def _send_discord_capture_started(self):
        """Send Discord capture started notification if enabled"""
        try:
            discord_config = self.config.get('discord', {})
            if not discord_config.get('enabled', False):
                return
            
            if not discord_config.get('post_startup_shutdown', False):
                return
            
            from services.discord_alerts import DiscordAlerts
            alerts = DiscordAlerts(self.config)
            
            if alerts.is_enabled():
                alerts.send_capture_started_message()
                app_logger.info("Discord capture started notification sent")
        except Exception as e:
            app_logger.error(f"Failed to send Discord capture started notification: {e}")
    
    def start_capture(self):
        """Start capture (camera or watch mode)"""
        mode = self.config.get('capture_mode', 'camera')
        
        try:
            # Ensure output servers are started if configured
            self._ensure_output_servers_started()
            
            if mode == 'camera':
                self._start_camera_capture()
                # Check if camera capture actually started successfully
                if self.camera_controller and not self.camera_controller.is_capturing:
                    app_logger.error("Camera capture failed to start")
                    return
            else:
                self._start_watch_mode()
            
            self.is_capturing = True
            self.app_bar.set_capturing(True)
            self.app_bar.set_status('waiting')  # Show waiting status until first image
            self.capture_started.emit()
            
            # Faster status updates while capturing
            self.status_timer.setInterval(200)
            
            # Send Discord capture started notification
            self._send_discord_capture_started()
            
        except Exception as e:
            app_logger.error(f"Failed to start capture: {e}")
            self.is_capturing = False
            self.app_bar.set_capturing(False)
            
            # Send Discord error notification
            self._send_discord_error(f"Failed to start capture: {e}")
    
    def stop_capture(self):
        """Stop capture"""
        try:
            # Update UI immediately for responsive feedback
            self.is_capturing = False
            self.app_bar.set_capturing(False)
            
            mode = self.config.get('capture_mode', 'camera')
            
            if mode == 'camera' and self.camera_controller:
                self.camera_controller.stop_capture()
                # Reset camera capabilities in capture settings panel
                if hasattr(self, 'capture_panel'):
                    self.capture_panel.reset_camera_capabilities()
            elif self.watch_controller:
                self.watch_controller.stop_watching()
            
            self.capture_stopped.emit()
            
            # Slower status updates when idle
            self.status_timer.setInterval(1000)
            
            # Reset camera chip to Ready (if cameras detected) or Idle
            self.app_bar.camera_chip.set_status('connected')
            self.app_bar.camera_chip.set_label('Ready')
            
            app_logger.info("Capture stopped")
            
        except Exception as e:
            app_logger.error(f"Error stopping capture: {e}")
    
    def _start_camera_capture(self):
        """Initialize and start camera capture"""
        # Import here to avoid circular imports
        from .controllers.camera_controller import CameraControllerQt
        
        if not self.camera_controller:
            self.camera_controller = CameraControllerQt(self)
            # Connect calibration signal
            self.camera_controller.calibration_status.connect(self.on_calibration_status)
            # Connect error signal to send Discord alerts
            self.camera_controller.error.connect(self._on_camera_error)
        
        self.camera_controller.start_capture()
        
        # Only update status if capture actually started successfully
        if self.camera_controller.is_capturing:
            # Update camera chip to show connected
            self.app_bar.camera_chip.set_status('connected')
            self.app_bar.camera_chip.set_label('Connected')
            app_logger.info("Camera capture started")
            
            # Update capture settings panel with camera capabilities (RAW16 support)
            if self.camera_controller.zwo_camera and hasattr(self, 'capture_panel'):
                try:
                    supports_raw16 = self.camera_controller.zwo_camera.supports_raw16
                    bit_depth = self.camera_controller.zwo_camera.sensor_bit_depth
                    self.capture_panel.update_camera_capabilities(supports_raw16, bit_depth)
                except Exception as e:
                    app_logger.debug(f"Could not update camera capabilities: {e}")
        else:
            # Connection failed - camera_controller already logged the error
            self.app_bar.camera_chip.set_status('error')
            self.app_bar.camera_chip.set_label('Connection Failed')
    
    def _start_watch_mode(self):
        """Initialize and start directory watch mode"""
        from .controllers.watch_controller import WatchControllerQt
        
        if not self.watch_controller:
            self.watch_controller = WatchControllerQt(self)
        
        watch_dir = self.config.get('watch_directory', '')
        if not watch_dir or not os.path.isdir(watch_dir):
            raise ValueError("Invalid watch directory")
        
        self.watch_controller.start_watching(watch_dir)
        app_logger.info(f"Watch mode started: {watch_dir}")
    
    # =========================================================================
    # STATUS UPDATES
    # =========================================================================
    
    def _update_status(self):
        """Periodic status update"""
        try:
            # Update app bar status
            self.app_bar.update_status(
                is_capturing=self.is_capturing,
                image_count=self.image_count,
                camera_controller=self.camera_controller,
                live_panel=self.live_panel
            )
            
            # Update live monitoring if capturing
            if self.is_capturing and self.camera_controller:
                self.live_panel.update_from_camera(self.camera_controller)
                
        except Exception as e:
            app_logger.debug(f"Status update error: {e}")
    
    def _poll_logs(self):
        """Poll log queue and update displays"""
        messages = app_logger.get_messages()
        if messages:
            # Update live monitoring mini-log
            self.live_panel.append_logs(messages)
            
            # Update logs panel
            self.logs_panel.append_logs(messages)
    
    # =========================================================================
    # SETTINGS
    # =========================================================================
    
    def _on_settings_changed(self):
        """Handle settings change from any panel"""
        # Don't save during config load
        if self.is_loading_config:
            return
        self.save_config()
        
        # Re-init weather service in case weather config changed
        self._init_weather_service()
        
        # Update ML display in live panel if ML settings changed
        ml_config = self.config.get('ml_models', {})
        ml_enabled = ml_config.get('enabled', False) and ml_config.get('show_in_preview', True)
        self.live_panel.metadata.set_ml_enabled(ml_enabled)
        
        # Update status chips based on new settings
        self._update_service_status()
        
        self.config_changed.emit()
    
    def _on_raw16_mode_changed(self, enabled: bool):
        """Handle RAW16 mode toggle from capture settings panel"""
        if not self.camera_controller or not self.camera_controller.is_capturing:
            # Not capturing - setting will apply on next capture start
            return
        
        # Camera is capturing - apply change immediately
        if self.camera_controller.zwo_camera:
            success = self.camera_controller.zwo_camera.set_raw16_mode(enabled)
            if not success:
                # Revert toggle if mode change failed
                if hasattr(self, 'capture_panel'):
                    self.capture_panel._loading_config = True
                    self.capture_panel.raw16_switch.set_checked(not enabled)
                    self.capture_panel._loading_config = False
    
    def save_config(self):
        """Save current configuration"""
        # Don't save during config load
        if self.is_loading_config:
            return
        try:
            self.config.save()
            app_logger.debug("Configuration saved")
        except Exception as e:
            app_logger.error(f"Failed to save config: {e}")
    
    def load_config(self):
        """Load configuration and update all panels"""
        self.is_loading_config = True
        try:
            self.capture_panel.load_from_config(self.config)
            self.output_panel.load_from_config(self.config)
            self.processing_panel.load_from_config(self.config)
            self.overlay_panel.load_from_config(self.config)
            self.settings_panel.load_from_config(self.config)
            
            # Update ML display in live panel based on config
            ml_config = self.config.get('ml_models', {})
            ml_enabled = ml_config.get('enabled', False) and ml_config.get('show_in_preview', True)
            self.live_panel.metadata.set_ml_enabled(ml_enabled)
            
            # Update status chips based on config
            self._update_service_status()
            
            # Re-initialize weather service with updated config
            self._init_weather_service()
            
            app_logger.debug("Configuration loaded")
        except Exception as e:
            app_logger.error(f"Failed to load config: {e}")
        finally:
            self.is_loading_config = False
    
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
    
    def _update_service_status(self):
        """Update app bar status chips based on current config"""
        # Web server status
        output_config = self.config.get('output', {})
        web_enabled = output_config.get('webserver_enabled', False)
        web_running = self.web_server is not None and self.web_server.running
        self.app_bar.set_web_status(web_enabled, web_running)
        
        # Discord status
        discord_config = self.config.get('discord', {})
        discord_enabled = discord_config.get('enabled', False)
        self.app_bar.set_discord_status(discord_enabled)
    
    # =========================================================================
    # IMAGE HANDLING
    # =========================================================================
    
    def on_image_captured(self, pil_image, metadata: dict):
        """Handle new captured image from camera or watch mode
        
        This receives RAW images and sends them to the image processor
        for auto-stretch, brightness, overlays, and saving.
        """
        self.image_count += 1
        self.app_bar.update_image_count(self.image_count)
        
        # Show status based on whether auto-stretch is enabled
        config = self.config
        auto_stretch_enabled = config.get('auto_stretch', {}).get('enabled', False)
        if auto_stretch_enabled:
            self.app_bar.set_status('stretching')
        else:
            self.app_bar.set_status('processing')
        
        # Send to image processor for processing and saving
        self.image_processor.process_and_save(pil_image, metadata)
        
        # Emit signal for other components
        self.image_captured.emit(pil_image)
    
    def _on_image_processed(self, processed_image, metadata: dict, output_path: str):
        """Handle processed image from image processor"""
        # Store for preview access
        self.last_processed_image = output_path
        self.preview_metadata = metadata
        
        # Update preview with FINAL processed image (with overlays)
        self.live_panel.update_preview(processed_image, metadata)
        
        # Check if any output servers are enabled
        config = self.config
        output_config = config.get('output', {})
        discord_config = config.get('discord', {})
        has_outputs = (
            output_config.get('webserver_enabled', False) or
            output_config.get('rtsp_enabled', False) or
            discord_config.get('enabled', False)
        )
        
        if has_outputs:
            # Show sending status briefly
            self.app_bar.set_status('sending')
            # Push to output servers (web, RTSP, Discord)
            self._push_to_output_servers(output_path, processed_image)
            
            # After sending, set to waiting if capturing
            from PySide6.QtCore import QTimer
            if self.is_capturing:
                QTimer.singleShot(300, lambda: self.app_bar.set_status('waiting'))
            else:
                QTimer.singleShot(300, lambda: self.app_bar.set_status(None))
        else:
            # No outputs, go to waiting if capturing
            if self.is_capturing:
                self.app_bar.set_status('waiting')
            else:
                self.app_bar.set_status(None)
        
        app_logger.debug(f"Image processed: {os.path.basename(output_path)}")
    
    def _on_preview_ready(self, preview_image, hist_data: dict):
        """Handle histogram data from image processor (RAW histogram)"""
        # Update histogram with pre-calculated RAW histogram data
        if hist_data:
            app_logger.debug(f"Histogram data received: r={len(hist_data.get('r', []))}, auto_exposure={hist_data.get('auto_exposure')}, target={hist_data.get('target_brightness')}")
            self.live_panel.histogram.update_from_data(hist_data)
        else:
            app_logger.warning("No histogram data received from processor")
    
    def _on_processing_error(self, error_msg: str):
        """Handle processing error"""
        self.app_bar.set_status(None)
        app_logger.error(f"Image processing error: {error_msg}")
    
    def on_calibration_status(self, is_calibrating: bool):
        """Handle calibration status change from camera
        
        Args:
            is_calibrating: True when calibration starts, False when complete
        """
        if is_calibrating:
            self.app_bar.set_status('calibrating')
            app_logger.debug("Calibration started")
        else:
            self.app_bar.set_status('waiting')
            app_logger.debug("Calibration complete")
    
    # =========================================================================
    # OUTPUT SERVER MANAGEMENT
    # =========================================================================
    
    def _ensure_output_servers_started(self):
        """Ensure output servers are started if configured (called when capture begins)"""
        output_config = self.config.get('output', {})
        
        # Start web server if enabled and not running
        if output_config.get('webserver_enabled', False):
            if not self.web_server or not self.web_server.running:
                self._start_web_server()
    
    def _start_web_server(self):
        """Start web server with current settings"""
        output_config = self.config.get('output', {})
        
        host = output_config.get('webserver_host', '127.0.0.1')
        port = output_config.get('webserver_port', 8080)
        image_path = output_config.get('webserver_path', '/latest')
        status_path = output_config.get('webserver_status_path', '/status')
        
        self.web_server = WebOutputServer(host, port, image_path, status_path)
        if self.web_server.start():
            url = self.web_server.get_url()
            status_url = self.web_server.get_status_url()
            app_logger.info(f"Web server started: {url}")
            app_logger.info(f"Status endpoint: {status_url}")
            
            # Update status chip
            self.app_bar.set_web_status(True, True)
        else:
            app_logger.error("Failed to start web server")
            self.web_server = None
            self.app_bar.set_web_status(True, False)
    
    def _stop_web_server(self):
        """Stop the web server if running"""
        if self.web_server:
            try:
                self.web_server.stop()
                self.web_server = None
                app_logger.info("Web server stopped")
                self.app_bar.set_web_status(False, False)
            except Exception as e:
                app_logger.error(f"Error stopping web server: {e}")
    
    def _push_to_output_servers(self, image_path: str, processed_img):
        """Push processed image to active output servers
        
        Args:
            image_path: Path to the saved image file
            processed_img: PIL Image object
        """
        import io
        
        try:
            # Push to web server if running
            if self.web_server and self.web_server.running:
                img_bytes = io.BytesIO()
                
                # Use configured output format and quality
                output_config = self.config.get('output', {})
                output_format = output_config.get('output_format', 'PNG').upper()
                
                if output_format in ('JPG', 'JPEG'):
                    quality = output_config.get('jpg_quality', 85)
                    processed_img.save(img_bytes, format='JPEG', quality=quality, optimize=True)
                    content_type = 'image/jpeg'
                else:
                    processed_img.save(img_bytes, format='PNG', optimize=True)
                    content_type = 'image/png'
                
                self.web_server.update_image(
                    image_path,
                    img_bytes.getvalue(),
                    metadata=self.preview_metadata,
                    content_type=content_type
                )
                app_logger.debug(f"Pushed image to web server ({content_type})")
            
            # TODO: Push to RTSP server if running
            # if self.rtsp_server and self.rtsp_server.running:
            #     self.rtsp_server.update_image(processed_img)
            
            # Send to Discord if enabled and periodic posting is on
            discord_config = self.config.get('discord', {})
            discord_enabled = discord_config.get('enabled', False)
            periodic_enabled = discord_config.get('periodic_enabled', False)
            
            if discord_enabled and periodic_enabled:
                # Post first image immediately, then based on interval
                should_post = False
                
                if not hasattr(self, 'first_image_posted_to_discord'):
                    self.first_image_posted_to_discord = False
                
                if not self.first_image_posted_to_discord:
                    should_post = True
                    app_logger.info(f"Posting first image to Discord: {image_path}")
                else:
                    # Check interval
                    interval_minutes = discord_config.get('periodic_interval_minutes', 30)
                    
                    if not hasattr(self, 'last_discord_post_time'):
                        self.last_discord_post_time = None
                    
                    if self.last_discord_post_time is None:
                        should_post = True
                    else:
                        from datetime import datetime, timedelta
                        elapsed = (datetime.now() - self.last_discord_post_time).total_seconds() / 60
                        if elapsed >= interval_minutes:
                            should_post = True
                            app_logger.info(f"Posting periodic Discord update (interval: {interval_minutes}m)")
                
                if should_post:
                    success = self._send_discord_periodic_update(image_path)
                    # Mark first image as posted only after successful send
                    if success and not self.first_image_posted_to_discord:
                        self.first_image_posted_to_discord = True
                
        except Exception as e:
            app_logger.error(f"Error pushing to output servers: {e}")
    
    def _send_discord_periodic_update(self, image_path: str):
        """Send periodic update to Discord with latest image
        
        Returns:
            bool: True if sent successfully, False otherwise
        """
        try:
            from services.discord_alerts import DiscordAlerts
            from datetime import datetime
            
            alerts = DiscordAlerts(self.config)
            
            if not alerts.is_enabled():
                return False
            
            # Build status message
            mode = "ZWO Camera" if self.is_capturing else "Directory Watch"
            count = self.image_count
            
            # Get camera info if capturing
            camera_info = ""
            if self.is_capturing and self.camera_controller and self.camera_controller.zwo_camera:
                from services.discord_alerts import format_exposure_time
                camera_settings = self.config.get('zwo_camera', {})
                exposure_seconds = self.camera_controller.zwo_camera.exposure_seconds
                gain = self.camera_controller.zwo_camera.gain
                exposure_formatted = format_exposure_time(exposure_seconds)
                camera_info = f"\n**Exposure:** {exposure_formatted}\n**Gain:** {gain}"
            
            message = f"""**Periodic Status Update**

**Mode:** {mode}
**Images Processed:** {count}{camera_info}
**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
            
            # Send with image if configured
            discord_config = self.config.get('discord', {})
            include_image = discord_config.get('include_image', True)
            
            attach_image = image_path if include_image else None
            
            success = alerts.send_discord_message(
                title=f"{self.config.get('app_name', 'PFRSentinel')} - Status Update",
                description=message,
                level="info",
                image_path=attach_image
            )
            
            if success:
                self.last_discord_post_time = datetime.now()
                app_logger.info("Discord update sent successfully")
                return True
            else:
                app_logger.warning(f"Discord update failed: {alerts.last_send_status}")
                return False
                
        except Exception as e:
            app_logger.error(f"Error sending Discord update: {e}")
            return False
    
    # =========================================================================
    # WINDOW EVENTS
    # =========================================================================
    
    def closeEvent(self, event):
        """Handle window close"""
        # If in tray mode, hide to tray instead of closing
        if self.system_tray is not None:
            event.ignore()  # Don't close the window
            self.hide()     # Hide it instead
            app_logger.debug("Window minimized to system tray")
            return
        
        # Normal close: send shutdown notification and cleanup
        # Send Discord shutdown notification first
        self._send_discord_shutdown()
        
        # Stop all timers first to prevent callbacks during shutdown
        if hasattr(self, 'status_timer') and self.status_timer:
            self.status_timer.stop()
        if hasattr(self, 'log_timer') and self.log_timer:
            self.log_timer.stop()
        
        # Save geometry
        geo = f"{self.width()}x{self.height()}"
        self.config.set('window_geometry', geo)
        
        # Save splitter sizes
        sizes = self.splitter.sizes()
        self.config.set('splitter_sizes', sizes)
        
        # Save inspector visibility
        inspector_visible = self.inspector_stack.isVisible()
        self.config.set('inspector_visible', inspector_visible)
        
        # Save all changes
        self.config.save()
        
        # Stop capture if running
        if self.is_capturing:
            self.stop_capture()
        
        # Stop image processor
        if self.image_processor:
            self.image_processor.stop()
        
        # Stop output servers
        if self.web_server:
            try:
                self.web_server.stop()
            except:
                pass
        
        if self.rtsp_server:
            try:
                self.rtsp_server.stop()
            except:
                pass
        
        # Save config
        self.save_config()
        
        app_logger.info("Application closing")
        event.accept()
        
        # Force quit the application to ensure all threads exit
        QApplication.quit()
    
    def quit_application(self):
        """Properly quit application (called from tray exit)"""
        # Stop the tray icon thread first
        if self.system_tray and hasattr(self.system_tray, 'tray_icon') and self.system_tray.tray_icon:
            try:
                self.system_tray.tray_icon.stop()
            except:
                pass
        
        # Disable tray mode to allow normal close
        self.system_tray = None
        # Close window (will trigger normal closeEvent)
        self.close()
    
    def set_tray_mode(self, enabled: bool):
        """Enable or disable system tray mode
        
        Args:
            enabled: True to enable tray mode, False to disable
        """
        if enabled and self.system_tray is None:
            # Enable tray mode - initialize system tray
            try:
                from .system_tray_qt import SystemTrayQt, PYSTRAY_AVAILABLE
                
                if not PYSTRAY_AVAILABLE:
                    app_logger.warning("System tray mode requires pystray package")
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(
                        self,
                        "Missing Dependency",
                        "System tray mode requires the 'pystray' package.\n\n"
                        "Install with: pip install pystray"
                    )
                    # Reset the setting
                    self.config.set('tray_mode_enabled', False)
                    # Update the UI switch if settings panel exists
                    if hasattr(self, 'settings_panel'):
                        self.settings_panel.tray_enabled_switch.setChecked(False)
                    return
                
                # Create system tray (hidden initially since window is already visible)
                self.system_tray = SystemTrayQt(self, QApplication.instance(), auto_start=False)
                self.system_tray._is_visible = True  # Window is currently visible
                app_logger.info("System tray enabled - window will minimize to tray on close")
                
            except Exception as e:
                app_logger.error(f"Failed to enable system tray: {e}")
                self.system_tray = None
                # Reset the setting
                self.config.set('tray_mode_enabled', False)
                if hasattr(self, 'settings_panel'):
                    self.settings_panel.tray_enabled_switch.setChecked(False)
        
        elif not enabled and self.system_tray is not None:
            # Disable tray mode - stop and remove tray
            try:
                if hasattr(self.system_tray, 'tray_icon') and self.system_tray.tray_icon:
                    self.system_tray.tray_icon.stop()
                self.system_tray = None
                app_logger.info("System tray disabled - window will close normally")
            except Exception as e:
                app_logger.error(f"Error disabling system tray: {e}")
                self.system_tray = None
