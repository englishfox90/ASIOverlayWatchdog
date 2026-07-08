"""Shared backend scaffolding.

Each notification backend owns exactly one ``queue.Queue`` and one daemon
worker thread, so a slow or misbehaving backend (e.g. a Hermes endpoint that
times out) can never block another backend (e.g. Discord) or the caller.
"""
import queue
import threading
from abc import ABC, abstractmethod

from ..logger import app_logger
from .webhook_http import redact_webhook_error

_STOP = object()


class NotificationBackend(ABC):
    """Base class for a single outbound notification sink."""

    def __init__(self, config, name: str):
        self.config = config
        self._name = name
        self._queue = queue.Queue()
        self._worker = None
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self._name

    @abstractmethod
    def is_enabled(self) -> bool:
        """Whether this backend should receive events right now."""

    @abstractmethod
    def _deliver(self, event) -> None:
        """Send one event. Called on the worker thread only."""

    def submit(self, event) -> None:
        """Enqueue an event for background delivery. Never blocks."""
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(
                    target=self._run, name=f"{self._name}NotifyWorker", daemon=True
                )
                self._worker.start()
        self._queue.put(event)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                self._queue.task_done()
                return
            try:
                self._deliver(item)
            except Exception as e:
                app_logger.error(
                    f"{self._name} notification delivery failed: {redact_webhook_error(e)}"
                )
            finally:
                self._queue.task_done()

    def shutdown(self) -> None:
        """Best-effort drain and stop. Safe to call even if never started."""
        with self._lock:
            worker = self._worker
        if worker is None or not worker.is_alive():
            return
        self._queue.put(_STOP)
        worker.join(timeout=5.0)
