"""
Library — single-image view (modal dialog).

The third screen: one archived frame at full (Discord) size, with a metadata
grid and prev/next navigation across the night's frames. Image bytes are pulled
on demand through the ``read_full`` callback the container passes in, so the
dialog never holds the whole night in memory.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from qfluentwidgets import PushButton, PrimaryPushButton, CaptionLabel, BodyLabel, StrongBodyLabel

from services.library import sessions as S
from ..theme.tokens import Colors, Spacing, Layout
from ..theme.icons import mdi
from .library_band import STATUS_LABELS
from .library_format import fmt_full, fmt_exposure, fmt_clouds

VIEWER_MAX = 720  # px — longest edge shown in the dialog

# (label, frame key) — metadata grid, four columns. ``None`` keys are computed.
_FIELDS = (
    ("Camera", "camera"), ("Exposure", "exposure"), ("Gain", "gain"),
    ("Sensor", "temp"), ("Clouds", "clouds"),
)


class ImageViewerDialog(QDialog):
    """Enlarged frame + metadata, navigable across a night's frames."""

    def __init__(self, frames, start_index, read_full, parent=None):
        super().__init__(parent)
        self._frames = frames
        self._index = start_index
        self._read_full = read_full

        self.setWindowTitle("Library Image")
        self.setStyleSheet(f"QDialog {{ background-color: {Colors.bg_app}; }}")
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.base, Spacing.base, Spacing.base, Spacing.base)
        layout.setSpacing(Spacing.md)

        layout.addLayout(self._build_header())
        layout.addLayout(self._build_image_row())
        self.meta_host = QWidget()
        self.meta_grid = QGridLayout(self.meta_host)
        self.meta_grid.setHorizontalSpacing(Spacing.base)
        self.meta_grid.setVerticalSpacing(Spacing.md)
        layout.addWidget(self.meta_host)
        layout.addLayout(self._build_footer())

        self._refresh()

    def _build_header(self):
        row = QHBoxLayout()
        self.title_label = StrongBodyLabel("")
        self.title_label.setStyleSheet(f"color: {Colors.text_primary};")
        row.addWidget(self.title_label)
        self.frame_label = CaptionLabel("")
        self.frame_label.setStyleSheet(f"color: {Colors.text_muted};")
        row.addWidget(self.frame_label)
        row.addStretch()
        return row

    def _build_image_row(self):
        row = QHBoxLayout()
        self.prev_btn = PushButton()
        self.prev_btn.setIcon(mdi('chevron-left'))
        self.prev_btn.clicked.connect(lambda: self._navigate(-1))
        row.addWidget(self.prev_btn)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(VIEWER_MAX, 360)
        row.addWidget(self.image_label, 1)

        self.next_btn = PushButton()
        self.next_btn.setIcon(mdi('chevron-right'))
        self.next_btn.clicked.connect(lambda: self._navigate(1))
        row.addWidget(self.next_btn)
        return row

    def _build_footer(self):
        row = QHBoxLayout()
        row.addStretch()
        close_btn = PrimaryPushButton("Close")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        return row

    # -- navigation --------------------------------------------------------

    def _navigate(self, delta):
        new_index = self._index + delta
        if 0 <= new_index < len(self._frames):
            self._index = new_index
            self._refresh()

    def _refresh(self):
        frame = self._frames[self._index]
        self.title_label.setText(fmt_full(frame.get("captured_at")))
        self.frame_label.setText(f"frame {self._index + 1:,} / {len(self._frames):,}")
        self.prev_btn.setEnabled(self._index > 0)
        self.next_btn.setEnabled(self._index < len(self._frames) - 1)

        data = self._read_full(frame["id"]) if self._read_full else None
        if data:
            pix = QPixmap()
            if pix.loadFromData(data):
                if max(pix.width(), pix.height()) > VIEWER_MAX:
                    pix = pix.scaled(VIEWER_MAX, VIEWER_MAX, Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation)
                self.image_label.setPixmap(pix)
                self.image_label.setText("")
        else:
            self.image_label.setText("That image is no longer available.")
            self.image_label.setStyleSheet(f"color: {Colors.text_muted};")

        self._rebuild_meta(frame)

    def _rebuild_meta(self, frame):
        grid = self.meta_grid
        while grid.count():
            item = grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        fields = list(_FIELDS)
        w, h = frame.get("width"), frame.get("height")
        fields.append(("Resolution", None))
        status = S.row_status(frame)
        cells = []
        for label, key in fields:
            if key is None:
                value = f"{w}×{h}" if w and h else "—"
            elif key == "exposure":
                value = fmt_exposure(frame.get("exposure"))
            elif key == "clouds":
                value = fmt_clouds(frame.get("clouds"))
            else:
                value = str(frame.get(key) or "—")
            cells.append((label, value))
        cells.append(("Roof", frame.get("roof") or "—"))
        cells.append(("Condition", STATUS_LABELS.get(status, "Unknown")))

        for i, (label, value) in enumerate(cells):
            grid.addWidget(self._meta_cell(label, value), i // 4, i % 4)

    def _meta_cell(self, label, value):
        cap = CaptionLabel(label)
        cap.setStyleSheet(f"color: {Colors.text_muted};")
        val = BodyLabel(value)
        val.setStyleSheet(f"color: {Colors.text_primary};")
        cell = QVBoxLayout()
        cell.setSpacing(0)
        cell.addWidget(cap)
        cell.addWidget(val)
        host = QWidget()
        host.setLayout(cell)
        return host

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Left,):
            self._navigate(-1)
        elif event.key() in (Qt.Key_Right,):
            self._navigate(1)
        else:
            super().keyPressEvent(event)
