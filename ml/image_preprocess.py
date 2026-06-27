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


def resize_for_model(img: np.ndarray, size: int) -> np.ndarray:
    """Aspect-preserving resize to size x size: center-crop to square, then
    block-average. Identical to the legacy squish on already-square inputs."""
    return block_average_resize(center_crop_square(img), size)
