"""
Compass rose overlay for astrophotography images.

Renders an 8-point star compass rose with cardinal (N/S/E/W) and
ordinal (NE/SE/SW/NW) points, configurable rotation and position.
"""
import math
from PIL import Image, ImageDraw, ImageFont


# Default compass settings
DEFAULT_SIZE = 80
DEFAULT_COLOR = (255, 255, 255, 200)
DEFAULT_LABEL_COLOR = (255, 255, 255, 255)

# Geometry ratios (fraction of radius). Shared with the Qt preview renderer
# in ui/panels/overlay_preview.py — change both or neither.
COMPASS_CIRCLE_R = 0.72
COMPASS_CARDINAL_LEN = 0.68
COMPASS_ORDINAL_LEN = 0.45
COMPASS_HALF_BASE = 0.12
COMPASS_INNER_R = 0.07
COMPASS_LABEL_R = 0.88

# Resolved label fonts, keyed by pixel size.
#
# Resolving inside draw_compass meant a filesystem font lookup on every frame
# of a 24/7 capture loop, and — worse — a *transient* truetype failure could
# resolve one frame to arial and the next to the default bitmap font, so the
# labels visibly changed size and position between frames. Cache the outcome so
# every frame in a session renders identically.
_FONT_CACHE = {}


def _label_font(px):
    """Return the cached label font for `px`, resolving it on first use.

    Returns None only if no font could be loaded at all, in which case the
    caller skips the labels rather than failing the frame — an unattended
    capture must not stop over a missing font.
    """
    if px in _FONT_CACHE:
        return _FONT_CACHE[px]

    font = None
    for name in ('arial.ttf', 'Arial.ttf', 'DejaVuSans.ttf'):
        try:
            font = ImageFont.truetype(name, px)
            break
        except (OSError, IOError):
            continue
    if font is None:
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

    _FONT_CACHE[px] = font
    return font


def draw_compass(image, rotation=0, position='bottom-right',
                 size=DEFAULT_SIZE, color=DEFAULT_COLOR,
                 label_color=DEFAULT_LABEL_COLOR, margin=20,
                 cx=None, cy=None, mirror=False):
    """Draw an 8-point star compass rose on an image.

    Args:
        image: PIL Image (RGBA or RGB — will be converted to RGBA)
        rotation: Rotation angle in degrees (0 = North is up)
        position: One of 'center', 'top-left', 'top-right',
                  'bottom-left', 'bottom-right' (ignored if cx/cy given)
        size: Compass diameter in pixels
        color: RGBA tuple for compass lines/fill
        label_color: RGBA tuple for N/S/E/W labels
        margin: Pixel margin from image edge (ignored if cx/cy given)
        cx: Optional explicit center X coordinate
        cy: Optional explicit center Y coordinate
        mirror: Mirror the rose left-right so E and W swap sides. Needed when
                the camera's view of the sky is handed the other way round
                (mirror-flipped optics, or a lens looking "down" on the sky),
                which rotation alone cannot correct.

    Returns:
        Modified PIL Image (RGBA)
    """
    if image.mode != 'RGBA':
        image = image.convert('RGBA')

    img_w, img_h = image.size

    # Calculate center position
    if cx is not None and cy is not None:
        pass
    else:
        if img_w < size + margin * 2 or img_h < size + margin * 2:
            return image
        cx, cy = _get_center(img_w, img_h, size, position, margin)

    radius = size // 2

    # Create overlay for compositing
    overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    rot_rad = math.radians(rotation)
    # Mirroring negates the bearing while leaving `rotation` a clockwise
    # screen rotation, so the rotation control still behaves the same way.
    flip = -1 if mirror else 1

    # Derive colors from the base color
    fill_light = color
    fill_dark = (color[0] // 3, color[1] // 3, color[2] // 3, color[3])
    outline = (*color[:3], min(255, color[3] + 30))

    # --- Outer circle ---
    circle_r = radius * COMPASS_CIRCLE_R
    draw.ellipse(
        [cx - circle_r, cy - circle_r, cx + circle_r, cy + circle_r],
        outline=outline, width=max(1, size // 50)
    )

    # --- 8-point star ---
    cardinal_len = radius * COMPASS_CARDINAL_LEN
    ordinal_len = radius * COMPASS_ORDINAL_LEN
    half_base = radius * COMPASS_HALF_BASE

    for i, angle_deg in enumerate(range(0, 360, 45)):
        is_cardinal = (i % 2 == 0)
        tip_r = cardinal_len if is_cardinal else ordinal_len
        angle = rot_rad + flip * math.radians(angle_deg)

        # Tip of this point
        tip_x = cx + tip_r * math.sin(angle)
        tip_y = cy - tip_r * math.cos(angle)

        # Two base vertices (perpendicular to the point direction)
        perp = angle + math.pi / 2
        base_x1 = cx + half_base * math.sin(perp)
        base_y1 = cy - half_base * math.cos(perp)
        base_x2 = cx - half_base * math.sin(perp)
        base_y2 = cy + half_base * math.cos(perp)

        # Each point is split into two triangles (light/dark halves)
        # Left half
        draw.polygon(
            [(cx, cy), (base_x1, base_y1), (tip_x, tip_y)],
            fill=fill_light, outline=outline
        )
        # Right half (darker)
        draw.polygon(
            [(cx, cy), (tip_x, tip_y), (base_x2, base_y2)],
            fill=fill_dark, outline=outline
        )

    # --- Inner circle (center dot) ---
    inner_r = radius * COMPASS_INNER_R
    draw.ellipse(
        [cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r],
        fill=fill_light, outline=outline
    )

    # --- Cardinal labels (N, E, S, W) ---
    font = _label_font(max(10, size // 6))
    if font is None:
        return Image.alpha_composite(image, overlay)

    for label_text, angle_deg in [('N', 0), ('E', 90), ('S', 180), ('W', 270)]:
        angle = rot_rad + flip * math.radians(angle_deg)
        label_r = radius * COMPASS_LABEL_R
        lx = cx + label_r * math.sin(angle)
        ly = cy - label_r * math.cos(angle)

        bbox = draw.textbbox((0, 0), label_text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

        # Draw text with dark outline for readability on any background
        ox, oy = lx - tw / 2, ly - th / 2
        shadow = (0, 0, 0, min(200, color[3]))
        for dx, dy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
            draw.text((ox + dx, oy + dy), label_text, fill=shadow, font=font)
        draw.text((ox, oy), label_text, fill=label_color, font=font)

    # Composite onto original
    image = Image.alpha_composite(image, overlay)
    return image


def _get_center(img_w, img_h, size, position, margin):
    """Calculate compass center coordinates for the given position."""
    radius = size // 2
    positions = {
        'center': (img_w // 2, img_h // 2),
        'top-left': (margin + radius, margin + radius),
        'top-right': (img_w - margin - radius, margin + radius),
        'bottom-left': (margin + radius, img_h - margin - radius),
        'bottom-right': (img_w - margin - radius, img_h - margin - radius),
    }
    return positions.get(position, positions['bottom-right'])
