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
    QCompleter, QDialog, QHBoxLayout, QVBoxLayout, QLabel,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, EditableComboBox, ListWidget,
    PushButton, PrimaryPushButton,
)

from ..theme.tokens import Spacing

# Snap radius within which a click locks onto a detected star. Expressed as a
# fraction of the sky radius so it stays a constant *display* distance at any
# frame resolution (a fixed 30 image-px was only ~7 display-px on 3552px
# frames — most careful clicks missed the snap and carried 10-20px of error,
# which alone exceeded the solver's RMS limit).
_SNAP_SKY_FRACTION = 0.035
_SNAP_MIN_PX = 30.0
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
        self._snap_px = max(_SNAP_MIN_PX,
                            _SNAP_SKY_FRACTION * float(prep.get('sky_r', 0.0)))
        self._anchors: List[dict] = []   # {px, py, ra, dec, name, snapped}
        self._pending: Optional[Tuple[float, float]] = None
        self._pending_snapped = False
        # Result exposed to caller after accept():
        # (px, py, ra_deg, dec_deg, name) per identified star.
        self.anchors: List[Tuple[float, float, float, float, str]] = []

        self._build_ui(prep['image'])
        self._refresh()

    # ------------------------------------------------------------------
    def _build_ui(self, pil_image):
        root = QHBoxLayout(self)
        root.setContentsMargins(Spacing.base, Spacing.base,
                                Spacing.base, Spacing.base)
        root.setSpacing(Spacing.base)

        # Left: clickable image.
        self._img = _ClickableImage(self._on_image_click)
        pix, scale = self._pil_to_pixmap(pil_image)
        self._img.set_base_pixmap(pix, scale)
        root.addWidget(self._img)

        # Right: controls.
        side = QVBoxLayout()
        side.setSpacing(Spacing.sm)
        root.addLayout(side)

        self._hint = BodyLabel(
            "Click a bright star (snaps to the nearest detected star), "
            "choose which star it is, then Add. Identify at least 4 — "
            "5 or more, spread across the sky, solves best — then Solve.")
        self._hint.setWordWrap(True)
        side.addWidget(self._hint)

        self._pending_lbl = CaptionLabel("No star selected.")
        side.addWidget(self._pending_lbl)

        self._combo = EditableComboBox()
        self._combo.setPlaceholderText("Search for a star by name…")
        for c in self._candidates:
            self._combo.addItem(f"{c['name']}  (mag {c['vmag']:.1f}, "
                                f"alt {c['alt']:.0f}°)", userData=c)
        self._combo.setCurrentIndex(-1)
        # EditableComboBox does no filtering by itself — its text handler
        # only exact-matches the FULL item string (which ends in "(mag …)"),
        # so typed star names never matched and the list had to be scrolled.
        # A contains-mode completer provides the intended type-to-search.
        completer = QCompleter(
            [self._combo.itemText(i) for i in range(self._combo.count())],
            self._combo)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        completer.setMaxVisibleItems(12)
        self._combo.setCompleter(completer)
        side.addWidget(self._combo)

        self._add_btn = PushButton("Add this star")
        self._add_btn.setCursor(Qt.PointingHandCursor)
        self._add_btn.clicked.connect(self._on_add)
        side.addWidget(self._add_btn)

        side.addWidget(CaptionLabel("Identified stars:"))
        self._list = ListWidget()
        side.addWidget(self._list, 1)

        self._remove_btn = PushButton("Remove selected")
        self._remove_btn.setCursor(Qt.PointingHandCursor)
        self._remove_btn.clicked.connect(self._on_remove)
        side.addWidget(self._remove_btn)

        row = QHBoxLayout()
        row.setSpacing(Spacing.sm)
        cancel = PushButton("Cancel")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        self._solve_btn = PrimaryPushButton("Solve")
        self._solve_btn.setCursor(Qt.PointingHandCursor)
        self._solve_btn.clicked.connect(self._on_solve)
        row.addStretch(1)
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
        best, best_d = None, self._snap_px
        for d in self._detections:
            dist = math.hypot(d[0] - ix, d[1] - iy)
            if dist <= best_d:
                best, best_d = (d[0], d[1]), dist
        self._pending = best if best is not None else (ix, iy)
        self._pending_snapped = best is not None
        snapped = ("snapped to detected star" if best is not None
                   else "no detected star nearby — the solve is much less "
                        "accurate with unsnapped clicks")
        self._pending_lbl.setText(
            f"Selected ({self._pending[0]:.0f}, {self._pending[1]:.0f}) — {snapped}.")
        self._refresh()

    def _on_add(self):
        if self._pending is None:
            self._pending_lbl.setText("Click a star in the image first.")
            return
        c = self._combo.currentData() or self._match_typed_star()
        if not c:
            self._pending_lbl.setText(
                "Choose which star this is — type a name to search the list.")
            return
        if any(a['name'] == c['name'] for a in self._anchors):
            self._pending_lbl.setText(
                f"{c['name']} is already identified — each star can only be "
                "used once.")
            return
        self._anchors.append({
            'px': self._pending[0], 'py': self._pending[1],
            'ra': c['ra_deg'], 'dec': c['dec_deg'], 'name': c['name'],
            'snapped': self._pending_snapped})
        self._pending = None
        self._pending_snapped = False
        self._combo.setText("")
        self._pending_lbl.setText(f"{c['name']} added.")
        self._refresh()

    def _match_typed_star(self):
        """Resolve free-typed text to a candidate star.

        Pressing Enter in an EditableComboBox appends the raw text as a new
        (data-less) item instead of selecting a match, so 'vega' + Add used
        to do nothing, silently. Accept the typed text when it names exactly
        one candidate (or matches one exactly), case-insensitive.
        """
        text = self._combo.text().strip().lower()
        if not text:
            return None
        hits = [c for c in self._candidates if text in c['name'].lower()]
        exact = [c for c in hits if c['name'].lower() == text]
        if exact:
            return exact[0]
        return hits[0] if len(hits) == 1 else None

    def _on_remove(self):
        i = self._list.currentRow()
        if 0 <= i < len(self._anchors):
            self._anchors.pop(i)
            self._refresh()

    def _on_solve(self):
        self.anchors = [(a['px'], a['py'], a['ra'], a['dec'], a['name'])
                        for a in self._anchors]
        self.accept()

    def _refresh(self):
        self._list.clear()
        for a in self._anchors:
            mark = "✓" if a.get('snapped') else "⚠ unsnapped"
            self._list.addItem(
                f"{a['name']}  @ ({a['px']:.0f}, {a['py']:.0f})  {mark}")
        markers = [(a['px'], a['py'], a['name']) for a in self._anchors]
        self._img.set_markers(markers, self._pending)
        n = len(self._anchors)
        self._solve_btn.setEnabled(n >= 4)
        self._solve_btn.setText(f"Solve ({n}/4)" if n < 4 else f"Solve ({n} stars)")
