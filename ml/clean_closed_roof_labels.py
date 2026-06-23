#!/usr/bin/env python3
"""
Data hygiene: clear sky labels on closed-roof frames.

A closed roof blocks the sky, so the celestial/sky labels can't be meaningful.
For every human-labeled calibration file with labels.roof_open == False, reset the
sky fields to their "nothing visible" state. roof_open, notes, and labeled_at are
left untouched, and only the `labels` block (human ground truth) is modified — the
AI's `ai_suggestion` record is left as-is.

Usage:
    python ml/clean_closed_roof_labels.py --dry-run    # preview
    python ml/clean_closed_roof_labels.py              # apply
"""
import sys
import json
import argparse
from pathlib import Path
from collections import Counter

# "Nothing visible through a closed roof" state for each sky label.
CLOSED_SKY_LABELS = {
    'sky_condition': '',
    'stars_visible': False,
    'star_density': 0,
    'moon_visible': False,
    'clouds_visible': False,
}


def main():
    parser = argparse.ArgumentParser(description="Clear sky labels on closed-roof frames")
    parser.add_argument("data_dir", nargs="?", default=r"D:\Pier Camera ML Data")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"ERROR: directory not found: {data_dir}")
        sys.exit(1)

    cal_files = sorted(data_dir.glob("calibration_*.json"))
    print(f"Scanning {len(cal_files)} calibration files in {data_dir}\n")

    closed_labeled = 0
    files_changed = 0
    fields_changed = Counter()

    for cal_file in cal_files:
        try:
            with open(cal_file, "r", encoding="utf-8") as f:
                cal = json.load(f)
        except Exception as e:
            print(f"  skip (unreadable): {cal_file.name}: {e}")
            continue

        labels = cal.get("labels")
        # Only human-labeled, explicitly-closed frames.
        if not isinstance(labels, dict) or not labels.get("labeled_at"):
            continue
        if labels.get("roof_open") is not False:
            continue

        closed_labeled += 1
        changed = False
        for field, cleared in CLOSED_SKY_LABELS.items():
            if field in labels and labels[field] != cleared:
                labels[field] = cleared
                fields_changed[field] += 1
                changed = True

        if changed:
            files_changed += 1
            if not args.dry_run:
                with open(cal_file, "w", encoding="utf-8") as f:
                    json.dump(cal, f, indent=2)

    verb = "Would clear" if args.dry_run else "Cleared"
    print(f"Closed-roof labeled frames: {closed_labeled}")
    print(f"{verb} sky labels on {files_changed} file(s) that still had stale values")
    if fields_changed:
        print("  per-field resets: " + ", ".join(f"{k}={v}" for k, v in sorted(fields_changed.items())))
    if args.dry_run:
        print("\n(dry run — nothing written; re-run without --dry-run to apply)")


if __name__ == "__main__":
    main()
