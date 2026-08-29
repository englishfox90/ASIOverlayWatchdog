#!/usr/bin/env python3
"""Shared image resize for the ML models — one source of truth.

The roof and sky classifiers (and their trainers) must resize identically, or
predictions skew. This logic used to be copy-pasted in four places; keep it
here so training and inference can never drift.

Multi-camera note: the models are tagged/served across cameras with different
aspect ratios, but every model needs a fixed square input. We center-crop to the
largest centered square BEFORE downscaling, which preserves geometry instead of
squishing a non-square frame to square (distortion the model never saw). On an
already-square frame the crop is a no-op, so existing square-trained models stay
valid with no retrain.
"""
import numpy as np

# Rec.601 luma, the weights every classifier and the training-time stretch used.
_LUMA_R, _LUMA_G, _LUMA_B = 0.299, 0.587, 0.114

# Rows per chunk in the weighted sum. Small enough that the float64 working
# temporaries stay a few MB, large enough that the loop overhead is noise.
_GRAY_ROW_CHUNK = 256


def to_gray_float32(img: np.ndarray) -> np.ndarray:
    """Luminance plane of `img` as a **freshly allocated** float32 2D array.

    Accepts 2D, or 3D (H, W, C): C == 3 is weighted 0.299/0.587/0.114, any other
    C takes channel 0. Integer and float inputs are both fine.

    The returned array never aliases `img`, even when `img` is already a float32
    2D array. Callers share one gray plane per frame and some of them stretch it
    in place, so aliasing would silently corrupt the source.

    The 3-channel sum runs over row chunks in float64 and stores float32, which
    is bit-identical to the whole-frame ``0.299*r + 0.587*g + 0.114*b`` float64
    expression it replaces while holding one full-size plane (50 MB at
    3552x3552) instead of three float64 temporaries (300 MB).
    """
    if img.ndim == 3:
        if img.shape[2] != 3:
            return img[:, :, 0].astype(np.float32)
        out = np.empty(img.shape[:2], dtype=np.float32)
        for y0 in range(0, img.shape[0], _GRAY_ROW_CHUNK):
            block = img[y0:y0 + _GRAY_ROW_CHUNK]
            acc = _LUMA_R * block[:, :, 0]
            acc += _LUMA_G * block[:, :, 1]
            acc += _LUMA_B * block[:, :, 2]
            out[y0:y0 + _GRAY_ROW_CHUNK] = acc
        return out
    return img.astype(np.float32)


def as_gray_float32(img: np.ndarray) -> np.ndarray:
    """Reuse a caller-supplied float32 2D plane, else convert via to_gray_float32.

    Read-only contract: the result MAY alias `img`, so callers must not write
    into it. Use this on an inference entry point that is handed either a raw
    frame or the per-frame shared gray plane.
    """
    if img.ndim == 2 and img.dtype == np.float32:
        return img
    return to_gray_float32(img)


def center_crop_square(img: np.ndarray) -> np.ndarray:
    """Crop a 2D array to its largest centered square. No-op if already square."""
    h, w = img.shape[:2]
    if h == w:
        return img
    m = min(h, w)
    top = (h - m) // 2
    left = (w - m) // 2
    return img[top:top + m, left:left + m]


def block_average_resize(img: np.ndarray, size: int) -> np.ndarray:
    """Downscale a 2D array to size x size by block averaging."""
    h, w = img.shape
    block_h = h // size
    block_w = w // size

    if block_h == 0 or block_w == 0:
        # Source smaller than target on a side — copy into the top-left corner.
        result = np.zeros((size, size), dtype=np.float32)
        copy_h = min(h, size)
        copy_w = min(w, size)
        result[:copy_h, :copy_w] = img[:copy_h, :copy_w]
        return result

    trimmed = img[:block_h * size, :block_w * size]
    return trimmed.reshape(size, block_h, size, block_w).mean(axis=(1, 3))


def crop_for_model(img: np.ndarray, size: int) -> np.ndarray:
    """The exact sub-array that ``resize_for_model(img, size)`` will read.

    resize_for_model throws away the right/bottom remainder that cannot fill a
    whole block. A caller that has to materialise a full-resolution working copy
    (the sky stretch does) can crop to this first: it skips the discarded pixels
    and, because the copy then divides evenly into blocks, block_average_resize's
    reshape becomes a view rather than a second full-size copy. Applying this
    before resize_for_model does not change resize_for_model's output.
    """
    square = center_crop_square(img)
    h, w = square.shape
    block_h = h // size
    block_w = w // size
    if block_h == 0 or block_w == 0:
        return square
    return square[:block_h * size, :block_w * size]


def resize_for_model(img: np.ndarray, size: int) -> np.ndarray:
    """Aspect-preserving resize to size x size: center-crop to square, then
    block-average. Identical to the legacy squish on already-square inputs."""
    return block_average_resize(center_crop_square(img), size)
