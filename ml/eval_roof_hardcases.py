#!/usr/bin/env python3
"""
Roof classifier hard-case evaluation (standalone dev tool).

Reconstructs the *exact* deterministic test split used by train_roof_classifier.py
(same load order + same random_state=42 stratified split), runs the trained model
over it, and reports where it fails — with a focus on the cases that motivated the
retrain: bright-moon-open and heavily-occluded-open frames.

The aggregate test accuracy hides these: the hard cases are a small fraction, so a
99% headline can still mean every bright-moon-open frame is wrong. This slices it
out, prints per-frame context from the calibration JSON, and renders each
misclassified frame to PNG so you can see what fooled the model.

Usage:
    python ml/eval_roof_hardcases.py
    python ml/eval_roof_hardcases.py --model ml/models/roof_classifier_v1.onnx
"""
import sys
import json
import argparse
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from sklearn.model_selection import train_test_split  # noqa: E402
from astropy.io import fits  # noqa: E402
from PIL import Image  # noqa: E402

from ml.train_roof_classifier import load_dataset  # noqa: E402
from ml.roof_classifier import RoofClassifier  # noqa: E402


def reconstruct_test_split(data_dir: Path) -> list:
    """Rebuild the identical test split train_roof_classifier.py produces.

    Mirrors its first split exactly (test_size=0.2, random_state=42, stratified on
    label). load_dataset walks the directory in the same order, so on the same
    machine this yields the same held-out test samples the model was scored on.
    """
    samples = load_dataset(data_dir)
    _, test_samples = train_test_split(
        samples, test_size=0.2, random_state=42,
        stratify=[s['label'] for s in samples],
    )
    return test_samples


def load_image(fits_path: Path) -> np.ndarray:
    with fits.open(fits_path) as hdul:
        data = hdul[0].data
    return data.astype(np.float32)


def render(fits_path: Path, out_path: Path):
    """Save a stretched preview PNG so a failure can be eyeballed."""
    data = load_image(fits_path)
    p1, p99 = np.percentile(data, [1, 99])
    if p99 > p1:
        data = (data - p1) / (p99 - p1)
    data = np.clip(data, 0, 1)
    Image.fromarray((data * 255).astype(np.uint8)).save(out_path)


def slice_accuracy(rows: list, predicate) -> tuple:
    """(correct, total) over rows matching predicate."""
    subset = [r for r in rows if predicate(r)]
    correct = sum(1 for r in subset if r['correct'])
    return correct, len(subset)


def main():
    parser = argparse.ArgumentParser(description="Roof classifier hard-case eval")
    parser.add_argument("data_dir", nargs="?", default=r"D:\Pier Camera ML Data")
    parser.add_argument("--model", default="ml/models/roof_classifier_v1.pth",
                        help="Trained roof model (.pth or .onnx)")
    parser.add_argument("--render-dir", default="ml/eval_output/roof_misclassified",
                        help="Where to write PNGs of misclassified frames")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Error: data dir not found: {data_dir}")
        sys.exit(1)

    print(f"Reconstructing test split from {data_dir} ...")
    test_samples = reconstruct_test_split(data_dir)
    print(f"Test samples: {len(test_samples)}")

    classifier = RoofClassifier.load(args.model)

    rows = []
    for s in test_samples:
        try:
            with open(s['cal_path']) as f:
                cal = json.load(f)
        except Exception:
            cal = {}
        mc = cal.get('moon_context', {})
        ca = cal.get('corner_analysis', {})

        image = load_image(s['fits_path'])
        result = classifier.predict(image, metadata=s['metadata'])

        true_open = bool(s['label'])
        rows.append({
            'timestamp': s['fits_path'].stem.replace('lum_', ''),
            'fits_path': s['fits_path'],
            'true_open': true_open,
            'pred_open': bool(result.roof_open),
            'confidence': float(result.confidence),
            'correct': bool(result.roof_open) == true_open,
            'is_bright_moon': bool(mc.get('is_bright_moon')),
            'moon_is_up': mc.get('moon_is_up'),
            'corner_to_center_ratio': ca.get('corner_to_center_ratio'),
        })

    n = len(rows)
    correct = sum(1 for r in rows if r['correct'])
    print(f"\nOverall test accuracy: {correct}/{n} ({correct / n * 100:.1f}%)")

    # Confusion (open is the positive class)
    tp = sum(1 for r in rows if r['true_open'] and r['pred_open'])
    fn = sum(1 for r in rows if r['true_open'] and not r['pred_open'])
    tn = sum(1 for r in rows if not r['true_open'] and not r['pred_open'])
    fp = sum(1 for r in rows if not r['true_open'] and r['pred_open'])
    print("\nConfusion:           Predicted")
    print("                  Closed   Open")
    print(f"Actual Closed     {tn:5d}  {fp:5d}")
    print(f"       Open       {fn:5d}  {tp:5d}")

    # The slices that motivated the retrain
    print("\n--- Hard-case slices ---")
    bm_open = lambda r: r['true_open'] and r['is_bright_moon']
    c, t = slice_accuracy(rows, bm_open)
    print(f"Bright-moon + roof OPEN: {c}/{t} correct" + ("" if t else "  (none in test set)"))

    moonup_open = lambda r: r['true_open'] and r['moon_is_up'] is True
    c, t = slice_accuracy(rows, moonup_open)
    print(f"Moon-up + roof OPEN:     {c}/{t} correct" + ("" if t else "  (none in test set)"))

    # Occlusion proxy: open frames whose corner/center ratio is high (sky barely
    # brighter than the equipment-filled corners) are the heavily-occluded ones.
    open_ratios = [r['corner_to_center_ratio'] for r in rows
                   if r['true_open'] and r['corner_to_center_ratio'] is not None]
    if open_ratios:
        thresh = float(np.percentile(open_ratios, 75))
        occluded = lambda r: (r['true_open'] and r['corner_to_center_ratio'] is not None
                              and r['corner_to_center_ratio'] >= thresh)
        c, t = slice_accuracy(rows, occluded)
        print(f"Most-occluded OPEN (corner/center >= {thresh:.2f}, top quartile): {c}/{t} correct")

    # Every misclassification, with context
    errors = [r for r in rows if not r['correct']]
    print(f"\n--- {len(errors)} misclassified frame(s) ---")
    render_dir = Path(args.render_dir)
    if errors:
        render_dir.mkdir(parents=True, exist_ok=True)
    for r in errors:
        direction = "OPEN-to-closed" if r['true_open'] else "CLOSED-to-open"
        ratio = r['corner_to_center_ratio']
        ratio_s = f"{ratio:.3f}" if ratio is not None else "?"
        print(f"  {r['timestamp']} | {direction} | conf={r['confidence']:.3f} | "
              f"bright_moon={r['is_bright_moon']} moon_up={r['moon_is_up']} "
              f"corner/center={ratio_s}")
        render(r['fits_path'], render_dir / f"{r['timestamp']}_{direction}.png")
    if errors:
        print(f"\nRendered misclassified frames to: {render_dir}")


if __name__ == "__main__":
    main()
