"""
Pure capture-status logic for the HTTP API.

The web server (``services/web_output.py``) is deliberately ignorant of capture:
it only ever receives image bytes.  The app *pushes* a discrete capture snapshot
into the server, and at request time the server asks this module to turn that
snapshot — plus the current image age and clock — into the ``capture`` and
``health`` blocks of ``/status``.

Everything here is pure (plain values in, dicts out; no Qt, no I/O, ``now`` and
``image_age`` are passed in) so it is cheap to unit-test across the full matrix
of capture states.  The same ``CAPTURE_FIELDS`` catalog that documents the API
in ``services/api_docs.py`` is defined here, so the docs cannot drift from the
payload this module produces.
"""
from __future__ import annotations

# --- Health status values -------------------------------------------------
HEALTH_OK = "ok"                  # capture running and producing fresh frames
HEALTH_IDLE = "idle"             # intentionally not capturing (off / outside window)
HEALTH_DEGRADED = "degraded"     # enabled + running but frames have stalled
HEALTH_RECOVERING = "recovering"  # auto-recovery in progress
HEALTH_ERROR = "error"           # capture failed / unrecoverable

# Multiplier on the expected interval before a running camera is judged stalled.
# A couple of missed frames is normal jitter; 3× the cadence is a real outage.
_STALL_INTERVAL_MULTIPLIER = 3


# Catalog of the fields inside the ``capture`` block, reused verbatim by
# api_docs.build_openapi_spec so the OpenAPI schema and /docs page are generated
# from the same source of truth as the payload below.
CAPTURE_FIELDS = [
    ("mode", "string", "Capture mode: 'camera', 'watch', or 'idle'."),
    ("enabled", "boolean", "Whether capture is currently enabled in the app."),
    ("running", "boolean", "Whether capture is actively producing frames right now."),
    ("state", "string",
     "Fine-grained capture state, e.g. 'capturing', 'waiting', 'calibrating', "
     "'recovering', 'outside_window', 'stopped', 'error'."),
    ("interval_seconds", "number",
     "Configured seconds between captures (camera mode); null in watch mode."),
    ("effective_interval_seconds", "number",
     "Interval actually in effect now, honouring variable-rate schedules; null in watch mode."),
    ("schedule", "object",
     "Scheduled-window config: {mode, start_time, end_time, in_window, window_interval_seconds}. "
     "null when no schedule applies."),
    ("last_capture_age_seconds", "integer",
     "Seconds since the last successful capture, or null if none yet."),
    ("next_capture_in_seconds", "integer",
     "Estimated seconds until the next capture (camera mode, running); null if not predictable."),
    ("next_capture_expected_epoch", "number",
     "Unix timestamp of the next expected capture; null if not predictable."),
    ("recovery", "object",
     "Auto-recovery state: {in_progress, attempts, unrecoverable}."),
    ("last_error", "string", "Most recent capture error message, or null."),
    ("last_error_epoch", "number",
     "Unix timestamp of the most recent capture error, or null. Lets a client "
     "tell a NEW failure from the same fault reported again — the message text "
     "cannot, because a repeated fault reads identically."),
]


def build_capture_snapshot(
    *,
    mode: str = "idle",
    enabled: bool = False,
    running: bool = False,
    state: str = "stopped",
    interval_seconds=None,
    effective_interval_seconds=None,
    schedule=None,
    last_capture_epoch=None,
    last_error=None,
    last_error_epoch=None,
    recovery=None,
) -> dict:
    """Normalize the discrete capture snapshot the feeders push to the server.

    Plain values in, dict out — no clock, no derived/time-relative fields (those
    are computed at request time by :func:`derive_status_view`).
    """
    return {
        "mode": mode,
        "enabled": bool(enabled),
        "running": bool(running),
        "state": state,
        "interval_seconds": interval_seconds,
        "effective_interval_seconds": effective_interval_seconds,
        "schedule": schedule,
        "last_capture_epoch": last_capture_epoch,
        "last_error": last_error,
        "last_error_epoch": last_error_epoch,
        "recovery": recovery or {"in_progress": False, "attempts": 0, "unrecoverable": False},
    }


