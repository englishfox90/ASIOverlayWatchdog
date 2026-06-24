"""
Shared image downscaling helper.

Single definition of "shrink a PIL image so its longest edge fits a cap, then
encode as JPEG". Used by the image library and intended to replace the
copy-pasted resize blocks in the Discord and web-output paths so the app has
one resize implementation, not three.
"""
import io
from PIL import Image


def downscale_to_jpeg(img, max_edge=750, quality=85):
    """Downscale ``img`` so its longest edge is <= ``max_edge`` and JPEG-encode it.

    Aspect ratio is preserved and the image is only ever shrunk, never upscaled
    (an image already within the cap is encoded at its native size). RGBA/P/LA
    images are flattened to RGB so JPEG encoding cannot fail.

    Args:
        img: A PIL ``Image.Image``.
        max_edge: Maximum length of the longest edge in pixels.
        quality: JPEG quality (1-95).

    Returns:
        Tuple ``(jpeg_bytes, width, height)`` where width/height are the encoded
        dimensions.
    """
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    # A non-positive cap means "no limit" — never let a stray 0/negative config
    # collapse the image to 1x1.
    longest = max(img.width, img.height)
    if max_edge and max_edge > 0 and longest > max_edge:
        ratio = max_edge / longest
        new_size = (max(1, round(img.width * ratio)), max(1, round(img.height * ratio)))
        img = img.resize(new_size, Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=max(1, min(95, quality)))
    return buf.getvalue(), img.width, img.height
