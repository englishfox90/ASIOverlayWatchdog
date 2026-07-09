"""
Live preview widget for the monitoring panel.

Shows the latest frame letterboxed to the card, with a message overlay for the
no-camera / stale-frame states and cursor-anchored scroll-to-zoom. All state
here is view-only (zoom, pan, focus) — no business logic or I/O.
"""
from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QSizePolicy
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QImage

from PIL import Image

from ..theme.tokens import Colors, Typography, Spacing, Layout
from ..theme.icons import qicon


class PreviewWidget(QFrame):
    """Image preview widget with metadata overlay and scroll-to-zoom."""

    _MAX_ZOOM = 8.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = None
        self._metadata = {}
        self._overlay_key = None
        # View state for scroll-to-zoom. _focus is the normalized image point
        # ([0,1] each axis) held at the centre of the viewport; _geom caches the
        # last render mapping so wheel/drag events can convert widget → image
        # coordinates. All view state, no business logic.
        self._zoom = 1.0
        self._focus = [0.5, 0.5]
        self._geom = None
        self._panning = False
        self._pan_last = None
        self._setup_ui()

    def _setup_ui(self):
        self.setMinimumSize(200, 150)
        # Allow flexible sizing - image will scale to fit
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Scope to the class — a bare `QFrame` selector also tints child QLabels
        # (QLabel subclasses QFrame), which put a box behind the overlay icon.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            PreviewWidget {{
                background-color: {Colors.bg_input};
                border: none;
                border-radius: {Layout.radius_md}px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Image label (centered). Starts empty — the message overlay below owns
        # all "no camera / no image" messaging, so a placeholder here would just
        # show through behind the translucent overlay as duplicate text.
        self.image_label = QLabel("")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet(f"""
            color: {Colors.text_muted};
            font-size: {Typography.size_body}px;
        """)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.image_label)

        # Message overlay (no-camera / stale "last frame") drawn over the image.
        # The bg is scoped to the frame's objectName so it doesn't tint the
        # child labels/icon (a selector-less rule propagates to children).
        self._overlay = QFrame(self)
        self._overlay.setObjectName("previewOverlay")
        self._overlay.setAttribute(Qt.WA_StyledBackground, True)
        self._overlay.setStyleSheet(
            "#previewOverlay { background-color: rgba(6, 8, 11, 0.55); }"
        )
        ov = QVBoxLayout(self._overlay)
        ov.setAlignment(Qt.AlignCenter)
        ov.setSpacing(Spacing.md)
        self._overlay_icon = QLabel()
        self._overlay_icon.setAlignment(Qt.AlignCenter)
        self._overlay_title = QLabel()
        self._overlay_title.setAlignment(Qt.AlignCenter)
        self._overlay_title.setStyleSheet(
            f"color: {Colors.text_primary}; font-size: {Typography.size_title}px; "
            f"font-weight: 600; background: transparent;"
        )
        self._overlay_sub = QLabel()
        self._overlay_sub.setAlignment(Qt.AlignCenter)
        self._overlay_sub.setWordWrap(True)
        # Fixed width gives the wrapped label a stable box so it isn't shrunk to
        # its content width (which clipped the text under the centered layout).
        self._overlay_sub.setFixedWidth(440)
        self._overlay_sub.setStyleSheet(
            f"color: {Colors.text_muted}; font-size: {Typography.size_body}px; "
            f"background: transparent;"
        )
        ov.addWidget(self._overlay_icon, 0, Qt.AlignCenter)
        ov.addWidget(self._overlay_title)
        ov.addWidget(self._overlay_sub, 0, Qt.AlignCenter)
        self._overlay.hide()

    def show_overlay(self, icon_name: str, title: str, subtitle: str = ""):
        """Cover the preview with a centered message (no-camera / stale frame)."""
        key = (icon_name, title, subtitle)
        if key == self._overlay_key and self._overlay.isVisible():
            return
        self._overlay_key = key
        self._overlay_icon.setPixmap(qicon(icon_name, Colors.text_muted).pixmap(QSize(64, 64)))
        self._overlay_title.setText(title)
        self._overlay_sub.setText(subtitle)
        self._overlay.setGeometry(0, 0, self.width(), self.height())
        self._overlay.raise_()
        self._overlay.show()

    def clear_overlay(self):
        if self._overlay.isVisible():
            self._overlay.hide()
        self._overlay_key = None

    def update_image(self, pil_image: Image.Image, metadata: dict = None):
        """Update preview with new image"""
        try:
            if pil_image.mode != 'RGB':
                pil_image = pil_image.convert('RGB')
            # Cap at 1920px — no need to keep a full 3552×3552 pixmap for a preview widget
            w, h = pil_image.size
            if max(w, h) > 1920:
                scale = 1920 / max(w, h)
                pil_image = pil_image.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
            data = pil_image.tobytes('raw', 'RGB')
            qimg = QImage(data, pil_image.width, pil_image.height,
                         pil_image.width * 3, QImage.Format_RGB888)
            self._pixmap = QPixmap.fromImage(qimg)
            self._metadata = metadata or {}
            self._update_display()
            self.clear_overlay()  # a fresh frame supersedes any message overlay
        except Exception as e:
            self.image_label.setText(f"Error: {e}")

    def _zoomed_size(self, lw: int, lh: int) -> tuple:
        """Full displayed image size (px) at the current zoom for a viewport."""
        pw, ph = self._pixmap.width(), self._pixmap.height()
        if pw <= 0 or ph <= 0:
            return 1, 1
        scale = min(lw / pw, lh / ph)  # fit (letterbox) scale at zoom 1
        return max(1, int(pw * scale * self._zoom)), max(1, int(ph * scale * self._zoom))

    def _update_display(self):
        """Render the image at the current zoom/pan, letterboxed to the widget."""
        if not self._pixmap:
            return
        lw, lh = self.image_label.width(), self.image_label.height()
        if lw <= 0 or lh <= 0:
            return

        zw, zh = self._zoomed_size(lw, lh)
        big = self._pixmap.scaled(zw, zh, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        # Viewport = intersection of the zoomed image with the widget. Below the
        # fit size on an axis it letterboxes; above it, we crop a window centred
        # on the focus point.
        vw, vh = min(zw, lw), min(zh, lh)
        cx, cy = self._focus[0] * zw, self._focus[1] * zh
        x0 = int(min(max(cx - vw / 2, 0), zw - vw))
        y0 = int(min(max(cy - vh / 2, 0), zh - vh))
        self.image_label.setPixmap(big.copy(x0, y0, vw, vh))

        offx, offy = (lw - vw) / 2, (lh - vh) / 2
        self._geom = (zw, zh, vw, vh, x0, y0, offx, offy)

    def _image_coord_at(self, px: float, py: float) -> tuple:
        """Map a widget point to a normalized image coordinate under the view."""
        if not self._geom:
            return None, None
        zw, zh, vw, vh, x0, y0, offx, offy = self._geom
        rx = min(max(px - offx, 0), vw)
        ry = min(max(py - offy, 0), vh)
        return (x0 + rx) / zw, (y0 + ry) / zh

    def _anchor_focus(self, nx: float, ny: float, px: float, py: float):
        """Set _focus so image point (nx, ny) stays under widget point (px, py)."""
        lw, lh = self.image_label.width(), self.image_label.height()
        zw, zh = self._zoomed_size(lw, lh)
        vw, vh = min(zw, lw), min(zh, lh)
        offx, offy = (lw - vw) / 2, (lh - vh) / 2
        x0 = nx * zw - (px - offx)
        y0 = ny * zh - (py - offy)
        self._focus = [
            min(max((x0 + vw / 2) / zw, 0.0), 1.0),
            min(max((y0 + vh / 2) / zh, 0.0), 1.0),
        ]

    def wheelEvent(self, event):
        """Scroll to zoom, anchored on the cursor. Double-click resets."""
        if not self._pixmap:
            super().wheelEvent(event)
            return
        pos = event.position()
        nx, ny = self._image_coord_at(pos.x(), pos.y())
        steps = event.angleDelta().y() / 120.0
        new_zoom = min(self._MAX_ZOOM, max(1.0, self._zoom * (1.25 ** steps)))
        if abs(new_zoom - self._zoom) < 1e-6:
            super().wheelEvent(event)  # at a limit — let the page scroll
            return
        self._zoom = new_zoom
        if new_zoom <= 1.0 + 1e-6:
            self._focus = [0.5, 0.5]
        elif nx is not None:
            self._anchor_focus(nx, ny, pos.x(), pos.y())
        self._update_display()
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._zoom > 1.0:
            self._panning = True
            self._pan_last = event.position()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._geom:
            zw, zh = self._geom[0], self._geom[1]
            d = event.position() - self._pan_last
            self._pan_last = event.position()
            self._focus[0] = min(max(self._focus[0] - d.x() / zw, 0.0), 1.0)
            self._focus[1] = min(max(self._focus[1] - d.y() / zh, 0.0), 1.0)
            self._update_display()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._panning and event.button() == Qt.LeftButton:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self._zoom = 1.0
        self._focus = [0.5, 0.5]
        self._update_display()
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_display()
        # Always track the preview size so the overlay is correctly sized the
        # moment it's shown (not just while already visible).
        self._overlay.setGeometry(0, 0, self.width(), self.height())
