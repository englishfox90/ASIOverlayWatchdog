from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog
from PySide6.QtCore import Qt, Signal, QTime
from qfluentwidgets import (
    BodyLabel, CaptionLabel,
    PushButton, ComboBox, LineEdit,
    SpinBox, DoubleSpinBox,
    TimePicker
)

from ..theme.tokens import Colors, Spacing
from ..theme.icons import mdi
from ..components.cards import SettingsCard, FormRow, SwitchRow, ClickSlider, CollapsibleCard
from services.logger import app_logger
from services.config import DEFAULT_CAMERA_PROFILE

_WB_MODES = ["asi_auto", "manual", "gray_world"]
_BAYER_PATTERNS = ["BGGR", "RGGB", "GRBG", "GBRG"]

# Scheduled-capture modes. Order matches the ComboBox.
_SCHEDULE_MODES = ["always", "gated", "variable"]
_SCHEDULE_MODE_LABELS = [
    "Always capture",
    "Only within time window",
    "Different rate within time window",
]
_SCHEDULE_MODE_HINTS = {
    "always": "Capture 24/7 at the interval set above.",
    "gated": "Capture only during the window below; pause (and disconnect the camera) outside it.",
    "variable": "Capture 24/7, but use the faster rate below while inside the window — useful for night timelapses.",
}


