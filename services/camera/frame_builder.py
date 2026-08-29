"""Turn one raw ZWO sensor readout into a display frame plus its companion arrays.

Pure and stateless: every call allocates the arrays it returns, so a frame owns
its own memory and nothing downstream can be overwritten by the next exposure.
That is deliberate — the previous ping-pong buffer pool handed the same two
slots back on alternating frames, so a queued processing task could have the
array stretched out from under it while the camera wrote the next frame.

Also holds the raw-frame *cache* contract: the three lightweight keys
(`RAW_BAYER`, `RAW_GEOMETRY`, `WB_CONFIG`) that let a frame be rebuilt on demand
from ~25 MB of SDK bytes instead of keeping the ~125 MB of decoded pixels alive.
"""
from __future__ import annotations

from PIL import Image

from .camera_utils import (
    apply_white_balance,
    calculate_image_stats,
    debayer_raw_image,
)
from ..logger import app_logger

# Metadata keys that describe how to rebuild a frame. They ride in the cached
# metadata only — never into the processor, which would pin the SDK bytes for
# the life of preview_metadata (it only pops the two decoded arrays).
CACHE_KEYS = ('RAW_BAYER', 'RAW_GEOMETRY', 'WB_CONFIG')

# Decoded per-frame arrays. Large; the processor pops both when it finishes.
ARRAY_KEYS = ('RAW_RGB_16BIT', 'RAW_RGB_NO_WB')


def build_frame(raw_bytes, width, height, bit_depth, bayer_pattern='BGGR',
                wb_config=None):
    """Debayer, white-balance, and package one raw readout.

    Returns ``(pil_image, arrays, stats)`` where ``arrays`` is a dict of the
    ``ARRAY_KEYS`` (values may be None) and ``stats`` is the
    :func:`calculate_image_stats` result for the displayed pixels.
    """
    img_rgb, img_rgb_raw16 = debayer_raw_image(
        raw_bytes, width, height, bayer_pattern,
        bit_depth=bit_depth,
        return_raw16=(bit_depth == 16),
    )

    # RAW_RGB_NO_WB exists solely as the pre-WB fallback for a missing
    # RAW_RGB_16BIT (image_processor._process_task), so in RAW16 mode it has no
    # reader at all — building it there pins a second full-frame array for
    # nothing.
    img_rgb_no_wb = img_rgb.copy() if bit_depth != 16 else None

    img_rgb = apply_white_balance(img_rgb, wb_config)
    pil_image = Image.fromarray(img_rgb, mode='RGB')

    # Stats come from the same uint8 array the PIL image was built from;
    # np.array(pil_image) would only re-materialise identical values.
    stats = calculate_image_stats(img_rgb)

    arrays = {'RAW_RGB_16BIT': img_rgb_raw16, 'RAW_RGB_NO_WB': img_rgb_no_wb}
    return pil_image, arrays, stats


def cache_metadata(metadata: dict) -> dict:
    """Array-free copy of ``metadata`` suitable for the raw-frame cache."""
    return {k: v for k, v in metadata.items() if k not in ARRAY_KEYS}


def strip_cache_keys(metadata: dict) -> dict:
    """Copy of ``metadata`` without the rebuild keys — what the processor gets."""
    return {k: v for k, v in metadata.items() if k not in CACHE_KEYS}


def is_rebuildable(metadata) -> bool:
    return bool(metadata) and metadata.get('RAW_BAYER') is not None


def rebuild_frame(metadata: dict):
    """Rebuild ``(pil_image, metadata)`` from a cached raw frame.

    The returned metadata is a shallow copy carrying the freshly decoded arrays
    and none of the rebuild keys. Returns ``(None, None)`` if the cache is not
    rebuildable or decoding fails.
    """
    if not is_rebuildable(metadata):
        return None, None
    try:
        width, height, bit_depth, bayer_pattern = metadata['RAW_GEOMETRY']
        pil_image, arrays, _stats = build_frame(
            metadata['RAW_BAYER'], width, height, bit_depth,
            bayer_pattern, metadata.get('WB_CONFIG'),
        )
    except Exception as e:
        app_logger.error(f"Failed to rebuild cached raw frame: {e}")
        return None, None

    rebuilt = strip_cache_keys(metadata)
    rebuilt.update({k: v for k, v in arrays.items() if v is not None})
    return pil_image, rebuilt


__all__ = [
    'ARRAY_KEYS',
    'CACHE_KEYS',
    'build_frame',
    'cache_metadata',
    'is_rebuildable',
    'rebuild_frame',
    'strip_cache_keys',
]