"""Single-instance guard command-channel tests.

Covers the quit/activate protocol the installer relies on: --shutdown sends
"quit" (clean teardown before an upgrade), while a second app launch sends
anything else and just surfaces the running window.
"""
import sys
import threading
import time

import pytest


@pytest.fixture
def qt_app():
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        pytest.skip("PySide6 not installed")
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def _pump_until_quit(app, timeout_sec=5.0):
    """Run the event loop until something calls app.quit() or the timeout."""
    from PySide6.QtCore import QTimer
    QTimer.singleShot(int(timeout_sec * 1000), app.quit)
    app.exec()


def test_quit_command_emits_quit_requested(qt_app):
    from services.single_instance import SingleInstanceGuard, request_shutdown
    name = "PFRSentinel-test-quit"
    guard = SingleInstanceGuard(name)
    seen = {"quit": 0, "activate": 0}
    guard.quit_requested.connect(lambda: seen.__setitem__("quit", seen["quit"] + 1))
    guard.activate_requested.connect(lambda: seen.__setitem__("activate", seen["activate"] + 1))
    guard.quit_requested.connect(qt_app.quit)

    try:
        assert guard.already_running() is False  # this process owns the lock

        result = {}

        def client():
            time.sleep(0.2)  # let the server's event loop start
            result["ok"] = request_shutdown(name, timeout_ms=2000)

        threading.Thread(target=client, daemon=True).start()
        _pump_until_quit(qt_app)

        assert result.get("ok") is True
        assert seen["quit"] == 1
        assert seen["activate"] == 0
    finally:
        guard.deleteLater()


def test_non_quit_payload_emits_activate(qt_app):
    from PySide6.QtNetwork import QLocalSocket
    from services.single_instance import SingleInstanceGuard
    name = "PFRSentinel-test-activate"
    guard = SingleInstanceGuard(name)
    seen = {"quit": 0, "activate": 0}
    guard.quit_requested.connect(lambda: seen.__setitem__("quit", seen["quit"] + 1))
    guard.activate_requested.connect(lambda: seen.__setitem__("activate", seen["activate"] + 1))
    guard.activate_requested.connect(qt_app.quit)

    try:
        assert guard.already_running() is False

        def client():
            time.sleep(0.2)
            sock = QLocalSocket()
            sock.connectToServer(name)
            if sock.waitForConnected(2000):
                sock.write(b"activate")  # what a second app launch sends
                sock.flush()
                sock.waitForBytesWritten(2000)
                sock.disconnectFromServer()

        threading.Thread(target=client, daemon=True).start()
        _pump_until_quit(qt_app)

        assert seen["activate"] == 1
        assert seen["quit"] == 0
    finally:
        guard.deleteLater()


def test_request_shutdown_false_when_nothing_running(qt_app):
    from services.single_instance import request_shutdown
    # No server listening on this name → no instance to signal.
    assert request_shutdown("PFRSentinel-test-absent", timeout_ms=300) is False
