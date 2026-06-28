"""
Roof safety-file confirmation FSM (Policy A — fail-safe).

Decides *when* the ASCOM safety file is (re)written, separately from
`ASCOMSafetyWriter` which decides *what* trigger text to write. Extracted from
the image processor so the safety-critical state machine is independently
testable and keeps the controller under its size cap.

Policy A guarantees:
- SAFE is NEVER certified without two consecutive confident-Open frames — not
  even on the first frame of a session (a single startup false-positive must not
  write OPEN).
- The session baseline is established as UNSAFE immediately, which also clears
  any stale OPEN file left by a previous run.
- Transitions in both directions require two consecutive confirming frames, so a
  single noisy frame can't flip the file.
- A write that is *attempted and genuinely fails* escalates (once per failure
  run); a benign skip (feature disabled / no path configured) does not.
- During a long steady session the confirmed state is re-stamped on a heartbeat
  so NINA's "maximum file age" check can't flag a healthy session as stale.
"""
import time
from typing import Any, Callable, Dict, Optional

from services.logger import app_logger
from services.ascom_safety import write_ascom_safety_file, is_safe_open

# A synthetic UNSAFE reading used to force a CLOSED write (e.g. to clear a stale
# OPEN at startup) regardless of the current frame's prediction.
UNSAFE_RESULT: Dict[str, Any] = {'roof_status': 'N/A', 'roof_confidence': None}

_DEFAULT_HEARTBEAT_SECONDS = 300


class RoofSafetyFSM:
    """Confirmed-state machine driving the ASCOM safety-file write."""

    def __init__(
        self,
        writer: Callable[[Dict[str, Any], Dict[str, Any]], bool] = write_ascom_safety_file,
        on_failure: Optional[Callable[[], None]] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        # _confirmed_safe is the verdict that has been DURABLY WRITTEN: None
        # until the session baseline lands, then True (OPEN) / False (CLOSED).
        self._confirmed_safe: Optional[bool] = None
        self._pending_safe: Optional[bool] = None
        self._pending_safe_count = 0
        self._write_failed = False
        self._last_write_time: Optional[float] = None
        self._writer = writer
        self._on_failure = on_failure
        self._clock = clock

    # --- public API ---------------------------------------------------------

    def update(self, ml_results: Dict[str, Any], ascom_config: Dict[str, Any]) -> None:
        """Feed one frame's ML result (or a synthetic UNSAFE one) through the FSM."""
        safe = self._verdict(ml_results, ascom_config)

        if self._confirmed_safe is None:
            self._establish_baseline(safe, ml_results, ascom_config)
            return

        if safe == self._confirmed_safe:
            self._pending_safe = None
            self._pending_safe_count = 0
            self._maybe_heartbeat(ml_results, ascom_config)
            return

        if self._pending_safe == safe:
            self._pending_safe_count += 1
        else:
            self._pending_safe = safe
            self._pending_safe_count = 1

        if self._pending_safe_count >= 2:
            if self._write(ml_results, ascom_config):
                self._confirmed_safe = safe
                self._pending_safe = None
                self._pending_safe_count = 0
            # On a non-durable write leave the confirmed/pending state intact
            # (count stays >= 2) so the next identical frame retries immediately.

    # --- internals ----------------------------------------------------------

    @staticmethod
    def _verdict(ml_results: Dict[str, Any], ascom_config: Dict[str, Any]) -> bool:
        # Same verdict the writer uses to choose the trigger text — one home, so
        # "should we write SAFE?" can't drift between the two.
        return is_safe_open(ml_results, ascom_config.get('min_confidence', 0.7))

    def _establish_baseline(self, safe: bool, ml_results: Dict[str, Any],
                            ascom_config: Dict[str, Any]) -> None:
        # Always establish the file as UNSAFE first. This clears any stale OPEN
        # from a previous run and refuses to certify SAFE on a single frame:
        # even a confident Open here writes CLOSED and must then be confirmed.
        results = UNSAFE_RESULT if safe else ml_results
        if not self._write(results, ascom_config):
            return  # not durable -> stay un-baselined, retry next frame
        self._confirmed_safe = False
        if safe:
            # Count this confident-Open frame as the first of the two needed to
            # flip to SAFE.
            self._pending_safe = True
            self._pending_safe_count = 1
        else:
            self._pending_safe = None
            self._pending_safe_count = 0

    def _maybe_heartbeat(self, ml_results: Dict[str, Any],
                         ascom_config: Dict[str, Any]) -> None:
        interval = ascom_config.get('heartbeat_seconds', _DEFAULT_HEARTBEAT_SECONDS)
        if not interval or interval <= 0 or self._last_write_time is None:
            return
        if self._clock() - self._last_write_time >= interval:
            # Verdict equals the confirmed state on this branch, so re-stamping
            # the current frame keeps the file's content consistent while
            # refreshing its timestamp for NINA's max-age check.
            self._write(ml_results, ascom_config)

    def _write(self, ml_results: Dict[str, Any], ascom_config: Dict[str, Any]) -> bool:
        try:
            ok = bool(self._writer(ml_results, ascom_config))
        except Exception as e:
            ok = False
            app_logger.error(f"ASCOM Safety: write raised: {e}")

        if ok:
            self._write_failed = False
            self._last_write_time = self._clock()
            return True

        # Only a write that was actually attempted-and-failed is escalated. A
        # benign skip (feature disabled or no file_path configured) must not
        # trigger the "write FAILED - check disk" alarm or a retry storm.
        configured = bool(ascom_config.get('enabled', False) and ascom_config.get('file_path'))
        if configured:
            self._escalate()
        return False

    def _escalate(self) -> None:
        if self._write_failed:
            return  # already escalated this failure run; don't spam
        self._write_failed = True
        if self._on_failure is None:
            return
        try:
            self._on_failure()
        except Exception as e:
            app_logger.warning(f"ASCOM safety failure escalation failed: {e}")
