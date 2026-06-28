"""
Library — session list view (layout only).

The first screen of the Library flow: archived frames grouped into nights, one
card per night. A card shows a cover thumbnail, the date + time range, a status
badge, the condition band for the whole night, and a few stats. Clicking a card
asks the container to open that night in the scrubber.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap

from qfluentwidgets import (
    CardWidget, SubtitleLabel, BodyLabel, CaptionLabel, PushButton, ComboBox
)

from ..theme.tokens import Colors, Spacing, Layout
from ..theme.icons import mdi
from .library_band import ConditionBand
from .library_format import fmt_clock, fmt_temp_c, fmt_gap

COVER_SIZE = 84  # px — square cover thumbnail on each session card


class SessionListView(QScrollArea):
    """Scrollable list of night cards with a range filter."""

    session_clicked = Signal(object)   # session summary dict
    refresh_requested = Signal()

    def __init__(self, range_options, parent=None):
        super().__init__(parent)
        self._range_options = range_options
        self._setup_ui()

    # -- UI ----------------------------------------------------------------

    def _setup_ui(self):
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(f"QScrollArea {{ background-color: {Colors.bg_app}; border: none; }}")

        content = QWidget()
        self.setWidget(content)
        layout = QVBoxLayout(content)
        # Extra right margin so the count/Refresh and the card chevron don't hug
        # the edge (and leaves room for the scrollbar when the list overflows).
        layout.setContentsMargins(Spacing.base, Spacing.base, Spacing.lg, Spacing.base)
        layout.setSpacing(Spacing.card_gap)

        layout.addWidget(self._build_controls())

        self.status_label = BodyLabel("")
        self.status_label.setStyleSheet(f"color: {Colors.text_muted}; padding: {Spacing.base}px;")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        self.cards_host = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_host)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(Spacing.md)
        layout.addWidget(self.cards_host)

        layout.addStretch()

    def _build_controls(self):
        controls = CardWidget()
        row = QHBoxLayout(controls)
        row.setContentsMargins(Spacing.card_padding, Spacing.md, Spacing.card_padding, Spacing.md)
        row.setSpacing(Spacing.md)

        title = SubtitleLabel("Image Library")
        title.setStyleSheet(f"color: {Colors.text_primary};")
        row.addWidget(title)
        row.addSpacing(Spacing.base)

        label = BodyLabel("Show:")
        label.setStyleSheet(f"color: {Colors.text_secondary};")
        row.addWidget(label)

        self.range_combo = ComboBox()
        self.range_combo.addItems([lbl for lbl, _ in self._range_options])
        self.range_combo.setCurrentIndex(0)
        self.range_combo.setFixedWidth(150)
        self.range_combo.currentIndexChanged.connect(lambda _i: self.refresh_requested.emit())
        row.addWidget(self.range_combo)

        row.addStretch()

        self.count_label = CaptionLabel("")
        self.count_label.setStyleSheet(f"color: {Colors.text_muted};")
        row.addWidget(self.count_label)

        refresh_btn = PushButton("Refresh")
        refresh_btn.setIcon(mdi('refresh'))
        refresh_btn.clicked.connect(self.refresh_requested.emit)
        row.addWidget(refresh_btn)

        return controls

    # -- state -------------------------------------------------------------

    def current_range(self):
        """Resolved lookback seconds for the selected range (None = all)."""
        idx = max(0, self.range_combo.currentIndex())
        return self._range_options[idx][1]

    def set_loading(self):
        self._set_status("Loading sessions…")
        self.count_label.setText("")

    def set_error(self, message):
        self._set_status(f"Could not load library: {message}")

    def _set_status(self, text):
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))

    def set_sessions(self, sessions):
        _clear_layout(self.cards_layout)

        if not sessions:
            self.count_label.setText("")
            self._set_status("No images archived for this range yet.")
            return

        self._set_status("")
        total_frames = sum(s.get("frame_count", 0) for s in sessions)
        n = len(sessions)
        self.count_label.setText(
            f"{n} session{'s' if n != 1 else ''} · {total_frames:,} frames"
        )

        for session in sessions:
            card = _SessionCard(session)
            card.clicked.connect(lambda s=session: self.session_clicked.emit(s))
            self.cards_layout.addWidget(card)


class _SessionCard(CardWidget):
    """One night: cover, date/range, status badge, condition band, stats."""

    clicked = Signal()

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self._session = session
        self.setCursor(Qt.PointingHandCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(Spacing.md, Spacing.md, Spacing.md, Spacing.md)
        row.setSpacing(Spacing.base)

        row.addWidget(self._build_cover())
        row.addLayout(self._build_body(), 1)
        row.addWidget(self._build_chevron())

    def _build_cover(self):
        cover = QLabel()
        cover.setFixedSize(COVER_SIZE, COVER_SIZE)
        cover.setAlignment(Qt.AlignCenter)
        cover.setStyleSheet(
            f"background-color: {Colors.gray_2}; border-radius: {Layout.radius_md}px;"
        )
        data = self._session.get("cover_data")
        if data:
            pix = QPixmap()
            if pix.loadFromData(data):
                cover.setPixmap(
                    pix.scaled(COVER_SIZE, COVER_SIZE, Qt.KeepAspectRatioByExpanding,
                               Qt.SmoothTransformation)
                )
                cover.setScaledContents(False)
        else:
            cover.setText("no\nimage")
            cover.setStyleSheet(
                f"background-color: {Colors.gray_2}; border-radius: {Layout.radius_md}px;"
                f" color: {Colors.text_muted};"
            )
        return cover

    def _build_body(self):
        body = QVBoxLayout()
        body.setSpacing(Spacing.sm)

        header = QHBoxLayout()
        header.setSpacing(Spacing.sm)
        date = BodyLabel(self._session.get("key", "—"))
        date.setStyleSheet(f"color: {Colors.text_primary}; font-weight: 600;")
        header.addWidget(date)

        rng = CaptionLabel(
            f"{fmt_clock(self._session.get('start_epoch'))} – "
            f"{fmt_clock(self._session.get('end_epoch'))}"
        )
        rng.setStyleSheet(f"color: {Colors.text_muted};")
        header.addWidget(rng)
        header.addWidget(self._build_badge())
        header.addStretch()
        body.addLayout(header)

        band = ConditionBand(height=8)
        band.set_segments(self._session.get("band"))
        band.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        body.addWidget(band)

        body.addWidget(self._build_stats())
        return body

    def _build_badge(self):
        gap = self._session.get("max_gap_seconds", 0)
        closed = self._session.get("roof_closed")
        if gap and gap >= 600:
            return _badge(fmt_gap(gap), Colors.error_text, Colors.error_bg)
        if closed:
            return _badge("roof closed", Colors.error_text, Colors.error_bg)
        if gap:
            return _badge(fmt_gap(gap), Colors.warning_text, Colors.warning_bg)
        return _badge("clean", Colors.success_text, Colors.success_bg)

    def _build_stats(self):
        parts = [f"{self._session.get('frame_count', 0):,} frames"]
        temp = fmt_temp_c(self._session.get("min_temp_c"))
        if temp:
            parts.append(f"min sensor {temp}")
        # Star/seeing peaks only appear on nights where star detection ran
        # (roof open + dark), so they stay off daytime / roof-closed cards.
        stars = self._session.get("max_stars")
        if stars:
            parts.append(f"peak {stars:,} stars")
        seeing = self._session.get("best_seeing")
        if seeing:
            parts.append(f"sky quality {seeing}")
        clear_pct = self._session.get("clear_pct")
        stats = CaptionLabel("      ".join(parts))
        stats.setStyleSheet(f"color: {Colors.text_muted};")

        wrap = QHBoxLayout()
        # Small left indent so the stats line isn't flush against the card edge.
        wrap.setContentsMargins(Spacing.sm, 0, 0, 0)
        wrap.setSpacing(Spacing.base)
        wrap.addWidget(stats)
        if clear_pct is not None:
            clear = CaptionLabel(f"{clear_pct}% clear")
            clear.setStyleSheet(f"color: {Colors.success_text};")
            wrap.addWidget(clear)
        wrap.addStretch()
        host = QWidget()
        host.setLayout(wrap)
        return host

    def _build_chevron(self):
        chevron = QLabel("›")
        chevron.setStyleSheet(f"color: {Colors.accent_text}; font-size: 20px;")
        chevron.setAlignment(Qt.AlignCenter)
        return chevron

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def _badge(text, fg, bg):
    label = CaptionLabel(text)
    label.setStyleSheet(
        f"color: {fg}; background-color: {bg};"
        f" border-radius: {Layout.radius_full}px; padding: 2px 10px;"
    )
    return label


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
