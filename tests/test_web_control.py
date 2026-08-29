"""Tests for services/web_control.py — capture-control HTTP routes.

Exercised through a fake request handler rather than a real socket, so the
whole security matrix runs in the default pytest selection (no
``requires_network`` marker, no port binding).
"""
import io
import json

import pytest

from services import api_control, web_control
from services.web_output import ImageHTTPHandler


TOKEN = "test-token-value-1234567890"
AUTH = {"Authorization": f"Bearer {TOKEN}", "Host": "127.0.0.1:8080"}


class _FakeServer:
    control_path = "/capture"
    control_host = "127.0.0.1"
    control_token = TOKEN
    capture_command_handler = None


class _FakeHandler:
    """Stands in for ImageHTTPHandler: records the response instead of sending."""

    def __init__(self, path="/capture/start", headers=None, body=b"",
                 server=None, capture_status=None):
        self.path = path
        self.headers = dict(headers if headers is not None else AUTH)
        self.rfile = io.BytesIO(body)
        if body:
            self.headers.setdefault("Content-Length", str(len(body)))
        self.server = server or _FakeServer()
        self.wfile = io.BytesIO()
        self.status = None
        self.sent_headers = {}
        self.capture_status = capture_status if capture_status is not None else {}

    # -- BaseHTTPRequestHandler surface used by web_control ----------------
    def send_response(self, code):
        self.status = code

    def send_header(self, key, value):
        self.sent_headers[key] = value

    def end_headers(self):
        pass

    def send_error(self, code, message=None):
        self.status = code

    def _build_status_dict(self):
        return {"capture": dict(self.capture_status), "health": {"status": "ok"},
                "timestamp": "2026-08-29T00:00:00"}

    # -- assertions helpers -----------------------------------------------
    @property
    def body(self):
        return json.loads(self.wfile.getvalue().decode("utf-8"))


def running_status():
    return {"mode": "camera", "enabled": True, "running": True, "state": "capturing"}


def stopped_status():
    return {"mode": "idle", "enabled": False, "running": False, "state": "stopped"}


@pytest.fixture(autouse=True)
def clean_capture_status():
    """web_control reads the snapshot off the handler CLASS — isolate it."""
    original = ImageHTTPHandler.capture_status
    ImageHTTPHandler.capture_status = {}
    yield
    ImageHTTPHandler.capture_status = original


class _Recorder:
    """A registered command handler that records rather than touching capture."""

    def __init__(self, on_command=None):
        self.commands = []
        self.on_command = on_command

    def __call__(self, command):
        self.commands.append(command)
        if self.on_command:
            self.on_command(command)


def make_handler(path="/capture/start", body=b"", headers=None, recorder=None,
                 snapshot=None):
    server = _FakeServer()
    server.capture_command_handler = recorder
    ImageHTTPHandler.capture_status = snapshot if snapshot is not None else stopped_status()
    h = _FakeHandler(path=path, headers=headers, body=body, server=server)
    # web_control reads the snapshot via type(handler).capture_status.
    h.__class__ = type("_H", (_FakeHandler,), {"capture_status": ImageHTTPHandler.capture_status})
    return h


def post(handler, command=api_control.COMMAND_START):
    web_control.serve_command(handler, command)
    return handler


# --- auth matrix ----------------------------------------------------------

def test_missing_token_is_rejected():
    h = make_handler(headers={"Host": "127.0.0.1"})
    post(h)
    assert h.status == 401


def test_wrong_token_is_rejected():
    h = make_handler(headers={"Authorization": "Bearer wrong", "Host": "127.0.0.1"})
    post(h)
    assert h.status == 401


def test_no_configured_token_fails_closed():
    h = make_handler()
    h.server.control_token = ""
    post(h)
    assert h.status == 503


def test_foreign_host_header_is_rejected():
    """DNS-rebinding defence: loopback socket, attacker-controlled Host."""
    h = make_handler(headers={"Authorization": f"Bearer {TOKEN}",
                              "Host": "evil.example.com"})
    post(h)
    assert h.status == 403


def test_host_check_runs_before_token_check():
    h = make_handler(headers={"Host": "evil.example.com"})
    post(h)
    assert h.status == 403


def test_rejected_request_never_invokes_the_handler():
    recorder = _Recorder()
    h = make_handler(headers={"Host": "127.0.0.1"}, recorder=recorder)
    post(h)
    assert recorder.commands == []


# --- CORS regression guard ------------------------------------------------

def test_control_responses_carry_no_acao_header():
    """Load-bearing: without ACAO a browser cannot read a control response."""
    recorder = _Recorder()
    h = make_handler(body=b'{"wait": false}', recorder=recorder)
    post(h)
    assert "Access-Control-Allow-Origin" not in h.sent_headers


