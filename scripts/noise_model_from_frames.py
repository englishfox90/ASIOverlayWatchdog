#!/usr/bin/env python3
# -*- coding: utf-8 -*-

r"""
noise_model_from_frames.py

Build a "static/background noise profile" from a pile of FITS frames when you
can't capture true darks (no cover). Works best with many ROOF_CLOSED frames.

Idea:
- OTA moves -> scene content moves in sensor coordinates
- sensor fixed-pattern noise stays in the same pixels
- per-pixel LOW percentile across many frames tends to reject moving bright content
  and retain sensor-fixed background/pattern.

Outputs:
- model_<name>.fits : background/static model in the SAME units as input
- sigma_<name>.fits : per-pixel residual stddev (optional; helps tune denoise)
- model_stats.json  : settings + basic stats

Supports:
- Mono luminance frames: (H,W)
- 3-channel frames: (3,H,W) or (H,W,3)

Examples (PowerShell):

# Luminance model (roof closed)
& "c:\Astrophotography\PFRSentinel\venv\Scripts\python.exe" `
  "c:\Astrophotography\PFRSentinel\scripts\noise_model_from_frames.py" `
  --in_dir "C:\Users\Paul Fox-Reeks\AppData\Local\PFRSentinel\raw_debug" `
  --glob "lum_*.fits" `
  --percentile 10 `
  --median_passes 2 `
  --out_dir "noise_model_out" `
  --name "lum_roof_closed"

# Raw RGB model
& "c:\Astrophotography\PFRSentinel\venv\Scripts\python.exe" `
  "c:\Astrophotography\PFRSentinel\scripts\noise_model_from_frames.py" `
  --in_dir "C:\Users\Paul Fox-Reeks\AppData\Local\PFRSentinel\raw_debug" `
  --glob "raw_*.fits" `
  --percentile 10 `
  --median_passes 1 `
  --out_dir "noise_model_out" `
  --name "raw_roof_closed" `
  --compute_sigma
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Tuple, List

import numpy as np
from astropy.io import fits


# ----------------------------
# IO helpers
# ----------------------------

def load_fits(path: str) -> np.ndarray:
    return np.asarray(fits.getdata(path))


def is_rgb_shape(arr: np.ndarray) -> bool:
    return arr.ndim == 3 and (arr.shape[0] == 3 or arr.shape[2] == 3)


def to_c_hw(arr: np.ndarray) -> Tuple[np.ndarray, str]:
    """
    Return array as (C,H,W) for internal processing.
    For mono: returns (1,H,W)
    For RGB: returns (3,H,W)
    Also returns a string describing original layout so we can write similarly if desired.
    """
    if arr.ndim == 2:
        return arr[None, ...], "mono"
    if arr.ndim == 3 and arr.shape[0] == 3:
        return arr, "chw"
    if arr.ndim == 3 and arr.shape[2] == 3:
        return np.transpose(arr, (2, 0, 1)), "hwc"
    raise ValueError(f"Unsupported FITS data shape: {arr.shape}. Expected (H,W), (3,H,W) or (H,W,3).")


def from_c_hw(arr_chw: np.ndarray, layout: str) -> np.ndarray:
    """
    Convert (C,H,W) back to original layout.
    """
    if layout == "mono":
        return arr_chw[0]
    if layout == "chw":
        return arr_chw
    if layout == "hwc":
        return np.transpose(arr_chw, (1, 2, 0))
    raise ValueError(f"Unknown layout: {layout}")


# ----------------------------
# Simple median 3x3 smoothing (no scipy)
# ----------------------------

def median3x3_single(m: np.ndarray) -> np.ndarray:
    """
    3x3 median filter for a single 2D plane.
    Uses reflect padding. Fast enough for 3552^2 with a couple passes.
    """
    m = m.astype(np.float32)
    p = np.pad(m, 1, mode="reflect")
    neigh = [
        p[0:-2, 0:-2], p[0:-2, 1:-1], p[0:-2, 2:],
        p[1:-1, 0:-2], p[1:-1, 1:-1], p[1:-1, 2:],
        p[2:,   0:-2], p[2:,   1:-1], p[2:,   2:],
    ]
    return np.median(np.stack(neigh, axis=0), axis=0).astype(np.float32)


def median_passes_chw(arr_chw: np.ndarray, passes: int) -> np.ndarray:
    if passes <= 0:
        return arr_chw
    out = arr_chw.astype(np.float32, copy=True)
    for _ in range(int(passes)):
        for c in range(out.shape[0]):
            out[c] = median3x3_single(out[c])
    return out


# ----------------------------
# Model builder (tile-based)
# ----------------------------

def build_percentile_model(
    files: List[Path],
    percentile: float,
    tile: int,
    compute_sigma: bool,
    median_passes: int,
) -> Tuple[np.ndarray, np.ndarray | None, dict]:
    """
    Returns:
      model_chw: (C,H,W) float32 in original units
      sigma_chw: (C,H,W) float32 or None
      info: dict
    """
    if len(files) < 5:
        raise ValueError("Need at least ~5 frames for a meaningful percentile model (more is better).")

    # Probe first frame for shape/layout/dtype
    first = load_fits(str(files[0]))
    first_chw, layout = to_c_hw(first)

    C, H, W = first_chw.shape
    dtype0 = first.dtype

    model = np.zeros((C, H, W), dtype=np.float32)
    sigma = np.zeros((C, H, W), dtype=np.float32) if compute_sigma else None

    # Stats we'll compute
    info = {
        "n_files": len(files),
        "percentile": float(percentile),
        "tile": int(tile),
        "layout": layout,
        "dtype_first": str(dtype0),
        "shape_chw": [int(C), int(H), int(W)],
        "median_passes": int(median_passes),
        "compute_sigma": bool(compute_sigma),
    }

    # Process channel-by-channel, tile-by-tile
    for c in range(C):
        for y0 in range(0, H, tile):
            y1 = min(H, y0 + tile)
            for x0 in range(0, W, tile):
                x1 = min(W, x0 + tile)

                # stack: (N, th, tw)
                th, tw = (y1 - y0), (x1 - x0)
                stack = np.empty((len(files), th, tw), dtype=np.float32)

                # Load each file and slice tile
                for i, fp in enumerate(files):
                    arr = load_fits(str(fp))
                    arr_chw, _ = to_c_hw(arr)

                    plane = arr_chw[c].astype(np.float32)
                    stack[i] = plane[y0:y1, x0:x1]

                # Per-pixel low percentile model
                model_tile = np.percentile(stack, percentile, axis=0).astype(np.float32)
                model[c, y0:y1, x0:x1] = model_tile

                # Optional sigma (stddev of residuals around the model)
                if compute_sigma:
                    resid = stack - model_tile[None, :, :]
                    sigma_tile = np.std(resid, axis=0).astype(np.float32)
                    sigma[c, y0:y1, x0:x1] = sigma_tile

    # Optional smoothing (helps remove “ghosts” from moving highlights)
    if median_passes > 0:
        model = median_passes_chw(model, passes=median_passes)
        if compute_sigma and sigma is not None:
            sigma = median_passes_chw(sigma, passes=1)  # light smoothing only

    # Final stats
    info["model_stats_per_channel"] = []
    for c in range(C):
        ch = model[c]
        info["model_stats_per_channel"].append({
            "c": int(c),
            "min": float(np.min(ch)),
            "p1": float(np.percentile(ch, 1)),
            "p50": float(np.percentile(ch, 50)),
            "p99": float(np.percentile(ch, 99)),
            "max": float(np.max(ch)),
            "mean": float(np.mean(ch)),
            "std": float(np.std(ch)),
        })

    if compute_sigma and sigma is not None:
        info["sigma_stats_per_channel"] = []
        for c in range(C):
            ch = sigma[c]
            info["sigma_stats_per_channel"].append({
                "c": int(c),
                "min": float(np.min(ch)),
                "p50": float(np.percentile(ch, 50)),
                "p99": float(np.percentile(ch, 99)),
                "max": float(np.max(ch)),
                "mean": float(np.mean(ch)),
                "std": float(np.std(ch)),
            })

    return model, sigma, info


# ----------------------------
# Main
# ----------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in_dir", required=True, help="Folder containing FITS frames")
    ap.add_argument("--glob", default="*.fits", help='Glob pattern, e.g. "lum_*.fits" or "raw_*.fits"')
    ap.add_argument("--out_dir", default="noise_model_out")
    ap.add_argument("--name", default="model")

    ap.add_argument("--percentile", type=float, default=10.0, help="Low percentile per-pixel (5..20 typical)")
    ap.add_argument("--tile", type=int, default=512, help="Tile size (memory control). 256/512/768 typical.")
    ap.add_argument("--median_passes", type=int, default=1, help="3x3 median smoothing passes for the model")

    ap.add_argument("--compute_sigma", action="store_true", help="Also output per-pixel residual sigma map")

    args = ap.parse_args()

    in_dir = Path(args.in_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(in_dir.glob(args.glob))
    if not files:
        raise SystemExit(f"No files matched {in_dir} / {args.glob}")

    print(f"Found {len(files)} frames")
    print(f"Building percentile model: p={args.percentile} tile={args.tile} median_passes={args.median_passes}")

    model_chw, sigma_chw, info = build_percentile_model(
        files=files,
        percentile=args.percentile,
        tile=args.tile,
        compute_sigma=args.compute_sigma,
        median_passes=args.median_passes,
    )

    # Write model + sigma in a consistent layout (CHW for RGB, 2D for mono)
    # (Keeping CHW is often easiest for later subtraction pipelines.)
    model_out = out_dir / f"model_{args.name}.fits"
    fits.writeto(model_out, from_c_hw(model_chw, info["layout"]), overwrite=True)

    if args.compute_sigma and sigma_chw is not None:
        sigma_out = out_dir / f"sigma_{args.name}.fits"
        fits.writeto(sigma_out, from_c_hw(sigma_chw, info["layout"]), overwrite=True)
        info["sigma_path"] = str(sigma_out)

    info["model_path"] = str(model_out)
    info["in_dir"] = str(in_dir)
    info["glob"] = args.glob
    info["name"] = args.name

    stats_out = out_dir / f"model_stats_{args.name}.json"
    with open(stats_out, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)

    print(f"Saved model: {model_out}")
    print(f"Saved stats: {stats_out}")
    if args.compute_sigma:
        print(f"Saved sigma: {out_dir / f'sigma_{args.name}.fits'}")
    print("Next step: subtract this model from new frames BEFORE stretching/colorizing.")


if __name__ == "__main__":
    main()
