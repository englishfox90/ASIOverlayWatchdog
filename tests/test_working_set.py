"""
Tests for services/working_set.py and the capture-stop trim wiring.

trim_working_set() itself is a thin wrapper over SetProcessWorkingSetSize —
covered directly here (non-Windows no-op, and on Windows a real measurable
drop). The capture-stop scheduling in ui/main_window/capture.py is covered
via a stub object carrying the real mixin methods, following the pattern in
tests/test_web_server_retry.py.
"""
import sys
import types

import pytest
from unittest.mock import MagicMock, patch

from services.working_set import trim_working_set


class TestTrimWorkingSetNonWindows:
    def test_returns_false_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        assert trim_working_set() is False

    def test_never_raises_when_ctypes_windll_missing(self, monkeypatch):
        # sys.platform stays 'win32' here (as it is on this dev box) but
        # ctypes.windll is unavailable on non-Windows Pythons — simulate that
        # by making the attribute access raise, and confirm we swallow it.
        monkeypatch.setattr(sys, "platform", "win32")
        import ctypes

        class _NoWindll:
            def __getattr__(self, name):
                raise AttributeError(name)

        monkeypatch.setattr(ctypes, "windll", _NoWindll(), raising=False)
        assert trim_working_set() is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only working-set API")
class TestTrimWorkingSetWindows:
    def test_returns_true_on_success(self):
        assert trim_working_set() is True

    @pytest.mark.slow
    def test_working_set_actually_drops(self):
        import ctypes
        from ctypes import wintypes
        import numpy as np

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

        psapi = ctypes.WinDLL("psapi.dll")
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD,
        ]
        handle = kernel32.GetCurrentProcess()

        def _working_set_size():
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
            return counters.WorkingSetSize

        # Allocate and touch ~200 MB so it's actually resident, not just
        # reserved virtual address space.
        block = np.ones((200, 1024, 1024), dtype=np.uint8)
        block[:] = 1
        before = _working_set_size()
        del block

        assert trim_working_set() is True
        after = _working_set_size()

        assert (before - after) >= 100 * 1024 * 1024


def _make_stopped_window():
    from ui.main_window.capture import _MainWindowCaptureMixin

    win = MagicMock()
    win.is_capturing = True
    win.config = {"capture_mode": "watch"}
    win.camera_controller = None
    win.watch_controller = MagicMock()
    win.image_count = 0

    win.stop_capture = types.MethodType(_MainWindowCaptureMixin.stop_capture, win)
    win._trim_working_set_after_stop = types.MethodType(
        _MainWindowCaptureMixin._trim_working_set_after_stop, win
    )
    return win


class TestCaptureStopSchedulesTrim:
    def test_stop_capture_schedules_trim_three_seconds_out(self):
        win = _make_stopped_window()

        with patch("ui.main_window.capture.QTimer.singleShot") as mock_single_shot:
            win.stop_capture()

        mock_single_shot.assert_called_once()
        delay, callback = mock_single_shot.call_args[0]
        assert delay == 3000
        assert callback == win._trim_working_set_after_stop

    def test_scheduled_callback_trims_when_still_stopped(self):
        win = _make_stopped_window()
        win.is_capturing = False  # capture stayed stopped through the delay

        with patch("services.working_set.trim_working_set") as mock_trim:
            win._trim_working_set_after_stop()

        mock_trim.assert_called_once()

    def test_scheduled_callback_skips_trim_if_capture_restarted(self):
        win = _make_stopped_window()
        win.is_capturing = True  # a stop->start happened within the delay window

        with patch("services.working_set.trim_working_set") as mock_trim:
            win._trim_working_set_after_stop()

        mock_trim.assert_not_called()


class TestImageProcessorWorkerUsesService:
    def test_trim_working_set_delegates_to_service(self):
        QtWidgets = pytest.importorskip("PySide6.QtWidgets")
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

        from ui.controllers.image_processor import ImageProcessorWorker

        worker = ImageProcessorWorker()
        with patch("services.working_set.trim_working_set") as mock_trim:
            worker._trim_working_set()

        mock_trim.assert_called_once()


class TestHeadlessStopTrimsWorkingSet:
    def test_control_api_stop_trims_directly(self):
        from services.headless_runner import HeadlessRunner

        runner = HeadlessRunner.__new__(HeadlessRunner)
        runner._paused = MagicMock()
        runner._wake = MagicMock()
        runner.running = True

        logged = []
        runner._log = logged.append

        with patch("services.working_set.trim_working_set") as mock_trim:
            runner._handle_capture_command("stop")

        runner._paused.set.assert_called_once()
        mock_trim.assert_called_once()

    def test_control_api_start_does_not_trim(self):
        from services.headless_runner import HeadlessRunner

        runner = HeadlessRunner.__new__(HeadlessRunner)
        runner._paused = MagicMock()
        runner._wake = MagicMock()
        runner.running = True

        logged = []
        runner._log = logged.append

        with patch("services.working_set.trim_working_set") as mock_trim:
            runner._handle_capture_command("start")

        runner._paused.clear.assert_called_once()
        mock_trim.assert_not_called()
