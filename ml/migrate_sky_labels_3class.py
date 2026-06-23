#!/usr/bin/env python3
"""
One-off migration: collapse 5-class sky_condition labels to the 3-class scheme.

Rewrites `labels.sky_condition` and `ai_suggestion.sky_condition` in every
calibration_*.json under the data dir, folding old/labeling-only classes into the
nearest of Clear / Partly Cloudy / Overcast via SKY_CONDITION_COLLAPSE (the same
map training uses, so data and code can't drift).

Empty strings (roof-closed frames) are left untouched. Files are only rewritten
when a value actually changes.

Usage:
    python ml/migrate_sky_labels_3class.py --dry-run      # preview only
    python ml/migrate_sky_labels_3class.py                # apply
"""
import sys
import json
import argparse
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))
from ml.sky_dataset import SKY_CONDITION_COLLAPSE  # noqa: E402


def _collapse(value):
    """Return the collapsed class, or the original if unmapped/empty."""
    if not value:
        return value
    return SKY_CONDITION_COLLAPSE.get(value, value)


def main():
    parser = argparse.ArgumentParser(description="Collapse sky labels to 3 classes")
    parser.add_argument("data_dir", nargs="?", default=r"D:\Pier Camera ML Data")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"ERROR: directory not found: {data_dir}")
        sys.exit(1)

    before = Counter()
    after = Counter()
    files_changed = 0
    fields_changed = Counter()

    cal_files = sorted(data_dir.glob("calibration_*.json"))
    print(f"Scanning {len(cal_files)} calibration files in {data_dir}\n")

    for cal_file in cal_files:
        try:
            with open(cal_file, "r", encoding="utf-8") as f:
                cal = json.load(f)
        except Exception as e:
            print(f"  skip (unreadable): {cal_file.name}: {e}")
            continue

        changed = False
        for section in ("labels", "ai_suggestion"):
            block = cal.get(section)
            if not isinstance(block, dict) or "sky_condition" not in block:
                continue
            old = block["sky_condition"]
            new = _collapse(old)
            if section == "labels" and old:
                before[old] += 1
                after[new] += 1
            if new != old:
                block["sky_condition"] = new
                fields_changed[section] += 1
                changed = True

        if changed:
            files_changed += 1
            if not args.dry_run:
                with open(cal_file, "w", encoding="utf-8") as f:
                    json.dump(cal, f, indent=2)

    verb = "Would change" if args.dry_run else "Changed"
    print("=== labels.sky_condition distribution (human labels) ===")
    print(f"  {'class':<16} before -> after")
    for cls in sorted(set(before) | set(after)):
        print(f"  {cls:<16} {before.get(cls, 0):>5} -> {after.get(cls, 0):>5}")
    print()
    print(f"{verb} {files_changed} file(s): "
          f"{dict(fields_changed)} field(s) collapsed")
    if args.dry_run:
        print("\n(dry run — nothing written; re-run without --dry-run to apply)")


if __name__ == "__main__":
    main()
