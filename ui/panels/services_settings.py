"""
Services Settings Panel
Weather API and other service integrations
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


class ServicesSettingsPanel(QScrollArea):
    """
    Services settings panel with:
    - Weather API (OpenWeatherMap)
    - RTSP streaming (if ffmpeg available)
    """
    
    settings_changed = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self._ffmpeg_available = is_ffmpeg_available()
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
        api_row.addWidget(self.api_key_input, 1)
        
        self.show_key_btn = PushButton("Show")
        self.show_key_btn.setCheckable(True)
        self.show_key_btn.clicked.connect(self._toggle_api_key_visibility)
        api_row.addWidget(self.show_key_btn)
        
        api_widget = QWidget()
        api_widget.setLayout(api_row)
        weather_card.add_row("API Key", api_widget)
        
        # Location (city name)
        self.location_input = LineEdit()
        self.location_input.setPlaceholderText("City name (e.g., London,GB)")
        self.location_input.textChanged.connect(self._on_weather_changed)
        weather_card.add_row("Location", self.location_input, "City,CountryCode format")
        
        # Coordinates row
        coord_row = QHBoxLayout()
        coord_row.setSpacing(Spacing.sm)
        
        self.lat_input = LineEdit()
        self.lat_input.setPlaceholderText("Latitude")
        self.lat_input.setMaximumWidth(120)
        self.lat_input.textChanged.connect(self._on_weather_changed)
        coord_row.addWidget(self.lat_input)
        
        self.lon_input = LineEdit()
        self.lon_input.setPlaceholderText("Longitude")
        self.lon_input.setMaximumWidth(120)
        self.lon_input.textChanged.connect(self._on_weather_changed)
        coord_row.addWidget(self.lon_input)
        
        coord_row.addStretch()
        
        coord_widget = QWidget()
        coord_widget.setLayout(coord_row)
        weather_card.add_row("Coordinates", coord_widget, "Preferred if both location and coordinates provided")
        
        # Units
        self.units_combo = ComboBox()
        self.units_combo.addItems(["metric (°C)", "imperial (°F)"])
        self.units_combo.currentTextChanged.connect(self._on_weather_changed)
        weather_card.add_row("Units", self.units_combo)
        
        # Test button row
        test_row = QHBoxLayout()
        test_row.setSpacing(Spacing.sm)
        
        self.test_weather_btn = PushButton("Test Connection")
        self.test_weather_btn.setIcon(FluentIcon.GLOBE)
        self.test_weather_btn.clicked.connect(self._test_weather)
        test_row.addWidget(self.test_weather_btn)
        
        self.weather_status_label = CaptionLabel("")
        self.weather_status_label.setStyleSheet(f"color: {Colors.text_muted};")
        test_row.addWidget(self.weather_status_label)
        test_row.addStretch()
        
        test_widget = QWidget()
        test_widget.setLayout(test_row)
        weather_card.add_widget(test_widget)
        
        layout.addWidget(weather_card)
        
        # === RTSP STREAMING (only if ffmpeg available) ===
        if self._ffmpeg_available:
            rtsp_card = CollapsibleCard("RTSP Streaming", FluentIcon.VIDEO)
            
            self.rtsp_enabled_switch = SwitchRow(
                "Enable RTSP Server",
                "Stream images via RTSP protocol"
            )
            self.rtsp_enabled_switch.toggled.connect(self._on_rtsp_changed)
            rtsp_card.add_widget(self.rtsp_enabled_switch)
            
            # Host
            self.rtsp_host_input = LineEdit()
            self.rtsp_host_input.setPlaceholderText("0.0.0.0")
            self.rtsp_host_input.textChanged.connect(self._on_rtsp_changed)
            rtsp_card.add_row("Host", self.rtsp_host_input, "0.0.0.0 for all interfaces")
            
            # Port
            self.rtsp_port_spin = SpinBox()
            self.rtsp_port_spin.setRange(1, 65535)
            self.rtsp_port_spin.setValue(8554)
            self.rtsp_port_spin.valueChanged.connect(self._on_rtsp_changed)
            rtsp_card.add_row("Port", self.rtsp_port_spin)
            
            # Stream name
            self.rtsp_stream_input = LineEdit()
            self.rtsp_stream_input.setPlaceholderText("asiwatchdog")
            self.rtsp_stream_input.textChanged.connect(self._on_rtsp_changed)
            rtsp_card.add_row("Stream Name", self.rtsp_stream_input, "rtsp://host:port/name")
            
            # FPS
            self.rtsp_fps_spin = DoubleSpinBox()
            self.rtsp_fps_spin.setRange(0.1, 30.0)
            self.rtsp_fps_spin.setDecimals(1)
            self.rtsp_fps_spin.setValue(1.0)
            self.rtsp_fps_spin.valueChanged.connect(self._on_rtsp_changed)
            rtsp_card.add_row("FPS", self.rtsp_fps_spin, "Frames per second")
            
            layout.addWidget(rtsp_card)
        
        layout.addStretch()
    
    def _toggle_api_key_visibility(self):
        """Toggle API key visibility"""
        if self.show_key_btn.isChecked():
            self.api_key_input.setEchoMode(LineEdit.Normal)
            self.show_key_btn.setText("Hide")
        else:
            self.api_key_input.setEchoMode(LineEdit.Password)
            self.show_key_btn.setText("Show")
    
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
            # Parse units from combo text
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
    
    def _on_rtsp_changed(self):
        """Handle RTSP settings change"""
        if not self._ffmpeg_available:
            return
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            output = self.main_window.config.get('output', {})
            output['rtsp_enabled'] = self.rtsp_enabled_switch.is_checked()
            output['rtsp_host'] = self.rtsp_host_input.text()
            output['rtsp_port'] = self.rtsp_port_spin.value()
            output['rtsp_stream_name'] = self.rtsp_stream_input.text()
            output['rtsp_fps'] = self.rtsp_fps_spin.value()
            self.main_window.config.set('output', output)
            self.settings_changed.emit()
    
    def load_from_config(self, config):
        """Load settings from config object"""
        self._loading_config = True
        try:
            # Weather
            weather = config.get('weather', {})
            self.api_key_input.setText(weather.get('api_key', ''))
            self.location_input.setText(weather.get('location', ''))
            self.lat_input.setText(str(weather.get('latitude', '')))
            self.lon_input.setText(str(weather.get('longitude', '')))
            
            units = weather.get('units', 'metric')
            idx = 1 if units == 'imperial' else 0
            self.units_combo.setCurrentIndex(idx)
            
            # RTSP (only if available)
            if self._ffmpeg_available:
                output = config.get('output', {})
                self.rtsp_enabled_switch.set_checked(output.get('rtsp_enabled', False))
                self.rtsp_host_input.setText(output.get('rtsp_host', '0.0.0.0'))
                self.rtsp_port_spin.setValue(output.get('rtsp_port', 8554))
                self.rtsp_stream_input.setText(output.get('rtsp_stream_name', 'asiwatchdog'))
                self.rtsp_fps_spin.setValue(output.get('rtsp_fps', 1.0))
        finally:
            self._loading_config = False
