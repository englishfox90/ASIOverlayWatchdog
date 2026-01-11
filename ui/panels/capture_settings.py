"""
Capture Settings Panel
Settings for Directory Watch and ZWO Camera capture modes
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QFileDialog, QSizePolicy, QStackedWidget
)
from PySide6.QtCore import Qt, Signal, QTime
from qfluentwidgets import (
    CardWidget, SubtitleLabel, BodyLabel, CaptionLabel,
    PushButton, PrimaryPushButton, ComboBox, LineEdit,
    SpinBox, DoubleSpinBox, SwitchButton,
    SegmentedWidget, FluentIcon, InfoBar, InfoBarPosition,
    TimePicker
)

import os

from ..theme.tokens import Colors, Typography, Spacing, Layout
from ..components.cards import SettingsCard, FormRow, SwitchRow, CollapsibleCard, ClickSlider


class CaptureSettingsPanel(QScrollArea):
    """
    Capture settings panel with:
    - Mode selector (Directory Watch / ZWO Camera)
    - Directory watch settings
    - ZWO Camera settings
    """
    
    settings_changed = Signal()
    detect_cameras_clicked = Signal()
    raw16_mode_changed = Signal(bool)  # Emitted when user toggles RAW16 mode
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self._loading_config = True  # Block signals during init
        self._setup_ui()
        self._loading_config = False
    
    def _setup_ui(self):
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(f"""
            QScrollArea {{
                background-color: {Colors.bg_app};
                border: none;
            }}
        """)
        
        # Content widget
        content = QWidget()
        self.setWidget(content)
        
        layout = QVBoxLayout(content)
        layout.setContentsMargins(Spacing.base, Spacing.base, Spacing.base, Spacing.base)
        layout.setSpacing(Spacing.card_gap)
        
        # === MODE SELECTOR ===
        mode_card = CardWidget()
        mode_layout = QVBoxLayout(mode_card)
        mode_layout.setContentsMargins(Spacing.card_padding, Spacing.card_padding,
                                       Spacing.card_padding, Spacing.card_padding)
        mode_layout.setSpacing(Spacing.md)
        
        mode_header = SubtitleLabel("Capture Mode")
        mode_header.setStyleSheet(f"color: {Colors.text_primary};")
        mode_layout.addWidget(mode_header)
        
        mode_desc = CaptionLabel("Choose between monitoring a directory for new images or capturing directly from a ZWO camera.")
        mode_desc.setStyleSheet(f"color: {Colors.text_muted};")
        mode_desc.setWordWrap(True)
        mode_layout.addWidget(mode_desc)
        
        # Segmented control for mode
        self.mode_selector = SegmentedWidget()
        self.mode_selector.addItem('watch', 'Directory Watch', onClick=lambda: self._on_mode_changed('watch'))
        self.mode_selector.addItem('camera', 'ZWO Camera', onClick=lambda: self._on_mode_changed('camera'))
        self.mode_selector.setCurrentItem('camera')
        mode_layout.addWidget(self.mode_selector)
        
        layout.addWidget(mode_card)
        
        # === MODE-SPECIFIC SETTINGS STACK ===
        self.settings_stack = QStackedWidget()
        
        # Directory Watch Settings
        self.watch_widget = self._create_watch_settings()
        self.settings_stack.addWidget(self.watch_widget)
        
        # ZWO Camera Settings
        self.camera_widget = self._create_camera_settings()
        self.settings_stack.addWidget(self.camera_widget)
        
        # Default to camera mode
        self.settings_stack.setCurrentIndex(1)
        
        layout.addWidget(self.settings_stack, 1)
        
        # Spacer at bottom
        layout.addStretch()
    
    def _on_mode_changed(self, mode: str):
        """Handle mode selector change"""
        if mode == 'watch':
            self.settings_stack.setCurrentIndex(0)
        else:
            self.settings_stack.setCurrentIndex(1)
        
        # Save to config
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('capture_mode', mode)
            self.settings_changed.emit()
    
    def _create_watch_settings(self) -> QWidget:
        """Create directory watch settings widget"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.card_gap)
        
        # Watch Directory Card
        dir_card = SettingsCard(
            "Watch Directory",
            "Monitor this folder for new images to process"
        )
        
        # Directory path with browse button
        dir_row = QHBoxLayout()
        dir_row.setSpacing(Spacing.sm)
        
        self.watch_dir_input = LineEdit()
        self.watch_dir_input.setPlaceholderText("Select directory to watch...")
        self.watch_dir_input.textChanged.connect(self._on_watch_dir_changed)
        dir_row.addWidget(self.watch_dir_input, 1)
        
        browse_btn = PushButton("Browse")
        browse_btn.setIcon(FluentIcon.FOLDER)
        browse_btn.clicked.connect(self._browse_watch_dir)
        dir_row.addWidget(browse_btn)
        
        dir_widget = QWidget()
        dir_widget.setLayout(dir_row)
        dir_card.add_widget(dir_widget)
        
        # Recursive option
        self.recursive_switch = SwitchRow(
            "Include Subfolders",
            "Watch subdirectories recursively"
        )
        self.recursive_switch.toggled.connect(self._on_recursive_changed)
        dir_card.add_widget(self.recursive_switch)
        
        layout.addWidget(dir_card)
        layout.addStretch()
        
        return widget
    
    def _create_camera_settings(self) -> QWidget:
        """Create ZWO camera settings widget"""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.card_gap)
        
        # === SDK & CONNECTION ===
        connection_card = SettingsCard(
            "Camera Connection",
            "Connect to your ZWO ASI camera"
        )
        
        # SDK Path
        sdk_row = QHBoxLayout()
        sdk_row.setSpacing(Spacing.sm)
        
        self.sdk_path_input = LineEdit()
        self.sdk_path_input.setPlaceholderText("Path to ASICamera2.dll")
        self.sdk_path_input.textChanged.connect(self._on_sdk_path_changed)
        sdk_row.addWidget(self.sdk_path_input, 1)
        
        sdk_browse = PushButton("Browse")
        sdk_browse.setIcon(FluentIcon.FOLDER)
        sdk_browse.clicked.connect(self._browse_sdk)
        sdk_row.addWidget(sdk_browse)
        
        sdk_widget = QWidget()
        sdk_widget.setLayout(sdk_row)
        connection_card.add_row("SDK Path", sdk_widget)
        
        # Camera selection
        camera_row = QHBoxLayout()
        camera_row.setSpacing(Spacing.sm)
        
        self.camera_combo = ComboBox()
        self.camera_combo.setPlaceholderText("No cameras detected")
        self.camera_combo.currentIndexChanged.connect(self._on_camera_selected)
        camera_row.addWidget(self.camera_combo, 1)
        
        self.detect_btn = PushButton("Detect")
        self.detect_btn.setIcon(FluentIcon.SYNC)
        self.detect_btn.clicked.connect(self._on_detect_cameras)
        camera_row.addWidget(self.detect_btn)
        
        camera_widget = QWidget()
        camera_widget.setLayout(camera_row)
        connection_card.add_row("Camera", camera_widget)
        
        layout.addWidget(connection_card)
        
        # === EXPOSURE SETTINGS ===
        exposure_card = SettingsCard(
            "Exposure Settings",
            "Control exposure time and gain"
        )
        
        # Exposure time
        self.exposure_spin = DoubleSpinBox()
        self.exposure_spin.setRange(0.001, 3600.0)
        self.exposure_spin.setDecimals(3)
        self.exposure_spin.setSuffix(" s")
        self.exposure_spin.setValue(1.0)
        self.exposure_spin.setToolTip("Single frame exposure time (0.001s to 3600s)")
        self.exposure_spin.valueChanged.connect(self._on_exposure_changed)
        exposure_card.add_row("Exposure", self.exposure_spin, "0.001s to 3600s")
        
        # Gain
        self.gain_spin = SpinBox()
        self.gain_spin.setRange(0, 600)
        self.gain_spin.setValue(100)
        self.gain_spin.setToolTip("Camera gain/sensitivity (higher = brighter but more noise)")
        self.gain_spin.valueChanged.connect(self._on_gain_changed)
        exposure_card.add_row("Gain", self.gain_spin, "0 to 600")
        
        # Capture interval
        self.interval_spin = DoubleSpinBox()
        self.interval_spin.setRange(0.1, 3600.0)
        self.interval_spin.setDecimals(1)
        self.interval_spin.setSuffix(" s")
        self.interval_spin.setValue(5.0)
        self.interval_spin.setToolTip("Time to wait between capturing frames")
        self.interval_spin.valueChanged.connect(self._on_interval_changed)
        exposure_card.add_row("Interval", self.interval_spin, "Time between captures")
        
        layout.addWidget(exposure_card)
        
        # === AUTO EXPOSURE ===
        auto_card = CollapsibleCard("Auto Exposure", FluentIcon.BRIGHTNESS)
        
        self.auto_exp_switch = SwitchRow(
            "Enable Auto Exposure",
            "Automatically adjust exposure based on image brightness"
        )
        self.auto_exp_switch.toggled.connect(self._on_auto_exposure_changed)
        auto_card.add_widget(self.auto_exp_switch)
        
        # Conditional auto-exposure settings container
        self.auto_exp_settings = QWidget()
        auto_exp_layout = QVBoxLayout(self.auto_exp_settings)
        auto_exp_layout.setContentsMargins(0, 0, 0, 0)
        auto_exp_layout.setSpacing(Spacing.input_gap)
        
        # Target brightness slider
        self.target_brightness_slider = ClickSlider(Qt.Horizontal)
        self.target_brightness_slider.setRange(20, 200)
        self.target_brightness_slider.setValue(100)
        self.target_brightness_slider.setToolTip("Target image brightness: 100")
        self.target_brightness_slider.valueChanged.connect(self._on_target_brightness_changed)
        self.target_brightness_slider.valueChanged.connect(lambda v: self.target_brightness_slider.setToolTip(f"Target image brightness: {v}"))
        target_row = FormRow("Target Brightness", self.target_brightness_slider, "20=dark, 200=bright")
        auto_exp_layout.addWidget(target_row)
        
        # Max exposure
        self.max_exposure_spin = DoubleSpinBox()
        self.max_exposure_spin.setRange(0.1, 3600.0)
        self.max_exposure_spin.setDecimals(1)
        self.max_exposure_spin.setSuffix(" s")
        self.max_exposure_spin.setValue(30.0)
        self.max_exposure_spin.setToolTip("Maximum exposure time for auto-exposure")
        self.max_exposure_spin.valueChanged.connect(self._on_max_exposure_changed)
        max_exp_row = FormRow("Max Exposure", self.max_exposure_spin, "Upper limit for auto exposure")
        auto_exp_layout.addWidget(max_exp_row)
        
        self.auto_exp_settings.hide()  # Hidden by default
        auto_card.add_widget(self.auto_exp_settings)
        
        layout.addWidget(auto_card)
        
        # === SCHEDULED CAPTURE ===
        schedule_card = CollapsibleCard("Scheduled Capture", FluentIcon.CALENDAR)
        
        self.schedule_switch = SwitchRow(
            "Enable Scheduled Capture",
            "Only capture during specified time window"
        )
        self.schedule_switch.toggled.connect(self._on_schedule_enabled_changed)
        schedule_card.add_widget(self.schedule_switch)
        
        # Conditional schedule time settings
        self.schedule_time_widget = QWidget()
        time_row = QHBoxLayout(self.schedule_time_widget)
        time_row.setContentsMargins(0, 0, 0, 0)
        time_row.setSpacing(Spacing.md)
        
        time_label_start = BodyLabel("Active:")
        time_label_start.setStyleSheet(f"color: {Colors.text_secondary};")
        time_row.addWidget(time_label_start)
        
        self.schedule_start = TimePicker()
        self.schedule_start.setTime(QTime(17, 0))
        self.schedule_start.setToolTip("Start time (24hr format)")
        self.schedule_start.timeChanged.connect(self._on_schedule_time_changed)
        time_row.addWidget(self.schedule_start)
        
        time_label_to = BodyLabel("to")
        time_label_to.setStyleSheet(f"color: {Colors.text_muted};")
        time_row.addWidget(time_label_to)
        
        self.schedule_end = TimePicker()
        self.schedule_end.setTime(QTime(9, 0))
        self.schedule_end.setToolTip("End time (24hr format, can span midnight)")
        self.schedule_end.timeChanged.connect(self._on_schedule_time_changed)
        time_row.addWidget(self.schedule_end)
        
        time_row.addStretch()
        
        self.schedule_time_widget.hide()  # Hidden by default
        schedule_card.add_widget(self.schedule_time_widget)
        
        layout.addWidget(schedule_card)
        
        # === WHITE BALANCE MODE ===
        wb_card = CollapsibleCard("White Balance", FluentIcon.PALETTE)
        
        # Mode selector
        self.wb_mode_combo = ComboBox()
        self.wb_mode_combo.addItems(["asi_auto", "manual", "gray_world"])
        self.wb_mode_combo.setToolTip("ASI Auto: SDK auto WB | Manual: Use R/B values | Gray World: Software algorithm")
        self.wb_mode_combo.currentIndexChanged.connect(self._on_wb_mode_changed)
        wb_card.add_row("Mode", self.wb_mode_combo)
        
        # Conditional gray world settings container
        self.gray_world_settings = QWidget()
        gray_world_layout = QVBoxLayout(self.gray_world_settings)
        gray_world_layout.setContentsMargins(0, 0, 0, 0)
        gray_world_layout.setSpacing(Spacing.input_gap)
        
        # Gray world settings (low/high percentile)
        self.wb_low_spin = SpinBox()
        self.wb_low_spin.setRange(0, 49)
        self.wb_low_spin.setValue(5)
        self.wb_low_spin.setToolTip("Mask dark pixels below this percentile")
        self.wb_low_spin.valueChanged.connect(self._on_wb_gray_world_changed)
        low_row = FormRow("Low %", self.wb_low_spin, "Mask dark pixels")
        gray_world_layout.addWidget(low_row)
        
        self.wb_high_spin = SpinBox()
        self.wb_high_spin.setRange(51, 100)
        self.wb_high_spin.setValue(95)
        self.wb_high_spin.setToolTip("Mask bright pixels above this percentile")
        self.wb_high_spin.valueChanged.connect(self._on_wb_gray_world_changed)
        high_row = FormRow("High %", self.wb_high_spin, "Mask bright pixels")
        gray_world_layout.addWidget(high_row)
        
        wb_info = CaptionLabel("Gray World uses mid-tones to balance colors.\nBest for scenes with mixed colors.")
        wb_info.setStyleSheet(f"color: {Colors.text_muted};")
        wb_info.setWordWrap(True)
        gray_world_layout.addWidget(wb_info)
        
        self.gray_world_settings.hide()  # Hidden by default
        wb_card.add_widget(self.gray_world_settings)
        
        # Conditional manual white balance settings container
        self.manual_wb_settings = QWidget()
        manual_wb_layout = QVBoxLayout(self.manual_wb_settings)
        manual_wb_layout.setContentsMargins(0, 0, 0, 0)
        manual_wb_layout.setSpacing(Spacing.input_gap)
        
        # White Balance R slider
        self.wb_r_slider = ClickSlider(Qt.Horizontal)
        self.wb_r_slider.setRange(1, 99)
        self.wb_r_slider.setValue(75)
        self.wb_r_slider.setToolTip("Red channel white balance: 75")
        self.wb_r_slider.valueChanged.connect(self._on_wb_changed)
        self.wb_r_slider.valueChanged.connect(lambda v: self.wb_r_slider.setToolTip(f"Red channel white balance: {v}"))
        r_row = FormRow("Red", self.wb_r_slider)
        manual_wb_layout.addWidget(r_row)
        
        # White Balance B slider
        self.wb_b_slider = ClickSlider(Qt.Horizontal)
        self.wb_b_slider.setRange(1, 99)
        self.wb_b_slider.setValue(99)
        self.wb_b_slider.setToolTip("Blue channel white balance: 99")
        self.wb_b_slider.valueChanged.connect(self._on_wb_changed)
        self.wb_b_slider.valueChanged.connect(lambda v: self.wb_b_slider.setToolTip(f"Blue channel white balance: {v}"))
        b_row = FormRow("Blue", self.wb_b_slider)
        manual_wb_layout.addWidget(b_row)
        
        self.manual_wb_settings.hide()  # Hidden by default
        wb_card.add_widget(self.manual_wb_settings)
        
        layout.addWidget(wb_card)
        
        # === ADVANCED CAMERA ===
        advanced_card = CollapsibleCard("Advanced Settings", FluentIcon.SETTING)
        
        # Offset
        self.offset_spin = SpinBox()
        self.offset_spin.setRange(0, 255)
        self.offset_spin.setValue(20)
        self.offset_spin.setToolTip("Black level offset to prevent clipping")
        self.offset_spin.valueChanged.connect(self._on_offset_changed)
        advanced_card.add_row("Offset", self.offset_spin, "Black level (0-255)")
        
        # Flip
        self.flip_combo = ComboBox()
        self.flip_combo.addItems(["None", "Horizontal", "Vertical", "Both"])
        self.flip_combo.setToolTip("Flip/mirror the image")
        self.flip_combo.currentIndexChanged.connect(self._on_flip_changed)
        advanced_card.add_row("Flip", self.flip_combo, "Mirror image orientation")
        
        # Bayer Pattern
        self.bayer_combo = ComboBox()
        self.bayer_combo.addItems(["BGGR", "RGGB", "GRBG", "GBRG"])
        self.bayer_combo.setToolTip("Color filter array pattern - BGGR for most ZWO cameras")
        self.bayer_combo.currentIndexChanged.connect(self._on_bayer_changed)
        advanced_card.add_row("Bayer Pattern", self.bayer_combo, "BGGR for most ASI cameras")
        
        # RAW16 mode toggle (requires camera support)
        self.raw16_switch = SwitchRow(
            "Use RAW16 Mode",
            "Capture full sensor bit depth (12-14 bit) instead of RAW8"
        )
        self.raw16_switch.toggled.connect(self._on_raw16_changed)
        self.raw16_switch.setEnabled(False)  # Disabled until camera connected
        advanced_card.add_widget(self.raw16_switch)
        
        # RAW16 status label
        self.raw16_status = CaptionLabel("Connect camera to check RAW16 support")
        self.raw16_status.setStyleSheet(f"color: {Colors.text_secondary}; padding: 4px 8px;")
        advanced_card.add_widget(self.raw16_status)
        
        layout.addWidget(advanced_card)
        
        layout.addStretch()
        
        return widget
    
    # === EVENT HANDLERS ===
    
    def _browse_watch_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Watch Directory")
        if dir_path:
            self.watch_dir_input.setText(dir_path)
    
    def _on_watch_dir_changed(self, text):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('watch_directory', text)
            self.settings_changed.emit()
    
    def _on_recursive_changed(self, checked):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('watch_recursive', checked)
            self.settings_changed.emit()
    
    def _browse_sdk(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select ASI SDK", "", "DLL Files (*.dll)"
        )
        if file_path:
            self.sdk_path_input.setText(file_path)
    
    def _on_sdk_path_changed(self, text):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('zwo_sdk_path', text)
            self.settings_changed.emit()
    
    def _on_detect_cameras(self):
        self.detect_cameras_clicked.emit()
        # Actual detection will be handled by controller
    
    def _on_camera_selected(self, index):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            camera_name = self.camera_combo.currentText()
            # Extract actual camera SDK index from the combo text (e.g., "ZWO ASI676MC (Index: 1)" -> 1)
            # The combo box index may differ from actual camera SDK index
            actual_index = index  # Default to combo index
            if '(Index: ' in camera_name:
                try:
                    actual_index = int(camera_name.split('(Index: ')[1].rstrip(')'))
                except (IndexError, ValueError):
                    pass
            self.main_window.config.set('zwo_selected_camera', actual_index)
            self.main_window.config.set('zwo_selected_camera_name', camera_name)
            self.settings_changed.emit()
    
    def _save_to_camera_profile(self, **kwargs):
        """Save settings to both global config AND active camera profile.
        
        This ensures each camera has its own settings that don't contaminate others.
        
        Args:
            **kwargs: Settings to save (e.g., exposure_ms=500, gain=150)
        """
        if not self.main_window or not hasattr(self.main_window, 'config'):
            return
        
        # Get current camera name (clean, without index)
        camera_name = self.main_window.config.get('zwo_selected_camera_name', '')
        if '(Index:' in camera_name:
            camera_name = camera_name.split('(Index:')[0].strip()
        
        # Save to camera-specific profile
        if camera_name:
            self.main_window.config.update_camera_profile(camera_name, **kwargs)
        
        # Also save to global config for backward compatibility and UI sync
        for key, value in kwargs.items():
            self.main_window.config.set(f'zwo_{key}', value)
    
    def _on_exposure_changed(self, value):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            # Store in ms for compatibility
            self._save_to_camera_profile(exposure_ms=value * 1000)
            self.settings_changed.emit()
    
    def _on_gain_changed(self, value):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self._save_to_camera_profile(gain=value)
            self.settings_changed.emit()
    
    def _on_interval_changed(self, value):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('zwo_interval', value)
            self.settings_changed.emit()
    
    def _on_auto_exposure_changed(self, checked):
        # Show/hide conditional settings
        if checked:
            self.auto_exp_settings.show()
        else:
            self.auto_exp_settings.hide()
        
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self._save_to_camera_profile(auto_exposure=checked)
            self.settings_changed.emit()
    
    def _on_target_brightness_changed(self, value):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self._save_to_camera_profile(target_brightness=value)
            self.settings_changed.emit()
    
    def _on_max_exposure_changed(self, value):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self._save_to_camera_profile(max_exposure_ms=value * 1000)
            self.settings_changed.emit()
    
    def _on_wb_changed(self):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self._save_to_camera_profile(
                wb_r=self.wb_r_slider.value(),
                wb_b=self.wb_b_slider.value()
            )
            self.settings_changed.emit()
    
    def _on_offset_changed(self, value):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self._save_to_camera_profile(offset=value)
            self.settings_changed.emit()
    
    def _on_flip_changed(self, index):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self._save_to_camera_profile(flip=index)
            self.settings_changed.emit()
    
    def _on_bayer_changed(self, index):
        if self._loading_config:
            return
        patterns = ["BGGR", "RGGB", "GRBG", "GBRG"]
        if self.main_window and hasattr(self.main_window, 'config'):
            self._save_to_camera_profile(bayer_pattern=patterns[index])
            self.settings_changed.emit()
    
    def _on_raw16_changed(self, checked):
        """Handle RAW16 mode toggle"""
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            dev_mode = self.main_window.config.get('dev_mode', {})
            dev_mode['use_raw16'] = checked
            self.main_window.config.set('dev_mode', dev_mode)
            self.main_window.config.save()
            self.settings_changed.emit()
            
            # Emit signal to update camera if capturing
            self.raw16_mode_changed.emit(checked)
            
            from services.logger import app_logger
            app_logger.info(f"RAW16 mode {'enabled' if checked else 'disabled'}: {'Full' if checked else 'Standard 8-bit'} sensor bit depth will be used")
    
    def update_camera_capabilities(self, supports_raw16: bool, bit_depth: int):
        """
        Update RAW16 toggle based on connected camera's capabilities.
        Called by main_window when camera connects.
        
        Args:
            supports_raw16: Whether camera supports RAW16 mode
            bit_depth: Camera's native ADC bit depth (e.g., 12)
        """
        self._loading_config = True
        try:
            if supports_raw16:
                self.raw16_switch.setEnabled(True)
                self.raw16_status.setText(f"✓ Camera supports RAW16 ({bit_depth}-bit ADC)")
                self.raw16_status.setStyleSheet(f"color: {Colors.success_text}; padding: 4px 8px;")
                # Restore saved preference
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
        """Reset RAW16 toggle when camera disconnects"""
        self._loading_config = True
        try:
            self.raw16_switch.setEnabled(False)
            self.raw16_switch.set_checked(False)
            self.raw16_status.setText("Connect camera to check RAW16 support")
            self.raw16_status.setStyleSheet(f"color: {Colors.text_secondary}; padding: 4px 8px;")
        finally:
            self._loading_config = False
    
    def _on_schedule_enabled_changed(self, checked):
        # Show/hide conditional settings
        if checked:
            self.schedule_time_widget.show()
        else:
            self.schedule_time_widget.hide()
        
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('scheduled_capture_enabled', checked)
            self.settings_changed.emit()
    
    def _on_schedule_time_changed(self):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            start_time = self.schedule_start.getTime()
            end_time = self.schedule_end.getTime()
            self.main_window.config.set('scheduled_start_time', start_time.toString('HH:mm'))
            self.main_window.config.set('scheduled_end_time', end_time.toString('HH:mm'))
            self.settings_changed.emit()
    
    def _on_wb_mode_changed(self, index):
        modes = ["asi_auto", "manual", "gray_world"]
        mode = modes[index]
        
        # Show/hide conditional settings based on mode
        if mode == "manual":
            self.manual_wb_settings.show()
            self.gray_world_settings.hide()
        elif mode == "gray_world":
            self.manual_wb_settings.hide()
            self.gray_world_settings.show()
        else:  # asi_auto
            self.manual_wb_settings.hide()
            self.gray_world_settings.hide()
        
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            wb_settings = self.main_window.config.get('white_balance', {})
            wb_settings['mode'] = mode
            self.main_window.config.set('white_balance', wb_settings)
            self.settings_changed.emit()
    
    def _on_wb_gray_world_changed(self):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            wb_settings = self.main_window.config.get('white_balance', {})
            wb_settings['gray_world_low_pct'] = self.wb_low_spin.value()
            wb_settings['gray_world_high_pct'] = self.wb_high_spin.value()
            self.main_window.config.set('white_balance', wb_settings)
            self.settings_changed.emit()
    
    # === CONFIG LOADING ===
    
    def load_from_config(self, config):
        """Load settings from config object"""
        self._loading_config = True
        try:
            # Mode
            mode = config.get('capture_mode', 'camera')
            self.mode_selector.setCurrentItem(mode)
            self.settings_stack.setCurrentIndex(0 if mode == 'watch' else 1)
            
            # Watch settings
            self.watch_dir_input.setText(config.get('watch_directory', ''))
            self.recursive_switch.set_checked(config.get('watch_recursive', True))
            
            # Camera settings
            self.sdk_path_input.setText(config.get('zwo_sdk_path', ''))
            
            # Exposure (stored in ms, displayed in s)
            exposure_ms = config.get('zwo_exposure_ms', 100.0)
            self.exposure_spin.setValue(exposure_ms / 1000.0)
            
            self.gain_spin.setValue(config.get('zwo_gain', 100))
            self.interval_spin.setValue(config.get('zwo_interval', 5.0))
            
            # Auto exposure
            auto_exp_enabled = config.get('zwo_auto_exposure', False)
            self.auto_exp_switch.set_checked(auto_exp_enabled)
            self.target_brightness_slider.setValue(config.get('zwo_target_brightness', 100))
            max_exp_ms = config.get('zwo_max_exposure_ms', 30000.0)
            self.max_exposure_spin.setValue(max_exp_ms / 1000.0)
            # Set initial visibility
            if auto_exp_enabled:
                self.auto_exp_settings.show()
            else:
                self.auto_exp_settings.hide()
            
            # Scheduled capture
            schedule_enabled = config.get('scheduled_capture_enabled', False)
            self.schedule_switch.set_checked(schedule_enabled)
            # Parse time strings to QTime
            start_str = config.get('scheduled_start_time', '17:00')
            end_str = config.get('scheduled_end_time', '09:00')
            start_parts = start_str.split(':')
            end_parts = end_str.split(':')
            self.schedule_start.setTime(QTime(int(start_parts[0]), int(start_parts[1])))
            self.schedule_end.setTime(QTime(int(end_parts[0]), int(end_parts[1])))
            # Set initial visibility
            if schedule_enabled:
                self.schedule_time_widget.show()
            else:
                self.schedule_time_widget.hide()
            
            # White balance mode
            wb_settings = config.get('white_balance', {})
            wb_mode = wb_settings.get('mode', 'asi_auto')
            modes = ["asi_auto", "manual", "gray_world"]
            if wb_mode in modes:
                self.wb_mode_combo.setCurrentIndex(modes.index(wb_mode))
            self.wb_low_spin.setValue(wb_settings.get('gray_world_low_pct', 5))
            self.wb_high_spin.setValue(wb_settings.get('gray_world_high_pct', 95))
            # Set initial visibility based on mode
            if wb_mode == "manual":
                self.manual_wb_settings.show()
                self.gray_world_settings.hide()
            elif wb_mode == "gray_world":
                self.manual_wb_settings.hide()
                self.gray_world_settings.show()
            else:
                self.manual_wb_settings.hide()
                self.gray_world_settings.hide()
            
            # Advanced
            self.wb_r_slider.setValue(config.get('zwo_wb_r', 75))
            self.wb_b_slider.setValue(config.get('zwo_wb_b', 99))
            self.offset_spin.setValue(config.get('zwo_offset', 20))
            self.flip_combo.setCurrentIndex(config.get('zwo_flip', 0))
            
            bayer = config.get('zwo_bayer_pattern', 'BGGR')
            patterns = ["BGGR", "RGGB", "GRBG", "GBRG"]
            if bayer in patterns:
                self.bayer_combo.setCurrentIndex(patterns.index(bayer))
        finally:
            self._loading_config = False
    
    def set_cameras(self, camera_list: list):
        """Update camera combo box with detected cameras"""
        # Block signals to prevent triggering _on_camera_selected during population
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()
        if camera_list:
            self.camera_combo.addItems(camera_list)
        else:
            self.camera_combo.setPlaceholderText("No cameras detected")
        self.camera_combo.blockSignals(False)
    
    def set_detecting(self, is_detecting: bool):
        """Show/hide detection in progress state"""
        self.detect_btn.setEnabled(not is_detecting)
        if is_detecting:
            self.detect_btn.setText("Detecting...")
        else:
            self.detect_btn.setText("Detect")
    
    def set_detection_error(self, error: str):
        """Display camera detection error"""
        from qfluentwidgets import InfoBar, InfoBarPosition
        InfoBar.error(
            title="Camera Detection Failed",
            content=error,
            parent=self,
            position=InfoBarPosition.TOP,
            duration=5000
        )
