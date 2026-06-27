"""
App Bar Component

Slim top bar: app branding on the left, then the pipeline status sprite, the
notification bell, and a single state-driven primary action button (Stop /
Start Capture / Connect Camera).

Live telemetry (Web/Discord/Camera/capture state) lives in the StatusStrip
band directly below; this bar delegates those updates to it so existing callers
keep working.
"""
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QSpacerItem
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from qfluentwidgets import PushButton, PrimaryPushButton, ToolButton, Flyout, setCustomStyleSheet

from .status_sprite import StatusSpriteWidget

import os

from ..theme.tokens import Colors, Typography, Spacing, Layout
from ..theme.icons import mdi
from ..theme.styles import paint_border_lines


class AppBar(QFrame):
    """Slim application bar: brand · sprite · bell · primary action."""

    start_clicked = Signal()
    stop_clicked = Signal()
    connect_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_capturing = False
        self._camera_connected = False
        self._action_mode = 'start'   # 'start' | 'stop' | 'connect'
        self._action_key = None       # skips redundant button rebuilds on the 1 Hz refresh
        self._start_enabled = True
        self._start_tooltip = ""
        self._status_generation = 0  # guards against stale delayed set_status calls
        self._status_strip = None    # set by the main window after construction
        self._setup_ui()

    def set_status_strip(self, strip):
        """Wire the telemetry strip this bar delegates Web/Discord/camera updates to."""
        self._status_strip = strip

    def _setup_ui(self):
        self.setFixedHeight(Layout.app_bar_height)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"AppBar {{ background-color: {Colors.bg_surface}; }}")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(Spacing.base, 0, Spacing.base, 0)
        layout.setSpacing(Spacing.md)

        # === LEFT: App branding ===
        self.app_icon = QLabel()
        self.app_icon.setFixedSize(28, 28)
        self.app_icon.setScaledContents(False)
        try:
            from services.utils_paths import resource_path
            icon_path = resource_path('assets/app_icon.png')
            if os.path.exists(icon_path):
                pixmap = QPixmap(icon_path).scaled(
                    28, 28, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.app_icon.setPixmap(pixmap)
                self.app_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        except (ImportError, FileNotFoundError, OSError):
            pass
        layout.addWidget(self.app_icon)

        self.app_name = QLabel("PFR Sentinel")
        self.app_name.setStyleSheet(f"""
            font-size: {Typography.size_subtitle}px;
            font-weight: {Typography.weight_bold};
            color: {Colors.text_primary};
            border: none;
        """)
        layout.addWidget(self.app_name)

        # Spacer
        layout.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        # Animated status sprite — visible during capture pipeline stages.
        # Fixed size: its policy is Expanding, which otherwise stretches it across
        # the whole bar so the centered animation gets lost in dead space.
        self.status_sprite = StatusSpriteWidget()
        self.status_sprite.setFixedSize(44, 44)
        self.status_sprite.hide()
        layout.addWidget(self.status_sprite, 0, Qt.AlignmentFlag.AlignVCenter)

        # Notification bell
        self.notification_btn = ToolButton(mdi('bell-outline'))
        self.notification_btn.setFixedSize(36, 36)
        self.notification_btn.setToolTip("Notifications")
        self.notification_btn.setCursor(Qt.PointingHandCursor)
        self.notification_btn.clicked.connect(self._show_notifications)
        layout.addWidget(self.notification_btn)

        # Badge overlay — parented to AppBar (not the button) so it can overflow
        # the button bounds without being clipped.
        from qfluentwidgets import InfoBadge
        self._notification_badge = InfoBadge.attension(0, self)
        self._notification_badge.hide()

        # Primary action: a native PrimaryPushButton reused for Start/Connect
        # (correct icon layout + standard radius), plus a red Stop button.
        # They toggle by visibility rather than re-skinning one button.
        self.primary_btn = PrimaryPushButton("Start Capture")
        self.primary_btn.setFixedHeight(34)
        self.primary_btn.setMinimumWidth(150)
        self.primary_btn.setCursor(Qt.PointingHandCursor)
        self.primary_btn.clicked.connect(self._on_primary_clicked)
        # Force white label so it matches the white icon (the iris accent is light
        # enough that qfluent would otherwise pick a darker text colour).
        # setCustomStyleSheet merges with the theme sheet, so icon padding + radius
        # are preserved and it survives accent/theme changes.
        _white = "PrimaryPushButton { color: white; font-weight: bold; }"
        setCustomStyleSheet(self.primary_btn, _white, _white)
        layout.addWidget(self.primary_btn)

        self.stop_btn = PushButton("Stop")
        self.stop_btn.setIcon(mdi('pause', 'white'))
        self.stop_btn.setFixedHeight(34)
        self.stop_btn.setMinimumWidth(110)
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        _stop = (
            f"PushButton {{ background-color: {Colors.error_default}; color: white; "
            f"border: none; font-weight: bold; }}"
            f"PushButton:hover {{ background-color: {Colors.error_hover}; }}"
        )
        setCustomStyleSheet(self.stop_btn, _stop, _stop)
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        self.stop_btn.hide()
        layout.addWidget(self.stop_btn)

        self.update_primary_action(False, False)

    # =========================================================================
    # PRIMARY ACTION
    # =========================================================================

    def update_primary_action(self, is_capturing: bool, camera_connected: bool):
        """Toggle/relabel the primary + stop buttons for the current app state."""
        self._is_capturing = is_capturing
        self._camera_connected = camera_connected

        # The 1 Hz status timer calls this every tick; only rebuild the buttons
        # (and re-rasterize the icon) when the state actually changes.
        key = (is_capturing, camera_connected, self._start_enabled, self._start_tooltip)
        if key == self._action_key:
            return
        self._action_key = key

        if is_capturing:
            self._action_mode = 'stop'
            self.primary_btn.hide()
            self.stop_btn.show()
            return

        self.stop_btn.hide()
        self.primary_btn.show()
        if camera_connected:
            self._action_mode = 'start'
            self.primary_btn.setText("Start Capture")
            self.primary_btn.setIcon(mdi('play', 'white'))
            self.primary_btn.setEnabled(self._start_enabled)
            self.primary_btn.setToolTip(self._start_tooltip)
        else:
            self._action_mode = 'connect'
            self.primary_btn.setText("Connect Camera")
            self.primary_btn.setIcon(mdi('camera-plus-outline', 'white'))
            self.primary_btn.setEnabled(True)
            self.primary_btn.setToolTip("")

    def _on_primary_clicked(self):
        if self._action_mode == 'connect':
            self.connect_clicked.emit()
        else:
            self.start_clicked.emit()

    def set_start_enabled(self, enabled: bool, tooltip: str = ""):
        """Enable/disable the Start action (only meaningful in the 'start' state)."""
        self._start_enabled = enabled
        self._start_tooltip = tooltip
        if self._action_mode == 'start':
            self.primary_btn.setEnabled(enabled)
            self.primary_btn.setToolTip(tooltip)

    def _push_pill_state(self):
        """Drive the strip's capture/camera pill from current capture state."""
        if not self._status_strip:
            return
        if self._is_capturing:
            self._status_strip.set_capture_state('capturing')
        elif self._camera_connected:
            self._status_strip.set_capture_state('idle', "Connected · idle")
        else:
            self._status_strip.set_capture_state('disconnected', "Disconnected")

    def set_capturing(self, capturing: bool):
        """Update button + pill for capturing mode."""
        self.update_primary_action(capturing, self._camera_connected)
        self._push_pill_state()
        if not capturing:
            self.status_sprite.hide()
            self.status_sprite.set_state(None)

    # =========================================================================
    # TELEMETRY DELEGATION (kept for existing callers)
    # =========================================================================

    def update_image_count(self, count: int):
        if self._status_strip:
            self._status_strip.set_frame_count(count)

    def set_camera_connected(self, connected: bool):
        """Window-supplied readiness flag (covers camera-available + watch mode)."""
        self._camera_connected = connected

    def update_status(self, is_capturing: bool, image_count: int,
                      camera_controller=None, live_panel=None):
        """Drive the action button, pill, and live-panel exposure progress."""
        self.update_image_count(image_count)

        self.update_primary_action(is_capturing, self._camera_connected)

        if is_capturing:
            if camera_controller and hasattr(camera_controller, 'zwo_camera'):
                zwo = camera_controller.zwo_camera
                if zwo and hasattr(zwo, 'exposure_seconds') and live_panel:
                    live_panel.update_exposure_progress(
                        zwo.exposure_seconds, getattr(zwo, 'exposure_remaining', 0)
                    )
        elif live_panel:
            live_panel.hide_progress()

        self._push_pill_state()

    def set_camera_status(self, state: str, label: str = ""):
        """Immediate camera-state feedback from the capture controller.

        state in {'connected', 'idle', 'error'}; maps onto the strip's pill.
        """
        if not self._status_strip:
            return
        if self._is_capturing:
            return  # don't clobber the live capture pill
        if state == 'connected':
            self._status_strip.set_capture_state('idle', "Connected · idle")
        elif state == 'error':
            self._status_strip.set_capture_state('disconnected', label or "Camera error")
        else:
            self._status_strip.set_capture_state('disconnected', "Disconnected")

    def set_web_status(self, enabled: bool, running: bool = False):
        if self._status_strip:
            self._status_strip.set_web(enabled, running)

    def set_discord_status(self, enabled: bool):
        if self._status_strip:
            self._status_strip.set_discord(enabled)

    # =========================================================================
    # PIPELINE STATUS SPRITE
    # =========================================================================

    def set_status(self, status: str = None):
        """Update the pipeline sprite with a specific stage (or None to hide).

        Transitions away from 'stretching'/'processing' are held ~250 ms so the
        animation is always visible even when processing is fast.
        """
        self._status_generation += 1
        gen = self._status_generation

        current = self.status_sprite._state
        if current in ('stretching', 'processing') and status in ('sending', 'waiting', None):
            from PySide6.QtCore import QTimer as _QTimer
            _QTimer.singleShot(250, lambda: self._apply_status(status, gen))
        else:
            self._apply_status(status, gen)

    def _apply_status(self, status: str, generation: int):
        if generation != self._status_generation:
            return
        if status:
            self.status_sprite.set_state(status)
            self.status_sprite.show()
        else:
            self.status_sprite.set_state(None)
            self.status_sprite.hide()

    def set_processing(self, is_processing: bool):
        """Legacy method for backward compatibility"""
        self.set_status('processing' if is_processing else None)

    # =========================================================================
    # NOTIFICATIONS
    # =========================================================================

    def _position_badge(self):
        """Place the badge at the top-right corner of the notification button."""
        btn_rect = self.notification_btn.geometry()
        badge_w = self._notification_badge.width()
        badge_h = self._notification_badge.height()
        # Center the badge on the button's top-right corner (offset outward).
        x = btn_rect.right() - badge_w // 2
        y = btn_rect.top() - badge_h // 2
        x = min(x, self.width() - badge_w)
        y = max(y, 0)
        self._notification_badge.move(x, y)
        self._notification_badge.raise_()

    def paintEvent(self, event):
        super().paintEvent(event)
        h = self.height()
        paint_border_lines(self, [(0, h - 1, self.width(), h - 1)])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._notification_badge.isVisible():
            self._position_badge()

    def showEvent(self, event):
        super().showEvent(event)
        if self._notification_badge.isVisible():
            self._position_badge()

    def update_notification_badge(self):
        """Update the notification badge count from the store."""
        from services.notification_store import get_notification_store
        count = get_notification_store().count()
        if count > 0:
            self._notification_badge.setNum(min(count, 99))
            self._notification_badge.adjustSize()
            self._notification_badge.show()
            self._position_badge()
        else:
            self._notification_badge.hide()

    def _show_notifications(self):
        """Open notification flyout anchored to the bell button."""
        from qfluentwidgets import FlyoutAnimationType
        from .notification_flyout import NotificationFlyoutView
        view = NotificationFlyoutView()
        Flyout.make(view, self.notification_btn, self.window(),
                    aniType=FlyoutAnimationType.DROP_DOWN)
