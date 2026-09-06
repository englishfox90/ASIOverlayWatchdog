"""Overlay rendering — text, image, and compass overlays."""
import os
import re
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from .logger import app_logger


def is_safe_path(path: str) -> bool:
    """
    Check if path is safe (no directory traversal attacks).
    SEC-003 fix: Prevents loading files from unintended directories.

    Args:
        path: File path to validate

    Returns:
        True if path is safe, False if potentially malicious
    """
    if not path:
        return False

    if path == 'WEATHER_ICON':
        return True

    normalized = os.path.normpath(path)

    if '..' in normalized:
        return False

    return True


def replace_tokens(text, metadata):
    """Replace tokens like {EXPOSURE}, {GAIN} with actual values."""
    formatted_metadata = metadata.copy()

    if 'EXPOSURE' in formatted_metadata:
        exp_str = str(formatted_metadata['EXPOSURE'])
        if exp_str.endswith('s'):
            try:
                exp_value = float(exp_str[:-1])
                formatted_metadata['EXPOSURE'] = f"{exp_value:.2f}s"
            except ValueError:
                pass

    result = text

    tokens = re.findall(r'\{([^}]+)\}', text)

    for token in tokens:
        token_upper = token.upper()
        value = formatted_metadata.get(token_upper, '?')
        result = result.replace(f'{{{token}}}', str(value))

    return result


def get_text_bbox(draw, text, font):
    """Get bounding box of text."""
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    return width, height


def calculate_position(image_size, text_size, anchor, x_offset, y_offset):
    """Calculate text position based on anchor point and offsets."""
    img_width, img_height = image_size
    text_width, text_height = text_size

    anchors = {
        "Top-Left": (x_offset, y_offset),
        "Top-Right": (img_width - text_width - x_offset, y_offset),
        "Bottom-Left": (x_offset, img_height - text_height - y_offset),
        "Bottom-Right": (img_width - text_width - x_offset, img_height - text_height - y_offset),
        "Center": ((img_width - text_width) // 2 + x_offset, (img_height - text_height) // 2 + y_offset)
    }

    return anchors.get(anchor, (x_offset, y_offset))


def parse_color(color_str):
    """
    Parse color string to RGB tuple.
    Supports: 'white', 'black', 'red', 'green', 'blue', or '#RRGGBB'
    """
    color_map = {
        'white': (255, 255, 255),
        'black': (0, 0, 0),
        'red': (255, 0, 0),
        'green': (0, 255, 0),
        'blue': (0, 0, 255),
        'yellow': (255, 255, 0),
        'cyan': (0, 255, 255),
        'magenta': (255, 0, 255)
    }

    color_lower = color_str.lower()

    if color_lower in color_map:
        return color_map[color_lower]

    if color_str.startswith('#') and len(color_str) == 7:
        try:
            r = int(color_str[1:3], 16)
            g = int(color_str[3:5], 16)
            b = int(color_str[5:7], 16)
            return (r, g, b)
        except (ValueError, IndexError):
            pass

    return (255, 255, 255)


def add_overlays(image_input, overlays, metadata, image_cache=None, weather_service=None):
    """
    Add text and image overlays to an image.

    Args:
        image_input: Either a file path (str) or PIL Image object
        overlays: List of overlay configurations
        metadata: Metadata dictionary
        image_cache: Optional dict to cache loaded overlay images
        weather_service: Optional WeatherService instance for weather tokens

    Returns the modified PIL Image object.
    """
    try:
        if weather_service and weather_service.is_configured():
            try:
                weather_tokens = weather_service.get_weather_tokens()
                if weather_tokens:
                    metadata.update(weather_tokens)
            except Exception as e:
                app_logger.warning(f"Failed to fetch weather data: {e}")

        if isinstance(image_input, str):
            img = Image.open(image_input)
        else:
            img = image_input

        if img.mode in ('P',):
            img = img.convert('RGB')

        if img.mode != 'RGBA':
            img = img.convert('RGBA')

        for overlay in overlays:
            overlay_type = overlay.get('type', 'text')

            if overlay_type == 'image':
                img = add_image_overlay(img, overlay, image_cache, weather_service)
            elif overlay_type == 'compass':
                img = _add_compass_overlay(img, overlay)
            else:
                img = add_text_overlay(img, overlay, metadata)

        if img.mode == 'RGBA':
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[3] if img.mode == 'RGBA' else None)
            img = rgb_img

        return img

    except Exception as e:
        error_msg = f"Error adding overlays: {e}"
        app_logger.error(error_msg)
        raise RuntimeError(error_msg)