class CameraSettingsWidget(QWidget):
    settings_changed = Signal()
    detect_cameras_clicked = Signal()
    raw16_mode_changed = Signal(bool)
    revive_camera_clicked = Signal(str)  # Saved camera name to revive via USB reset

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self._loading_config = False
        self._setup_ui()

    @property
    def _can_save(self):
        return not self._loading_config and self.main_window and hasattr(self.main_window, 'config')

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.card_gap)
        layout.addWidget(self._build_connection_card())
        layout.addWidget(self._build_exposure_card())
        layout.addWidget(self._build_auto_exposure_card())
        layout.addWidget(self._build_schedule_card())
        layout.addWidget(self._build_wb_card())
        layout.addWidget(self._build_advanced_card())
        layout.addStretch()

    def _build_connection_card(self):
        card = SettingsCard("Camera Connection", "Connect to your ZWO ASI camera")

        sdk_row = QHBoxLayout()
        sdk_row.setSpacing(Spacing.sm)
        self.sdk_path_input = LineEdit()
        self.sdk_path_input.setPlaceholderText("Path to ASICamera2.dll")
        self.sdk_path_input.textChanged.connect(self._on_sdk_path_changed)
        sdk_row.addWidget(self.sdk_path_input, 1)
        sdk_browse = PushButton("Browse")
        sdk_browse.setIcon(mdi('folder-outline'))
        sdk_browse.clicked.connect(self._browse_sdk)
        sdk_row.addWidget(sdk_browse)
        sdk_widget = QWidget()
        sdk_widget.setLayout(sdk_row)
        card.add_row("SDK Path", sdk_widget)

        camera_row = QHBoxLayout()
        camera_row.setSpacing(Spacing.sm)
        self.camera_combo = ComboBox()
        self.camera_combo.setPlaceholderText("No cameras detected")
        self.camera_combo.currentIndexChanged.connect(self._on_camera_selected)
        camera_row.addWidget(self.camera_combo, 1)
        self.detect_btn = PushButton("Detect")
        self.detect_btn.setIcon(mdi('refresh'))
        self.detect_btn.clicked.connect(self._on_detect_cameras)
        camera_row.addWidget(self.detect_btn)
        camera_widget = QWidget()
        camera_widget.setLayout(camera_row)
        card.add_row("Camera", camera_widget)

        self._missing_widget = QWidget()
        self._missing_widget.setObjectName("missingCameraWidget")
        missing_layout = QVBoxLayout(self._missing_widget)
        missing_layout.setContentsMargins(Spacing.sm, Spacing.sm, Spacing.sm, Spacing.sm)
        missing_layout.setSpacing(Spacing.xs)

        self._missing_label = BodyLabel("")
        self._missing_label.setWordWrap(True)

        self._missing_detect_btn = PushButton("Detect Again")
        self._missing_detect_btn.setIcon(mdi('refresh'))
        self._missing_detect_btn.clicked.connect(self._on_detect_cameras)

        self._missing_revive_btn = PushButton("Revive (USB Reset)")
        self._missing_revive_btn.setIcon(mdi('restart'))
        self._missing_revive_btn.setToolTip(
            "Toggle the USB device off and on in Windows Device Manager. "
            "Can recover a camera that the driver sees but can't open. "
            "Requires Administrator privileges."
        )
        self._missing_revive_btn.clicked.connect(self._on_revive_camera_clicked)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(Spacing.sm)
        btn_row.addWidget(self._missing_detect_btn)
        btn_row.addWidget(self._missing_revive_btn)
        btn_row.addStretch()

        missing_layout.addWidget(self._missing_label)
        missing_layout.addLayout(btn_row)
        self._missing_widget.hide()
        self._missing_saved_name = ''
        card.add_widget(self._missing_widget)

        return card

    def set_missing_camera_warning(self, saved_name: str, phantom_count: int = 0):
        """Pass empty saved_name to hide. phantom_count>0 shows Revive, else Detect Again."""
        if not saved_name:
            self._missing_widget.hide()
            self._missing_saved_name = ''
            self._missing_revive_btn.setEnabled(True)
            self._missing_revive_btn.setText("Revive (USB Reset)")
            return

        self._missing_saved_name = saved_name
        if phantom_count > 0:
            msg = (
                f"'{saved_name}' is stuck — the SDK detects {phantom_count} "
                "device(s) it can't open. Try Revive to perform a USB reset."
            )
            self._missing_detect_btn.hide()
            self._missing_revive_btn.show()
            bg, fg = Colors.error_bg, Colors.error_text
        else:
            msg = (
                f"'{saved_name}' is not connected. "
                "Check the USB cable, then click Detect Again to scan for cameras."
            )
            self._missing_revive_btn.hide()
            self._missing_detect_btn.show()
            bg, fg = Colors.warning_bg, Colors.warning_text

        self._missing_label.setText(msg)
        self._missing_label.setStyleSheet(f"color: {fg}; font-weight: 500;")
        self._missing_widget.setStyleSheet(f"""
            QWidget#missingCameraWidget {{
                background-color: {bg};
                border-radius: 6px;
                border: 1px solid {fg}40;
            }}
        """)
        self._missing_widget.show()

    def _on_revive_camera_clicked(self):
        if not self._missing_saved_name:
            return
        app_logger.info(
            f"User requested Revive for camera '{self._missing_saved_name}'"
        )
        self._missing_revive_btn.setEnabled(False)
        self._missing_revive_btn.setText("Resetting USB…")
        self.revive_camera_clicked.emit(self._missing_saved_name)

    def reset_revive_button(self):
        """Restore the Revive button after an async reset finishes."""
        self._missing_revive_btn.setEnabled(True)
        self._missing_revive_btn.setText("Revive (USB Reset)")

    def _build_exposure_card(self):
        card = SettingsCard("Exposure Settings", "Control exposure time and gain")

        self.exposure_spin = DoubleSpinBox()
        self.exposure_spin.setRange(0.001, 3600.0)
        self.exposure_spin.setDecimals(3)
        self.exposure_spin.setSuffix(" s")
        self.exposure_spin.setValue(1.0)
        self.exposure_spin.setToolTip("Single frame exposure time (0.001s to 3600s)")
        self.exposure_spin.valueChanged.connect(self._on_exposure_changed)
        card.add_row("Exposure", self.exposure_spin, "0.001s to 3600s")

        self.gain_spin = SpinBox()
        self.gain_spin.setRange(0, 600)
        self.gain_spin.setValue(100)
        self.gain_spin.setToolTip("Camera gain/sensitivity (higher = brighter but more noise)")
        self.gain_spin.valueChanged.connect(self._on_gain_changed)
        card.add_row("Gain", self.gain_spin, "0 to 600")

        self.interval_spin = DoubleSpinBox()
        self.interval_spin.setRange(0.1, 3600.0)
        self.interval_spin.setDecimals(1)
        self.interval_spin.setSuffix(" s")
        self.interval_spin.setValue(5.0)
        self.interval_spin.setToolTip("Time to wait between capturing frames")
        self.interval_spin.valueChanged.connect(self._on_interval_changed)
        card.add_row("Interval", self.interval_spin, "Time between captures")

        return card

    def _build_auto_exposure_card(self):
        card = CollapsibleCard("Auto Exposure", mdi('camera-iris'))

        self.auto_exp_switch = SwitchRow(
            "Enable Auto Exposure",
            "Automatically adjust exposure based on image brightness"
        )
        self.auto_exp_switch.toggled.connect(self._on_auto_exposure_changed)
        card.add_widget(self.auto_exp_switch)

        self.auto_exp_settings = QWidget()
        auto_exp_layout = QVBoxLayout(self.auto_exp_settings)
        auto_exp_layout.setContentsMargins(0, 0, 0, 0)
        auto_exp_layout.setSpacing(Spacing.input_gap)

        self.target_brightness_slider = ClickSlider(Qt.Horizontal)
        self.target_brightness_slider.setRange(20, 200)
        self.target_brightness_slider.setValue(100)
        self.target_brightness_slider.setToolTip("Target image brightness: 100")
        self.target_brightness_slider.valueChanged.connect(self._on_target_brightness_changed)
        self.target_brightness_slider.valueChanged.connect(
            lambda v: self.target_brightness_slider.setToolTip(f"Target image brightness: {v}")
        )
        auto_exp_layout.addWidget(FormRow("Target Brightness", self.target_brightness_slider, "20=dark, 200=bright"))

        self.max_exposure_spin = DoubleSpinBox()
        self.max_exposure_spin.setRange(0.1, 3600.0)
        self.max_exposure_spin.setDecimals(1)
        self.max_exposure_spin.setSuffix(" s")
        self.max_exposure_spin.setValue(30.0)
        self.max_exposure_spin.setToolTip("Maximum exposure time for auto-exposure")
        self.max_exposure_spin.valueChanged.connect(self._on_max_exposure_changed)
        auto_exp_layout.addWidget(FormRow("Max Exposure", self.max_exposure_spin, "Upper limit for auto exposure"))

        self.auto_exp_settings.hide()
        card.add_widget(self.auto_exp_settings)

        return card

    def _build_schedule_card(self):
        card = CollapsibleCard("Scheduled Capture", mdi('calendar-clock'))

        # Mode selector
        self.schedule_mode_combo = ComboBox()
        self.schedule_mode_combo.addItems(_SCHEDULE_MODE_LABELS)
        self.schedule_mode_combo.setToolTip(
            "Always: capture 24/7. "
            "Only within window: pause outside the window. "
            "Different rate within window: switch rate inside vs outside (e.g. fast at night, slow by day)."
        )
        self.schedule_mode_combo.currentIndexChanged.connect(self._on_schedule_mode_changed)
        card.add_row("Mode", self.schedule_mode_combo)

        # Per-mode description line — updated by _on_schedule_mode_changed
        self.schedule_mode_hint = CaptionLabel(_SCHEDULE_MODE_HINTS["always"])
        self.schedule_mode_hint.setStyleSheet(f"color: {Colors.text_muted}; padding: 0 8px;")
        self.schedule_mode_hint.setWordWrap(True)
        card.add_widget(self.schedule_mode_hint)

        # Time window row (shown for gated + variable)
        self.schedule_time_widget = QWidget()
        time_row = QHBoxLayout(self.schedule_time_widget)
        time_row.setContentsMargins(0, 0, 0, 0)
        time_row.setSpacing(Spacing.md)

        time_label_start = BodyLabel("Window:")
        time_label_start.setStyleSheet(f"color: {Colors.text_secondary};")
        time_row.addWidget(time_label_start)

        self.schedule_start = TimePicker()
        self.schedule_start.setTime(QTime(17, 0))
        self.schedule_start.setToolTip("Window start time (24hr format)")
        self.schedule_start.timeChanged.connect(self._on_schedule_time_changed)
        time_row.addWidget(self.schedule_start)

        time_label_to = BodyLabel("to")
        time_label_to.setStyleSheet(f"color: {Colors.text_muted};")
        time_row.addWidget(time_label_to)

        self.schedule_end = TimePicker()
        self.schedule_end.setTime(QTime(9, 0))
        self.schedule_end.setToolTip("Window end time (24hr format; crossing midnight is supported)")
        self.schedule_end.timeChanged.connect(self._on_schedule_time_changed)
        time_row.addWidget(self.schedule_end)
        time_row.addStretch()

        self.schedule_time_widget.hide()
        card.add_widget(self.schedule_time_widget)

        # Window interval row (shown for variable only)
        self.schedule_window_interval_spin = DoubleSpinBox()
        self.schedule_window_interval_spin.setRange(0.1, 3600.0)
        self.schedule_window_interval_spin.setDecimals(1)
        self.schedule_window_interval_spin.setSuffix(" s")
        self.schedule_window_interval_spin.setValue(5.0)
        self.schedule_window_interval_spin.setToolTip(
            "Time between captures while inside the window. Outside the window, the "
            "Interval above is used."
        )
        self.schedule_window_interval_spin.valueChanged.connect(self._on_schedule_window_interval_changed)
        self.schedule_window_row = FormRow(
            "In-window interval",
            self.schedule_window_interval_spin,
            "Overrides the Interval above while inside the window."
        )
        self.schedule_window_row.hide()
        card.add_widget(self.schedule_window_row)

        return card

    def _build_wb_card(self):
        card = CollapsibleCard("White Balance", mdi('palette'))

        self.wb_mode_combo = ComboBox()
        self.wb_mode_combo.addItems(_WB_MODES)
        self.wb_mode_combo.setToolTip("ASI Auto: SDK auto WB | Manual: Use R/B values | Gray World: Software algorithm")
        self.wb_mode_combo.currentIndexChanged.connect(self._on_wb_mode_changed)
        card.add_row("Mode", self.wb_mode_combo)

        self.gray_world_settings = QWidget()
        gray_world_layout = QVBoxLayout(self.gray_world_settings)
        gray_world_layout.setContentsMargins(0, 0, 0, 0)
        gray_world_layout.setSpacing(Spacing.input_gap)

        self.wb_low_spin = SpinBox()
        self.wb_low_spin.setRange(0, 49)
        self.wb_low_spin.setValue(5)
        self.wb_low_spin.setToolTip("Mask dark pixels below this percentile")
        self.wb_low_spin.valueChanged.connect(self._on_wb_gray_world_changed)
        gray_world_layout.addWidget(FormRow("Low %", self.wb_low_spin, "Mask dark pixels"))

        self.wb_high_spin = SpinBox()
        self.wb_high_spin.setRange(51, 100)
        self.wb_high_spin.setValue(95)
        self.wb_high_spin.setToolTip("Mask bright pixels above this percentile")
        self.wb_high_spin.valueChanged.connect(self._on_wb_gray_world_changed)
        gray_world_layout.addWidget(FormRow("High %", self.wb_high_spin, "Mask bright pixels"))

        wb_info = CaptionLabel("Gray World uses mid-tones to balance colors.\nBest for scenes with mixed colors.")
        wb_info.setStyleSheet(f"color: {Colors.text_muted};")
        wb_info.setWordWrap(True)
        gray_world_layout.addWidget(wb_info)

        self.gray_world_settings.hide()
        card.add_widget(self.gray_world_settings)

        self.manual_wb_settings = QWidget()
        manual_wb_layout = QVBoxLayout(self.manual_wb_settings)
        manual_wb_layout.setContentsMargins(0, 0, 0, 0)
        manual_wb_layout.setSpacing(Spacing.input_gap)

        self.wb_r_slider = ClickSlider(Qt.Horizontal)
        self.wb_r_slider.setRange(1, 99)
        self.wb_r_slider.setValue(75)
        self.wb_r_slider.setToolTip("Red channel white balance: 75")
        self.wb_r_slider.valueChanged.connect(self._on_wb_changed)
        self.wb_r_slider.valueChanged.connect(lambda v: self.wb_r_slider.setToolTip(f"Red channel white balance: {v}"))
        manual_wb_layout.addWidget(FormRow("Red", self.wb_r_slider))

        self.wb_b_slider = ClickSlider(Qt.Horizontal)
        self.wb_b_slider.setRange(1, 99)
        self.wb_b_slider.setValue(99)
        self.wb_b_slider.setToolTip("Blue channel white balance: 99")
        self.wb_b_slider.valueChanged.connect(self._on_wb_changed)
        self.wb_b_slider.valueChanged.connect(lambda v: self.wb_b_slider.setToolTip(f"Blue channel white balance: {v}"))
        manual_wb_layout.addWidget(FormRow("Blue", self.wb_b_slider))

        self.manual_wb_settings.hide()
        card.add_widget(self.manual_wb_settings)

        return card

    def _build_advanced_card(self):
        card = CollapsibleCard("Advanced Settings", mdi('tune-variant'))

        self.offset_spin = SpinBox()
        self.offset_spin.setRange(0, 255)
        self.offset_spin.setValue(20)
        self.offset_spin.setToolTip("Black level offset to prevent clipping")
        self.offset_spin.valueChanged.connect(self._on_offset_changed)
        card.add_row("Offset", self.offset_spin, "Black level (0-255)")

        self.flip_combo = ComboBox()
        self.flip_combo.addItems(["None", "Horizontal", "Vertical", "Both"])
        self.flip_combo.setToolTip("Flip/mirror the image")
        self.flip_combo.currentIndexChanged.connect(self._on_flip_changed)
        card.add_row("Flip", self.flip_combo, "Mirror image orientation")

        self.bayer_combo = ComboBox()
        self.bayer_combo.addItems(_BAYER_PATTERNS)
        self.bayer_combo.setToolTip("Color filter array pattern - BGGR for most ZWO cameras")
        self.bayer_combo.currentIndexChanged.connect(self._on_bayer_changed)
        card.add_row("Bayer Pattern", self.bayer_combo, "BGGR for most ASI cameras")

        self.raw16_switch = SwitchRow(
            "Use RAW16 Mode",
            "Capture full sensor bit depth (12-14 bit) instead of RAW8"
        )
        self.raw16_switch.toggled.connect(self._on_raw16_changed)
        self.raw16_switch.setEnabled(False)
        card.add_widget(self.raw16_switch)

        self.raw16_status = CaptionLabel("Connect camera to check RAW16 support")
        self.raw16_status.setStyleSheet(f"color: {Colors.text_secondary}; padding: 4px 8px;")
        card.add_widget(self.raw16_status)

        return card

    @staticmethod
    def _clean_camera_name(name: str) -> str:
        return name.split('(Index:')[0].strip() if '(Index:' in name else name

    def _browse_sdk(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select ASI SDK", "", "DLL Files (*.dll)")
        if file_path:
            self.sdk_path_input.setText(file_path)

    def _on_sdk_path_changed(self, text):
        if self._can_save:
            self.main_window.config.set('zwo_sdk_path', text)
            self.settings_changed.emit()

    def _on_detect_cameras(self):
        self.detect_cameras_clicked.emit()

    def _on_camera_selected(self, index):
        if not self._can_save:
            return
        camera_name = self._clean_camera_name(self.camera_combo.currentText())
        # The SDK index now rides as hidden item data (set in set_cameras), so
        # we no longer parse it out of the visible label.
        data = self.camera_combo.currentData()
        actual_index = data if isinstance(data, int) else index
        self.main_window.config.set('zwo_selected_camera', actual_index)
        self.main_window.config.set('zwo_selected_camera_name', camera_name)
        # Identity is keyed by serial, which is learned on connect. A manual
        # pick may point at a different body, so clear the stored serial — it is
        # re-learned on the next connect. Leaving a stale serial would make the
        # identity gate reject the camera the user just chose.
        self.main_window.config.set('zwo_selected_camera_serial', '')
        self.load_from_config(self.main_window.config)
        self.settings_changed.emit()

    def _save_to_camera_profile(self, **kwargs):
        if not self.main_window or not hasattr(self.main_window, 'config'):
            return
        camera_name = self._clean_camera_name(self.main_window.config.get('zwo_selected_camera_name', ''))
        serial = self.main_window.config.get('zwo_selected_camera_serial', '')
        if camera_name:
            self.main_window.config.update_camera_profile(camera_name, serial=serial, **kwargs)
        for key, value in kwargs.items():
            self.main_window.config.set(f'zwo_{key}', value)

    def _on_exposure_changed(self, value):
        if self._can_save:
            self._save_to_camera_profile(exposure_ms=value * 1000)
            self.settings_changed.emit()

    def _on_gain_changed(self, value):
        if self._can_save:
            self._save_to_camera_profile(gain=value)
            self.settings_changed.emit()

    def _on_interval_changed(self, value):
        if self._can_save:
            self.main_window.config.set('zwo_interval', value)
            self.settings_changed.emit()

    def _on_auto_exposure_changed(self, checked):
        self.auto_exp_settings.setVisible(checked)
        if self._can_save:
            self._save_to_camera_profile(auto_exposure=checked)
            self.settings_changed.emit()

    def _on_target_brightness_changed(self, value):
        if self._can_save:
            self._save_to_camera_profile(target_brightness=value)
            self.settings_changed.emit()

    def _on_max_exposure_changed(self, value):
        if self._can_save:
            self._save_to_camera_profile(max_exposure_ms=value * 1000)
            self.settings_changed.emit()

    def _on_wb_changed(self):
        if self._can_save:
            self._save_to_camera_profile(wb_r=self.wb_r_slider.value(), wb_b=self.wb_b_slider.value())
            self.settings_changed.emit()

    def _on_offset_changed(self, value):
        if self._can_save:
            self._save_to_camera_profile(offset=value)
            self.settings_changed.emit()

    def _on_flip_changed(self, index):
        if self._can_save:
            self._save_to_camera_profile(flip=index)
            self.settings_changed.emit()

    def _on_bayer_changed(self, index):
        if self._can_save:
            self._save_to_camera_profile(bayer_pattern=_BAYER_PATTERNS[index])
            self.settings_changed.emit()

    def _on_raw16_changed(self, checked):
        if not self._can_save:
            return
        dev_mode = self.main_window.config.get('dev_mode', {})
        dev_mode['use_raw16'] = checked
        self.main_window.config.set('dev_mode', dev_mode)
        self.main_window.config.save()
        self.settings_changed.emit()
        self.raw16_mode_changed.emit(checked)
        app_logger.info(
            f"RAW16 mode {'enabled' if checked else 'disabled'}: "
            f"{'Full' if checked else 'Standard 8-bit'} sensor bit depth will be used"
        )

    def _on_schedule_mode_changed(self, index):
        mode = _SCHEDULE_MODES[index] if 0 <= index < len(_SCHEDULE_MODES) else "always"
        self.schedule_mode_hint.setText(_SCHEDULE_MODE_HINTS.get(mode, ""))
        # Window row is visible for any mode that uses the window.
        self.schedule_time_widget.setVisible(mode in ("gated", "variable"))
        # In-window interval is only meaningful in variable mode.
        self.schedule_window_row.setVisible(mode == "variable")
        if self._can_save:
            self.main_window.config.set('scheduled_capture_mode', mode)
            # Keep legacy flag in sync so any external tooling still reading it
            # (migrations, pre-update installs) sees a sensible value.
            self.main_window.config.set('scheduled_capture_enabled', mode != "always")
            self.settings_changed.emit()

    def _on_schedule_time_changed(self):
        if not self._can_save:
            return
        start_time = self.schedule_start.getTime()
        end_time = self.schedule_end.getTime()
        self.main_window.config.set('scheduled_start_time', start_time.toString('HH:mm'))
        self.main_window.config.set('scheduled_end_time', end_time.toString('HH:mm'))
        self.settings_changed.emit()

    def _on_schedule_window_interval_changed(self, value):
        if self._can_save:
            self.main_window.config.set('scheduled_window_interval', value)
            self.settings_changed.emit()

    def _on_wb_mode_changed(self, index):
        mode = _WB_MODES[index]
        self.manual_wb_settings.setVisible(mode == "manual")
        self.gray_world_settings.setVisible(mode == "gray_world")
        if self._can_save:
            wb_settings = self.main_window.config.get('white_balance', {})
            wb_settings['mode'] = mode
            self.main_window.config.set('white_balance', wb_settings)
            self.settings_changed.emit()

    def _on_wb_gray_world_changed(self):
        if not self._can_save:
            return
        wb_settings = self.main_window.config.get('white_balance', {})
        wb_settings['gray_world_low_pct'] = self.wb_low_spin.value()
        wb_settings['gray_world_high_pct'] = self.wb_high_spin.value()
        self.main_window.config.set('white_balance', wb_settings)
        self.settings_changed.emit()

    def load_from_config(self, config):
        self._loading_config = True
        try:
            self.sdk_path_input.setText(config.get('zwo_sdk_path', ''))

            active_name = config.get('zwo_selected_camera_name', '') or config.get('zwo_camera_name', '')
            active_serial = config.get('zwo_selected_camera_serial', '')
            profile = (
                self.main_window.config.get_camera_profile(active_name, active_serial)
                if active_name else dict(DEFAULT_CAMERA_PROFILE)
            )

            self.exposure_spin.setValue(
                profile.get('exposure_ms', DEFAULT_CAMERA_PROFILE['exposure_ms']) / 1000.0
            )
            self.gain_spin.setValue(profile.get('gain', DEFAULT_CAMERA_PROFILE['gain']))
            self.interval_spin.setValue(config.get('zwo_interval', 5.0))

            auto_exp_enabled = config.get('zwo_auto_exposure', False)
            self.auto_exp_switch.set_checked(auto_exp_enabled)
            self.target_brightness_slider.setValue(
                profile.get('target_brightness', DEFAULT_CAMERA_PROFILE['target_brightness'])
            )
            self.max_exposure_spin.setValue(
                profile.get('max_exposure_ms', DEFAULT_CAMERA_PROFILE['max_exposure_ms']) / 1000.0
            )
            self.auto_exp_settings.setVisible(auto_exp_enabled)

            # Derive the scheduled-capture mode, accepting legacy configs that
            # only stored the boolean flag.
            mode = config.get('scheduled_capture_mode')
            if mode not in _SCHEDULE_MODES:
                mode = 'gated' if config.get('scheduled_capture_enabled', False) else 'always'
            self.schedule_mode_combo.setCurrentIndex(_SCHEDULE_MODES.index(mode))
            self.schedule_mode_hint.setText(_SCHEDULE_MODE_HINTS.get(mode, ""))

            start_h, start_m = map(int, config.get('scheduled_start_time', '17:00').split(':'))
            end_h, end_m = map(int, config.get('scheduled_end_time', '09:00').split(':'))
            self.schedule_start.setTime(QTime(start_h, start_m))
            self.schedule_end.setTime(QTime(end_h, end_m))
            self.schedule_window_interval_spin.setValue(config.get('scheduled_window_interval', 5.0))

            self.schedule_time_widget.setVisible(mode in ("gated", "variable"))
            self.schedule_window_row.setVisible(mode == "variable")

            wb_settings = config.get('white_balance', {})
            wb_mode = wb_settings.get('mode', 'asi_auto')
            if wb_mode in _WB_MODES:
                self.wb_mode_combo.setCurrentIndex(_WB_MODES.index(wb_mode))
            self.wb_low_spin.setValue(wb_settings.get('gray_world_low_pct', 5))
            self.wb_high_spin.setValue(wb_settings.get('gray_world_high_pct', 95))
            self.manual_wb_settings.setVisible(wb_mode == "manual")
            self.gray_world_settings.setVisible(wb_mode == "gray_world")

            self.wb_r_slider.setValue(profile.get('wb_r', DEFAULT_CAMERA_PROFILE['wb_r']))
            self.wb_b_slider.setValue(profile.get('wb_b', DEFAULT_CAMERA_PROFILE['wb_b']))
            self.offset_spin.setValue(profile.get('offset', DEFAULT_CAMERA_PROFILE['offset']))
            self.flip_combo.setCurrentIndex(profile.get('flip', DEFAULT_CAMERA_PROFILE['flip']))

            bayer = profile.get('bayer_pattern', DEFAULT_CAMERA_PROFILE['bayer_pattern'])
            if bayer in _BAYER_PATTERNS:
                self.bayer_combo.setCurrentIndex(_BAYER_PATTERNS.index(bayer))
        finally:
            self._loading_config = False

    def set_cameras(self, camera_list: list):
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()
        if camera_list:
            # Display the model name only — the hardware serial is the identity
            # now. The SDK index is kept as hidden item data (a starting hint for
            # connect); it shifts on hot-plug, so showing it is misleading.
            # NB: pass the index as userData, NOT positionally — ComboBox.addItem
            # is (text, icon, userData), so a bare int lands in the icon slot and
            # crashes the dropdown ('int' object has no attribute 'icon') when the
            # menu renders. currentData() also reads userData, so this is the slot
            # _on_camera_selected expects.
            for pos, entry in enumerate(camera_list):
                idx = pos
                if '(Index: ' in entry:
                    try:
                        idx = int(entry.split('(Index: ')[1].rstrip(')'))
                    except (IndexError, ValueError):
                        idx = pos
                self.camera_combo.addItem(self._clean_camera_name(entry), userData=idx)
        else:
            self.camera_combo.setPlaceholderText("No cameras detected")
        self.camera_combo.blockSignals(False)

    def set_detecting(self, is_detecting: bool):
        self.detect_btn.setEnabled(not is_detecting)
        self.detect_btn.setText("Detecting..." if is_detecting else "Detect")

    def set_capture_active(self, active: bool):
        """Disable camera selection/detection while capturing.

        Changing the selected camera does not switch the live hardware — it only
        pushes the picked camera's profile onto the running one (the
        selection/connection decoupling). Locking the picker during capture
        enforces the real workflow: Stop → pick a camera → Start.
        """
        self.camera_combo.setEnabled(not active)
        self.detect_btn.setEnabled(not active)
        self.camera_combo.setToolTip(
            "Stop capture to change cameras" if active else ""
        )

    def update_camera_capabilities(self, supports_raw16: bool, bit_depth: int):
        self._loading_config = True
        try:
            if supports_raw16:
                self.raw16_switch.setEnabled(True)
                self.raw16_status.setText(f"✓ Camera supports RAW16 ({bit_depth}-bit ADC)")
                self.raw16_status.setStyleSheet(f"color: {Colors.success_text}; padding: 4px 8px;")
                if self.main_window and hasattr(self.main_window, 'config'):
                    dev_mode = self.main_window.config.get('dev_mode', {})
                    self.raw16_switch.set_checked(dev_mode.get('use_raw16', False))
            else:
                self.raw16_switch.setEnabled(False)
                self.raw16_switch.set_checked(False)
                self.raw16_status.setText(f"✗ Camera does not support RAW16 ({bit_depth}-bit ADC, RAW8 only)")
                self.raw16_status.setStyleSheet(f"color: {Colors.text_secondary}; padding: 4px 8px;")
        finally:
            self._loading_config = False

    def reset_camera_capabilities(self):
        self._loading_config = True
        try:
            self.raw16_switch.setEnabled(False)
            self.raw16_switch.set_checked(False)
            self.raw16_status.setText("Connect camera to check RAW16 support")
            self.raw16_status.setStyleSheet(f"color: {Colors.text_secondary}; padding: 4px 8px;")
        finally:
            self._loading_config = False