def test_rejection_responses_also_carry_no_acao_header():
    h = make_handler(headers={"Host": "127.0.0.1"})
    post(h)
    assert "Access-Control-Allow-Origin" not in h.sent_headers


def test_status_endpoint_still_sends_acao():
    """/status must keep its wildcard CORS — existing consumers rely on it."""
    import inspect
    src = inspect.getsource(ImageHTTPHandler._serve_status)
    assert "Access-Control-Allow-Origin" in src


def test_options_allow_list_excludes_post():
    """The missing preflight is part of the control-route defence."""
    import inspect
    src = inspect.getsource(ImageHTTPHandler.do_OPTIONS)
    allow = [line for line in src.splitlines() if "Allow-Methods" in line]
    assert allow and all("POST" not in line for line in allow)


# --- idempotency ----------------------------------------------------------

def test_start_when_already_running_is_a_200_noop():
    recorder = _Recorder()
    h = make_handler(recorder=recorder, snapshot=running_status())
    post(h, api_control.COMMAND_START)
    assert h.status == 200
    assert h.body["result"] == api_control.RESULT_ALREADY_RUNNING
    assert h.body["changed"] is False
    assert recorder.commands == []  # handler never invoked


def test_stop_when_already_stopped_is_a_200_noop():
    recorder = _Recorder()
    h = make_handler(path="/capture/stop", recorder=recorder, snapshot=stopped_status())
    post(h, api_control.COMMAND_STOP)
    assert h.status == 200
    assert h.body["result"] == api_control.RESULT_ALREADY_STOPPED
    assert recorder.commands == []


# --- command dispatch -----------------------------------------------------

def test_no_registered_handler_returns_503():
    h = make_handler(recorder=None)
    post(h)
    assert h.status == 503


def test_handler_is_invoked_with_the_command():
    recorder = _Recorder()
    h = make_handler(body=b'{"wait": false}', recorder=recorder,
                     snapshot=running_status())
    post(h, api_control.COMMAND_STOP)
    assert recorder.commands == [api_control.COMMAND_STOP]


def test_wait_false_returns_pending_without_blocking():
    recorder = _Recorder()
    h = make_handler(body=b'{"wait": false}', recorder=recorder)
    post(h)
    assert h.status == 200
    assert h.body["result"] == api_control.RESULT_PENDING
    assert h.body["waited"] is False


def test_wait_true_returns_started_once_state_flips():
    def flip(_command):
        # Stand in for the app pushing a new snapshot after the command lands.
        h.__class__.capture_status = running_status()

    recorder = _Recorder(on_command=flip)
    h = make_handler(body=b'{"wait": true, "timeout": 5}', recorder=recorder)
    post(h)
    assert h.status == 200
    assert h.body["result"] == api_control.RESULT_STARTED
    assert h.body["waited"] is True


def test_wait_times_out_with_504():
    recorder = _Recorder()  # state never flips
    h = make_handler(body=b'{"wait": true, "timeout": 1}', recorder=recorder)
    post(h)
    assert h.status == 504
    assert h.body["result"] == api_control.RESULT_TIMEOUT


def test_handler_exception_returns_500_and_does_not_propagate():
    def boom(_command):
        raise RuntimeError("capture stack exploded")

    h = make_handler(body=b'{"wait": false}', recorder=_Recorder(on_command=boom))
    post(h)
    assert h.status == 500
    assert h.body["result"] == api_control.RESULT_FAILED


def test_token_never_appears_in_an_error_payload():
    def boom(_command):
        raise RuntimeError(f"failed while presenting Bearer {TOKEN}")

    h = make_handler(body=b'{"wait": false}', recorder=_Recorder(on_command=boom))
    post(h)
    assert TOKEN not in h.wfile.getvalue().decode("utf-8")


# --- body validation at the route layer -----------------------------------

def test_malformed_body_returns_400_without_invoking_handler():
    recorder = _Recorder()
    h = make_handler(body=b"{nope", recorder=recorder)
    post(h)
    assert h.status == 400
    assert recorder.commands == []


def test_oversized_content_length_returns_413():
    h = make_handler(recorder=_Recorder())
    h.headers["Content-Length"] = str(api_control.MAX_BODY_BYTES + 1)
    post(h)
    assert h.status == 413


def test_invalid_content_length_returns_400():
    h = make_handler(recorder=_Recorder())
    h.headers["Content-Length"] = "not-a-number"
    post(h)
    assert h.status == 400


# --- routing --------------------------------------------------------------

