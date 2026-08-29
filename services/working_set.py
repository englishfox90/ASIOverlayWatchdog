"""
Process working-set trim (Windows only).

PFR Sentinel runs 24/7 unattended on an observatory PC, and the operator's
only real-time sanity check that the app is behaving is Task Manager's
"Memory" column. After a capture session, private working set idles around
~1 GB even though the process has released essentially everything it was
holding — those are resident-but-untouched pages left over from processing
12.6 MP frames that Windows never reclaimed on its own (measured: forcing a
trim drops the idle GUI to ~75 MB re-touched).

Calling SetProcessWorkingSetSize(-1, -1) asks Windows to page the working set
down to only what's actually live right now. Nothing is freed and no virtual
address space changes — any page touched again is simply re-faulted in on
demand — so this is a no-op for correctness. It's purely cosmetic for the
operator-visible number, and cheap enough to call at capture cadence.
"""
import sys

from .logger import app_logger


def trim_working_set() -> bool:
    """Ask Windows to trim this process's working set.

    Returns True if the trim call succeeded, False on non-Windows platforms
    or any failure. Never raises.
    """
    if sys.platform != 'win32':
        return False

    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32

        # Explicit argtypes/restype matter here: without them ctypes marshals
        # the raw literal -1 as a 32-bit int on a 64-bit HANDLE/SIZE_T ABI,
        # which is a latent correctness bug even though it happens to work on
        # most builds. c_size_t(-1) is the well-defined "no minimum/maximum"
        # sentinel per the Win32 API contract.
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.SetProcessWorkingSetSize.restype = wintypes.BOOL
        kernel32.SetProcessWorkingSetSize.argtypes = [
            wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t,
        ]

        handle = kernel32.GetCurrentProcess()
        ok = kernel32.SetProcessWorkingSetSize(
            handle, ctypes.c_size_t(-1), ctypes.c_size_t(-1)
        )
        return bool(ok)
    except Exception as e:
        app_logger.debug(f"trim_working_set failed: {e}")
        return False
