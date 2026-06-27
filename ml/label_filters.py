#!/usr/bin/env python3
"""Filter logic for the labeling tool — pure, Qt-free, independently testable.

Lets the labeler narrow the sample set to frames worth revisiting, e.g. frames
labeled "Partly Cloudy"/"Overcast" on a night the weather service reported a
*clear* sky — the signature of moon-glow / twilight wash being read as cloud.
"""
from dataclasses import dataclass

SKY_LABELS = ["Clear", "Partly Cloudy", "Overcast"]
# A label is "suspect" when it claims cloud but the weather service called it clear.
SUSPECT_LABELS = ("Partly Cloudy", "Overcast")


@dataclass
class FilterCriteria:
    sky_label: str = "Any"      # Any | Clear | Partly Cloudy | Overcast | Unlabeled
    weather: str = "Any"        # Any | Clear sky | Cloudy sky
    bright_moon_up: bool = False
    suspect_only: bool = False

    def is_active(self) -> bool:
        return (self.sky_label != "Any" or self.weather != "Any"
                or self.bright_moon_up or self.suspect_only)


def extract_filter_meta(cal: dict) -> dict:
    """Pull the handful of fields the filters need from a calibration JSON.

    Cached once per frame so navigation/counting never re-reads the file.
    """
    labels = cal.get("labels") or {}
    w = cal.get("weather_context") or {}
    m = cal.get("moon_context") or {}
    rs = cal.get("roof_state") or {}
    return {
        "sky_label": labels.get("sky_condition") or "",
        "has_label": bool(labels.get("labeled_at")),
        "wx_clear": w.get("is_clear"),            # True / False / None
        "wx_clouds": w.get("cloud_coverage_pct"),  # int or None
        "moon_bright": bool(m.get("is_bright_moon")),
        "moon_up": bool(m.get("moon_is_up")),
        "roof_open": rs.get("roof_open"),
    }


def is_suspect(meta: dict) -> bool:
    """Label claims cloud, but the weather service reported a clear sky."""
    return meta.get("sky_label") in SUSPECT_LABELS and meta.get("wx_clear") is True


def frame_matches(meta: dict, c: FilterCriteria) -> bool:
    if c.suspect_only and not is_suspect(meta):
        return False

    if c.sky_label == "Unlabeled":
        if meta.get("has_label"):
            return False
    elif c.sky_label not in ("Any", ""):
        if meta.get("sky_label") != c.sky_label:
            return False

    if c.weather == "Clear sky" and meta.get("wx_clear") is not True:
        return False
    if c.weather == "Cloudy sky" and meta.get("wx_clear") is not False:
        return False

    if c.bright_moon_up and not (meta.get("moon_bright") and meta.get("moon_up")):
        return False

    return True
