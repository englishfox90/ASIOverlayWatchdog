"""
Guided all-sky calibration dialog (UI only).

Shows the latest frame; the user clicks bright stars (clicks snap to detected
centroids) and names each one. On Solve it hands the collected
(pixel_x, pixel_y, ra_deg, dec_deg) anchors back to the caller, which runs the
solver off-thread. No business logic lives here — collecting anchors only.

The companion solver is services/allsky/guided_calibration.py; the controller
hooks are AllSkyController.prepare_guided_calibration / start_guided_calibration.
"""
import math
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QColor
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QLabel, QListWidget, QPushButton,
    QComboBox, QWidget,
)

# Snap radius (image pixels) within which a click locks onto a detected star.
_SNAP_PX = 30.0
_MAX_DISPLAY = 760  # longest displayed image edge (px)


class _ClickableImage(QLabel):
    """Image label that reports clicks in ORIGINAL image coordinates."""

    def __init__(self, on_click, parent=None):
        super().__init__(parent)
        self._on_click = on_click
        self._scale = 1.0
        self._markers: List[Tuple[float, float, str]] = []  # img coords + label
        self._pending: Optional[Tuple[float, float]] = None
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)

    def set_base_pixmap(self, pix: QPixmap, scale: float):
        self._base = pix
        self._scale = scale
        self._redraw()

    def set_markers(self, markers, pending):
        self._markers = markers
        self._pending = pending
        self._redraw()

    def _redraw(self):
        if not hasattr(self, '_base'):
            return
        pix = self._base.copy()
        p = QPainter(pix)
        try:
            for ix, iy, label in self._markers:
                p.setPen(QPen(QColor(60, 220, 60), 2))
                x, y = ix * self._scale, iy * self._scale
                p.drawEllipse(QPoint(int(x), int(y)), 9, 9)
                p.drawText(int(x) + 11, int(y) - 6, label)
            if self._pending is not None:
                p.setPen(QPen(QColor(255, 210, 60), 2))
                x, y = self._pending[0] * self._scale, self._pending[1] * self._scale
                p.drawEllipse(QPoint(int(x), int(y)), 11, 11)
                p.drawLine(int(x) - 15, int(y), int(x) + 15, int(y))
                p.drawLine(int(x), int(y) - 15, int(x), int(y) + 15)
        finally:
            p.end()
        self.setPixmap(pix)

    def mousePressEvent(self, ev):
        if self._scale > 0:
            self._on_click(ev.position().x() / self._scale,
                           ev.position().y() / self._scale)


class GuidedCalibrationDialog(QDialog):
    """Collect user-identified star anchors for guided calibration."""

    def __init__(self, prep: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Guided All-Sky Calibration")
        self._prep = prep
        self._detections = prep.get('detections', [])
        self._candidates = prep.get('candidates', [])
        self._anchors: List[dict] = []   # {px, py, ra, dec, name}
        self._pending: Optional[Tuple[float, float]] = None
        # Result exposed to caller after accept().
        self.anchors: List[Tuple[float, float, float, float]] = []

        self._build_ui(prep['image'])
        self._refresh()

    # ------------------------------------------------------------------
    def _build_ui(self, pil_image):
        root = QHBoxLayout(self)

        # Left: clickable image.
        self._img = _ClickableImage(self._on_image_click)
        pix, scale = self._pil_to_pixmap(pil_image)
        self._img.set_base_pixmap(pix, scale)
        root.addWidget(self._img)

        # Right: controls.
        side = QVBoxLayout()
        root.addLayout(side)

        self._hint = QLabel(
            "Click a bright star (snaps to the nearest detected star),\n"
            "choose which star it is, then Add. Identify at least 4,\n"
            "spread across the sky, then Solve.")
        self._hint.setWordWrap(True)
        side.addWidget(self._hint)

        self._pending_lbl = QLabel("No star selected.")
        side.addWidget(self._pending_lbl)

        self._combo = QComboBox()
        for c in self._candidates:
            self._combo.addItem(f"{c['name']}  (mag {c['vmag']:.1f}, "
                                f"alt {c['alt']:.0f}°)", c)
        side.addWidget(self._combo)

        self._add_btn = QPushButton("Add this star")
        self._add_btn.clicked.connect(self._on_add)
        side.addWidget(self._add_btn)

        side.addWidget(QLabel("Identified stars:"))
        self._list = QListWidget()
        side.addWidget(self._list, 1)

        self._remove_btn = QPushButton("Remove selected")
        self._remove_btn.clicked.connect(self._on_remove)
        side.addWidget(self._remove_btn)

        row = QHBoxLayout()
        self._solve_btn = QPushButton("Solve")
        self._solve_btn.clicked.connect(self._on_solve)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        row.addWidget(self._solve_btn)
        side.addLayout(row)

    def _pil_to_pixmap(self, pil_image) -> Tuple[QPixmap, float]:
        img = pil_image.convert('RGB')
        w, h = img.size
        scale = min(1.0, _MAX_DISPLAY / float(max(w, h)))
        data = img.tobytes('raw', 'RGB')
        qimg = QImage(data, w, h, 3 * w, QImage.Format_RGB888).copy()
        if scale < 1.0:
            qimg = qimg.scaled(int(w * scale), int(h * scale),
                               Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return QPixmap.fromImage(qimg), scale

    # ------------------------------------------------------------------
    def _on_image_click(self, ix: float, iy: float):
        """Snap the click to the nearest detected star (image coords)."""
        best, best_d = None, _SNAP_PX
        for d in self._detections:
            dist = math.hypot(d[0] - ix, d[1] - iy)
            if dist <= best_d:
                best, best_d = (d[0], d[1]), dist
        self._pending = best if best is not None else (ix, iy)
        snapped = "snapped to detection" if best is not None else "no nearby detection"
        self._pending_lbl.setText(
            f"Selected ({self._pending[0]:.0f}, {self._pending[1]:.0f}) — {snapped}.")
        self._refresh()

    def _on_add(self):
        if self._pending is None:
            self._pending_lbl.setText("Click a star in the image first.")
            return
        c = self._combo.currentData()
        if not c:
            return
        self._anchors.append({
            'px': self._pending[0], 'py': self._pending[1],
            'ra': c['ra_deg'], 'dec': c['dec_deg'], 'name': c['name']})
        self._pending = None
        self._pending_lbl.setText("Star added.")
        self._refresh()

    def _on_remove(self):
        i = self._list.currentRow()
        if 0 <= i < len(self._anchors):
            self._anchors.pop(i)
            self._refresh()

    def _on_solve(self):
        self.anchors = [(a['px'], a['py'], a['ra'], a['dec']) for a in self._anchors]
        self.accept()

    def _refresh(self):
        self._list.clear()
        for a in self._anchors:
            self._list.addItem(f"{a['name']}  @ ({a['px']:.0f}, {a['py']:.0f})")
        markers = [(a['px'], a['py'], a['name']) for a in self._anchors]
        self._img.set_markers(markers, self._pending)
        n = len(self._anchors)
        self._solve_btn.setEnabled(n >= 4)
        self._solve_btn.setText(f"Solve ({n}/4)" if n < 4 else f"Solve ({n} stars)")
