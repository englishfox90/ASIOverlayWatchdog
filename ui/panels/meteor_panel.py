"""
Meteor Tracker Panel
Full-page settings, live status, and per-detection thumbnail cards.
"""
from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFileDialog, QLabel,
    QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QFont
from qfluentwidgets import (
    CardWidget, SubtitleLabel, BodyLabel, CaptionLabel,
    PushButton, SpinBox, LineEdit, FluentIcon,
)

from ..theme.tokens import Colors, Spacing, Layout
from ..theme.icons import mdi
from ..components.cards import SettingsCard, SwitchRow, CollapsibleCard


# ------------------------------------------------------------------ #
#  Detection card widget                                               #
# ------------------------------------------------------------------ #

class DetectionCard(CardWidget):
    """
    One card per detection event.

    Shows a 300×300 clean thumbnail with a toggleable green highlight overlay,
    metadata, a "Confirm Meteor" button (keeps the files on disk in a
    ``confirmed/`` subdir) and a "Not a Meteor" button (deletes thumbnail +
    full annotated frame and adds an exclusion zone).
    """

    reject_clicked = Signal(str)   # timestamp
    confirm_clicked = Signal(str)  # timestamp

    _THUMB_SIZE = 300
    _PLACEHOLDER_STYLE = f"background-color: #1a1a2e; border: 1px solid #333;"

    def __init__(self, event: dict, parent=None):
        super().__init__(parent)
        self._timestamp = event.get("timestamp", "")
        self._confirmed = bool(event.get("confirmed"))
        self._clean_pix: QPixmap | None = None
        self._highlight_pix: QPixmap | None = None
        self._highlight_on = True
        self._setup_ui(event)

    def _setup_ui(self, event: dict):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(Spacing.sm, Spacing.sm, Spacing.sm, Spacing.sm)
        outer.setSpacing(Spacing.base)

        # --- Thumbnail ---
        self._thumb_lbl = QLabel()
        self._thumb_lbl.setFixedSize(self._THUMB_SIZE, self._THUMB_SIZE)
        self._thumb_lbl.setAlignment(Qt.AlignCenter)
        thumb_path = event.get("thumbnail_path", "")
        if thumb_path and os.path.isfile(thumb_path):
            clean = QPixmap(thumb_path).scaled(
                self._THUMB_SIZE, self._THUMB_SIZE,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            self._clean_pix = clean
            self._highlight_pix = self._build_highlight_pixmap(clean, event)
            self._thumb_lbl.setPixmap(self._highlight_pix or clean)
        else:
            self._thumb_lbl.setStyleSheet(self._PLACEHOLDER_STYLE)
            self._thumb_lbl.setText("No image")
            self._thumb_lbl.setStyleSheet(
                self._PLACEHOLDER_STYLE
                + f" color: {Colors.text_muted}; font-size: 12px;"
            )
        outer.addWidget(self._thumb_lbl)

        # --- Metadata + buttons ---
        meta_layout = QVBoxLayout()
        meta_layout.setSpacing(Spacing.xs)

        ts = event.get("timestamp", "")
        time_str = ts.replace("T", "  ") if "T" in ts else ts
        time_lbl = BodyLabel(time_str)
        time_lbl.setStyleSheet(f"color: {Colors.text_primary}; font-weight: 600;")
        meta_layout.addWidget(time_lbl)

        count = event.get("count", 0)
        max_len = event.get("max_length", 0)
        noun = "meteor" if count == 1 else "meteors"
        desc_lbl = BodyLabel(f"{count} {noun}  \u2022  longest {max_len:.0f} px")
        desc_lbl.setStyleSheet(f"color: {Colors.text_secondary};")
        meta_layout.addWidget(desc_lbl)

        # --- Show/hide highlight toggle (only useful when we have a clean pixmap) ---
        if self._highlight_pix is not None:
            self._toggle_btn = PushButton("Hide Highlight")
            self._toggle_btn.setIcon(FluentIcon.VIEW)
            self._toggle_btn.setToolTip(
                "Show or hide the green line so you can see the streak underneath"
            )
            self._toggle_btn.clicked.connect(self._on_toggle_highlight)
            meta_layout.addWidget(self._toggle_btn)

        meta_layout.addStretch()

        if self._confirmed:
            confirmed_badge = BodyLabel("\u2713  Confirmed Meteor")
            confirmed_badge.setStyleSheet(
                "color: #3ac46a; font-weight: 600; padding: 6px 0;"
            )
            meta_layout.addWidget(confirmed_badge)
        else:
            confirm_btn = PushButton("Confirm Meteor")
            confirm_btn.setIcon(FluentIcon.ACCEPT)
            confirm_btn.clicked.connect(
                lambda: self.confirm_clicked.emit(self._timestamp))
            confirm_btn.setToolTip(
                "Mark as a real meteor — files are preserved in a 'confirmed' folder"
            )
            meta_layout.addWidget(confirm_btn)

            reject_btn = PushButton("Not a Meteor")
            reject_btn.setIcon(FluentIcon.CLOSE)
            reject_btn.clicked.connect(
                lambda: self.reject_clicked.emit(self._timestamp))
            reject_btn.setToolTip(
                "Mark as a false positive — this region will be excluded from future detection"
            )
            meta_layout.addWidget(reject_btn)

        outer.addLayout(meta_layout, 1)

    def _build_highlight_pixmap(self, clean: QPixmap, event: dict) -> QPixmap | None:
        """Paint the green line + length label on a copy of the clean pixmap.

        Coordinates are translated from the saved 300px crop space to the
        displayed label size (typically 1:1, but scaled if KeepAspectRatio
        shrank the image)."""
        thumb_size = int(event.get("thumb_size", self._THUMB_SIZE)) or self._THUMB_SIZE
        line = (
            int(event.get("line_x1", 0)), int(event.get("line_y1", 0)),
            int(event.get("line_x2", 0)), int(event.get("line_y2", 0)),
        )
        if line == (0, 0, 0, 0):
            return None

        scale = clean.width() / thumb_size if thumb_size else 1.0
        x1, y1, x2, y2 = (int(v * scale) for v in line)

        pix = QPixmap(clean)
        painter = QPainter(pix)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            pen = QPen(QColor(0, 255, 0), 2)
            painter.setPen(pen)
            painter.drawLine(x1, y1, x2, y2)
            length_px = int(event.get("length_px", event.get("max_length", 0)))
            if length_px:
                font = QFont()
                font.setPointSize(9)
                painter.setFont(font)
                mid_x = (x1 + x2) // 2
                mid_y = max(10, (y1 + y2) // 2 - 6)
                painter.drawText(mid_x, mid_y, f"{length_px}px")
        finally:
            painter.end()
        return pix

    def _on_toggle_highlight(self):
        if self._clean_pix is None:
            return
        self._highlight_on = not self._highlight_on
        if self._highlight_on and self._highlight_pix is not None:
            self._thumb_lbl.setPixmap(self._highlight_pix)
            self._toggle_btn.setText("Hide Highlight")
        else:
            self._thumb_lbl.setPixmap(self._clean_pix)
            self._toggle_btn.setText("Show Highlight")


# ------------------------------------------------------------------ #
#  Main panel                                                          #
# ------------------------------------------------------------------ #

class MeteorPanel(QScrollArea):
    """
    Full-page meteor tracker panel.

    Sections:
    - Enable toggle
    - Detection settings  (min trail length)
    - Logging             (JSONL log, annotated images)
    - Session status      (frames analysed, meteors detected, last hit)
    - Recent detections   (thumbnail cards with "Not a Meteor" buttons)
    """

    settings_changed  = Signal()
    detection_rejected = Signal(str)   # timestamp of rejected event
    detection_confirmed = Signal(str)  # timestamp of confirmed event

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self._loading_config = True
        self._setup_ui()
        self._loading_config = False

    # ------------------------------------------------------------------ #
    #  Layout                                                              #
    # ------------------------------------------------------------------ #

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

        self._build_enable_card(layout)
        self._build_detection_card(layout)
        self._build_logging_card(layout)
        self._build_status_card(layout)
        self._build_events_card(layout)

        layout.addStretch()

    def _build_enable_card(self, layout: QVBoxLayout):
        card = SettingsCard(
            "Meteor Tracker",
            "Detects meteor trails by comparing consecutive frames within "
            "the sky circle to isolate transient streaks."
        )
        self._enable_switch = SwitchRow("Enable Detection", "Runs on every captured frame")
        self._enable_switch.toggled.connect(self._on_settings_changed)
        card.add_widget(self._enable_switch)
        layout.addWidget(card)

    def _build_detection_card(self, layout: QVBoxLayout):
        card = CollapsibleCard("Detection Settings", mdi('radar'))

        self._min_length_spin = SpinBox()
        self._min_length_spin.setRange(10, 500)
        self._min_length_spin.setValue(100)
        self._min_length_spin.setSuffix(" px")
        self._min_length_spin.valueChanged.connect(self._on_settings_changed)
        card.add_row(
            "Min Trail Length", self._min_length_spin,
            "Minimum pixel length for a line to be counted as a meteor",
        )

        self._adaptive_switch = SwitchRow(
            "Adaptive Sensitivity",
            "Auto-compute threshold from sky noise level (recommended)",
        )
        self._adaptive_switch.toggled.connect(self._on_adaptive_toggled)
        card.add_widget(self._adaptive_switch)

        self._diff_threshold_spin = SpinBox()
        self._diff_threshold_spin.setRange(5, 100)
        self._diff_threshold_spin.setValue(25)
        self._diff_threshold_spin.valueChanged.connect(self._on_settings_changed)
        card.add_row(
            "Fixed Diff Threshold", self._diff_threshold_spin,
            "Manual pixel threshold (only used when adaptive is off)",
        )

        self._cooldown_spin = SpinBox()
        self._cooldown_spin.setRange(0, 300)
        self._cooldown_spin.setValue(30)
        self._cooldown_spin.setSuffix(" sec")
        self._cooldown_spin.valueChanged.connect(self._on_settings_changed)
        card.add_row(
            "Detection Cooldown", self._cooldown_spin,
            "Minimum seconds between detection events to prevent flooding",
        )

        # --- Multi-frame confirmation (advanced) ---
        self._multi_frame_switch = SwitchRow(
            "Multi-Frame Confirmation",
            "Require consistent motion across multiple frames",
        )
        self._multi_frame_switch.toggled.connect(self._on_settings_changed)
        card.add_widget(self._multi_frame_switch)

        self._multi_frame_warn = CaptionLabel(
            "Short exposures recommended (< 2 s). With long exposures "
            "a meteor may only appear in a single frame and be discarded."
        )
        self._multi_frame_warn.setWordWrap(True)
        self._multi_frame_warn.setStyleSheet(
            f"color: {Colors.text_muted}; padding-left: 4px;")
        card.add_widget(self._multi_frame_warn)

        self._confirm_frames_spin = SpinBox()
        self._confirm_frames_spin.setRange(2, 10)
        self._confirm_frames_spin.setValue(2)
        self._confirm_frames_spin.valueChanged.connect(self._on_settings_changed)
        card.add_row(
            "Min Confirm Frames", self._confirm_frames_spin,
            "Number of frames a trail must appear in before reporting",
        )

        layout.addWidget(card)

    def _build_logging_card(self, layout: QVBoxLayout):
        card = CollapsibleCard("Logging", mdi('file-document-outline'))

        self._save_detections_switch = SwitchRow(
            "Save Detection Log", "Append each detected event to a JSONL file"
        )
        self._save_detections_switch.toggled.connect(self._on_settings_changed)
        card.add_widget(self._save_detections_switch)

        self._log_file_edit, log_widget = self._make_path_row(
            "Default: %LOCALAPPDATA%\\PFRSentinel\\meteor_detections.jsonl",
            self._browse_log_file, file_picker=True,
        )
        card.add_row("Log File", log_widget, "Leave blank to use the default location")

        self._save_annotated_switch = SwitchRow(
            "Save Annotated Images",
            "Write full-frame copies with trails highlighted in green"
        )
        self._save_annotated_switch.toggled.connect(self._on_settings_changed)
        card.add_widget(self._save_annotated_switch)

        self._annotated_dir_edit, ann_widget = self._make_path_row(
            "Directory for annotated images",
            self._browse_annotated_dir, file_picker=False,
        )
        card.add_row("Annotated Image Dir", ann_widget,
                     "Leave blank to disable saving full annotated frames")

        layout.addWidget(card)

    def _make_path_row(self, placeholder: str, browse_callback, file_picker: bool):
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(Spacing.sm)
        edit = LineEdit()
        edit.setPlaceholderText(placeholder)
        edit.textChanged.connect(self._on_settings_changed)
        row.addWidget(edit, 1)
        btn = PushButton("Browse")
        btn.setIcon(mdi('folder-outline'))
        btn.clicked.connect(browse_callback)
        row.addWidget(btn)
        return edit, container

    def _build_status_card(self, layout: QVBoxLayout):
        card = CardWidget()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(
            Spacing.card_padding, Spacing.card_padding,
            Spacing.card_padding, Spacing.card_padding,
        )
        card_layout.setSpacing(Spacing.element_gap)

        title = SubtitleLabel("Session Status")
        title.setStyleSheet(f"color: {Colors.text_primary};")
        card_layout.addWidget(title)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(Spacing.base)
        self._frames_widget   = self._make_stat("Frames Analysed", "0")
        self._hits_widget     = self._make_stat("Meteors Detected", "0")
        self._last_hit_widget = self._make_stat("Last Detection", "\u2014")
        stats_row.addWidget(self._frames_widget)
        stats_row.addWidget(self._hits_widget)
        stats_row.addWidget(self._last_hit_widget)
        stats_row.addStretch()
        card_layout.addLayout(stats_row)
        layout.addWidget(card)

    def _make_stat(self, label: str, value: str) -> QWidget:
        w = QFrame()
        w.setStyleSheet(
            f"QFrame {{ background: {Colors.bg_input}; "
            f"border: none; "
            f"border-radius: {Layout.radius_md}px; }}"
        )
        vbox = QVBoxLayout(w)
        vbox.setContentsMargins(
            Spacing.md, Spacing.sm, Spacing.md, Spacing.sm,
        )
        vbox.setSpacing(2)
        val_lbl = BodyLabel(value)
        val_lbl.setStyleSheet(
            f"color: {Colors.text_primary}; font-size: 22px; font-weight: 600;"
            f"background: transparent;"
        )
        cap_lbl = CaptionLabel(label)
        cap_lbl.setStyleSheet(
            f"color: {Colors.text_muted}; background: transparent;"
        )
        vbox.addWidget(val_lbl)
        vbox.addWidget(cap_lbl)
        w._val = val_lbl  # type: ignore[attr-defined]
        return w

    def _build_events_card(self, layout: QVBoxLayout):
        self._events_card = CollapsibleCard("Recent Detections", mdi('history'))

        self._events_container = QWidget()
        self._events_layout = QVBoxLayout(self._events_container)
        self._events_layout.setContentsMargins(0, 0, 0, 0)
        self._events_layout.setSpacing(Spacing.sm)

        self._no_events_lbl = CaptionLabel("No meteors detected this session.")
        self._no_events_lbl.setStyleSheet(f"color: {Colors.text_muted};")
        self._events_layout.addWidget(self._no_events_lbl)

        self._events_card.add_widget(self._events_container)
        layout.addWidget(self._events_card)

    # ------------------------------------------------------------------ #
    #  Public interface                                                    #
    # ------------------------------------------------------------------ #

    def load_from_config(self, config: dict):
        self._loading_config = True
        try:
            self._enable_switch.set_checked(config.get("enabled", False))
            self._min_length_spin.setValue(int(config.get("min_length", 100)))
            adaptive = config.get("adaptive_threshold", True)
            self._adaptive_switch.set_checked(adaptive)
            self._diff_threshold_spin.setEnabled(not adaptive)
            self._diff_threshold_spin.setValue(int(config.get("diff_threshold", 25)))
            self._cooldown_spin.setValue(int(config.get("detection_cooldown", 30)))
            self._multi_frame_switch.set_checked(config.get("multi_frame_confirm", False))
            self._confirm_frames_spin.setValue(int(config.get("min_confirm_frames", 2)))
            self._save_detections_switch.set_checked(config.get("save_detections", True))
            self._log_file_edit.setText(config.get("log_file", ""))
            self._save_annotated_switch.set_checked(config.get("save_annotated", False))
            self._annotated_dir_edit.setText(config.get("annotated_dir", ""))
        finally:
            self._loading_config = False

    def update_status(self, status: dict):
        """Called by MeteorController.status_updated every 5 s."""
        self._frames_widget._val.setText(str(status.get("session_frames", 0)))
        self._hits_widget._val.setText(str(status.get("session_detections", 0)))
        last = status.get("last_detection_time")
        self._last_hit_widget._val.setText(
            last.replace("T", "  ")[:19] if last else "\u2014"
        )
        self._refresh_events(status.get("recent_events", []))

    # ------------------------------------------------------------------ #
    #  Events list                                                         #
    # ------------------------------------------------------------------ #

    def _refresh_events(self, events: list):
        # Remove existing detection cards (keep placeholder label)
        for i in reversed(range(self._events_layout.count())):
            item = self._events_layout.itemAt(i)
            if item and item.widget() and item.widget() is not self._no_events_lbl:
                item.widget().deleteLater()
                self._events_layout.removeItem(item)

        if not events:
            self._no_events_lbl.show()
            return

        self._no_events_lbl.hide()
        for event in events[:10]:
            card = DetectionCard(event, self._events_container)
            card.reject_clicked.connect(self.detection_rejected.emit)
            card.confirm_clicked.connect(self.detection_confirmed.emit)
            self._events_layout.addWidget(card)

    # ------------------------------------------------------------------ #
    #  Slots / helpers                                                     #
    # ------------------------------------------------------------------ #

    def _on_adaptive_toggled(self, checked: bool):
        self._diff_threshold_spin.setEnabled(not checked)
        self._on_settings_changed()

    def _on_settings_changed(self):
        if self._loading_config:
            return
        self._save_config()
        self.settings_changed.emit()

    def _save_config(self):
        if not self.main_window:
            return
        # Merge into existing config so exclusion_zones (managed by the
        # controller) are never overwritten by a panel save.
        existing = dict(self.main_window.config.get("meteor", {}))
        existing.update({
            "enabled":              self._enable_switch.is_checked(),
            "min_length":           self._min_length_spin.value(),
            "adaptive_threshold":   self._adaptive_switch.is_checked(),
            "diff_threshold":       self._diff_threshold_spin.value(),
            "detection_cooldown":   self._cooldown_spin.value(),
            "multi_frame_confirm":  self._multi_frame_switch.is_checked(),
            "min_confirm_frames":   self._confirm_frames_spin.value(),
            "save_detections":      self._save_detections_switch.is_checked(),
            "log_file":             self._log_file_edit.text().strip(),
            "save_annotated":       self._save_annotated_switch.is_checked(),
            "annotated_dir":        self._annotated_dir_edit.text().strip(),
        })
        self.main_window.config.set("meteor", existing)
        self.main_window.config.save()

    def _browse_log_file(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Choose Log File", "",
            "JSONL Files (*.jsonl);;All Files (*)",
        )
        if path:
            self._log_file_edit.setText(path)

    def _browse_annotated_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "Choose Annotated Image Directory"
        )
        if path:
            self._annotated_dir_edit.setText(path)
