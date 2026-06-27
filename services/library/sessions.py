"""
Image library session grouping.

Aggregates archived frames into observing 'nights' for the Library UI. A night
is the natural unit an operator thinks in: frames from local noon to the next
local noon belong to the same night, so an evening-to-morning run is never split
at midnight. Pure read-side logic over the index — no file I/O — so it stays
unit-testable without disk or Qt.

The condition band shown on the session cards and the night scrubber is driven
by per-frame ``status``:
  • clear  — roof open + clear sky   (green)
  • cloudy — roof open + not clear   (amber)
  • closed — roof closed             (red)
  • gap    — a stretch with no captured frames (dark / hatched)
  • unknown — no roof/sky/weather signal stored for the frame (grey)
Roof + sky come from the ML service (when ``ml_models.enabled``); cloud cover
from the weather service is the fallback for "clear" when the sky model is N/A.
"""
import re
from datetime import datetime, timedelta

# A frame captured before local noon belongs to the previous calendar day's
# night (the run that started the evening before).
_NIGHT_CUTOFF_HOUR = 12

# A break between consecutive frames longer than this counts as a capture gap —
# an event worth surfacing (capture stopped, app restart), not normal cadence.
# Daytime cadence is one frame every ~10 min and nights are far more regular, so
# the threshold sits above the daytime interval: only a real >1h stall registers.
GAP_THRESHOLD_SECONDS = 3600  # 1 hour

# Cloud cover at or below this percent counts as "clear" when only weather data
# is available (no ML sky condition).
CLOUD_CLEAR_PERCENT = 30

# Per-frame condition band states.
STATUS_CLEAR = "clear"
STATUS_CLOUDY = "cloudy"
STATUS_CLOSED = "closed"
STATUS_GAP = "gap"
STATUS_UNKNOWN = "unknown"

_TEMP_RE = re.compile(r"-?\d+(?:\.\d+)?")


def night_key(epoch):
    """Local 'YYYY-MM-DD' key for the night a capture epoch belongs to."""
    dt = datetime.fromtimestamp(int(epoch))
    if dt.hour < _NIGHT_CUTOFF_HOUR:
        dt = dt - timedelta(days=1)
    return dt.strftime("%Y-%m-%d")


def _parse_float(text):
    """First float found in a string ('2.3' / '2.3 px' -> 2.3), or None."""
    if text is None or text == "":
        return None
    m = _TEMP_RE.search(str(text))
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def parse_temp_c(text):
    """Best-effort Celsius float from a stored temp display string, or None."""
    return _parse_float(text)


def best_seeing(rows):
    """The (label, fwhm) of the sharpest frame (lowest FWHM), or (None, None).

    Lower FWHM = better seeing, so 'best' is the minimum across the night.
    """
    best_fwhm = None
    label = None
    for r in rows:
        fwhm = _parse_float(r.get("fwhm"))
        if fwhm is not None and (best_fwhm is None or fwhm < best_fwhm):
            best_fwhm, label = fwhm, r.get("seeing")
    return label, best_fwhm


def _is_clear(condition, clouds):
    """Tri-state sky clarity: True / False / None (unknown).

    ML sky condition wins; cloud-cover percent is the fallback.
    """
    if condition:
        return str(condition).strip().lower() == "clear"
    if clouds is not None:
        try:
            return int(clouds) <= CLOUD_CLEAR_PERCENT
        except (TypeError, ValueError):
            return None
    return None


def roof_state(roof):
    """Normalise a stored roof string to 'open' / 'closed' / None."""
    if not roof:
        return None
    s = str(roof).strip().lower()
    if s.startswith("open"):
        return "open"
    if s.startswith("clos"):
        return "closed"
    return None


def frame_status(roof, condition, clouds):
    """Map a frame's roof/sky/cloud signal to a condition-band state."""
    state = roof_state(roof)
    if state == "closed":
        return STATUS_CLOSED
    clear = _is_clear(condition, clouds)
    if state == "open":
        return STATUS_CLEAR if clear else STATUS_CLOUDY
    # Roof unknown: still colour by sky if we have it, else grey.
    if clear is True:
        return STATUS_CLEAR
    if clear is False:
        return STATUS_CLOUDY
    return STATUS_UNKNOWN


