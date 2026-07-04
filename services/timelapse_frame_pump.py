"""
Bounded single-consumer frame queue that decouples a fast producer (the GUI
thread delivering captured frames) from a slow consumer (RGB conversion +
blocking ffmpeg stdin write).

Generic on purpose — it knows nothing about timelapses or ffmpeg. It exists
because ``TimelapseWriter.add_frame`` used to do the conversion and the
blocking ``stdin.write`` inline on the caller's thread (the GUI thread, via
the Qt signal chain), which meant a wedged encoder stalled the whole event
loop. Producer calls must return immediately; a full queue drops the OLDEST
item rather than blocking the producer or refusing the newest one.
"""
import queue
import threading
import time
from typing import Any, Callable, Optional

from .logger import app_logger


class FramePump:
    """Runs ``consume(item)`` on a single daemon worker thread, fed by ``submit``."""

    def __init__(self, consume: Callable[[Any], None], *, maxsize: int = 2,
                 name: str = "frame-pump"):
        self._consume = consume
        self._name = name
        self._queue: "queue.Queue[Any]" = queue.Queue(maxsize=maxsize)
        self._cv = threading.Condition()
        self._pending = 0  # submitted but not yet fully processed (or dropped)
        self._thread = threading.Thread(target=self._run, daemon=True, name=name)
        self._thread.start()

    def submit(self, item: Any) -> None:
        """Enqueue ``item`` for background processing. Never blocks the caller.

        If the queue is already full, the OLDEST queued item is dropped to make
        room — a skipped frame is invisible in a timelapse; a blocked producer
        is not.
        """
        with self._cv:
            self._pending += 1
        while True:
            try:
                self._queue.put_nowait(item)
                return
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    continue
                with self._cv:
                    self._pending -= 1
                    self._cv.notify_all()
                app_logger.debug(f"{self._name}: queue full, dropped oldest queued item")

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                self._consume(item)
            except Exception as e:
                app_logger.error(f"{self._name}: consumer error: {e}")
            finally:
                with self._cv:
                    self._pending -= 1
                    self._cv.notify_all()

    def flush(self, timeout: Optional[float] = None) -> bool:
        """Block until every submitted item has been consumed (or dropped).

        Returns True if the queue drained within ``timeout`` seconds (None
        waits indefinitely — test-only usage), False on timeout.
        """
        with self._cv:
            deadline = None if timeout is None else time.monotonic() + timeout
            while self._pending > 0:
                if deadline is None:
                    self._cv.wait()
                    continue
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cv.wait(timeout=remaining)
            return True

    def discard_queued(self) -> int:
        """Drop items still sitting in the queue without running ``consume`` on
        them. Does not affect an item the worker is already processing."""
        dropped = 0
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
            dropped += 1
        if dropped:
            with self._cv:
                self._pending -= dropped
                self._cv.notify_all()
        return dropped

    def drain(self, timeout: float = 3.0) -> None:
        """Best-effort flush, then discard whatever is left.

        Used at shutdown: give the worker a bounded chance to finish anything
        already queued, then give up so a wedged consumer (e.g. a blocking
        write to a hung ffmpeg) can never hang the caller indefinitely. An
        item the worker is *already* running when the timeout expires is not
        interrupted — there is no safe way to cancel a blocking pipe write —
        but nothing further will be pulled off the queue for it to do.
        """
        if not self.flush(timeout=timeout):
            self.discard_queued()
