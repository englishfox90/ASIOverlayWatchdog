r"""
colorize_from_lum.py

Drop-in replacement for PFRSentinel stretch/color tuning.

What this version does (per your spec, plus the aggressive corner-driven cleanup you asked for):

A) Corner “DIY overscan” (50x50 ROIs, 5px margin)
   - Computes robust per-frame:
       * bias  = median(corner pixels)
       * sigma = 1.4826 * MAD(corner pixels)
   - These are written to debug.json

B) Luminance cleanup BEFORE stretch (aggressive, but structure-preserving)
   - Subtract bias from LUMINANCE ONLY (your request)
   - Optionally raise the effective black point by N*sigma (noise-floor gate)
     This is the “pull noise out using corner calculations” knob.

C) Stretch
   1) stretch luminance using bp/wp + asinh + gamma
   2) stretch RGB using SAME bp/wp/asinh/gamma
   3) inject chroma into stretched luminance (LRGB-style)

D) Post-stretch denoise (cheap wins)
   - Optional hot-pixel dab on luminance (uses corner sigma)
   - Optional shadow-only luma smoothing (uses local median) to reduce "static" in dark areas
   - Optional chroma blur (very light) to reduce color speckle without smearing detail

Why your earlier attempts sometimes “lost color”:
- Too much global desaturation or heavy chroma suppression can push chroma towards zero.
- This version defaults to *shadow-only* smoothing + optional light chroma blur.

Usage (PowerShell example):
& "c:\Astrophotography\PFRSentinel\venv\Scripts\python.exe" `
  "c:\Astrophotography\PFRSentinel\scripts\colorize_from_lum.py" `
  "C:\Users\Paul Fox-Reeks\AppData\Local\PFRSentinel\raw_debug\lum_20260105_003229.fits" `
  "C:\Users\Paul Fox-Reeks\AppData\Local\PFRSentinel\raw_debug\raw_20260105_003229.fits" `
  --black_pct 5 --white_pct 99.9 --asinh 30 --gamma 1.05 `
  --color_strength 1.20 --chroma_clip 0.55 --blue_suppress 0.92 --desaturate 0.05 --blue_floor 0.020 `
  --corner_roi 50 --corner_margin 5 `
  --corner_sigma_bp 2.0 `
  --hp_dab 1 --hp_k 9 --hp_max_luma 0.35 `
  --shadow_denoise 0.40 --shadow_start 0.02 --shadow_end 0.14 `
  --chroma_blur 1 `
  --out_dir "colorize_out" --out_name "final_corner_overscan_aggressive.png"

Notes:
- Expects color FITS to be (3,H,W) or (H,W,3). If it's 2D Bayer, this script errors.
- Uses a raw docstring to avoid Windows path unicode escape issues.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from astropy.io import fits
import imageio.v3 as iio


# ----------------------------
# IO / normalization
# ----------------------------

def load_fits(path: str) -> np.ndarray:
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
    dbg = {"dtype": str(arr.dtype), "raw_min": float(np.min(arr)), "raw_max": float(np.max(arr))}

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


def luminance_from_rgb(rgb01: np.ndarray) -> np.ndarray:
    """Rec.709 luminance from (H,W,3) float 0..1 -> (H,W)."""
    return (
        0.2126 * rgb01[..., 0]
        + 0.7152 * rgb01[..., 1]
        + 0.0722 * rgb01[..., 2]
    )


# ----------------------------
# Corner ROI “overscan”
# ----------------------------

def _mad_sigma(x: np.ndarray) -> float:
    """Robust sigma estimate from MAD."""
    x = x.astype(np.float32, copy=False).ravel()
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med)))
    return float(1.4826 * mad + 1e-8)


def corner_rois(lum01: np.ndarray, roi: int = 50, margin: int = 5) -> tuple[np.ndarray, dict]:
    """Return concatenated corner pixels from 4 ROIs."""
    h, w = lum01.shape
    r = int(roi)
    m = int(margin)

    if h < (2 * (m + r + 1)) or w < (2 * (m + r + 1)):
        raise ValueError(f"Image too small for roi={roi} margin={margin}: shape={lum01.shape}")

    y0, y1 = m, m + r
    x0, x1 = m, m + r
    y2, y3 = h - m - r, h - m
    x2, x3 = w - m - r, w - m

    tl = lum01[y0:y1, x0:x1]
    tr = lum01[y0:y1, x2:x3]
    bl = lum01[y2:y3, x0:x1]
    br = lum01[y2:y3, x2:x3]

    vals = np.concatenate([tl.ravel(), tr.ravel(), bl.ravel(), br.ravel()]).astype(np.float32, copy=False)

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


def estimate_bias_sigma_from_corners(lum01: np.ndarray, roi: int, margin: int) -> tuple[float, float, dict]:
    vals, dbg = corner_rois(lum01, roi=roi, margin=margin)
    bias = float(np.median(vals))
    sigma = _mad_sigma(vals)
    dbg["bias"] = float(bias)
    dbg["sigma_mad"] = float(sigma)
    return bias, sigma, dbg

def estimate_rgb_bias_from_corners(rgb01: np.ndarray, roi: int, margin: int) -> tuple[np.ndarray, dict]:
    """
    Estimate per-channel RGB bias from the same 4 corner ROIs.
    Returns bias_rgb: shape (3,) float32
    """
    h, w, _ = rgb01.shape
    r = int(roi); m = int(margin)

    TL = rgb01[m:m+r, m:m+r, :]
    TR = rgb01[m:m+r, w-m-r:w-m, :]
    BL = rgb01[h-m-r:h-m, m:m+r, :]
    BR = rgb01[h-m-r:h-m, w-m-r:w-m, :]

    vals = np.concatenate([TL.reshape(-1,3), TR.reshape(-1,3), BL.reshape(-1,3), BR.reshape(-1,3)], axis=0)
    bias = np.median(vals, axis=0).astype(np.float32)

    dbg = {
        "bias_r": float(bias[0]),
        "bias_g": float(bias[1]),
        "bias_b": float(bias[2]),
    }
    return bias, dbg



# ----------------------------
# Stretch
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


def stretch_rgb_using_lum_points(rgb01: np.ndarray, bp: float, wp: float, asinh_strength: float, gamma: float) -> np.ndarray:
    """Apply same bp/wp + asinh + gamma to RGB (0..1)."""
    rgb01 = np.clip(rgb01.astype(np.float32), 0, 1)
    x = (rgb01 - float(bp)) / (float(wp) - float(bp) + 1e-8)
    x = np.clip(x, 0, 1)

    s = float(asinh_strength)
    x = np.arcsinh(s * x) / np.arcsinh(s)

    g = float(gamma)
    if g != 1.0:
        x = np.clip(x, 0, 1) ** (1.0 / g)

    return np.clip(x, 0, 1)


# ----------------------------
# Denoise helpers (no extra deps)
# ----------------------------

def median3x3_mono(img: np.ndarray) -> np.ndarray:
    img = img.astype(np.float32, copy=False)
    p = np.pad(img, 1, mode="reflect")
    neigh = [
        p[0:-2, 0:-2], p[0:-2, 1:-1], p[0:-2, 2:],
        p[1:-1, 0:-2], p[1:-1, 1:-1], p[1:-1, 2:],
        p[2:,   0:-2], p[2:,   1:-1], p[2:,   2:],
    ]
    return np.median(np.stack(neigh, axis=0), axis=0).astype(np.float32)


def hot_pixel_dab_lum(lum01: np.ndarray, sigma: float, k: float = 9.0, max_luma: float = 0.35) -> tuple[np.ndarray, dict]:
    """Replace only extreme bright outliers (in dark regions) with local median."""
    lum01 = np.clip(lum01.astype(np.float32), 0, 1)
    med = median3x3_mono(lum01)

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


def shadow_luma_denoise(lum_stretched01: np.ndarray, amount: float = 0.40, shadow_start: float = 0.02, shadow_end: float = 0.14) -> np.ndarray:
    """Shadow-weighted luma denoise: blend towards 3x3 median only in shadows."""
    y = np.clip(lum_stretched01.astype(np.float32), 0, 1)
    y_med = median3x3_mono(y)

    denom = max(shadow_end - shadow_start, 1e-6)
    w = np.clip((shadow_end - y) / denom, 0, 1)
    w = (w * w).astype(np.float32)  # soften

    a = float(np.clip(amount, 0, 1))
    return np.clip((1 - a * w) * y + (a * w) * y_med, 0, 1)


def box_blur2d(img: np.ndarray, radius: int) -> np.ndarray:
    """Stable box blur using separable cumulative sums. Returns same HxW shape."""
    r = int(radius)
    if r <= 0:
        return img.astype(np.float32, copy=False)

    img = img.astype(np.float32, copy=False)
    h, w = img.shape
    k = 2 * r + 1

    # horizontal
    p = np.pad(img, ((0, 0), (r, r)), mode="reflect")
    cs = np.cumsum(p, axis=1, dtype=np.float32)
    cs = np.pad(cs, ((0, 0), (1, 0)), mode="constant")
    hor = (cs[:, k:] - cs[:, :-k]) / float(k)

    # vertical
    p = np.pad(hor, ((r, r), (0, 0)), mode="reflect")
    cs = np.cumsum(p, axis=0, dtype=np.float32)
    cs = np.pad(cs, ((1, 0), (0, 0)), mode="constant")
    out = (cs[k:, :] - cs[:-k, :]) / float(k)

    return out.astype(np.float32, copy=False)


def blur_chroma_only(rgb01: np.ndarray, radius: int) -> np.ndarray:
    """Blur chroma (rgb-luma) but keep luma untouched."""
    r = int(radius)
    if r <= 0:
        return np.clip(rgb01.astype(np.float32), 0, 1)

    rgb01 = np.clip(rgb01.astype(np.float32), 0, 1)
    y = luminance_from_rgb(rgb01)[..., None]
    c = rgb01 - y

    for ch in range(3):
        c[..., ch] = box_blur2d(c[..., ch], r)

    return np.clip(y + c, 0, 1)


# ----------------------------
# Color / chroma
# ----------------------------

def blue_suppress_chroma(rgb01: np.ndarray, strength: float, blue_bias_floor: float = 0.020) -> np.ndarray:
    """Reduce blue cast by suppressing blue chroma selectively."""
    rgb01 = np.clip(rgb01.astype(np.float32), 0, 1)
    y = luminance_from_rgb(rgb01)[..., None]
    c = rgb01 - y

    blue_c = c[..., 2]
    mask = blue_c > float(blue_bias_floor)

    scale = 1.0 - float(np.clip(strength, 0, 1))
    c[..., 2][mask] *= scale

    return np.clip(y + c, 0, 1)


def inject_chroma_into_luminance(lum_stretched01: np.ndarray, rgb_stretched01: np.ndarray, color_strength: float, chroma_clip: float) -> np.ndarray:
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
    rgb01 = np.clip(rgb01.astype(np.float32), 0, 1)
    y = luminance_from_rgb(rgb01)[..., None]
    a = float(np.clip(amount, 0, 1))
    return np.clip((1 - a) * rgb01 + a * y, 0, 1)


# ----------------------------
# Debug / mode (optional)
# ----------------------------

def classify_mode_from_lum(
    lum01: np.ndarray,
    *,
    corner_roi: int = 50,
    corner_margin: int = 5,
    center_frac: float = 0.25,
    # Day/night thresholds (tune with your dataset)
    day_p50: float = 0.10,
    day_p99: float = 0.35,
    # Roof closed thresholds (corner vs center contrast)
    closed_ratio: float = 0.55,
    closed_delta: float = 0.02,
) -> dict:
    """
    Classify frame into:
      DAY_ROOF_CLOSED / DAY_ROOF_OPEN / NIGHT_ROOF_CLOSED / NIGHT_ROOF_OPEN

    Uses:
      - day/night: overall brightness (p50 and p99)
      - roof open/closed: corner-vs-center brightness contrast
        (roof closed => corners much darker than center)

    Assumes lum01 is float-ish and roughly 0..1 (clipped inside).
    """
    lum01 = np.clip(lum01.astype(np.float32), 0, 1)
    h, w = lum01.shape

    # --- global brightness stats ---
    p1 = float(np.percentile(lum01, 1))
    p50 = float(np.percentile(lum01, 50))
    p99 = float(np.percentile(lum01, 99))
    dr = p99 - p1

    # Day / Night decision (robust to odd highlights)
    is_day = (p50 >= day_p50) or (p99 >= day_p99)

    # --- corner median (DIY overscan) ---
    r = int(corner_roi)
    m = int(corner_margin)
    if h >= (2 * (m + r + 1)) and w >= (2 * (m + r + 1)):
        TL = lum01[m:m+r, m:m+r]
        TR = lum01[m:m+r, w-m-r:w-m]
        BL = lum01[h-m-r:h-m, m:m+r]
        BR = lum01[h-m-r:h-m, w-m-r:w-m]
        corner_vals = np.concatenate([TL.ravel(), TR.ravel(), BL.ravel(), BR.ravel()])
        corner_med = float(np.median(corner_vals))
        corner_p90 = float(np.percentile(corner_vals, 90))
    else:
        # Fallback if image is unexpectedly small
        corner_med = float(np.percentile(lum01, 5))
        corner_p90 = float(np.percentile(lum01, 10))

    # --- center median ---
    # Use a center crop so edge vignetting doesn't confuse us
    cf = float(np.clip(center_frac, 0.05, 0.8))
    ch = max(1, int(h * cf))
    cw = max(1, int(w * cf))
    y0 = (h - ch) // 2
    x0 = (w - cw) // 2
    center = lum01[y0:y0+ch, x0:x0+cw]
    center_med = float(np.median(center))
    center_p90 = float(np.percentile(center, 90))

    # --- roof open/closed decision ---
    # If roof is closed, corners should be materially darker than center.
    # Use BOTH ratio and absolute delta so this works in night + day.
    ratio = corner_med / max(center_med, 1e-6)
    delta = center_med - corner_med
    is_closed = (ratio <= closed_ratio) and (delta >= closed_delta)

    if is_day and is_closed:
        mode = "DAY_ROOF_CLOSED"
        reason = "day brightness + corners much darker than center"
    elif is_day and not is_closed:
        mode = "DAY_ROOF_OPEN"
        reason = "day brightness + corners similar to center"
    elif (not is_day) and is_closed:
        mode = "NIGHT_ROOF_CLOSED"
        reason = "night brightness + corners much darker than center"
    else:
        mode = "NIGHT_ROOF_OPEN"
        reason = "night brightness + corners similar to center"

    return {
        "mode": mode,
        "reason": reason,
        "stats": {
            "p1": p1,
            "p50": p50,
            "p99": p99,
            "dynamic_range_p99_p1": dr,
            "corner_med": corner_med,
            "corner_p90": corner_p90,
            "center_med": center_med,
            "center_p90": center_p90,
            "corner_to_center_ratio": ratio,
            "center_minus_corner": delta,
            "is_day": bool(is_day),
            "is_closed": bool(is_closed),
        },
        "thresholds": {
            "day_p50": day_p50,
            "day_p99": day_p99,
            "closed_ratio": closed_ratio,
            "closed_delta": closed_delta,
            "corner_roi": corner_roi,
            "corner_margin": corner_margin,
            "center_frac": center_frac,
        },
    }


# ----------------------------
# Main
# ----------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lum_fits")
    ap.add_argument("color_fits")
    ap.add_argument("--out_dir", default="colorize_out")
    ap.add_argument("--out_name", default=None)

    # Stretch params
    ap.add_argument("--black_pct", type=float, default=5.0)
    ap.add_argument("--white_pct", type=float, default=99.9)
    ap.add_argument("--asinh", type=float, default=30.0)
    ap.add_argument("--gamma", type=float, default=1.05)

    # Color controls
    ap.add_argument("--color_strength", type=float, default=1.20)
    ap.add_argument("--chroma_clip", type=float, default=0.55)
    ap.add_argument("--blue_suppress", type=float, default=0.92)
    ap.add_argument("--blue_floor", type=float, default=0.020)
    ap.add_argument("--desaturate", type=float, default=0.05)
    ap.add_argument("--rgb_bias_subtract", type=int, default=1, help="1=enable RGB corner bias subtract, 0=disable")

    # Corner ROI overscan
    ap.add_argument("--corner_roi", type=int, default=50)
    ap.add_argument("--corner_margin", type=int, default=5)

    # Use corner sigma to push black point upward (aggressive noise pull)
    ap.add_argument(
        "--corner_sigma_bp",
        type=float,
        default=0.0,
        help="If >0, overrides black point to (corner_sigma_bp * sigma) after bias subtract. "
             "0.5–1.5 typical for night roof-closed; keep 0 for daytime unless needed.",
    )

    # Optional hot pixel dab BEFORE stretch
    ap.add_argument("--hp_dab", type=int, default=0, help="1=enable hot pixel dab on LUM before stretch")
    ap.add_argument("--hp_k", type=float, default=12.0, help="threshold multiplier (k*sigma), 6-14 typical")
    ap.add_argument("--hp_max_luma", type=float, default=0.35, help="only dab where luma is below this")

    # Shadow denoise AFTER stretch (luma only)
    ap.add_argument("--shadow_denoise", type=float, default=0.0, help="0..1; blend median into luma only in shadows")
    ap.add_argument("--shadow_start", type=float, default=0.02)
    ap.add_argument("--shadow_end", type=float, default=0.14)

    # Light chroma blur AFTER colorize (reduces color speckle)
    ap.add_argument("--chroma_blur", type=int, default=0, help="0=off, 1-2 subtle, 3-6 more aggressive")

    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.out_name is None:
        args.out_name = f"final_bp{args.black_pct:g}_wp{args.white_pct:g}_asinh{args.asinh:g}_g{args.gamma:g}.png"

    # ----------------------------
    # Load + normalize
    # ----------------------------
    lum = load_fits(args.lum_fits)
    col = load_fits(args.color_fits)

    rgb = to_hwc_rgb(col)
    rgb01, rgb_norm_dbg = normalize_if_int(rgb)
    lum01, lum_norm_dbg = normalize_if_int(lum)

    # ----------------------------
    # Corner overscan stats
    # ----------------------------
    bias, sigma, corner_dbg = estimate_bias_sigma_from_corners(
        lum01,
        roi=int(args.corner_roi),
        margin=int(args.corner_margin),
    )

    # Bias subtract LUM (drives stretch)
    lum01_corr = np.clip(lum01 - bias, 0, 1)

    # Classify mode on the bias-corrected luminance (important!)
    mode_info = classify_mode_from_lum(lum01_corr)
    mode = str(mode_info.get("mode", "UNKNOWN"))

    # RGB per-channel corner bias (optional) -> RGB used for stretch
    rgb_corner_dbg = None
    bias_rgb = None
    if int(args.rgb_bias_subtract) > 0:
        bias_rgb, rgb_corner_dbg = estimate_rgb_bias_from_corners(
            rgb01, roi=int(args.corner_roi), margin=int(args.corner_margin)
        )
        rgb01_for_stretch = np.clip(rgb01 - bias_rgb[None, None, :], 0, 1)
    else:
        rgb01_for_stretch = rgb01

    # ----------------------------
    # Mode-based softening (prevents daytime getting crushed)
    # ----------------------------
    # For DAY_* modes, default to disabling the aggressive "noise floor" tools.
    # You can still force them on by explicitly passing non-zero values; but this
    # keeps your defaults safe as you add more modes.
    eff_corner_sigma_bp = float(args.corner_sigma_bp)
    eff_hp_dab = int(args.hp_dab)
    eff_shadow_denoise = float(args.shadow_denoise)
    eff_chroma_blur = int(args.chroma_blur)

    if mode.startswith("DAY_"):
        # Only auto-soften if user didn't explicitly choose aggressive settings
        if args.corner_sigma_bp > 0:
            eff_corner_sigma_bp = 0.0
        if args.hp_dab > 0:
            eff_hp_dab = 0
        if args.shadow_denoise > 0:
            eff_shadow_denoise = 0.0
        if args.chroma_blur > 0:
            eff_chroma_blur = 0

    # ----------------------------
    # Optional: hot pixel dab on bias-corrected LUM (pre-stretch)
    # ----------------------------
    hp_dbg = None
    if eff_hp_dab > 0:
        lum01_corr, hp_dbg = hot_pixel_dab_lum(
            lum01_corr,
            sigma=sigma,
            k=float(args.hp_k),
            max_luma=float(args.hp_max_luma),
        )

    # Aggressive black point override using sigma (noise-floor gate)
    override_bp = None
    if eff_corner_sigma_bp > 0:
        override_bp = float(eff_corner_sigma_bp) * float(sigma)

    # ----------------------------
    # Stretch LUM -> get bp/wp
    # ----------------------------
    lum_stretched01, lum_stretch_dbg = stretch_mono(
        mono01=lum01_corr,
        black_pct=args.black_pct,
        white_pct=args.white_pct,
        asinh_strength=args.asinh,
        gamma=args.gamma,
        override_bp=override_bp,  # requires stretch_mono override_bp support
    )

    # Post-stretch shadow luma denoise
    if eff_shadow_denoise > 0:
        lum_stretched01 = shadow_luma_denoise(
            lum_stretched01,
            amount=float(eff_shadow_denoise),
            shadow_start=float(args.shadow_start),
            shadow_end=float(args.shadow_end),
        )

    bp = float(lum_stretch_dbg["black_point"])
    wp = float(lum_stretch_dbg["white_point"])

    # ----------------------------
    # RGB: (optional) bias subtract THEN stretch using SAME bp/wp
    # ----------------------------
    rgb_stretched01 = stretch_rgb_using_lum_points(
        rgb01=rgb01_for_stretch,
        bp=bp,
        wp=wp,
        asinh_strength=args.asinh,
        gamma=args.gamma,
    )

    # Blue suppression (in stretched domain)
    if float(args.blue_suppress) > 0:
        rgb_stretched01 = blue_suppress_chroma(
            rgb_stretched01,
            strength=float(args.blue_suppress),
            blue_bias_floor=float(args.blue_floor),
        )

    # ----------------------------
    # Colorize (inject chroma into stretched lum)
    # ----------------------------
    out01 = inject_chroma_into_luminance(
        lum_stretched01=lum_stretched01,
        rgb_stretched01=rgb_stretched01,
        color_strength=float(args.color_strength),
        chroma_clip=float(args.chroma_clip),
    )

    # Reduce color speckle without touching luma detail (after colorize)
    if eff_chroma_blur > 0:
        out01 = blur_chroma_only(out01, radius=int(eff_chroma_blur))

    # Mild global desat (optional)
    if float(args.desaturate) > 0:
        out01 = desaturate_global(out01, amount=float(args.desaturate))

    # ----------------------------
    # Write output
    # ----------------------------
    out_u8 = (np.clip(out01, 0, 1) * 255.0).round().astype(np.uint8)
    out_path = out_dir / args.out_name
    iio.imwrite(out_path, out_u8)

    # Debug stats
    y_out = luminance_from_rgb(out01)
    chroma_mag = float(np.mean(np.abs(out01 - y_out[..., None])))

    debug = {
        "inputs": {"lum_fits": args.lum_fits, "color_fits": args.color_fits},
        "normalize": {"lum": lum_norm_dbg, "rgb": rgb_norm_dbg},
        "corner_overscan": corner_dbg,
        "rgb_corner_bias": rgb_corner_dbg,
        "bias_subtract": {"applied_to": "lum_only", "bias": float(bias), "sigma_mad": float(sigma)},
        "bias_subtract_rgb": (
            {"applied_to": "rgb_pre_stretch", "bias_rgb": [float(x) for x in bias_rgb]}
            if bias_rgb is not None else
            {"applied_to": "rgb_pre_stretch", "bias_rgb": None}
        ),
        "bp_override": {
            "corner_sigma_bp": float(args.corner_sigma_bp),
            "effective_corner_sigma_bp": float(eff_corner_sigma_bp),
            "override_bp": override_bp,
        },
        "hot_pixel_dab": hp_dbg,
        "stretch": {
            "black_pct": float(args.black_pct),
            "white_pct": float(args.white_pct),
            "asinh_strength": float(args.asinh),
            "gamma": float(args.gamma),
            "black_point": float(bp),
            "white_point": float(wp),
        },
        "color": {
            "color_strength": float(args.color_strength),
            "chroma_clip": float(args.chroma_clip),
            "blue_suppress": float(args.blue_suppress),
            "blue_floor": float(args.blue_floor),
            "desaturate": float(args.desaturate),
            "chroma_blur": int(args.chroma_blur),
            "effective_chroma_blur": int(eff_chroma_blur),
        },
        "noise": {
            "shadow_denoise": float(args.shadow_denoise),
            "effective_shadow_denoise": float(eff_shadow_denoise),
            "shadow_start": float(args.shadow_start),
            "shadow_end": float(args.shadow_end),
        },
        "mode_info": mode_info,
        "output": {
            "path": str(out_path),
            "shape": list(out_u8.shape),
            "dtype": str(out_u8.dtype),
            "mean_abs_chroma_after": chroma_mag,
        },
    }

    with open(out_dir / "debug.json", "w", encoding="utf-8") as f:
        json.dump(debug, f, indent=2)

    print(f"Saved: {out_path}")
    print(f"Mode: {mode_info.get('mode')} ({mode_info.get('reason')})")
    print(f"Corner bias (median): {bias:.6f}   sigma(MAD): {sigma:.6f}")
    if bias_rgb is not None:
        print(f"RGB corner bias: R={bias_rgb[0]:.6f} G={bias_rgb[1]:.6f} B={bias_rgb[2]:.6f}")
    else:
        print("RGB corner bias: disabled")
    if override_bp is not None:
        print(f"Override bp: {override_bp:.6f}  (corner_sigma_bp={eff_corner_sigma_bp:g})")
    if hp_dbg:
        print(f"Hot-pixel dab: {hp_dbg['hot_pixels']} pixels (k={hp_dbg['k']}, thr={hp_dbg['threshold']:.6f})")
    print(f"bp/wp (post-bias LUM): {bp:.6f} / {wp:.6f}")
    print(f"Mean |chroma| after: {chroma_mag:.6f}")


if __name__ == "__main__":
    main()
