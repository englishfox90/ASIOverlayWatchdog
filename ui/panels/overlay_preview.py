"""Overlay preview card plus the shared token catalogue and sample-value substitution."""
import math
import os
import random

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy
from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QPen, QPolygonF

from qfluentwidgets import CardWidget, SubtitleLabel

from ..theme.tokens import Colors, Spacing, Layout
from services.compass_overlay import (
    COMPASS_CIRCLE_R, COMPASS_CARDINAL_LEN, COMPASS_ORDINAL_LEN,
    COMPASS_HALF_BASE, COMPASS_INNER_R, COMPASS_LABEL_R,
)


TOKENS = [
    ("━━━ Camera ━━━", None),
    ("Camera", "{CAMERA}"),
    ("Exposure", "{EXPOSURE}"),
    ("Gain", "{GAIN}"),
    ("Temperature", "{TEMP}"),
    ("Temp (Celsius)", "{TEMP_C}"),
    ("Temp (Fahrenheit)", "{TEMP_F}"),
    ("Resolution", "{RES}"),
    ("Session", "{SESSION}"),
    ("Date & Time", "{DATETIME}"),
    ("Filename", "{FILENAME}"),
    ("━━━ Image Stats ━━━", None),
    ("Brightness/Mean", "{BRIGHTNESS}"),
    ("Median", "{MEDIAN}"),
    ("Min Pixel", "{MIN}"),
    ("Max Pixel", "{MAX}"),
    ("Std Deviation", "{STD_DEV}"),
    ("25th Percentile", "{P25}"),
    ("75th Percentile", "{P75}"),
    ("95th Percentile", "{P95}"),
    ("━━━ Weather ━━━", None),
    ("Weather Temp", "{WEATHER_TEMP}"),
    ("Feels Like", "{WEATHER_FEELS_LIKE}"),
    ("Condition", "{WEATHER_CONDITION}"),
    ("Description", "{WEATHER_DESC}"),
    ("Humidity", "{WEATHER_HUMIDITY}"),
    ("Pressure", "{WEATHER_PRESSURE}"),
    ("Wind Speed", "{WEATHER_WIND_SPEED}"),
    ("Wind Direction", "{WEATHER_WIND_DIR}"),
    ("Clouds", "{WEATHER_CLOUDS}"),
    ("Visibility", "{WEATHER_VISIBILITY}"),
    ("Sunrise", "{WEATHER_SUNRISE}"),
    ("Sunset", "{WEATHER_SUNSET}"),
    ("City", "{WEATHER_CITY}"),
    ("━━━ ML Models (Beta) ━━━", None),
    ("Roof Status", "{ROOF_STATUS}"),
    ("Sky Condition", "{SKY_CONDITION}"),
    ("Stars Visible", "{STARS_VISIBLE}"),
    ("Star Density", "{STAR_DENSITY}"),
    ("━━━ Star Detection ━━━", None),
    ("Star Count", "{STAR_COUNT}"),
    ("FWHM", "{FWHM}"),
    ("Seeing", "{SEEING}"),
]

ANCHOR_POSITIONS = [
    "Top-Left", "Top-Center", "Top-Right",
    "Bottom-Left", "Bottom-Center", "Bottom-Right",
]

COLOR_OPTIONS = [
    "white", "black", "lightgray", "darkgray",
    "red", "green", "blue", "cyan", "magenta",
    "yellow", "orange", "purple", "pink", "lime"
]


def _anchor_xy(anchor, offset_x, offset_y, width, height, elem_w, elem_h, margin=0):
    """Return top-left (x, y) for an element given anchor, offsets, and margin."""
    if 'Left' in anchor:
        x = margin + offset_x
    elif 'Right' in anchor:
        x = width - elem_w - margin - offset_x
    else:
        x = (width - elem_w) // 2 + offset_x

    if 'Top' in anchor:
        y = margin + offset_y
    elif 'Bottom' in anchor:
        y = height - elem_h - margin - offset_y
    else:
        y = (height - elem_h) // 2 + offset_y

    return x, y