def row_status(row):
    """Condition-band state for a brief/full index row."""
    return frame_status(row.get("roof"), row.get("condition"), row.get("clouds"))


def detect_gaps(rows, threshold=GAP_THRESHOLD_SECONDS):
    """Capture gaps in an ascending-by-time row list.

    Returns dicts ``{at, seconds, before_id, after_id}`` where ``at`` is the
    epoch of the last frame before the break.
    """
    gaps = []
    prev = None
    for r in rows:
        if prev is not None:
            delta = r["captured_at"] - prev["captured_at"]
            if delta > threshold:
                gaps.append({
                    "at": prev["captured_at"],
                    "seconds": int(delta),
                    "before_id": prev["id"],
                    "after_id": r["id"],
                })
        prev = r
    return gaps


def status_segments(rows, start_epoch, end_epoch, gap_threshold=GAP_THRESHOLD_SECONDS):
    """Compress a night into ``(frac_start, frac_end, status)`` runs.

    Fractions are 0-1 across ``[start_epoch, end_epoch]``. Consecutive frames of
    the same status merge into one run; a time break longer than ``gap_threshold``
    becomes a ``STATUS_GAP`` run. Both the session cards and the scrubber band
    render from this, so they always agree.
    """
    span = max(1, int(end_epoch) - int(start_epoch))

    def frac(epoch):
        return max(0.0, min(1.0, (epoch - start_epoch) / span))

    segments = []
    run_status = None
    run_start = 0.0
    prev = None
    for r in rows:
        st = row_status(r)
        f = frac(r["captured_at"])
        if prev is not None and (r["captured_at"] - prev["captured_at"]) > gap_threshold:
            if run_status is not None:
                segments.append((run_start, frac(prev["captured_at"]), run_status))
            segments.append((frac(prev["captured_at"]), f, STATUS_GAP))
            run_status, run_start = st, f
        elif st != run_status:
            if run_status is not None:
                segments.append((run_start, f, run_status))
            run_status, run_start = st, f
        prev = r

    if run_status is not None:
        segments.append((run_start, 1.0, run_status))
    if not segments:
        segments.append((0.0, 1.0, STATUS_UNKNOWN))
    return segments


def summarize_sessions(index, since=None):
    """Group archived frames into night sessions, newest night first.

    Each summary dict has: ``key, start_epoch, end_epoch, frame_count,
    cover_id, min_temp_c, max_temp_c, gaps, max_gap_seconds, band, clear_pct,
    roof_closed``.
    """
    rows = index.brief_rows(since=since)  # ascending by captured_at
    groups = {}
    for r in rows:
        groups.setdefault(night_key(r["captured_at"]), []).append(r)

    sessions = []
    for key, grp in groups.items():
        temps = [t for t in (parse_temp_c(r.get("temp")) for r in grp) if t is not None]
        gaps = detect_gaps(grp)
        cover = grp[len(grp) // 2]  # mid-night frame: usually a real sky shot
        statuses = [row_status(r) for r in grp]
        clear = sum(1 for s in statuses if s == STATUS_CLEAR)
        star_counts = [r["star_count"] for r in grp if r.get("star_count") is not None]
        seeing_label, seeing_fwhm = best_seeing(grp)
        sessions.append({
            "key": key,
            "start_epoch": grp[0]["captured_at"],
            "end_epoch": grp[-1]["captured_at"],
            "frame_count": len(grp),
            "cover_id": cover["id"],
            "min_temp_c": min(temps) if temps else None,
            "max_temp_c": max(temps) if temps else None,
            "gaps": gaps,
            "max_gap_seconds": max((g["seconds"] for g in gaps), default=0),
            "band": status_segments(grp, grp[0]["captured_at"], grp[-1]["captured_at"]),
            "clear_pct": round(100 * clear / len(grp)) if grp else None,
            "roof_closed": any(s == STATUS_CLOSED for s in statuses),
            "max_stars": max(star_counts) if star_counts else None,
            "best_seeing": seeing_label,
            "best_fwhm": seeing_fwhm,
        })
    sessions.sort(key=lambda s: s["start_epoch"], reverse=True)
    return sessions
