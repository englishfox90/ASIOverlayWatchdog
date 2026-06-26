import os
import re
import threading
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QProgressDialog

from services.logger import app_logger


# Seconds after the first watchdog fire before we declare UI-fatal.
# Gives the self-heal nudge time to land; escalates when it clearly hasn't.
_WATCHDOG_UI_FATAL_GRACE_SEC = 120


def _sdk_call_with_timeout(fn, timeout_sec=10.0, hint=""):
    """Run a blocking ZWO SDK call on a daemon thread with a hard timeout.

    Any ZWO SDK C-extension call can block indefinitely when the camera or
    driver is in a bad state.  Running such calls here (even on a non-GUI
    thread) means the thread is stuck for the life of the process and the UI
    'detecting…' spinner never clears.  The daemon thread is abandoned on
    timeout — it cannot be killed, but it won't prevent process exit.
    """
    result = [None]
    exc = [None]

    def _call():
        try:
            result[0] = fn()
        except Exception as e:
            exc[0] = e

    t = threading.Thread(target=_call, daemon=True)
    t.start()
    t.join(timeout_sec)
    if t.is_alive():
        msg = f"ZWO SDK call timed out after {timeout_sec:.0f}s"
        if hint:
            msg += f" — {hint}"
        raise TimeoutError(msg)
    if exc[0] is not None:
        raise exc[0]
    return result[0]


def _sdk_list_cameras(asi, timeout_sec=8.0):
    raw = _sdk_call_with_timeout(
        asi.list_cameras,
        timeout_sec,
        "a camera may be in a bad USB state. Try the Revive button.",
    )
    return list(raw) if raw is not None else []


