"""
stretch_tuner.py

Creates contact sheets for luminance-driven stretching of a pier/all-sky image
using a luminance FITS + a raw color FITS.

Adds:
  ✅ A luminance-only stretch example (grayscale output; best for "roof closed / warehouse dark")
  ✅ Automatic "mode" classification: DAY / ROOF_CLOSED / ROOF_OPEN
  ✅ Mode + global luminance stats recorded into recipes.json

Usage:
  python stretch_tuner.py <lum_fits> <color_fits> [out_dir]

Outputs:
  - contact_sheet_rgb_asinh_<strength>_<MODE>.png   (3x3 grid per asinh strength)
  - contact_sheet_lum_asinh_<strength>_<MODE>.png   (3x3 grid per asinh strength)
  - recipes.json                                   (parameters + mode + stats)

Grid layout per sheet:
  rows = black_pct  [1, 2, 5]
  cols = white_pct  [99.5, 99.7, 99.9]
"""

import json
from pathlib import Path

import numpy as np
from astropy.io import fits
import imageio.v3 as iio


# ----------------------------
# FITS loading / conversions
# ----------------------------

def load_fits(path: str) -> np.ndarray:
    return np.asarray(fits.getdata(path))


def to_hwc_rgb(color: np.ndarray) -> np.ndarray:
    """Accept (3,H,W) or (H,W,3) and return (H,W,3)."""
    if color.ndim == 3 and color.shape[0] == 3:
        return np.transpose(color, (1, 2, 0))
    if color.ndim == 3 and color.shape[2] == 3:
        return color
    raise ValueError(f"Unexpected color shape: {color.shape}")


def normalize_if_uint(arr: np.ndarray) -> np.ndarray:
    """Normalize uint8/uint16 arrays to float32 0..1 using dtype max."""
    if np.issubdtype(arr.dtype, np.integer):
        maxv = float(np.iinfo(arr.dtype).max)
        return arr.astype(np.float32) / maxv
    return arr.astype(np.float32)


def normalize_luminance(lum: np.ndarray) -> np.ndarray:
    """
    Normalize luminance to float32 0..1.

    - If integer: scale by dtype max
    - If float: assume already 0..1, but if not, scale by p99.9 as a fallback.
    """
    lum01 = lum.astype(np.float32)
    if np.issubdtype(lum.dtype, np.integer):
        lum01 /= float(np.iinfo(lum.dtype).max)
        return np.clip(lum01, 0, 1)

    p999 = float(np.percentile(lum01, 99.9))
    if p999 > 1.5:
        lum01 = lum01 / (p999 + 1e-8)

    return np.clip(lum01, 0, 1)


def lum_stats(lum01: np.ndarray) -> dict:
    lum01 = np.clip(lum01.astype(np.float32), 0, 1)
    p1 = float(np.percentile(lum01, 1.0))
    p50 = float(np.percentile(lum01, 50.0))
    p90 = float(np.percentile(lum01, 90.0))
    p99 = float(np.percentile(lum01, 99.0))
    p999 = float(np.percentile(lum01, 99.9))
    dyn = float(p99 - p1)
    return {
        "p1": p1,
        "p50": p50,
        "p90": p90,
        "p99": p99,
        "p999": p999,
        "dynamic_range_p99_p1": dyn,
        "mean": float(np.mean(lum01)),
        "std": float(np.std(lum01)),
    }


def classify_mode(lum01: np.ndarray) -> tuple[str, dict]:
    """
    Heuristic mode classifier.

    DAY:
      - brighter median and much wider dynamic range (warehouse lights / daylight)

    ROOF_CLOSED:
      - very low median and tight dynamic range (almost no sky signal)

    ROOF_OPEN:
      - darker than day, but wider dynamic range than roof-closed (stars/sky adds structure)

    NOTE: These thresholds are intentionally conservative and can be tuned.
    """
    st = lum_stats(lum01)
    p50 = st["p50"]
    dyn = st["dynamic_range_p99_p1"]

    # Tune thresholds here
    if p50 > 0.18 and dyn > 0.20:
        mode = "DAY"
        reason = "high median + wide dynamic range"
    elif p50 < 0.06 and dyn < 0.08:
        mode = "ROOF_CLOSED"
        reason = "low median + tight dynamic range"
    else:
        mode = "ROOF_OPEN"
        reason = "intermediate brightness with meaningful dynamic range"

    return mode, {"mode": mode, "reason": reason, **st}


