"""
Output Settings Panel
Settings for file output, web server, and Discord
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QFileDialog, QSizePolicy, QApplication
)
from PySide6.QtCore import Qt, Signal
from qfluentwidgets import (
    CardWidget, SubtitleLabel, BodyLabel,
    PushButton, PrimaryPushButton, ComboBox, LineEdit,
    SpinBox, DoubleSpinBox, SwitchButton,
    HyperlinkButton
)
from PySide6.QtGui import QColor

import os

from ..theme.tokens import Colors, Typography, Spacing, Layout
from ..theme.icons import mdi
from ..components.cards import SettingsCard, SwitchRow, CollapsibleCard
from ._integration_cards import IntegrationCardsMixin


class OutputSettingsPanel(IntegrationCardsMixin, QScrollArea):
    """
    Output settings panel with:
    - File output (directory, format, naming)
    - Web server settings
    - Discord integration
    """
    
    settings_changed = Signal()
    test_discord_requested = Signal()
    test_hermes_requested = Signal()
    
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

        # --- Capture control API ---
        # Mutating routes, so opt-in and token-gated. Lets NINA (or curl, or a
        # phone bookmark) start and stop capture.
        self.control_enabled_switch = SwitchRow(
            "Enable Capture Control API",
            "Let NINA and other local tools start/stop capture"
        )
        self.control_enabled_switch.toggled.connect(self._on_control_enabled_changed)
        web_card.add_widget(self.control_enabled_switch)

        token_row = QHBoxLayout()
        token_row.setSpacing(Spacing.sm)

        # Read-only: the token is generated, never typed. Masked by default so
        # it can't be shoulder-surfed off a screenshot of the settings page.
        self.control_token_input = LineEdit()
        self.control_token_input.setReadOnly(True)
        self.control_token_input.setEchoMode(LineEdit.Password)
        self.control_token_input.setPlaceholderText("Enable the control API to generate a token")
        token_row.addWidget(self.control_token_input, 1)

        self.show_token_btn = PushButton("Show")
        self.show_token_btn.setCheckable(True)
        self.show_token_btn.clicked.connect(self._toggle_token_visibility)
        token_row.addWidget(self.show_token_btn)

        self.copy_token_btn = PushButton("Copy")
        self.copy_token_btn.setIcon(mdi('content-copy'))
        self.copy_token_btn.clicked.connect(self._copy_control_token)
        token_row.addWidget(self.copy_token_btn)

        self.regen_token_btn = PushButton("Regenerate")
        self.regen_token_btn.setIcon(mdi('refresh'))
        self.regen_token_btn.clicked.connect(self._regenerate_control_token)
        token_row.addWidget(self.regen_token_btn)

        token_widget = QWidget()
        token_widget.setLayout(token_row)
        web_card.add_row("API Token", token_widget,
                         "The bundled NINA scripts read this automatically — "
                         "you only need to copy it for other tools")

        layout.addWidget(web_card)
        
        # === DISCORD + HERMES ===
        # Built by IntegrationCardsMixin (ui/panels/_integration_cards.py) —
        # kept in a sibling module to stay under the file-size cap.
        self._build_integration_cards(layout)

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
                             "Longest edge of stored images (applies to new frames only)")

        self.library_quality_spin = SpinBox()
        self.library_quality_spin.setRange(1, 95)
        self.library_quality_spin.valueChanged.connect(self._on_library_settings_changed)
        library_card.add_row("JPEG Quality", self.library_quality_spin,
                             "1-95 (applies to new frames only)")

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

    # === CAPTURE CONTROL API ===

    def _on_control_enabled_changed(self, checked):
        if self._loading_config:
            return
        if not (self.main_window and hasattr(self.main_window, 'config')):
            return
        output = self.main_window.config.get('output', {})
        output['webserver_control_enabled'] = checked
        self.main_window.config.set('output', output)
        # Persist + reconcile the server first, then mint — minting reads the
        # flag we just wrote.
        self.settings_changed.emit()
        self._sync_control_token(mint=checked)

        if checked and not self.web_enabled_switch.is_checked():
            # The control routes ride on the web server; enabling one without
            # the other silently does nothing.
            self._notify_main_window(
                "Capture control needs the web server — enable it above.", "warning"
            )

    def _toggle_token_visibility(self):
        if self.show_token_btn.isChecked():
            self.control_token_input.setEchoMode(LineEdit.Normal)
            self.show_token_btn.setText("Hide")
        else:
            self.control_token_input.setEchoMode(LineEdit.Password)
            self.show_token_btn.setText("Show")

    def _copy_control_token(self):
        token = self.control_token_input.text()
        if not token:
            self._notify_main_window(
                "No token yet — enable the capture control API first.", "warning"
            )
            return
        QApplication.clipboard().setText(token)
        self._notify_main_window("API token copied to clipboard")

    def _regenerate_control_token(self):
        """Mint a fresh token, invalidating the old one."""
        if not (self.main_window and hasattr(self.main_window, 'regenerate_control_token')):
            return
        self.main_window.regenerate_control_token()
        self._sync_control_token(mint=False)
        self._notify_main_window(
            "New API token generated — any tool using the old one must be updated."
        )

    def _sync_control_token(self, mint=False):
        """Refresh the token field from config, optionally minting one first.

        Minting and pushing the token to a live server belong to the main
        window (panels stay layout-only); this just reflects the result.
        """
        if mint and self.main_window and hasattr(self.main_window, 'ensure_control_token'):
            self.main_window.ensure_control_token()
        token = ''
        if self.main_window and hasattr(self.main_window, 'config'):
            token = self.main_window.config.get('output', {}).get('api_token', '') or ''
        self.control_token_input.setText(token)

    def _notify_main_window(self, message, category='info'):
        if self.main_window and hasattr(self.main_window, '_notify'):
            self.main_window._notify(message, category)

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
    
    # Discord + Hermes handlers live in IntegrationCardsMixin
    # (ui/panels/_integration_cards.py).

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
            self.control_enabled_switch.set_checked(
                output.get('webserver_control_enabled', False))
            self.control_token_input.setText(output.get('api_token', '') or '')
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

            # Hermes
            hermes = config.get('hermes', {})
            hermes_enabled = hermes.get('enabled', False)
            self.hermes_enabled_switch.set_checked(hermes_enabled)
            self.hermes_url_input.setText(hermes.get('url', ''))
            self.hermes_secret_input.setText(hermes.get('secret', ''))
            self.hermes_post_errors_switch.set_checked(hermes.get('post_errors', False))
            self.hermes_post_lifecycle_switch.set_checked(hermes.get('post_startup_shutdown', False))
            self.hermes_post_roof_changes_switch.set_checked(hermes.get('post_roof_changes', False))
            self.hermes_post_timelapse_switch.set_checked(hermes.get('post_timelapse', False))
            self.hermes_post_calibration_switch.set_checked(hermes.get('post_calibration', False))
            self.hermes_periodic_switch.set_checked(hermes.get('periodic_enabled', False))
            route_by_event = hermes.get('route_by_event', False)
            self.hermes_route_switch.set_checked(route_by_event)
            event_urls = hermes.get('event_urls', {})
            for key, field in self.hermes_event_url_inputs.items():
                field.setText(event_urls.get(key, ''))
            self.hermes_event_urls_options.setVisible(route_by_event)
            self.hermes_options.setVisible(hermes_enabled)

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
