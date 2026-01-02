"""
Settings Panel
Application settings: Discord, Weather, Storage, System
"""
import subprocess
import webbrowser
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from qfluentwidgets import (
    CardWidget, SubtitleLabel, BodyLabel, CaptionLabel,
    PushButton, PrimaryPushButton, ComboBox, LineEdit,
    SpinBox, DoubleSpinBox, SwitchButton, FluentIcon, HyperlinkLabel
)

from ..theme.tokens import Colors, Typography, Spacing, Layout
from ..components.cards import SettingsCard, FormRow, SwitchRow, CollapsibleCard


def is_ffmpeg_available() -> bool:
    """Check if ffmpeg is available in PATH"""
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except:
        return False


class SettingsPanel(QScrollArea):
    """
    Application settings panel with:
    - System settings (tray mode)
    - Discord alerts
    - Weather API
    - Storage cleanup
    """
    
    settings_changed = Signal()
    test_discord_requested = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self._loading_config = True
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
        
        # === SYSTEM SETTINGS ===
        system_card = SettingsCard(
            "System",
            "Application behavior settings"
        )
        
        # System tray mode
        tray_row = SwitchRow(
            "Enable System Tray",
            "Minimize to system tray instead of taskbar when closing window"
        )
        self.tray_enabled_switch = tray_row.switch
        self.tray_enabled_switch.checkedChanged.connect(self._on_system_changed)
        system_card.add_widget(tray_row)
        
        layout.addWidget(system_card)
        
        # === DISCORD ALERTS ===
        discord_card = SettingsCard(
            "Discord Alerts",
            "Send notifications to Discord webhook"
        )
        
        # Enable Discord
        discord_enable_row = SwitchRow(
            "Enable Discord Alerts",
            "Send notifications to Discord via webhook"
        )
        self.discord_enabled_switch = discord_enable_row.switch
        self.discord_enabled_switch.checkedChanged.connect(self._on_discord_changed)
        discord_card.add_widget(discord_enable_row)
        
        # Webhook URL
        webhook_row = QHBoxLayout()
        webhook_row.setSpacing(Spacing.sm)
        
        self.webhook_input = LineEdit()
        self.webhook_input.setPlaceholderText("https://discord.com/api/webhooks/...")
        self.webhook_input.textChanged.connect(self._on_discord_changed)
        webhook_row.addWidget(self.webhook_input)
        
        test_btn = PrimaryPushButton("Test")
        test_btn.setIcon(FluentIcon.SEND)
        test_btn.clicked.connect(lambda: self.test_discord_requested.emit())
        webhook_row.addWidget(test_btn)
        
        webhook_widget = QWidget()
        webhook_widget.setLayout(webhook_row)
        discord_card.add_row("Webhook URL", webhook_widget)
        
        # Notification types
        startup_row = SwitchRow(
            "Startup / Shutdown / Capture Started",
            "Notify when app starts, stops, or capture begins"
        )
        self.discord_startup_switch = startup_row.switch
        self.discord_startup_switch.checkedChanged.connect(self._on_discord_changed)
        discord_card.add_widget(startup_row)
        
        error_row = SwitchRow(
            "Error Alerts",
            "Notify when errors occur"
        )
        self.discord_error_switch = error_row.switch
        self.discord_error_switch.checkedChanged.connect(self._on_discord_changed)
        discord_card.add_widget(error_row)
        
        periodic_row = SwitchRow(
            "Periodic Updates",
            "Post periodic status updates with latest image"
        )
        self.discord_periodic_switch = periodic_row.switch
        self.discord_periodic_switch.checkedChanged.connect(self._on_discord_changed)
        discord_card.add_widget(periodic_row)
        
        # Periodic interval
        self.periodic_interval_spin = SpinBox()
        self.periodic_interval_spin.setRange(1, 120)
        self.periodic_interval_spin.setSuffix(" min")
        self.periodic_interval_spin.valueChanged.connect(self._on_discord_changed)
        discord_card.add_row("Update Interval", self.periodic_interval_spin)
        
        layout.addWidget(discord_card)
        
        # === WEATHER API ===
        weather_card = SettingsCard(
            "Weather API",
            "OpenWeatherMap integration for overlay tokens"
        )
        
        # Info link
        info_row = QHBoxLayout()
        info_row.setSpacing(Spacing.sm)
        
        info_label = CaptionLabel("🌤️ Add live weather data to overlays")
        info_label.setStyleSheet(f"color: {Colors.text_muted};")
        info_row.addWidget(info_label)
        
        link_btn = PushButton("Get free API key")
        link_btn.setIcon(FluentIcon.LINK)
        link_btn.clicked.connect(lambda: webbrowser.open("https://openweathermap.org/api"))
        info_row.addWidget(link_btn)
        info_row.addStretch()
        
        info_widget = QWidget()
        info_widget.setLayout(info_row)
        weather_card.add_widget(info_widget)
        
        # API Key
        api_row = QHBoxLayout()
        api_row.setSpacing(Spacing.sm)
        
        self.api_key_input = LineEdit()
        self.api_key_input.setPlaceholderText("Enter OpenWeatherMap API key")
        self.api_key_input.setEchoMode(LineEdit.Password)
        self.api_key_input.textChanged.connect(self._on_weather_changed)
        api_row.addWidget(self.api_key_input)
        
        self.show_key_btn = PushButton("Show")
        self.show_key_btn.setCheckable(True)
        self.show_key_btn.clicked.connect(self._toggle_api_key_visibility)
        api_row.addWidget(self.show_key_btn)
        
        self.test_weather_btn = PrimaryPushButton("Test")
        self.test_weather_btn.setIcon(FluentIcon.SYNC)
        self.test_weather_btn.clicked.connect(self._test_weather)
        api_row.addWidget(self.test_weather_btn)
        
        api_widget = QWidget()
        api_widget.setLayout(api_row)
        weather_card.add_row("API Key", api_widget)
        
        # Status label
        self.weather_status_label = CaptionLabel("Not tested")
        self.weather_status_label.setStyleSheet(f"color: {Colors.text_muted};")
        weather_card.add_widget(self.weather_status_label)
        
        # Location
        self.location_input = LineEdit()
        self.location_input.setPlaceholderText("City name, e.g., London, UK")
        self.location_input.textChanged.connect(self._on_weather_changed)
        weather_card.add_row("Location", self.location_input, "City name or leave blank to use coordinates")
        
        # OR coordinates
        coord_row = QHBoxLayout()
        coord_row.setSpacing(Spacing.sm)
        
        self.lat_input = LineEdit()
        self.lat_input.setPlaceholderText("Latitude")
        self.lat_input.textChanged.connect(self._on_weather_changed)
        coord_row.addWidget(self.lat_input)
        
        self.lon_input = LineEdit()
        self.lon_input.setPlaceholderText("Longitude")
        self.lon_input.textChanged.connect(self._on_weather_changed)
        coord_row.addWidget(self.lon_input)
        
        coord_widget = QWidget()
        coord_widget.setLayout(coord_row)
        weather_card.add_row("Coordinates", coord_widget, "Alternative to location name")
        
        # Units
        self.units_combo = ComboBox()
        self.units_combo.addItems(["Metric (°C, m/s)", "Imperial (°F, mph)"])
        self.units_combo.currentIndexChanged.connect(self._on_weather_changed)
        weather_card.add_row("Units", self.units_combo)
        
        layout.addWidget(weather_card)
        
        # === STORAGE CLEANUP ===
        cleanup_card = SettingsCard(
            "Storage Cleanup",
            "Automatic cleanup of old images"
        )
        
        # Enable cleanup
        cleanup_enable_row = SwitchRow(
            "Enable Auto-Cleanup",
            "Automatically delete old images when storage limit is reached"
        )
        self.cleanup_enabled_switch = cleanup_enable_row.switch
        self.cleanup_enabled_switch.checkedChanged.connect(self._on_cleanup_changed)
        cleanup_card.add_widget(cleanup_enable_row)
        
        # Storage limit (use DoubleSpinBox for decimal values like 0.1 GB)
        self.cleanup_size_spin = DoubleSpinBox()
        self.cleanup_size_spin.setRange(0.1, 1000.0)
        self.cleanup_size_spin.setDecimals(1)
        self.cleanup_size_spin.setSingleStep(0.1)
        self.cleanup_size_spin.setValue(10.0)
        self.cleanup_size_spin.setSuffix(" GB")
        self.cleanup_size_spin.valueChanged.connect(self._on_cleanup_changed)
        cleanup_card.add_row("Storage Limit", self.cleanup_size_spin, "Maximum storage before cleanup")
        
        layout.addWidget(cleanup_card)
        
        layout.addStretch()
    
    def _toggle_api_key_visibility(self):
        """Toggle API key visibility"""
        if self.show_key_btn.isChecked():
            self.api_key_input.setEchoMode(LineEdit.Normal)
            self.show_key_btn.setText("Hide")
        else:
            self.api_key_input.setEchoMode(LineEdit.Password)
            self.show_key_btn.setText("Show")
    
    def _on_system_changed(self):
        """Handle system settings change"""
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            tray_enabled = self.tray_enabled_switch.isChecked()
            self.main_window.config.set('tray_mode_enabled', tray_enabled)
            
            # Apply tray mode change immediately
            if hasattr(self.main_window, 'set_tray_mode'):
                self.main_window.set_tray_mode(tray_enabled)
            
            self.settings_changed.emit()
    
    def _on_discord_changed(self):
        """Handle Discord settings change"""
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            discord = self.main_window.config.get('discord', {})
            discord['enabled'] = self.discord_enabled_switch.isChecked()
            discord['webhook_url'] = self.webhook_input.text()
            discord['post_startup_shutdown'] = self.discord_startup_switch.isChecked()
            discord['error_enabled'] = self.discord_error_switch.isChecked()
            discord['periodic_enabled'] = self.discord_periodic_switch.isChecked()
            discord['periodic_interval_minutes'] = self.periodic_interval_spin.value()
            self.main_window.config.set('discord', discord)
            self.settings_changed.emit()
    
    def _on_weather_changed(self):
        """Handle weather settings change"""
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            weather = self.main_window.config.get('weather', {})
            weather['api_key'] = self.api_key_input.text()
            weather['location'] = self.location_input.text()
            weather['latitude'] = self.lat_input.text()
            weather['longitude'] = self.lon_input.text()
            units_text = self.units_combo.currentText()
            weather['units'] = 'imperial' if 'imperial' in units_text else 'metric'
            self.main_window.config.set('weather', weather)
            self.settings_changed.emit()
    
    def _test_weather(self):
        """Test weather API connection"""
        self.weather_status_label.setText("Testing...")
        self.weather_status_label.setStyleSheet(f"color: {Colors.text_muted};")
        
        try:
            from services.weather import WeatherService
            
            api_key = self.api_key_input.text().strip()
            location = self.location_input.text().strip()
            lat = self.lat_input.text().strip()
            lon = self.lon_input.text().strip()
            units_text = self.units_combo.currentText()
            units = 'imperial' if 'imperial' in units_text else 'metric'
            
            if not api_key:
                self.weather_status_label.setText("❌ API key required")
                self.weather_status_label.setStyleSheet(f"color: {Colors.status_error};")
                return
            
            if not location and not (lat and lon):
                self.weather_status_label.setText("❌ Location or coordinates required")
                self.weather_status_label.setStyleSheet(f"color: {Colors.status_error};")
                return
            
            service = WeatherService(
                api_key=api_key,
                location=location if location else None,
                latitude=float(lat) if lat else None,
                longitude=float(lon) if lon else None,
                units=units
            )
            
            data = service.fetch_weather()
            if data:
                temp = data.get('temp', 'N/A')
                condition = data.get('condition', 'N/A')
                self.weather_status_label.setText(f"✓ {condition}, {temp}")
                self.weather_status_label.setStyleSheet(f"color: {Colors.status_success};")
            else:
                self.weather_status_label.setText("❌ No data returned")
                self.weather_status_label.setStyleSheet(f"color: {Colors.status_error};")
                
        except Exception as e:
            self.weather_status_label.setText(f"❌ {str(e)[:30]}")
            self.weather_status_label.setStyleSheet(f"color: {Colors.status_error};")
    
    def _on_cleanup_changed(self):
        """Handle cleanup settings change"""
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('cleanup_enabled', self.cleanup_enabled_switch.isChecked())
            self.main_window.config.set('cleanup_max_size_gb', self.cleanup_size_spin.value())
            self.settings_changed.emit()
    
    def load_from_config(self, config):
        """Load settings from config object"""
        self._loading_config = True
        try:
            # System
            self.tray_enabled_switch.setChecked(config.get('tray_mode_enabled', False))
            
            # Discord
            discord = config.get('discord', {})
            self.discord_enabled_switch.setChecked(discord.get('enabled', False))
            self.webhook_input.setText(discord.get('webhook_url', ''))
            self.discord_startup_switch.setChecked(discord.get('post_startup_shutdown', True))
            self.discord_error_switch.setChecked(discord.get('error_enabled', True))
            self.discord_periodic_switch.setChecked(discord.get('periodic_enabled', False))
            self.periodic_interval_spin.setValue(discord.get('periodic_interval_minutes', 15))
            
            # Weather
            weather = config.get('weather', {})
            self.api_key_input.setText(weather.get('api_key', ''))
            self.location_input.setText(weather.get('location', ''))
            self.lat_input.setText(str(weather.get('latitude', '')))
            self.lon_input.setText(str(weather.get('longitude', '')))
            
            units = weather.get('units', 'metric')
            idx = 1 if units == 'imperial' else 0
            self.units_combo.setCurrentIndex(idx)
            
            # Cleanup
            self.cleanup_enabled_switch.setChecked(config.get('cleanup_enabled', False))
            self.cleanup_size_spin.setValue(config.get('cleanup_max_size_gb', 10))
            
        finally:
            self._loading_config = False
