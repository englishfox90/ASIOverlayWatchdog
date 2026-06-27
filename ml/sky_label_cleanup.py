#!/usr/bin/env python3
"""Surface suspect sky labels for a cleanup pass (READ-ONLY).

Targets the residual moon-glow mislabels: roof-open frames labelled
"Partly Cloudy"/"Overcast" on a night the weather service reported a *clear*
sky. These are what teach the sky model the bad "moon-up -> cloudy" association
that blocks us from passing real moon metadata at inference time.

Produces, in <data_dir>/_label_cleanup/:
  - contact-sheet montages (asinh-stretched lum, sorted worst-first)
  - a CSV worklist with the model's current verdict as a triage hint

It does NOT modify any labels. Fix them in the labeling tool
(ml/labeling_tool.py) using the "Suspect only" filter, then retrain.

Usage:
    python ml/sky_label_cleanup.py
    python ml/sky_label_cleanup.py "D:\\Pier Camera ML Data" --no-model
"""
import argparse
import csv
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from astropy.io import fits
from PIL import Image, ImageDraw, ImageFont

SUSPECT_LABELS = ("Partly Cloudy", "Overcast")
THUMB = 360
COLS = 5
PAD = 6
CAP_H = 60
PER_SHEET = COLS * 6


def to_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.lower() in ("true", "1", "yes")
    return bool(v)


def asinh_thumb(fits_path, black, white, strength):
    with fits.open(fits_path) as h:
        data = h[0].data
    if data is None:
        raise ValueError("empty FITS")
    if data.ndim == 3:
        data = data.mean(axis=0)
    a = data.astype(np.float32)
    lo = np.percentile(a, 1.0) if black is None else black
    hi = np.percentile(a, 99.7) if white is None else white
    if hi <= lo:
        hi = lo + 1e-6
    a = np.clip((a - lo) / (hi - lo), 0, 1)
    s = strength or 20.0
    a = np.arcsinh(a * s) / np.arcsinh(s)
    img = Image.fromarray((a * 255).astype(np.uint8)).convert("RGB")
    img.thumbnail((THUMB, THUMB), Image.LANCZOS)
    return img


def model_verdict(classifier, fits_path, cal):
    """Sky model prediction with training-style (correct) metadata. None if off."""
    if classifier is None:
        return None
    ca = cal.get("corner_analysis") or {}
    st = cal.get("stretch") or {}
    tc = cal.get("time_context") or {}
    mc = cal.get("moon_context") or {}
    meta = {
        "corner_to_center_ratio": ca.get("corner_to_center_ratio", 1.0),
        "median_lum": st.get("median_lum", 0.0),
        "is_astronomical_night": 1 if tc.get("is_astronomical_night") else 0,
        "hour": tc.get("hour", 2),
        "moon_illumination": mc.get("illumination_pct", 0.0),
        "moon_is_up": to_bool(mc.get("moon_is_up")),
    }
    try:
        r = classifier.predict_from_fits(fits_path, meta)
        return r.sky_condition, float(r.sky_confidence)
    except Exception:
        return None


def collect(data_dir, classifier):
    rows = []
    for jf in glob.glob(os.path.join(data_dir, "calibration_*.json")):
        try:
            d = json.load(open(jf, encoding="utf-8"))
        except Exception:
            continue
        labels = d.get("labels") or {}
        if not labels.get("labeled_at") or not to_bool(labels.get("roof_open")):
            continue
        sc = labels.get("sky_condition")
        if sc not in SUSPECT_LABELS:
            continue
        w = d.get("weather_context") or {}
        if w.get("is_clear") is not True:        # only weather-clear == suspect
            continue
        ts = os.path.basename(jf).replace("calibration_", "").replace(".json", "")
        fpath = os.path.join(data_dir, f"lum_{ts}.fits")
        if not os.path.isfile(fpath):
            continue
        mc = d.get("moon_context") or {}
        st = d.get("stretch") or {}
        mv = model_verdict(classifier, fpath, d)
        rows.append({
            "ts": ts, "fits": fpath, "label": sc,
            "wx_clouds": w.get("cloud_coverage_pct"),
            "moon_pct": mc.get("illumination_pct"),
            "moon_up": to_bool(mc.get("moon_is_up")),
            "model_says": mv[0] if mv else "", "model_conf": mv[1] if mv else None,
            "black": st.get("black_point"), "white": st.get("white_point"),
            "asinh": st.get("recommended_asinh_strength") or 20.0,
        })
    # worst-first: model already disagrees (says Clear) => most likely a mislabel
    rows.sort(key=lambda r: (r["model_says"] != "Clear", r["ts"]))
    return rows


