"""Preview downscale — the single cap shared by the worker and the preview widget.

The GUI preview never needs more than ``PREVIEW_MAX_PX`` on its long side, and
the LANCZOS resize that gets a 3552^2 frame down to it costs 150-350 ms. That
has to run on the processing worker, not the GUI thread, so both ends resolve
the cap from here: the worker emits an already-capped preview and the widget's
own call becomes a no-op guard for callers that still hand it a full-res frame.
"""
from PIL import Image

PREVIEW_MAX_PX = 1920


def downscale_for_preview(img, max_px: int = PREVIEW_MAX_PX):
    """Return ``img`` scaled so its long side is at most ``max_px``.

    Returns the input object unchanged when it already fits, so callers must
    treat the result as read-only rather than mutating it in place.
    """
    if img is None:
        return img
    width, height = img.size
    longest = max(width, height)
    if longest <= max_px:
        return img
    scale = max_px / longest
    return img.resize(
        (max(1, int(width * scale)), max(1, int(height * scale))),
        Image.Resampling.LANCZOS,
    )
