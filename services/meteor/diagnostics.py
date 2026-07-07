"""
Meteor pipeline diagnostics.

Answers the two questions a silent night raises:
  1. "Did frames stop reaching the detector — and when?" A one-shot
     'frames stopped' line records the last-frame timestamp when the flow
     dries up, and a 'frames resumed' line marks recovery.
  2. "Frames flowed but nothing fired — where did candidates die?" A periodic
     INFO heartbeat summarises per-stage counters (raw Hough candidates →
     length ceiling → streak profile → persistence verdicts) plus the current
     noise threshold and hot-mask coverage, so a zero-detection night is
     attributable to a specific stage from the log alone.

Also logs transitions: roof-gate suspend/resume, and a WARNING when the hot
mask blankets an implausible fraction of the frame (the transient map is then
mostly blanked and detection cannot fire).

All log lines go through app_logger. Methods return the message they logged
(None when nothing was logged) so tests can assert without capturing logs.

Thread-safety: frame_received()/roof_gate()/detection_*() are called from the
frame-ingest slot and the detection worker thread; maybe_heartbeat() from the
GUI status timer. All mutable state sits behind one lock.
"""
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from services.logger import app_logger

# Above this fraction of masked pixels the hot mask is almost certainly
# eating sky background rather than equipment — warn loudly.
HOT_MASK_WARN_FRACTION = 0.4