def caption(r):
    mp = f"{r['moon_pct']:.0f}%" if r["moon_pct"] is not None else "?"
    cc = f"{r['wx_clouds']}%" if r["wx_clouds"] is not None else "?"
    ms = r["model_says"] or "-"
    flag = "  <-- model: Clear" if r["model_says"] == "Clear" else ""
    return [f"{r['ts']}{flag}",
            f"label {r['label']} | wx clear {cc} | moon {mp}{'up' if r['moon_up'] else ''}",
            f"model: {ms}" + (f" ({r['model_conf']:.0%})" if r["model_conf"] is not None else "")]


def build_montages(rows, out_dir):
    try:
        font = ImageFont.truetype("arial.ttf", 12)
        fontb = ImageFont.truetype("arialbd.ttf", 12)
    except OSError:
        font = fontb = ImageFont.load_default()
    cell_w, cell_h = THUMB + PAD, THUMB + CAP_H + PAD
    sheets = []
    for s in range(0, len(rows), PER_SHEET):
        chunk = rows[s:s + PER_SHEET]
        rN = (len(chunk) + COLS - 1) // COLS
        canvas = Image.new("RGB", (COLS * cell_w + PAD, rN * cell_h + PAD), (18, 18, 22))
        draw = ImageDraw.Draw(canvas)
        for i, r in enumerate(chunk):
            cx = PAD + (i % COLS) * cell_w
            cy = PAD + (i // COLS) * cell_h
            try:
                thumb = asinh_thumb(r["fits"], r["black"], r["white"], r["asinh"])
            except Exception as e:
                thumb = Image.new("RGB", (THUMB, THUMB), (60, 0, 0))
                ImageDraw.Draw(thumb).text((8, 8), f"err {e}", fill=(255, 180, 180))
            canvas.paste(thumb, (cx + (THUMB - thumb.width) // 2, cy))
            mislabel = r["model_says"] == "Clear"
            draw.rectangle([cx - 1, cy - 1, cx + THUMB, cy + THUMB],
                           outline=(220, 60, 60) if mislabel else (90, 90, 100), width=2)
            for j, line in enumerate(caption(r)):
                draw.text((cx + 2, cy + THUMB + 3 + j * 18), line,
                          fill=(255, 220, 120) if (j == 0 and mislabel) else (200, 205, 215),
                          font=fontb if j == 0 else font)
        out = os.path.join(out_dir, f"suspect_sky_sheet{s // PER_SHEET + 1:02d}.png")
        canvas.save(out)
        sheets.append(out)
    return sheets


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data_dir", nargs="?", default=r"D:\Pier Camera ML Data")
    ap.add_argument("--no-model", action="store_true", help="Skip model triage (faster).")
    args = ap.parse_args()

    classifier = None
    if not args.no_model:
        try:
            from ml.sky_classifier import SkyClassifier
            mp = os.path.join(os.path.dirname(__file__), "models", "sky_classifier_v1.onnx")
            classifier = SkyClassifier.load(mp)
        except Exception as e:
            print(f"(model triage off: {e})")

    out_dir = os.path.join(args.data_dir, "_label_cleanup")
    os.makedirs(out_dir, exist_ok=True)
    rows = collect(args.data_dir, classifier)
    n_model_clear = sum(1 for r in rows if r["model_says"] == "Clear")

    print(f"Suspect frames (roof open, label Partly Cloudy/Overcast, weather CLEAR): {len(rows)}")
    if classifier is not None:
        print(f"  of those, model now predicts Clear (likely mislabel): {n_model_clear}")

    csv_path = os.path.join(out_dir, "suspect_sky_worklist.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "current_label", "wx_clouds_pct", "moon_pct", "moon_up",
                    "model_says", "model_conf", "fits"])
        for r in rows:
            w.writerow([r["ts"], r["label"], r["wx_clouds"], r["moon_pct"], r["moon_up"],
                        r["model_says"], r["model_conf"], r["fits"]])

    for s in build_montages(rows, out_dir):
        print("  montage:", s)
    print("  csv:    ", csv_path)
    print("\nReview the red-bordered cells, then fix labels in ml/labeling_tool.py "
          "('Suspect only' filter). Re-run after relabeling to confirm the set shrinks.")


if __name__ == "__main__":
    main()