# ----------------------------
# Color correction helpers
# ----------------------------

def gray_world_midtones_clamped(
    rgb01: np.ndarray,
    low_pct: float = 30.0,
    high_pct: float = 80.0,
    min_gain: float = 0.85,
    max_gain: float = 1.20,
    sat_max: float = 0.35,
) -> tuple[np.ndarray, dict]:

    rgb01 = np.clip(rgb01.astype(np.float32), 0, 1)

    lum_post = (
        0.2126 * rgb01[..., 0] +
        0.7152 * rgb01[..., 1] +
        0.0722 * rgb01[..., 2]
    )

    eps = 1.0 / 255.0
    nz = lum_post > eps
    nz_count = int(nz.sum())
    if nz_count < 5000:
        return rgb01, {"applied": False, "reason": "not enough non-zero pixels", "nz_pixels": nz_count}

    vals = lum_post[nz]
    lo = float(np.percentile(vals, low_pct))
    hi = float(np.percentile(vals, high_pct))

    if hi <= lo + 1e-6:
        hi = lo + 0.02

    mask = (lum_post >= lo) & (lum_post <= hi)

    # exclude highly saturated pixels (avoid pure-blue sky / sensor bias spikes)
    maxc = np.max(rgb01, axis=2)
    minc = np.min(rgb01, axis=2)
    sat = (maxc - minc) / np.maximum(maxc, 1e-6)
    mask &= (sat < sat_max)

    mask_pixels = int(mask.sum())
    if mask_pixels < 5000:
        return rgb01, {
            "applied": False,
            "reason": "mask too small after nz+sat filtering",
            "mask_pixels": mask_pixels,
            "nz_pixels": nz_count,
            "lum_lo": lo,
            "lum_hi": hi,
            "sat_max": sat_max,
        }

    r = float(rgb01[..., 0][mask].mean())
    g = float(rgb01[..., 1][mask].mean())
    b = float(rgb01[..., 2][mask].mean())

    if g < 1e-4:
        return rgb01, {
            "applied": False,
            "reason": "g_mean too low in mask (mask not neutral)",
            "mask_pixels": mask_pixels,
            "r_mean": r,
            "g_mean": g,
            "b_mean": b,
        }

    r_gain = float(np.clip(g / max(r, 1e-6), min_gain, max_gain))
    b_gain = float(np.clip(g / max(b, 1e-6), min_gain, max_gain))

    out = rgb01.copy()
    out[..., 0] *= r_gain
    out[..., 2] *= b_gain
    out = np.clip(out, 0, 1)

    return out, {
        "applied": True,
        "mask_pixels": mask_pixels,
        "low_pct": low_pct,
        "high_pct": high_pct,
        "min_gain": min_gain,
        "max_gain": max_gain,
        "sat_max": sat_max,
        "r_mean": r,
        "g_mean": g,
        "b_mean": b,
        "r_gain": r_gain,
        "b_gain": b_gain,
        "lum_lo": lo,
        "lum_hi": hi,
    }


def reduce_blue_cast_luma_preserving(rgb01: np.ndarray, strength: float = 0.6) -> np.ndarray:
    """
    Reduce blue cast without needing neutral pixels.
    Preserves luminance (detail/contrast), adjusts chroma.
    strength: 0=no change, 1=strong correction
    """
    rgb01 = np.clip(rgb01.astype(np.float32), 0, 1)

    y = (
        0.2126 * rgb01[..., 0] +
        0.7152 * rgb01[..., 1] +
        0.0722 * rgb01[..., 2]
    )[..., None]

    c = rgb01 - y

    r_scale = 1.0
    g_scale = 1.0
    b_scale = 1.0 - 0.75 * strength

    c_scaled = c.copy()
    c_scaled[..., 0] *= r_scale
    c_scaled[..., 1] *= g_scale
    c_scaled[..., 2] *= b_scale

    out = y + c_scaled
    return np.clip(out, 0, 1)


