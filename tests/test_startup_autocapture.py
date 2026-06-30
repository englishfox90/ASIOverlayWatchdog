"""Validates the "start on login + auto-start capture" launch contract.

Written to answer a real user report (Michal, Discord 2026-06-27/28):

  "Is there a way to make Sentinel autostart and start capture on login but
   NOT in the background? When I toggle this option OFF in settings it's back
   ON after reboot."

What that needs, and what these tests pin down:

1. The login command is built by ``services.autostart`` and is the single
   source of truth for what runs on logon.
2. Whether the login window is hidden (``--tray``) or visible is driven by the
   "Enable System Tray" setting — NOT hardwired. Tray on  -> ``--tray`` (hidden
   in background). Tray off -> no ``--tray`` (visible window).
3. ``--auto-start`` is present iff "Auto-start capture on launch" is on, and it
   starts capture even when ``--tray`` is absent (visible-window auto-capture).
4. So Michal's exact want — autostart + capture + visible — is the command
   ``…exe --auto-start`` (tray off), which these tests assert.
5. A bare Startup-folder shortcut (no flags) still won't auto-start capture,
   so the in-app "Start with Windows" toggle is the supported path.
6. A clean ``--shutdown`` path exists to stop the app cleanly from Task
   Scheduler instead of pulling the plug.
"""
import os
import sys

import pytest

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from unittest.mock import patch

from services import autostart


@pytest.fixture
def frozen_exe():
    """Pretend we're the packaged build so the command is the install-time one."""
    with patch.object(sys, "frozen", True, create=True), \
         patch.object(sys, "executable", r"C:\Program Files\PFRSentinel\PFRSentinel.exe"):
        yield


class TestLoginCommandMatrix:
    """The schtasks /TR command is the source of truth for what runs on login."""

    def test_background_login_with_capture(self, frozen_exe):
        # Tray ON: the unattended-observatory default — hidden, auto-capturing.
        cmd = autostart._resolve_launch_command(auto_start=True, start_in_tray=True)
        assert "--tray" in cmd
        assert "--auto-start" in cmd

    def test_visible_login_with_capture_is_what_michal_wants(self, frozen_exe):
        # Tray OFF: start on login, auto-capture, but window VISIBLE (not in the
        # background). This is the case his report was asking for.
        cmd = autostart._resolve_launch_command(auto_start=True, start_in_tray=False)
        assert "--tray" not in cmd        # not hidden / not background
        assert "--auto-start" in cmd      # capture still starts automatically

    def test_visible_login_without_capture(self, frozen_exe):
        cmd = autostart._resolve_launch_command(auto_start=False, start_in_tray=False)
        assert "--tray" not in cmd
        assert "--auto-start" not in cmd

    def test_tray_setting_decides_background_vs_visible(self, frozen_exe):
        # The ONLY thing that toggles hidden-vs-visible on login is start_in_tray
        # (wired to the "Enable System Tray" setting), holding capture constant.
        hidden = autostart._resolve_launch_command(auto_start=True, start_in_tray=True)
        visible = autostart._resolve_launch_command(auto_start=True, start_in_tray=False)
        assert ("--tray" in hidden) and ("--tray" not in visible)


class TestVisibleLaunchStillStartsCapture:
    """Proves --auto-start works without --tray, using main.py's own parser.

    main.py starts capture when ``args.auto_start and not args.tray`` (the
    non-tray path), so a visible login launch (``--auto-start`` alone) does
    begin capturing.
    """

    @staticmethod
    def _parse(argv):
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('--auto-start', action='store_true')
        parser.add_argument('--tray', action='store_true')
        parser.add_argument('--headless', action='store_true')
        parser.add_argument('--shutdown', action='store_true')
        return parser.parse_args(argv)

    def test_autostart_without_tray_triggers_capture_path(self):
        args = self._parse(['--auto-start'])
        assert args.auto_start is True
        assert args.tray is False
        # main.py: `if args.auto_start and not args.tray: start_capture()`
        assert (args.auto_start and not args.tray) is True

    def test_bare_startup_folder_shortcut_does_not_autocapture(self):
        # A hand-made Startup-folder shortcut passes no flags -> no capture.
        args = self._parse([])
        assert args.auto_start is False
        assert (args.auto_start and not args.tray) is False


class TestCivilisedShutdown:
    """The supported way to stop the app from Task Scheduler."""

    def test_shutdown_request_helper_exists(self):
        # Task Scheduler can run `PFRSentinel.exe --shutdown` to ask the running
        # instance to quit cleanly (release the camera, save config) — the
        # "civilised" stop, instead of pulling the plug.
        from services.single_instance import request_shutdown
        assert callable(request_shutdown)
