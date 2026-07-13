"""
Offline Meteor Detection Replay Harness
========================================
Feeds a directory of pre-recorded frames through the Phase 2–4 detection
pipeline so you can iterate on thresholds, stack depth, and profile filters
without needing a live camera session.

Usage
-----
    python scripts/dev/meteor_replay.py <frames_dir> [options]

    python scripts/dev/meteor_replay.py E:/meteor_corpus/planes_2026-06 \
        --sensitivity high --stack 6 --show

Frames directory should contain JPEG/PNG grayscale (or RGB) images named in
chronological order (alphabetical sort is used). The script replicates exactly
what the live pipeline does:
  1. Downscale to detection resolution (default: long side = 1280 px).
  2. Convert to grayscale.
  3. Push to FrameStack; compute transient_map and hot_mask when full.
  4. Apply DiffNoiseEMA → noise_to_threshold.
  5. Run detect_meteors with feathered sky-circle mask.
  6. Feed PersistenceFilter; print released meteors / plane rejections.

Output
------
- Console report per frame (detections, noise sigma, threshold).
- Optional: save annotated images to <frames_dir>/replay_out/.
- Optional: show each frame in an OpenCV window (--show).

Run as a script from the project root:
    python -m scripts.dev.meteor_replay <args>
or directly:
    python scripts/dev/meteor_replay.py <args>
"""
import argparse
import os
import sys
import math
import time

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import numpy as np
from PIL import Image

from services.meteor.detection_scale import make_scale
from services.meteor.frame_stack import FrameStack
from services.meteor.noise import DiffNoiseEMA, noise_to_threshold
from services.meteor.detector import detect_meteors, annotate_image, MeteorDetection
from services.meteor.persistence import PersistenceFilter


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


def _load_frames(directory: str):
    files = sorted(
        f for f in os.listdir(directory)
        if os.path.splitext(f)[1].lower() in _IMAGE_EXTS
    )
    return [os.path.join(directory, f) for f in files]


def _to_gray_det(path: str, det_long_side: int) -> tuple:
    """Load image, downscale to detection size, return (gray_arr, full_pil)."""
    img = Image.open(path).convert("RGB")
    factor = min(1.0, det_long_side / max(img.width, img.height))
    if factor < 1.0:
        det = img.resize(
            (max(1, int(img.width * factor)), max(1, int(img.height * factor))),
            Image.Resampling.LANCZOS,
        ).convert("L")
    else:
        det = img.convert("L")
    gray_arr = np.array(det, dtype=np.uint8)
    return gray_arr, img, factor


