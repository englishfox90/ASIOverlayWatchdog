"""
Telemetry Bar Component

Thin monospace strip pinned to the bottom of the window showing technical
frame metrics: DISK · FILE · EXP · GAIN · SENSOR on the left, LAST CAPTURE and
the app version on the right.

Layout + display formatting only. Values are pushed in from the main window's
status timer and per-frame handlers; per-frame cells mute to "—" when idle or
when no camera is connected.
"""
import re

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel
from PySide6.QtCore import Qt

from ..theme.tokens import Colors, Typography
from ..theme.styles import paint_border_lines

_DASH = "—"


class TelemetryBar(QFrame):
    """Bottom mono metrics strip."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame_state = None   # 'live' | 'idle' | 'disconnected'
        self._build()

    def _build(self):
        self.setFixedHeight(30)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"TelemetryBar {{ background: {Colors.bg_surface}; }}")
        lay = QHBoxLayout(self)
        # 1px top inset balances the painted top border so cells sit centered.
        lay.setContentsMargins(0, 1, 0, 0)
        lay.setSpacing(0)

        self._disk = self._make_cell(first=True)
        self._exp = self._make_cell()
        self._gain = self._make_cell()
        self._sensor = self._make_cell()
        for c in (self._disk, self._exp, self._gain, self._sensor):
            lay.addWidget(c)

        lay.addStretch(1)

        self._last = self._make_cell()
        self._version = self._make_cell()
        lay.addWidget(self._last)
        lay.addWidget(self._version)

        self.set_disk(None)
        self._exp.setText(self._fmt("EXP", _DASH, muted=True))
        self._gain.setText(self._fmt("GAIN", _DASH, muted=True))
        self._sensor.setText(self._fmt("SENSOR", _DASH, muted=True))
        self._last.setText(self._fmt("LAST CAPTURE", _DASH, muted=True))
        self._version.setText("")

    def _make_cell(self, first: bool = False) -> QLabel:
        lbl = QLabel()
        lbl.setTextFormat(Qt.RichText)
        lbl.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        border = "" if first else f"border-left: 1px solid {Colors.border_subtle};"
        lbl.setStyleSheet(
            f"QLabel {{ font-family: {Typography.family_mono}; font-size: 11px; "
            f"padding: 0 14px; {border} }}"
        )
        return lbl

    def _fmt(self, label: str, value: str, muted: bool = False) -> str:
        vcolor = Colors.text_muted if muted else Colors.text_primary
        return (
            f"<span style='color:{Colors.text_secondary};'>{label} </span>"
            f"<span style='color:{vcolor};'>{value}</span>"
        )

    # --- Public API ------------------------------------------------------
    def set_version(self, version: str):
        self._version.setText(
            f"<span style='color:{Colors.text_muted};'>v{version}</span>"
        )

    def set_disk(self, free_gb):
        if free_gb is None:
            self._disk.setText(self._fmt("DISK", _DASH, muted=True))
        else:
            self._disk.setText(self._fmt("DISK", f"{self._human_size(free_gb)} free"))

    @staticmethod
    def _fmt_exposure(raw) -> str:
        """Compact exposure: long float seconds -> 2dp, scaled to ms/s/m."""
        if raw is None or raw == _DASH:
            return _DASH
        m = re.match(r'\s*([0-9]*\.?[0-9]+)\s*(ms|s|m)?', str(raw), re.I)
        if not m:
            return str(raw)
        val = float(m.group(1))
        unit = (m.group(2) or 's').lower()
        secs = val / 1000.0 if unit == 'ms' else (val * 60.0 if unit == 'm' else val)
        if secs >= 60:
            return f"{secs / 60:.2f}m"
        if secs >= 1:
            return f"{secs:.2f}s"
        return f"{secs * 1000:.0f}ms"

    @staticmethod
    def _human_size(gb: float) -> str:
        """Scale a GB figure to MB/GB/TB for a compact, readable label."""
        if gb >= 1024:
            return f"{gb / 1024:.1f} TB"
        if gb >= 1:
            return f"{gb:.1f} GB"
        return f"{gb * 1024:.0f} MB"

    def update_from_metadata(self, metadata: dict):
        """Populate FILE/EXP/GAIN/SENSOR/LAST CAPTURE from a fresh frame."""
        if not metadata:
            return
        self._frame_state = 'live'
        self._exp.setText(self._fmt("EXP", self._fmt_exposure(metadata.get('EXPOSURE'))))
        self._gain.setText(self._fmt("GAIN", metadata.get('GAIN', _DASH)))
        sensor = metadata.get('TEMP_F') or metadata.get('TEMP') or _DASH
        self._sensor.setText(self._fmt("SENSOR", sensor))
        dt = metadata.get('DATETIME', '')
        self._last.setText(self._fmt("LAST CAPTURE", dt[-8:] if dt else _DASH))

    def set_idle(self):
        """Capture stopped: mute live per-exposure cells, keep file/last/disk."""
        if self._frame_state == 'idle':
            return
        self._frame_state = 'idle'
        self._exp.setText(self._fmt("EXP", _DASH, muted=True))
        self._gain.setText(self._fmt("GAIN", _DASH, muted=True))
        self._sensor.setText(self._fmt("SENSOR", _DASH, muted=True))

    def set_disconnected(self):
        """No camera: mute every per-frame cell, keep disk."""
        if self._frame_state == 'disconnected':
            return
        # set_idle() mutes the live cells; force it past its own guard first.
        self._frame_state = None
        self.set_idle()
        self._frame_state = 'disconnected'
        self._last.setText(self._fmt("LAST CAPTURE", _DASH, muted=True))

    def paintEvent(self, event):
        super().paintEvent(event)
        paint_border_lines(self, [(0, 0, self.width(), 0)])
