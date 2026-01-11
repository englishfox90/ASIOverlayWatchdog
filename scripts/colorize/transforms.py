"""
Image transforms: stretch, bias correction, denoise, color injection.
"""

from __future__ import annotations

import numpy as np

from .io_utils import luminance_from_rgb


# ----------------------------
# Stretch functions
# ----------------------------

def stretch_mono(
    mono01: np.ndarray,
    black_pct: float,
    white_pct: float,
    asinh_strength: float,
    gamma: float,
    *,
    override_bp: float | None = None,
) -> tuple[np.ndarray, dict]:
    """Stretch mono 0..1 using bp/wp percentiles + asinh + gamma.

    If override_bp is provided, it replaces the percentile-derived black point.
    """
    mono01 = np.clip(mono01.astype(np.float32), 0, 1)

    bp = float(np.percentile(mono01, float(black_pct)))
    if override_bp is not None:
        bp = float(override_bp)

    wp = float(np.percentile(mono01, float(white_pct)))
    if wp <= bp + 1e-8:
        wp = bp + 1e-3

    x = (mono01 - bp) / (wp - bp + 1e-8)
    x = np.clip(x, 0, 1)

    s = float(asinh_strength)
    if s > 0:
        x = np.arcsinh(s * x) / np.arcsinh(s)

    g = float(gamma)
    if g != 1.0:
        x = np.clip(x, 0, 1) ** (1.0 / g)

    dbg = {
        "black_pct": float(black_pct),
        "white_pct": float(white_pct),
        "black_point": float(bp),
        "white_point": float(wp),
        "asinh_strength": float(s),
        "gamma": float(g),
        "override_bp": None if override_bp is None else float(override_bp),
    }
    return np.clip(x, 0, 1), dbg


def stretch_rgb_using_lum_points(
    rgb01: np.ndarray,
    bp: float,
    wp: float,
    asinh_strength: float,
    gamma: float,
) -> np.ndarray:
    """Apply same bp/wp + asinh + gamma to RGB (0..1)."""
    rgb01 = np.clip(rgb01.astype(np.float32), 0, 1)
    x = (rgb01 - float(bp)) / (float(wp) - float(bp) + 1e-8)
    x = np.clip(x, 0, 1)

    s = float(asinh_strength)
    if s > 0:
        x = np.arcsinh(s * x) / np.arcsinh(s)

    g = float(gamma)
    if g != 1.0:
        x = np.clip(x, 0, 1) ** (1.0 / g)

    return np.clip(x, 0, 1)


# ----------------------------
# Denoise helpers (pure numpy, no scipy)
# ----------------------------

def _median3x3_mono(img: np.ndarray) -> np.ndarray:
    """3x3 median filter using reflect padding."""
    img = img.astype(np.float32, copy=False)
    p = np.pad(img, 1, mode="reflect")
    neigh = [
        p[0:-2, 0:-2], p[0:-2, 1:-1], p[0:-2, 2:],
        p[1:-1, 0:-2], p[1:-1, 1:-1], p[1:-1, 2:],
        p[2:, 0:-2], p[2:, 1:-1], p[2:, 2:],
    ]
    return np.median(np.stack(neigh, axis=0), axis=0).astype(np.float32)


def _box_blur2d(img: np.ndarray, radius: int) -> np.ndarray:
    """Separable box blur using cumulative sums. Returns same HxW shape."""
    r = int(radius)
    if r <= 0:
        return img.astype(np.float32, copy=False)

    img = img.astype(np.float32, copy=False)
    h, w = img.shape
    k = 2 * r + 1

    # Horizontal pass
    p = np.pad(img, ((0, 0), (r, r)), mode="reflect")
    cs = np.cumsum(p, axis=1, dtype=np.float32)
    cs = np.pad(cs, ((0, 0), (1, 0)), mode="constant")
    hor = (cs[:, k:] - cs[:, :-k]) / float(k)

    # Vertical pass
    p = np.pad(hor, ((r, r), (0, 0)), mode="reflect")
    cs = np.cumsum(p, axis=0, dtype=np.float32)
    cs = np.pad(cs, ((1, 0), (0, 0)), mode="constant")
    out = (cs[k:, :] - cs[:-k, :]) / float(k)

    return out.astype(np.float32, copy=False)


def hot_pixel_dab_lum(
    lum01: np.ndarray,
    sigma: float,
    k: float = 9.0,
    max_luma: float = 0.35,
) -> tuple[np.ndarray, dict]:
    """Replace extreme bright outliers (in dark regions) with local median."""
    lum01 = np.clip(lum01.astype(np.float32), 0, 1)
    med = _median3x3_mono(lum01)

    thr = float(k) * float(sigma)
    dark_mask = lum01 < float(max_luma)
    hot = dark_mask & ((lum01 - med) > thr)

    out = lum01.copy()
    out[hot] = med[hot]

    dbg = {
        "sigma": float(sigma),
        "k": float(k),
        "threshold": float(thr),
        "max_luma": float(max_luma),
        "hot_pixels": int(np.count_nonzero(hot)),
        "hot_frac": float(np.count_nonzero(hot) / hot.size),
    }
    return out, dbg


