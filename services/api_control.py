"""
Pure capture-control logic for the HTTP API.

Mirror image of ``services/api_status.py``.  Where that module turns a pushed
capture snapshot into the ``/status`` payload, this one turns an inbound
control request into a validated command and a result payload — and it is
equally ignorant of Qt, sockets, and the capture stack itself.

The seam that keeps it that way: the app *registers a command handler* with the
web server (exactly as it already *pushes* a status snapshot).  The HTTP thread
validates here, hands the command to the handler, and the handler marshals onto
the thread that actually owns capture.  Nothing in this file may start, stop,
or touch capture.

Everything is pure — plain values in, dicts out, with ``now`` and the clock /
sleep / snapshot-reader injected — so idempotency, the ``wait`` semantics and
the timeout path are all unit-testable without a server, a camera, or real
elapsed time.  The :data:`CONTROL_ROUTES` catalog is consumed verbatim by
``services/api_docs.py`` so the OpenAPI spec cannot drift from the behaviour
implemented below.
"""
from __future__ import annotations

import json

# Sentinel for "no baseline captured", distinct from a baseline of None.
_UNSET = object()

COMMAND_START = "start"
COMMAND_STOP = "stop"
COMMANDS = (COMMAND_START, COMMAND_STOP)

# Outcome values in the `result` field of a control response.
RESULT_STARTED = "started"
RESULT_STOPPED = "stopped"
RESULT_ALREADY_RUNNING = "already_running"
RESULT_ALREADY_STOPPED = "already_stopped"
RESULT_PENDING = "pending"    # command issued, `wait` was false — state unconfirmed
RESULT_TIMEOUT = "timeout"    # command issued, target state not reached in time
RESULT_FAILED = "failed"      # capture reported an error while we waited

# Capture states (see api_status.CAPTURE_FIELDS) that count as "capture is on".
# `outside_window` is included deliberately: a scheduled run that is enabled but
# waiting for its window HAS started — blocking a sequence until dusk would be
# wrong.
_STARTED_STATES = frozenset({"capturing", "waiting", "calibrating", "outside_window", "recovering"})
_STOPPED_STATES = frozenset({"stopped"})
_ERROR_STATES = frozenset({"error"})

# `wait` bounds. The floor stops a caller from passing 0 and getting the
# no-wait path by the back door; the ceiling stops a request thread being
# parked indefinitely (W6 — threads are unbounded).
TIMEOUT_DEFAULT = 30
TIMEOUT_MIN = 1
TIMEOUT_MAX = 300

# How often wait_for_target re-reads the snapshot. Fast enough that a sequencer
# step doesn't feel laggy, slow enough not to spin.
POLL_INTERVAL_SEC = 0.25

# Largest control request body accepted. These bodies are two scalar fields;
# anything larger is a client bug or an attempt to tie up a request thread.
MAX_BODY_BYTES = 4096


# Catalog of the control routes, reused verbatim by
# api_docs.build_openapi_spec so the documented surface and the implemented
# surface come from one source of truth.
CONTROL_ROUTES = [
    {
        "path": "/capture/start",
        "method": "post",
        "command": COMMAND_START,
        "summary": "Start capture",
        "description": (
            "Start capture in the app's configured mode. Idempotent — starting "
            "an already-running capture returns 200 with result "
            "'already_running'. Requires a bearer token."
        ),
    },
    {
        "path": "/capture/stop",
        "method": "post",
        "command": COMMAND_STOP,
        "summary": "Stop capture",
        "description": (
            "Stop capture. Idempotent — stopping an already-stopped capture "
            "returns 200 with result 'already_stopped'. Requires a bearer token."
        ),
    },
    {
        "path": "/capture",
        "method": "get",
        "command": None,
        "summary": "Current capture control state",
        "description": (
            "Convenience alias for the 'capture' block of /status, so a control "
            "client needs only one path prefix. Requires a bearer token."
        ),
    },
]

