"""
Library — night view (layout only).

The second screen: one night opened from the session list. A hero preview of the
current frame, a metadata panel, and the draggable scrubber below. Dragging the
scrubber (or pressing play) walks the playhead across the night and the hero
updates live. Clicking the hero opens the single-image view.

All disk reads go through ``LibraryController`` — this view only renders frames
the controller hands back and asks for the frame under the playhead.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QPixmap

from qfluentwidgets import PushButton, CaptionLabel, BodyLabel, StrongBodyLabel

from services.library import sessions as S
from ..theme.tokens import Colors, Spacing, Layout
from ..theme.icons import mdi
from .library_band import STATUS_COLORS, STATUS_LABELS
from .library_scrubber import Scrubber
from .library_format import fmt_clock, fmt_gap, fmt_time_seconds

# Playback advances this many frames per tick, by speed button.
_SPEEDS = (1, 8, 30)
_TICK_MS = 80

_META_FIELDS = (
    ("Temp", "temp"), ("Exposure", "exposure"), ("Gain", "gain"),
    ("Camera", "camera"), ("Weather", "weather"),
)


class NightView(QWidget):
    """Hero preview + metadata + scrubber for a single night."""

    back_requested = Signal()
    frame_request = Signal(int)   # image id to load into the hero
    image_activated = Signal()    # open the current frame in the single-image view

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session = None
        self._frames = []
        self._id_index = {}
        self._speed = _SPEEDS[0]
        self._pending_hero_id = None

        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._advance)

        self._setup_ui()

    # -- UI ----------------------------------------------------------------

    def _setup_ui(self):
        # Scope to this widget — a selector-less background leaks to all children.
        self.setObjectName("NightView")
        self.setStyleSheet(f"#NightView {{ background-color: {Colors.bg_app}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.base, Spacing.base, Spacing.base, Spacing.base)
        layout.setSpacing(Spacing.md)

        layout.addLayout(self._build_breadcrumb())
        layout.addLayout(self._build_main(), 1)
        layout.addWidget(self._build_scrubber_block())

    def _build_breadcrumb(self):
        row = QHBoxLayout()
        row.setSpacing(Spacing.sm)
        back = PushButton("Library")
        back.setIcon(mdi('chevron-left'))
        back.clicked.connect(self.back_requested.emit)
        row.addWidget(back)

        self.title_label = StrongBodyLabel("Night")
        self.title_label.setStyleSheet(f"color: {Colors.text_primary};")
        row.addWidget(self.title_label)

        self.issue_badge = CaptionLabel("")
        self.issue_badge.setVisible(False)
        row.addWidget(self.issue_badge)
        row.addStretch()
        return row

    def _build_main(self):
        row = QHBoxLayout()
        row.setSpacing(Spacing.base)
        row.addWidget(self._build_hero(), 1)
        row.addWidget(self._build_meta_panel())
        return row

    def _build_hero(self):
        self.hero = _ClickableFrame()
        self.hero.setStyleSheet(
            f"background-color: #08070d; border-radius: {Layout.radius_md}px;"
        )
        self.hero.setMinimumSize(360, 360)
        self.hero.clicked.connect(self._on_hero_clicked)

        hero_layout = QVBoxLayout(self.hero)
        hero_layout.setContentsMargins(0, 0, 0, 0)
        self.hero_image = QLabel()
        self.hero_image.setAlignment(Qt.AlignCenter)
        self.hero_image.setText("")
        hero_layout.addWidget(self.hero_image)

        self.overlay_label = CaptionLabel("", self.hero)
        self.overlay_label.setStyleSheet(
            f"color: white; background-color: rgba(0,0,0,120);"
            f" border-radius: {Layout.radius_sm}px; padding: 3px 8px;"
        )
        self.overlay_label.move(12, 12)
        return self.hero

    def _build_meta_panel(self):
        panel = QFrame()
        panel.setFixedWidth(264)
        panel.setStyleSheet(
            f"QFrame {{ background-color: {Colors.bg_card};"
            f" border: 1px solid {Colors.border_subtle};"
            f" border-radius: {Layout.radius_md}px; }}"
        )
        v = QVBoxLayout(panel)
        v.setContentsMargins(Spacing.base, Spacing.base, Spacing.base, Spacing.base)
        v.setSpacing(Spacing.md)

        header = QHBoxLayout()
        title = CaptionLabel("CURRENT FRAME")
        title.setStyleSheet(f"color: {Colors.text_muted}; letter-spacing: 1px;")
        header.addWidget(title)
        header.addStretch()
        self.cond_badge = CaptionLabel("")
        header.addWidget(self.cond_badge)
        v.addLayout(header)

        self.meta_grid = QGridLayout()
        self.meta_grid.setHorizontalSpacing(Spacing.md)
        self.meta_grid.setVerticalSpacing(Spacing.sm)
        self._meta_values = {}
        for i, (label, key) in enumerate(_META_FIELDS + (("Resolution", "_res"),)):
            col = (i % 2) * 2
            rowi = i // 2
            cap = CaptionLabel(label)
            cap.setStyleSheet(f"color: {Colors.text_muted};")
            val = BodyLabel("—")
            val.setStyleSheet(f"color: {Colors.text_primary};")
            cell = QVBoxLayout()
            cell.setSpacing(0)
            cell.addWidget(cap)
            cell.addWidget(val)
            host = QWidget()
            host.setLayout(cell)
            self.meta_grid.addWidget(host, rowi, col, 1, 2)
            self._meta_values[key] = val
        v.addLayout(self.meta_grid)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color: {Colors.border_subtle};")
        v.addWidget(divider)

        events_title = CaptionLabel("EVENTS TONIGHT")
        events_title.setStyleSheet(f"color: {Colors.text_muted}; letter-spacing: 1px;")
        v.addWidget(events_title)
        self.events_box = QVBoxLayout()
        self.events_box.setSpacing(Spacing.xs)
        v.addLayout(self.events_box)
        v.addStretch()
        return panel

    def _build_scrubber_block(self):
        block = QFrame()
        block.setStyleSheet(
            f"QFrame {{ background-color: {Colors.gray_2};"
            f" border-radius: {Layout.radius_md}px; }}"
        )
        v = QVBoxLayout(block)
        v.setContentsMargins(Spacing.base, Spacing.md, Spacing.base, Spacing.md)
        v.setSpacing(Spacing.sm)

        self.scrubber = Scrubber()
        self.scrubber.index_changed.connect(self._on_index_changed)
        v.addWidget(self.scrubber)

        v.addLayout(self._build_transport())
        return block

    def _build_transport(self):
        row = QHBoxLayout()
        row.setSpacing(Spacing.sm)

        self.prev_btn = PushButton()
        self.prev_btn.setIcon(mdi('skip-previous'))
        self.prev_btn.clicked.connect(lambda: self._step(-1))
        row.addWidget(self.prev_btn)

        self.play_btn = PushButton("Play")
        self.play_btn.setIcon(mdi('play'))
        self.play_btn.clicked.connect(self._toggle_play)
        row.addWidget(self.play_btn)

        self.next_btn = PushButton()
        self.next_btn.setIcon(mdi('skip-next'))
        self.next_btn.clicked.connect(lambda: self._step(1))
        row.addWidget(self.next_btn)

        row.addSpacing(Spacing.md)
        self._speed_btns = []
        for speed in _SPEEDS:
            btn = PushButton(f"{speed}×")
            btn.setFixedWidth(48)
            btn.clicked.connect(lambda _c=False, s=speed: self._set_speed(s))
            row.addWidget(btn)
            self._speed_btns.append((speed, btn))
        self._set_speed(self._speed)

        row.addStretch()
        self.counter_label = CaptionLabel("")
        self.counter_label.setStyleSheet(f"color: {Colors.text_muted};")
        row.addWidget(self.counter_label)
        return row

    # -- load / public API -------------------------------------------------

    def begin_load(self, session):
        self.stop()
        self._session = session
        self._frames = []
        self._id_index = {}
        self.title_label.setText(f"Night · {session.get('key', '')}")
        self._update_issue_badge(session)
        self.hero_image.setText("Loading night…")
        self.hero_image.setStyleSheet(f"color: {Colors.text_muted};")
        self.overlay_label.setText("")
        self.counter_label.setText("")

    def set_frames(self, payload):
        if payload.get("session") is not self._session and \
                payload.get("session", {}).get("key") != (self._session or {}).get("key"):
            return  # a newer night was opened before this load returned
        self._frames = payload.get("frames", [])
        self._id_index = {row["id"]: i for i, row in enumerate(self._frames)}

        if not self._frames:
            self.hero_image.setText("No frames archived for this night.")
            return

        self.scrubber.set_data(
            self._frames,
            payload.get("filmstrip", []),
            self._session.get("band"),
            self._session.get("gaps"),
        )
        self._build_events(self._session.get("gaps", []))
        self._on_index_changed(self.scrubber.current_index())

    def on_frame_ready(self, image_id, data):
        if image_id != self._pending_hero_id:
            return  # stale; the playhead moved on
        pix = QPixmap()
        if not pix.loadFromData(data):
            return
        self._set_hero_pixmap(pix)

    def stop(self):
        if self._timer.isActive():
            self._timer.stop()
            self.play_btn.setText("Play")
            self.play_btn.setIcon(mdi('play'))

    def current_index(self):
        return self.scrubber.current_index()

    def frames(self):
        return self._frames

    def current_frame(self):
        idx = self.scrubber.current_index()
        if 0 <= idx < len(self._frames):
            return self._frames[idx]
        return None

    # -- transport / scrubbing --------------------------------------------

    def _toggle_play(self):
        if self._timer.isActive():
            self.stop()
        elif self._frames:
            self.play_btn.setText("Pause")
            self.play_btn.setIcon(mdi('pause'))
            self._timer.start()

    def _advance(self):
        idx = self.scrubber.current_index() + self._speed
        if idx >= len(self._frames) - 1:
            idx = len(self._frames) - 1
            self.scrubber.set_index(idx)
            self._on_index_changed(idx)
            self.stop()
            return
        self.scrubber.set_index(idx)
        self._on_index_changed(idx)

    def _step(self, delta):
        self.stop()
        idx = self.scrubber.current_index() + delta
        self.scrubber.set_index(idx)
        self._on_index_changed(self.scrubber.current_index())

    def _set_speed(self, speed):
        self._speed = speed
        for value, btn in self._speed_btns:
            active = value == speed
            btn.setStyleSheet(
                f"background-color: {Colors.accent_subtle}; color: {Colors.accent_text};"
                if active else ""
            )

    def _on_index_changed(self, index):
        if not (0 <= index < len(self._frames)):
            return
        frame = self._frames[index]
        self._pending_hero_id = frame["id"]
        self.frame_request.emit(frame["id"])
        self._update_overlay(index, frame)
        self._update_meta(frame)
        self.counter_label.setText(f"frame {index + 1:,} / {len(self._frames):,} · drag to scrub")

    # -- rendering helpers -------------------------------------------------

    def _set_hero_pixmap(self, pix):
        avail = self.hero.size()
        target_w = max(120, avail.width() - 24)
        target_h = max(120, avail.height() - 24)
        self.hero_image.setPixmap(
            pix.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def _update_overlay(self, index, frame):
        self.overlay_label.setText(
            f"{fmt_clock(frame['captured_at'])} · frame {index + 1:,}"
        )
        self.overlay_label.adjustSize()

    def _update_meta(self, frame):
        for _label, key in _META_FIELDS:
            self._meta_values[key].setText(str(frame.get(key) or "—"))
        w, h = frame.get("width"), frame.get("height")
        self._meta_values["_res"].setText(f"{w}×{h}" if w and h else "—")

        status = S.row_status(frame)
        self.cond_badge.setText(STATUS_LABELS.get(status, "Unknown"))
        color = STATUS_COLORS.get(status, Colors.gray_6)
        self.cond_badge.setStyleSheet(
            f"color: {Colors.bg_app}; background-color: {color};"
            f" border-radius: {Layout.radius_full}px; padding: 2px 9px;"
        )

    def _update_issue_badge(self, session):
        gap = session.get("max_gap_seconds", 0)
        if gap:
            self.issue_badge.setText(fmt_gap(gap))
            self.issue_badge.setStyleSheet(
                f"color: {Colors.error_text}; background-color: {Colors.error_bg};"
                f" border-radius: {Layout.radius_full}px; padding: 2px 9px;"
            )
            self.issue_badge.setVisible(True)
        else:
            self.issue_badge.setVisible(False)

    def _build_events(self, gaps):
        while self.events_box.count():
            item = self.events_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not gaps:
            none_label = CaptionLabel("No capture gaps")
            none_label.setStyleSheet(f"color: {Colors.text_muted};")
            self.events_box.addWidget(none_label)
            return
        for gap in gaps:
            label = _LinkLabel(f"{fmt_clock(gap['at'])}  ·  {fmt_gap(gap['seconds'])}")
            label.setStyleSheet(f"color: {Colors.text_secondary};")
            label.clicked.connect(lambda g=gap: self._seek_to_id(g["after_id"]))
            self.events_box.addWidget(label)

    def _seek_to_id(self, image_id):
        self.stop()
        index = self._id_index.get(image_id)
        if index is None:
            return
        self.scrubber.set_index(index)
        self._on_index_changed(index)

    def _on_hero_clicked(self):
        if self.current_frame() is not None:
            self.image_activated.emit()


class _ClickableFrame(QFrame):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class _LinkLabel(CaptionLabel):
    clicked = Signal()

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)
