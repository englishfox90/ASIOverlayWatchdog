import os
import re
import threading
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QProgressDialog

from services.logger import app_logger

from .camera_detect import (  # re-exported for existing callers
    _CameraDetectMixin,
    _sdk_call_with_timeout,
    _sdk_list_cameras,
)
from .capture_watchdog import _WATCHDOG_UI_FATAL_GRACE_SEC, _CaptureWatchdogMixin


class _MainWindowCaptureMixin(_CameraDetectMixin, _CaptureWatchdogMixin):


    def _wait_for_timelapse_finalization(self, timeout_sec: float = 75.0):
        """Show a non-cancelable progress dialog while the timelapse finalizes.

        Finalizing flushes ffmpeg's buffered frames and joins the process; the
        fragmented MP4 on disk is already playable, but we still block the close
        with a visible dialog rather than letting the window vanish mid-write.
        """
        if not self.timelapse_controller or not self.timelapse_controller.is_finalizing():
            return

        dlg = QProgressDialog(
            "Saving timelapse video, please wait…",
            None,
            0, 0,
            self,
        )
        dlg.setWindowTitle("PFR Sentinel")
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.setCancelButton(None)
        dlg.setMinimumDuration(0)
        dlg.show()
        QApplication.processEvents()

        deadline = time.monotonic() + timeout_sec
        while self.timelapse_controller.is_finalizing() and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.1)

        dlg.close()

    def _send_discord_capture_started(self):
        discord_config = self.config.get('discord', {})
        if not discord_config.get('enabled', False):
            return
        if not discord_config.get('post_startup_shutdown', False):
            return

        def _send():
            try:
                from services.discord_alerts import DiscordAlerts
                alerts = DiscordAlerts(self.config)
                if alerts.is_enabled():
                    alerts.send_capture_started_message()
                    app_logger.info("Discord capture started notification sent")
            except Exception as e:
                app_logger.error(f"Failed to send Discord capture started notification: {e}")

        threading.Thread(target=_send, daemon=True).start()

    def _update_start_button(self):
        if self.is_capturing:
            return
        mode = self.config.get('capture_mode', 'camera')
        if mode == 'camera':
            cameras = self.config.get('available_cameras', [])
            if not cameras:
                self.app_bar.set_start_enabled(False, "No ZWO cameras detected — click Detect Cameras on the Capture tab")
                return
        else:
            watch_dir = self.config.get('watch_directory', '')
            if not watch_dir or not os.path.isdir(watch_dir):
                self.app_bar.set_start_enabled(False, "Set a valid watch directory on the Capture tab")
                return
        self.app_bar.set_start_enabled(True)

    def _lock_camera_picker(self, active: bool):
        """Lock/unlock the Capture-tab camera picker as capture starts/stops."""
        if hasattr(self, 'capture_panel'):
            self.capture_panel.set_capture_active(active)

    def start_capture(self):
        mode = self.config.get('capture_mode', 'camera')

        try:
            self._ensure_output_servers_started()

            if mode == 'camera':
                self._start_camera_capture()
                if (self.camera_controller
                        and not self.camera_controller.is_capturing
                        and not self.camera_controller._capture_starting):
                    app_logger.error("Camera capture failed to start")
                    return
            else:
                self._start_watch_mode()

            self.is_capturing = True
            self.app_bar.set_capturing(True)
            self._lock_camera_picker(True)
            self.app_bar.set_status('waiting')
            self._set_capture_error(None)
            self.push_capture_status()
            self.capture_started.emit()
            self._notify(f"Capture started ({mode} mode)")

            self._send_posthog_capture_started(mode)

            # Faster status updates while capturing
            self.status_timer.setInterval(200)

            self._send_discord_capture_started()

        except Exception as e:
            app_logger.error(f"Failed to start capture: {e}")
            self.is_capturing = False
            self.app_bar.set_capturing(False)
            self._lock_camera_picker(False)
            self._notify(f"Capture failed: {e}", "error")
            self._send_discord_error(f"Failed to start capture: {e}")

    def stop_capture(self):
        try:
            # Update UI immediately for responsive feedback
            self.is_capturing = False
            self.app_bar.set_capturing(False)

            mode = self.config.get('capture_mode', 'camera')

            self._lock_camera_picker(False)

            if mode == 'camera' and self.camera_controller:
                self.camera_controller.stop_capture()
                if hasattr(self, 'capture_panel'):
                    self.capture_panel.reset_camera_capabilities()
            elif self.watch_controller:
                self.watch_controller.stop_watching()

            self.capture_stopped.emit()
            self._notify("Capture stopped")
            self.push_capture_status()

            if self.timelapse_controller:
                self.timelapse_controller.on_capture_stopped()

            if self.meteor_controller:
                self.meteor_controller.on_capture_stopped()

            # Slower status updates when idle
            self.status_timer.setInterval(1000)

            self.app_bar.set_camera_status('connected', 'Ready')

            self._update_start_button()

            app_logger.info("Capture stopped")

            from services.posthog_service import capture_event
            capture_event('capture_stopped', {
                'mode': mode,
                'images_processed': self.image_count,
            })

            # Trim the working set once capture is idle so the operator-visible
            # Task Manager number reflects reality instead of sitting at the
            # processing peak indefinitely. Delayed 3s so the processor's
            # queue has time to drain the frame it was mid-processing when
            # stop was requested — trimming immediately would just get
            # re-faulted right back in. is_capturing is re-checked in the
            # callback so a stop->start within that window doesn't page out
            # memory mid-capture.
            QTimer.singleShot(3000, self._trim_working_set_after_stop)

        except Exception as e:
            app_logger.error(f"Error stopping capture: {e}")

    def _trim_working_set_after_stop(self):
        if self.is_capturing:
            return
        from services.working_set import trim_working_set
        trim_working_set()

    def _send_posthog_capture_started(self, mode: str):
        try:
            from services.posthog_service import capture_event
            from version import __version__

            output_cfg = self.config.get('output', {})
            discord_cfg = self.config.get('discord', {})
            timelapse_cfg = self.config.get('timelapse', {})
            ml_cfg = self.config.get('ml_models', {})
            rtsp_cfg = self.config.get('rtsp', {})

            props = {
                'version': __version__,
                'mode': mode,
                'camera_name': self.config.get('zwo_selected_camera_name', '') if mode == 'camera' else None,
                'auto_exposure': self.config.get('zwo_auto_exposure', False) if mode == 'camera' else None,
                'output_file_enabled': True,
                'output_format': self.config.get('output_format', 'jpg'),
                'output_web_enabled': output_cfg.get('webserver_enabled', False),
                'output_discord_enabled': discord_cfg.get('enabled', False),
                'output_discord_interval_min': discord_cfg.get('periodic_interval_minutes', 30) if discord_cfg.get('periodic_enabled') else None,
                'output_rtsp_enabled': rtsp_cfg.get('enabled', False),
                'weather_enabled': self.weather_service is not None,
                'timelapse_enabled': timelapse_cfg.get('enabled', False),
                'ml_enabled': ml_cfg.get('enabled', False),
                'overlay_count': len(self.config.get('overlays', [])),
                'auto_stretch_enabled': self.config.get('auto_stretch', {}).get('enabled', False),
                'scheduled_capture': self.config.get('scheduled_capture_enabled', False),
            }

            overlays = self.config.get('overlays', [])
            tokens_used = set()
            for ov in overlays:
                tokens_used.update(t.upper() for t in re.findall(r'\{([^}]+)\}', ov.get('text', '')))
            if tokens_used:
                props['overlay_tokens'] = sorted(tokens_used)
            props = {k: v for k, v in props.items() if v is not None}
            capture_event('capture_started', props)
        except Exception:
            pass

    def _ensure_camera_controller(self):
        from ..controllers.camera_controller import CameraControllerQt

        if self.camera_controller:
            return

        self.camera_controller = CameraControllerQt(self)
        self.camera_controller.calibration_status.connect(self.on_calibration_status)
        self.camera_controller.error.connect(self._on_camera_error)
        # frame_ready is emitted on the worker thread — Qt's queued
        # connection is what keeps on_image_captured safe to touch widgets
        # (StatusSprite's QTimer has GUI-thread affinity).
        self.camera_controller.frame_ready.connect(self.on_image_captured)
        self.camera_controller.capture_stopped.connect(self._on_camera_capture_stopped)
        self.camera_controller.capture_started.connect(self._on_camera_capture_started)
        self.camera_controller.camera_revive_done.connect(self._on_camera_revive_done)
        self.camera_controller.raw16_mode_done.connect(self._on_raw16_mode_done)

    def _on_revive_camera(self, camera_name: str):
        self._ensure_camera_controller()
        app_logger.info(f"Revive requested for '{camera_name}'")
        self._notify(f"Trying to revive '{camera_name}' via USB reset…", "info")
        self.camera_controller.revive_missing_camera(camera_name)

    def _on_camera_revive_done(self, success: bool, camera_name: str):
        if hasattr(self, 'capture_panel'):
            self.capture_panel.reset_revive_button()
        msg = (
            f"USB reset completed for '{camera_name}' — re-detecting…"
            if success else
            f"USB reset failed for '{camera_name}'. Admin privileges may be "
            "required, or the device is unresponsive to disable/enable."
        )
        self._notify(msg, "success" if success else "error")
        self._on_detect_cameras()

    def _start_camera_capture(self):
        # start_capture() connects on a worker thread and returns before the
        # camera is open, so is_capturing/zwo_camera aren't ready yet. The chip
        # and RAW16 capabilities are updated from the capture_started signal
        # (_on_camera_capture_started); failures arrive via the error signal.
        self._ensure_camera_controller()
        self.camera_controller.start_capture()

    def _start_watch_mode(self):
        from .controllers.watch_controller import WatchControllerQt

        if not self.watch_controller:
            self.watch_controller = WatchControllerQt(self)
            # Watch mode has its own pipeline (services/processor.py) that never
            # renders the all-sky overlay into the saved file — burn_into_output
            # only applies to the camera-mode path through image_processor.py.
            # dispatch_image is the same clean frame until that gap is closed.
            self.watch_controller.image_processed.connect(
                lambda preview, out, path: self._on_image_processed(preview, out, {}, path, out)
            )

        watch_dir = self.config.get('watch_directory', '')
        if not watch_dir or not os.path.isdir(watch_dir):
            raise ValueError("Invalid watch directory")

        self.watch_controller.start_watching(watch_dir)
        if self.watch_controller.is_watching:
            app_logger.info(f"Watch mode started: {watch_dir}")

    def _on_camera_error(self, error_msg: str):
        app_logger.error(f"Camera error received: {error_msg}")
        self._set_capture_error(error_msg)
        self.push_capture_status()
        self._notify(f"Camera error: {error_msg}", "error")

        if hasattr(self, 'app_bar') and self.app_bar:
            self.app_bar.set_camera_status('error', 'Camera error')

        should_notify = (
            self.camera_controller is None
            or self.camera_controller.should_notify_discord()
        )
        if should_notify:
            self._send_discord_error(f"Camera Error: {error_msg}")
            if self.camera_controller is not None:
                self.camera_controller.mark_discord_notified()
        else:
            app_logger.debug("Discord error suppressed")

    def _on_camera_capture_stopped(self):
        """Handle controller capture_stopped signal.

        Fires when the capture loop has terminated on its own (fatal error).
        Mirrors the state changes that stop_capture() performs, so the UI
        (AppBar buttons, tray menu Start/Stop enablement, status chips) stays
        consistent with reality instead of claiming we're still capturing.
        """
        if not self.is_capturing:
            return

        app_logger.warning("Capture ended unexpectedly — syncing UI state")
        self.stop_capture()
        self.push_capture_status()

    def _on_camera_capture_started(self):
        """Handle controller capture_started signal.

        Fires on the main thread once the worker has actually connected and the
        capture loop is running — the first point where zwo_camera is populated,
        so the reliable place to read camera capabilities (RAW16 support, bit
        depth). Reached both from the user's own button click and from
        auto-recovery (which otherwise leaves the AppBar showing "Start").
        """
        self.app_bar.set_camera_status('connected', 'Connected')
        self._update_camera_capabilities()

        # Auto-recovery restarted capture with no user click, so the rest of the
        # UI state still says "stopped" — sync it. The user-initiated path has
        # already mirrored this in start_capture().
        if not self.is_capturing:
            app_logger.info("Capture resumed by auto-recovery — syncing UI state")
            self.is_capturing = True
            self.app_bar.set_capturing(True)
            self._lock_camera_picker(True)
            self.app_bar.set_status('waiting')
            self._set_capture_error(None)
            self.push_capture_status()

    def _update_camera_capabilities(self):
        """Push the connected camera's RAW16 support to the Capture panel.

        Must run after the camera is open — start_capture() connects on a worker
        thread, so zwo_camera is only populated by the time capture_started fires.
        """
        cam = self.camera_controller.zwo_camera if self.camera_controller else None
        if not cam or not hasattr(self, 'capture_panel'):
            return
        try:
            self.capture_panel.update_camera_capabilities(
                cam.supports_raw16, cam.sensor_bit_depth)
        except Exception as e:
            app_logger.debug(f"Could not update camera capabilities: {e}")

    def _on_raw16_mode_changed(self, enabled: bool):
        if not self.camera_controller or not self.camera_controller.is_capturing:
            return
        # set_raw16_mode() runs off the Qt main thread (it issues blocking SDK
        # calls); the result arrives on raw16_mode_done → _on_raw16_mode_done.
        self.camera_controller.set_raw16_mode(enabled)

    def _on_raw16_mode_done(self, enabled: bool, ok: bool):
        # Revert the toggle if the SDK rejected or failed the mode change.
        if not ok and hasattr(self, 'capture_panel'):
            self.capture_panel._loading_config = True
            self.capture_panel.raw16_switch.set_checked(not enabled)
            self.capture_panel._loading_config = False
