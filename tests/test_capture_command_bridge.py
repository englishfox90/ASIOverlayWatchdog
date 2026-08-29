"""Tests for the capture-control handler seam (Stage 0c).

The highest-severity risk in the control API is a request thread touching Qt
state. These tests pin the two halves of the mitigation:

* the GUI bridge queues onto the GUI thread rather than executing inline, so a
  call from an HTTP thread never runs ``start_capture()`` there;
* the headless handler only flips a ``threading.Event``, which needs no
  marshalling at all.
"""
import threading

import pytest

from PySide6.QtCore import QCoreApplication, QThread
from PySide6.QtWidgets import QApplication, QWidget

from ui.controllers.capture_command_bridge import CaptureCommandBridge


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeWindow(QWidget):
    """A real QObject parent so the bridge has genuine thread affinity."""

    def __init__(self):
        super().__init__()
        self.calls = []
        self.pushes = 0
        self.raise_on = None

    def start_capture(self):
        self.calls.append(("start", threading.get_ident()))
        if self.raise_on == "start":
            raise RuntimeError("camera exploded")

    def stop_capture(self):
        self.calls.append(("stop", threading.get_ident()))
        if self.raise_on == "stop":
            raise RuntimeError("camera exploded")

    def push_capture_status(self):
        self.pushes += 1


def _drain():
    """Run queued events so QueuedConnection deliveries land."""
    QCoreApplication.processEvents()


# --- GUI bridge -----------------------------------------------------------

def test_command_is_queued_not_executed_inline(qapp):
    """The whole point: calling the bridge must not run capture immediately."""
    win = _FakeWindow()
    bridge = CaptureCommandBridge(win)

    bridge("start")
    assert win.calls == []  # still queued

    _drain()
    assert [c[0] for c in win.calls] == ["start"]


def test_command_executes_on_the_gui_thread(qapp):
    """A call from a worker thread must still run start_capture on the GUI thread."""
    win = _FakeWindow()
    bridge = CaptureCommandBridge(win)
    gui_thread_id = threading.get_ident()
    worker_thread_id = {}

    def call_from_worker():
        worker_thread_id["id"] = threading.get_ident()
        bridge("stop")

    t = threading.Thread(target=call_from_worker)
    t.start()
    t.join(5)

    assert win.calls == []  # not executed on the worker thread
    _drain()
    assert len(win.calls) == 1
    command, ran_on = win.calls[0]
    assert command == "stop"
    assert ran_on == gui_thread_id
    assert ran_on != worker_thread_id["id"]


def test_status_is_pushed_after_the_command(qapp):
    """A waiting HTTP client polls the snapshot — publish it without delay."""
    win = _FakeWindow()
    bridge = CaptureCommandBridge(win)
    bridge("start")
    _drain()
    assert win.pushes == 1


def test_capture_exception_does_not_escape_the_event_loop(qapp):
    win = _FakeWindow()
    win.raise_on = "start"
    bridge = CaptureCommandBridge(win)
    bridge("start")
    _drain()  # must not raise
    assert win.pushes == 1  # status still published


def test_unknown_command_raises_before_queueing(qapp):
    win = _FakeWindow()
    bridge = CaptureCommandBridge(win)
    with pytest.raises(ValueError):
        bridge("restart")
    _drain()
    assert win.calls == []


def test_bridge_lives_on_the_gui_thread(qapp):
    win = _FakeWindow()
    bridge = CaptureCommandBridge(win)
    assert bridge.thread() is QThread.currentThread()


# --- headless handler -----------------------------------------------------

class _StubRunner:
    """The headless handler under test, without the camera/web machinery."""

    def __init__(self):
        from services.headless_runner import HeadlessRunner
        self._paused = threading.Event()
        self.logs = []
        self.pushes = []
        self._handle = HeadlessRunner._handle_capture_command.__get__(self)

    def _log(self, msg):
        self.logs.append(msg)

    def _push_capture_status(self, **kwargs):
        self.pushes.append(kwargs)


def test_headless_stop_pauses_without_shutting_down():
    """Pausing must not tear the process down, or 'Start at dusk' has no host."""
    runner = _StubRunner()
    runner._handle("stop")
    assert runner._paused.is_set()
    assert runner.pushes and runner.pushes[-1]["enabled"] is False


def test_headless_start_resumes():
    runner = _StubRunner()
    runner._paused.set()
    runner._handle("start")
    assert not runner._paused.is_set()


def test_headless_commands_are_idempotent():
    runner = _StubRunner()
    runner._handle("stop")
    runner._handle("stop")
    assert runner._paused.is_set()
    runner._handle("start")
    runner._handle("start")
    assert not runner._paused.is_set()


def test_headless_rejects_unknown_command():
    runner = _StubRunner()
    with pytest.raises(ValueError):
        runner._handle("restart")


def test_headless_stop_does_not_touch_the_shutdown_event():
    """The API controls capture, never process lifetime."""
    from services.headless_runner import HeadlessRunner
    import inspect
    src = inspect.getsource(HeadlessRunner._handle_capture_command)
    assert "_shutdown_event" not in src