def desaturate(rgb01: np.ndarray, amount: float = 0.15) -> np.ndarray:
    """amount: 0=no change, 1=full grayscale"""
    rgb01 = np.clip(rgb01.astype(np.float32), 0, 1)
    y = (
        0.2126 * rgb01[..., 0] +
        0.7152 * rgb01[..., 1] +
        0.0722 * rgb01[..., 2]
    )[..., None]
    out = (1.0 - amount) * rgb01 + amount * y
    return np.clip(out, 0, 1)


# ----------------------------
# Stretching (lum-driven + lum-only)
# ----------------------------

def stretch_luminance_only(
    lum01: np.ndarray,
    black_pct: float,
    white_pct: float,
    asinh_strength: float,
    gamma: float,
) -> tuple[np.ndarray, dict]:
    """
    Luminance-only stretch:
      1) bp/wp from lum01
      2) normalize lum
      3) asinh + gamma
      4) output grayscale RGB (Y replicated to 3 channels)
    """
    lum = np.clip(lum01.astype(np.float32), 0, 1)

    bp = float(np.percentile(lum, black_pct))
    wp = float(np.percentile(lum, white_pct))
    if wp <= bp + 1e-8:
        wp = bp + 1e-3

    y = (lum - bp) / (wp - bp + 1e-8)
    y = np.clip(y, 0, 1)

    s = float(asinh_strength)
    y = np.arcsinh(s * y) / np.arcsinh(s)

    g = float(gamma)
    if g != 1.0:
        y = np.clip(y, 0, 1) ** (1.0 / g)

    rgb = np.repeat(y[..., None], 3, axis=2)

    debug = {
        "black_pct": black_pct,
        "white_pct": white_pct,
        "black_point": bp,
        "white_point": wp,
        "asinh_strength": s,
        "gamma": g,
        "mode_note": "luminance_only_grayscale",
    }

    return (rgb * 255).astype(np.uint8), debug


def stretch_rgb_by_luminance(
    rgb01: np.ndarray,
    lum01: np.ndarray,
    black_pct: float,
    white_pct: float,
    asinh_strength: float,
    gamma: float,
    mode: str,
    apply_gray_world: bool = True,
    gw_low_pct: float = 30.0,
    gw_high_pct: float = 80.0,
    gw_min_gain: float = 0.80,
    gw_max_gain: float = 1.25,
    gw_sat_max: float = 0.35,
    blue_suppress_strength: float = 0.6,
    desat_amount: float = 0.0,
) -> tuple[np.ndarray, dict]:
    """
    Luminance-driven RGB stretch:
      1) bp/wp from lum01
      2) normalize rgb using same bp/wp for all channels
      3) asinh + gamma
      4) optional blue suppression (luma preserving)
      5) optional gray-world (midtone, clamped)
      6) optional desaturation

    Returns:
      (uint8 RGB image, debug info)
    """
    rgb = np.clip(rgb01.astype(np.float32), 0, None)
    lum = np.clip(lum01.astype(np.float32), 0, 1)

    bp = float(np.percentile(lum, black_pct))
    wp = float(np.percentile(lum, white_pct))
    if wp <= bp + 1e-8:
        wp = bp + 1e-3

    x = (rgb - bp) / (wp - bp + 1e-8)
    x = np.clip(x, 0, 1)

    s = float(asinh_strength)
    x = np.arcsinh(s * x) / np.arcsinh(s)

    g = float(gamma)
    if g != 1.0:
        x = np.clip(x, 0, 1) ** (1.0 / g)

    debug = {
        "black_pct": black_pct,
        "white_pct": white_pct,
        "black_point": bp,
        "white_point": wp,
        "asinh_strength": s,
        "gamma": g,
        "mode": mode,
        "blue_suppress": {"enabled": True, "strength": float(blue_suppress_strength)},
        "gray_world": {"applied": False, "reason": "not_run"},
        "desaturate": {"enabled": desat_amount > 0, "amount": float(desat_amount)},
    }

    # For ROOF_CLOSED, color is generally not reliable; keep chroma minimal.
    # Still allow the tuner to show you what happens—just default to stronger suppression + slight desat.
    x = reduce_blue_cast_luma_preserving(x, strength=float(blue_suppress_strength))

    if apply_gray_world:
        try:
            x2, gw_dbg = gray_world_midtones_clamped(
                x,
                low_pct=gw_low_pct,
                high_pct=gw_high_pct,
                min_gain=gw_min_gain,
                max_gain=gw_max_gain,
                sat_max=gw_sat_max,
            )
            x = x2
            debug["gray_world"] = gw_dbg
        except Exception as e:
            debug["gray_world"] = {
                "applied": False,
                "reason": f"exception: {type(e).__name__}: {e}",
            }
    else:
        debug["gray_world"] = {"applied": False, "reason": "disabled"}

    if desat_amount > 0:
        x = desaturate(x, amount=float(desat_amount))

    return (x * 255).astype(np.uint8), debug


