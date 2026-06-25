"""
Library — night scrubber track (custom-painted, interactive).

A draggable timeline across one night: a sampled filmstrip, the condition band,
event pins for capture gaps, a playhead, and time ticks. Dragging (or clicking)
moves the playhead and emits ``index_changed`` with the frame index under it —
the night view loads that frame into the hero preview.

The whole track is laid out in **frame-index space** (every frame gets an equal
slice), not clock-time space. That keeps the filmstrip thumbnails, the playhead,
the condition band, and the ticks all on one axis — otherwise an uneven capture
cadence (a burst of frames in one minute, then a gap) slides the band off the
thumbnails. Capture gaps therefore show as event pins rather than as width.

Painted directly rather than built from nested layouts so dragging stays smooth
and the playhead can overlay the strip + band precisely.
"""
from PySide6.QtWidgets import QWidget, QToolTip
from PySide6.QtGui import QPainter, QPixmap, QColor, QPen, QFont, QBrush
from PySide6.QtCore import Qt, Signal, QRectF, QPointF

from services.library.sessions import row_status
from ..theme.tokens import Colors
from .library_band import status_color
from .library_format import fmt_clock, fmt_gap

# A gap at/above this length is flagged red rather than amber on the timeline.
_LONG_GAP_SECONDS = 1800  # 30 min
_PIN_HOVER_PX = 7         # cursor-to-pin x distance that triggers the tooltip

_PAD_X = 4
_PINS_TOP = 0
_PINS_H = 10
_STRIP_TOP = 12
_STRIP_H = 52
_BAND_TOP = _STRIP_TOP + _STRIP_H + 4
_BAND_H = 9
_TRACK_BOTTOM = _BAND_TOP + _BAND_H
_TOTAL_H = _TRACK_BOTTOM + 20


