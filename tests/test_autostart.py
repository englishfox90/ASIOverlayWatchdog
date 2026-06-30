"""Tests for services.autostart — Windows logon task registration.

subprocess and the ShellExecute elevation path are fully mocked, so these run
on any platform without touching the real Task Scheduler.
"""
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services import autostart


def _completed(returncode):
    return SimpleNamespace(returncode=returncode, stdout="", stderr="")


@pytest.fixture
def on_windows():
    """Force the module to behave as if running on Windows."""
    with patch.object(autostart, "_IS_WINDOWS", True):
        yield


class TestLaunchCommand:
    def test_frozen_build_uses_executable_directly(self):
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", r"C:\Program Files\PFRSentinel\PFRSentinel.exe"):
            cmd = autostart._resolve_launch_command(auto_start=True)
        assert cmd == r'"C:\Program Files\PFRSentinel\PFRSentinel.exe" --tray --auto-start'

    def test_source_run_appends_main_py(self):
        with patch.object(sys, "frozen", False, create=True), \
             patch.object(sys, "executable", r"C:\Python\python.exe"):
            cmd = autostart._resolve_launch_command(auto_start=True)
        assert cmd.startswith(r'"C:\Python\python.exe" "')
        assert cmd.endswith('main.py" --tray --auto-start')

    def test_auto_start_omitted_when_false(self):
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", r"C:\app\PFRSentinel.exe"):
            cmd = autostart._resolve_launch_command(auto_start=False)
        assert cmd == r'"C:\app\PFRSentinel.exe" --tray'
        assert "--auto-start" not in cmd

    def test_visible_login_omits_tray_but_keeps_autostart(self):
        # "Start on login but NOT in the background": tray off → no --tray, so
        # the window opens visibly, while --auto-start still starts capture.
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", r"C:\app\PFRSentinel.exe"):
            cmd = autostart._resolve_launch_command(auto_start=True, start_in_tray=False)
        assert cmd == r'"C:\app\PFRSentinel.exe" --auto-start'
        assert "--tray" not in cmd

    def test_visible_login_without_capture_has_no_flags(self):
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", r"C:\app\PFRSentinel.exe"):
            cmd = autostart._resolve_launch_command(auto_start=False, start_in_tray=False)
        assert cmd == r'"C:\app\PFRSentinel.exe"'

    def test_enable_passes_start_in_tray_through_to_command(self, on_windows):
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", r"C:\app\PFRSentinel.exe"), \
             patch.object(autostart.subprocess, "run", return_value=_completed(0)) as run:
            assert autostart.enable(auto_start=True, start_in_tray=False) is True
        argv = run.call_args.args[0]
        command = argv[argv.index("/TR") + 1]
        assert "--tray" not in command
        assert "--auto-start" in command


class TestIsEnabled:
    def test_false_off_windows(self):
        with patch.object(autostart, "_IS_WINDOWS", False):
            assert autostart.is_enabled() is False

    def test_true_when_query_succeeds(self, on_windows):
        with patch.object(autostart.subprocess, "run", return_value=_completed(0)):
            assert autostart.is_enabled() is True

    def test_false_when_query_fails(self, on_windows):
        with patch.object(autostart.subprocess, "run", return_value=_completed(1)):
            assert autostart.is_enabled() is False


class TestEnable:
    def test_noop_off_windows(self):
        with patch.object(autostart, "_IS_WINDOWS", False):
            assert autostart.enable() is False

    def test_direct_create_success_builds_logon_task(self, on_windows):
        with patch.object(autostart.subprocess, "run", return_value=_completed(0)) as run:
            assert autostart.enable(auto_start=True) is True
        argv = run.call_args.args[0]
        assert argv[0] == "schtasks.exe"
        assert "/Create" in argv and "/F" in argv
        assert argv[argv.index("/SC") + 1] == "ONLOGON"
        assert argv[argv.index("/RL") + 1] == "HIGHEST"
        assert argv[argv.index("/TN") + 1] == autostart.TASK_NAME

    def test_falls_back_to_elevation_when_denied(self, on_windows):
        # Direct create fails, elevation succeeds, then re-query reports the task exists.
        run_results = [_completed(1), _completed(0)]  # create denied, then is_enabled() query
        with patch.object(autostart.subprocess, "run", side_effect=run_results), \
             patch.object(autostart, "_run_schtasks_elevated", return_value=True) as elev:
            assert autostart.enable() is True
        elev.assert_called_once()

    def test_returns_false_when_elevation_declined(self, on_windows):
        with patch.object(autostart.subprocess, "run", return_value=_completed(1)), \
             patch.object(autostart, "_run_schtasks_elevated", return_value=False):
            assert autostart.enable() is False

    def test_graceful_when_subprocess_raises(self, on_windows):
        with patch.object(autostart.subprocess, "run", side_effect=OSError("boom")), \
             patch.object(autostart, "_run_schtasks_elevated", return_value=False):
            assert autostart.enable() is False


class TestDisable:
    def test_true_when_already_absent(self, on_windows):
        with patch.object(autostart, "is_enabled", return_value=False):
            assert autostart.disable() is True

    def test_direct_delete_success(self, on_windows):
        with patch.object(autostart, "is_enabled", side_effect=[True]), \
             patch.object(autostart.subprocess, "run", return_value=_completed(0)) as run:
            assert autostart.disable() is True
        argv = run.call_args.args[0]
        assert "/Delete" in argv and argv[argv.index("/TN") + 1] == autostart.TASK_NAME

    def test_falls_back_to_elevation(self, on_windows):
        # exists, direct delete denied, elevation runs, re-query shows it gone.
        with patch.object(autostart, "is_enabled", side_effect=[True, False]), \
             patch.object(autostart.subprocess, "run", return_value=_completed(1)), \
             patch.object(autostart, "_run_schtasks_elevated", return_value=True) as elev:
            assert autostart.disable() is True
        elev.assert_called_once()