# Fields in a control response, documented alongside CONTROL_ROUTES.
CONTROL_RESULT_FIELDS = [
    ("command", "string", "The command that was issued: 'start' or 'stop'."),
    ("result", "string",
     "Outcome: 'started', 'stopped', 'already_running', 'already_stopped', "
     "'pending', 'timeout', or 'failed'."),
    ("changed", "boolean",
     "Whether capture state actually changed — true only for 'started'/'stopped'."),
    ("issued", "boolean",
     "Whether a command was handed to the app (false for idempotent no-ops)."),
    ("state", "string", "Capture state reached, from the /status 'capture' block."),
    ("running", "boolean", "Whether capture is producing frames."),
    ("enabled", "boolean", "Whether capture is enabled in the app."),
    ("waited", "boolean", "Whether the request blocked for the target state."),
    ("wait_seconds", "number", "Seconds spent waiting; 0 when wait was false."),
    ("message", "string", "Human-readable outcome, safe to surface in a UI."),
]


def snapshot_state(snapshot) -> str:
    """The fine-grained capture state from a snapshot, defaulting to stopped."""
    if not snapshot:
        return "stopped"
    return str(snapshot.get("state") or "stopped")


def is_at_target(snapshot, command: str) -> bool:
    """Whether ``snapshot`` already satisfies ``command``.

    This is what makes the endpoints idempotent, and it is a hard requirement
    rather than polish: a sequence that re-runs "Start" must not error, and an
    aborting sequence may legitimately fire "Stop" twice.
    """
    snapshot = snapshot or {}
    state = snapshot_state(snapshot)

    if command == COMMAND_START:
        return bool(snapshot.get("enabled")) and state in _STARTED_STATES
    if command == COMMAND_STOP:
        return not snapshot.get("enabled") and not snapshot.get("running")
    return False


def is_failed(snapshot, command: str, baseline_error=_UNSET) -> bool:
    """Whether the command has failed outright, so waiting further is pointless.

    ``baseline_error`` is ``last_error`` as it stood when the command was
    issued. A *new* error appearing while we wait is a real failure; the stale
    one already there is not — without that distinction, any start after a
    previous camera fault would report failure before the app had even
    processed the command.
    """
    if command != COMMAND_START:
        return False
    snapshot = snapshot or {}
    if snapshot_state(snapshot) in _ERROR_STATES:
        return True
    recovery = snapshot.get("recovery") or {}
    if recovery.get("unrecoverable"):
        return True
    if baseline_error is _UNSET:
        return False
    # The GUI start path can fail without ever reaching state="error": it
    # returns early, leaving enabled False with only last_error set.
    current = snapshot.get("last_error")
    return bool(current) and current != baseline_error and not snapshot.get("enabled")


def parse_request(raw_body):
    """Validate a control request body into ``(params, error)``.

    An empty body is valid and yields the defaults — a sequencer step or a bare
    ``curl -X POST`` should not have to send JSON.  Exactly one of ``params`` /
    ``error`` is non-``None``; ``error`` is ``(http_status, message)``.
    """
    params = {"wait": True, "timeout": TIMEOUT_DEFAULT}

    if raw_body is None:
        return params, None
    if isinstance(raw_body, (bytes, bytearray)):
        if len(raw_body) > MAX_BODY_BYTES:
            return None, (413, "Request body too large.")
        try:
            raw_body = raw_body.decode("utf-8")
        except UnicodeDecodeError:
            return None, (400, "Request body must be UTF-8 JSON.")

    if isinstance(raw_body, str):
        if not raw_body.strip():
            return params, None
        try:
            body = json.loads(raw_body)
        except (json.JSONDecodeError, ValueError):
            return None, (400, "Request body must be valid JSON.")
    else:
        body = raw_body

    if not isinstance(body, dict):
        return None, (400, "Request body must be a JSON object.")

    if "wait" in body:
        wait = body["wait"]
        if not isinstance(wait, bool):
            return None, (400, "'wait' must be a boolean.")
        params["wait"] = wait

    if "timeout" in body:
        timeout = body["timeout"]
        # bool is an int subclass — reject it explicitly, a caller passing
        # `true` here means something they will not get.
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            return None, (400, "'timeout' must be a number of seconds.")
        if timeout < TIMEOUT_MIN or timeout > TIMEOUT_MAX:
            return None, (
                400,
                f"'timeout' must be between {TIMEOUT_MIN} and {TIMEOUT_MAX} seconds.",
            )
        params["timeout"] = float(timeout)

    return params, None