@pytest.mark.parametrize("path,expected", [
    ("/capture/start", api_control.COMMAND_START),
    ("/capture/stop", api_control.COMMAND_STOP),
    ("/capture/start/", api_control.COMMAND_START),
    ("/capture/start?x=1", api_control.COMMAND_START),
])
def test_route_post_dispatches_known_paths(path, expected):
    recorder = _Recorder()
    # Half-way state: neither command is already at target, so both dispatch.
    partial = {"mode": "camera", "enabled": True, "running": False, "state": "stopped"}
    h = make_handler(path=path, body=b'{"wait": false}', recorder=recorder,
                     snapshot=partial)
    assert web_control.route_post(h, "/capture") is True
    assert recorder.commands == [expected]


@pytest.mark.parametrize("path", ["/capture", "/status", "/latest", "/capture/restart", "/"])
def test_route_post_ignores_unknown_paths(path):
    recorder = _Recorder()
    h = make_handler(path=path, recorder=recorder)
    assert web_control.route_post(h, "/capture") is False
    assert recorder.commands == []


# --- GET /capture ---------------------------------------------------------

def test_get_capture_state_requires_a_token():
    h = make_handler(path="/capture", headers={"Host": "127.0.0.1"})
    web_control.serve_capture_state(h)
    assert h.status == 401


def test_get_capture_state_returns_capture_and_health():
    h = make_handler(path="/capture")
    h.capture_status = running_status()
    web_control.serve_capture_state(h)
    assert h.status == 200
    assert h.body["capture"]["state"] == "capturing"
    assert h.body["health"]["status"] == "ok"
    assert "Access-Control-Allow-Origin" not in h.sent_headers


# --- machine-readable error codes -----------------------------------------

def test_the_two_503_causes_are_distinguishable():
    """Same status, opposite operator advice — a client must not match on prose.

    503 means either 'the control API is switched off' (tell the user to enable
    it on the Output tab) or 'the server is up but no capture handler
    registered' (a wiring fault). Only `code` separates them.
    """
    disabled = make_handler()
    disabled.server.control_token = ""
    post(disabled)

    unavailable = make_handler(recorder=None)  # token fine, no handler
    post(unavailable)

    assert disabled.status == unavailable.status == 503
    assert disabled.body["code"] == "control_disabled"
    assert unavailable.body["code"] == "control_unavailable"


@pytest.mark.parametrize("headers,code", [
    ({"Host": "127.0.0.1"}, "unauthorized"),
    ({"Host": "127.0.0.1", "Authorization": "Bearer wrong"}, "unauthorized"),
    ({"Host": "127.0.0.1", "Authorization": "Basic x"}, "unauthorized"),
    ({"Host": "evil.example.com", "Authorization": f"Bearer {TOKEN}"}, "host_not_allowed"),
])
def test_rejection_codes(headers, code):
    h = make_handler(headers=headers)
    post(h)
    assert h.body["code"] == code


def test_auth_failures_share_one_code_and_message():
    """The code must not leak which of the three auth failures occurred."""
    missing = make_handler(headers={"Host": "127.0.0.1"})
    wrong = make_handler(headers={"Host": "127.0.0.1", "Authorization": "Bearer wrong"})
    post(missing)
    post(wrong)
    assert missing.body["code"] == wrong.body["code"]
    assert missing.body["error"] == wrong.body["error"]


def test_bad_body_codes():
    malformed = make_handler(body=b"{nope", recorder=_Recorder())
    post(malformed)
    assert malformed.body["code"] == "bad_request"

    oversized = make_handler(recorder=_Recorder())
    oversized.headers["Content-Length"] = str(api_control.MAX_BODY_BYTES + 1)
    post(oversized)
    assert oversized.body["code"] == "body_too_large"


def test_every_error_response_carries_a_code():
    for h in (make_handler(headers={"Host": "127.0.0.1"}),
              make_handler(headers={"Host": "evil.com"}),
              make_handler(body=b"{nope", recorder=_Recorder()),
              make_handler(recorder=None)):
        post(h)
        assert "code" in h.body, h.body


# --- pre-flight readiness (Stage 2 Validate) -------------------------------

def test_capture_state_reports_control_ready_when_a_handler_is_registered():
    h = make_handler(path="/capture", recorder=_Recorder())
    web_control.serve_capture_state(h)
    assert h.body["control_ready"] is True


def test_capture_state_reports_not_ready_without_a_handler():
    """The gap this closes: the token is valid, so the route used to answer a
    bare 200 and a sequence would validate green then fail when it ran."""
    h = make_handler(path="/capture", recorder=None)
    web_control.serve_capture_state(h)
    assert h.status == 200
    assert h.body["control_ready"] is False


def test_control_ready_matches_what_a_command_would_do():
    """Readiness must agree with serve_command, or validation lies."""
    unwired = make_handler(path="/capture", recorder=None)
    web_control.serve_capture_state(unwired)
    assert unwired.body["control_ready"] is False

    cmd = make_handler(recorder=None)
    post(cmd)
    assert cmd.status == 503 and cmd.body["code"] == "control_unavailable"