def substitute_tokens(text: str) -> str:
    """Replace tokens with sample values for preview rendering."""
    result = text
    result = result.replace('{CAMERA}', 'ASI676MC')
    result = result.replace('{EXPOSURE}', '0.10s')
    result = result.replace('{GAIN}', '150')
    result = result.replace('{TEMP}', '25.0 C')
    result = result.replace('{TEMPERATURE}', '25.0 C')
    result = result.replace('{TEMP_C}', '25.0°C')
    result = result.replace('{TEMP_F}', '77.0°F')
    result = result.replace('{RES}', '1920x1080')
    result = result.replace('{SESSION}', '2026-01-01')
    result = result.replace('{DATETIME}', '2026-01-01 20:30:00')
    result = result.replace('{FILENAME}', 'capture_20260101_203000.png')
    result = result.replace('{BRIGHTNESS}', '128.5')
    result = result.replace('{MEAN}', '128.5')
    result = result.replace('{MEDIAN}', '120.0')
    result = result.replace('{MIN}', '0')
    result = result.replace('{MAX}', '255')
    result = result.replace('{STD_DEV}', '45.23')
    result = result.replace('{P25}', '85.0')
    result = result.replace('{P75}', '165.0')
    result = result.replace('{P95}', '240.0')
    result = result.replace('{WEATHER_TEMP}', '15°C')
    result = result.replace('{WEATHER_FEELS_LIKE}', '12°C')
    result = result.replace('{WEATHER_CONDITION}', 'Clear')
    result = result.replace('{WEATHER_DESC}', 'Clear sky')
    result = result.replace('{WEATHER_HUMIDITY}', '45%')
    result = result.replace('{WEATHER_PRESSURE}', '1013 hPa')
    result = result.replace('{WEATHER_WIND_SPEED}', '5 km/h')
    result = result.replace('{WEATHER_WIND_DIR}', 'NW')
    result = result.replace('{WEATHER_CLOUDS}', '10%')
    result = result.replace('{WEATHER_VISIBILITY}', '10 km')
    result = result.replace('{WEATHER_SUNRISE}', '06:45')
    result = result.replace('{WEATHER_SUNSET}', '18:30')
    result = result.replace('{WEATHER_CITY}', 'Rockwood')
    result = result.replace('{WEATHER_ICON_CODE}', '01d')
    result = result.replace('{ROOF_STATUS}', 'Open (95%)')
    result = result.replace('{SKY_CONDITION}', 'Clear (87%)')
    result = result.replace('{STARS_VISIBLE}', 'Yes')
    result = result.replace('{STAR_DENSITY}', 'High (0.85)')
    result = result.replace('{STAR_COUNT}', '1247')
    result = result.replace('{FWHM}', '3.2"')
    result = result.replace('{SEEING}', 'Good')
    return result


