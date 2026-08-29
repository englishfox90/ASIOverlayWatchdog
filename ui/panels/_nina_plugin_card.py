"""NINA plugin install card for OutputSettingsPanel.

A mixin, like ``_integration_cards.py``: the widgets land on the same instance
as the rest of the Output panel, and it keeps ``output_settings.py`` under the
file-size cap. Layout only — the buttons ask the window to run the action, the
window's controller threads it and pushes status back through
``set_nina_plugin_status`` / ``set_nina_plugin_busy``.

Button state comes straight off :class:`services.nina_plugin_install.PluginStatus`
(``can_install`` / ``can_remove`` / ``message``); nothing is re-derived here
beyond the button's wording.
"""
from PySide6.QtWidgets import QWidget, QHBoxLayout
from qfluentwidgets import BodyLabel, PushButton, PrimaryPushButton

from services.nina_plugin_install import (
    STATUS_INSTALLED, STATUS_STALE, STATUS_UPDATE_AVAILABLE,
)

from ..theme.tokens import Colors, Spacing
from ..theme.icons import mdi
from ..components.cards import CollapsibleCard

DEFAULT_INSTALL_LABEL = "Install Plugin"
INSTALL_LABELS = {
    STATUS_UPDATE_AVAILABLE: "Update Plugin",
    STATUS_STALE: "Reinstall Plugin",
    STATUS_INSTALLED: "Reinstall Plugin",
}


class NinaPluginCardMixin:
    """Install / update / remove the bundled NINA plugin DLL."""

    def _build_nina_plugin_card(self, layout):
        card = CollapsibleCard("NINA Plugin", mdi('puzzle-outline'))

        self.nina_status_label = BodyLabel("Checking NINA…")
        self.nina_status_label.setWordWrap(True)
        self.nina_status_label.setStyleSheet(f"color: {Colors.text_secondary};")
        card.add_row(
            "Status", self.nina_status_label,
            "Copies the Sentinel plugin into NINA — pairs itself, no token to type"
        )

        button_row = QHBoxLayout()
        button_row.setSpacing(Spacing.sm)

        self.nina_install_btn = PrimaryPushButton(DEFAULT_INSTALL_LABEL)
        self.nina_install_btn.setIcon(mdi('download'))
        self.nina_install_btn.setEnabled(False)
        self.nina_install_btn.clicked.connect(self._on_install_nina_plugin)
        button_row.addWidget(self.nina_install_btn)

        self.nina_remove_btn = PushButton("Remove")
        self.nina_remove_btn.setIcon(mdi('trash-can-outline'))
        self.nina_remove_btn.setEnabled(False)
        self.nina_remove_btn.clicked.connect(self._on_remove_nina_plugin)
        button_row.addWidget(self.nina_remove_btn)

        button_row.addStretch()

        button_widget = QWidget()
        button_widget.setLayout(button_row)
        card.add_widget(button_widget)

        layout.addWidget(card)

    # === DISPLAY (called by the window, on the GUI thread) ===

    def set_nina_plugin_status(self, status):
        """Render a PluginStatus. The service's message is shown verbatim."""
        self._nina_plugin_status = status
        self.nina_status_label.setText(getattr(status, 'message', '') or '')
        self.nina_install_btn.setText(
            INSTALL_LABELS.get(getattr(status, 'status', ''), DEFAULT_INSTALL_LABEL)
        )
        self._apply_nina_plugin_buttons()

    def set_nina_plugin_busy(self, busy):
        self._nina_plugin_busy = bool(busy)
        self._apply_nina_plugin_buttons()

    def _apply_nina_plugin_buttons(self):
        status = getattr(self, '_nina_plugin_status', None)
        busy = getattr(self, '_nina_plugin_busy', False)
        self.nina_install_btn.setEnabled(
            bool(status is not None and status.can_install) and not busy)
        self.nina_remove_btn.setEnabled(
            bool(status is not None and status.can_remove) and not busy)

    # === EVENT HANDLERS ===

    def _on_install_nina_plugin(self):
        self._request_nina_plugin_action('install')

    def _on_remove_nina_plugin(self):
        self._request_nina_plugin_action('remove')

    def _request_nina_plugin_action(self, action):
        if self.main_window and hasattr(self.main_window, 'run_nina_plugin_action'):
            self.main_window.run_nina_plugin_action(action)
