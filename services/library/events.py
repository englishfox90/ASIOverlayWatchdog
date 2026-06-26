"""
Library night events — the typed timeline behind 'Events Tonight'.

Merges three event sources for one night into a single time-sorted list the
night view renders as clickable links:
  • gap    — a break in capture longer than the gap threshold (from sessions)
  • roof   — a roof open/close transition between consecutive frames
  • meteor — a logged meteor detection matched to the frame it landed in

Pure read-side logic over the frame rows the library already holds, plus a
best-effort read of the meteor detection JSONL. No Qt, no config writes — so it
stays unit-testable without disk or a running app.
"""
import json
import os
from datetime import datetime

from .sessions import roof_state
from services.meteor.storage import resolve_log_path as resolve_meteor_log_path

EVENT_GAP = "gap"
EVENT_ROOF_OPEN = "roof_open"
EVENT_ROOF_CLOSED = "roof_closed"
EVENT_METEOR = "meteor"

# A meteor's logged timestamp is stamped at detection, a beat after the frame it
# came from was captured. Match within this window; drop hits with no frame near.
_METEOR_MATCH_TOLERANCE_SECONDS = 300


def roof_transitions(rows):
    """Roof open/close events: one per change in roof state across the night.

    Emitted at the first frame showing the new state, so clicking the event
    seeks to the frame where the roof changed. Frames with no roof signal are
    skipped — they neither start nor break a run.
    """
    events = []
    prev_state = None
    for r in rows:
        state = roof_state(r.get("roof"))
        if state is None:
            continue
        if prev_state is not None and state != prev_state:
            events.append({
                "type": EVENT_ROOF_OPEN if state == "open" else EVENT_ROOF_CLOSED,
                "at": r["captured_at"],
                "image_id": r["id"],
            })
        prev_state = state
    return events


def meteor_hits(rows, log_path):
    """Meteor detection events for this night, matched to the nearest frame.

    Reads the meteor detection JSONL (best-effort) and, for each entry that
    recorded at least one detection within the night's time span, attaches the
    id of the closest frame so the event is clickable. Entries with no frame
    within the match tolerance are dropped.
    """
    if not rows or not log_path or not os.path.isfile(log_path):
        return []

    times = [r["captured_at"] for r in rows]
    lo = times[0] - _METEOR_MATCH_TOLERANCE_SECONDS
    hi = times[-1] + _METEOR_MATCH_TOLERANCE_SECONDS

    events = []
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                count = entry.get("count")
                if count is None:
                    count = len(entry.get("detections") or [])
                if not count:
                    continue  # confirmation/free-form events carry no detections
                at = _epoch(entry.get("timestamp"))
                if at is None or at < lo or at > hi:
                    continue
                fid = _nearest_frame_id(rows, at)
                if fid is None:
                    continue
                events.append({
                    "type": EVENT_METEOR,
                    "at": at,
                    "image_id": fid,
                    "count": int(count),
                })
    except OSError:
        return events
    return events


def build_timeline(rows, gaps=None, meteors=None):
    """Merge gaps, roof transitions and meteor hits into one time-sorted list.

    ``gaps`` come from ``sessions.detect_gaps`` and ``meteors`` from
    ``meteor_hits`` (resolved off-thread by the controller); roof transitions are
    derived here from the rows. Each event carries ``at`` (epoch) and
    ``image_id`` (the frame to seek to when clicked).
    """
    events = list(roof_transitions(rows))
    for g in gaps or []:
        events.append({
            "type": EVENT_GAP,
            "at": g["at"],
            "image_id": g.get("after_id"),   # clicking a gap seeks past it
            "before_id": g.get("before_id"),  # pin sits at the frame before the break
            "seconds": g.get("seconds", 0),
        })
    events.extend(meteors or [])
    events.sort(key=lambda e: e["at"])
    return events


def _epoch(iso_ts):
    """Local epoch seconds from an ISO timestamp string, or None."""
    if not iso_ts:
        return None
    try:
        return int(datetime.fromisoformat(str(iso_ts)).timestamp())
    except (TypeError, ValueError):
        return None


def _nearest_frame_id(rows, at):
    """Id of the frame closest in time to ``at``, within the match tolerance."""
    best_id, best_diff = None, None
    for r in rows:
        diff = abs(r["captured_at"] - at)
        if best_diff is None or diff < best_diff:
            best_id, best_diff = r["id"], diff
    if best_diff is not None and best_diff <= _METEOR_MATCH_TOLERANCE_SECONDS:
        return best_id
    return None
