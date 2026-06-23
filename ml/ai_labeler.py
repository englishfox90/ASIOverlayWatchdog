#!/usr/bin/env python3
"""
AI pre-labeler for PFR Sentinel lum frames (dev tool).

Sends a stretched lum FITS frame to a cheap vision model via OpenRouter and asks
for the two labels we actually care about: is the metal roof open, and what are
the clouds like. The result is stored as an `ai_suggestion` block in the
calibration JSON — it never overwrites a human label, it only pre-fills the form.

Requires the OPENROUTER_API_KEY environment variable. Model is configurable via
OPENROUTER_MODEL (defaults to google/gemini-2.5-flash).
"""
import os
import json
import time
import base64

import requests

from services.logger import app_logger
from ml.labeling_io import fits_to_jpeg_bytes

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-2.5-flash"

# Must match the LabelsWidget sky_condition combo box (minus the empty entry).
SKY_CONDITIONS = ["Clear", "Partly Cloudy", "Overcast"]

SYSTEM_PROMPT = f"""You are labelling monochrome luminance frames from an astrophotography \
pier camera that points at a fixed patch of sky through a roll-off metal roof. \
Judge ONLY from the image; the text context is a weak hint, not ground truth.

Decide two things:

1. roof_open: true if the open night sky is visible (stars, open sky, a clear \
exposed field of view). false if the metal roof / closed enclosure fills the \
frame and the sky is blocked (typically near-uniform, few or no stars, hard edges).

2. sky_condition: only meaningful when roof_open is true. Read cloud cover from \
the star field and sky texture:
   - Clear: mostly sharp pinpoint stars, dark clean background (a little haze or
     a few soft patches is still Clear).
   - Partly Cloudy: noticeable cloud patches blotting out parts of the field.
   - Overcast: most/all stars gone — large washed-out regions, uniform bright/grey
     murk, or diffuse fog/haze smearing the stars.
A bright moon can wash out faint stars WITHOUT clouds — a uniform soft glow with \
no distinct cloud edges may be moonlight, not cloud (if a moon hint is given, use \
it). If roof_open is false, set sky_condition to "" and clouds_visible to false.

Respond with ONLY a JSON object, no prose:
{{"roof_open": bool, "roof_confidence": 0.0-1.0, "sky_condition": one of \
{SKY_CONDITIONS} or "", "clouds_visible": bool, "sky_confidence": 0.0-1.0, \
"reasoning": "one short sentence"}}"""


def build_context_from_cal(cal: dict) -> dict:
    """Extract the (non-label) astronomical hints we may pass to the model.

    Only night/moon facts — never weather, roof_state, or existing labels, so the
    prediction stays independent of the answer when validated.
    """
    tc = cal.get("time_context", {})
    mc = cal.get("moon_context", {})
    return {
        "is_astronomical_night": tc.get("is_astronomical_night"),
        "moon_is_up": mc.get("moon_is_up"),
        "moon_illumination_pct": mc.get("illumination_pct"),
    }


def _context_hint(context: dict | None) -> str:
    if not context:
        return "No additional context."
    parts = []
    if context.get("is_astronomical_night") is not None:
        parts.append("astronomical night" if context["is_astronomical_night"]
                     else "not astronomical night (twilight/day)")
    if context.get("moon_is_up"):
        illum = context.get("moon_illumination_pct")
        if illum is not None:
            parts.append(f"moon is up ({illum:.0f}% illuminated)")
        else:
            parts.append("moon is up")
    else:
        parts.append("moon is down")
    return "Context hint (may be wrong): " + ", ".join(parts) + "."


TRANSIENT_STATUS = {429, 500, 502, 503, 504}


def label_lum_frame(fits_path, context: dict | None = None,
                    model: str | None = None, timeout: int = 60,
                    max_retries: int = 4) -> dict:
    """Call OpenRouter to label a single lum frame. Raises on API/parse failure.

    Retries transient failures (429 rate-limit, 5xx, network/timeout) with
    exponential backoff — important when many classifiers run concurrently.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY environment variable is not set")

    model = model or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)

    jpeg = fits_to_jpeg_bytes(fits_path)
    data_uri = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")

    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": _context_hint(context)},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ]},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Title": "PFR Sentinel AI Labeler",
    }

    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=timeout)
        except requests.RequestException:
            if attempt < max_retries:
                time.sleep(min(2 ** attempt, 30))
                continue
            raise
        if resp.status_code in TRANSIENT_STATUS and attempt < max_retries:
            time.sleep(min(2 ** attempt, 30))
            continue
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        parsed = _parse_response(content)
        parsed["model"] = model
        return parsed


def _parse_response(content: str) -> dict:
    """Parse the model's JSON, tolerating ```json fences and stray text."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in model reply: {content[:200]}")

    data = json.loads(text[start:end + 1])

    sky = data.get("sky_condition", "") or ""
    if sky and sky not in SKY_CONDITIONS:
        app_logger.warning(f"AI returned unknown sky_condition {sky!r}; clearing")
        sky = ""

    return {
        "roof_open": bool(data.get("roof_open", False)),
        "roof_confidence": float(data.get("roof_confidence", 0.0)),
        "sky_condition": sky,
        "clouds_visible": bool(data.get("clouds_visible", False)),
        "sky_confidence": float(data.get("sky_confidence", 0.0)),
        "reasoning": str(data.get("reasoning", "")),
    }
