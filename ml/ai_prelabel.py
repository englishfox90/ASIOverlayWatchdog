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
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    parser.add_argument("--workers", type=int, default=6,
                        help="Number of concurrent classifiers (default 6)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"ERROR: directory not found: {data_dir}")
        sys.exit(1)

    samples = [s for s in find_sample_sets(data_dir) if "lum" in s]
    print(f"Found {len(samples)} samples with lum frames in {data_dir}")

    # Decide the work-list up front (cheap local JSON reads) so the pool only
    # spends paid API calls on frames that actually need a suggestion.
    jobs, skipped = [], 0
    for sample in samples:
        with open(sample["calibration"], "r") as f:
            cal = json.load(f)
        if not _should_process(cal, args.include_labeled, args.overwrite):
            skipped += 1
            continue
        jobs.append((sample, cal))
        if args.limit and len(jobs) >= args.limit:
            break

    total = len(jobs)
    print(f"To label: {total}  (skipped {skipped})  with {args.workers} workers\n")
    if not total:
        return

    use_hints = args.hints

    def process_one(job):
        sample, cal = job
        context = build_context_from_cal(cal) if use_hints else None
        result = label_lum_frame(sample["lum"], context, model=args.model)
        result["suggested_at"] = datetime.now().isoformat()
        result["hints_used"] = bool(use_hints)
        cal["ai_suggestion"] = result
        with open(sample["calibration"], "w") as f:
            json.dump(cal, f, indent=2)
        return result

    done = failed = 0
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process_one, job): job for job in jobs}
        for i, fut in enumerate(as_completed(futures), 1):
            sample = futures[fut][0]
            try:
                result = fut.result()
                done += 1
                roof = "OPEN" if result["roof_open"] else "CLOSED"
                sky = result["sky_condition"] or "-"
                print(f"  [{i}/{total}] OK  {sample['timestamp']}: roof={roof} "
                      f"({result['roof_confidence']:.0%}) sky={sky}")
            except Exception as e:
                failed += 1
                print(f"  [{i}/{total}] ERR {sample['timestamp']}: {e}")

    elapsed = time.monotonic() - started
    rate = done / elapsed * 60 if elapsed else 0
    print(f"\nDone. labelled={done}  failed={failed}  "
          f"in {elapsed:.0f}s ({rate:.0f}/min)")


if __name__ == "__main__":
    main()