def _add_compass_overlay(img, overlay):
    try:
        from .compass_overlay import draw_compass

        size = overlay.get('size', 80)
        rotation = overlay.get('rotation', 0)
        mirror = overlay.get('mirror', False)
        anchor = overlay.get('anchor', 'Bottom-Right')
        offset_x = overlay.get('offset_x', 20)
        offset_y = overlay.get('offset_y', 20)

        x, y = calculate_position(img.size, (size, size), anchor, offset_x, offset_y)
        cx = x + size // 2
        cy = y + size // 2

        img = draw_compass(img, rotation=rotation, size=size, cx=cx, cy=cy,
                           mirror=mirror)
    except Exception as e:
        app_logger.debug(f"Compass overlay skipped: {e}")
    return img


_OVERLAY_CACHE_MAX_PATHS = 6
_OVERLAY_CACHE_MAX_SIZES = 3


def _file_stamp(path):
    """(mtime_ns, size) used to notice the user replacing an overlay file."""
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _fit_size(src_size, width, height, maintain_aspect):
    """Resolve the requested overlay size against the source dimensions."""
    src_w, src_h = src_size
    target_w = int(width) if width else src_w
    target_h = int(height) if height else src_h

    if maintain_aspect and (target_w != src_w or target_h != src_h):
        aspect = src_w / src_h
        if target_w / target_h > aspect:
            target_w = int(target_h * aspect)
        else:
            target_h = int(target_w / aspect)

    return max(1, target_w), max(1, target_h)


def _cached_overlay_image(image_path, overlay, image_cache):
    """Return the overlay image at its rendered size, reusing image_cache.

    Decoding is the expensive part — a 3000 px RGBA logo costs ~150 ms and
    ~37 MB per frame — and the LANCZOS resize down to overlay size repeats
    identically on every frame, so the RESIZED result is what we keep; the
    full-res source is never held, only its dimensions. An entry is dropped
    when the file's mtime/size changes (the overlay settings panel lets the
    user replace a file in place) and both the path count and the per-path
    size variants are capped, so cycling through files can't grow the dict.

    The returned image may be the cached object — callers must not mutate it.
    """
    stamp = _file_stamp(image_path)
    entry = image_cache.get(image_path) if image_cache is not None else None
    if entry is not None and entry['stamp'] != stamp:
        entry = None
        image_cache.pop(image_path, None)

    if entry is not None:
        size = _fit_size(entry['src_size'], overlay.get('width'),
                         overlay.get('height'), overlay.get('maintain_aspect', True))
        cached = entry['resized'].get(size)
        if cached is not None:
            return cached

    app_logger.debug(f"Loading image overlay from: {image_path}")
    with Image.open(image_path) as src:
        src.load()
        src_size = src.size
        size = _fit_size(src_size, overlay.get('width'), overlay.get('height'),
                         overlay.get('maintain_aspect', True))
        img = src.copy() if size == src_size else src.resize(size, Image.Resampling.LANCZOS)
    app_logger.debug(f"Loaded image: {src_size}, mode: {img.mode}")

    if image_cache is not None:
        if entry is None:
            if len(image_cache) >= _OVERLAY_CACHE_MAX_PATHS:
                image_cache.pop(next(iter(image_cache)), None)
            entry = {'stamp': stamp, 'src_size': src_size, 'resized': {}}
            image_cache[image_path] = entry
        if len(entry['resized']) >= _OVERLAY_CACHE_MAX_SIZES:
            entry['resized'].pop(next(iter(entry['resized'])))
        entry['resized'][size] = img

    return img


