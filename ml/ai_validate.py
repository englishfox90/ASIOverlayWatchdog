#!/usr/bin/env python3
"""
Validate AI pre-labels against existing ground truth.

Because ai_prelabel.py sends only the image (no config) by default, the
ai_suggestion block is an independent prediction you can score against the data
you already have: human labels, the NINA roof state, and the weather API.

Reports agreement so you can see where the cheap model is reliable before you
trust it to pre-fill the labeling form.

Usage:
    python ml/ai_validate.py                       # validate on D:
    python ml/ai_validate.py --clean-only          # only image-only (no-hint) predictions
"""
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ml.labeling_io import find_sample_sets
from ml.review_tab import to_bool

CLEAR = {"Clear"}


def _is_clear(sky_condition: str) -> bool:
    return sky_condition in CLEAR


def _pct(hits: int, total: int) -> str:
    return f"{hits}/{total} ({hits / total:.0%})" if total else "n/a (0)"


def main():
    parser = argparse.ArgumentParser(description="Validate AI pre-labels vs ground truth")
    parser.add_argument("data_dir", nargs="?", default=r"D:\Pier Camera ML Data")
    parser.add_argument("--clean-only", action="store_true",
                        help="Only score predictions made without hints (hints_used=false)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"ERROR: directory not found: {data_dir}")
        sys.exit(1)

    roof_vs_human = [0, 0]      # [hits, total]
    roof_vs_nina = [0, 0]
    sky_exact = [0, 0]
    sky_clear_vs_human = [0, 0]
    sky_clear_vs_weather = [0, 0]
    n_with_ai = 0

    for sample in find_sample_sets(data_dir):
        if "calibration" not in sample:
            continue
        with open(sample["calibration"], "r") as f:
            cal = json.load(f)

        ai = cal.get("ai_suggestion")
        if not ai:
            continue
        # Legacy suggestions predate the hints_used stamp; treat unknown as not-clean.
        if args.clean_only and ai.get("hints_used") is not False:
            continue
        n_with_ai += 1

        ai_roof = bool(ai.get("roof_open"))
        ai_sky = ai.get("sky_condition", "") or ""

        labels = cal.get("labels", {})
        if labels.get("labeled_at"):
            if labels.get("roof_open") is not None:
                roof_vs_human[1] += 1
                roof_vs_human[0] += (ai_roof == to_bool(labels.get("roof_open")))
            lbl_sky = labels.get("sky_condition", "") or ""
            # Sky only meaningful when roof is open in BOTH views.
            if ai_roof and to_bool(labels.get("roof_open")) and lbl_sky:
                sky_exact[1] += 1
                sky_exact[0] += (ai_sky == lbl_sky)
                sky_clear_vs_human[1] += 1
                sky_clear_vs_human[0] += (_is_clear(ai_sky) == _is_clear(lbl_sky))

        rs = cal.get("roof_state", {})
        if rs.get("available") and rs.get("source") == "nina_api":
            roof_vs_nina[1] += 1
            roof_vs_nina[0] += (ai_roof == to_bool(rs.get("roof_open")))

        wc = cal.get("weather_context", {})
        if ai_roof and wc.get("available") and wc.get("is_clear") is not None:
            sky_clear_vs_weather[1] += 1
            sky_clear_vs_weather[0] += (_is_clear(ai_sky) == bool(wc.get("is_clear")))

    print(f"AI suggestions scored: {n_with_ai}"
          + (" (image-only)" if args.clean_only else ""))
    print("\nROOF OPEN/CLOSED")
    print(f"  vs human labels : {_pct(*roof_vs_human)}")
    print(f"  vs NINA roof API: {_pct(*roof_vs_nina)}")
    print("\nSKY (roof open only)")
    print(f"  vs human, exact 6-class : {_pct(*sky_exact)}")
    print(f"  vs human, clear-or-not  : {_pct(*sky_clear_vs_human)}")
    print(f"  vs weather, clear-or-not: {_pct(*sky_clear_vs_weather)}")


if __name__ == "__main__":
    main()
