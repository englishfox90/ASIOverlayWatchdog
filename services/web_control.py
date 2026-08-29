"""
HTTP route handlers for the capture-control endpoints.

Delegated from ``services/web_output.py`` exactly as ``services/web_library.py``
already is, so the server module stays under the size cap.  This file owns the
socket-facing half of capture control; the decision logic is in
``services/api_control.py`` and the auth logic in ``services/api_auth.py``,
both pure and unit-tested.

**The load-bearing constraint:** these functions run on an HTTP request thread.
They must never call ``start_capture()`` / ``stop_capture()`` directly — that
would touch Qt state from the wrong thread.  Instead the app registers a
command handler at startup (the mirror of how it pushes a status snapshot), and
that handler marshals onto the thread which owns capture:

* ``MainWindow``     -> ``QMetaObject.invokeMethod(..., Qt.QueuedConnection)``
* ``HeadlessRunner`` -> a direct call into its own capture lifecycle

**Security posture.** These are the first mutating routes on a server whose
read-only endpoints accepted wildcard CORS and no ``Host`` validation as an
explicit accepted risk (W4).  Control routes do not inherit that:

1. a bearer token is required on every request, even on loopback;
2. no ``Access-Control-Allow-Origin`` header is ever sent, so a browser cannot
   read a response even if it manages to issue the request;
3. the ``Host`` header must be loopback or the configured host, which closes
   DNS rebinding directly rather than relying on the CORS side effect;
4. with no token configured the routes fail closed.

``POST`` is deliberately absent from ``do_OPTIONS``'s allow-list in
``web_output.py``: the missing preflight is part of the defence.
"""
from __future__ import annotations

import json
import time

from . import api_auth, api_control
from .logger import app_logger


def _send_json(handler, status: int, payload: dict):
    """Write a JSON response with no CORS header.

    The absent ``Access-Control-Allow-Origin`` is load-bearing, not an
    oversight — see the module docstring.
    """
    try:
        body = json.dumps(payload, indent=2).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", len(body))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(body)
    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
        app_logger.debug("Client disconnected during control response")
    except Exception as e:
        app_logger.error(f"Error serving control response: {api_auth.redact(e)}")


# Machine-readable error codes. HTTP status alone is not enough: 503 has two
# entirely different causes needing opposite operator advice, and a client
# should never have to match on free text to tell them apart.
ERR_BAD_REQUEST = "bad_request"
ERR_BODY_TOO_LARGE = "body_too_large"
ERR_UNAUTHORIZED = "unauthorized"
ERR_HOST_NOT_ALLOWED = "host_not_allowed"
ERR_CONTROL_DISABLED = "control_disabled"        # no token configured
ERR_CONTROL_UNAVAILABLE = "control_unavailable"  # no capture handler registered


def _send_error(handler, status: int, message: str, code: str):
    _send_json(handler, status, {"error": message, "status": status, "code": code})


def _configured_host(handler):
    return getattr(handler.server, "control_host", None) or getattr(handler.server, "host", None)


def authorize(handler) -> bool:
    """Gate a control request. Writes the rejection itself and returns False.

    Host is checked before the token so a rebinding probe never even reaches
    the constant-time compare.
    """
    if not api_auth.host_allowed(handler.headers.get("Host"),
                                 _configured_host(handler),
                                 getattr(handler.server, "control_allowed_hosts", None)):
        app_logger.warning(
            "Rejected control request with disallowed Host header "
            f"'{api_auth.redact(handler.headers.get('Host'))}'"
        )
        _send_error(handler, 403, "Host not allowed.", ERR_HOST_NOT_ALLOWED)
        return False

    token = getattr(handler.server, "control_token", "") or ""
    verdict = api_auth.check_bearer(handler.headers.get("Authorization"), token)
    if verdict == api_auth.AUTH_OK:
        return True

    status, code, message = api_auth.verdict_response(verdict)
    # The verdict is safe to log; the presented credential is not.
    app_logger.warning(f"Control request denied ({verdict}) for {handler.path}")
    _send_error(handler, status, message, code)
    return False