def run(args):
    frames = _load_frames(args.directory)
    if not frames:
        print(f"No images found in {args.directory}")
        return

    out_dir = os.path.join(args.directory, "replay_out") if args.save else None
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    stack = FrameStack(maxlen=args.stack)
    noise_ema = DiffNoiseEMA()
    pf = PersistenceFilter(suppress_frames=args.suppress_frames)

    total_released = 0
    total_planes = 0
    frame_idx = 0
    # Image of the frame whose candidates are currently held — released
    # meteors must be annotated on THAT frame (streak is absent from the next).
    held_img = None

    for i, path in enumerate(frames):
        fname = os.path.basename(path)
        try:
            gray_arr, full_img, factor = _to_gray_det(path, args.det_long_side)
        except Exception as exc:
            print(f"[{i:04d}] {fname}: load error — {exc}")
            continue

        scale = make_scale(gray_arr.shape[1], full_img.width)
        stack.push(gray_arr)
        frame_idx += 1

        if not stack.full:
            print(f"[{i:04d}] {fname}: warming stack ({stack.count}/{stack.maxlen})")
            continue

        transient = stack.transient_map()
        hot = stack.hot_mask()
        masked = transient.copy()
        masked[hot > 0] = 0

        sigma = noise_ema.update(transient)
        threshold = noise_to_threshold(sigma, args.sensitivity)

        detections = detect_meteors(
            Image.fromarray(masked),
            min_length=int(args.min_length * factor),
            threshold=threshold,
            max_nonline_prob=args.max_nonline_prob,
        )

        # Absolute length ceiling — sky-spanning streaks are satellite/plane passes
        max_len_det = args.max_length_frac * masked.shape[1]
        detections = [d for d in detections if d.length <= max_len_det]

        print(f"[{i:04d}] {fname}: sigma={sigma:.1f} thresh={threshold} "
              f"raw_dets={len(detections)}")

        # Scale detections back to full-res coords
        kept = []
        for d in detections:
            inv = 1.0 / factor if factor < 1.0 else 1.0
            d_full = MeteorDetection(
                x1=int(d.x1 * inv), y1=int(d.y1 * inv),
                x2=int(d.x2 * inv), y2=int(d.y2 * inv),
                length=d.length * inv,
                angle_deg=d.angle_deg,
                nonline_prob=d.nonline_prob,
            )
            print(f"    det: ({d_full.x1},{d_full.y1})→({d_full.x2},{d_full.y2}) "
                  f"len={d_full.length:.0f}px angle={d_full.angle_deg:.0f}° "
                  f"nonline={d_full.nonline_prob:.3f}")
            kept.append(d_full)

        prev_held_img = held_img
        released, planes = pf.update(kept, frame_idx)
        held_img = full_img if kept else None
        total_planes += planes
        if planes:
            print(f"    -> PLANE: {planes} track(s) suppressed")
        if released:
            total_released += len(released)
            print(f"    => METEOR: {len(released)} detection(s) released")
            for r in released:
                print(f"       ({r.x1},{r.y1})→({r.x2},{r.y2}) len={r.length:.0f}px")

            if out_dir or args.show:
                annotated = annotate_image(prev_held_img or full_img, released)
                if out_dir:
                    out_path = os.path.join(out_dir, f"meteor_{i:04d}_{fname}")
                    annotated.save(out_path, "JPEG", quality=90)
                    print(f"       saved → {out_path}")
                if args.show:
                    import cv2
                    cv2_img = cv2.cvtColor(np.array(annotated), cv2.COLOR_RGB2BGR)
                    cv2.imshow("Meteor Replay", cv2_img)
                    key = cv2.waitKey(0 if args.pause else 100)
                    if key == ord('q'):
                        break

    # Flush held candidates at end of sequence
    held = pf.flush()
    if held:
        print(f"\nEnd of sequence: {len(held)} candidate(s) held (no next frame to verify)")
        total_released += len(held)

    print(f"\n{'='*60}")
    print(f"Frames processed : {frame_idx}")
    print(f"Meteors released : {total_released}")
    print(f"Planes rejected  : {total_planes}")
    print(f"{'='*60}")

    if args.show:
        import cv2
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description="PFR Sentinel meteor detection replay")
    parser.add_argument("directory", help="Directory of frame images (JPEG/PNG)")
    parser.add_argument("--det-long-side", type=int, default=1280,
                        help="Detection resolution long side (default: 1280)")
    parser.add_argument("--stack", type=int, default=6,
                        help="FrameStack depth (default: 6)")
    parser.add_argument("--sensitivity", choices=["high", "normal", "low"],
                        default="normal", help="Noise sensitivity (default: normal)")
    parser.add_argument("--min-length", type=float, default=100,
                        help="Minimum streak length in full-res pixels (default: 100)")
    parser.add_argument("--max-nonline-prob", type=float, default=0.30,
                        help="Max nonlinearity probability to pass (default: 0.30)")
    parser.add_argument("--max-length-frac", type=float, default=0.5,
                        help="Reject streaks longer than this fraction of frame width (default: 0.5)")
    parser.add_argument("--suppress-frames", type=int, default=30,
                        help="Plane suppression duration in frames (default: 30)")
    parser.add_argument("--save", action="store_true",
                        help="Save annotated meteor images to <dir>/replay_out/")
    parser.add_argument("--show", action="store_true",
                        help="Show frames in OpenCV window (q to quit)")
    parser.add_argument("--pause", action="store_true",
                        help="With --show: wait for keypress after each meteor frame")
    args = parser.parse_args()

    if not os.path.isdir(args.directory):
        print(f"Error: '{args.directory}' is not a directory")
        sys.exit(1)

    run(args)


if __name__ == "__main__":
    main()
