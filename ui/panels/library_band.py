"""
Condition band — the colored timeline strip shared by the Library views.

Renders ``(frac_start, frac_end, status)`` segments (from
``services.library.sessions.status_segments``) as a rounded horizontal bar:
green = clear + roof open, amber = roof open + not clear, red = roof closed,
dark = capture gap, grey = unknown. Used both on the session cards (whole night
at a glance) and under the night-view scrubber.
"""
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QBrush, QPainterPath
from PySide6.QtCore import Qt

from services.library import sessions as S
from ..theme.tokens import Colors

STATUS_COLORS = {
    S.STATUS_CLEAR: Colors.success_default,
    S.STATUS_CLOUDY: Colors.warning_default,
    S.STATUS_CLOSED: Colors.error_default,
    S.STATUS_GAP: Colors.gray_4,
    S.STATUS_UNKNOWN: Colors.gray_6,
}

# Human labels for legends / tooltips.
STATUS_LABELS = {
    S.STATUS_CLEAR: "Clear · roof open",
    S.STATUS_CLOUDY: "Cloudy · roof open",
    S.STATUS_CLOSED: "Roof closed",
    S.STATUS_GAP: "No capture",
    S.STATUS_UNKNOWN: "Unknown",
}


def status_color(status):
    return QColor(STATUS_COLORS.get(status, Colors.gray_6))


class ConditionBand(QWidget):
    """A thin rounded bar colored by night condition segments."""

    def __init__(self, height=8, radius=4, parent=None):
        super().__init__(parent)
        self._segments = []
        self._radius = radius
        self.setFixedHeight(height)
        self.setMinimumWidth(40)

    def set_segments(self, segments):
        self._segments = list(segments or [])
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, self._radius, self._radius)
        painter.setClipPath(path)

        # Base fill so a sparse band still reads as a bar, not floating chips.
        painter.fillRect(0, 0, w, h, QColor(Colors.gray_3))

        for frac0, frac1, status in self._segments:
            x0 = int(round(frac0 * w))
            x1 = int(round(frac1 * w))
            width = max(1, x1 - x0)
            painter.fillRect(x0, 0, width, h, QBrush(status_color(status)))

        painter.end()
