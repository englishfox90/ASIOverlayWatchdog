"""
Image Processing Settings Panel
Settings for resize, brightness, saturation, timestamp, and auto-stretch
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from qfluentwidgets import (
    CardWidget, SubtitleLabel, BodyLabel, CaptionLabel,
    PushButton, ComboBox, SpinBox, DoubleSpinBox, 
    SwitchButton, FluentIcon
)

from ..theme.tokens import Colors, Typography, Spacing, Layout
from ..components.cards import SettingsCard, FormRow, SwitchRow, CollapsibleCard, ClickSlider


class ImageProcessingPanel(QScrollArea):
    """
    Image processing settings panel with:
    - Resize settings
    - Brightness/saturation adjustments
    - Timestamp overlay
    - Auto-stretch (MTF)
    """
    
    settings_changed = Signal()
    
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
        
        content = QWidget()
        self.setWidget(content)
        
        layout = QVBoxLayout(content)
        layout.setContentsMargins(Spacing.base, Spacing.base, Spacing.base, Spacing.base)
        layout.setSpacing(Spacing.card_gap)
        
        # === RESIZE ===
        resize_card = SettingsCard(
            "Image Resize",
            "Scale output images to reduce file size"
        )
        
        # Resize percentage with slider
        resize_row = QHBoxLayout()
        resize_row.setSpacing(Spacing.md)
        
        self.resize_slider = ClickSlider(Qt.Horizontal)
        self.resize_slider.setRange(10, 100)
        self.resize_slider.setValue(85)
        self.resize_slider.setToolTip("Image scale: 85%")
        self.resize_slider.valueChanged.connect(self._on_resize_changed)
        self.resize_slider.valueChanged.connect(lambda v: self.resize_slider.setToolTip(f"Image scale: {v}%"))
        resize_row.addWidget(self.resize_slider, 1)
        
        self.resize_label = BodyLabel("85%")
        self.resize_label.setFixedWidth(50)
        self.resize_label.setStyleSheet(f"color: {Colors.text_primary};")
        resize_row.addWidget(self.resize_label)
        
        resize_widget = QWidget()
        resize_widget.setLayout(resize_row)
        resize_card.add_row("Scale", resize_widget, "10% to 100%")
        
        layout.addWidget(resize_card)
        
        # === ADJUSTMENTS ===
        adjust_card = SettingsCard(
            "Adjustments",
            "Fine-tune image brightness and saturation"
        )
        
        # Brightness
        self.auto_brightness_switch = SwitchRow(
            "Auto Brightness",
            "Automatically adjust brightness based on image content"
        )
        self.auto_brightness_switch.toggled.connect(self._on_auto_brightness_changed)
        adjust_card.add_widget(self.auto_brightness_switch)
        
        # Brightness factor
        brightness_row = QHBoxLayout()
        brightness_row.setSpacing(Spacing.md)
        
        self.brightness_slider = ClickSlider(Qt.Horizontal)
        self.brightness_slider.setRange(50, 200)
        self.brightness_slider.setValue(100)
        self.brightness_slider.setToolTip("Brightness: 1.0x")
        self.brightness_slider.valueChanged.connect(self._on_brightness_changed)
        self.brightness_slider.valueChanged.connect(lambda v: self.brightness_slider.setToolTip(f"Brightness: {v/100.0:.1f}x"))
        brightness_row.addWidget(self.brightness_slider, 1)
        
        self.brightness_label = BodyLabel("1.0x")
        self.brightness_label.setFixedWidth(50)
        self.brightness_label.setStyleSheet(f"color: {Colors.text_primary};")
        brightness_row.addWidget(self.brightness_label)
        
        brightness_widget = QWidget()
        brightness_widget.setLayout(brightness_row)
        adjust_card.add_row("Brightness", brightness_widget, "0.5x to 2.0x")
        
        # Saturation factor
        saturation_row = QHBoxLayout()
        saturation_row.setSpacing(Spacing.md)
        
        self.saturation_slider = ClickSlider(Qt.Horizontal)
        self.saturation_slider.setRange(0, 200)
        self.saturation_slider.setValue(100)
        self.saturation_slider.setToolTip("Saturation: 1.0x")
        self.saturation_slider.valueChanged.connect(self._on_saturation_changed)
        self.saturation_slider.valueChanged.connect(lambda v: self.saturation_slider.setToolTip(f"Saturation: {v/100.0:.1f}x"))
        saturation_row.addWidget(self.saturation_slider, 1)
        
        self.saturation_label = BodyLabel("1.0x")
        self.saturation_label.setFixedWidth(50)
        self.saturation_label.setStyleSheet(f"color: {Colors.text_primary};")
        saturation_row.addWidget(self.saturation_label)
        
        saturation_widget = QWidget()
        saturation_widget.setLayout(saturation_row)
        adjust_card.add_row("Saturation", saturation_widget, "0.0x to 2.0x")
        
        layout.addWidget(adjust_card)
        
        # === TIMESTAMP ===
        timestamp_card = SettingsCard(
            "Timestamp Overlay",
            "Add timestamp to image corner"
        )
        
        self.timestamp_switch = SwitchRow(
            "Show Timestamp",
            "Display capture time in corner of image"
        )
        self.timestamp_switch.toggled.connect(self._on_timestamp_changed)
        timestamp_card.add_widget(self.timestamp_switch)
        
        layout.addWidget(timestamp_card)
        
        # === AUTO STRETCH ===
        stretch_card = CollapsibleCard("Auto Stretch (MTF)", FluentIcon.BRIGHTNESS)
        
        self.stretch_enabled_switch = SwitchRow(
            "Enable Auto Stretch",
            "Apply Midtone Transfer Function for dynamic range optimization"
        )
        self.stretch_enabled_switch.toggled.connect(self._on_stretch_enabled_changed)
        stretch_card.add_widget(self.stretch_enabled_switch)
        
        # Target median
        target_row = QHBoxLayout()
        target_row.setSpacing(Spacing.md)
        
        self.target_median_slider = ClickSlider(Qt.Horizontal)
        self.target_median_slider.setRange(10, 50)
        self.target_median_slider.setValue(25)
        self.target_median_slider.setToolTip("Target median: 0.25")
        self.target_median_slider.valueChanged.connect(self._on_stretch_settings_changed)
        self.target_median_slider.valueChanged.connect(lambda v: self.target_median_slider.setToolTip(f"Target median: {v/100.0:.2f}"))
        target_row.addWidget(self.target_median_slider, 1)
        
        self.target_median_label = BodyLabel("0.25")
        self.target_median_label.setFixedWidth(50)
        self.target_median_label.setStyleSheet(f"color: {Colors.text_primary};")
        target_row.addWidget(self.target_median_label)
        
        target_widget = QWidget()
        target_widget.setLayout(target_row)
        stretch_card.add_row("Target Median", target_widget, "0.1 to 0.5")
        
        # Linked stretch
        self.linked_stretch_switch = SwitchRow(
            "Linked Channels",
            "Apply same stretch to all RGB channels"
        )
        self.linked_stretch_switch.set_checked(True)
        self.linked_stretch_switch.toggled.connect(self._on_stretch_settings_changed)
        stretch_card.add_widget(self.linked_stretch_switch)
        
        # Preserve blacks
        self.preserve_blacks_switch = SwitchRow(
            "Preserve Blacks",
            "Keep true blacks dark instead of lifting to grey"
        )
        self.preserve_blacks_switch.set_checked(True)
        self.preserve_blacks_switch.toggled.connect(self._on_stretch_settings_changed)
        stretch_card.add_widget(self.preserve_blacks_switch)
        
        # Shadow aggressiveness
        shadow_row = QHBoxLayout()
        shadow_row.setSpacing(Spacing.md)
        
        self.shadow_slider = ClickSlider(Qt.Horizontal)
        self.shadow_slider.setRange(15, 40)  # 1.5 to 4.0 scaled by 10
        self.shadow_slider.setValue(28)
        self.shadow_slider.setToolTip("Shadow aggressiveness: 2.8")
        self.shadow_slider.valueChanged.connect(self._on_stretch_settings_changed)
        self.shadow_slider.valueChanged.connect(lambda v: self.shadow_slider.setToolTip(f"Shadow aggressiveness: {v/10.0:.1f}"))
        shadow_row.addWidget(self.shadow_slider, 1)
        
        self.shadow_label = BodyLabel("2.8")
        self.shadow_label.setFixedWidth(50)
        self.shadow_label.setStyleSheet(f"color: {Colors.text_primary};")
        shadow_row.addWidget(self.shadow_label)
        
        shadow_widget = QWidget()
        shadow_widget.setLayout(shadow_row)
        stretch_card.add_row("Shadow Aggressiveness", shadow_widget, "1.5 (aggressive) to 4.0 (gentle)")
        
        # Saturation boost
        boost_row = QHBoxLayout()
        boost_row.setSpacing(Spacing.md)
        
        self.sat_boost_slider = ClickSlider(Qt.Horizontal)
        self.sat_boost_slider.setRange(10, 20)  # 1.0 to 2.0 scaled by 10
        self.sat_boost_slider.setValue(15)
        self.sat_boost_slider.setToolTip("Saturation boost: 1.5x")
        self.sat_boost_slider.valueChanged.connect(self._on_stretch_settings_changed)
        self.sat_boost_slider.valueChanged.connect(lambda v: self.sat_boost_slider.setToolTip(f"Saturation boost: {v/10.0:.1f}x"))
        boost_row.addWidget(self.sat_boost_slider, 1)
        
        self.sat_boost_label = BodyLabel("1.5x")
        self.sat_boost_label.setFixedWidth(50)
        self.sat_boost_label.setStyleSheet(f"color: {Colors.text_primary};")
        boost_row.addWidget(self.sat_boost_label)
        
        boost_widget = QWidget()
        boost_widget.setLayout(boost_row)
        stretch_card.add_row("Saturation Boost", boost_widget, "Post-stretch saturation enhancement")
        
        layout.addWidget(stretch_card)
        
        layout.addStretch()
    
    # === EVENT HANDLERS ===
    
    def _on_resize_changed(self, value):
        self.resize_label.setText(f"{value}%")
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('resize_percent', value)
            self.settings_changed.emit()
    
    def _on_auto_brightness_changed(self, checked):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('auto_brightness', checked)
            self.settings_changed.emit()
    
    def _on_brightness_changed(self, value):
        factor = value / 100.0
        self.brightness_label.setText(f"{factor:.1f}x")
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('brightness_factor', factor)
            self.settings_changed.emit()
    
    def _on_saturation_changed(self, value):
        factor = value / 100.0
        self.saturation_label.setText(f"{factor:.1f}x")
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('saturation_factor', factor)
            self.settings_changed.emit()
    
    def _on_timestamp_changed(self, checked):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('timestamp_corner', checked)
            self.settings_changed.emit()
    
    def _on_stretch_enabled_changed(self, checked):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            stretch = self.main_window.config.get('auto_stretch', {})
            stretch['enabled'] = checked
            self.main_window.config.set('auto_stretch', stretch)
            self.settings_changed.emit()
    
    def _on_stretch_settings_changed(self):
        # Update labels
        self.target_median_label.setText(f"{self.target_median_slider.value() / 100:.2f}")
        self.shadow_label.setText(f"{self.shadow_slider.value() / 10:.1f}")
        self.sat_boost_label.setText(f"{self.sat_boost_slider.value() / 10:.1f}x")
        
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            stretch = self.main_window.config.get('auto_stretch', {})
            stretch['target_median'] = self.target_median_slider.value() / 100
            stretch['linked_stretch'] = self.linked_stretch_switch.is_checked()
            stretch['preserve_blacks'] = self.preserve_blacks_switch.is_checked()
            stretch['shadow_aggressiveness'] = self.shadow_slider.value() / 10
            stretch['saturation_boost'] = self.sat_boost_slider.value() / 10
            self.main_window.config.set('auto_stretch', stretch)
            self.settings_changed.emit()
    
    # === CONFIG LOADING ===
    
    def load_from_config(self, config):
        """Load settings from config object"""
        self._loading_config = True
        try:
            # Resize
            resize = config.get('resize_percent', 85)
            self.resize_slider.setValue(resize)
            self.resize_label.setText(f"{resize}%")
            
            # Brightness/saturation
            self.auto_brightness_switch.set_checked(config.get('auto_brightness', False))
            
            brightness = int(config.get('brightness_factor', 1.0) * 100)
            self.brightness_slider.setValue(brightness)
            self.brightness_label.setText(f"{brightness / 100:.1f}x")
            
            saturation = int(config.get('saturation_factor', 1.0) * 100)
            self.saturation_slider.setValue(saturation)
            self.saturation_label.setText(f"{saturation / 100:.1f}x")
            
            # Timestamp
            self.timestamp_switch.set_checked(config.get('timestamp_corner', False))
            
            # Auto stretch
            stretch = config.get('auto_stretch', {})
            self.stretch_enabled_switch.set_checked(stretch.get('enabled', False))
            
            target = int(stretch.get('target_median', 0.25) * 100)
            self.target_median_slider.setValue(target)
            self.target_median_label.setText(f"{target / 100:.2f}")
            
            self.linked_stretch_switch.set_checked(stretch.get('linked_stretch', True))
            self.preserve_blacks_switch.set_checked(stretch.get('preserve_blacks', True))
            
            shadow = int(stretch.get('shadow_aggressiveness', 2.8) * 10)
            self.shadow_slider.setValue(shadow)
            self.shadow_label.setText(f"{shadow / 10:.1f}")
            
            boost = int(stretch.get('saturation_boost', 1.5) * 10)
            self.sat_boost_slider.setValue(boost)
            self.sat_boost_label.setText(f"{boost / 10:.1f}x")
        finally:
            self._loading_config = False
