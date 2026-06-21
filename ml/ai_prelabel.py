#!/usr/bin/env python3
"""
Batch AI pre-labeller for PFR Sentinel.

Walks the ML data dir, sends each unlabelled lum frame to a cheap vision model
via OpenRouter, and writes an `ai_suggestion` block into the calibration JSON.
The labeling tool then pre-fills the form from it so you only review + confirm.

Human labels are never touched. By default already-suggested frames are skipped.

Usage:
    set OPENROUTER_API_KEY=sk-or-...
    python ml/ai_prelabel.py                       # all unlabelled frames on D:
    python ml/ai_prelabel.py --limit 20            # try 20 first (sanity check)
    python ml/ai_prelabel.py --overwrite           # redo existing AI suggestions
    python ml/ai_prelabel.py --include-labeled     # also suggest for human-labelled frames
"""
import sys
import json
import time
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ml.labeling_io import find_sample_sets
from ml.ai_labeler import label_lum_frame, build_context_from_cal


def _should_process(cal: dict, include_labeled: bool, overwrite: bool) -> bool:
    if not include_labeled and cal.get("labels", {}).get("labeled_at"):
        return False
    if not overwrite and cal.get("ai_suggestion"):
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Batch AI pre-labeller for lum frames")
    parser.add_argument("data_dir", nargs="?", default=r"D:\Pier Camera ML Data",
                        help="Directory containing calibration files")
    parser.add_argument("--model", default=None, help="OpenRouter model slug (overrides env)")
    parser.add_argument("--limit", type=int, default=0, help="Stop after N frames (0 = all)")
    parser.add_argument("--overwrite", action="store_true", help="Redo existing AI suggestions")
    parser.add_argument("--include-labeled", action="store_true",
                        help="Also suggest for human-labelled frames")
    parser.add_argument("--hints", action="store_true",
                        help="Send night/moon context to the model. OFF by default so the "
                             "prediction is purely image-derived and can be validated cleanly "
                             "against the config's existing labels.")
    parser.add_argument("--sleep", type=float, default=0.0,
                        help="Seconds to pause between calls (rate limiting)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"ERROR: directory not found: {data_dir}")
        sys.exit(1)

    samples = [s for s in find_sample_sets(data_dir) if "lum" in s]
    print(f"Found {len(samples)} samples with lum frames in {data_dir}")

    done = skipped = failed = 0
    for sample in samples:
        if args.limit and done >= args.limit:
            break

        cal_path = sample["calibration"]
        with open(cal_path, "r") as f:
            cal = json.load(f)

        if not _should_process(cal, args.include_labeled, args.overwrite):
            skipped += 1
            continue

        context = build_context_from_cal(cal) if args.hints else None
        try:
            result = label_lum_frame(sample["lum"], context, model=args.model)
        except Exception as e:
            failed += 1
            print(f"  ✗ {sample['timestamp']}: {e}")
            continue

        result["suggested_at"] = datetime.now().isoformat()
        result["hints_used"] = bool(args.hints)
        cal["ai_suggestion"] = result
        with open(cal_path, "w") as f:
            json.dump(cal, f, indent=2)

        done += 1
        roof = "OPEN" if result["roof_open"] else "CLOSED"
        sky = result["sky_condition"] or "-"
        print(f"  ✓ {sample['timestamp']}: roof={roof} ({result['roof_confidence']:.0%}) "
              f"sky={sky} ({result['sky_confidence']:.0%})")

        if args.sleep:
            time.sleep(args.sleep)

    print(f"\nDone. labelled={done}  skipped={skipped}  failed={failed}")


if __name__ == "__main__":
    main()
