"""
Measurement utilities: corner ROI stats, mode classification, quality metrics.
"""

from __future__ import annotations

import numpy as np

from .io_utils import luminance_from_rgb


def _mad_sigma(x: np.ndarray) -> float:
    """Robust sigma estimate from MAD (Median Absolute Deviation)."""
    x = x.astype(np.float32, copy=False).ravel()
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med)))
    return float(1.4826 * mad + 1e-8)


def _corner_rois(img2d: np.ndarray, roi: int = 50, margin: int = 5) -> tuple[np.ndarray, dict]:
    """Return concatenated corner pixels from 4 ROIs (TL, TR, BL, BR)."""
    h, w = img2d.shape[:2]
    r = int(roi)
    m = int(margin)

    if h < (2 * (m + r + 1)) or w < (2 * (m + r + 1)):
        raise ValueError(f"Image too small for roi={roi} margin={margin}: shape={img2d.shape}")

    y0, y1 = m, m + r
    x0, x1 = m, m + r
    y2, y3 = h - m - r, h - m
    x2, x3 = w - m - r, w - m

    tl = img2d[y0:y1, x0:x1]
    tr = img2d[y0:y1, x2:x3]
    bl = img2d[y2:y3, x0:x1]
    br = img2d[y2:y3, x2:x3]

    vals = np.concatenate([tl.ravel(), tr.ravel(), bl.ravel(), br.ravel()]).astype(np.float32)

    dbg = {
        "roi": r,
        "margin": m,
        "n_vals": int(vals.size),
        "tl_med": float(np.median(tl)),
        "tr_med": float(np.median(tr)),
        "bl_med": float(np.median(bl)),
        "br_med": float(np.median(br)),
        "all_min": float(np.min(vals)),
        "all_p10": float(np.percentile(vals, 10)),
        "all_p50": float(np.percentile(vals, 50)),
        "all_p90": float(np.percentile(vals, 90)),
        "all_max": float(np.max(vals)),
    }
    return vals, dbg


def estimate_bias_sigma_from_corners(
    lum01: np.ndarray, roi: int = 50, margin: int = 5
) -> tuple[float, float, dict]:
    """Estimate bias (median) and sigma (MAD) from corner ROIs of luminance."""
    vals, dbg = _corner_rois(lum01, roi=roi, margin=margin)
    bias = float(np.median(vals))
    sigma = _mad_sigma(vals)
    dbg["bias"] = float(bias)
    dbg["sigma_mad"] = float(sigma)
    return bias, sigma, dbg


def estimate_rgb_bias_from_corners(
    rgb01: np.ndarray, roi: int = 50, margin: int = 5
) -> tuple[np.ndarray, dict]:
    """Estimate per-channel RGB bias from corner ROIs. Returns (3,) array."""
    h, w, _ = rgb01.shape
    r = int(roi)
    m = int(margin)

    tl = rgb01[m:m + r, m:m + r, :]
    tr = rgb01[m:m + r, w - m - r:w - m, :]
    bl = rgb01[h - m - r:h - m, m:m + r, :]
    br = rgb01[h - m - r:h - m, w - m - r:w - m, :]

    vals = np.concatenate([
        tl.reshape(-1, 3), tr.reshape(-1, 3),
        bl.reshape(-1, 3), br.reshape(-1, 3)
    ], axis=0)
    bias = np.median(vals, axis=0).astype(np.float32)

    dbg = {
        "bias_r": float(bias[0]),
        "bias_g": float(bias[1]),
        "bias_b": float(bias[2]),
        "n_pixels": int(vals.shape[0]),
    }
    return bias, dbg


