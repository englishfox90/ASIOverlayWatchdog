"""
YouTube upload settings card for the Timelapse panel.
"""
import html
import os
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFileDialog, QPlainTextEdit,
    QSizePolicy,
    QDialog, QDialogButtonBox, QTextBrowser,
)
from PySide6.QtCore import Qt, Signal
from qfluentwidgets import (
    BodyLabel, CaptionLabel, ComboBox, LineEdit,
    PushButton, PrimaryPushButton
)

from ..components.cards import CollapsibleCard, SwitchRow
from ..theme.icons import mdi
from ..theme.tokens import Colors, Spacing
from services.youtube_config import normalize_youtube_config


class YouTubeSetupGuideDialog(QDialog):
    """Non-technical setup guide shown directly in the app."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("YouTube setup")
        self.setMinimumWidth(620)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        intro = BodyLabel(
            "Use the steps below inside PFR Sentinel. Start with a dedicated Google account, not your main one."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {Colors.text_primary};")
        layout.addWidget(intro)

        body = QTextBrowser()
        body.setOpenExternalLinks(True)
        body.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {Colors.bg_surface};
                color: {Colors.text_primary};
                border: 1px solid {Colors.border_subtle};
                border-radius: 6px;
            }}
        """)
        body.setHtml(
            """
            <ol>
              <li><b>Choose the Google file.</b> Use <b>Browse</b> to pick the desktop OAuth JSON you downloaded from Google Cloud.</li>
              <li><b>Connect the account.</b> Click <b>Authenticate</b> and approve the YouTube permission in the browser.</li>
              <li><b>Test safely.</b> Leave privacy on <b>Private</b> first, then click <b>Upload latest video</b>.</li>
              <li><b>Keep the account dedicated.</b> If Google flags or blocks the account, your personal Google data stays separate.</li>
            </ol>
            <p>
              If uploads stop after about a week, the app is probably still in Google
              Cloud <b>Testing</b> mode. Re-authenticate or publish the OAuth app.
            </p>
            """
        )
        layout.addWidget(body, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class YouTubeUploadCard(CollapsibleCard):
    """Self-contained YouTube upload settings UI as a collapsible section."""

    settings_changed = Signal()

    _PRIVACY_TO_LABEL = {
        "private": "Private",
        "unlisted": "Unlisted",
        "public": "Public",
    }
    _LABEL_TO_PRIVACY = {v: k for k, v in _PRIVACY_TO_LABEL.items()}

    def __init__(self, parent=None):
        super().__init__("YouTube Uploads", mdi("youtube"))
        self._timelapse_panel = parent
        self._loading = True
        self._setup_fields()
        self._loading = False
        self._refresh_guidance()

    def _setup_fields(self):
        self._intro_label = CaptionLabel(
            "Use a dedicated Google/YouTube account, not your primary account. Keep the first test Private."
        )
        self._intro_label.setWordWrap(True)
        self._intro_label.setStyleSheet(f"color: {Colors.text_muted};")
        self.add_widget(self._intro_label)

        self._step_label = BodyLabel("Step 1: Choose the Google file")
        self._step_label.setWordWrap(True)
        self._step_label.setStyleSheet(f"color: {Colors.text_primary}; font-weight: 600;")
        self.add_widget(self._step_label)

        self._step_detail = CaptionLabel(
            "Pick the desktop OAuth JSON you downloaded from Google Cloud Console."
        )
        self._step_detail.setWordWrap(True)
        self._step_detail.setStyleSheet(f"color: {Colors.text_muted};")
        self.add_widget(self._step_detail)

        self.enable_switch = SwitchRow("Enable YouTube uploads", "Completed timelapse videos only")
        self.enable_switch.toggled.connect(self._emit_changed)
        self.add_widget(self.enable_switch)

        json_row = QWidget()
        json_layout = QHBoxLayout(json_row)
        json_layout.setContentsMargins(0, 0, 0, 0)
        json_layout.setSpacing(Spacing.sm)

        self.client_json_input = LineEdit()
        self.client_json_input.setPlaceholderText("Select OAuth desktop client JSON...")
        self.client_json_input.textChanged.connect(self._emit_changed)
        json_layout.addWidget(self.client_json_input, 1)

        browse_btn = PushButton("Browse")
        browse_btn.setIcon(mdi("folder-outline"))
        browse_btn.clicked.connect(self._browse_client_json)
        json_layout.addWidget(browse_btn)
        self.add_row("OAuth JSON", json_row, "Create this in Google Cloud Console as a Desktop OAuth client.")

        self.auth_hint = CaptionLabel("After selecting the file, click Authenticate to sign in.")
        self.auth_hint.setWordWrap(True)
        self.auth_hint.setStyleSheet(f"color: {Colors.text_muted};")
        self.add_widget(self.auth_hint)

        auth_row = QWidget()
        auth_layout = QHBoxLayout(auth_row)
        auth_layout.setContentsMargins(0, 0, 0, 0)
        auth_layout.setSpacing(Spacing.sm)

        self.auth_btn = PrimaryPushButton("Authenticate")
        # White icon: the muted-secondary default vanishes on the purple primary button.
        self.auth_btn.setIcon(mdi("login", color=Colors.text_on_accent))
        self.auth_btn.clicked.connect(self._authenticate)
        auth_layout.addWidget(self.auth_btn)

        self.upload_latest_btn = PushButton("Upload latest video")
        self.upload_latest_btn.setIcon(mdi("upload"))
        self.upload_latest_btn.clicked.connect(self._upload_latest)
        auth_layout.addWidget(self.upload_latest_btn)
        auth_layout.addStretch()
        self.add_widget(auth_row)

        self.advanced_toggle_btn = PushButton("Show advanced settings")
        self.advanced_toggle_btn.setIcon(mdi("tune-variant"))
        self.advanced_toggle_btn.clicked.connect(self._toggle_advanced)
        self._add_action_button(self.advanced_toggle_btn)

        self._advanced_widget = QWidget()
        advanced_layout = QVBoxLayout(self._advanced_widget)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(Spacing.input_gap)

        self.privacy_combo = ComboBox()
        self.privacy_combo.addItems(["Private", "Unlisted", "Public"])
        self.privacy_combo.currentTextChanged.connect(self._emit_changed)
        advanced_layout.addWidget(self._build_row("Privacy", self.privacy_combo, "Private is safest for first tests and unverified apps."))

        self.title_input = LineEdit()
        self.title_input.textChanged.connect(self._emit_changed)
        advanced_layout.addWidget(self._build_row("Title", self.title_input, "Supported: {date}, {filename}, {frame_count}, {duration}, {size_mb}"))

        self.description_input = QPlainTextEdit()
        self.description_input.setFixedHeight(72)
        self.description_input.textChanged.connect(self._emit_changed)
        advanced_layout.addWidget(self._build_row("Description", self.description_input))

        self.tags_input = LineEdit()
        self.tags_input.textChanged.connect(self._emit_changed)
        advanced_layout.addWidget(self._build_row("Tags", self.tags_input, "Comma-separated tags"))
        self._advanced_widget.setVisible(False)
        self.add_widget(self._advanced_widget)

        guide_btn = PushButton("Show setup steps")
        guide_btn.setIcon(mdi("open-in-new"))
        guide_btn.clicked.connect(self._open_setup_guide)
        self._add_action_button(guide_btn)

        self.status_label = BodyLabel("Not authenticated")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.RichText)
        self.status_label.setOpenExternalLinks(True)
        self.status_label.setStyleSheet(f"color: {Colors.text_muted};")
        self.add_widget(self.status_label)

    def _add_action_button(self, button):
        """Add a discrete, left-aligned action button.

        Matches the auth-row convention so buttons stay chip-sized instead of
        stretching full-width like a section band.
        """
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.sm)
        layout.addWidget(button)
        layout.addStretch()
        self.add_widget(row)

    def _build_row(self, label: str, widget, hint: str = None):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.md)

        label_widget = BodyLabel(label)
        label_widget.setFixedWidth(140)
        label_widget.setStyleSheet(f"color: {Colors.text_secondary};")
        layout.addWidget(label_widget)

        input_layout = QVBoxLayout()
        input_layout.setSpacing(Spacing.xs)
        input_layout.setContentsMargins(0, 0, 0, 0)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        input_layout.addWidget(widget)

        if hint:
            hint_label = CaptionLabel(hint)
            hint_label.setStyleSheet(f"color: {Colors.text_muted};")
            hint_label.setWordWrap(True)
            input_layout.addWidget(hint_label)

        layout.addLayout(input_layout, 1)
        return row

    def load_from_config(self, config):
        self._loading = True
        try:
            cfg = normalize_youtube_config(config)
            self.enable_switch.set_checked(cfg["enabled"])
            self.client_json_input.setText(cfg["client_secrets_path"])
            privacy_label = self._PRIVACY_TO_LABEL.get(cfg["privacy_status"], "Private")
            idx = self.privacy_combo.findText(privacy_label)
            self.privacy_combo.setCurrentIndex(max(0, idx))
            self.title_input.setText(cfg["title_template"])
            self.description_input.setPlainText(cfg["description_template"])
            self.tags_input.setText(cfg["tags"])
        finally:
            self._loading = False
        self._refresh_guidance()

    def current_config(self) -> dict:
        return normalize_youtube_config({
            "enabled": self.enable_switch.is_checked(),
            "client_secrets_path": self.client_json_input.text().strip(),
            "privacy_status": self._LABEL_TO_PRIVACY.get(self.privacy_combo.currentText(), "private"),
            "title_template": self.title_input.text(),
            "description_template": self.description_input.toPlainText(),
            "tags": self.tags_input.text(),
            "category_id": "22",
        })

    def set_status(self, status: dict):
        message = status.get("message") or status.get("status") or ""
        if status.get("status") in {"uploaded", "authenticated", "queued"} or status.get("success"):
            color = Colors.status_success
        elif status.get("status") in {"uploading", "authenticating"}:
            color = Colors.text_secondary
        else:
            color = Colors.status_error
        watch_url = status.get("watch_url") or ""
        text = f'<span style="color:{color};">{html.escape(message)}</span>'
        if watch_url:
            safe_url = html.escape(watch_url, quote=True)
            text += (
                f' <a href="{safe_url}" style="color:{Colors.accent_text};">'
                f'{html.escape(watch_url)}</a>'
            )
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color};")
        self._refresh_guidance()

    def _browse_client_json(self):
        start_dir = os.path.dirname(self.client_json_input.text()) if self.client_json_input.text() else ""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Google OAuth Client JSON",
            start_dir,
            "JSON Files (*.json);;All Files (*.*)",
        )
        if path:
            self.client_json_input.setText(path)

    def _emit_changed(self, *_):
        if not self._loading:
            main_window = getattr(self._timelapse_panel, "main_window", None)
            if main_window and hasattr(main_window, "config"):
                main_window.config.set("youtube", self.current_config())
                main_window.config.save()
            self.settings_changed.emit()
            self._refresh_guidance()

    def _authenticate(self):
        main_window = getattr(self._timelapse_panel, "main_window", None)
        controller = getattr(main_window, "timelapse_controller", None) if main_window else None
        if controller:
            controller.authenticate_youtube()

    def _upload_latest(self):
        main_window = getattr(self._timelapse_panel, "main_window", None)
        controller = getattr(main_window, "timelapse_controller", None) if main_window else None
        if controller:
            controller.upload_latest_youtube()

    def _open_setup_guide(self):
        dialog = YouTubeSetupGuideDialog(self)
        dialog.exec()

    def _toggle_advanced(self):
        visible = not self._advanced_widget.isVisible()
        self._advanced_widget.setVisible(visible)
        self.advanced_toggle_btn.setText("Hide advanced settings" if visible else "Show advanced settings")
        self.advanced_toggle_btn.setIcon(mdi("tune-variant"))

    def _has_token(self) -> bool:
        main_window = getattr(self._timelapse_panel, "main_window", None)
        controller = getattr(main_window, "timelapse_controller", None) if main_window else None
        publishers = getattr(controller, "_publishers", None) if controller else None
        auth = getattr(publishers, "youtube_auth", None) if publishers else None
        return bool(auth and hasattr(auth, "has_token") and auth.has_token())

    def _refresh_guidance(self):
        cfg = normalize_youtube_config(self.current_config())
        has_file = bool(cfg.get("client_secrets_path"))
        has_token = self._has_token()
        enabled = bool(cfg.get("enabled"))

        if not enabled:
            step = "Step 0: Turn on uploads"
            detail = "Enable YouTube uploads first, then choose the Google file."
        elif not has_file:
            step = "Step 1: Choose the Google file"
            detail = "Browse to the desktop OAuth JSON you downloaded from Google Cloud."
        elif not has_token:
            step = "Step 2: Sign in to YouTube"
            detail = "Click Authenticate and approve the upload permission in the browser."
        else:
            step = "Step 3: Upload a private test video"
            detail = "Private is safest for the first upload. Use Upload latest video when you are ready."

        self._step_label.setText(step)
        self._step_detail.setText(detail)
        self.auth_btn.setEnabled(enabled and has_file)
        self.auth_btn.setText("Re-authenticate" if has_token else "Authenticate")
        self.upload_latest_btn.setEnabled(enabled and has_token)
        current_status = self.status_label.text().strip().lower()
        if has_token and current_status in {"", "not authenticated"}:
            self.status_label.setText("Authenticated and ready for a test upload.")
            self.status_label.setStyleSheet(f"color: {Colors.status_success};")