def add_image_overlay(base_img, overlay, image_cache=None, weather_service=None):
    """
    Add an image overlay to the base image.

    Args:
        base_img: Base PIL Image
        overlay: Overlay configuration dict
        image_cache: Optional dict to cache loaded images
        weather_service: Optional WeatherService for dynamic weather icons

    Returns:
        Modified PIL Image
    """
    try:
        image_path = overlay.get('image_path', '')
        if not image_path:
            app_logger.warning(f"Image overlay has no image_path: {overlay}")
            return base_img

        # SEC-003: Validate path before loading (prevent directory traversal)
        if not is_safe_path(image_path):
            app_logger.warning(f"Blocked potentially unsafe image overlay path: {image_path}")
            return base_img

        if image_path == 'WEATHER_ICON':
            if weather_service and weather_service.is_configured():
                actual_path = weather_service.get_weather_icon_path()
                if actual_path and os.path.exists(actual_path):
                    app_logger.debug(f"Resolved WEATHER_ICON to: {actual_path}")
                    image_path = actual_path
                else:
                    app_logger.warning("Weather icon not available - path not returned or doesn't exist")
                    return base_img
            else:
                app_logger.debug("Weather service not configured for WEATHER_ICON")
                return base_img

        if not os.path.exists(image_path):
            app_logger.warning(f"Image overlay path does not exist: {image_path}")
            return base_img

        overlay_img = _cached_overlay_image(image_path, overlay, image_cache)
        target_width, target_height = overlay_img.size

        opacity = overlay.get('opacity', 100)
        if overlay_img.mode != 'RGBA':
            overlay_img = overlay_img.convert('RGBA')  # convert() already returns a new image
        elif opacity < 100:
            overlay_img = overlay_img.copy()  # putalpha below must not touch the cached object

        if opacity < 100:
            alpha = overlay_img.split()[3].point(lambda p: int(p * opacity / 100))
            overlay_img.putalpha(alpha)

        anchor = overlay.get('anchor', 'Bottom-Right')
        x_offset = overlay.get('offset_x', 10)
        y_offset = overlay.get('offset_y', 10)

        x, y = calculate_position(base_img.size, (target_width, target_height),
                                 anchor, x_offset, y_offset)

        base_img.paste(overlay_img, (x, y), overlay_img)

        return base_img

    except Exception as e:
        app_logger.error(f"Error adding image overlay: {e}")
        return base_img


def add_text_overlay(img, overlay, metadata):
    """
    Add a text overlay to the image.

    Args:
        img: PIL Image
        overlay: Overlay configuration dict
        metadata: Metadata dictionary

    Returns:
        Modified PIL Image
    """
    try:
        draw = ImageDraw.Draw(img)
        datetime_format = overlay.get('datetime_format', '%Y-%m-%d %H:%M:%S')

        overlay_metadata = metadata.copy()
        if '{DATETIME}' in overlay.get('text', '').upper():
            overlay_metadata['DATETIME'] = datetime.now().strftime(datetime_format)

        text = replace_tokens(overlay.get('text', ''), overlay_metadata)

        font_size = overlay.get('font_size', 28)
        color = parse_color(overlay.get('color', 'white'))
        anchor = overlay.get('anchor', 'Bottom-Left')
        x_offset = overlay.get('offset_x', 10)
        y_offset = overlay.get('offset_y', 10)
        background_enabled = overlay.get('background_enabled', False)
        background_color = overlay.get('background_color', 'black')
        alignment = overlay.get('alignment', 'left')

        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except (OSError, IOError):
            try:
                font = ImageFont.truetype("Arial.ttf", font_size)
            except (OSError, IOError):
                font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        x, y = calculate_position(img.size, (text_width, text_height), anchor, x_offset, y_offset)

        lines = text.split('\n')
        line_positions = []

        for line in lines:
            line_bbox = draw.textbbox((0, 0), line, font=font)
            line_width = line_bbox[2] - line_bbox[0]

            if alignment == 'center':
                line_x = x + (text_width - line_width) // 2
            elif alignment == 'right':
                line_x = x + (text_width - line_width)
            else:
                line_x = x

            line_positions.append(line_x)

        if background_enabled and background_color.lower() != 'transparent':
            padding = 5
            text_bbox = draw.textbbox((x, y), text, font=font)
            box_coords = [
                text_bbox[0] - padding,
                text_bbox[1] - padding,
                text_bbox[2] + padding,
                text_bbox[3] + padding
            ]
            bg_color = parse_color(background_color)
            draw.rectangle(box_coords, fill=bg_color)

        if len(lines) == 1:
            draw.text((line_positions[0], y), text, fill=color, font=font)
        else:
            line_height = draw.textbbox((0, 0), 'Ay', font=font)[3]
            current_y = y
            for i, line in enumerate(lines):
                draw.text((line_positions[i], current_y), line, fill=color, font=font)
                current_y += line_height

        return img

    except Exception as e:
        app_logger.error(f"Error adding text overlay: {e}")
        return img
