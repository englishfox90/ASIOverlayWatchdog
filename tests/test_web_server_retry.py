"""Regression tests for web-server auto-start recovery.

Reproduces the field bug where the web output never came up on logon
autostart (Discord worked fine) and only a manual app restart fixed it.

Cause: the web server is started exactly once, when capture starts. If the
bind fails because the configured ``webserver_host`` (e.g. a Tailscale/LAN
IP) is not yet assigned to a network interface at logon, the one-shot start
fails and nothing ever retries — so web output stays off for the whole
session even though Discord (which binds nothing) keeps working.
"""
import types

from unittest.mock import MagicMock, patch

from ui.main_window.output import _MainWindowOutputMixin
from services.headless_runner import HeadlessRunner


class _FakeServer:
    """Stand-in for WebOutputServer whose bind succeeds only when the shared
    ``bind_ok`` flag is set — mimics a network interface coming up late."""

    def __init__(self, bind_ok, *args, **kwargs):
        self._bind_ok = bind_ok
        self.running = False
        self.command_handler = None

    def register_capture_command_handler(self, handler):
        self.command_handler = handler

    def start(self):
        self.running = bool(self._bind_ok["value"])
        return self.running

    def stop(self):
        self.running = False

    def get_url(self):
        return "http://100.64.0.1:8080/latest"

    def get_status_url(self):
        return "http://100.64.0.1:8080/status"


def _make_window(bind_ok):
    """A minimal object carrying the real output-mixin methods under test."""
    win = MagicMock()
    win.config = {
        "output": {
            "webserver_enabled": True,
            "webserver_host": "100.64.0.1",  # Tailscale-style IP, up late at logon
            "webserver_port": 8080,
        }
    }
    win.web_server = None
    win.image_library = None

    # Bind the genuine implementations so we exercise real control flow.
    for name in (
        "_ensure_output_servers_started",
        "_start_web_server",
        "_retry_web_server",
    ):
        setattr(win, name, types.MethodType(getattr(_MainWindowOutputMixin, name), win))

    # Retry scheduling itself is just QTimer plumbing — stub it so the test
    # can drive the retry deterministically.
    win._schedule_web_server_retry = MagicMock()
    win._cancel_web_server_retry = MagicMock()
    return win


def test_failed_bind_schedules_retry_and_recovers():
    bind_ok = {"value": False}
    win = _make_window(bind_ok)

    def factory(*args, **kwargs):
        return _FakeServer(bind_ok, *args, **kwargs)

    with patch("ui.main_window.output.WebOutputServer", side_effect=factory):
        # Autostart: bind fails because the IP isn't up yet.
        win._ensure_output_servers_started()
        assert win.web_server is None
        # The bug: nothing schedules another attempt. After the fix a retry
        # is queued instead of giving up for the session.
        win._schedule_web_server_retry.assert_called_once()

        # Network (Tailscale) comes up; the retry tick fires.
        bind_ok["value"] = True
        win._retry_web_server()

    assert win.web_server is not None
    assert win.web_server.running


def test_runtime_toggle_starts_and_stops_web_server():
    """W8: flipping webserver_enabled at runtime must start AND stop the server
    via the (now idempotent) reconciler, instead of doing nothing."""
    bind_ok = {"value": True}
    win = _make_window(bind_ok)
    win._stop_web_server = types.MethodType(
        _MainWindowOutputMixin._stop_web_server, win
    )
    win._stop_capture_status_timer = MagicMock()

    def factory(*args, **kwargs):
        return _FakeServer(bind_ok, *args, **kwargs)

    with patch("ui.main_window.output.WebOutputServer", side_effect=factory):
        # Enabled → server starts.
        win._ensure_output_servers_started()
        started = win.web_server
        assert started is not None and started.running

        # Toggle off at runtime → reconciler tears the server down.
        win.config["output"]["webserver_enabled"] = False
        win._ensure_output_servers_started()
        assert win.web_server is None
        assert started.running is False


def test_retry_is_noop_once_running():
    bind_ok = {"value": True}
    win = _make_window(bind_ok)

    def factory(*args, **kwargs):
        return _FakeServer(bind_ok, *args, **kwargs)

    with patch("ui.main_window.output.WebOutputServer", side_effect=factory):
        win._ensure_output_servers_started()
        running_server = win.web_server
        assert running_server is not None and running_server.running

        # A stray retry must not tear down or replace a healthy server.
        win._retry_web_server()
        assert win.web_server is running_server


# ---------------------------------------------------------------------------
# Headless runner — same one-shot-bind bug, recovered from the capture loop
# ---------------------------------------------------------------------------


def _make_runner(bind_ok):
    """A HeadlessRunner with only the attributes the web-server path touches.

    Built without __init__ to skip its real Config load and signal-handler
    registration.
    """
    runner = HeadlessRunner.__new__(HeadlessRunner)
    runner.config = {
        "output": {
            "mode": "webserver",
            "webserver_host": "100.64.0.1",
            "webserver_port": 8080,
        }
    }
    runner.web_server = None
    runner.image_library = None
    runner._last_webserver_retry = 0.0
    runner._log = lambda *a, **k: None
    return runner


def test_headless_starts_webserver_from_webserver_enabled_flag():
    """W1: headless must start the web server from the modern
    output.webserver_enabled flag, even when the legacy output.mode is absent."""
    bind_ok = {"value": True}
    runner = HeadlessRunner.__new__(HeadlessRunner)
    runner.config = {
        "output": {
            "webserver_enabled": True,
            "webserver_host": "127.0.0.1",
            "webserver_port": 8080,
        }
    }
    runner.web_server = None
    runner.image_library = None
    runner._last_webserver_retry = 0.0
    runner._log = lambda *a, **k: None

    # The gate now honours webserver_enabled (mode is absent).
    assert runner._webserver_mode_enabled() is True

    def factory(*args, **kwargs):
        return _FakeServer(bind_ok, *args, **kwargs)

    with patch("services.headless_runner.WebOutputServer", side_effect=factory):
        runner._ensure_webserver()

    assert runner.web_server is not None
    assert runner.web_server.running


def test_headless_ensure_webserver_recovers_after_failed_bind():
    bind_ok = {"value": False}
    runner = _make_runner(bind_ok)

    def factory(*args, **kwargs):
        return _FakeServer(bind_ok, *args, **kwargs)

    with patch("services.headless_runner.WebOutputServer", side_effect=factory):
        # Initial bind at autostart fails — IP not up yet.
        runner._start_webserver()
        assert runner.web_server is None

        # Throttle blocks an immediate re-attempt within the window.
        runner._ensure_webserver()
        assert runner.web_server is None

        # Window elapses and the network comes up; the loop's tick recovers it.
        runner._last_webserver_retry = 0.0
        bind_ok["value"] = True
        runner._ensure_webserver()

    assert runner.web_server is not None
    assert runner.web_server.running


def test_headless_ensure_webserver_noop_when_running():
    bind_ok = {"value": True}
    runner = _make_runner(bind_ok)

    def factory(*args, **kwargs):
        return _FakeServer(bind_ok, *args, **kwargs)

    with patch("services.headless_runner.WebOutputServer", side_effect=factory):
        runner._start_webserver()
        running_server = runner.web_server
        assert running_server is not None and running_server.running

        runner._last_webserver_retry = 0.0
        runner._ensure_webserver()
        assert runner.web_server is running_server