class _MainWindowCaptureMixin:

    # =========================================================================
    # CAMERA DETECTION
    # =========================================================================

    def _auto_detect_cameras(self):
        sdk_path = self.config.get('zwo_sdk_path', '')
        if sdk_path and os.path.exists(sdk_path):
            app_logger.info("Auto-detecting cameras on startup...")
            self._startup_detect_retries = 3
            self._on_detect_cameras()

    def _on_detect_cameras(self):
        app_logger.info("=== Camera Detection Initiated ===")

        sdk_path = self.config.get('zwo_sdk_path', '')

        if not sdk_path:
            self.capture_panel.set_detection_error("SDK path not specified")
            return

        if not os.path.exists(sdk_path):
            self.capture_panel.set_detection_error(f"SDK not found: {sdk_path}")
            return

        self.capture_panel.set_detecting(True)

        main_window = self

        def detect_thread():
            cameras = []
            try:
                import zwoasi as asi

                main_window._sdk_phantom_count = 0
                try:
                    _sdk_call_with_timeout(
                        lambda: asi.init(sdk_path),
                        timeout_sec=15.0,
                        hint="SDK init wedged — ZWO driver may need a restart",
                    )
                    app_logger.info(f"ASI SDK initialized: {sdk_path}")
                except TimeoutError as e:
                    main_window.cameras_detected.emit([], str(e))
                    return
                except Exception as e:
                    if "already" not in str(e).lower():
                        main_window.cameras_detected.emit([], f"SDK init failed: {e}")
                        return

                num_cameras = _sdk_call_with_timeout(
                    asi.get_num_cameras,
                    timeout_sec=10.0,
                    hint="SDK wedged — try the Revive button",
                )
                app_logger.info(f"SDK reports {num_cameras} camera(s)")

                if num_cameras == 0:
                    # SDK may be in a stale state from a previous session —
                    # force a full re-init and retry once before giving up
                    app_logger.warning("No cameras found, retrying with fresh SDK init...")
                    try:
                        import importlib
                        importlib.reload(asi)
                        asi.init(sdk_path)
                    except Exception as e:
                        if "already" not in str(e).lower():
                            app_logger.debug(f"SDK re-init note: {e}")

                    time.sleep(1.0)
                    num_cameras = _sdk_call_with_timeout(
                        asi.get_num_cameras,
                        timeout_sec=10.0,
                        hint="SDK wedged on retry — try the Revive button",
                    )
                    app_logger.info(f"SDK retry reports {num_cameras} camera(s)")

                    if num_cameras == 0:
                        main_window.cameras_detected.emit([], "No cameras detected")
                        return

                # Snapshot list_cameras() once and retry if it disagrees with
                # get_num_cameras — the SDK has a race during hot-plug where
                # get_num_cameras briefly reports N but list_cameras returns
                # fewer names. Filling the missing slot with a placeholder
                # like "Camera 0" used to auto-save the placeholder as the
                # user's selected camera, clobbering the real camera_name in
                # config (see production log 2026-04-20 10:15).
                camera_list = []
                for poll_attempt in range(3):
                    camera_list = _sdk_list_cameras(asi)
                    if len(camera_list) >= num_cameras:
                        break
                    app_logger.warning(
                        f"SDK enumeration race: get_num_cameras={num_cameras} "
                        f"but list_cameras returned {len(camera_list)} — "
                        f"retrying in 1s ({poll_attempt + 1}/3)"
                    )
                    time.sleep(1.0)

                for i, name in enumerate(camera_list):
                    cameras.append(f"{name} (Index: {i})")
                    app_logger.info(f"Camera {i}: {name}")

                phantom_count = max(0, num_cameras - len(camera_list))
                if phantom_count:
                    # Device appears in the Windows USB enumeration (hence
                    # get_num_cameras counts it) but the ZWO SDK can't open
                    # it. Usually means the camera's firmware or driver is
                    # in a bad state; a USB disable/enable can revive it.
                    app_logger.error(
                        f"⚠ {phantom_count} camera(s) are driver-visible but "
                        "not openable by the ZWO SDK — likely in a bad state. "
                        "If your saved camera is missing below, use the Revive "
                        "button on the Capture tab to attempt a USB reset."
                    )
                main_window._sdk_phantom_count = phantom_count

                app_logger.info(f"Detection complete: {len(cameras)} camera(s)")
                main_window.cameras_detected.emit(cameras, "")

            except Exception as e:
                app_logger.error(f"Detection failed: {e}")
                main_window.cameras_detected.emit([], str(e))

        threading.Thread(target=detect_thread, daemon=True).start()

    def _on_cameras_detected(self, cameras: list, error: str):
        self.capture_panel.set_detecting(False)

        if error:
            self.capture_panel.set_detection_error(error)
            app_logger.error(f"Camera detection error: {error}")
            self._notify(f"Camera detection: {error}", "error")
            self.app_bar.set_camera_status('idle')
        else:
            self.capture_panel.set_cameras(cameras)
            self._notify(f"{len(cameras)} camera(s) detected")

            self.config.set('available_cameras', cameras)

            if cameras:
                self.app_bar.set_camera_status('connected', 'Ready')

            saved_name = self.config.get('zwo_selected_camera_name', '')

            self.capture_panel.camera_widget.camera_combo.blockSignals(True)

            if '(Index:' in saved_name:
                saved_name = saved_name.split('(Index:')[0].strip()
                self.config.set('zwo_selected_camera_name', saved_name)

            # Placeholder names like "Camera 0" came from a previous detection
            # bug (fixed 2026-04-20) and must be cleared — otherwise the user
            # is locked out of auto-recovery on this rig forever.
            if saved_name and re.fullmatch(r'Camera \d+', saved_name.strip()):
                app_logger.warning(
                    f"Clearing placeholder camera name '{saved_name}' from config "
                    "(artefact of a previous detection bug)"
                )
                self.config.set('zwo_selected_camera_name', '')
                self.config.save()
                saved_name = ''

            found = False
            if saved_name and cameras:
                for i, cam in enumerate(cameras):
                    cam_clean = cam.split(' (Index:')[0] if '(Index:' in cam else cam
                    if saved_name == cam_clean:
                        self.capture_panel.camera_widget.camera_combo.setCurrentIndex(i)
                        actual_index = i
                        if '(Index: ' in cam:
                            try:
                                actual_index = int(cam.split('(Index: ')[1].rstrip(')'))
                            except (IndexError, ValueError):
                                pass
                        self.config.set('zwo_selected_camera', actual_index)
                        self.config.save()
                        app_logger.info(
                            f"Restored camera by name: '{saved_name}' "
                            f"(SDK Index: {actual_index})"
                        )
                        found = True
                        self.capture_panel.set_missing_camera_warning('')
                        break

            if saved_name and not found:
                phantom_count = getattr(self, '_sdk_phantom_count', 0)
                retries_left = getattr(self, '_startup_detect_retries', 0)
                if retries_left > 0 and phantom_count == 0:
                    # Camera not yet enumerated (common for 676MC which takes a
                    # few seconds to appear after USB power-on). Retry silently
                    # rather than flashing an error the user can't act on.
                    self._startup_detect_retries -= 1
                    app_logger.info(
                        f"Saved camera '{saved_name}' not yet enumerated — "
                        f"retrying in 5s ({retries_left} attempt(s) left)"
                    )
                    QTimer.singleShot(5000, self._on_detect_cameras)
                    self.capture_panel.camera_widget.camera_combo.blockSignals(False)
                    return

                # Multi-camera rigs (guide cam, NINA imaging cam, etc.) share
                # the USB bus. Silently swapping would hijack another
                # process's session or capture the wrong sky.
                app_logger.error(
                    f"Saved camera '{saved_name}' not found in detected cameras "
                    f"— refusing to auto-select a different camera on a "
                    f"multi-camera rig. Pick one manually on the Capture tab."
                )
                msg = (
                    f"Saved camera '{saved_name}' not detected — SDK sees "
                    f"{phantom_count} device(s) in bad state. Try Revive on "
                    "the Capture tab."
                    if phantom_count > 0 else
                    f"Saved camera '{saved_name}' not detected — select a camera manually"
                )
                self._notify(msg, "error")
                self.capture_panel.clear_camera_selection()
                self.capture_panel.set_missing_camera_warning(
                    saved_name, phantom_count
                )
            elif not saved_name and len(cameras) == 1:
                # Fresh install on an unambiguous single-camera rig: auto-pick so
                # the user isn't staring at an empty combo. We deliberately do
                # NOT auto-pick on a multi-camera rig — grabbing "the first
                # camera" is how a guide camera got hijacked (June 2026).
                cam = cameras[0]
                cam_clean = cam.split(' (Index:')[0] if '(Index:' in cam else cam
                actual_index = 0
                if '(Index: ' in cam:
                    try:
                        actual_index = int(cam.split('(Index: ')[1].rstrip(')'))
                    except (IndexError, ValueError):
                        pass
                self.capture_panel.camera_widget.camera_combo.setCurrentIndex(0)
                self.config.set('zwo_selected_camera', actual_index)
                self.config.set('zwo_selected_camera_name', cam_clean)
                self.config.set('zwo_selected_camera_serial', '')  # learned on connect
                self.config.save()
                app_logger.info(
                    f"Auto-selected camera (first install, single camera): "
                    f"'{cam_clean}' (SDK Index: {actual_index})"
                )
                self.capture_panel.set_missing_camera_warning('')
            elif not saved_name and len(cameras) > 1:
                app_logger.info(
                    f"{len(cameras)} cameras present and none selected — leaving "
                    "the choice to the user (refusing to auto-pick on a multi-camera rig)."
                )
                self.capture_panel.clear_camera_selection()

            self.capture_panel.camera_widget.camera_combo.blockSignals(False)
            self.capture_panel.camera_widget.load_from_config(self.config)

        self._update_start_button()

    # =========================================================================
    # CAPTURE WATCHDOG
    # =========================================================================

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

    # =========================================================================
    # CAPTURE CONTROL
    # =========================================================================

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
            self.app_bar.set_status('waiting')
            self._last_capture_error = None
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
            self._notify(f"Capture failed: {e}", "error")
            self._send_discord_error(f"Failed to start capture: {e}")

    def stop_capture(self):
        try:
            # Update UI immediately for responsive feedback
            self.is_capturing = False
            self.app_bar.set_capturing(False)

            mode = self.config.get('capture_mode', 'camera')

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

        except Exception as e:
            app_logger.error(f"Error stopping capture: {e}")

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
            self.watch_controller.image_processed.connect(
                lambda preview, out, path: self._on_image_processed(preview, out, {}, path)
            )

        watch_dir = self.config.get('watch_directory', '')
        if not watch_dir or not os.path.isdir(watch_dir):
            raise ValueError("Invalid watch directory")

        self.watch_controller.start_watching(watch_dir)
        if self.watch_controller.is_watching:
            app_logger.info(f"Watch mode started: {watch_dir}")

    def _on_camera_error(self, error_msg: str):
        app_logger.error(f"Camera error received: {error_msg}")
        self._last_capture_error = error_msg
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
            self.app_bar.set_status('waiting')
            self._last_capture_error = None
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
