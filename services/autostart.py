"""Windows startup registration via Task Scheduler.

Registers PFR Sentinel to launch on user logon so an unattended observatory
PC resumes capture automatically after a reboot. We use a scheduled task
(``schtasks.exe``) rather than a Run-key / Startup-folder shortcut because the
task can run with ``/RL HIGHEST`` — launching elevated *without* a UAC prompt
at every boot. That matters here: the app recommends Administrator rights for
USB camera recovery, and a Run-key launch of an "always run as admin" exe would
prompt for UAC on every logon and stall unattended startup.

Creating an elevated task itself needs admin, so ``enable``/``disable`` retry
through a one-time UAC elevation when the direct call is denied. All functions
no-op gracefully off Windows and on any failure.
"""
from __future__ import annotations

import os
import subprocess
import sys

from services.logger import app_logger

TASK_NAME = "PFR Sentinel Autostart"

_IS_WINDOWS = sys.platform == "win32"
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0


def _resolve_launch_command(auto_start: bool) -> str:
    """Build the ``/TR`` command string for the scheduled task.

    Handles both the frozen PyInstaller build (``sys.executable`` is the app
    exe) and a source run (``sys.executable`` is python; we append main.py).
    Paths are quoted because the install dir normally contains a space
    (e.g. ``C:\\Program Files\\PFRSentinel``).
    """
    flags = "--tray --auto-start" if auto_start else "--tray"
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" {flags}'
    main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    return f'"{sys.executable}" "{main_py}" {flags}'


def _run_schtasks(args: list[str]) -> subprocess.CompletedProcess | None:
    """Run schtasks.exe directly (no elevation). Returns None on hard failure."""
    try:
        return subprocess.run(
            ["schtasks.exe", *args],
            capture_output=True,
            text=True,
            creationflags=_NO_WINDOW,
        )
    except Exception as e:
        app_logger.error(f"autostart: schtasks invocation failed: {e}")
        return None


def _run_schtasks_elevated(args: list[str]) -> bool:
    """Re-invoke schtasks.exe elevated via a single UAC prompt (ShellExecute runas).

    ShellExecuteW returns a value > 32 on success. We cannot capture the task's
    own exit code through this path, so success here means "the elevated process
    launched"; callers should re-query state if they need certainty.
    """
    try:
        import ctypes

        params = subprocess.list2cmdline(args)
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "schtasks.exe", params, None, 0)
        if rc > 32:
            return True
        app_logger.warning(f"autostart: elevated schtasks declined or failed (ShellExecute={rc})")
        return False
    except Exception as e:
        app_logger.error(f"autostart: elevated schtasks failed: {e}")
        return False


def is_enabled() -> bool:
    """True if the scheduled task currently exists."""
    if not _IS_WINDOWS:
        return False
    result = _run_schtasks(["/Query", "/TN", TASK_NAME])
    return bool(result and result.returncode == 0)


def enable(auto_start: bool = True) -> bool:
    """Register (or update) the logon task. Returns True on success.

    Tries a direct create first; if that is denied (non-elevated session),
    retries through a UAC elevation prompt.
    """
    if not _IS_WINDOWS:
        app_logger.debug("autostart: enable() is a no-op off Windows")
        return False

    command = _resolve_launch_command(auto_start)
    args = ["/Create", "/TN", TASK_NAME, "/TR", command,
            "/SC", "ONLOGON", "/RL", "HIGHEST", "/F"]

    result = _run_schtasks(args)
    if result and result.returncode == 0:
        app_logger.info(f"autostart: scheduled task created ({command})")
        return True

    if result is not None:
        app_logger.info("autostart: direct create denied, retrying with elevation")
    if _run_schtasks_elevated(args):
        # The elevated process is fire-and-forget; confirm by re-querying.
        if is_enabled():
            app_logger.info(f"autostart: scheduled task created via elevation ({command})")
            return True
    app_logger.error("autostart: failed to create scheduled task")
    return False


def disable() -> bool:
    """Remove the logon task. Returns True if the task is gone afterwards."""
    if not _IS_WINDOWS:
        return False

    if not is_enabled():
        return True

    args = ["/Delete", "/TN", TASK_NAME, "/F"]
    result = _run_schtasks(args)
    if result and result.returncode == 0:
        app_logger.info("autostart: scheduled task removed")
        return True

    if result is not None:
        app_logger.info("autostart: direct delete denied, retrying with elevation")
    _run_schtasks_elevated(args)
    if not is_enabled():
        app_logger.info("autostart: scheduled task removed via elevation")
        return True
    app_logger.error("autostart: failed to remove scheduled task")
    return False
