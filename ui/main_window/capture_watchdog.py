"""Wedged-capture watchdog for the main window.

Split out of `capture.py` (which was over the size cap). The watchdog only
observes capture state and escalates through `camera_controller`; it never
starts or stops capture itself.
"""
import time

from services.logger import app_logger


# Seconds after the first watchdog fire before we declare UI-fatal.
# Gives the self-heal nudge time to land; escalates when it clearly hasn't.
_WATCHDOG_UI_FATAL_GRACE_SEC = 120


class _CaptureWatchdogMixin:
    """Two-stage detector for a capture thread stuck inside the ZWO SDK."""

    def _check_capture_watchdog(self):
        """Two-stage wedged-capture detector.

        Stage 2 declares fatal because the capture thread is stuck inside
        a C SDK call that can't see our _recovery_requested flag; UI sync
        is safe because _dying_camera + _join_or_skip_dying_camera handle
        the wedged thread asynchronously.
        """
        if not self.is_capturing or not self.camera_controller:
            self._reset_watchdog_state()
            return

        cam = getattr(self.camera_controller, 'zwo_camera', None)
        if not cam:
            self._reset_watchdog_state()
            return

        if getattr(cam, 'is_capturing', False) is False:
            self._reset_watchdog_state()
            return

        last_frame = getattr(cam, '_last_frame_time', None)
        if last_frame is None:
            return

        interval = getattr(cam, 'capture_interval', 5.0) or 5.0
        exposure_sec = getattr(cam, 'exposure_seconds', 0.0) or 0.0
        threshold = max(3 * interval, 180.0, exposure_sec + 60.0)
        stale_for = time.time() - last_frame

        if stale_for < threshold:
            self._reset_watchdog_state()
            return

        if getattr(cam, 'long_retry_mode_public', False):
            return

        if self._watchdog_first_fire_ts is None:
            self._watchdog_first_fire_ts = time.time()
            app_logger.error(
                f"⚠ Capture watchdog: no frames for {stale_for:.0f}s "
                f"(threshold {threshold:.0f}s) — nudging capture thread to self-heal"
            )
            cam._recovery_requested = True
            try:
                self.camera_controller._on_camera_error(
                    f"Capture wedged — no frames for {int(stale_for)}s; "
                    f"requesting capture thread to self-heal",
                    is_fatal=False,
                )
            except TypeError:
                self.camera_controller._on_camera_error(
                    f"Capture wedged — no frames for {int(stale_for)}s"
                )
            return

        if self._watchdog_ui_fatal_sent:
            return
        since_first = time.time() - self._watchdog_first_fire_ts
        if since_first >= _WATCHDOG_UI_FATAL_GRACE_SEC:
            self._watchdog_ui_fatal_sent = True
            app_logger.error(
                f"⚠ Capture still stalled after {int(since_first)}s since first "
                "alert — SDK call not returning. Syncing UI state."
            )
            try:
                self.camera_controller._on_camera_error(
                    "Capture thread appears permanently wedged inside the ZWO SDK. "
                    "Auto-recovery will keep trying; the app may need a manual "
                    "restart if this persists.",
                    is_fatal=True,
                )
            except TypeError:
                self.camera_controller._on_camera_error(
                    "Capture thread appears permanently wedged inside the ZWO SDK."
                )

    def _reset_watchdog_state(self):
        self._watchdog_first_fire_ts = None
        self._watchdog_ui_fatal_sent = False
