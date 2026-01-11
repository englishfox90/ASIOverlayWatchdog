r"""
colorize_from_lum.py - PFRSentinel stretch/color tuning harness (v2.0)

Refactored experiment harness with:
- Modular architecture (colorize/ package)
- Batch processing mode
- Mode-aware auto parameters
- Quality metrics for recipe evaluation
- Comprehensive debug output

Single-file mode:
  python colorize_from_lum.py lum.fits raw.fits --out_dir out

Batch mode:
  python colorize_from_lum.py --batch_dir /path/to/fits --out_dir out

Auto mode (mode-aware defaults):
  python colorize_from_lum.py lum.fits raw.fits --auto 1

See colorize/ package for implementation details.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

# Import from colorize package
from colorize import (
    load_fits, to_hwc_rgb, normalize_if_int, save_output_image,
    estimate_bias_sigma_from_corners, estimate_rgb_bias_from_corners,
    classify_mode_from_lum, compute_quality_metrics,
    stretch_mono, stretch_rgb_using_lum_points, inject_chroma_into_luminance,
    hot_pixel_dab_lum, shadow_luma_denoise, blur_chroma_only,
    blue_suppress_chroma, desaturate_global, midtone_white_balance,
    compute_effective_params, MODE_DEFAULTS,
)
from colorize.recipes import apply_bp_guardrails


def discover_pairs(batch_dir: Path) -> list[tuple[Path, Path, str]]:
    """
    Discover matching lum_*.fits and raw_*.fits pairs by timestamp/key.

    Returns list of (lum_path, raw_path, key) tuples.
    """
    lum_files = sorted(batch_dir.glob("lum_*.fits"))
    raw_files = {f.stem.replace("raw_", ""): f for f in batch_dir.glob("raw_*.fits")}

    pairs = []
    for lum_path in lum_files:
        key = lum_path.stem.replace("lum_", "")
        if key in raw_files:
            pairs.append((lum_path, raw_files[key], key))

    return pairs


def process_single(
    lum_path: Path,
    raw_path: Path,
    out_dir: Path,
    args: argparse.Namespace,
    *,
    key: str | None = None,
    organize_by_mode: bool = False,
) -> dict[str, Any]:
    """
    Process a single lum/raw pair and return debug/metrics dict.
    """
    t_start = time.perf_counter()

    # Load and normalize
    lum = load_fits(str(lum_path))
    col = load_fits(str(raw_path))

    rgb = to_hwc_rgb(col)
    rgb01, rgb_norm_dbg = normalize_if_int(rgb)
    lum01, lum_norm_dbg = normalize_if_int(lum)

    t_load = time.perf_counter()

    # ==================== MEASUREMENT STAGE ====================

    # Corner overscan stats
    bias, sigma, corner_dbg = estimate_bias_sigma_from_corners(
        lum01, roi=args.corner_roi, margin=args.corner_margin
    )

    # Mode classification BEFORE bias subtraction (so corner vs center comparison works)
    mode_info = classify_mode_from_lum(
        lum01,
        corner_roi=args.corner_roi,
        corner_margin=args.corner_margin,
        center_frac=args.center_frac,
        day_p50=args.day_p50,
        day_p99=args.day_p99,
        closed_ratio=args.closed_ratio,
        closed_delta=args.closed_delta,
    )
    mode = mode_info["mode"]
    
    # Refine mode for very dark frames
    if mode == "NIGHT_ROOF_CLOSED" and mode_info.get("stats", {}).get("very_dark_frame", False):
        mode = "NIGHT_ROOF_CLOSED_VERY_DARK"

    # Bias subtract LUM (always, after classification)
    lum01_corr = np.clip(lum01 - bias, 0, 1)

    # RGB corner bias (optional)
    bias_rgb = None
    rgb_corner_dbg = None
    if args.rgb_bias_subtract:
        bias_rgb, rgb_corner_dbg = estimate_rgb_bias_from_corners(
            rgb01, roi=args.corner_roi, margin=args.corner_margin
        )

    t_measure = time.perf_counter()

    # ==================== EFFECTIVE PARAMETERS ====================

    # Collect user-specified (non-default) values
    requested = {}
    for param in [
        "black_pct", "white_pct", "asinh", "gamma",
        "color_strength", "chroma_clip", "blue_suppress", "blue_floor", "desaturate",
        "corner_sigma_bp", "hp_dab", "hp_k", "hp_max_luma",
        "shadow_denoise", "shadow_start", "shadow_end", "chroma_blur",
        "midtone_wb", "midtone_wb_strength",
    ]:
        val = getattr(args, param, None)
        if val is not None:
            requested[param] = val

    # Compute effective parameters
    eff_result = compute_effective_params(
        mode=mode,
        requested=requested,
        auto_mode=bool(args.auto),
    )
    eff = eff_result["effective"]

    t_params = time.perf_counter()

    # ==================== TRANSFORM STAGE ====================

    # RGB bias subtract for stretch input
    if eff.get("rgb_bias_subtract", True) and bias_rgb is not None:
        rgb01_for_stretch = np.clip(rgb01 - bias_rgb[None, None, :], 0, 1)
    else:
        rgb01_for_stretch = rgb01

    # Hot pixel dab on LUM (pre-stretch)
    hp_dbg = None
    if eff.get("hp_dab", False):
        lum01_corr, hp_dbg = hot_pixel_dab_lum(
            lum01_corr,
            sigma=sigma,
            k=float(eff.get("hp_k", 11.0)),
            max_luma=float(eff.get("hp_max_luma", 0.25)),
        )

    # Compute override_bp with guardrails
    p10_lum = float(np.percentile(lum01_corr, 10))
    wp_est = float(np.percentile(lum01_corr, eff.get("white_pct", 99.9)))

    override_bp, bp_guard_dbg = apply_bp_guardrails(
        override_bp=None,
        sigma=sigma,
        corner_sigma_bp=float(eff.get("corner_sigma_bp", 0)),
        wp=wp_est,
        p10=p10_lum,
    )

    # Stretch LUM
    lum_stretched01, lum_stretch_dbg = stretch_mono(
        mono01=lum01_corr,
        black_pct=float(eff.get("black_pct", 5.0)),
        white_pct=float(eff.get("white_pct", 99.9)),
        asinh_strength=float(eff.get("asinh", 30.0)),
        gamma=float(eff.get("gamma", 1.05)),
        override_bp=override_bp,
    )

    bp = float(lum_stretch_dbg["black_point"])
    wp = float(lum_stretch_dbg["white_point"])

    # Shadow luma denoise (post-stretch)
    if eff.get("shadow_denoise", 0) > 0:
        lum_stretched01 = shadow_luma_denoise(
            lum_stretched01,
            amount=float(eff["shadow_denoise"]),
            shadow_start=float(eff.get("shadow_start", 0.02)),
            shadow_end=float(eff.get("shadow_end", 0.14)),
        )

    # Stretch RGB using same bp/wp
    rgb_stretched01 = stretch_rgb_using_lum_points(
        rgb01=rgb01_for_stretch,
        bp=bp,
        wp=wp,
        asinh_strength=float(eff.get("asinh", 30.0)),
        gamma=float(eff.get("gamma", 1.05)),
    )

    # Blue suppression
    if float(eff.get("blue_suppress", 0)) > 0:
        rgb_stretched01 = blue_suppress_chroma(
            rgb_stretched01,
            strength=float(eff["blue_suppress"]),
            blue_bias_floor=float(eff.get("blue_floor", 0.02)),
        )

    # Midtone white balance (for day modes)
    wb_dbg = None
    if eff.get("midtone_wb", False):
        rgb_stretched01, wb_dbg = midtone_white_balance(
            rgb_stretched01,
            strength=float(eff.get("midtone_wb_strength", 0.6)),
        )

    # Colorize (inject chroma into stretched lum)
    out01 = inject_chroma_into_luminance(
        lum_stretched01=lum_stretched01,
        rgb_stretched01=rgb_stretched01,
        color_strength=float(eff.get("color_strength", 1.2)),
        chroma_clip=float(eff.get("chroma_clip", 0.55)),
    )

    # Chroma blur (post-colorize)
    if int(eff.get("chroma_blur", 0)) > 0:
        out01 = blur_chroma_only(out01, radius=int(eff["chroma_blur"]))

    # Global desaturation
    if float(eff.get("desaturate", 0)) > 0:
        out01 = desaturate_global(out01, amount=float(eff["desaturate"]))

    t_transform = time.perf_counter()

    # ==================== OUTPUT ====================

    # Determine output path
    if key is None:
        key = lum_path.stem.replace("lum_", "")

    if organize_by_mode:
        mode_dir = out_dir / mode
        out_path = mode_dir / f"{key}.png"
    else:
        out_name = args.out_name if args.out_name else f"{key}.png"
        out_path = out_dir / out_name

    save_dbg = save_output_image(out01, out_path)

    # Quality metrics
    quality = compute_quality_metrics(
        out01, corner_roi=args.corner_roi, corner_margin=args.corner_margin
    )

    t_end = time.perf_counter()

    # ==================== DEBUG OUTPUT ====================

    debug = {
        "key": key,
        "inputs": {"lum_fits": str(lum_path), "color_fits": str(raw_path)},
        "normalize": {"lum": lum_norm_dbg, "rgb": rgb_norm_dbg},
        "mode_info": mode_info,
        "corner_overscan": corner_dbg,
        "rgb_corner_bias": rgb_corner_dbg,
        "bias_subtract": {
            "lum_bias": float(bias),
            "lum_sigma_mad": float(sigma),
        },
        "bias_subtract_rgb": {
            "applied": bias_rgb is not None,
            "bias_rgb": [float(x) for x in bias_rgb] if bias_rgb is not None else None,
        },
        "effective_params": eff_result,
        "bp_guardrails": bp_guard_dbg,
        "hot_pixel_dab": hp_dbg,
        "stretch": lum_stretch_dbg,
        "midtone_wb": wb_dbg,
        "quality_metrics": quality,
        "output": save_dbg,
        "timing": {
            "load_sec": round(t_load - t_start, 4),
            "measure_sec": round(t_measure - t_load, 4),
            "params_sec": round(t_params - t_measure, 4),
            "transform_sec": round(t_transform - t_params, 4),
            "total_sec": round(t_end - t_start, 4),
        },
    }

    # Write per-image debug JSON
    debug_path = out_path.with_suffix(".json")
    with open(debug_path, "w", encoding="utf-8") as f:
        json.dump(debug, f, indent=2)

    return debug


def run_batch(batch_dir: Path, out_dir: Path, args: argparse.Namespace) -> None:
    """Run batch processing on all discovered pairs."""
    pairs = discover_pairs(batch_dir)

    if not pairs:
        print(f"No matching lum_*/raw_* pairs found in {batch_dir}")
        return

    print(f"Found {len(pairs)} pairs to process")

    results = []
    for lum_path, raw_path, key in pairs:
        print(f"  Processing: {key} ...", end=" ", flush=True)
        try:
            debug = process_single(
                lum_path, raw_path, out_dir, args,
                key=key, organize_by_mode=True
            )
            results.append(debug)
            print(f"OK ({debug['mode_info']['mode']})")
        except Exception as e:
            print(f"FAILED: {e}")
            results.append({
                "key": key,
                "error": str(e),
                "inputs": {"lum_fits": str(lum_path), "color_fits": str(raw_path)},
            })

    # Write summary CSV
    write_summary_csv(results, out_dir / "summary.csv")
    print(f"\nSummary written to {out_dir / 'summary.csv'}")


def write_summary_csv(results: list[dict], csv_path: Path) -> None:
    """Write summary CSV with key metrics from all runs."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "key", "mode", "error",
        # Params
        "black_pct", "white_pct", "asinh", "gamma",
        "color_strength", "corner_sigma_bp", "hp_dab", "shadow_denoise", "chroma_blur",
        # Quality
        "luma_mean", "luma_p50", "saturation_frac", "mean_abs_chroma",
        "detail_proxy", "corner_stddev",
        # Timing
        "total_sec",
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        for r in results:
            row = {"key": r.get("key", ""), "error": r.get("error", "")}

            if "mode_info" in r:
                row["mode"] = r["mode_info"]["mode"]

            if "effective_params" in r:
                eff = r["effective_params"].get("effective", {})
                row.update({
                    "black_pct": eff.get("black_pct"),
                    "white_pct": eff.get("white_pct"),
                    "asinh": eff.get("asinh"),
                    "gamma": eff.get("gamma"),
                    "color_strength": eff.get("color_strength"),
                    "corner_sigma_bp": eff.get("corner_sigma_bp"),
                    "hp_dab": eff.get("hp_dab"),
                    "shadow_denoise": eff.get("shadow_denoise"),
                    "chroma_blur": eff.get("chroma_blur"),
                })

            if "quality_metrics" in r:
                q = r["quality_metrics"]
                row.update({
                    "luma_mean": round(q.get("luma_mean", 0), 4),
                    "luma_p50": round(q.get("luma_p50", 0), 4),
                    "saturation_frac": round(q.get("saturation_frac", 0), 4),
                    "mean_abs_chroma": round(q.get("mean_abs_chroma", 0), 4),
                    "detail_proxy": round(q.get("detail_proxy", 0), 6),
                    "corner_stddev": round(q.get("corner_stddev", 0), 6),
                })

            if "timing" in r:
                row["total_sec"] = r["timing"].get("total_sec")

            writer.writerow(row)


