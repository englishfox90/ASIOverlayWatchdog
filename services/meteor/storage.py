"""
Meteor Detection Storage
Appends detection events to a JSONL log file (one JSON object per line).
Also saves plain 300×300 thumbnail crops for display in the UI — the
highlight overlay is drawn dynamically in the UI so the raw streak can
always be inspected underneath.
"""
import json
import os
from datetime import datetime
from typing import Dict, List

from PIL import Image

from .detector import MeteorDetection

_LOG_FILENAME = "meteor_detections.jsonl"


def resolve_log_path(meteor_config):
    """Canonical meteor-log path: the configured ``log_file`` or the app-data
    default. Single source of truth for both the writer (meteor controller) and
    readers (the library timeline)."""
    log_file = (meteor_config or {}).get("log_file", "").strip()
    if log_file:
        return log_file
    from services.app_config import get_app_data_dir
    return os.path.join(get_app_data_dir(), _LOG_FILENAME)


def log_detections(
    log_path: str,
    detections: List[MeteorDetection],
    image_filename: str = "",
) -> None:
    """
    Append a detection event to *log_path*.

    Creates parent directories and the file if they do not exist.
    Silently ignores I/O errors — detection logging is best-effort.
    """
    if not log_path:
        return

    parent = os.path.dirname(log_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "image": image_filename,
        "count": len(detections),
        "detections": [
            {
                "x1": d.x1, "y1": d.y1,
                "x2": d.x2, "y2": d.y2,
                "length": round(d.length, 1),
                "angle": round(d.angle_deg, 1),
            }
            for d in detections
        ],
    }

    try:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def log_event(log_path: str, payload: dict) -> None:
    """Append a free-form event (e.g. confirmation) to the detection log."""
    if not log_path:
        return
    parent = os.path.dirname(log_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except OSError:
        pass


def save_thumbnail(
    image: Image.Image,
    detection: MeteorDetection,
    thumb_dir: str,
    timestamp: str,
    size: int = 300,
) -> Dict[str, object]:
    """
    Crop a *size*×*size* region centred on *detection* from *image* and save
    it as a JPEG. No annotation is baked in — the UI draws the highlight
    overlay on top so the raw streak remains inspectable.

    Returns a dict with the saved path plus crop offset and crop-local line
    coordinates so the UI can draw the overlay at the right position:

        {
          "path": str,            # empty on failure
          "thumb_left": int, "thumb_top": int, "thumb_size": int,
          "line_x1": int, "line_y1": int, "line_x2": int, "line_y2": int,
          "length_px": int,
        }
    """
    empty: Dict[str, object] = {
        "path": "",
        "thumb_left": 0, "thumb_top": 0, "thumb_size": size,
        "line_x1": 0, "line_y1": 0, "line_x2": 0, "line_y2": 0,
        "length_px": int(round(detection.length)),
    }
    if not thumb_dir:
        return empty
    try:
        os.makedirs(thumb_dir, exist_ok=True)

        mid_x = (detection.x1 + detection.x2) // 2
        mid_y = (detection.y1 + detection.y2) // 2
        half = size // 2

        left   = max(0, mid_x - half)
        top    = max(0, mid_y - half)
        right  = min(image.width,  mid_x + half)
        bottom = min(image.height, mid_y + half)

        crop = image.crop((left, top, right, bottom))

        # Pad to size×size with black if the crop is near an edge
        if crop.size != (size, size):
            padded = Image.new("RGB", (size, size), (0, 0, 0))
            padded.paste(crop, (0, 0))
            crop = padded

        lx1 = max(0, min(size - 1, detection.x1 - left))
        ly1 = max(0, min(size - 1, detection.y1 - top))
        lx2 = max(0, min(size - 1, detection.x2 - left))
        ly2 = max(0, min(size - 1, detection.y2 - top))

        safe_ts = timestamp.replace(":", "-").replace("T", "_")
        path = os.path.join(thumb_dir, f"meteor_{safe_ts}.jpg")
        crop.save(path, "JPEG", quality=90)

        return {
            "path": path,
            "thumb_left": left, "thumb_top": top, "thumb_size": size,
            "line_x1": lx1, "line_y1": ly1, "line_x2": lx2, "line_y2": ly2,
            "length_px": int(round(detection.length)),
        }

    except Exception:
        return empty
