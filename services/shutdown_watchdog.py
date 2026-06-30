"""Force-exit watchdog.

A clean shutdown tears down capture, outputs, timelapse, and the camera SDK.
Any one of those can wedge — a thread join with no timeout, ffmpeg stuck mid
flush, or the ZWO SDK blocking DllMain(DLL_PROCESS_DETACH) inside native code.
When that happens the process hangs *after* the user (or the installer) asked it
to quit, holding the exe + bundled DLLs/pyds locked. That locked zombie is what
makes an in-place upgrade fail: the installer reports success but can't actually
overwrite files a dead-but-still-alive process owns, leaving a mix of old and
new code on disk.

This arms a single daemon timer the moment shutdown begins. If teardown
finishes normally the interpreter exits first and the timer is discarded — it
never fires. If teardown wedges past the timeout, the timer force-terminates the
process so the locks are released no matter where the hang is.
"""
from __future__ import annotations

import os
import sys
import threading

from services.logger import app_logger

# Must exceed the longest *legitimate* teardown step so the watchdog only ever
# fires on a genuine hang. The timelapse finalize blocks up to ~75s flushing
# ffmpeg (see _wait_for_timelapse_finalization); everything else is a few
# seconds. 90s clears that with margin without force-killing a real flush.
DEFAULT_TIMEOUT_SEC = 90.0

_armed = False
_lock = threading.Lock()


def _force_exit() -> None:
    app_logger.error(
        "Shutdown watchdog fired — teardown did not complete in time; "
        "force-terminating the process to release file locks."
    )
    if sys.platform == "win32":
        # Prefer TerminateProcess: it kills without running DLL_PROCESS_DETACH,
        # which is exactly where the ZWO SDK can hang — so it succeeds where a
        # normal exit would itself wedge. argtypes are REQUIRED: without them
        # ctypes truncates the 64-bit pseudo-handle on x64 and the call fails
        # silently (returns FALSE, process keeps running).
        try:
            import ctypes
            from ctypes import wintypes
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.GetCurrentProcess.restype = wintypes.HANDLE
            k.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            k.TerminateProcess.restype = wintypes.BOOL
            if k.TerminateProcess(k.GetCurrentProcess(), 0):
                return
            app_logger.error(
                f"TerminateProcess failed (err={ctypes.get_last_error()}); "
                "falling back to os._exit"
            )
        except Exception as e:
            app_logger.error(f"TerminateProcess raised {e!r}; falling back to os._exit")
    # Cross-platform last resort. Runs ExitProcess on Windows, which can stall
    # on a wedged DLL detach — hence it's the fallback, not the primary path.
    os._exit(1)


def arm_force_exit(timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> None:
    """Start the force-exit timer once. Idempotent — extra calls are no-ops.

    Call at the very start of any shutdown path, before the first blocking
    teardown step, so a wedge anywhere downstream can't keep the process alive.
    The timer is a daemon, so a clean exit (sys.exit) tears it down before it
    fires; it only ever triggers when the process otherwise refuses to die.
    """
    global _armed
    with _lock:
        if _armed:
            return
        _armed = True
    timer = threading.Timer(timeout_sec, _force_exit)
    timer.daemon = True
    timer.start()
    app_logger.debug(f"Shutdown watchdog armed ({timeout_sec:.0f}s)")