def main():
    ap = argparse.ArgumentParser(
        description="PFRSentinel colorize harness v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Input modes
    ap.add_argument("lum_fits", nargs="?", help="Path to lum_*.fits (single mode)")
    ap.add_argument("color_fits", nargs="?", help="Path to raw_*.fits (single mode)")
    ap.add_argument("--batch_dir", type=str, help="Directory for batch processing")

    # Output
    ap.add_argument("--out_dir", default="colorize_out")
    ap.add_argument("--out_name", default=None, help="Output filename (single mode)")

    # Auto mode
    ap.add_argument("--auto", type=int, default=1, help="1=mode-aware auto params, 0=manual")

    # Stretch params
    ap.add_argument("--black_pct", type=float, default=None)
    ap.add_argument("--white_pct", type=float, default=None)
    ap.add_argument("--asinh", type=float, default=None)
    ap.add_argument("--gamma", type=float, default=None)

    # Color controls
    ap.add_argument("--color_strength", type=float, default=None)
    ap.add_argument("--chroma_clip", type=float, default=None)
    ap.add_argument("--blue_suppress", type=float, default=None)
    ap.add_argument("--blue_floor", type=float, default=None)
    ap.add_argument("--desaturate", type=float, default=None)
    ap.add_argument("--rgb_bias_subtract", type=int, default=1)

    # Corner ROI / mode classification
    ap.add_argument("--corner_roi", type=int, default=50)
    ap.add_argument("--corner_margin", type=int, default=5)
    ap.add_argument("--center_frac", type=float, default=0.25)
    ap.add_argument("--day_p50", type=float, default=0.10)
    ap.add_argument("--day_p99", type=float, default=0.35)
    ap.add_argument("--closed_ratio", type=float, default=0.55)
    ap.add_argument("--closed_delta", type=float, default=0.02)

    # Noise floor gate
    ap.add_argument("--corner_sigma_bp", type=float, default=None)

    # Hot pixel dab
    ap.add_argument("--hp_dab", type=int, default=None)
    ap.add_argument("--hp_k", type=float, default=None)
    ap.add_argument("--hp_max_luma", type=float, default=None)

    # Shadow denoise
    ap.add_argument("--shadow_denoise", type=float, default=None)
    ap.add_argument("--shadow_start", type=float, default=None)
    ap.add_argument("--shadow_end", type=float, default=None)

    # Chroma blur
    ap.add_argument("--chroma_blur", type=int, default=None)

    # Midtone white balance
    ap.add_argument("--midtone_wb", type=int, default=None)
    ap.add_argument("--midtone_wb_strength", type=float, default=None)

    args = ap.parse_args()

    # Convert int flags to bool where needed
    args.rgb_bias_subtract = bool(args.rgb_bias_subtract)
    if args.hp_dab is not None:
        args.hp_dab = bool(args.hp_dab)
    if args.midtone_wb is not None:
        args.midtone_wb = bool(args.midtone_wb)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Batch mode
    if args.batch_dir:
        batch_dir = Path(args.batch_dir)
        if not batch_dir.is_dir():
            print(f"Error: batch_dir not found: {batch_dir}")
            return
        run_batch(batch_dir, out_dir, args)
        return

    # Single file mode
    if not args.lum_fits or not args.color_fits:
        ap.print_help()
        print("\nError: Provide lum_fits and color_fits, or use --batch_dir")
        return

    lum_path = Path(args.lum_fits)
    raw_path = Path(args.color_fits)

    if not lum_path.exists():
        print(f"Error: lum_fits not found: {lum_path}")
        return
    if not raw_path.exists():
        print(f"Error: color_fits not found: {raw_path}")
        return

    debug = process_single(lum_path, raw_path, out_dir, args)

    # Print summary
    mode = debug["mode_info"]["mode"]
    reason = debug["mode_info"]["reason"]
    bias = debug["bias_subtract"]["lum_bias"]
    sigma = debug["bias_subtract"]["lum_sigma_mad"]
    q = debug["quality_metrics"]

    print(f"Saved: {debug['output']['path']}")
    print(f"Mode: {mode} ({reason})")
    print(f"Corner bias: {bias:.6f}  sigma(MAD): {sigma:.6f}")
    print(f"Quality: luma_mean={q['luma_mean']:.3f} chroma={q['mean_abs_chroma']:.4f} "
          f"detail={q['detail_proxy']:.5f} corner_noise={q['corner_stddev']:.5f}")
    print(f"Time: {debug['timing']['total_sec']:.2f}s")


if __name__ == "__main__":
    main()
