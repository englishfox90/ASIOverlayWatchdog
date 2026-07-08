"""
Discord + Hermes integration cards for OutputSettingsPanel.

Split out to stay under the file-size cap in output_settings.py. This is a
mixin — OutputSettingsPanel inherits from it — so the widgets and handlers
below land on the same instance as everything else in that panel; from the
rest of the panel's perspective this is indistinguishable from inline code.
Layout only: no network, no threading — settings are collected and handed
to `services.config`, same as every other card in output_settings.py.
"""
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout
from PySide6.QtGui import QColor
from qfluentwidgets import CaptionLabel, PushButton, LineEdit, SpinBox, ColorPickerButton

from ..theme.tokens import Colors, Spacing
from ..theme.icons import mdi
from ..components.cards import FormRow, SwitchRow, CollapsibleCard


class IntegrationCardsMixin:
    """Discord + Hermes webhook cards: widget construction and handlers."""

    def _build_integration_cards(self, layout):
        self._build_discord_card(layout)
        self._build_hermes_card(layout)

    def _build_discord_card(self, layout):
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

    def _build_hermes_card(self, layout):
        hermes_card = CollapsibleCard("Hermes Webhook", mdi('webhook'))

        self.hermes_enabled_switch = SwitchRow(
            "Enable Hermes Webhook",
            "Send notifications to a Hermes agent webhook"
        )
        self.hermes_enabled_switch.toggled.connect(self._on_hermes_enabled_changed)
        hermes_card.add_widget(self.hermes_enabled_switch)

        # Detail options container (shown/hidden based on the enable switch)
        self.hermes_options = QWidget()
        hermes_options_layout = QVBoxLayout(self.hermes_options)
        hermes_options_layout.setContentsMargins(0, 0, 0, 0)
        hermes_options_layout.setSpacing(Spacing.input_gap)

        # Webhook URL
        hermes_url_row = QHBoxLayout()
        hermes_url_row.setSpacing(Spacing.sm)

        self.hermes_url_input = LineEdit()
        self.hermes_url_input.setPlaceholderText("https://hermes.../webhooks/...")
        self.hermes_url_input.setEchoMode(LineEdit.Password)
        self.hermes_url_input.textChanged.connect(self._on_hermes_settings_changed)
        hermes_url_row.addWidget(self.hermes_url_input, 1)

        self.show_hermes_url_btn = PushButton("Show")
        self.show_hermes_url_btn.setCheckable(True)
        self.show_hermes_url_btn.clicked.connect(self._toggle_hermes_url_visibility)
        hermes_url_row.addWidget(self.show_hermes_url_btn)

        hermes_url_widget = QWidget()
        hermes_url_widget.setLayout(hermes_url_row)
        hermes_options_layout.addWidget(FormRow("Webhook URL", hermes_url_widget))

        # Signing secret
        self.hermes_secret_input = LineEdit()
        self.hermes_secret_input.setPlaceholderText("Signing secret")
        self.hermes_secret_input.setEchoMode(LineEdit.Password)
        self.hermes_secret_input.textChanged.connect(self._on_hermes_settings_changed)
        hermes_options_layout.addWidget(FormRow("Secret", self.hermes_secret_input))

        # Post errors
        self.hermes_post_errors_switch = SwitchRow("Post Errors", "Send error messages to Hermes")
        self.hermes_post_errors_switch.toggled.connect(self._on_hermes_settings_changed)
        hermes_options_layout.addWidget(self.hermes_post_errors_switch)

        # Post lifecycle
        self.hermes_post_lifecycle_switch = SwitchRow(
            "Post Startup/Shutdown",
            "Send capture start/stop messages"
        )
        self.hermes_post_lifecycle_switch.toggled.connect(self._on_hermes_settings_changed)
        hermes_options_layout.addWidget(self.hermes_post_lifecycle_switch)

        # Post roof changes
        self.hermes_post_roof_changes_switch = SwitchRow(
            "Post Roof Changes",
            "Send notification when ML detects a roof open/close event"
        )
        self.hermes_post_roof_changes_switch.toggled.connect(self._on_hermes_settings_changed)
        hermes_options_layout.addWidget(self.hermes_post_roof_changes_switch)

        # Post timelapse
        self.hermes_post_timelapse_switch = SwitchRow(
            "Post Timelapse",
            "Send notification when a timelapse video finishes"
        )
        self.hermes_post_timelapse_switch.toggled.connect(self._on_hermes_settings_changed)
        hermes_options_layout.addWidget(self.hermes_post_timelapse_switch)

        # Post calibration
        self.hermes_post_calibration_switch = SwitchRow(
            "Post Calibration",
            "Send notification when all-sky calibration completes"
        )
        self.hermes_post_calibration_switch.toggled.connect(self._on_hermes_settings_changed)
        hermes_options_layout.addWidget(self.hermes_post_calibration_switch)

        # Periodic posts
        self.hermes_periodic_switch = SwitchRow(
            "Periodic Image Updates",
            "Post images at regular intervals"
        )
        self.hermes_periodic_switch.toggled.connect(self._on_hermes_settings_changed)
        hermes_options_layout.addWidget(self.hermes_periodic_switch)

        # Test button and status
        hermes_test_row = QHBoxLayout()
        hermes_test_row.setSpacing(Spacing.sm)

        self.test_hermes_btn = PushButton("Test Webhook")
        self.test_hermes_btn.setIcon(mdi('send'))
        self.test_hermes_btn.clicked.connect(self._test_hermes)
        hermes_test_row.addWidget(self.test_hermes_btn)

        self.hermes_status_label = CaptionLabel("")
        hermes_test_row.addWidget(self.hermes_status_label)
        hermes_test_row.addStretch()

        hermes_test_widget = QWidget()
        hermes_test_widget.setLayout(hermes_test_row)
        hermes_options_layout.addWidget(hermes_test_widget)

        hermes_card.add_widget(self.hermes_options)
        self.hermes_options.hide()

        layout.addWidget(hermes_card)

    # === DISCORD HANDLERS ===

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

    # === HERMES HANDLERS ===

    def _on_hermes_enabled_changed(self, checked):
        """Show/hide Hermes detail options based on the enable switch"""
        self.hermes_options.setVisible(checked)
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            hermes = self.main_window.config.get('hermes', {})
            hermes['enabled'] = checked
            self.main_window.config.set('hermes', hermes)
            self.settings_changed.emit()

    def _toggle_hermes_url_visibility(self):
        """Toggle Hermes webhook URL visibility"""
        if self.show_hermes_url_btn.isChecked():
            self.hermes_url_input.setEchoMode(LineEdit.Normal)
            self.show_hermes_url_btn.setText("Hide")
        else:
            self.hermes_url_input.setEchoMode(LineEdit.Password)
            self.show_hermes_url_btn.setText("Show")

    def _on_hermes_settings_changed(self):
        if self._loading_config:
            return
        if self.main_window and hasattr(self.main_window, 'config'):
            hermes = self.main_window.config.get('hermes', {})
            hermes['url'] = self.hermes_url_input.text()
            hermes['secret'] = self.hermes_secret_input.text()
            hermes['post_errors'] = self.hermes_post_errors_switch.is_checked()
            hermes['post_startup_shutdown'] = self.hermes_post_lifecycle_switch.is_checked()
            hermes['post_roof_changes'] = self.hermes_post_roof_changes_switch.is_checked()
            hermes['post_timelapse'] = self.hermes_post_timelapse_switch.is_checked()
            hermes['post_calibration'] = self.hermes_post_calibration_switch.is_checked()
            hermes['periodic_enabled'] = self.hermes_periodic_switch.is_checked()
            self.main_window.config.set('hermes', hermes)
            self.settings_changed.emit()

    def _test_hermes(self):
        """Test Hermes webhook - emit signal for main window to handle"""
        webhook_url = self.hermes_url_input.text().strip()
        if not webhook_url:
            self.set_hermes_test_result(False, "Webhook URL required")
            return

        self.hermes_status_label.setText("Testing...")
        self.hermes_status_label.setStyleSheet(f"color: {Colors.text_muted};")
        self.test_hermes_requested.emit()

    def set_hermes_test_result(self, success: bool, message: str):
        """Update Hermes test result display"""
        if success:
            self.hermes_status_label.setText(f"✓ {message}")
            self.hermes_status_label.setStyleSheet(f"color: {Colors.status_success};")
        else:
            self.hermes_status_label.setText(f"❌ {message}")
            self.hermes_status_label.setStyleSheet(f"color: {Colors.status_error};")