class Scrubber(QWidget):
    """Interactive filmstrip + condition band with a draggable playhead."""

    index_changed = Signal(int)  # frame index under the playhead (user drag/seek)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frames = []
        self._film = []        # [(frame_index, QPixmap)] — sampled thumbnails
        self._band = []        # [(frac0, frac1, status)] in frame-index space
        self._pins = []        # [(frac, gap_dict)] — capture-gap event pins
        self._id_index = {}    # image id -> frame index (pin click-to-seek)
        self._index = 0
        self._dragging = False
        self.setFixedHeight(_TOTAL_H)
        self.setMinimumWidth(120)
        self.setMouseTracking(True)  # hover tooltips on event pins
        self.setCursor(Qt.PointingHandCursor)

    # -- data --------------------------------------------------------------

    def set_data(self, frames, filmstrip_items, gaps):
        """Load one night. ``filmstrip_items`` is ``[(frame_index, jpeg bytes)]``."""
        self._load_frames(frames, gaps)

        self._film = []
        for idx, data in (filmstrip_items or []):
            pix = QPixmap()
            if pix.loadFromData(data):
                self._film.append((idx, pix))

        self._index = len(self._frames) // 2 if self._frames else 0
        self.update()

    def update_data(self, frames, gaps):
        """Replace the night's frames/gaps while preserving the playhead.

        Used when a frame arrives live: unlike ``set_data`` this keeps the
        current index (clamped) and the existing sampled filmstrip, so the
        playhead doesn't jump back to the middle as the timeline grows.
        """
        self._load_frames(frames, gaps)
        self._index = min(self._index, len(self._frames) - 1) if self._frames else 0
        self.update()

    def _load_frames(self, frames, gaps):
        """Rebuild frames, the id→index map, the condition band, and event pins.

        Shared by ``set_data`` / ``update_data``; each then sets the filmstrip
        and playhead index per its own policy.
        """
        self._frames = frames or []
        self._id_index = {row["id"]: i for i, row in enumerate(self._frames)}
        self._band = self._build_band()
        # Pins sit at the index boundary where the gap occurred, so they line up
        # with the thumbnail before the gap rather than a clock position.
        self._pins = []
        for g in (gaps or []):
            before = self._id_index.get(g["before_id"])
            if before is not None:
                self._pins.append((self._index_frac(before), g))

    def _build_band(self):
        """Condition segments in frame-index space (merging equal neighbours)."""
        n = len(self._frames)
        if n == 0:
            return []
        if n == 1:
            return [(0.0, 1.0, row_status(self._frames[0]))]
        segments = []
        run_status = None
        run_start = 0.0
        for i, row in enumerate(self._frames):
            status = row_status(row)
            left = 0.0 if i == 0 else (i - 0.5) / (n - 1)
            if status != run_status:
                if run_status is not None:
                    segments.append((run_start, left, run_status))
                run_status, run_start = status, left
        segments.append((run_start, 1.0, run_status))
        return segments

    def set_index(self, index):
        """Move the playhead without emitting (used by playback / events)."""
        if not self._frames:
            return
        self._index = max(0, min(len(self._frames) - 1, int(index)))
        self.update()

    def current_index(self):
        return self._index

    def frame_count(self):
        return len(self._frames)

    # -- interaction -------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or not self._frames:
            return
        gap = self._pin_at_x(event.position().x())
        if gap is not None:
            self._seek_to_id(gap["after_id"])  # clicking a pin jumps past the gap
            return
        self._dragging = True
        self._seek_to_x(event.position().x())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._seek_to_x(event.position().x())
            return
        gap = self._pin_at_x(event.position().x())
        if gap is not None:
            QToolTip.showText(
                event.globalPosition().toPoint(),
                f"Capture gap · {fmt_gap(gap['seconds'])}\nstarting {fmt_clock(gap['at'])}",
                self,
            )
        else:
            QToolTip.hideText()

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def _pin_at_x(self, x):
        """The gap whose pin is within hover range of ``x``, or None."""
        for frac, gap in self._pins:
            if abs(self._frac_to_x(frac) - x) <= _PIN_HOVER_PX:
                return gap
        return None

    def _seek_to_id(self, image_id):
        index = self._id_index.get(image_id)
        if index is None:
            return
        self._index = index
        self.update()
        self.index_changed.emit(index)

    def _seek_to_x(self, x):
        frac = self._x_to_frac(x)
        index = round(frac * (len(self._frames) - 1))
        if index != self._index:
            self._index = index
            self.update()
            self.index_changed.emit(index)
        else:
            self.update()

    # -- geometry ----------------------------------------------------------

    def _track_w(self):
        return max(1, self.width() - 2 * _PAD_X)

    def _frac_to_x(self, frac):
        return _PAD_X + frac * self._track_w()

    def _x_to_frac(self, x):
        return max(0.0, min(1.0, (x - _PAD_X) / self._track_w()))

    def _index_frac(self, index):
        n = len(self._frames)
        return (index / (n - 1)) if n > 1 else 0.0

    def _current_frac(self):
        return self._index_frac(self._index)

    # -- paint -------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self._track_w()

        self._paint_filmstrip(painter, w)
        self._paint_band(painter, w)
        self._paint_pins(painter)
        self._paint_playhead(painter)
        self._paint_ticks(painter, w)
        painter.end()

    def _paint_filmstrip(self, painter, w):
        painter.fillRect(QRectF(_PAD_X, _STRIP_TOP, w, _STRIP_H), QColor(Colors.gray_2))
        if not self._film:
            return
        # Each thumbnail is centred on its own frame's index position, so it sits
        # directly above the band colour and playhead for that frame.
        cell_w = (w / len(self._film)) * 0.92
        half = cell_w / 2
        for idx, pix in self._film:
            cx = self._frac_to_x(self._index_frac(idx))
            cx = max(_PAD_X + half, min(_PAD_X + w - half, cx))  # keep edges in view
            # Letterbox (KeepAspectRatio, centered) so square and rectangular
            # frames both show un-cropped and un-stretched — pier cameras vary.
            scaled = pix.scaled(int(cell_w), _STRIP_H, Qt.KeepAspectRatio,
                                Qt.SmoothTransformation)
            ox = cx - scaled.width() / 2
            oy = _STRIP_TOP + (_STRIP_H - scaled.height()) / 2
            painter.drawPixmap(QPointF(ox, oy), scaled)

    def _paint_band(self, painter, w):
        painter.fillRect(QRectF(_PAD_X, _BAND_TOP, w, _BAND_H), QColor(Colors.gray_3))
        for frac0, frac1, status in self._band:
            x0 = _PAD_X + frac0 * w
            x1 = _PAD_X + frac1 * w
            painter.fillRect(QRectF(x0, _BAND_TOP, max(1.0, x1 - x0), _BAND_H),
                             QBrush(status_color(status)))

    def _paint_pins(self, painter):
        for frac, gap in self._pins:
            cx = self._frac_to_x(frac)
            severe = gap["seconds"] >= _LONG_GAP_SECONDS
            color = QColor(Colors.error_default if severe else Colors.warning_default)
            painter.setPen(QPen(QColor(Colors.gray_2), 1.5))  # outline for contrast
            painter.setBrush(color)
            painter.drawEllipse(QRectF(cx - 4, _PINS_TOP, 8, 8))

    def _paint_playhead(self, painter):
        if not self._frames:
            return
        x = self._frac_to_x(self._current_frac())
        painter.setPen(QPen(QColor(Colors.accent_text), 2))
        painter.drawLine(int(x), _STRIP_TOP - 2, int(x), _TRACK_BOTTOM + 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(Colors.accent_text))
        painter.drawEllipse(QRectF(x - 5, _STRIP_TOP - 7, 10, 10))

    def _paint_ticks(self, painter, w):
        if not self._frames:
            return
        last = len(self._frames) - 1
        font = QFont()
        font.setPointSize(7)
        painter.setFont(font)
        painter.setPen(QColor(Colors.text_muted))
        y = _TRACK_BOTTOM + 14
        for i in range(5):
            frac = i / 4
            # Index-space axis: label each tick with the time of the frame that
            # sits there, so ticks line up with the thumbnails above them.
            label = fmt_clock(self._frames[round(frac * last)]["captured_at"])
            x = _PAD_X + frac * w
            if i == 0:
                rect = QRectF(x, y - 10, 60, 12)
                painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, label)
            elif i == 4:
                rect = QRectF(x - 60, y - 10, 60, 12)
                painter.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, label)
            else:
                rect = QRectF(x - 30, y - 10, 60, 12)
                painter.drawText(rect, Qt.AlignHCenter | Qt.AlignVCenter, label)
