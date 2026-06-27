#!/usr/bin/env python3
"""Validate manual sky labels with an independent vision model; flag disagreements.

Sends each human-labelled, roof-open lum frame to a (stronger) OpenRouter vision
model, stores the verdict in the frame's `ai_suggestion` block, and reports every
frame where the model disagrees with the human `sky_condition` — the review queue.

It NEVER modifies `labels`. Review/fix flagged frames in the labeling tool using
the "AI disagrees" filter, then keep or correct each one.

DRY-RUN by default (counts + cost estimate, no API calls). Pass --run to call the
API. Needs OPENROUTER_API_KEY; pick the model with --model or OPENROUTER_MODEL
(a strong vision model is the point here, e.g. a frontier multimodal model).

Usage:
    python ml/validate_labels.py                              # dry run, all sky labels
    python ml/validate_labels.py --labels "Partly Cloudy,Overcast"
    python ml/validate_labels.py --run --model anthropic/claude-3.7-sonnet
"""
import argparse
import csv
import glob
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ml.ai_labeler import label_lum_frame  # noqa: E402

SKY = ("Clear", "Partly Cloudy", "Overcast")


def to_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes")
    return bool(v)


def context_hint(cal):
    mc = cal.get("moon_context") or {}
    return {"moon_is_up": mc.get("moon_is_up"),
            "moon_illumination_pct": mc.get("illumination_pct")}


def load_targets(data_dir, labels_filter, sample, model, force):
    rows = []
    for jf in glob.glob(os.path.join(data_dir, "calibration_*.json")):
        try:
            cal = json.load(open(jf, encoding="utf-8"))
        except Exception:
            continue
        L = cal.get("labels") or {}
        if not L.get("labeled_at") or not to_bool(L.get("roof_open")):
            continue
        sc = L.get("sky_condition")
        if sc not in SKY or (labels_filter and sc not in labels_filter):
            continue
        if not force:
            ai = cal.get("ai_suggestion") or {}
            if ai.get("model") == model and ai.get("validated_at"):
                continue  # already validated by this model
        ts = os.path.basename(jf).replace("calibration_", "").replace(".json", "")
        fits = os.path.join(data_dir, f"lum_{ts}.fits")
        if not os.path.isfile(fits):
            continue
        rows.append({"jf": jf, "fits": fits, "ts": ts, "label": sc, "cal": cal})
    if sample and sample < len(rows):
        rows = random.sample(rows, sample)
    return rows


def validate_one(row, model):
    verdict = label_lum_frame(row["fits"], context_hint(row["cal"]), model=model)
    verdict["validated_at"] = datetime.now().isoformat()
    cal = row["cal"]
    cal["ai_suggestion"] = verdict                       # never touches cal["labels"]
    with open(row["jf"], "w", encoding="utf-8") as f:
        json.dump(cal, f, indent=2)
    return row["ts"], row["label"], verdict.get("sky_condition", "") or ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data_dir", nargs="?", default=r"D:\Pier Camera ML Data")
    ap.add_argument("--labels", default=None, help='Comma list, e.g. "Partly Cloudy,Overcast". Default: all.')
    ap.add_argument("--sample", type=int, default=0, help="Validate a random N-frame subset (0 = all).")
    ap.add_argument("--model", default=os.getenv("OPENROUTER_MODEL"), help="OpenRouter model slug.")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cost-per-image", type=float, default=0.005, help="Rough $/frame for the estimate.")
    ap.add_argument("--force", action="store_true", help="Re-validate even if this model already did.")
    ap.add_argument("--run", action="store_true", help="Actually call the API (else dry run).")
    args = ap.parse_args()

    labels_filter = [s.strip() for s in args.labels.split(",")] if args.labels else None
    model = args.model or "google/gemini-2.5-flash"
    rows = load_targets(args.data_dir, labels_filter, args.sample, model, args.force)

    print(f"Target frames (labeled, roof-open{', '+args.labels if labels_filter else ''}): {len(rows)}")
    print(f"Model: {model}  |  estimated cost ~= ${len(rows) * args.cost_per_image:.2f} "
          f"(at ${args.cost_per_image}/frame — model-dependent)")
    if not args.run:
        print("\nDRY RUN — add --run to validate. Results write to each frame's ai_suggestion "
              "(labels untouched); flagged disagreements are reviewable in the labeling tool.")
        return
    if not os.getenv("OPENROUTER_API_KEY"):
        print("\nOPENROUTER_API_KEY is not set. Launch from a shell that has it:\n"
              '  $env:OPENROUTER_API_KEY="sk-or-..."; python ml/validate_labels.py --run ...')
        return

    disagreements, done, failed = [], 0, 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(validate_one, r, model): r for r in rows}
        for fut in as_completed(futs):
            try:
                ts, label, ai_sky = fut.result()
            except Exception as e:
                failed += 1
                if failed <= 5:
                    print(f"  ! {futs[fut]['ts']}: {e}")
                continue
            done += 1
            if ai_sky and ai_sky != label:
                disagreements.append((ts, label, ai_sky))
            if done % 25 == 0:
                print(f"  {done}/{len(rows)} validated, {len(disagreements)} flagged...")

    out = os.path.join(args.data_dir, "_label_validation", "ai_disagreements.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "your_label", "model_says"])
        for ts, label, ai in sorted(disagreements):
            w.writerow([ts, label, ai])

    print(f"\nValidated {done} frames ({failed} failed).")
    print(f"Model AGREES with your label on {done - len(disagreements)}/{done}.")
    print(f"Flagged for review (model disagrees): {len(disagreements)}  ->  {out}")
    print("Open the labeling tool and use the 'AI disagrees' filter to review them.")


if __name__ == "__main__":
    main()
