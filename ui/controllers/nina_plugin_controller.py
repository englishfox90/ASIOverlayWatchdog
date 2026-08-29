"""Threads the NINA plugin install/remove service off the GUI thread.

``services/nina_plugin_install.py`` is synchronous file I/O (a stat walk plus a
copy) and states that GUI-thread callers must thread it themselves. This is
that thread. One operation runs at a time; every result comes back as a Qt
signal, so the panel is only ever touched from the GUI thread.

``service`` and ``runner`` are injectable so the behaviour can be tested
without real NINA folders and without an event loop (a runner that calls
inline makes the signals synchronous).
"""
import threading

from PySide6.QtCore import QObject, Signal

from services import nina_plugin_install
from services.logger import app_logger

ACTION_INSTALL = 'install'
ACTION_REMOVE = 'remove'
ACTION_REFRESH = 'refresh'


def _run_detached(job):
    threading.Thread(target=job, name="nina-plugin", daemon=True).start()


class NinaPluginController(QObject):
    """Background runner for NINA plugin status / install / remove."""

    status_ready = Signal(object)      # PluginStatus
    action_finished = Signal(object)   # PluginActionResult
    busy_changed = Signal(bool)

    def __init__(self, parent=None, service=None, runner=None):
        super().__init__(parent)
        self._service = service or nina_plugin_install
        self._runner = runner or _run_detached
        self._lock = threading.Lock()
        self._busy = False

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return self._busy

    # --- public API -------------------------------------------------------

    def refresh_status(self) -> bool:
        return self._start(self._do_refresh, "check")

    def install(self) -> bool:
        return self._start(self._do_install, "install")

    def remove(self) -> bool:
        return self._start(self._do_remove, "remove")

    def run(self, action: str) -> bool:
        """Dispatch by name — what the panel's buttons hand the window."""
        if action == ACTION_INSTALL:
            return self.install()
        if action == ACTION_REMOVE:
            return self.remove()
        if action == ACTION_REFRESH:
            return self.refresh_status()
        app_logger.warning(f"Unknown NINA plugin action: {action}")
        return False

    # --- work -------------------------------------------------------------

    def _do_refresh(self):
        self.status_ready.emit(self._service.get_status())

    def _do_install(self):
        self.action_finished.emit(self._service.install_plugin())
        self._do_refresh()

    def _do_remove(self):
        self.action_finished.emit(self._service.remove_plugin())
        self._do_refresh()

    def _start(self, work, describe: str) -> bool:
        """Claim the single worker slot and run ``work`` on it.

        Returns False when an operation is already in flight — the buttons are
        disabled while busy, but a queued click must not start a second copy.
        """
        with self._lock:
            if self._busy:
                app_logger.debug(f"NINA plugin {describe} skipped: already busy")
                return False
            self._busy = True

        self.busy_changed.emit(True)

        def job():
            try:
                work()
            except Exception as exc:
                # The service documents that it never raises; if it does, the
                # buttons must still come back rather than stay greyed out.
                app_logger.error(f"NINA plugin {describe} failed: {exc}")
                self.action_finished.emit(self._service.PluginActionResult(
                    False, self._service.RESULT_ERROR,
                    f"Could not {describe} the NINA plugin: {exc}",
                ))
            finally:
                with self._lock:
                    self._busy = False
                self.busy_changed.emit(False)

        self._runner(job)
        return True
