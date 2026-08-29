"""Single-instance guard.

PFR Sentinel runs unattended 24/7 and often lives in the system tray, so a
user can easily forget it's already running and launch it again — spawning a
second process that fights over the camera, output ports, and config file.

This guard uses a Qt local socket (named pipe on Windows) as the lock. The
first process listens on a well-known name; a second launch fails to listen,
connects to the running instance to ask it to surface its window, then exits.

Requires a QCoreApplication/QApplication instance to already exist.
"""
import time

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from services.logger import app_logger

# Stable, app-specific name. Scoped per user by the OS, which is what we want —
# two different Windows users may each run their own instance.
_SERVER_NAME = "PFRSentinel-single-instance-v1"

# How long the receiver waits for a command payload. Matches request_shutdown's
# own timeout: the sender is patient, so the receiver must be too.
_READ_TIMEOUT_MS = 1500


class SingleInstanceGuard(QObject):
    """Detect and signal an already-running PFR Sentinel instance.

    Emits ``activate_requested`` on the owning (first) instance whenever a
    second launch attempt connects, so the UI can restore/raise its window.
    Emits ``quit_requested`` instead when the connecting client sends the
    ``quit`` command (the installer's ``--shutdown`` path), so the running
    instance can shut down cleanly and release the camera before an upgrade
    replaces its files. A self-initiated quit works even when the running app
    is elevated, which a non-elevated installer cannot force-terminate.
    """

    activate_requested = Signal()
    quit_requested = Signal()

    def __init__(self, name: str = _SERVER_NAME):
        super().__init__()
        self._name = name
        self._server: QLocalServer | None = None

    def already_running(self) -> bool:
        """Return True if another instance owns the lock (and was signalled).

        On the first instance this claims the lock and returns False. On a
        second instance it pokes the owner to show its window and returns True;
        the caller should then exit.
        """
        probe = QLocalSocket()
        probe.connectToServer(self._name)
        if probe.waitForConnected(300):
            # Owner is alive — ask it to surface, then bow out.
            probe.write(b"activate")
            probe.flush()
            probe.waitForBytesWritten(300)
            probe.disconnectFromServer()
            app_logger.info("Another PFR Sentinel instance is already running; signalled it to show.")
            return True

        # No owner answered. A crashed prior instance can leave a stale socket
        # file that blocks listen() on Unix; removeServer clears it (no-op when
        # nothing is stale).
        QLocalServer.removeServer(self._name)

        self._server = QLocalServer(self)
        # Grant access to the same user explicitly. The installer's --shutdown
        # helper runs at medium integrity while an auto-started instance runs
        # elevated (high integrity); UserAccessOption makes the same-user DACL
        # explicit so the medium-integrity helper can still connect to ask the
        # elevated instance to quit. (The pipe's mandatory label stays default,
        # so the integrity levels themselves don't block the write.)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._on_new_connection)
        if not self._server.listen(self._name):
            # Couldn't claim the lock and couldn't connect — don't block startup,
            # just run without the guard rather than refusing to launch.
            app_logger.warning(
                f"Single-instance guard failed to listen: {self._server.errorString()} — "
                "continuing without it."
            )
            self._server = None
        return False

    def _on_new_connection(self):
        conn = self._server.nextPendingConnection() if self._server else None
        if conn is None:
            return
        # Read the small command payload. "quit" asks for a clean shutdown
        # (installer upgrade path); anything else (or nothing) means "surface
        # the window" — the behaviour a second app launch relies on.
        #
        # Wait up to _READ_TIMEOUT_MS across repeated slices rather than a single
        # 200ms one. The sender allows 1500ms, and a GUI thread busy with a frame
        # or ML inference can easily take longer than 200ms to reach this handler.
        # Losing that race silently downgraded a "quit" into an "activate", so an
        # installer upgrade would proceed while the app still held its files and
        # the camera — and it surfaced as an intermittent test failure.
        command = b""
        deadline = time.monotonic() + _READ_TIMEOUT_MS / 1000.0
        while True:
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                break
            if conn.waitForReadyRead(remaining_ms):
                command = bytes(conn.readAll())
                break
            # waitForReadyRead normally blocks the whole budget, but it can
            # return early. Keep waiting unless the peer has actually gone,
            # which also stops this spinning on a dead socket.
            if conn.state() != QLocalSocket.LocalSocketState.ConnectedState:
                break
        conn.disconnectFromServer()
        if command.strip().lower().startswith(b"quit"):
            app_logger.info("Single-instance: received quit command — shutting down")
            self.quit_requested.emit()
        else:
            self.activate_requested.emit()


def request_shutdown(name: str = _SERVER_NAME, timeout_ms: int = 1500) -> bool:
    """Ask a running PFR Sentinel instance to quit cleanly via its single-instance
    channel. Returns True if an instance was found and signalled, False if none
    is running. Requires a QCoreApplication to already exist.

    Used by the installer (``--shutdown``) to release locked files + the camera
    before an upgrade. Works regardless of the running app's elevation, because
    the app terminates itself — no cross-process kill, no UAC prompt."""
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(timeout_ms):
        return False  # nothing listening — no running instance
    sock.write(b"quit")
    sock.flush()
    sock.waitForBytesWritten(timeout_ms)
    # Give the server a moment to read the command before the pipe tears down.
    sock.waitForDisconnected(timeout_ms)
    return True
