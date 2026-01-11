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
from services.dev_mode_config import is_dev_mode_available


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
        
        # Normalize channels (dark scene fix)
        self.normalize_channels_switch = SwitchRow(
            "Dark Scene Color Fix",
            "Equalize R/G/B medians before stretch (fixes purple/magenta in dark images)"
        )
        self.normalize_channels_switch.set_checked(True)
        self.normalize_channels_switch.toggled.connect(self._on_stretch_settings_changed)
        stretch_card.add_widget(self.normalize_channels_switch)
        
        # Dark scene threshold
        threshold_row = QHBoxLayout()
        threshold_row.setSpacing(Spacing.md)
        
        self.dark_threshold_slider = ClickSlider(Qt.Horizontal)
        self.dark_threshold_slider.setRange(1, 15)  # 0.01 to 0.15 scaled by 100
        self.dark_threshold_slider.setValue(5)  # 0.05 default
        self.dark_threshold_slider.setToolTip("Dark scene threshold: 0.05")
        self.dark_threshold_slider.valueChanged.connect(self._on_stretch_settings_changed)
        self.dark_threshold_slider.valueChanged.connect(lambda v: self.dark_threshold_slider.setToolTip(f"Dark scene threshold: {v/100.0:.2f}"))
        threshold_row.addWidget(self.dark_threshold_slider, 1)
        
        self.dark_threshold_label = BodyLabel("0.05")
        self.dark_threshold_label.setFixedWidth(50)
        self.dark_threshold_label.setStyleSheet(f"color: {Colors.text_primary};")
        threshold_row.addWidget(self.dark_threshold_label)
        
        threshold_widget = QWidget()
        threshold_widget.setLayout(threshold_row)
        stretch_card.add_row("Dark Threshold", threshold_widget, "Median below this enables color fix")
        
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
        
        # === ML MODELS (Beta) ===
        ml_card = CollapsibleCard("ML Models (Beta)", FluentIcon.IOT)
        
        self.ml_enabled_switch = SwitchRow(
            "Enable ML Analysis",
            "Use machine learning to analyze observatory conditions"
        )
        self.ml_enabled_switch.toggled.connect(self._on_ml_enabled_changed)
        ml_card.add_widget(self.ml_enabled_switch)
        
        # Info about what ML models do
        ml_info = CaptionLabel(
            "🔭 Roof Classifier: Detects if observatory roof is open or closed\n"
            "🌤️ Sky Classifier: Identifies sky conditions (Clear, Cloudy, etc.) when roof is open\n\n"
            "New overlay tokens available:\n"
            "• {ROOF_STATUS} - \"Open (95%)\" or \"Closed (98%)\"\n"
            "• {SKY_CONDITION} - \"Clear (87%)\" or \"Partly Cloudy (72%)\"\n"
            "• {STARS_VISIBLE} - \"Yes\" or \"No\"\n"
            "• {STAR_DENSITY} - \"High (0.85)\" or \"Low (0.12)\""
        )
        ml_info.setStyleSheet(f"color: {Colors.text_secondary}; padding: 8px;")
        ml_info.setWordWrap(True)
        ml_card.add_widget(ml_info)
        
        # ML status label
        self.ml_status_label = CaptionLabel("Status: Not initialized")
        self.ml_status_label.setStyleSheet(f"color: {Colors.text_muted}; padding: 8px;")
        ml_card.add_widget(self.ml_status_label)
        
        layout.addWidget(ml_card)
        
        # === DEV MODE === (Only show in development builds)
        if is_dev_mode_available():
            dev_card = CollapsibleCard("Developer Mode", FluentIcon.DEVELOPER_TOOLS)
            
            self.dev_mode_switch = SwitchRow(
                "Enable Dev Mode",
                "Save raw images to raw_debug folder for troubleshooting"
            )
            self.dev_mode_switch.toggled.connect(self._on_dev_mode_changed)
            dev_card.add_widget(self.dev_mode_switch)
            
            self.dev_stats_switch = SwitchRow(
                "Log Channel Statistics",
                "Log detailed per-channel histogram stats (R, G, B medians, MAD, etc.)"
            )
            self.dev_stats_switch.set_checked(True)
            self.dev_stats_switch.toggled.connect(self._on_dev_stats_changed)
            dev_card.add_widget(self.dev_stats_switch)
            
            # Info label
            dev_info = CaptionLabel(
                "When enabled, raw images are saved before any processing (stretch, overlays). "
                "Check logs for per-channel statistics to diagnose color balance issues."
            )
            dev_info.setStyleSheet(f"color: {Colors.text_secondary}; padding: 8px;")
            dev_info.setWordWrap(True)
            dev_card.add_widget(dev_info)
            
            layout.addWidget(dev_card)
        
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
        self.dark_threshold_label.setText(f"{self.dark_threshold_slider.value() / 100:.2f}")
        
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            stretch = self.main_window.config.get('auto_stretch', {})
            stretch['target_median'] = self.target_median_slider.value() / 100
            stretch['linked_stretch'] = self.linked_stretch_switch.is_checked()
            stretch['preserve_blacks'] = self.preserve_blacks_switch.is_checked()
            stretch['normalize_channels'] = self.normalize_channels_switch.is_checked()
            stretch['dark_scene_threshold'] = self.dark_threshold_slider.value() / 100
            stretch['shadow_aggressiveness'] = self.shadow_slider.value() / 10
            stretch['saturation_boost'] = self.sat_boost_slider.value() / 10
            self.main_window.config.set('auto_stretch', stretch)
            self.settings_changed.emit()
    
    def _on_dev_mode_changed(self, checked):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            dev_mode = self.main_window.config.get('dev_mode', {})
            dev_mode['enabled'] = checked
            self.main_window.config.set('dev_mode', dev_mode)
            self.main_window.config.save()  # CRITICAL: Save immediately so setting persists
            self.settings_changed.emit()
            from services.logger import app_logger
            app_logger.info(f"Dev Mode {'enabled' if checked else 'disabled'}: raw images will {'be saved to raw_debug/' if checked else 'not be saved'}")
    
    def _on_dev_stats_changed(self, checked):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            dev_mode = self.main_window.config.get('dev_mode', {})
            dev_mode['save_histogram_stats'] = checked
            self.main_window.config.set('dev_mode', dev_mode)
            self.settings_changed.emit()
    
    def _on_ml_enabled_changed(self, checked):
        """Handle ML Models enable/disable toggle"""
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            ml_config = self.main_window.config.get('ml_models', {})
            ml_config['enabled'] = checked
            self.main_window.config.set('ml_models', ml_config)
            self.main_window.config.save()
            self.settings_changed.emit()
            
            from services.logger import app_logger
            if checked:
                app_logger.info("ML Models enabled - initializing classifiers...")
                self._initialize_ml_service()
            else:
                app_logger.info("ML Models disabled")
                self.ml_status_label.setText("Status: Disabled")
    
    def _initialize_ml_service(self):
        """Initialize ML service and update status label"""
        try:
            from services.ml_service import get_ml_service
            ml = get_ml_service()
            ml.initialize()
            
            status = ml.get_status()
            roof_ok = status['roof_classifier']['available']
            sky_ok = status['sky_classifier']['available']
            
            if roof_ok and sky_ok:
                self.ml_status_label.setText("Status: ✓ Both models loaded")
                self.ml_status_label.setStyleSheet(f"color: #4ade80; padding: 8px;")  # Green
            elif roof_ok:
                self.ml_status_label.setText("Status: ✓ Roof model only")
                self.ml_status_label.setStyleSheet(f"color: #facc15; padding: 8px;")  # Yellow
            elif sky_ok:
                self.ml_status_label.setText("Status: ✓ Sky model only")
                self.ml_status_label.setStyleSheet(f"color: #facc15; padding: 8px;")  # Yellow
            else:
                roof_err = status['roof_classifier'].get('error', 'Unknown')
                self.ml_status_label.setText(f"Status: ✗ No models available ({roof_err})")
                self.ml_status_label.setStyleSheet(f"color: #f87171; padding: 8px;")  # Red
                
        except Exception as e:
            self.ml_status_label.setText(f"Status: ✗ Error: {str(e)[:50]}")
            self.ml_status_label.setStyleSheet(f"color: #f87171; padding: 8px;")

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
            
            # Dark scene color fix
            self.normalize_channels_switch.set_checked(stretch.get('normalize_channels', True))
            
            dark_threshold = int(stretch.get('dark_scene_threshold', 0.05) * 100)
            self.dark_threshold_slider.setValue(dark_threshold)
            self.dark_threshold_label.setText(f"{dark_threshold / 100:.2f}")
            
            shadow = int(stretch.get('shadow_aggressiveness', 2.8) * 10)
            self.shadow_slider.setValue(shadow)
            self.shadow_label.setText(f"{shadow / 10:.1f}")
            
            boost = int(stretch.get('saturation_boost', 1.5) * 10)
            self.sat_boost_slider.setValue(boost)
            self.sat_boost_label.setText(f"{boost / 10:.1f}x")
            
            # Dev mode
            dev_mode = config.get('dev_mode', {})
            if hasattr(self, 'dev_mode_switch'):
                self.dev_mode_switch.set_checked(dev_mode.get('enabled', False))
                self.dev_stats_switch.set_checked(dev_mode.get('save_histogram_stats', True))
            
            # ML Models
            ml_config = config.get('ml_models', {})
            self.ml_enabled_switch.set_checked(ml_config.get('enabled', False))
            
            # Initialize ML service if enabled
            if ml_config.get('enabled', False):
                self._initialize_ml_service()
            else:
                self.ml_status_label.setText("Status: Disabled")
                self.ml_status_label.setStyleSheet(f"color: {Colors.text_muted}; padding: 8px;")
        finally:
            self._loading_config = False
