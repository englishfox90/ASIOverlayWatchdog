"""ZWO SDK camera enumeration for the main window.

Split out of `capture.py` (which was over the size cap). Owns the blocking-SDK
timeout wrappers and the full detect -> restore-saved-camera flow; the capture
lifecycle itself stays in `capture.py`.
"""
import os
import re
import threading
import time

from PySide6.QtCore import QTimer

from services.logger import app_logger


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



class _CameraDetectMixin:
    """Camera enumeration and saved-camera restoration."""

    def _auto_detect_cameras(self):
        sdk_path = self.config.get('zwo_sdk_path', '')
        if sdk_path and os.path.exists(sdk_path):
            app_logger.info("Auto-detecting cameras on startup...")
            self._startup_detect_retries = 3
            self._on_detect_cameras()

    def _on_detect_cameras(self):
        # Coalesce overlapping triggers. The Detect button, the AppBar connect
        # action, the missing-camera "Detect Again" button and the startup
        # auto-detect can all fire near-simultaneously, each spawning a full
        # enumeration thread (four ran in 3s on 2026-06-26). One in-flight
        # detection is enough; ignore re-entrant calls until it completes. The
        # flag is cleared in _on_cameras_detected, which every detect path
        # reaches via the cameras_detected signal.
        if getattr(self, '_detection_in_progress', False):
            app_logger.debug("Camera detection already in progress — ignoring duplicate trigger")
            return

        app_logger.info("=== Camera Detection Initiated ===")

        sdk_path = self.config.get('zwo_sdk_path', '')

        if not sdk_path:
            self.capture_panel.set_detection_error("SDK path not specified")
            return

        if not os.path.exists(sdk_path):
            self.capture_panel.set_detection_error(f"SDK not found: {sdk_path}")
            return

        self._detection_in_progress = True
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
        self._detection_in_progress = False
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
