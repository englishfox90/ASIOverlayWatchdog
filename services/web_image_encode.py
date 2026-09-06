"""Encode a processed frame for the HTTP image endpoint.

Separate from ``web_output`` on purpose: this is pure image work (no sockets,
no server state, no config lookups) so it is cheap to unit-test and can be
shared by every push site — the GUI dispatcher and the headless runner.

Why it exists: the web copy is consumed by a NINA dock panel and a polling
agent, neither of which can use more than a couple of megapixels. Encoding the
full 12.6 MP frame as an *optimized* PNG cost ~1.4 s per frame and produced a
15 MB blob that the server then had to decode, LANCZOS-resize and re-encode as
JPEG anyway. Resizing first and encoding once is ~20x cheaper for a visually
identical result.
"""

import io

from PIL import Image

from .logger import app_logger

# Maximum image size served by the web endpoint (5 MB).
WEB_IMAGE_MAX_BYTES = 5 * 1024 * 1024

# Longest-edge cap for the web copy. 2048 px comfortably exceeds what either
# HTTP consumer displays (a NINA dock panel and a monitoring agent) while
# keeping a quality-90 JPEG far under WEB_IMAGE_MAX_BYTES, so the server-side
# downsize safety net never has to fire in the normal path.
WEB_IMAGE_MAX_DIM = 2048

# Quality used whenever this module has to re-encode as JPEG itself (a resized
# frame, or a fallback shrink). High enough to be visually lossless at these
# dimensions; the user's own jpg_quality still applies to frames served at
# native size.
WEB_JPEG_QUALITY = 90

# Bounded so a pathological frame can't spin here; the caller keeps serving the
# previous image if the result is still over the cap.
_SHRINK_ATTEMPTS = 5


def _scaled_size(size, max_dim):
    """Target size that fits ``max_dim`` on the longest edge, or None."""
    width, height = size
    longest = max(width, height)
    if longest <= max_dim or longest <= 0:
        return None
    scale = max_dim / float(longest)
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def _to_jpeg(image, quality):
    """JPEG-encode ``image``, flattening any alpha JPEG can't carry."""
    if image.mode in ('RGBA', 'LA', 'P'):
        image = image.convert('RGB')
    buf = io.BytesIO()
    image.save(buf, format='JPEG', quality=quality)
    return buf.getvalue()


def _to_png(image):
    """PNG-encode ``image``.

    Deliberately without ``optimize=True``: it is an extra full compression
    pass for a few percent of size, and the size problem is solved by resizing
    instead.
    """
    buf = io.BytesIO()
    image.save(buf, format='PNG')
    return buf.getvalue()


def _shrink_to_fit(image, data, max_bytes):
    """Progressively downscale ``image`` until its JPEG fits ``max_bytes``.

    Encoded size scales with pixel count, so each pass estimates the needed
    linear scale as sqrt(target / actual) with a little headroom. Returns the
    smallest attempt even if it is still over the cap — the caller decides.
    """
    scale = 1.0
    for _ in range(_SHRINK_ATTEMPTS):
        scale *= min(0.95, (max_bytes * 0.85 / len(data)) ** 0.5)
        width = max(1, int(image.width * scale))
        height = max(1, int(image.height * scale))
        data = _to_jpeg(image.resize((width, height), Image.LANCZOS),
                        WEB_JPEG_QUALITY)
        if len(data) <= max_bytes:
            return data
    app_logger.warning(
        f"Web image still {len(data) / (1024 * 1024):.1f} MB after "
        f"{_SHRINK_ATTEMPTS} downscale attempts"
    )
    return data


def encode_for_web(pil_image, *, output_format='jpg', jpg_quality=85,
                   max_bytes=WEB_IMAGE_MAX_BYTES, max_dim=WEB_IMAGE_MAX_DIM):
    """Encode ``pil_image`` for the /latest endpoint.

    Honours the user's chosen ``output_format`` for frames small enough to
    serve at native size. Anything larger than ``max_dim`` on its longest edge
    is LANCZOS-resized *first* and then encoded once as JPEG, regardless of the
    configured format — a full-resolution PNG is neither servable nor useful to
    the HTTP consumers.

    Returns ``(image_bytes, content_type)``.
    """
    target = _scaled_size(pil_image.size, max_dim)

    if target is not None:
        image = pil_image.resize(target, Image.LANCZOS)
        data = _to_jpeg(image, WEB_JPEG_QUALITY)
        content_type = 'image/jpeg'
    elif str(output_format or 'jpg').strip().upper() in ('JPG', 'JPEG'):
        image = pil_image
        data = _to_jpeg(image, jpg_quality)
        content_type = 'image/jpeg'
    else:
        image = pil_image
        data = _to_png(image)
        content_type = 'image/png'

    if len(data) > max_bytes:
        return _shrink_to_fit(image, data, max_bytes), 'image/jpeg'
    return data, content_type
