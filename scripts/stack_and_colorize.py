#!/usr/bin/env python3
"""
Stack multiple FITS frames to improve SNR, then colorize.

Stacks N most recent frames from a directory using median combine,
which effectively reduces noise by ~sqrt(N) while rejecting outliers.

Usage:
    python stack_and_colorize.py "H:\\raw_debug\\Roof Closed Night" \\
        --num_frames 5 \\
        --out_dir "stacked_out" \\
        --out_name "stacked_result.png"
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

import numpy as np
from astropy.io import fits


def find_fits_pairs(directory: Path, pattern: str = "lum_*.fits") -> list[tuple[Path, Path]]:
    """
    Find matching lum/raw FITS pairs in directory.
    
    Returns list of (lum_path, raw_path) tuples sorted by timestamp (newest first).
    """
    lum_files = list(directory.glob(pattern))
    
    pairs = []
    for lum_path in lum_files:
        # Extract timestamp from filename: lum_20260105_193928.fits
        timestamp = lum_path.stem.replace("lum_", "")
        raw_path = directory / f"raw_{timestamp}.fits"
        
        if raw_path.exists():
            pairs.append((lum_path, raw_path, timestamp))
    
    # Sort by timestamp string (YYYYMMDD_HHMMSS format sorts correctly)
    pairs.sort(key=lambda x: x[2], reverse=True)
    
    # Return without timestamp for backward compatibility
    return [(lum, raw) for lum, raw, _ in pairs]


def find_consecutive_sequence(pairs: list[tuple[Path, Path]], num_frames: int) -> list[tuple[Path, Path]]:
    """
    Find the most recent consecutive sequence of frames.
    
    For fixed camera setup, we just take the N most recent frames.
    They're already sorted by timestamp (newest first).
    
    Args:
        pairs: List of (lum_path, raw_path) tuples sorted newest first
        num_frames: Desired number of frames
    
    Returns:
        List of consecutive frames (newest first), up to num_frames
    """
    # Simply take the most recent N frames
    # Sigma-clipping will handle any moving objects
    result = pairs[:num_frames]
    
    return result


def load_fits_data(path: Path) -> np.ndarray:
    """Load FITS file and return data array."""
    with fits.open(path) as hdul:
        return hdul[0].data.astype(np.float32)


def sigma_clipped_stack(
    stack: np.ndarray, 
    sigma: float = 3.0, 
    method: str = "median"
) -> tuple[np.ndarray, dict]:
    """
    Stack with per-pixel sigma-clipping to reject outliers.
    
    For fixed camera with moving objects (imaging train, moon),
    this rejects pixels that differ significantly from the median.
    
    Args:
        stack: (N, H, W) array of frames
        sigma: Reject pixels > sigma * MAD from median
        method: "median" or "mean" for final combine
    
    Returns:
        (stacked, stats_dict)
    """
    # Compute median and MAD (Median Absolute Deviation) per pixel
    median_vals = np.median(stack, axis=0)
    
    # MAD = median(|x - median|)
    # Robust estimate of stddev = 1.4826 * MAD
    abs_dev = np.abs(stack - median_vals[np.newaxis, ...])
    mad = np.median(abs_dev, axis=0)
    sigma_est = 1.4826 * mad
    
    # Flag outliers (pixels > sigma * sigma_est from median)
    threshold = sigma * sigma_est[np.newaxis, ...]
    is_outlier = abs_dev > threshold
    
    # Replace outliers with NaN
    stack_clean = stack.copy()
    stack_clean[is_outlier] = np.nan
    
    # Compute final stack (ignoring NaNs)
    if method == "median":
        result = np.nanmedian(stack_clean, axis=0)
    elif method == "mean":
        result = np.nanmean(stack_clean, axis=0)
    else:
        raise ValueError(f"Unknown method: {method}")
    
    # Fill any remaining NaNs (pixels rejected in all frames) with original median
    result = np.where(np.isnan(result), median_vals, result)
    
    # Statistics
    total_pixels = stack.shape[0] * stack.shape[1] * stack.shape[2]
    rejected_pixels = np.sum(is_outlier)
    rejection_rate = rejected_pixels / total_pixels
    
    # Per-frame rejection stats
    per_frame_rejection = []
    for i in range(stack.shape[0]):
        frame_rejected = np.sum(is_outlier[i])
        frame_pixels = stack.shape[1] * stack.shape[2]
        per_frame_rejection.append({
            "frame_idx": i,
            "rejected_pixels": int(frame_rejected),
            "rejection_rate": float(frame_rejected / frame_pixels)
        })
    
    stats = {
        "sigma_threshold": float(sigma),
        "total_rejected": int(rejected_pixels),
        "rejection_rate": float(rejection_rate),
        "per_frame": per_frame_rejection,
    }
    
    return result, stats


def stack_frames(
    pairs: list[tuple[Path, Path]], 
    method: str = "median",
    sigma_clip: float = None
) -> tuple[np.ndarray, np.ndarray, dict]:
    """
    Stack lum and raw frames separately.
    
    Args:
        pairs: List of (lum_path, raw_path) tuples
        method: "median" or "mean"
        sigma_clip: If set, use sigma-clipping to reject outliers (e.g., 3.0)
                   Good for fixed camera with moving objects in scene.
    
    Returns:
        (stacked_lum, stacked_raw, metadata)
    """
    print(f"Loading {len(pairs)} frame pairs...")
    
    lum_stack = []
    raw_stack = []
    
    for i, (lum_path, raw_path) in enumerate(pairs, 1):
        print(f"  [{i}/{len(pairs)}] {lum_path.name}")
        lum_stack.append(load_fits_data(lum_path))
        raw_stack.append(load_fits_data(raw_path))
    
    # Stack into 3D arrays (N, H, W)
    lum_array = np.stack(lum_stack, axis=0)
    raw_array = np.stack(raw_stack, axis=0)
    
    metadata = {
        "method": method,
        "num_frames": len(pairs),
        "frame_list": [str(p[0].name) for p in pairs],
        "stacked_at": datetime.now().isoformat(),
        "noise_reduction_factor": np.sqrt(len(pairs)),
    }
    
    if sigma_clip:
        print(f"Stacking with sigma-clipped {method} (sigma={sigma_clip})...")
        print("  This will reject moving objects (imaging train, moon, etc.)")
        
        stacked_lum, lum_stats = sigma_clipped_stack(lum_array, sigma=sigma_clip, method=method)
        stacked_raw, raw_stats = sigma_clipped_stack(raw_array, sigma=sigma_clip, method=method)
        
        stacked_lum = stacked_lum.astype(np.float32)
        stacked_raw = stacked_raw.astype(np.uint16)
        
        metadata["sigma_clip"] = {
            "enabled": True,
            "sigma": sigma_clip,
            "lum": lum_stats,
            "raw": raw_stats,
        }
        
        # Print rejection summary
        print(f"  Lum: {lum_stats['rejection_rate']*100:.2f}% pixels rejected")
        print(f"  Raw: {raw_stats['rejection_rate']*100:.2f}% pixels rejected")
        
        # Show per-frame rejection if significant variance
        max_frame_reject = max(f["rejection_rate"] for f in lum_stats["per_frame"])
        min_frame_reject = min(f["rejection_rate"] for f in lum_stats["per_frame"])
        if max_frame_reject - min_frame_reject > 0.05:  # 5% difference
            print("\n  Per-frame rejection (frames with moving objects):")
            for i, frame_stat in enumerate(lum_stats["per_frame"]):
                if frame_stat["rejection_rate"] > 0.01:  # > 1% rejected
                    print(f"    Frame {i+1}: {frame_stat['rejection_rate']*100:.2f}% rejected")
    else:
        print(f"Stacking with {method} combine...")
        
        if method == "median":
            stacked_lum = np.median(lum_array, axis=0).astype(np.float32)
            stacked_raw = np.median(raw_array, axis=0).astype(np.uint16)
        elif method == "mean":
            stacked_lum = np.mean(lum_array, axis=0).astype(np.float32)
            stacked_raw = np.mean(raw_array, axis=0).astype(np.uint16)
        else:
            raise ValueError(f"Unknown method: {method}")
        
        metadata["sigma_clip"] = {"enabled": False}
    
    return stacked_lum, stacked_raw, metadata


def save_fits(data: np.ndarray, path: Path) -> None:
    """Save data as FITS file."""
    hdu = fits.PrimaryHDU(data)
    hdu.writeto(path, overwrite=True)
    print(f"Saved: {path}")


def run_colorize(lum_path: Path, raw_path: Path, out_dir: Path, out_name: str, extra_args: list[str]) -> int:
    """
    Run colorize_from_lum.py on the stacked frames.
    
    Returns exit code.
    """
    colorize_script = Path(__file__).parent / "colorize_from_lum.py"
    
    cmd = [
        sys.executable,
        str(colorize_script),
        str(lum_path),
        str(raw_path),
        "--out_dir", str(out_dir),
        "--out_name", out_name,
        "--auto", "1",  # Enable auto mode for recipe selection
    ]
    
    # Add any extra args passed through
    cmd.extend(extra_args)
    
    print(f"\nRunning colorize_from_lum...")
    print(f"  Command: {' '.join(cmd)}")
    
    result = subprocess.run(cmd, capture_output=False, text=True)
    return result.returncode


def main():
    ap = argparse.ArgumentParser(
        description="Stack multiple FITS frames and colorize for improved SNR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Stack 5 most recent frames
    python stack_and_colorize.py "H:\\raw_debug\\Roof Closed Night" --num_frames 5
    
    # Stack 10 frames with custom output
    python stack_and_colorize.py "H:\\raw_debug\\Roof Closed Night" \\
        --num_frames 10 \\
        --out_dir "stacked_output" \\
        --out_name "night_stacked_10x.png"
    
    # Stack and pass custom colorize args
    python stack_and_colorize.py "H:\\raw_debug\\Roof Closed Night" \\
        --num_frames 8 \\
        -- --corner_sigma_bp 2.0 --chroma_blur 8
        """
    )
    
    ap.add_argument("directory", help="Directory containing lum_*.fits and raw_*.fits pairs")
    ap.add_argument("--num_frames", type=int, default=5, help="Number of frames to stack (default: 5)")
    ap.add_argument("--method", choices=["median", "mean"], default="median", 
                    help="Stacking method (default: median)")
    ap.add_argument("--sigma_clip", type=float, default=None, metavar="SIGMA",
                    help="Sigma-clipping threshold for outlier rejection (e.g., 3.0). "
                         "Use this for fixed camera with moving objects in scene. "
                         "Pixels > SIGMA*MAD from median are rejected.")
    ap.add_argument("--out_dir", default="stacked_out", help="Output directory (default: stacked_out)")
    ap.add_argument("--out_name", default=None, 
                    help="Output filename (default: stacked_Nx_YYYYMMDD_HHMMSS.png)")
    ap.add_argument("--keep_fits", action="store_true", 
                    help="Keep intermediate stacked FITS files")
    
    # Allow passing extra args to colorize_from_lum after --
    args, colorize_args = ap.parse_known_args()
    
    directory = Path(args.directory)
    if not directory.exists():
        print(f"ERROR: Directory not found: {directory}")
        sys.exit(1)
    
    # Find FITS pairs
    pairs = find_fits_pairs(directory)
    if not pairs:
        print(f"ERROR: No lum/raw FITS pairs found in {directory}")
        sys.exit(1)
    
    print(f"Found {len(pairs)} total FITS pairs in {directory}")
    
    # Find consecutive sequence
    consecutive_pairs = find_consecutive_sequence(pairs, args.num_frames)
    
    if len(consecutive_pairs) < args.num_frames:
        print(f"WARNING: Only found {len(consecutive_pairs)} consecutive frames (requested {args.num_frames})")
        print("         Using all consecutive frames found")
    else:
        print(f"Found consecutive sequence of {len(consecutive_pairs)} frames")
    
    if not consecutive_pairs:
        print("ERROR: No consecutive frames found")
        sys.exit(1)
    
    # Print sequence info
    print(f"\nStacking sequence (newest to oldest):")
    for i, (lum, raw) in enumerate(consecutive_pairs, 1):
        timestamp_str = lum.stem.replace("lum_", "")
        print(f"  {i}. {timestamp_str}")
    
    # Stack frames
    stacked_lum, stacked_raw, stack_meta = stack_frames(
        consecutive_pairs, 
        method=args.method,
        sigma_clip=args.sigma_clip
    )
    
    print(f"Stacked shape: lum={stacked_lum.shape}, raw={stacked_raw.shape}")
    print(f"Noise reduction factor: {stack_meta['noise_reduction_factor']:.2f}x")
    
    # Create output directory
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate timestamp for this stack
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Save stacked FITS to temp directory
    temp_dir = out_dir / "temp_fits"
    temp_dir.mkdir(exist_ok=True)
    
    stacked_lum_path = temp_dir / f"stacked_lum_{args.num_frames}x_{timestamp}.fits"
    stacked_raw_path = temp_dir / f"stacked_raw_{args.num_frames}x_{timestamp}.fits"
    
    save_fits(stacked_lum, stacked_lum_path)
    save_fits(stacked_raw, stacked_raw_path)
    
    # Save stack metadata
    stack_json_path = out_dir / f"stack_metadata_{args.num_frames}x_{timestamp}.json"
    with open(stack_json_path, 'w') as f:
        json.dump(stack_meta, f, indent=2)
    print(f"Saved: {stack_json_path}")
    
    # Determine output name
    if args.out_name is None:
        out_name = f"stacked_{args.num_frames}x_{timestamp}.png"
    else:
        out_name = args.out_name
    
    # Run colorize on stacked frames
    exit_code = run_colorize(
        stacked_lum_path, 
        stacked_raw_path, 
        out_dir, 
        out_name,
        colorize_args
    )
    
    if exit_code == 0:
        print(f"\n✓ Success! Output saved to: {out_dir / out_name}")
    else:
        print(f"\n✗ Colorize failed with exit code {exit_code}")
    
    # Cleanup temp FITS if requested
    if not args.keep_fits:
        print(f"\nCleaning up temp FITS files...")
        stacked_lum_path.unlink()
        stacked_raw_path.unlink()
        if not any(temp_dir.iterdir()):
            temp_dir.rmdir()
    else:
        print(f"\nKept stacked FITS files in: {temp_dir}")
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
