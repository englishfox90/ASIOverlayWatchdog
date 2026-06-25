"""
Output Settings Panel
Settings for file output, web server, and Discord
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QFileDialog, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from qfluentwidgets import (
    CardWidget, SubtitleLabel, BodyLabel, CaptionLabel,
    PushButton, PrimaryPushButton, ComboBox, LineEdit,
    SpinBox, DoubleSpinBox, SwitchButton, ColorPickerButton,
    HyperlinkButton
)
from PySide6.QtGui import QColor

import os

from ..theme.tokens import Colors, Typography, Spacing, Layout
from ..theme.icons import mdi
from ..components.cards import SettingsCard, FormRow, SwitchRow, CollapsibleCard


class OutputSettingsPanel(QScrollArea):
    """
    Output settings panel with:
    - File output (directory, format, naming)
    - Web server settings
    - Discord integration
    """
    
    settings_changed = Signal()
    test_discord_requested = Signal()
    
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
        
        # === FILE OUTPUT ===
        file_card = SettingsCard(
            "File Output",
            "Save processed images to disk"
        )
        
        # Output directory
        dir_row = QHBoxLayout()
        dir_row.setSpacing(Spacing.sm)
        
        self.output_dir_input = LineEdit()
        self.output_dir_input.setPlaceholderText("Select output directory...")
        self.output_dir_input.textChanged.connect(self._on_output_dir_changed)
        dir_row.addWidget(self.output_dir_input, 1)
        
        browse_btn = PushButton("Browse")
        browse_btn.setIcon(mdi('folder-outline'))
        browse_btn.clicked.connect(self._browse_output_dir)
        dir_row.addWidget(browse_btn)
        
        dir_widget = QWidget()
        dir_widget.setLayout(dir_row)
        file_card.add_row("Output Directory", dir_widget)
        
        # Filename pattern
        self.filename_input = LineEdit()
        self.filename_input.setPlaceholderText("latestImage")
        self.filename_input.textChanged.connect(self._on_filename_changed)
        file_card.add_row("Filename", self.filename_input, "Base name for output files")
        
        # Output format
        self.format_combo = ComboBox()
        self.format_combo.addItems(["jpg", "png"])
        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        file_card.add_row("Format", self.format_combo)
        
        # JPG Quality
        self.quality_spin = SpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(85)
        self.quality_spin.valueChanged.connect(self._on_quality_changed)
        file_card.add_row("JPG Quality", self.quality_spin, "1-100 (only for JPG)")
        
        layout.addWidget(file_card)
        
        # === WEB SERVER ===
        web_card = CollapsibleCard("Web Server", mdi('web'))
        
        self.web_enabled_switch = SwitchRow(
            "Enable Web Server",
            "Serve latest image via HTTP"
        )
        self.web_enabled_switch.toggled.connect(self._on_web_enabled_changed)
        web_card.add_widget(self.web_enabled_switch)
        
        # Host
        self.web_host_input = LineEdit()
        self.web_host_input.setPlaceholderText("127.0.0.1")
        self.web_host_input.textChanged.connect(self._on_web_settings_changed)
        web_card.add_row("Host", self.web_host_input)
        
        # Port
        self.web_port_spin = SpinBox()
        self.web_port_spin.setRange(1, 65535)
        self.web_port_spin.setValue(8080)
        self.web_port_spin.valueChanged.connect(self._on_web_settings_changed)
        web_card.add_row("Port", self.web_port_spin)
        
        # Path
        self.web_path_input = LineEdit()
        self.web_path_input.setPlaceholderText("/latest")
        self.web_path_input.textChanged.connect(self._on_web_settings_changed)
        web_card.add_row("Image Path", self.web_path_input, "URL path to latest image")

        # Self-documenting API reference — opens the live /docs page (works
        # offline; rendered from the server's own OpenAPI spec).
        self.api_docs_link = HyperlinkButton("http://127.0.0.1:8080/docs", "Open API Docs")
        web_card.add_row("API Docs", self.api_docs_link,
                         "Interactive reference for /latest, /status, /openapi.json")
        self._update_api_docs_url()

        layout.addWidget(web_card)
        
        # === DISCORD ===
        discord_card = CollapsibleCard("Discord Integration", mdi('webhook'))
        
        self.discord_enabled_switch = SwitchRow(
            "Enable Discord Alerts",
            "Send notifications to Discord channel"
        )
        self.discord_enabled_switch.toggled.connect(self._on_discord_enabled_changed)
        discord_card.add_widget(self.discord_enabled_switch)
        
        # Webhook URL
        webhook_row = QHBoxLayout()
        webhook_row.setSpacing(Spacing.sm)
        
        self.webhook_input = LineEdit()
        self.webhook_input.setPlaceholderText("https://discord.com/api/webhooks/...")
        self.webhook_input.setEchoMode(LineEdit.Password)
        self.webhook_input.textChanged.connect(self._on_discord_settings_changed)
        webhook_row.addWidget(self.webhook_input, 1)
        
        self.show_webhook_btn = PushButton("Show")
        self.show_webhook_btn.setCheckable(True)
        self.show_webhook_btn.clicked.connect(self._toggle_webhook_visibility)
        webhook_row.addWidget(self.show_webhook_btn)
        
        webhook_widget = QWidget()
        webhook_widget.setLayout(webhook_row)
        discord_card.add_row("Webhook URL", webhook_widget, "Get from Discord Server Settings → Integrations")
        
        # Post errors
        self.post_errors_switch = SwitchRow("Post Errors", "Send error messages to Discord")
        self.post_errors_switch.toggled.connect(self._on_discord_settings_changed)
        discord_card.add_widget(self.post_errors_switch)
        
        # Post lifecycle
        self.post_lifecycle_switch = SwitchRow("Post Start/Stop", "Send capture start/stop messages")
        self.post_lifecycle_switch.toggled.connect(self._on_discord_settings_changed)
        discord_card.add_widget(self.post_lifecycle_switch)

        # Post timelapse
        self.post_timelapse_switch = SwitchRow(
            "Post Timelapse Video",
            "Upload completed timelapse video (up to 8 MB, camera mode only)"
        )
        self.post_timelapse_switch.toggled.connect(self._on_discord_settings_changed)
        discord_card.add_widget(self.post_timelapse_switch)

        # Post roof changes
        self.post_roof_changes_switch = SwitchRow(
            "Post Roof Changes",
            "Send notification when ML detects a roof open/close event"
        )
        self.post_roof_changes_switch.toggled.connect(self._on_discord_settings_changed)
        discord_card.add_widget(self.post_roof_changes_switch)

        # Periodic posts
        self.periodic_switch = SwitchRow("Periodic Updates", "Post images at regular intervals")
        self.periodic_switch.toggled.connect(self._on_periodic_toggle)
        discord_card.add_widget(self.periodic_switch)
        
        # Periodic options container (shown/hidden based on toggle)
        self.periodic_options = QWidget()
        periodic_layout = QVBoxLayout(self.periodic_options)
        periodic_layout.setContentsMargins(0, 0, 0, 0)
        periodic_layout.setSpacing(Spacing.input_gap)
        
        self.periodic_interval_spin = SpinBox()
        self.periodic_interval_spin.setRange(30, 1440)
        self.periodic_interval_spin.setValue(60)
        self.periodic_interval_spin.setSuffix(" min")
        self.periodic_interval_spin.valueChanged.connect(self._on_discord_settings_changed)
        periodic_layout.addWidget(FormRow("Interval", self.periodic_interval_spin))

        self.periodic_jitter_label = CaptionLabel(
            "A random offset of up to 5 minutes is applied each cycle to reduce network load"
        )
        self.periodic_jitter_label.setWordWrap(True)
        self.periodic_jitter_label.setObjectName("hintLabel")
        periodic_layout.addWidget(self.periodic_jitter_label)

        # Include image
        self.include_image_switch = SwitchRow("Include Latest Image", "Attach image to Discord posts")
        self.include_image_switch.set_checked(True)
        self.include_image_switch.toggled.connect(self._on_discord_settings_changed)
        periodic_layout.addWidget(self.include_image_switch)
        
        self.periodic_options.hide()
        discord_card.add_widget(self.periodic_options)
        
        # Embed Color (wrap in container for proper alignment)
        color_container = QWidget()
        color_layout = QHBoxLayout(color_container)
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.setSpacing(Spacing.sm)
        
        self.embed_color_picker = ColorPickerButton(QColor('#0EA5E9'), 'Embed Color')
        self.embed_color_picker.setFixedSize(80, 32)
        self.embed_color_picker.colorChanged.connect(self._on_embed_color_changed)
        color_layout.addWidget(self.embed_color_picker)
        color_layout.addStretch()
        
        discord_card.add_row("Embed Color", color_container, "Color for Discord message embeds")
        
        # Test button and status
        test_row = QHBoxLayout()
        test_row.setSpacing(Spacing.sm)
        
        self.test_discord_btn = PushButton("Test Webhook")
        self.test_discord_btn.setIcon(mdi('send'))
        self.test_discord_btn.clicked.connect(self._test_discord)
        test_row.addWidget(self.test_discord_btn)
        
        self.discord_status_label = CaptionLabel("")
        test_row.addWidget(self.discord_status_label)
        test_row.addStretch()
        
        test_widget = QWidget()
        test_widget.setLayout(test_row)
        discord_card.add_widget(test_widget)
        
        layout.addWidget(discord_card)

        # === CLEANUP ===
        cleanup_card = CollapsibleCard("Storage Cleanup", mdi('broom'))
        
        self.cleanup_enabled_switch = SwitchRow(
            "Enable Auto Cleanup",
            "Automatically delete old files to manage disk space"
        )
        self.cleanup_enabled_switch.toggled.connect(self._on_cleanup_settings_changed)
        cleanup_card.add_widget(self.cleanup_enabled_switch)
        
        # Max size
        self.max_size_spin = DoubleSpinBox()
        self.max_size_spin.setRange(0.1, 1000.0)
        self.max_size_spin.setDecimals(1)
        self.max_size_spin.setValue(10.0)
        self.max_size_spin.setSuffix(" GB")
        self.max_size_spin.valueChanged.connect(self._on_cleanup_settings_changed)
        cleanup_card.add_row("Max Size", self.max_size_spin, "Delete old files when exceeded")
        
        # Strategy
        self.cleanup_strategy_combo = ComboBox()
        self.cleanup_strategy_combo.addItems(["oldest", "largest"])
        self.cleanup_strategy_combo.currentTextChanged.connect(self._on_cleanup_settings_changed)
        cleanup_card.add_row("Strategy", self.cleanup_strategy_combo, "Which files to delete first")
        
        layout.addWidget(cleanup_card)

        # === IMAGE LIBRARY ===
        library_card = CollapsibleCard("Image Library", mdi('image-multiple'))

        self.library_enabled_switch = SwitchRow(
            "Enable Library",
            "Keep a browsable history of downscaled frames (in-app + web API)"
        )
        self.library_enabled_switch.toggled.connect(self._on_library_settings_changed)
        library_card.add_widget(self.library_enabled_switch)

        self.library_retention_spin = SpinBox()
        self.library_retention_spin.setRange(1, 365)
        self.library_retention_spin.setSuffix(" days")
        self.library_retention_spin.valueChanged.connect(self._on_library_settings_changed)
        library_card.add_row("Retention", self.library_retention_spin,
                             "Keep images for this many days")

        self.library_max_size_spin = DoubleSpinBox()
        self.library_max_size_spin.setRange(0.1, 1000.0)
        self.library_max_size_spin.setDecimals(1)
        self.library_max_size_spin.setSuffix(" GB")
        self.library_max_size_spin.valueChanged.connect(self._on_library_settings_changed)
        library_card.add_row("Max Size", self.library_max_size_spin,
                             "Prune oldest once the library exceeds this size")

        self.library_max_dim_spin = SpinBox()
        self.library_max_dim_spin.setRange(100, 4000)
        self.library_max_dim_spin.setSuffix(" px")
        self.library_max_dim_spin.valueChanged.connect(self._on_library_settings_changed)
        library_card.add_row("Max Dimension", self.library_max_dim_spin,
                             "Longest edge of stored images")

        self.library_quality_spin = SpinBox()
        self.library_quality_spin.setRange(1, 95)
        self.library_quality_spin.valueChanged.connect(self._on_library_settings_changed)
        library_card.add_row("JPEG Quality", self.library_quality_spin, "1-95")

        self.library_api_switch = SwitchRow(
            "Expose Web API",
            "Serve /library and /library/image from the web server"
        )
        self.library_api_switch.toggled.connect(self._on_library_settings_changed)
        library_card.add_widget(self.library_api_switch)

        layout.addWidget(library_card)

        layout.addStretch()
    
    # === EVENT HANDLERS ===
    
    def _browse_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.output_dir_input.setText(dir_path)
    
    def _on_output_dir_changed(self, text):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('output_directory', text)
            self.settings_changed.emit()
    
    def _on_filename_changed(self, text):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('filename_pattern', text)
            self.settings_changed.emit()
    
    def _on_format_changed(self, text):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('output_format', text)
            self.settings_changed.emit()
    
    def _on_quality_changed(self, value):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('jpg_quality', value)
            self.settings_changed.emit()
    
    def _on_web_enabled_changed(self, checked):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            output = self.main_window.config.get('output', {})
            output['webserver_enabled'] = checked
            self.main_window.config.set('output', output)
            self.settings_changed.emit()
    
    def _on_web_settings_changed(self):
        self._update_api_docs_url()
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            output = self.main_window.config.get('output', {})
            output['webserver_host'] = self.web_host_input.text()
            output['webserver_port'] = self.web_port_spin.value()
            output['webserver_path'] = self.web_path_input.text()
            self.main_window.config.set('output', output)
            self.settings_changed.emit()

    def _update_api_docs_url(self):
        """Point the API Docs link at the current host/port (browser-friendly)."""
        if not hasattr(self, 'api_docs_link'):
            return
        host = (self.web_host_input.text() or '127.0.0.1').strip()
        if host in ('0.0.0.0', '', '::'):
            host = '127.0.0.1'  # wildcard bind isn't browseable; use loopback
        port = self.web_port_spin.value()
        docs_path = '/docs'
        if self.main_window and hasattr(self.main_window, 'config'):
            docs_path = self.main_window.config.get('output', {}).get('webserver_docs_path', '/docs')
        self.api_docs_link.setUrl(f"http://{host}:{port}{docs_path}")
    
    def _on_discord_enabled_changed(self, checked):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            discord = self.main_window.config.get('discord', {})
            discord['enabled'] = checked
            self.main_window.config.set('discord', discord)
            self.settings_changed.emit()
    
    def _toggle_webhook_visibility(self):
        """Toggle webhook URL visibility"""
        if self.show_webhook_btn.isChecked():
            self.webhook_input.setEchoMode(LineEdit.Normal)
            self.show_webhook_btn.setText("Hide")
        else:
            self.webhook_input.setEchoMode(LineEdit.Password)
            self.show_webhook_btn.setText("Show")
    
    def _on_periodic_toggle(self, checked):
        """Show/hide periodic options based on toggle"""
        self.periodic_options.setVisible(checked)
        if not self._loading_config:
            self._on_discord_settings_changed()
    
    def _on_embed_color_changed(self, color: QColor):
        """Save embed color to config"""
        if self._loading_config:
            return
        hex_color = color.name()  # Returns #RRGGBB format
        
        if self.main_window and hasattr(self.main_window, 'config'):
            discord = self.main_window.config.get('discord', {})
            discord['embed_color_hex'] = hex_color
            self.main_window.config.set('discord', discord)
            self.settings_changed.emit()
    
    def _on_discord_settings_changed(self):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            discord = self.main_window.config.get('discord', {})
            discord['webhook_url'] = self.webhook_input.text()
            discord['post_errors'] = self.post_errors_switch.is_checked()
            discord['post_startup_shutdown'] = self.post_lifecycle_switch.is_checked()
            discord['post_timelapse'] = self.post_timelapse_switch.is_checked()
            discord['post_roof_changes'] = self.post_roof_changes_switch.is_checked()
            discord['periodic_enabled'] = self.periodic_switch.is_checked()
            discord['periodic_interval_minutes'] = self.periodic_interval_spin.value()
            discord['include_latest_image'] = self.include_image_switch.is_checked()
            discord['embed_color_hex'] = self.embed_color_picker.color.name()
            self.main_window.config.set('discord', discord)
            self.settings_changed.emit()
    
    def _test_discord(self):
        """Test Discord webhook - emit signal for main window to handle"""
        webhook_url = self.webhook_input.text().strip()
        if not webhook_url:
            self.set_discord_test_result(False, "Webhook URL required")
            return
        
        self.discord_status_label.setText("Testing...")
        self.discord_status_label.setStyleSheet(f"color: {Colors.text_muted};")
        self.test_discord_requested.emit()
    
    def set_discord_test_result(self, success: bool, message: str):
        """Update Discord test result display"""
        if success:
            self.discord_status_label.setText(f"✓ {message}")
            self.discord_status_label.setStyleSheet(f"color: {Colors.status_success};")
        else:
            self.discord_status_label.setText(f"❌ {message}")
            self.discord_status_label.setStyleSheet(f"color: {Colors.status_error};")
    
    def _on_cleanup_settings_changed(self):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            self.main_window.config.set('cleanup_enabled', self.cleanup_enabled_switch.is_checked())
            self.main_window.config.set('cleanup_max_size_gb', self.max_size_spin.value())
            self.main_window.config.set('cleanup_strategy', self.cleanup_strategy_combo.currentText())
            self.settings_changed.emit()

    def _on_library_settings_changed(self):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            library = self.main_window.config.get('library', {})
            library['enabled'] = self.library_enabled_switch.is_checked()
            library['retention_days'] = self.library_retention_spin.value()
            library['max_size_gb'] = self.library_max_size_spin.value()
            library['max_dimension'] = self.library_max_dim_spin.value()
            library['jpeg_quality'] = self.library_quality_spin.value()
            library['api_enabled'] = self.library_api_switch.is_checked()
            self.main_window.config.set('library', library)
            self.settings_changed.emit()

    # === CONFIG LOADING ===
    
    def load_from_config(self, config):
        """Load settings from config object"""
        self._loading_config = True
        try:
            # File output
            self.output_dir_input.setText(config.get('output_directory', ''))
            self.filename_input.setText(config.get('filename_pattern', 'latestImage'))
            
            fmt = config.get('output_format', 'jpg')
            idx = self.format_combo.findText(fmt)
            if idx >= 0:
                self.format_combo.setCurrentIndex(idx)
            
            self.quality_spin.setValue(config.get('jpg_quality', 85))
            
            # Web server
            output = config.get('output', {})
            self.web_enabled_switch.set_checked(output.get('webserver_enabled', False))
            self.web_host_input.setText(output.get('webserver_host', '127.0.0.1'))
            self.web_port_spin.setValue(output.get('webserver_port', 8080))
            self.web_path_input.setText(output.get('webserver_path', '/latest'))
            self._update_api_docs_url()

            # Discord
            discord = config.get('discord', {})
            self.discord_enabled_switch.set_checked(discord.get('enabled', False))
            self.webhook_input.setText(discord.get('webhook_url', ''))
            self.post_errors_switch.set_checked(discord.get('post_errors', False))
            self.post_lifecycle_switch.set_checked(discord.get('post_startup_shutdown', False))
            self.post_timelapse_switch.set_checked(discord.get('post_timelapse', False))
            self.post_roof_changes_switch.set_checked(discord.get('post_roof_changes', False))

            periodic_enabled = discord.get('periodic_enabled', False)
            self.periodic_switch.set_checked(periodic_enabled)
            self.periodic_options.setVisible(periodic_enabled)
            self.periodic_interval_spin.setValue(discord.get('periodic_interval_minutes', 60))
            self.include_image_switch.set_checked(discord.get('include_latest_image', True))
            
            # Embed color
            embed_color = discord.get('embed_color_hex', '#0EA5E9')
            self.embed_color_picker.setColor(QColor(embed_color))
            
            # Cleanup
            self.cleanup_enabled_switch.set_checked(config.get('cleanup_enabled', False))
            self.max_size_spin.setValue(config.get('cleanup_max_size_gb', 10.0))
            strategy = config.get('cleanup_strategy', 'oldest')
            idx = self.cleanup_strategy_combo.findText(strategy)
            if idx >= 0:
                self.cleanup_strategy_combo.setCurrentIndex(idx)

            # Image Library
            library = config.get('library', {})
            self.library_enabled_switch.set_checked(library.get('enabled', True))
            self.library_retention_spin.setValue(library.get('retention_days', 7))
            self.library_max_size_spin.setValue(library.get('max_size_gb', 2.0))
            self.library_max_dim_spin.setValue(library.get('max_dimension', 750))
            self.library_quality_spin.setValue(library.get('jpeg_quality', 85))
            self.library_api_switch.set_checked(library.get('api_enabled', True))
        finally:
            self._loading_config = False