class MeteorDiagnostics:
    """Aggregates pipeline counters and emits periodic/transition log lines."""

    def __init__(self, heartbeat_minutes: float = 15.0,
                 now_fn: Callable[[], float] = time.monotonic):
        self._interval = heartbeat_minutes * 60.0
        self._now = now_fn
        self._lock = threading.Lock()
        self._reset_counters()
        self._last_frame_mono: Optional[float] = None
        self._last_frame_wall: str = ""
        self._last_heartbeat_mono: Optional[float] = None
        self._silence_logged = False
        self._roof_suspended = False
        self._hot_warned = False
        self._sigma: float = 0.0
        self._threshold: int = 0
        self._hot_coverage: float = 0.0

    def _reset_counters(self):
        self._frames = 0
        self._runs = 0
        self._skipped = {"warming": 0, "cooldown": 0, "busy": 0}
        self._raw = 0
        self._after_length = 0
        self._after_profile = 0
        self._released = 0
        self._planes = 0

    # ------------------------------------------------------------------ #
    #  Ingest events                                                       #
    # ------------------------------------------------------------------ #

    def frame_received(self) -> Optional[str]:
        with self._lock:
            self._frames += 1
            self._last_frame_mono = self._now()
            self._last_frame_wall = datetime.now().strftime("%H:%M:%S")
            if self._last_heartbeat_mono is None:
                self._last_heartbeat_mono = self._last_frame_mono
            if not self._silence_logged:
                return None
            self._silence_logged = False
        msg = "Meteor: frames resumed — detection active again"
        app_logger.info(msg)
        return msg

    def roof_gate(self, closed: bool) -> Optional[str]:
        """Call every frame with the roof state; logs only on transitions."""
        with self._lock:
            if closed == self._roof_suspended:
                return None
            self._roof_suspended = closed
        msg = ("Meteor: detection suspended — roof reported closed" if closed
               else "Meteor: detection resumed — roof reported open")
        app_logger.info(msg)
        return msg

    def detection_skipped(self, reason: str) -> None:
        """reason: 'warming' | 'cooldown' | 'busy'."""
        with self._lock:
            if reason in self._skipped:
                self._skipped[reason] += 1

    def detection_run(self, hot_coverage: float, sigma: float, threshold: int,
                      raw: int, after_length: int, after_profile: int,
                      released: int, planes: int) -> Optional[str]:
        """Record one detection run's stage counts. Returns the hot-mask
        warning message when coverage crosses the warn fraction, else None."""
        with self._lock:
            self._runs += 1
            self._raw += raw
            self._after_length += after_length
            self._after_profile += after_profile
            self._released += released
            self._planes += planes
            self._sigma = sigma
            self._threshold = threshold
            self._hot_coverage = hot_coverage
            warn = hot_coverage >= HOT_MASK_WARN_FRACTION and not self._hot_warned
            recovered = hot_coverage < HOT_MASK_WARN_FRACTION and self._hot_warned
            self._hot_warned = hot_coverage >= HOT_MASK_WARN_FRACTION

        if warn:
            msg = (f"Meteor: hot mask covers {hot_coverage * 100:.0f}% of the "
                   "frame — transient map is mostly blanked and detection "
                   "cannot fire (detection-frame background too bright?)")
            app_logger.warning(msg)
            return msg
        if recovered:
            msg = (f"Meteor: hot mask coverage back to "
                   f"{hot_coverage * 100:.1f}% — detection unblocked")
            app_logger.info(msg)
            return msg
        return None

    # ------------------------------------------------------------------ #
    #  Periodic heartbeat                                                  #
    # ------------------------------------------------------------------ #

    def maybe_heartbeat(self, enabled: bool) -> Optional[str]:
        """Call periodically (e.g. from a QTimer). Emits at most one line:
        either the interval heartbeat or the one-shot 'frames stopped' note."""
        if not enabled:
            return None
        now = self._now()
        with self._lock:
            if self._last_frame_mono is None:
                return None  # never saw a frame — capture not started

            # Frames dried up: say so ONCE, with the last-frame timestamp.
            # Heartbeats pause until frames resume — the pre-silence counters
            # are stale and a periodic summary of a dead pipeline is noise.
            if (not self._silence_logged
                    and now - self._last_frame_mono >= self._interval):
                self._silence_logged = True
                minutes = (now - self._last_frame_mono) / 60.0
                last_wall = self._last_frame_wall
                self._reset_counters()
                self._last_heartbeat_mono = now
                msg = (f"Meteor: frames stopped — none since {last_wall} "
                       f"({minutes:.0f} min ago); capture stalled, meteor "
                       "disabled mid-session, or app idle")
                app_logger.info(msg)
                return msg

            if (self._silence_logged
                    or self._last_heartbeat_mono is None
                    or now - self._last_heartbeat_mono < self._interval
                    or self._frames == 0):
                return None
            msg = self._format_heartbeat()
            self._last_heartbeat_mono = now
            self._reset_counters()
        app_logger.info(msg)
        return msg

    def flush(self, reason: str) -> Optional[str]:
        """Emit a final heartbeat immediately (e.g. on capture stop)."""
        with self._lock:
            if self._frames == 0 and self._runs == 0:
                return None
            msg = f"{self._format_heartbeat()} [{reason}]"
            self._reset_counters()
        app_logger.info(msg)
        return msg

    def reset(self) -> None:
        """Discard all state (capture stop / session change)."""
        with self._lock:
            self._reset_counters()
            self._last_frame_mono = None
            self._last_frame_wall = ""
            self._last_heartbeat_mono = None
            self._silence_logged = False
            self._roof_suspended = False
            self._hot_warned = False

    # ------------------------------------------------------------------ #
    #  Formatting (call with lock held)                                    #
    # ------------------------------------------------------------------ #

    def _format_heartbeat(self) -> str:
        skipped = ", ".join(f"{v} {k}" for k, v in self._skipped.items() if v)
        parts = [
            f"Meteor heartbeat: {self._frames} frames, {self._runs} detection "
            f"run(s)" + (f" ({skipped} skipped)" if skipped else ""),
            f"candidates {self._raw} raw -> {self._after_length} length-ok -> "
            f"{self._after_profile} profile-ok",
            f"{self._released} meteor(s) released, "
            f"{self._planes} plane track(s) suppressed",
            f"hot mask {self._hot_coverage * 100:.1f}%, "
            f"threshold {self._threshold} (sigma={self._sigma:.2f})",
        ]
        if self._roof_suspended:
            parts.append("roof gate ACTIVE")
        return "; ".join(parts)
