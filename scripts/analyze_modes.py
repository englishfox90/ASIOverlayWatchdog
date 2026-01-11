r"""
analyze_modes.py - Batch mode classification analysis for threshold tuning

This script analyzes FITS files to extract mode classification statistics
WITHOUT processing them. Use this to understand mode detection values and
tune classification thresholds.

Usage:
  python analyze_modes.py --batch_dir /path/to/fits --out_csv analysis.csv

Output CSV contains:
  - key: timestamp from filename
  - All mode classification stats (p1, p10, p50, p90, p99, corner_med, center_med, etc.)
  - Classification result (mode, is_day, is_closed, very_dark_frame)
  - Threshold values used

This helps identify misclassified images and tune thresholds.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

from colorize import load_fits, to_hwc_rgb, normalize_if_int
from colorize.measurement import estimate_bias_sigma_from_corners, classify_mode_from_lum


def analyze_single(
    lum_path: Path,
    *,
    corner_roi: int = 50,
    corner_margin: int = 5,
    center_frac: float = 0.25,
    day_p50: float = 0.10,
    day_p99: float = 0.35,
    closed_ratio: float = 0.55,
    closed_delta: float = 0.02,
) -> dict:
    """Analyze a single lum file for mode classification stats."""
    key = lum_path.stem.replace("lum_", "")

    try:
        lum = load_fits(str(lum_path))
        lum01, _ = normalize_if_int(lum)

        # Get corner bias/sigma
        bias, sigma, corner_dbg = estimate_bias_sigma_from_corners(
            lum01, roi=corner_roi, margin=corner_margin
        )

        # Classify mode (before bias subtraction, as per current logic)
        mode_info = classify_mode_from_lum(
            lum01,
            corner_roi=corner_roi,
            corner_margin=corner_margin,
            center_frac=center_frac,
            day_p50=day_p50,
            day_p99=day_p99,
            closed_ratio=closed_ratio,
            closed_delta=closed_delta,
        )

        stats = mode_info["stats"]

        return {
            "key": key,
            "file": str(lum_path),
            "error": "",
            # Mode result
            "mode": mode_info["mode"],
            "reason": mode_info["reason"],
            "is_day": stats["is_day"],
            "is_closed": stats["is_closed"],
            "very_dark_frame": stats.get("very_dark_frame", False),
            # Global brightness stats
            "p1": stats["p1"],
            "p10": stats["p10"],
            "p50": stats["p50"],
            "p90": stats["p90"],
            "p99": stats["p99"],
            "dynamic_range": stats["dynamic_range_p99_p1"],
            # Corner stats
            "corner_med": stats["corner_med"],
            "corner_p90": stats["corner_p90"],
            "corner_bias": bias,
            "corner_sigma": sigma,
            # Center stats
            "center_med": stats["center_med"],
            "center_p90": stats["center_p90"],
            # Ratio/delta (key for closed detection)
            "corner_center_ratio": stats["corner_to_center_ratio"],
            "center_minus_corner": stats["center_minus_corner"],
            # Thresholds used
            "thresh_day_p50": day_p50,
            "thresh_day_p99": day_p99,
            "thresh_closed_ratio": closed_ratio,
            "thresh_closed_delta": closed_delta,
        }

    except Exception as e:
        return {
            "key": key,
            "file": str(lum_path),
            "error": str(e),
            "mode": "ERROR",
        }


def discover_lum_files(batch_dir: Path) -> list[Path]:
    """Find all lum_*.fits files in directory."""
    return sorted(batch_dir.glob("lum_*.fits"))


def run_analysis(
    batch_dir: Path,
    out_csv: Path,
    **kwargs,
) -> list[dict]:
    """Analyze all lum files in directory and write CSV."""
    lum_files = discover_lum_files(batch_dir)

    if not lum_files:
        print(f"No lum_*.fits files found in {batch_dir}")
        return []

    print(f"Analyzing {len(lum_files)} files...")

    results = []
    for lum_path in lum_files:
        result = analyze_single(lum_path, **kwargs)
        results.append(result)
        mode = result.get("mode", "ERROR")
        ratio = result.get("corner_center_ratio", 0)
        delta = result.get("center_minus_corner", 0)
        print(f"  {result['key']}: {mode:20s} ratio={ratio:.4f} delta={delta:.5f}")

    # Write CSV
    write_analysis_csv(results, out_csv)
    print(f"\nAnalysis written to {out_csv}")

    # Print summary
    print_summary(results)

    return results


def write_analysis_csv(results: list[dict], csv_path: Path) -> None:
    """Write analysis results to CSV."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "key", "mode", "is_day", "is_closed", "very_dark_frame",
        "p1", "p10", "p50", "p90", "p99", "dynamic_range",
        "corner_med", "corner_p90", "corner_bias", "corner_sigma",
        "center_med", "center_p90",
        "corner_center_ratio", "center_minus_corner",
        "reason", "error", "file",
        "thresh_day_p50", "thresh_day_p99", "thresh_closed_ratio", "thresh_closed_delta",
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            # Round floats for readability
            row = {}
            for k, v in r.items():
                if isinstance(v, float):
                    row[k] = round(v, 6)
                else:
                    row[k] = v
            writer.writerow(row)