def classify_mode_from_lum(
    lum01: np.ndarray,
    *,
    corner_roi: int = 50,
    corner_margin: int = 5,
    center_frac: float = 0.25,
    # Day/night thresholds
    day_p50: float = 0.10,
    day_p99: float = 0.35,
    # Roof closed thresholds (corner vs center contrast)
    closed_ratio: float = 0.55,
    closed_delta: float = 0.02,
) -> dict:
    """
    Classify frame into one of 4 modes:
      DAY_ROOF_CLOSED / DAY_ROOF_OPEN / NIGHT_ROOF_CLOSED / NIGHT_ROOF_OPEN

    Uses global brightness (p50/p99) for day/night and corner-vs-center
    contrast for roof open/closed detection.

    Special case: Very low dynamic range frames (p99 < 0.05) are classified
    as CLOSED since they represent blocked/dark frames with no sky signal.
    """
    lum01 = np.clip(lum01.astype(np.float32), 0, 1)
    h, w = lum01.shape

    # Global brightness stats
    p1 = float(np.percentile(lum01, 1))
    p10 = float(np.percentile(lum01, 10))
    p50 = float(np.percentile(lum01, 50))
    p90 = float(np.percentile(lum01, 90))
    p99 = float(np.percentile(lum01, 99))
    dr = p99 - p1

    # Day/Night decision
    is_day = (p50 >= day_p50) or (p99 >= day_p99)

    # Corner median (DIY overscan)
    r = int(corner_roi)
    m = int(corner_margin)
    if h >= (2 * (m + r + 1)) and w >= (2 * (m + r + 1)):
        tl = lum01[m:m + r, m:m + r]
        tr = lum01[m:m + r, w - m - r:w - m]
        bl = lum01[h - m - r:h - m, m:m + r]
        br = lum01[h - m - r:h - m, w - m - r:w - m]
        corner_vals = np.concatenate([tl.ravel(), tr.ravel(), bl.ravel(), br.ravel()])
        corner_med = float(np.median(corner_vals))
        corner_p90 = float(np.percentile(corner_vals, 90))
    else:
        corner_med = float(np.percentile(lum01, 5))
        corner_p90 = float(np.percentile(lum01, 10))

    # Center median
    cf = float(np.clip(center_frac, 0.05, 0.8))
    ch = max(1, int(h * cf))
    cw = max(1, int(w * cf))
    y0 = (h - ch) // 2
    x0 = (w - cw) // 2
    center = lum01[y0:y0 + ch, x0:x0 + cw]
    center_med = float(np.median(center))
    center_p90 = float(np.percentile(center, 90))

    # Roof open/closed decision
    ratio = corner_med / max(center_med, 1e-6)
    delta = center_med - corner_med

    # Special case: Very dark/low-DR frames are likely closed roof or bias frames
    # If p99 < 0.05 (5% of full scale), treat as closed regardless of corner/center ratio
    very_dark_frame = (p99 < 0.05) and (dr < 0.02)

    # Standard closed detection: corners much darker than center
    standard_closed = (ratio <= closed_ratio) and (delta >= closed_delta)

    is_closed = very_dark_frame or standard_closed

    # Determine mode and reason
    if very_dark_frame:
        closed_reason = "very dark frame (p99 < 0.05, low DR)"
    elif standard_closed:
        closed_reason = "corners much darker than center"
    else:
        closed_reason = "corners similar to center"

    if is_day and is_closed:
        mode = "DAY_ROOF_CLOSED"
        reason = f"day brightness + {closed_reason}"
    elif is_day and not is_closed:
        mode = "DAY_ROOF_OPEN"
        reason = "day brightness + corners similar to center"
    elif (not is_day) and is_closed:
        mode = "NIGHT_ROOF_CLOSED"
        reason = f"night brightness + {closed_reason}"
    else:
        mode = "NIGHT_ROOF_OPEN"
        reason = "night brightness + corners similar to center"

    return {
        "mode": mode,
        "reason": reason,
        "stats": {
            "p1": p1, "p10": p10, "p50": p50, "p90": p90, "p99": p99,
            "dynamic_range_p99_p1": dr,
            "corner_med": corner_med, "corner_p90": corner_p90,
            "center_med": center_med, "center_p90": center_p90,
            "corner_to_center_ratio": ratio,
            "center_minus_corner": delta,
            "is_day": bool(is_day),
            "is_closed": bool(is_closed),
            "very_dark_frame": bool(very_dark_frame),
        },
        "thresholds": {
            "day_p50": day_p50, "day_p99": day_p99,
            "closed_ratio": closed_ratio, "closed_delta": closed_delta,
            "corner_roi": corner_roi, "corner_margin": corner_margin,
            "center_frac": center_frac,
        },
    }


def compute_quality_metrics(
    output_rgb01: np.ndarray,
    corner_roi: int = 50,
    corner_margin: int = 5,
) -> dict:
    """
    Compute image quality metrics for recipe evaluation.

    Returns dict with:
      - luma stats (mean, p1/p50/p99)
      - saturation fraction (pixels near 0 or 1)
      - mean abs chroma
      - detail proxy (mean abs gradient)
      - background noise proxy (stddev in corners)
    """
    output_rgb01 = np.clip(output_rgb01.astype(np.float32), 0, 1)
    y = luminance_from_rgb(output_rgb01)

    # Luma stats
    luma_mean = float(np.mean(y))
    luma_p1 = float(np.percentile(y, 1))
    luma_p50 = float(np.percentile(y, 50))
    luma_p99 = float(np.percentile(y, 99))

    # Saturation fraction (clipped pixels)
    near_black = float(np.mean(y < 0.01))
    near_white = float(np.mean(y > 0.99))
    sat_frac = near_black + near_white

    # Mean abs chroma
    chroma = output_rgb01 - y[..., None]
    mean_abs_chroma = float(np.mean(np.abs(chroma)))

    # Detail proxy: mean abs gradient (Sobel-lite via finite differences)
    dy = np.abs(y[1:, :] - y[:-1, :])
    dx = np.abs(y[:, 1:] - y[:, :-1])
    detail_proxy = float((np.mean(dy) + np.mean(dx)) / 2.0)

    # Background noise proxy: stddev in corners after processing
    h, w = y.shape
    r = int(corner_roi)
    m = int(corner_margin)
    if h >= (2 * (m + r + 1)) and w >= (2 * (m + r + 1)):
        tl = y[m:m + r, m:m + r]
        tr = y[m:m + r, w - m - r:w - m]
        bl = y[h - m - r:h - m, m:m + r]
        br = y[h - m - r:h - m, w - m - r:w - m]
        corner_vals = np.concatenate([tl.ravel(), tr.ravel(), bl.ravel(), br.ravel()])
        corner_stddev = float(np.std(corner_vals))
        corner_mean = float(np.mean(corner_vals))
    else:
        corner_stddev = float(np.std(y[:50, :50]))
        corner_mean = float(np.mean(y[:50, :50]))

    return {
        "luma_mean": luma_mean,
        "luma_p1": luma_p1,
        "luma_p50": luma_p50,
        "luma_p99": luma_p99,
        "near_black_frac": near_black,
        "near_white_frac": near_white,
        "saturation_frac": sat_frac,
        "mean_abs_chroma": mean_abs_chroma,
        "detail_proxy": detail_proxy,
        "corner_stddev": corner_stddev,
        "corner_mean": corner_mean,
    }