def _read_body(handler):
    """Read the request body, or ``(None, error)`` if it is unreadable/oversized.

    The 413/401/403 paths answer without draining ``rfile``. That is safe only
    because this handler stays on HTTP/1.0, so every connection closes after the
    response. If ``protocol_version`` is ever raised to HTTP/1.1, the undrained
    body becomes a request-smuggling desync — drain it first at that point.
    """
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except (TypeError, ValueError):
        return None, (400, "Invalid Content-Length.", ERR_BAD_REQUEST)
    if length < 0:
        return None, (400, "Invalid Content-Length.", ERR_BAD_REQUEST)
    if length > api_control.MAX_BODY_BYTES:
        return None, (413, "Request body too large.", ERR_BODY_TOO_LARGE)
    if length == 0:
        return b"", None
    try:
        return handler.rfile.read(length), None
    except Exception as e:
        app_logger.debug(f"Error reading control body: {api_auth.redact(e)}")
        return None, (400, "Could not read request body.", ERR_BAD_REQUEST)


def _read_snapshot(handler_cls):
    return handler_cls.capture_status or {}


def serve_capture_state(handler):
    """``GET /capture`` — the ``capture`` + ``health`` blocks, behind the token.

    A convenience alias so a control client needs only one path prefix; the
    same data is already in ``/status``.
    """
    if not authorize(handler):
        return
    payload = handler._build_status_dict()
    _send_json(handler, 200, {
        "capture": payload.get("capture", {}),
        "health": payload.get("health", {}),
        "timestamp": payload.get("timestamp"),
    })


def serve_command(handler, command: str):
    """``POST /capture/start`` | ``POST /capture/stop``.

    Idempotent by contract: a sequence that re-runs Start, or fires Stop twice
    on abort, gets a 200 no-op rather than an error.
    """
    if not authorize(handler):
        return

    raw_body, error = _read_body(handler)
    if error:
        _send_error(handler, *error)
        return

    params, error = api_control.parse_request(raw_body)
    if error:
        # api_control validates plain values and has no HTTP vocabulary, so it
        # returns (status, message); the code is assigned here.
        status, message = error
        _send_error(handler, status, message,
                    ERR_BODY_TOO_LARGE if status == 413 else ERR_BAD_REQUEST)
        return

    handler_cls = type(handler)
    snapshot = _read_snapshot(handler_cls)

    if api_control.is_at_target(snapshot, command):
        result = (api_control.RESULT_ALREADY_RUNNING
                  if command == api_control.COMMAND_START
                  else api_control.RESULT_ALREADY_STOPPED)
        _send_json(handler, 200, api_control.build_result(
            command, snapshot, result=result, issued=False))
        return

    command_handler = getattr(handler.server, "capture_command_handler", None)
    if not callable(command_handler):
        app_logger.error(f"Control command '{command}' rejected — no handler registered")
        _send_error(handler, 503, "Capture control is not available on this server.",
                    ERR_CONTROL_UNAVAILABLE)
        return

    # Stamp of the error as it stands BEFORE the command, so a stale fault is
    # ignored while the SAME fault happening again still counts as this command
    # failing. Comparing the message text cannot do that.
    baseline_error_epoch = snapshot.get("last_error_epoch")

    try:
        command_handler(command)
    except Exception as e:
        app_logger.error(f"Capture command '{command}' failed: {api_auth.redact(e)}")
        _send_json(handler, 500, api_control.build_result(
            command, _read_snapshot(handler_cls),
            result=api_control.RESULT_FAILED, issued=True))
        return

    app_logger.info(f"Capture control: '{command}' issued via HTTP API")

    if not params["wait"]:
        _send_json(handler, 200, api_control.build_result(
            command, _read_snapshot(handler_cls),
            result=api_control.RESULT_PENDING, issued=True))
        return

    started = time.monotonic()
    snapshot, outcome = api_control.wait_for_target(
        command,
        lambda: _read_snapshot(handler_cls),
        timeout=params["timeout"],
        monotonic=time.monotonic,
        sleep=time.sleep,
        baseline_error_epoch=baseline_error_epoch,
    )
    elapsed = time.monotonic() - started
    result = api_control.result_for_outcome(command, outcome)
    _send_json(
        handler,
        api_control.http_status_for_result(result),
        api_control.build_result(command, snapshot, result=result, issued=True,
                                 waited=True, wait_seconds=elapsed),
    )


def route_post(handler, control_path: str) -> bool:
    """Dispatch a POST to a control route. Returns False if the path isn't ours."""
    path = handler.path.split("?", 1)[0].rstrip("/") or "/"
    control_path = (control_path or "/capture").rstrip("/")

    if path == f"{control_path}/start":
        serve_command(handler, api_control.COMMAND_START)
        return True
    if path == f"{control_path}/stop":
        serve_command(handler, api_control.COMMAND_STOP)
        return True
    return False