def print_summary(results: list[dict]) -> None:
    """Print summary statistics for threshold tuning."""
    # Group by mode
    modes = {}
    for r in results:
        mode = r.get("mode", "ERROR")
        if mode not in modes:
            modes[mode] = []
        modes[mode].append(r)

    print("\n" + "=" * 70)
    print("SUMMARY BY MODE")
    print("=" * 70)

    for mode, items in sorted(modes.items()):
        if not items or mode == "ERROR":
            continue

        ratios = [r["corner_center_ratio"] for r in items if "corner_center_ratio" in r]
        deltas = [r["center_minus_corner"] for r in items if "center_minus_corner" in r]
        p50s = [r["p50"] for r in items if "p50" in r]
        p99s = [r["p99"] for r in items if "p99" in r]

        print(f"\n{mode} ({len(items)} images)")
        print("-" * 50)
        if ratios:
            print(f"  corner_center_ratio: min={min(ratios):.4f} max={max(ratios):.4f} "
                  f"mean={np.mean(ratios):.4f}")
        if deltas:
            print(f"  center_minus_corner: min={min(deltas):.5f} max={max(deltas):.5f} "
                  f"mean={np.mean(deltas):.5f}")
        if p50s:
            print(f"  p50:                 min={min(p50s):.4f} max={max(p50s):.4f} "
                  f"mean={np.mean(p50s):.4f}")
        if p99s:
            print(f"  p99:                 min={min(p99s):.4f} max={max(p99s):.4f} "
                  f"mean={np.mean(p99s):.4f}")

    # Identify boundary cases
    print("\n" + "=" * 70)
    print("BOUNDARY CASES (for threshold tuning)")
    print("=" * 70)

    # Find images near classification boundaries
    for r in results:
        if r.get("mode") == "ERROR":
            continue

        ratio = r.get("corner_center_ratio", 0)
        delta = r.get("center_minus_corner", 0)
        p50 = r.get("p50", 0)
        p99 = r.get("p99", 0)

        # Flag boundary cases
        flags = []

        # Near day/night boundary
        if 0.08 <= p50 <= 0.12 or 0.30 <= p99 <= 0.40:
            flags.append("near_day_night_boundary")

        # Near closed/open boundary
        if 0.50 <= ratio <= 0.60:
            flags.append("near_ratio_boundary")
        if 0.015 <= delta <= 0.025:
            flags.append("near_delta_boundary")

        if flags:
            print(f"\n  {r['key']}: {r['mode']}")
            print(f"    ratio={ratio:.4f} delta={delta:.5f} p50={p50:.4f} p99={p99:.4f}")
            print(f"    flags: {', '.join(flags)}")


def main():
    ap = argparse.ArgumentParser(
        description="Analyze FITS files for mode classification stats",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    ap.add_argument("--batch_dir", type=str, required=True,
                    help="Directory containing lum_*.fits files")
    ap.add_argument("--out_csv", type=str, default="mode_analysis.csv",
                    help="Output CSV file (default: mode_analysis.csv)")

    # Threshold parameters (for testing different values)
    ap.add_argument("--corner_roi", type=int, default=50)
    ap.add_argument("--corner_margin", type=int, default=5)
    ap.add_argument("--center_frac", type=float, default=0.25)
    ap.add_argument("--day_p50", type=float, default=0.10)
    ap.add_argument("--day_p99", type=float, default=0.35)
    ap.add_argument("--closed_ratio", type=float, default=0.55)
    ap.add_argument("--closed_delta", type=float, default=0.02)

    args = ap.parse_args()

    batch_dir = Path(args.batch_dir)
    if not batch_dir.is_dir():
        print(f"Error: batch_dir not found: {batch_dir}")
        return

    out_csv = Path(args.out_csv)

    run_analysis(
        batch_dir=batch_dir,
        out_csv=out_csv,
        corner_roi=args.corner_roi,
        corner_margin=args.corner_margin,
        center_frac=args.center_frac,
        day_p50=args.day_p50,
        day_p99=args.day_p99,
        closed_ratio=args.closed_ratio,
        closed_delta=args.closed_delta,
    )


if __name__ == "__main__":
    main()
