"""
Marshals HTTP capture-control commands onto the GUI thread.

The web server runs on a background thread; ``start_capture()`` /
``stop_capture()`` touch Qt widgets and camera-controller state.  Calling one
from the other is the single highest-severity hazard in the control API — it
races or crashes rather than failing cleanly.

This bridge is the seam.  ``services/web_control.py`` invokes it *on an HTTP
request thread*; it immediately queues the work onto the GUI thread and
returns.  The HTTP side then confirms the outcome by polling the capture
snapshot the app already pushes — it never waits on a return value from here,
because there is nothing meaningful to return synchronously.

The system tray (``ui/system_tray_qt.py``) is the existing precedent for
driving capture from outside the capture panel — but the tray already runs *on*
the GUI thread and can call straight through.  The HTTP thread cannot, hence
the QueuedConnection.
"""
from __future__ import annotations

from PySide6.QtCore import Q_ARG, QMetaObject, QObject, Qt, Slot

from services.logger import app_logger


class CaptureCommandBridge(QObject):
    """Queues 'start'/'stop' onto the GUI thread on behalf of the HTTP API.

    Constructed with the MainWindow as parent so it lives on the GUI thread —
    which is what makes ``QueuedConnection`` deliver ``_execute`` there.
    """

    def __init__(self, main_window):
        super().__init__(main_window)
        self._window = main_window

    def __call__(self, command: str):
        """Entry point for ``web_control`` — runs on an HTTP request thread.

        Returns as soon as the command is queued. Raising here surfaces to the
        client as a 500, so only genuinely un-queueable commands raise.
        """
        if command not in ("start", "stop"):
            raise ValueError(f"Unknown capture command: {command!r}")

        ok = QMetaObject.invokeMethod(
            self, "_execute", Qt.QueuedConnection, Q_ARG(str, command)
        )
        if not ok:
            raise RuntimeError("Could not queue capture command onto the GUI thread")

    @Slot(str)
    def _execute(self, command: str):
        """Runs on the GUI thread. Safe to touch widgets and controllers here."""
        try:
            if command == "start":
                self._window.start_capture()
            else:
                self._window.stop_capture()
        except Exception as e:
            # Never let an exception escape into the Qt event loop.
            app_logger.error(f"Capture command '{command}' failed on GUI thread: {e}")
        finally:
            # Publish the resulting state immediately so a waiting HTTP client
            # sees it without having to wait for the next status-timer tick.
            try:
                self._window.push_capture_status()
            except Exception as e:
                app_logger.debug(f"Post-command status push failed: {e}")
