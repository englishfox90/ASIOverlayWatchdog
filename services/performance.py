"""
Performance measurement helpers for PFR Sentinel.

Provides processing time tracking, memory usage, and disk space queries.
"""
import os
import time
import shutil

from .logger import app_logger


class ProcessingTimer:
    """Context manager that measures elapsed processing time."""

    def __init__(self):
        self.elapsed = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed = time.perf_counter() - self._start


def get_memory_usage_mb():
    """Return current process memory usage in megabytes.

    Returns:
        float: RSS memory in MB, or -1.0 on failure.
    """
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        return proc.memory_info().rss / (1024 * 1024)
    except ImportError:
        pass
    except OSError as e:
        app_logger.debug(f"psutil memory query failed: {e}")

    # Fallback for Windows without psutil
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        # Private DLL handles with explicit prototypes. Untyped, the 64-bit
        # pseudo-handle from GetCurrentProcess() is truncated to a C int and
        # GetProcessMemoryInfo silently fails (this returned -1.0 on every
        # frozen build); and prototyping ctypes.windll's shared objects would
        # leak the types into every other caller in the process.
        kernel32 = ctypes.WinDLL('kernel32')
        psapi = ctypes.WinDLL('psapi')
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD,
        ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        if psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            return counters.WorkingSetSize / (1024 * 1024)
    except (ImportError, AttributeError):
        pass
    except OSError as e:
        app_logger.debug(f"Win32 memory query failed: {e}")

    return -1.0


def get_disk_space(path):
    """Return disk space info for the given path.

    Args:
        path: Directory or file path to check

    Returns:
        dict with 'total_gb', 'used_gb', 'free_gb', or None on failure.
    """
    try:
        if not path or not os.path.exists(path):
            return None

        usage = shutil.disk_usage(path)
        return {
            'total_gb': round(usage.total / (1024 ** 3), 2),
            'used_gb': round(usage.used / (1024 ** 3), 2),
            'free_gb': round(usage.free / (1024 ** 3), 2),
        }
    except (OSError, ValueError):
        return None
