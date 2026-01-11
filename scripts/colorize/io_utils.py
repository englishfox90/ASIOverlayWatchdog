"""
IO utilities for FITS loading, normalization, and output writing.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from astropy.io import fits
import imageio.v3 as iio


def load_fits(path: str) -> np.ndarray:
    """Load FITS file and return numpy array."""
    return np.asarray(fits.getdata(path))


def to_hwc_rgb(color: np.ndarray) -> np.ndarray:
    """Accept (3,H,W) or (H,W,3) and return (H,W,3)."""
    if color.ndim == 3 and color.shape[0] == 3:
        return np.transpose(color, (1, 2, 0))
    if color.ndim == 3 and color.shape[2] == 3:
        return color
    raise ValueError(
        f"Unexpected color shape: {color.shape}. "
        "Expected a 3-channel FITS (3,H,W) or (H,W,3), not a 2D Bayer mosaic."
    )


def normalize_if_int(arr: np.ndarray) -> tuple[np.ndarray, dict]:
    """Normalize to float32 0..1.

    - integer: divide by dtype max
    - float: if not 0..1-ish, scale by p99.9
    """
    dbg = {
        "dtype": str(arr.dtype),
        "raw_min": float(np.min(arr)),
        "raw_max": float(np.max(arr)),
    }

    if np.issubdtype(arr.dtype, np.integer):
        denom = float(np.iinfo(arr.dtype).max)
        out = arr.astype(np.float32) / denom
        dbg["denom"] = denom
        return np.clip(out, 0, 1), dbg

    out = arr.astype(np.float32)
    p999 = float(np.percentile(out, 99.9))
    dbg["p999"] = p999
    if p999 > 1.5:
        out = out / (p999 + 1e-8)
        dbg["scaled_by_p999"] = True
    else:
        dbg["scaled_by_p999"] = False
    return np.clip(out, 0, 1), dbg


def save_output_image(rgb01: np.ndarray, out_path: Path) -> dict:
    """Save float 0..1 RGB image as 8-bit PNG/JPG."""
    out_u8 = (np.clip(rgb01, 0, 1) * 255.0).round().astype(np.uint8)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    iio.imwrite(str(out_path), out_u8)
    return {
        "path": str(out_path),
        "shape": list(out_u8.shape),
        "dtype": str(out_u8.dtype),
    }


def luminance_from_rgb(rgb01: np.ndarray) -> np.ndarray:
    """Rec.709 luminance from (H,W,3) float 0..1 -> (H,W)."""
    return (
        0.2126 * rgb01[..., 0]
        + 0.7152 * rgb01[..., 1]
        + 0.0722 * rgb01[..., 2]
    )
