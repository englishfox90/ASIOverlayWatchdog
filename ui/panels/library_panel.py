"""
Library Panel
In-app gallery of the rolling image library (services/library).

Layout/UI only — all disk work happens in ``LibraryController`` on a worker
thread; this panel just renders the pages it emits and opens a viewer dialog
when a thumbnail is clicked.
"""
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QLabel,
    QDialog, QGridLayout, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from qfluentwidgets import (
    CardWidget, SubtitleLabel, BodyLabel, CaptionLabel, PushButton,
    PrimaryPushButton, ComboBox
)

from ..theme.tokens import Colors, Typography, Spacing, Layout
from ..theme.icons import mdi
from ..controllers.library_controller import RANGE_OPTIONS

THUMB_WIDTH = 200   # px — gallery thumbnail width
VIEWER_MAX = 820    # px — longest edge shown in the viewer dialog


def _fmt_time(epoch):
    """Local 'YYYY-MM-DD HH:MM:SS' for a stored capture epoch."""
    try:
        return datetime.fromtimestamp(int(epoch)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "—"


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()


class _Thumbnail(QFrame):
    """A clickable gallery cell: scaled image + capture time."""

    clicked = Signal(dict)

    def __init__(self, item, pixmap, parent=None):
        super().__init__(parent)
        self._item = item
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"""
            _Thumbnail {{
                background-color: {Colors.bg_card};
                border: 1px solid {Colors.border_subtle};
                border-radius: {Layout.radius_md}px;
            }}
            _Thumbnail:hover {{ border-color: {Colors.accent_default}; }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.xs, Spacing.xs, Spacing.xs, Spacing.xs)
        layout.setSpacing(Spacing.xs)

        image = QLabel()
        image.setPixmap(pixmap)
        image.setAlignment(Qt.AlignCenter)
        layout.addWidget(image)

        caption = CaptionLabel(_fmt_time(item.get("captured_at")))
        caption.setStyleSheet(f"color: {Colors.text_muted};")
        caption.setAlignment(Qt.AlignCenter)
        layout.addWidget(caption)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._item)
        super().mousePressEvent(event)


class LibraryPanel(QScrollArea):
    """Full-page gallery of archived library frames."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self._loading = False
        self._loaded_once = False
        self._setup_ui()

    # -- UI ---------------------------------------------------------------

    def _setup_ui(self):
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(f"QScrollArea {{ background-color: {Colors.bg_app}; border: none; }}")

        content = QWidget()
        self.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(Spacing.base, Spacing.base, Spacing.base, Spacing.base)
        layout.setSpacing(Spacing.card_gap)

        # --- controls ---
        controls = CardWidget()
        row = QHBoxLayout(controls)
        row.setContentsMargins(Spacing.card_padding, Spacing.md, Spacing.card_padding, Spacing.md)
        row.setSpacing(Spacing.md)

        title = SubtitleLabel("Image Library")
        title.setStyleSheet(f"color: {Colors.text_primary};")
        row.addWidget(title)
        row.addSpacing(Spacing.base)

        range_label = BodyLabel("Show:")
        range_label.setStyleSheet(f"color: {Colors.text_secondary};")
        row.addWidget(range_label)

        self.range_combo = ComboBox()
        self.range_combo.addItems([label for label, _ in RANGE_OPTIONS])
        self.range_combo.setCurrentIndex(2)  # default "Last 7 days"
        self.range_combo.setFixedWidth(140)
        self.range_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        row.addWidget(self.range_combo)

        row.addStretch()

        self.count_label = CaptionLabel("")
        self.count_label.setStyleSheet(f"color: {Colors.text_muted};")
        row.addWidget(self.count_label)

        self.refresh_btn = PushButton("Refresh")
        self.refresh_btn.setIcon(mdi('refresh'))
        self.refresh_btn.clicked.connect(self.refresh)
        row.addWidget(self.refresh_btn)

        layout.addWidget(controls)

        # --- status line (loading / empty) ---
        self.status_label = BodyLabel("")
        self.status_label.setStyleSheet(f"color: {Colors.text_muted}; padding: {Spacing.base}px;")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        # --- thumbnail grid ---
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(Spacing.md)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        layout.addWidget(self.grid_host)

        layout.addStretch()

    # -- lifecycle / triggers ---------------------------------------------

    def showEvent(self, event):
        # Lazy first load when the user opens the panel; cheap manual refresh
        # via the button afterwards.
        super().showEvent(event)
        if not self._loaded_once:
            self.refresh()

    def _controller(self):
        return getattr(self.main_window, 'library_controller', None)

    def refresh(self):
        controller = self._controller()
        if controller is None or self._loading:
            return
        self._loading = True
        self._loaded_once = True
        self.status_label.setText("Loading…")
        self.status_label.show()
        since = RANGE_OPTIONS[self.range_combo.currentIndex()][1]
        controller.refresh(since_seconds=since)

    # -- slots (UI thread) -------------------------------------------------

    def on_page_ready(self, items, total):
        self._loading = False
        _clear_layout(self.grid)

        if not items:
            self.count_label.setText("")
            self.status_label.setText("No images archived for this range yet.")
            self.status_label.show()
            return

        self.status_label.hide()
        shown = len(items)
        suffix = f" (showing newest {shown})" if total > shown else ""
        self.count_label.setText(f"{total} image{'s' if total != 1 else ''}{suffix}")

        avail = self.viewport().width() or self.width() or (THUMB_WIDTH + Spacing.md)
        columns = max(1, avail // (THUMB_WIDTH + Spacing.md))
        for idx, item in enumerate(items):
            pixmap = QPixmap()
            pixmap.loadFromData(item.get("data", b""))
            if pixmap.isNull():
                continue
            thumb_pix = pixmap.scaledToWidth(THUMB_WIDTH, Qt.SmoothTransformation)
            # Drop the full bytes once the thumbnail is built — the viewer
            # re-fetches by id so the gallery only holds small scaled pixmaps.
            meta = {k: v for k, v in item.items() if k != "data"}
            thumb = _Thumbnail(meta, thumb_pix, self.grid_host)
            thumb.clicked.connect(self._open_viewer)
            self.grid.addWidget(thumb, idx // columns, idx % columns)

    def on_load_failed(self, message):
        self._loading = False
        self.status_label.setText(f"Could not load library: {message}")
        self.status_label.show()

    # -- viewer ------------------------------------------------------------

    def _open_viewer(self, item):
        controller = self._controller()
        data = controller.read_full(item["id"]) if controller else None
        if not data:
            self.status_label.setText("That image is no longer available.")
            self.status_label.show()
            return
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        if pixmap.isNull():
            return
        _ImageViewerDialog(pixmap, item, self).exec()


class _ImageViewerDialog(QDialog):
    """Click-to-enlarge viewer: the stored frame plus its metadata."""

    def __init__(self, pixmap, item, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Library Image")
        self.setStyleSheet(f"QDialog {{ background-color: {Colors.bg_app}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.base, Spacing.base, Spacing.base, Spacing.base)
        layout.setSpacing(Spacing.md)

        image = QLabel()
        if max(pixmap.width(), pixmap.height()) > VIEWER_MAX:
            pixmap = pixmap.scaled(VIEWER_MAX, VIEWER_MAX, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        image.setPixmap(pixmap)
        image.setAlignment(Qt.AlignCenter)
        layout.addWidget(image)

        meta = self._meta_text(item)
        if meta:
            meta_label = BodyLabel(meta)
            meta_label.setStyleSheet(f"color: {Colors.text_secondary};")
            meta_label.setWordWrap(True)
            layout.addWidget(meta_label)

        close_btn = PrimaryPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    @staticmethod
    def _meta_text(item):
        lines = [f"Captured: {_fmt_time(item.get('captured_at'))}"]
        for label, key in (
            ("Camera", "camera"), ("Exposure", "exposure"), ("Gain", "gain"),
            ("Temp", "temp"), ("Weather", "weather"), ("Session", "session"),
        ):
            value = item.get(key)
            if value:
                lines.append(f"{label}: {value}")
        w, h = item.get("width"), item.get("height")
        if w and h:
            lines.append(f"Resolution: {w}×{h}")
        return "    ".join(lines)
