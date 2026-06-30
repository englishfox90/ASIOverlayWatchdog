"""
Settings Panel
Application settings: Discord, Weather, Storage, System
"""
import webbrowser
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QSizePolicy, QPushButton
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from qfluentwidgets import (
    CardWidget, SubtitleLabel, BodyLabel, CaptionLabel,
    PushButton, PrimaryPushButton, ComboBox, LineEdit,
    SpinBox, DoubleSpinBox, SwitchButton
)
from ..theme.accent_themes import ACCENT_PRESETS

from version import __version__
from ..theme.tokens import Colors, Typography, Spacing, Layout
from ..theme.icons import mdi
from ..components.cards import SettingsCard, FormRow, SwitchRow, CollapsibleCard
from services.ffmpeg_utils import is_ffmpeg_available  # noqa: F401 – re-exported for legacy callers


class SettingsPanel(QScrollArea):
    """
    Application settings panel with:
    - System settings (tray mode)
    - Discord alerts
    - Weather API
    - Storage cleanup
    """
    
    settings_changed = Signal()
    accent_changed = Signal(str)   # emits preset name
    
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
        
        # === APPEARANCE ===
        appearance_card = SettingsCard(
            "Appearance",
            "Accent colour — dark theme is always preserved"
        )

        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(Spacing.sm)
        swatch_row.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self._accent_swatches: dict[str, QPushButton] = {}
        for key, preset in ACCENT_PRESETS.items():
            btn = QPushButton()
            btn.setFixedSize(28, 28)
            btn.setCheckable(True)
            btn.setToolTip(preset['label'])
            swatch_color = preset['swatch']
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {swatch_color};
                    border-radius: 14px;
                    border: 2px solid transparent;
                }}
                QPushButton:hover {{ border-color: rgba(255,255,255,0.5); }}
                QPushButton:checked {{ border-color: white; border-width: 3px; }}
            """)
            btn.clicked.connect(lambda checked, k=key: self._on_accent_changed(k))
            swatch_row.addWidget(btn)
            self._accent_swatches[key] = btn

        swatch_widget = QWidget()
        swatch_widget.setLayout(swatch_row)
        appearance_card.add_row("Accent", swatch_widget)
        layout.addWidget(appearance_card)

        # === SYSTEM SETTINGS ===
        system_card = SettingsCard(
            "System",
            "Application behavior settings"
        )
        
        # System tray mode
        tray_row = SwitchRow(
            "Enable System Tray",
            "Run in the background: minimize to tray on close, and start hidden "
            "when launched on login. Turn off to keep the window visible."
        )
        self.tray_enabled_switch = tray_row.switch
        self.tray_enabled_switch.checkedChanged.connect(self._on_system_changed)
        system_card.add_widget(tray_row)

        # Run on Windows startup
        startup_row = SwitchRow(
            "Start with Windows",
            "Launch automatically on logon (scheduled task; expect a one-time admin prompt)"
        )
        self.startup_switch = startup_row.switch
        self.startup_switch.checkedChanged.connect(self._on_startup_changed)
        system_card.add_widget(startup_row)

        # Auto-start capture when launched on startup
        autostart_capture_row = SwitchRow(
            "Auto-start capture on launch",
            "Begin capturing with the saved camera automatically when the app starts"
        )
        self.autostart_capture_switch = autostart_capture_row.switch
        self.autostart_capture_switch.checkedChanged.connect(self._on_startup_changed)
        system_card.add_widget(autostart_capture_row)

        # Analytics opt-out
        analytics_row = SwitchRow(
            "Send Anonymous Usage Data",
            "Help improve PFR Sentinel by sharing anonymous feature usage and error reports"
        )
        self.analytics_switch = analytics_row.switch
        self.analytics_switch.checkedChanged.connect(self._on_analytics_changed)
        system_card.add_widget(analytics_row)

        layout.addWidget(system_card)
        
        # === DISCORD ALERTS (cross-reference) ===
        discord_ref_card = SettingsCard(
            "Discord Alerts",
            "Webhook, notifications, and periodic updates"
        )
        discord_ref_label = CaptionLabel(
            "Discord settings have moved to the Output Settings panel "
            "where all output channels are configured together."
        )
        discord_ref_label.setWordWrap(True)
        discord_ref_label.setStyleSheet(f"color: {Colors.text_muted}; padding: 4px;")
        discord_ref_card.add_widget(discord_ref_label)
        layout.addWidget(discord_ref_card)
        
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
        link_btn.setIcon(mdi('open-in-new'))
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
        self.test_weather_btn.setIcon(mdi('refresh'))
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
        self.lat_input.setPlaceholderText("Latitude (e.g. 31.33)")
        self.lat_input.textChanged.connect(self._on_weather_changed)
        self.lat_input.editingFinished.connect(
            lambda: self._commit_coordinate(self.lat_input, 'latitude', False))
        coord_row.addWidget(self.lat_input)

        self.lon_input = LineEdit()
        self.lon_input.setPlaceholderText("Longitude (e.g. -100.46)")
        self.lon_input.textChanged.connect(self._on_weather_changed)
        self.lon_input.editingFinished.connect(
            lambda: self._commit_coordinate(self.lon_input, 'longitude', True))
        coord_row.addWidget(self.lon_input)

        self.elevation_input = LineEdit()
        self.elevation_input.setPlaceholderText("Elevation (m)")
        self.elevation_input.setMaximumWidth(120)
        self.elevation_input.textChanged.connect(self._on_weather_changed)
        coord_row.addWidget(self.elevation_input)

        coord_widget = QWidget()
        coord_widget.setLayout(coord_row)
        weather_card.add_row("Coordinates", coord_widget, "Alternative to location name (elevation for refraction correction)")
        
        # Units
        self.units_combo = ComboBox()
        self.units_combo.addItems(["Metric (°C, m/s)", "Imperial (°F, mph)"])
        self.units_combo.currentIndexChanged.connect(self._on_weather_changed)
        weather_card.add_row("Units", self.units_combo)
        
        layout.addWidget(weather_card)
        
        # === STORAGE CLEANUP (cross-reference) ===
        cleanup_ref_card = SettingsCard(
            "Storage Cleanup",
            "Automatic cleanup of old images"
        )
        cleanup_ref_label = CaptionLabel(
            "Storage cleanup settings have moved to the Output Settings panel "
            "alongside file output configuration."
        )
        cleanup_ref_label.setWordWrap(True)
        cleanup_ref_label.setStyleSheet(f"color: {Colors.text_muted}; padding: 4px;")
        cleanup_ref_card.add_widget(cleanup_ref_label)
        layout.addWidget(cleanup_ref_card)
        
        # === ABOUT & UPDATES ===
        about_card = SettingsCard(
            "About & Updates",
            f"PFR Sentinel v{__version__}"
        )
        
        # Version info
        version_info = CaptionLabel(
            f"Version: {__version__}\n"
            "Check for updates manually or wait for automatic check (24h after startup)"
        )
        version_info.setStyleSheet(f"color: {Colors.text_secondary}; padding: 8px;")
        version_info.setWordWrap(True)
        about_card.add_widget(version_info)
        
        # Update buttons row
        update_btn_row = QHBoxLayout()
        update_btn_row.setSpacing(Spacing.sm)
        
        self.check_updates_btn = PrimaryPushButton("Check for Updates")
        self.check_updates_btn.setIcon(mdi('refresh'))
        self.check_updates_btn.clicked.connect(self._check_for_updates)
        update_btn_row.addWidget(self.check_updates_btn)
        
        self.github_btn = PushButton("GitHub Releases")
        self.github_btn.setIcon(mdi('github'))
        self.github_btn.clicked.connect(self._open_github_releases)
        update_btn_row.addWidget(self.github_btn)
        
        update_btn_row.addStretch()
        
        update_btn_widget = QWidget()
        update_btn_widget.setLayout(update_btn_row)
        about_card.add_widget(update_btn_widget)
        
        layout.addWidget(about_card)
        
        layout.addStretch()
    
    def _on_accent_changed(self, key: str):
        """Handle accent swatch click."""
        if self._loading_config:
            return
        for k, btn in self._accent_swatches.items():
            btn.setChecked(k == key)
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('ui_accent', key)
            self.main_window.config.save()
        self.accent_changed.emit(key)

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

    def _on_startup_changed(self):
        """Handle 'Start with Windows' / 'Auto-start capture' toggles.

        Both feed the same scheduled-task registration: the auto-start switch
        only changes the command the task runs, so toggling it re-registers the
        task when startup is enabled. Registration (and any UAC prompt + revert)
        is owned by main_window.set_run_on_startup.
        """
        if self._loading_config:
            return
        if not (self.main_window and hasattr(self.main_window, 'set_run_on_startup')):
            return
        enabled = self.startup_switch.isChecked()
        auto_start = self.autostart_capture_switch.isChecked()
        self.main_window.set_run_on_startup(enabled, auto_start)

    def refresh_startup_switches(self, config):
        """Re-sync the startup switches to actual state without firing handlers."""
        self._loading_config = True
        try:
            self.startup_switch.setChecked(config.get('run_on_startup', False))
            self.autostart_capture_switch.setChecked(config.get('autostart_capture', True))
        finally:
            self._loading_config = False

    def _on_analytics_changed(self):
        """Handle analytics opt-in/out toggle"""
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            enabled = self.analytics_switch.isChecked()
            self.main_window.config.set('analytics_enabled', enabled)
            self.main_window.config.save()
            from services.posthog_service import set_enabled
            set_enabled(enabled)
    
    def _on_weather_changed(self):
        """Handle weather settings change"""
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            weather = self.main_window.config.get('weather', {})
            weather['api_key'] = self.api_key_input.text()
            weather['location'] = self.location_input.text()
            # Coordinates are normalised to canonical signed decimal before they
            # reach config, so the rest of the app never sees an unparseable
            # string. Mid-edit text that doesn't parse yet keeps the last good
            # value rather than clobbering it; the editingFinished handler does
            # the final rewrite + error feedback.
            weather['latitude'] = self._normalise_coord(
                self.lat_input.text(), weather.get('latitude', ''), False)
            weather['longitude'] = self._normalise_coord(
                self.lon_input.text(), weather.get('longitude', ''), True)
            weather['elevation'] = self.elevation_input.text()
            units_text = self.units_combo.currentText()
            weather['units'] = 'imperial' if 'imperial' in units_text else 'metric'
            self.main_window.config.set('weather', weather)
            self.settings_changed.emit()

    @staticmethod
    def _normalise_coord(text: str, previous, is_longitude: bool):
        """Canonical decimal string for parseable input; preserve last good value otherwise."""
        from services.coordinates import parse_coordinate, to_decimal_string
        if not text.strip():
            return ''
        val = parse_coordinate(text, is_longitude)
        if val is None:
            return previous  # don't overwrite a good value with mid-typed/garbage text
        return to_decimal_string(val)

    def _commit_coordinate(self, field, key: str, is_longitude: bool) -> None:
        """On focus-out: rewrite the field to canonical decimal, or flag an error."""
        if self._loading_config:
            return
        if not (self.main_window and hasattr(self.main_window, 'config')):
            return
        from services.coordinates import parse_coordinate, to_decimal_string
        text = field.text().strip()
        weather = self.main_window.config.get('weather', {})
        if not text:
            weather[key] = ''
            self._set_coord_error(field, False)
        else:
            val = parse_coordinate(text, is_longitude)
            if val is None:
                weather[key] = ''  # refuse to persist an unparseable coordinate
                self._set_coord_error(field, True)
                self.weather_status_label.setText(
                    "❌ Invalid coordinate — use decimal degrees (e.g. 31.33 or -100.46)")
                self.weather_status_label.setStyleSheet(f"color: {Colors.status_error};")
            else:
                canonical = to_decimal_string(val)
                weather[key] = canonical
                self._set_coord_error(field, False)
                if field.text() != canonical:
                    field.blockSignals(True)
                    field.setText(canonical)
                    field.blockSignals(False)
        self.main_window.config.set('weather', weather)
        self.main_window.config.save()
        self.settings_changed.emit()

    def _set_coord_error(self, field, is_error: bool) -> None:
        """Toggle a red error border on a coordinate field."""
        field.setStyleSheet(
            f"border: 1px solid {Colors.status_error};" if is_error else "")
    
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
    
    def _check_for_updates(self):
        """Manually check for updates"""
        if self.main_window and hasattr(self.main_window, 'check_for_updates_now'):
            self.check_updates_btn.setEnabled(False)
            self.check_updates_btn.setText("Checking...")
            self.main_window.check_for_updates_now()
            # Re-enable after short delay
            from PySide6.QtCore import QTimer
            QTimer.singleShot(2000, lambda: self._reset_update_button())
    
    def _reset_update_button(self):
        """Reset update button state"""
        self.check_updates_btn.setEnabled(True)
        self.check_updates_btn.setText("Check for Updates")
    
    def _open_github_releases(self):
        """Open GitHub releases page"""
        webbrowser.open("https://github.com/englishfox90/PFRSentinel/releases")
    
    def load_from_config(self, config):
        """Load settings from config object"""
        self._loading_config = True
        try:
            # Appearance
            active_accent = config.get('ui_accent', 'iris')
            for key, btn in self._accent_swatches.items():
                btn.setChecked(key == active_accent)

            # System
            self.tray_enabled_switch.setChecked(config.get('tray_mode_enabled', False))
            self.analytics_switch.setChecked(config.get('analytics_enabled', True))

            # Startup — the scheduled task is authoritative, not the cached flag.
            from services import autostart
            self.startup_switch.setChecked(autostart.is_enabled())
            self.autostart_capture_switch.setChecked(config.get('autostart_capture', True))
            
            # Weather
            weather = config.get('weather', {})
            self.api_key_input.setText(weather.get('api_key', ''))
            self.location_input.setText(weather.get('location', ''))
            self.lat_input.setText(str(weather.get('latitude', '')))
            self.lon_input.setText(str(weather.get('longitude', '')))
            self.elevation_input.setText(str(weather.get('elevation', '')))
            
            units = weather.get('units', 'metric')
            idx = 1 if units == 'imperial' else 0
            self.units_combo.setCurrentIndex(idx)
            
        finally:
            self._loading_config = False
