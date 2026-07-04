import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from services.logger import app_logger


class _MainWindowLifecycleMixin:

    # =========================================================================
    # UPDATE CHECKER
    # =========================================================================

    def _init_update_checker(self):
        from services.update_checker import get_update_checker
        self.update_checker = get_update_checker(on_update_available=self._on_update_available)

        # Check on startup after a short delay (respects 24h cache to avoid API spam)
        QTimer.singleShot(3000, self._do_startup_update_check)

        # Also start the background delayed check for users who leave app running
        self.update_checker.start_delayed_check(delay_hours=24.0)
        app_logger.debug("Update checker initialized")

    def _do_startup_update_check(self):
        self.update_checker.check_for_update(force=False)

    def _on_update_available(self, update_info):
        QTimer.singleShot(0, lambda: self._handle_update_available(update_info))

    def _handle_update_available(self, update_info):
        from version import __version__
        from services.posthog_service import capture_event
        self._notify(f"Update available: v{update_info.latest_version}")
        capture_event('update_available', {
            'current_version': __version__,
            'latest_version': update_info.latest_version,
        })
        if hasattr(self, 'nav_rail'):
            self.nav_rail.set_badge('settings', True, "!")

        self._show_update_dialog(update_info)

    def _show_update_dialog(self, update_info):
        from ..dialogs.update_dialog import show_update_dialog

        if not self.isVisible() and self.system_tray:
            try:
                from PySide6.QtWidgets import QSystemTrayIcon
                if hasattr(self.system_tray, 'tray_icon') and self.system_tray.tray_icon:
                    self.system_tray.tray_icon.showMessage(
                        "Update Available",
                        f"PFR Sentinel v{update_info.latest_version} is available",
                        QSystemTrayIcon.Information,
                        5000
                    )
            except Exception:
                pass

        if not self.isVisible():
            self.show()
            self.activateWindow()

        show_update_dialog(self, update_info)

    def check_for_updates_now(self):
        """Manually trigger an update check (for settings panel button)."""
        if hasattr(self, 'update_checker'):
            from version import __version__
            result = self.update_checker.check_for_update(force=True)
            if result is None:
                from qfluentwidgets import InfoBar, InfoBarPosition
                bar = InfoBar.success(
                    title="Up to Date",
                    content=f"You're running the latest version (v{__version__})",
                    parent=self.content_area,
                    position=InfoBarPosition.TOP,
                    duration=3000
                )
                bar.raise_()
            else:
                if hasattr(self, 'nav_rail'):
                    self.nav_rail.set_badge('settings', True, "!")

    # =========================================================================
    # WINDOW EVENTS
    # =========================================================================

    def closeEvent(self, event):
        # If in tray mode, hide to tray instead of closing
        if self.system_tray is not None:
            event.ignore()
            self.hide()
            app_logger.debug("Window minimized to system tray")
            return

        # Real teardown from here. Arm the force-exit watchdog FIRST so a wedge
        # in any step below (timelapse flush, web server, camera SDK) can't
        # leave a locked zombie that fails the next in-place upgrade.
        from services.shutdown_watchdog import arm_force_exit
        arm_force_exit()

        self._send_discord_shutdown()

        # Stop all timers first to prevent callbacks during shutdown
        if hasattr(self, 'status_timer') and self.status_timer:
            self.status_timer.stop()
        if hasattr(self, 'log_timer') and self.log_timer:
            self.log_timer.stop()
        if hasattr(self, 'watchdog_timer') and self.watchdog_timer:
            self.watchdog_timer.stop()
        if getattr(self, '_web_server_retry_timer', None):
            self._web_server_retry_timer.stop()

        if hasattr(self, 'update_checker') and self.update_checker:
            self.update_checker.stop()

        geo = f"{self.width()}x{self.height()}"
        self.config.set('window_geometry', geo)

        sizes = self.splitter.sizes()
        self.config.set('splitter_sizes', sizes)

        inspector_visible = self.inspector_stack.isVisible()
        self.config.set('inspector_visible', inspector_visible)

        self.config.save()

        if self.is_capturing:
            self.stop_capture()

        if self.image_processor:
            self.image_processor.stop()

        # Drain the output dispatcher before the web server / library it feeds.
        try:
            self._stop_output_dispatcher()
        except Exception:
            pass

        if self.web_server:
            try:
                self.web_server.stop()
            except Exception:
                pass

        # Controller first: its worker threads read via image_library, so
        # joining them before the library closes its SQLite connection avoids
        # an in-flight read hitting a closed DB (sqlite3.ProgrammingError on
        # a background thread, reported as an unhandled crash).
        if self.library_controller:
            try:
                self.library_controller.shutdown()
            except Exception:
                pass

        if self.image_library:
            try:
                self.image_library.stop()
            except Exception:
                pass

        if self.timelapse_controller:
            try:
                self._wait_for_timelapse_finalization()
                self.timelapse_controller.shutdown()
            except Exception:
                pass

        if self.allsky_controller:
            try:
                self.allsky_controller.shutdown()
            except Exception:
                pass

        if self.meteor_controller:
            try:
                self.meteor_controller.shutdown()
            except Exception:
                pass

        self.save_config()

        app_logger.info("Application closing")
        event.accept()

        # Force quit the application to ensure all threads exit
        QApplication.quit()

    def quit_application(self):
        """Properly quit application (called from tray exit)"""
        # Arm the force-exit watchdog before touching the tray or running
        # teardown: tray Exit and the installer's --shutdown both land here, and
        # both must guarantee the process actually dies (releasing file locks)
        # even if a teardown step wedges. Idempotent — closeEvent re-arming is a
        # no-op. See services/shutdown_watchdog.py.
        from services.shutdown_watchdog import arm_force_exit
        arm_force_exit()

        if self.system_tray and hasattr(self.system_tray, 'tray_icon') and self.system_tray.tray_icon:
            try:
                self.system_tray.tray_icon.stop()
            except Exception:
                pass

        self.system_tray = None
        self.close()

    def restart_application(self, reason: str = "") -> bool:
        """Relaunch the app cleanly — last-resort camera recovery.

        Schedules a detached waiter to relaunch us, then runs the normal
        tray-exit teardown (which stops capture/outputs and releases the
        single-instance lock and web-server port) so the replacement can claim
        them. Returns True if a restart was scheduled (app is now quitting),
        False if it could not be — the caller then falls back to alert-and-wait.
        """
        from services.app_restart import schedule_restart
        if not schedule_restart(reason):
            return False
        app_logger.warning(f"Restarting application for camera recovery — {reason}")
        # Force a full teardown even in tray mode: clearing system_tray makes
        # closeEvent run the real shutdown path instead of hiding to tray.
        try:
            self.quit_application()
        except Exception:
            from PySide6.QtWidgets import QApplication
            QApplication.quit()
        return True

    def set_tray_mode(self, enabled: bool):
        """Enable or disable system tray mode

        Args:
            enabled: True to enable tray mode, False to disable
        """
        if enabled and self.system_tray is None:
            try:
                from ..system_tray_qt import SystemTrayQt, PYSTRAY_AVAILABLE

                if not PYSTRAY_AVAILABLE:
                    app_logger.warning("System tray mode requires pystray package")
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(
                        self,
                        "Missing Dependency",
                        "System tray mode requires the 'pystray' package.\n\n"
                        "Install with: pip install pystray"
                    )
                    self.config.set('tray_mode_enabled', False)
                    if hasattr(self, 'settings_panel'):
                        self.settings_panel.tray_enabled_switch.setChecked(False)
                    return

                # start_hidden=False: enabling tray from Settings must not yank
                # the window away — it stays open and only hides on close.
                self.system_tray = SystemTrayQt(
                    self, QApplication.instance(), auto_start=False, start_hidden=False
                )
                app_logger.info("System tray enabled - window will minimize to tray on close")

            except Exception as e:
                app_logger.error(f"Failed to enable system tray: {e}")
                self.system_tray = None
                self.config.set('tray_mode_enabled', False)
                if hasattr(self, 'settings_panel'):
                    self.settings_panel.tray_enabled_switch.setChecked(False)

        elif not enabled and self.system_tray is not None:
            try:
                if hasattr(self.system_tray, 'tray_icon') and self.system_tray.tray_icon:
                    self.system_tray.tray_icon.stop()
                self.system_tray = None
                app_logger.info("System tray disabled - window will close normally")
            except Exception as e:
                app_logger.error(f"Error disabling system tray: {e}")
                self.system_tray = None

        # Tray mode also decides whether the logon task starts hidden, so keep
        # the registered command in sync. Base it on the real outcome (did the
        # tray actually come up?), not the requested flag. No-op unless start-on-
        # login is enabled; may surface a one-time UAC prompt to update the task.
        if self.config.get('run_on_startup', False):
            from services import autostart
            autostart.enable(
                auto_start=self.config.get('autostart_capture', True),
                start_in_tray=self.system_tray is not None,
            )

    def set_run_on_startup(self, enabled: bool, auto_start: bool = True):
        """Register or remove the Windows logon task and report the outcome.

        Returns True on success. Reverts the Settings switch + config on failure
        (e.g. the user declines the one-time UAC elevation), matching the
        self-healing pattern set_tray_mode uses for its switch.
        """
        from services import autostart

        # Tray mode decides whether the logon launch is hidden (--tray) or opens
        # a visible window. "Start on login but NOT in the background" = tray off.
        start_in_tray = self.config.get('tray_mode_enabled', False)
        if enabled:
            ok = autostart.enable(auto_start=auto_start, start_in_tray=start_in_tray)
        else:
            ok = autostart.disable()

        if ok:
            self.config.set('run_on_startup', enabled)
            self.config.set('autostart_capture', auto_start)
            self.config.save()
            self._notify_startup_result(enabled, success=True)
        else:
            # Revert UI to the real task state so the switch never lies.
            self.config.set('run_on_startup', autostart.is_enabled())
            self.config.save()
            if hasattr(self, 'settings_panel'):
                self.settings_panel.refresh_startup_switches(self.config)
            self._notify_startup_result(enabled, success=False)
        return ok

    def _notify_startup_result(self, enabled: bool, success: bool):
        from PySide6.QtCore import Qt
        from qfluentwidgets import InfoBar, InfoBarPosition
        try:
            if success:
                msg = ("PFR Sentinel will start with Windows."
                       if enabled else "PFR Sentinel will no longer start with Windows.")
                InfoBar.success(
                    title="Startup updated", content=msg, orient=Qt.Horizontal,
                    isClosable=True, position=InfoBarPosition.TOP, duration=6000, parent=self,
                )
            else:
                InfoBar.warning(
                    title="Startup not changed",
                    content=("Could not update the Windows startup task. Administrator "
                             "approval is required — please accept the prompt and try again."),
                    orient=Qt.Horizontal, isClosable=True, position=InfoBarPosition.TOP,
                    duration=10000, parent=self,
                )
        except Exception as e:
            app_logger.debug(f"startup InfoBar failed: {e}")