def shadow_luma_denoise(
    lum_stretched01: np.ndarray,
    amount: float = 0.40,
    shadow_start: float = 0.02,
    shadow_end: float = 0.14,
) -> np.ndarray:
    """Shadow-weighted luma denoise: blend towards 3x3 median only in shadows."""
    y = np.clip(lum_stretched01.astype(np.float32), 0, 1)
    y_med = _median3x3_mono(y)

    denom = max(shadow_end - shadow_start, 1e-6)
    w = np.clip((shadow_end - y) / denom, 0, 1)
    w = (w * w).astype(np.float32)  # Soften transition

    a = float(np.clip(amount, 0, 1))
    return np.clip((1 - a * w) * y + (a * w) * y_med, 0, 1)


def blur_chroma_only(rgb01: np.ndarray, radius: int) -> np.ndarray:
    """Blur chroma (rgb-luma) but keep luma untouched."""
    r = int(radius)
    if r <= 0:
        return np.clip(rgb01.astype(np.float32), 0, 1)

    rgb01 = np.clip(rgb01.astype(np.float32), 0, 1)
    y = luminance_from_rgb(rgb01)[..., None]
    c = rgb01 - y

    for ch in range(3):
        c[..., ch] = _box_blur2d(c[..., ch], r)

    return np.clip(y + c, 0, 1)


# ----------------------------
# Color / chroma transforms
# ----------------------------

def blue_suppress_chroma(
    rgb01: np.ndarray,
    strength: float,
    blue_bias_floor: float = 0.020,
) -> np.ndarray:
    """Reduce blue cast by suppressing blue chroma selectively."""
    rgb01 = np.clip(rgb01.astype(np.float32), 0, 1)
    y = luminance_from_rgb(rgb01)[..., None]
    c = rgb01 - y

    blue_c = c[..., 2]
    mask = blue_c > float(blue_bias_floor)

    scale = 1.0 - float(np.clip(strength, 0, 1))
    c[..., 2][mask] *= scale

    return np.clip(y + c, 0, 1)


def inject_chroma_into_luminance(
    lum_stretched01: np.ndarray,
    rgb_stretched01: np.ndarray,
    color_strength: float,
    chroma_clip: float,
) -> np.ndarray:
    """LRGB-style chroma injection into stretched luminance."""
    lum_stretched01 = np.clip(lum_stretched01.astype(np.float32), 0, 1)
    rgb_stretched01 = np.clip(rgb_stretched01.astype(np.float32), 0, 1)

    y = luminance_from_rgb(rgb_stretched01)[..., None]
    chroma = rgb_stretched01 - y

    cc = float(max(chroma_clip, 0.0))
    if cc > 0:
        chroma = np.clip(chroma, -cc, cc)

    out = lum_stretched01[..., None] + float(color_strength) * chroma
    return np.clip(out, 0, 1)


def desaturate_global(rgb01: np.ndarray, amount: float) -> np.ndarray:
    """Global desaturation by blending towards luminance."""
    rgb01 = np.clip(rgb01.astype(np.float32), 0, 1)
    y = luminance_from_rgb(rgb01)[..., None]
    a = float(np.clip(amount, 0, 1))
    return np.clip((1 - a) * rgb01 + a * y, 0, 1)


def midtone_white_balance(
    rgb01: np.ndarray,
    *,
    roi_frac: float = 0.25,
    luma_low: float = 0.15,
    luma_high: float = 0.85,
    strength: float = 0.6,
    gain_clamp: tuple[float, float] = (0.5, 2.0),
) -> tuple[np.ndarray, dict]:
    """
    Midtone white balance correction for daylight images.

    Estimates per-channel gains from center ROI pixels in midtone range,
    then applies with configurable strength.
    """
    rgb01 = np.clip(rgb01.astype(np.float32), 0, 1)
    h, w, _ = rgb01.shape

    # Extract center ROI
    ch = max(1, int(h * roi_frac))
    cw = max(1, int(w * roi_frac))
    y0 = (h - ch) // 2
    x0 = (w - cw) // 2
    center = rgb01[y0:y0 + ch, x0:x0 + cw, :]

    # Compute luminance of center
    y_center = luminance_from_rgb(center)

    # Mask for midtones
    midtone_mask = (y_center >= luma_low) & (y_center <= luma_high)
    n_midtone = int(np.count_nonzero(midtone_mask))

    if n_midtone < 100:
        # Not enough midtone pixels, skip correction
        return rgb01, {
            "applied": False,
            "reason": "insufficient midtone pixels",
            "n_midtone": n_midtone,
        }

    # Compute mean of each channel in midtone region
    midtone_pixels = center[midtone_mask]  # (N, 3)
    channel_means = np.mean(midtone_pixels, axis=0)  # (3,)

    # Target: average of channel means (neutral gray)
    target = float(np.mean(channel_means))

    # Compute gains
    gains = np.array([
        target / max(channel_means[0], 1e-6),
        target / max(channel_means[1], 1e-6),
        target / max(channel_means[2], 1e-6),
    ], dtype=np.float32)

    # Clamp gains
    g_lo, g_hi = gain_clamp
    gains = np.clip(gains, g_lo, g_hi)

    # Apply with strength
    effective_gains = 1.0 + strength * (gains - 1.0)

    # Apply gains
    out = rgb01 * effective_gains[None, None, :]

    dbg = {
        "applied": True,
        "n_midtone": n_midtone,
        "channel_means": [float(x) for x in channel_means],
        "target": target,
        "raw_gains": [float(x) for x in gains],
        "effective_gains": [float(x) for x in effective_gains],
        "strength": float(strength),
    }
    return np.clip(out, 0, 1), dbg
