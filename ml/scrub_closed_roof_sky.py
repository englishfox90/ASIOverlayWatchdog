#!/usr/bin/env python3
"""Strip sky-condition labels from closed-roof frames in the ML dataset.

When the roof is closed the pier camera cannot see the sky, so any
`sky_condition` / `clouds_visible` value on that frame is noise that would
corrupt the sky classifier. This walks every calibration_*.json, decides
whether the roof was closed, and removes those fields from the `labels` block
(and optionally the `ai_suggestion` block).

Roof state is resolved in priority order — manual label, then NINA roof_state,
then the roof ML prediction — so it works for manual, AI, and unlabeled frames.

DRY RUN BY DEFAULT. Pass --apply to write; every modified file is backed up
first.

Usage:
    python ml/scrub_closed_roof_sky.py                       # dry run, report only
    python ml/scrub_closed_roof_sky.py --apply               # write changes (+ backup)
    python ml/scrub_closed_roof_sky.py --roof-source nina    # force a roof signal
    python ml/scrub_closed_roof_sky.py --include-ai          # also scrub ai_suggestion
    python ml/scrub_closed_roof_sky.py --clear-celestial     # also clear stars/moon/density
"""
import argparse
import json
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

DEFAULT_DATA_DIR = r"D:\Pier Camera ML Data"
SKY_FIELDS = ("sky_condition", "clouds_visible")
CELESTIAL_FIELDS = ("stars_visible", "star_density", "moon_visible")


def to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def resolve_roof_open(cal: dict, source: str):
    """Return (roof_open: bool|None, used_source: str).

    None means no usable roof signal — the frame is left untouched.
    """
    labels = cal.get("labels") or {}
    rs = cal.get("roof_state") or {}
    ml = cal.get("ml_prediction") or {}

    def from_label():
        if labels.get("labeled_at") is not None and labels.get("roof_open") is not None:
            return to_bool(labels.get("roof_open"))
        return None

    def from_nina():
        if rs.get("available") and rs.get("roof_open") is not None:
            return to_bool(rs.get("roof_open"))
        return None

    def from_ml():
        if ml and ml.get("roof_open") is not None:
            return to_bool(ml.get("roof_open"))
        return None

    providers = {"label": from_label, "nina": from_nina, "ml": from_ml}
    order = [source] if source != "auto" else ["label", "nina", "ml"]
    for name in order:
        val = providers[name]()
        if val is not None:
            return val, name
    return None, "none"


def scrub_block(block: dict, fields) -> list:
    """Remove the given fields from a dict; return the keys actually removed."""
    removed = []
    for f in fields:
        if f in block:
            block.pop(f)
            removed.append(f)
    return removed


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("data_dir", nargs="?", default=DEFAULT_DATA_DIR)
    parser.add_argument("--apply", action="store_true",
                        help="Write changes. Without this the script only reports.")
    parser.add_argument("--roof-source", choices=["auto", "label", "nina", "ml"],
                        default="auto", help="Which roof signal decides 'closed'.")
    parser.add_argument("--include-ai", action="store_true",
                        help="Also strip sky fields from the ai_suggestion block.")
    parser.add_argument("--clear-celestial", action="store_true",
                        help="Also clear stars_visible / star_density / moon_visible.")
    parser.add_argument("--backup-dir", default=None,
                        help="Where to copy originals before writing (default: "
                             "<data_dir>/_backup_scrub_<timestamp>).")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Directory not found: {data_dir}")
        return

    fields = list(SKY_FIELDS) + (list(CELESTIAL_FIELDS) if args.clear_celestial else [])

    files = sorted(data_dir.rglob("calibration_*.json"))
    print(f"Scanning {len(files)} calibration files in {data_dir}")
    print(f"Roof source: {args.roof_source} | fields: {fields} | include_ai: {args.include_ai}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN (no files written)'}\n")

    backup_dir = None
    if args.apply:
        backup_dir = Path(args.backup_dir) if args.backup_dir else (
            data_dir / f"_backup_scrub_{datetime.now():%Y%m%d_%H%M%S}")
        backup_dir.mkdir(parents=True, exist_ok=True)

    src_used = Counter()
    closed = 0
    to_change = 0
    changed = 0
    removed_keys = Counter()
    by_label_state = Counter()
    errors = 0

    for fp in files:
        try:
            cal = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            errors += 1
            continue

        roof_open, used = resolve_roof_open(cal, args.roof_source)
        if roof_open is None:
            src_used["unknown"] += 1
            continue
        src_used[used] += 1
        if roof_open:
            continue
        closed += 1

        labels = cal.get("labels") or {}
        targets = [("labels", labels)]
        if args.include_ai and isinstance(cal.get("ai_suggestion"), dict):
            targets.append(("ai_suggestion", cal["ai_suggestion"]))

        would_remove = [(name, [f for f in fields if f in blk]) for name, blk in targets]
        any_removable = any(keys for _, keys in would_remove)
        if not any_removable:
            continue

        to_change += 1
        by_label_state["labeled" if labels.get("labeled_at") else "unlabeled"] += 1
        for _, keys in would_remove:
            for k in keys:
                removed_keys[k] += 1

        if args.apply:
            shutil.copy2(fp, backup_dir / fp.name)
            for _, blk in targets:
                scrub_block(blk, fields)
            fp.write_text(json.dumps(cal, indent=2), encoding="utf-8")
            changed += 1

    print("-- Roof signal coverage --")
    for k, v in src_used.most_common():
        print(f"  {k:9} {v}")
    print(f"\nClosed-roof frames:                 {closed}")
    print(f"Closed-roof frames with sky fields: {to_change}")
    print(f"  of which previously labeled:      {by_label_state.get('labeled', 0)}")
    print(f"  of which unlabeled:               {by_label_state.get('unlabeled', 0)}")
    print("\nFields that would be removed:" if not args.apply else "\nFields removed:")
    for k, v in removed_keys.most_common():
        print(f"  {k:16} {v}")
    if errors:
        print(f"\nUnreadable files skipped: {errors}")

    if args.apply:
        print(f"\nDone. Modified {changed} files. Backups in: {backup_dir}")
    else:
        print(f"\nDRY RUN -- re-run with --apply to write (originals are backed up first).")


if __name__ == "__main__":
    main()