# ----------------------------
# Contact sheet
# ----------------------------

def make_contact_sheet(images: list[np.ndarray], rows: int, cols: int, pad: int = 8) -> np.ndarray:
    assert len(images) == rows * cols
    h, w, c = images[0].shape
    sheet = np.zeros((rows * h + (rows + 1) * pad, cols * w + (cols + 1) * pad, c), dtype=np.uint8)

    y = pad
    idx = 0
    for r in range(rows):
        x = pad
        for cidx in range(cols):
            sheet[y:y + h, x:x + w] = images[idx]
            x += w + pad
            idx += 1
        y += h + pad

    return sheet


# ----------------------------
# Main
# ----------------------------

def main(lum_fits: str, color_fits: str, out_dir: str = "stretch_tuner_out"):
    outp = Path(out_dir)
    outp.mkdir(parents=True, exist_ok=True)

    lum = load_fits(lum_fits)
    color = load_fits(color_fits)

    rgb = to_hwc_rgb(color)
    rgb01 = normalize_if_uint(rgb)
    lum01 = normalize_luminance(lum)

    # classify mode once per run (for labeling + context in JSON)
    mode, mode_info = classify_mode(lum01)

    # Candidate grid
    black_pcts = [1.0, 2.0, 5.0]
    white_pcts = [99.5, 99.7, 99.9]
    asinh_strengths = [30, 80, 200]
    gamma = 1.05

    # Gray-world parameters
    apply_gray_world = True
    gw_low_pct = 30.0
    gw_high_pct = 80.0
    gw_min_gain = 0.80
    gw_max_gain = 1.25
    gw_sat_max = 0.35

    # Color handling knobs (defaults can be mode-dependent)
    # ROOF_CLOSED: stronger blue suppression and slight desat tends to look more neutral
    if mode == "ROOF_CLOSED":
        blue_suppress_strength = 0.85
        desat_amount = 0.20
        # you can also choose to disable gray-world here if you want:
        # apply_gray_world = False
    elif mode == "DAY":
        blue_suppress_strength = 0.25
        desat_amount = 0.00
    else:  # ROOF_OPEN
        blue_suppress_strength = 0.40
        desat_amount = 0.10

    recipes_rgb = []
    recipes_lum = []

    for s in asinh_strengths:
        # ---- RGB sheet ----
        tiles_rgb = []
        tile_debugs_rgb = []

        for bp in black_pcts:
            for wp in white_pcts:
                img_u8, dbg = stretch_rgb_by_luminance(
                    rgb01=rgb01,
                    lum01=lum01,
                    black_pct=bp,
                    white_pct=wp,
                    asinh_strength=s,
                    gamma=gamma,
                    mode=mode,
                    apply_gray_world=apply_gray_world,
                    gw_low_pct=gw_low_pct,
                    gw_high_pct=gw_high_pct,
                    gw_min_gain=gw_min_gain,
                    gw_max_gain=gw_max_gain,
                    gw_sat_max=gw_sat_max,
                    blue_suppress_strength=blue_suppress_strength,
                    desat_amount=desat_amount,
                )
                tiles_rgb.append(img_u8)
                tile_debugs_rgb.append(dbg)

        sheet_rgb = make_contact_sheet(tiles_rgb, rows=3, cols=3, pad=8)
        iio.imwrite(outp / f"contact_sheet_rgb_asinh_{s}_{mode}.png", sheet_rgb)

        recipes_rgb.append({
            "asinh_strength": float(s),
            "gamma": float(gamma),
            "mode": mode,
            "grid_notes": "3x3: rows=black_pct [1,2,5], cols=white_pct [99.5,99.7,99.9]",
            "gray_world": {
                "enabled": apply_gray_world,
                "low_pct": gw_low_pct,
                "high_pct": gw_high_pct,
                "min_gain": gw_min_gain,
                "max_gain": gw_max_gain,
                "sat_max": gw_sat_max,
            },
            "blue_suppress": {
                "enabled": True,
                "strength": float(blue_suppress_strength),
            },
            "desaturate": {
                "enabled": desat_amount > 0,
                "amount": float(desat_amount),
            },
            "tiles": tile_debugs_rgb
        })

        # ---- Luminance-only sheet ----
        tiles_lum = []
        tile_debugs_lum = []

        for bp in black_pcts:
            for wp in white_pcts:
                img_u8, dbg = stretch_luminance_only(
                    lum01=lum01,
                    black_pct=bp,
                    white_pct=wp,
                    asinh_strength=s,
                    gamma=gamma,
                )
                # add mode into lum tile debug for parity
                dbg["mode"] = mode
                tiles_lum.append(img_u8)
                tile_debugs_lum.append(dbg)

        sheet_lum = make_contact_sheet(tiles_lum, rows=3, cols=3, pad=8)
        iio.imwrite(outp / f"contact_sheet_lum_asinh_{s}_{mode}.png", sheet_lum)

        recipes_lum.append({
            "asinh_strength": float(s),
            "gamma": float(gamma),
            "mode": mode,
            "grid_notes": "3x3: rows=black_pct [1,2,5], cols=white_pct [99.5,99.7,99.9]",
            "tiles": tile_debugs_lum
        })

    with open(outp / "recipes.json", "w", encoding="utf-8") as f:
        json.dump({
            "lum_fits": str(lum_fits),
            "color_fits": str(color_fits),
            "mode": mode,
            "mode_info": mode_info,
            "notes": [
                "Each contact sheet is a 3x3 grid:",
                "rows=black_pct [1,2,5], cols=white_pct [99.5,99.7,99.9].",
                "RGB sheets use luminance-derived bp/wp, then asinh+gamma, then blue suppression, then optional gray-world, then optional desaturation.",
                "LUM sheets are luminance-only grayscale (best for roof-closed / extremely dark scenes).",
            ],
            "recipes_rgb_by_asinh": recipes_rgb,
            "recipes_lum_by_asinh": recipes_lum,
        }, f, indent=2)

    print(f"Saved outputs to: {outp.resolve()}")
    print(f"Detected mode: {mode} ({mode_info.get('reason','')})")
    print("Review files:")
    for s in asinh_strengths:
        print(f"  - contact_sheet_rgb_asinh_{s}_{mode}.png")
        print(f"  - contact_sheet_lum_asinh_{s}_{mode}.png")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python stretch_tuner.py <lum_fits> <color_fits> [out_dir]")
    else:
        main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "stretch_tuner_out")