def wait_for_target(command, read_snapshot, *, timeout, monotonic, sleep,
                    poll_interval=POLL_INTERVAL_SEC, baseline_error=_UNSET):
    """Poll until ``command``'s target state is reached, or ``timeout`` elapses.

    This is what makes a sequencer instruction deterministic: the sequence must
    not advance until capture is genuinely running.  The clock, the sleep and
    the snapshot reader are injected so the reached / timed-out / failed paths
    are testable in microseconds.

    Returns ``(snapshot, outcome)`` where outcome is ``"reached"``,
    ``"timeout"`` or ``"failed"``.
    """
    deadline = monotonic() + float(timeout)
    snapshot = read_snapshot()

    while True:
        if is_at_target(snapshot, command):
            return snapshot, "reached"
        if is_failed(snapshot, command, baseline_error):
            return snapshot, "failed"
        if monotonic() >= deadline:
            return snapshot, "timeout"
        sleep(poll_interval)
        snapshot = read_snapshot()


def _message(command, result, state):
    if result == RESULT_ALREADY_RUNNING:
        return "Capture is already running."
    if result == RESULT_ALREADY_STOPPED:
        return "Capture is already stopped."
    if result == RESULT_STARTED:
        return "Capture started."
    if result == RESULT_STOPPED:
        return "Capture stopped."
    if result == RESULT_PENDING:
        verb = "start" if command == COMMAND_START else "stop"
        return f"Capture {verb} requested; state not confirmed (wait was false)."
    if result == RESULT_TIMEOUT:
        target = "running" if command == COMMAND_START else "stopped"
        return f"Timed out waiting for capture to reach '{target}' (state is '{state}')."
    return f"Capture command failed (state is '{state}')."


# Outcomes where capture state genuinely moved. A timeout or a failure did not
# change anything, and a no-op did not either — reporting `changed` for those
# would make the field meaningless to a client deciding whether to act.
_CHANGED_RESULTS = frozenset({RESULT_STARTED, RESULT_STOPPED})


def build_result(command, snapshot, *, result, issued, waited=False, wait_seconds=0.0) -> dict:
    """Shape a control response body. Plain values in, dict out.

    ``issued`` says whether the command reached the app; ``changed`` is derived
    from the outcome, so the two cannot drift apart.
    """
    snapshot = snapshot or {}
    state = snapshot_state(snapshot)
    return {
        "command": command,
        "result": result,
        "changed": result in _CHANGED_RESULTS,
        "issued": bool(issued),
        "state": state,
        "running": bool(snapshot.get("running")),
        "enabled": bool(snapshot.get("enabled")),
        "waited": bool(waited),
        "wait_seconds": round(float(wait_seconds), 2),
        "message": _message(command, result, state),
    }


def result_for_outcome(command, outcome):
    """Map a :func:`wait_for_target` outcome to a ``RESULT_*`` value."""
    if outcome == "reached":
        return RESULT_STARTED if command == COMMAND_START else RESULT_STOPPED
    if outcome == "failed":
        return RESULT_FAILED
    return RESULT_TIMEOUT


def http_status_for_result(result: str) -> int:
    """HTTP status for a control outcome.

    Every idempotent no-op and every genuine state change is a 200 — a sequence
    re-running "Start" must not see an error.  Only a real failure or an
    unconfirmed state after waiting is non-2xx.
    """
    if result == RESULT_FAILED:
        return 500
    if result == RESULT_TIMEOUT:
        return 504
    return 200
