"""
Library — night scrubber track (custom-painted, interactive).

A draggable timeline across one night: a sampled filmstrip, the condition band,
event pins for capture gaps, a playhead, and time ticks. Dragging (or clicking)
moves the playhead and emits ``index_changed`` with the frame index under it —
the night view loads that frame into the hero preview.

Painted directly rather than built from nested layouts so dragging stays smooth
and the playhead can overlay the strip + band precisely.
"""
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QPixmap, QColor, QPen, QFont, QBrush
from PySide6.QtCore import Qt, Signal, QRectF

from ..theme.tokens import Colors
from .library_band import status_color
from .library_format import fmt_clock

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
        self._pixmaps = []
        self._band = []
        self._pins = []        # fractions (0-1) of capture-gap events
        self._index = 0
        self._dragging = False
        self.setFixedHeight(_TOTAL_H)
        self.setMinimumWidth(120)
        self.setCursor(Qt.PointingHandCursor)

    # -- data --------------------------------------------------------------

    def set_data(self, frames, filmstrip_items, band, gaps):
        """Load one night. ``filmstrip_items`` is ``[(frame_index, jpeg bytes)]``."""
        self._frames = frames or []
        self._band = band or []
        self._pixmaps = []
        for _idx, data in (filmstrip_items or []):
            pix = QPixmap()
            if pix.loadFromData(data):
                self._pixmaps.append(pix)

        self._pins = []
        if self._frames:
            start = self._frames[0]["captured_at"]
            span = max(1, self._frames[-1]["captured_at"] - start)
            for g in (gaps or []):
                self._pins.append(max(0.0, min(1.0, (g["at"] - start) / span)))

        self._index = len(self._frames) // 2 if self._frames else 0
        self.update()

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
        if event.button() == Qt.LeftButton and self._frames:
            self._dragging = True
            self._seek_to_x(event.position().x())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._seek_to_x(event.position().x())

    def mouseReleaseEvent(self, event):
        self._dragging = False

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

    def _current_frac(self):
        n = len(self._frames)
        return (self._index / (n - 1)) if n > 1 else 0.0

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
        if not self._pixmaps:
            return
        gap = 2
        n = len(self._pixmaps)
        cell_w = (w - gap * (n - 1)) / n
        for i, pix in enumerate(self._pixmaps):
            x = _PAD_X + i * (cell_w + gap)
            target = QRectF(x, _STRIP_TOP, cell_w, _STRIP_H)
            scaled = pix.scaled(int(cell_w) + 1, _STRIP_H, Qt.KeepAspectRatioByExpanding,
                                Qt.SmoothTransformation)
            painter.save()
            painter.setClipRect(target)
            painter.drawPixmap(target.topLeft(), scaled)
            painter.restore()

    def _paint_band(self, painter, w):
        painter.fillRect(QRectF(_PAD_X, _BAND_TOP, w, _BAND_H), QColor(Colors.gray_3))
        for frac0, frac1, status in self._band:
            x0 = _PAD_X + frac0 * w
            x1 = _PAD_X + frac1 * w
            painter.fillRect(QRectF(x0, _BAND_TOP, max(1.0, x1 - x0), _BAND_H),
                             QBrush(status_color(status)))

    def _paint_pins(self, painter):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(Colors.warning_default))
        for frac in self._pins:
            cx = self._frac_to_x(frac)
            painter.drawEllipse(QRectF(cx - 3, _PINS_TOP, 6, 6))

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
        start = self._frames[0]["captured_at"]
        end = self._frames[-1]["captured_at"]
        font = QFont()
        font.setPointSize(7)
        painter.setFont(font)
        painter.setPen(QColor(Colors.text_muted))
        y = _TRACK_BOTTOM + 14
        for i in range(5):
            frac = i / 4
            label = fmt_clock(start + frac * (end - start))
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
