#!/usr/bin/env python3
"""A/B the sky classifier across input sizes; report per-class recall side by side.

Trains the sky model at each --size into an experiment folder (never touches the
production ml/models/sky_classifier_v1.*), then prints one comparison table so you
can pick the size by Partly Cloudy / Overcast recall rather than overall accuracy
(which Clear dominates). Same SEED in the trainer => identical held-out test set
across sizes, so the comparison is apples-to-apples.

Heads-up on this architecture: the sky CNN flattens the conv output into a dense
layer sized (image_size // 32)^2 * 256, so doubling the size ~quadruples that FC's
parameters. On ~1200 training frames that invites overfitting — watch the params
column and the *test* recall, not just "more pixels = better". If bigger sizes
overfit, the real fix is a global-avg-pool before the FC (decouples FC from input
size); ask and I'll add that variant.

Usage:
    python ml/sweep_sky_image_size.py --sizes 256,384,512 --epochs 50
    python ml/sweep_sky_image_size.py --sizes 256,384 --epochs 30 --batch-size 32
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ml.train_sky_classifier import train_model  # noqa: E402


def fmt(cor_tot):
    c, t = cor_tot
    return f"{c}/{t} ({(c / t * 100) if t else 0:.0f}%)"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=r"D:\Pier Camera ML Data")
    ap.add_argument("--sizes", default="256,384,512", help="Comma list, must be multiples of 32.")
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--out-root", default="ml/models/_size_sweep")
    args = ap.parse_args()

    sizes = [int(s) for s in args.sizes.split(",")]
    bad = [s for s in sizes if s % 32]
    if bad:
        print(f"Sizes must be multiples of 32 (5 pooling layers): {bad}")
        return

    results = []
    for sz in sizes:
        print("\n" + "#" * 64)
        print(f"#  Training sky model at image_size = {sz}")
        print("#" * 64)
        m = train_model(
            data_dir=Path(args.data_dir),
            output_dir=Path(args.out_root) / f"s{sz}",
            image_size=sz,
            batch_size=args.batch_size,
            epochs=args.epochs,
            model_name=f"sky_classifier_s{sz}",
        )
        if m:
            results.append(m)
        else:
            print(f"  size {sz}: training returned no metrics (too few samples?)")

    if not results:
        print("\nNo successful runs.")
        return

    print("\n" + "=" * 78)
    print("IMAGE-SIZE SWEEP — held-out test set (pick by Partly Cloudy / Overcast recall)")
    print("=" * 78)
    hdr = (f"{'size':>5} | {'overall':>13} | {'Clear':>12} | {'Partly Cloudy':>14} | "
           f"{'Overcast':>12} | {'params':>8}")
    print(hdr)
    print("-" * len(hdr))
    for m in results:
        pc = m["sky_per_class"]
        print(f"{m['image_size']:>5} | {fmt(m['sky_overall']):>13} | {fmt(pc['Clear']):>12} | "
              f"{fmt(pc['Partly Cloudy']):>14} | {fmt(pc['Overcast']):>12} | {m['params'] / 1e6:>6.1f}M")

    print(f"\n(test set n = {results[0]['test_n']}, train n = {results[0]['train_n']})")
    print("\nPromote the winner to production:")
    for m in results:
        stem = Path(m["model_path"]).with_suffix("")
        print(f"  size {m['image_size']}:  copy {stem}.pth/.onnx  ->  ml/models/sky_classifier_v1.pth/.onnx")


if __name__ == "__main__":
    main()