def _stall_threshold(snapshot: dict, stale_threshold: float) -> float:
    """Seconds without a frame before a running camera is judged stalled."""
    interval = snapshot.get("effective_interval_seconds") or snapshot.get("interval_seconds")
    if interval and interval > 0:
        return max(float(stale_threshold), float(interval) * _STALL_INTERVAL_MULTIPLIER)
    return float(stale_threshold)


def derive_health(snapshot: dict, image_age, now: float, stale_threshold: float = 300.0) -> dict:
    """Compute the overall capture health from a snapshot + current image age.

    Returns ``{"status": <HEALTH_*>, "reasons": [str, ...]}``.  This is the
    signal the bare ``/status`` lacked: it goes non-``ok`` the moment capture is
    off, paused, stalled, recovering, or failed.
    """
    recovery = snapshot.get("recovery") or {}

    if not snapshot.get("enabled"):
        return {"status": HEALTH_IDLE, "reasons": ["capture is not enabled"]}

    if recovery.get("unrecoverable"):
        return {"status": HEALTH_ERROR,
                "reasons": ["camera unrecoverable — manual restart required"]}

    if recovery.get("in_progress"):
        attempts = recovery.get("attempts", 0)
        return {"status": HEALTH_RECOVERING,
                "reasons": [f"capture auto-recovery in progress (attempt {attempts})"]}

    # A recorded error while not actively capturing is a real failure.
    if snapshot.get("last_error") and not snapshot.get("running"):
        return {"status": HEALTH_ERROR, "reasons": [str(snapshot["last_error"])]}

    # Enabled but intentionally paused outside the scheduled window — expected,
    # not a fault.
    schedule = snapshot.get("schedule") or {}
    if schedule and schedule.get("mode") == "gated" and schedule.get("in_window") is False:
        return {"status": HEALTH_IDLE, "reasons": ["outside scheduled capture window"]}

    if not snapshot.get("running"):
        return {"status": HEALTH_IDLE, "reasons": ["capture is enabled but not running"]}

    # Running camera that has stopped producing frames — the outage signal that
    # was previously invisible.  Watch mode has no fixed cadence, so staleness
    # there is not necessarily a fault.
    if snapshot.get("mode") != "watch" and image_age is not None:
        threshold = _stall_threshold(snapshot, stale_threshold)
        if image_age > threshold:
            return {"status": HEALTH_DEGRADED,
                    "reasons": [f"no new frame for {int(image_age)}s — capture may be stalled"]}

    return {"status": HEALTH_OK, "reasons": []}


def derive_status_view(snapshot, *, image_age, now: float, stale_threshold: float = 300.0) -> dict:
    """Build the request-time ``capture`` + ``health`` blocks for ``/status``.

    ``snapshot`` is whatever the feeders last pushed (possibly empty before the
    first push).  Time-relative fields (ages, next-capture countdown) are
    computed here from ``now`` so they are always current regardless of push
    cadence.
    """
    if not snapshot:
        # No capture feed yet (e.g. web server up before capture starts).
        snapshot = build_capture_snapshot()

    capture = dict(snapshot)
    last_epoch = snapshot.get("last_capture_epoch")

    if last_epoch is not None:
        capture["last_capture_age_seconds"] = max(0, int(now - last_epoch))
    else:
        capture["last_capture_age_seconds"] = None

    # Next-capture estimate: only meaningful for a running camera on a fixed cadence.
    interval = snapshot.get("effective_interval_seconds") or snapshot.get("interval_seconds")
    if (snapshot.get("running") and snapshot.get("mode") != "watch"
            and interval and last_epoch is not None):
        next_epoch = last_epoch + float(interval)
        capture["next_capture_expected_epoch"] = next_epoch
        capture["next_capture_in_seconds"] = max(0, int(round(next_epoch - now)))
    else:
        capture["next_capture_expected_epoch"] = None
        capture["next_capture_in_seconds"] = None

    # Internal-only field — not part of the documented payload.
    capture.pop("last_capture_epoch", None)

    health = derive_health(snapshot, image_age, now, stale_threshold)
    return {"capture": capture, "health": health}