class OverlayPreviewCard(CardWidget):
    """Preview card with a starry sky backdrop and rendered overlay."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_overlay = None
        self._image_cache = {}
        self._background_pixmap = None
        self._background_size = (0, 0)
        self._setup_ui()
        self._update_preview()

    def _setup_ui(self):
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.card_padding, Spacing.card_padding,
                                  Spacing.card_padding, Spacing.card_padding)
        layout.setSpacing(Spacing.md)

        header = SubtitleLabel("Preview")
        header.setStyleSheet(f"color: {Colors.text_primary};")
        layout.addWidget(header)

        self.preview_container = QWidget()
        self.preview_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        container_layout = QVBoxLayout(self.preview_container)
        container_layout.setContentsMargins(0, 0, 0, 0)

        self.preview_label = QLabel()
        self.preview_label.setMinimumSize(200, 150)
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet(f"""
            background-color: {Colors.gray_9};
            border: 1px solid {Colors.border_subtle};
            border-radius: {Layout.radius_md}px;
        """)
        container_layout.addWidget(self.preview_label)

        layout.addWidget(self.preview_container, stretch=1)

    def set_overlay(self, overlay):
        self._current_overlay = overlay
        self._update_preview()

    def clear_image_cache(self, image_path=None):
        if image_path is None:
            self._image_cache.clear()
        elif image_path in self._image_cache:
            del self._image_cache[image_path]

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(100, self._update_preview)

    def _update_preview(self):
        label_w = max(self.preview_label.width(), 200)
        label_h = max(self.preview_label.height(), 150)

        if (label_w, label_h) != self._background_size:
            bg = QPixmap(label_w, label_h)
            bg.fill(QColor('#0a0e27'))
            painter = QPainter(bg)
            painter.setRenderHint(QPainter.Antialiasing)
            random.seed(42)
            for _ in range(80):
                x = random.randint(5, label_w - 5)
                y = random.randint(5, label_h - 5)
                brightness = random.randint(150, 255)
                size = random.randint(1, 3)
                painter.setPen(QPen(QColor(brightness, brightness, brightness)))
                painter.setBrush(QColor(brightness, brightness, brightness))
                painter.drawEllipse(x, y, size, size)
            painter.end()
            self._background_pixmap = bg
            self._background_size = (label_w, label_h)

        preview = QPixmap(self._background_pixmap)
        if self._current_overlay is not None:
            painter = QPainter(preview)
            painter.setRenderHint(QPainter.Antialiasing)
            self._render_overlay(painter, self._current_overlay, label_w, label_h)
            painter.end()

        self.preview_label.setPixmap(preview)

    def _render_overlay(self, painter: QPainter, overlay: dict, width: int, height: int):
        overlay_type = overlay.get('type', 'text')

        if overlay_type == 'image':
            self._render_image_overlay(painter, overlay, width, height)
        elif overlay_type == 'compass':
            self._render_compass_overlay(painter, overlay, width, height)
        else:
            self._render_text_overlay(painter, overlay, width, height)

    def _render_text_overlay(self, painter: QPainter, overlay: dict, width: int, height: int):
        text = overlay.get('text', '')
        anchor = overlay.get('anchor', 'Bottom-Left')
        offset_x = overlay.get('offset_x', 15)
        offset_y = overlay.get('offset_y', 15)
        font_size = overlay.get('font_size', 24)
        font_style = overlay.get('font_style', 'normal')
        color = overlay.get('color', 'white')
        bg_enabled = overlay.get('bg_enabled', False)
        bg_color = overlay.get('bg_color', 'transparent')
        alignment = overlay.get('alignment', 'left')

        sample_text = substitute_tokens(text)
        if not sample_text.strip():
            return

        scale = max(0.1, width / 800.0)
        scaled_font_size = max(8, int(font_size * scale))

        font = QFont()
        font.setPointSize(max(1, scaled_font_size))
        if font_style == 'bold':
            font.setBold(True)
        elif font_style == 'italic':
            font.setItalic(True)
        painter.setFont(font)

        metrics = painter.fontMetrics()
        lines = sample_text.split('\n')
        line_widths = [metrics.horizontalAdvance(line) for line in lines]
        text_width = max(line_widths) if line_widths else 0
        line_height = metrics.height()
        text_height = line_height * len(lines)

        scaled_offset_x = int(offset_x * scale)
        scaled_offset_y = int(offset_y * scale)
        margin = int(10 * scale)

        base_x, base_y = _anchor_xy(anchor, scaled_offset_x, scaled_offset_y,
                                     width, height, text_width, text_height, margin)
        y = base_y + line_height  # Qt draws text at baseline, not top-left

        if bg_enabled and bg_color != 'transparent':
            bg_qcolor = QColor(bg_color)
            bg_qcolor.setAlpha(180)
            padding = int(5 * scale)
            painter.fillRect(
                int(base_x - padding), int(y - line_height - padding//2),
                int(text_width + padding*2), int(text_height + padding),
                bg_qcolor
            )

        painter.setPen(QColor(color))
        for i, line in enumerate(lines):
            line_width = line_widths[i]
            if alignment == 'center':
                line_x = base_x + (text_width - line_width) // 2
            elif alignment == 'right':
                line_x = base_x + (text_width - line_width)
            else:
                line_x = base_x
            painter.drawText(int(line_x), int(y + i * line_height), line)

    def _render_compass_overlay(self, painter: QPainter, overlay: dict, width: int, height: int):
        rotation = overlay.get('rotation', 0)
        mirror = overlay.get('mirror', False)
        size = overlay.get('size', 80)
        anchor = overlay.get('anchor', 'Bottom-Right')
        offset_x = overlay.get('offset_x', 20)
        offset_y = overlay.get('offset_y', 20)

        scale = min(width, height) / 1000.0
        scaled_size = max(20, int(size * scale * 2))
        radius = scaled_size // 2

        cx, cy = self._anchor_to_xy(anchor, offset_x, offset_y, width, height, scaled_size, scaled_size)
        cx += radius
        cy += radius

        rot_rad = math.radians(rotation)
        flip = -1 if mirror else 1
        painter.setRenderHint(QPainter.Antialiasing, True)

        col_light = QColor(255, 255, 255, 200)
        col_dark = QColor(85, 85, 85, 200)
        col_outline = QColor(255, 255, 255, 230)

        circle_r = radius * COMPASS_CIRCLE_R
        painter.setPen(QPen(col_outline, max(1, scaled_size // 50)))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), circle_r, circle_r)

        cardinal_len = radius * COMPASS_CARDINAL_LEN
        ordinal_len = radius * COMPASS_ORDINAL_LEN
        half_base = radius * COMPASS_HALF_BASE

        for i, angle_deg in enumerate(range(0, 360, 45)):
            is_cardinal = (i % 2 == 0)
            tip_r = cardinal_len if is_cardinal else ordinal_len
            angle = rot_rad + flip * math.radians(angle_deg)

            tip_x = cx + tip_r * math.sin(angle)
            tip_y = cy - tip_r * math.cos(angle)

            perp = angle + math.pi / 2
            bx1 = cx + half_base * math.sin(perp)
            by1 = cy - half_base * math.cos(perp)
            bx2 = cx - half_base * math.sin(perp)
            by2 = cy + half_base * math.cos(perp)

            painter.setPen(QPen(col_outline, 1))
            painter.setBrush(col_light)
            painter.drawPolygon(QPolygonF([
                QPointF(cx, cy), QPointF(bx1, by1), QPointF(tip_x, tip_y)
            ]))
            painter.setBrush(col_dark)
            painter.drawPolygon(QPolygonF([
                QPointF(cx, cy), QPointF(tip_x, tip_y), QPointF(bx2, by2)
            ]))

        inner_r = radius * COMPASS_INNER_R
        painter.setBrush(col_light)
        painter.setPen(QPen(col_outline, 1))
        painter.drawEllipse(QPointF(cx, cy), inner_r, inner_r)

        font = painter.font()
        font.setPixelSize(max(8, scaled_size // 6))
        painter.setFont(font)
        fm = painter.fontMetrics()

        for label_text, angle_deg in [('N', 0), ('E', 90), ('S', 180), ('W', 270)]:
            angle = rot_rad + flip * math.radians(angle_deg)
            label_r = radius * COMPASS_LABEL_R
            lx = cx + label_r * math.sin(angle)
            ly = cy - label_r * math.cos(angle)

            tw = fm.horizontalAdvance(label_text)
            th = fm.height()
            tx = int(lx - tw / 2)
            ty = int(ly + th / 4)

            painter.setPen(QColor(0, 0, 0, 180))
            for dx, dy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
                painter.drawText(tx + dx, ty + dy, label_text)
            painter.setPen(QColor(255, 255, 255, 255))
            painter.drawText(tx, ty, label_text)

    def _anchor_to_xy(self, anchor, offset_x, offset_y, width, height, elem_w, elem_h):
        anchor_lower = anchor.lower().replace('-', ' ').replace('_', ' ')
        if 'top' in anchor_lower:
            y = offset_y
        elif 'bottom' in anchor_lower:
            y = height - elem_h - offset_y
        else:
            y = (height - elem_h) // 2

        if 'left' in anchor_lower:
            x = offset_x
        elif 'right' in anchor_lower:
            x = width - elem_w - offset_x
        else:
            x = (width - elem_w) // 2

        return x, y

    def _render_image_overlay(self, painter: QPainter, overlay: dict, width: int, height: int):
        image_path = overlay.get('image_path', '')
        if not image_path or not os.path.exists(image_path):
            return

        anchor = overlay.get('anchor', 'Bottom-Right')
        offset_x = overlay.get('offset_x', 15)
        offset_y = overlay.get('offset_y', 15)
        img_width = overlay.get('width', 100)
        img_height = overlay.get('height', 100)
        opacity = overlay.get('opacity', 100) / 100.0

        if image_path not in self._image_cache:
            pixmap = QPixmap(image_path)
            if pixmap.isNull():
                return
            self._image_cache[image_path] = pixmap
        else:
            pixmap = self._image_cache[image_path]

        scale = width / 800.0
        scaled_w = max(10, int(img_width * scale))
        scaled_h = max(10, int(img_height * scale))
        scaled_offset_x = int(offset_x * scale)
        scaled_offset_y = int(offset_y * scale)
        margin = int(10 * scale)

        scaled_pixmap = pixmap.scaled(scaled_w, scaled_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        actual_w = scaled_pixmap.width()
        actual_h = scaled_pixmap.height()

        x, y = _anchor_xy(anchor, scaled_offset_x, scaled_offset_y,
                           width, height, actual_w, actual_h, margin)

        old_opacity = painter.opacity()
        painter.setOpacity(opacity)
        painter.drawPixmap(int(x), int(y), scaled_pixmap)
        painter.setOpacity(old_opacity)
