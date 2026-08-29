"""ZWO camera capture worker.

Holds the single-frame capture routine and the long-running capture loop with
reconnect/backoff logic. Split out of services/zwo_camera.py to keep both
files under the project size cap. Functions take a ZWOCamera instance and
operate on its attributes — they are not standalone; they rely on the camera's
connection, calibration manager, and callbacks.
"""
from __future__ import annotations

import time
import traceback
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np

from .camera_utils import call_with_timeout
from .frame_builder import build_frame
from ..posthog_service import capture_error

if TYPE_CHECKING:
    from .zwo_camera import ZWOCamera


def _get_temperature(camera: "ZWOCamera"):
    try:
        temp_value = camera.camera.get_control_value(camera.asi.ASI_TEMPERATURE)[0]
        temp_celsius = temp_value / 10.0
        temp_fahrenheit = (temp_celsius * 9 / 5) + 32
        return {
            'display': f"{temp_celsius:.1f} C",
            'celsius_str': f"{temp_celsius:.1f}°C",
            'fahrenheit_str': f"{temp_fahrenheit:.1f}°F",
        }
    except Exception:
        return {'display': "N/A", 'celsius_str': "N/A", 'fahrenheit_str': "N/A"}


def capture_single_frame(camera: "ZWOCamera"):
    """Capture a single frame and return (PIL image, metadata dict)."""
    if not camera.camera:
        raise Exception("Camera not connected")

    # Honour a watchdog-requested self-heal before opening a new exposure.
    # See ZWOCamera._recovery_requested.
    if getattr(camera, '_recovery_requested', False):
        camera._recovery_requested = False
        raise Exception(
            "Recovery requested by watchdog — triggering internal reconnect"
        )

    sdk_lock = camera._connection.sdk_lock

    try:
        # Enforce max exposure limit as a safety net.
        # The auto-exposure algorithm should already clamp, but this catches
        # edge cases (stale calibration manager, manual set_exposure, etc.).
        if camera.auto_exposure and camera.exposure_seconds > camera.max_exposure:
            camera.log(
                f"⚠ Exposure {camera.exposure_seconds*1000:.0f}ms exceeds "
                f"max {camera.max_exposure*1000:.0f}ms — clamping"
            )
            camera.exposure_seconds = camera.max_exposure

        # Hold SDK lock while sending commands to the camera.
        # Released before the exposure wait loop so disconnect can proceed.
        with sdk_lock:
            if not camera.camera:
                raise Exception("Camera disconnected before exposure")
            camera.camera.set_control_value(
                camera.asi.ASI_EXPOSURE, int(camera.exposure_seconds * 1000000)
            )
            camera.camera.set_control_value(camera.asi.ASI_GAIN, camera.gain)

        # Retry ASI_EXP_FAILED once before tearing down — a single failed
        # status is frequently just a USB bandwidth hiccup and recovers on
        # immediate restart. The expensive full-reconnect path stays for
        # persistent failures.
        max_exp_attempts = 2
        exposure_succeeded = False
        for exp_attempt in range(1, max_exp_attempts + 1):
            with sdk_lock:
                if not camera.camera:
                    raise Exception("Camera disconnected before exposure")
                camera.camera.start_exposure()

            # Wait for exposure to complete (lock released so disconnect can run)
            timeout = camera.exposure_seconds + 5.0
            start_time = time.time()
            camera.exposure_start_time = start_time
            transient_failure = False

            while time.time() - start_time < timeout:
                if not camera.is_capturing:
                    try:
                        camera.camera.stop_exposure()
                    except Exception:
                        pass
                    raise Exception("Capture stopped during exposure")
                if camera.camera is None:
                    raise Exception("Camera disconnected during exposure")
                if getattr(camera, '_recovery_requested', False):
                    camera._recovery_requested = False
                    try:
                        camera.camera.stop_exposure()
                    except Exception:
                        pass
                    raise Exception(
                        "Recovery requested by watchdog mid-exposure"
                    )

                status = camera.camera.get_exposure_status()
                if status == camera.asi.ASI_EXP_SUCCESS:
                    exposure_succeeded = True
                    break
                elif status == camera.asi.ASI_EXP_FAILED:
                    if exp_attempt < max_exp_attempts:
                        camera.log(
                            f"⚠ ASI_EXP_FAILED on attempt {exp_attempt}/{max_exp_attempts} — "
                            "retrying exposure (likely USB bandwidth hiccup)"
                        )
                        try:
                            with sdk_lock:
                                if camera.camera:
                                    camera.camera.stop_exposure()
                        except Exception:
                            pass
                        time.sleep(0.3)
                        transient_failure = True
                        break
                    raise Exception("Exposure failed (camera returned ASI_EXP_FAILED status)")
                elif status == camera.asi.ASI_EXP_IDLE:
                    raise Exception("Exposure error: camera returned to IDLE state unexpectedly")

                elapsed = time.time() - start_time
                camera.exposure_remaining = max(0, camera.exposure_seconds - elapsed)
                time.sleep(0.05)

            if exposure_succeeded:
                break
            if not transient_failure:
                # Fell out of wait loop via timeout — don't retry, let the
                # timeout check below raise.
                break

        if not exposure_succeeded and time.time() - start_time >= timeout:
            camera.exposure_remaining = 0.0
            camera.exposure_start_time = None
            raise Exception(
                f"Exposure timeout: camera did not complete {camera.exposure_seconds}s "
                f"exposure within {timeout}s"
            )

        camera.exposure_remaining = 0.0
        camera.exposure_start_time = None

        with sdk_lock:
            if not camera.camera:
                raise Exception("Camera disconnected before data readout")

            # The readout is the one per-frame SDK call that can wedge a USB
            # bus indefinitely — and it runs while holding sdk_lock, so a hang
            # here would block disconnect()'s close() forever (USB stuck until
            # reboot). The exposure has already completed, so the transfer
            # itself should be fast; bound it generously and raise on a wedge
            # so the loop's recovery path runs instead. See the connection
            # audit, 2026-06-02.
            readout_timeout = max(10.0, camera.exposure_seconds)

            def _read_frame():
                data = camera.camera.get_data_after_exposure()
                info = camera.camera.get_camera_property()
                # Use the SDK's view of the active ROI rather than the sensor's
                # MaxWidth/MaxHeight. If set_roi was ever silently rejected or
                # another process left the SDK with a non-default ROI, these
                # diverge — and trusting MaxWidth then crashes in reshape.
                roi = camera.camera.get_roi_format()
                return data, info, roi

            img_data, camera_info, roi_format = call_with_timeout(
                _read_frame, readout_timeout,
                hint="frame readout — USB bus may be wedged",
            )
            roi_width, roi_height, _bins, roi_image_type = roi_format

        active_bit_depth = (
            16 if roi_image_type == camera.asi.ASI_IMG_RAW16 else 8
        )
        expected_bytes = roi_width * roi_height * (active_bit_depth // 8)
        if len(img_data) != expected_bytes:
            raise Exception(
                f"Frame size mismatch: SDK delivered {len(img_data)} bytes but "
                f"ROI {roi_width}x{roi_height} @ {active_bit_depth}-bit expects "
                f"{expected_bytes}. Camera may have been reset by another process."
            )
        width, height = roi_width, roi_height

        temp_info = _get_temperature(camera)

        img, arrays, stats = build_frame(
            img_data, width, height, active_bit_depth,
            camera.bayer_pattern, camera.wb_config,
        )

        metadata = {
            'CAMERA': camera_info['Name'],
            'EXPOSURE': f"{camera.exposure_seconds}s",
            'GAIN': str(camera.gain),
            'TEMP': temp_info['display'],
            'TEMPERATURE': temp_info['display'],
            'TEMP_C': temp_info['celsius_str'],
            'TEMP_F': temp_info['fahrenheit_str'],
            'RES': f"{width}x{height}",
            'CAPTURE AREA SIZE': f"{width} * {height}",
            'FILENAME': f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
            'SESSION': datetime.now().strftime('%Y-%m-%d'),
            'DATETIME': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'BRIGHTNESS': f"{stats['mean']:.1f}",
            'MEAN': f"{stats['mean']:.1f}",
            'MEDIAN': f"{stats['median']:.1f}",
            'MIN': f"{stats['min']}",
            'MAX': f"{stats['max']}",
            'STD_DEV': f"{stats['std_dev']:.2f}",
            'P25': f"{stats['p25']:.1f}",
            'P75': f"{stats['p75']:.1f}",
            'P95': f"{stats['p95']:.1f}",
            'RAW_RGB_NO_WB': arrays['RAW_RGB_NO_WB'],
            'RAW_RGB_16BIT': arrays['RAW_RGB_16BIT'],
            # Rebuild keys: the SDK bytes (referenced, not copied) plus what
            # build_frame needs to decode them again. They let the reprocess /
            # all-sky cache hold ~25 MB instead of the decoded frame's ~125 MB.
            'RAW_BAYER': img_data,
            'RAW_GEOMETRY': (width, height, active_bit_depth, camera.bayer_pattern),
            'WB_CONFIG': dict(camera.wb_config or {}),
            'CAMERA_BIT_DEPTH': camera_info.get('BitDepth', 8),
            'IMAGE_BIT_DEPTH': active_bit_depth,
            'BAYER_PATTERN': camera.bayer_pattern,
            'PIXEL_SIZE': camera_info.get('PixelSize', 0),
            'ELEC_PER_ADU': camera_info.get('ElecPerADU', 1.0),
        }

        return img, metadata

    except Exception as e:
        camera.log(f"ERROR capturing frame: {e}")
        raise


def capture_loop(camera: "ZWOCamera"):
    """Background capture loop with automatic recovery and scheduled capture support."""
    camera.log("=== Capture Loop Started ===")
    mode = getattr(camera, 'scheduled_capture_mode', 'always')
    if mode == "gated":
        camera.log(
            f"Scheduled capture (gated): {camera.scheduled_start_time} - "
            f"{camera.scheduled_end_time} — paused outside window"
        )
        # Gated mode disconnects the camera during off-peak hours and reconnects
        # at the next window. If the camera comes back unopenable, recovery needs
        # a USB disable/enable, which requires Administrator rights — and that
        # need only surfaces hours later. Warn now, while the operator can act.
        try:
            conn = camera._connection
            if (getattr(conn, '_usb_disable_enable_func', None)
                    and not conn._is_running_as_admin()):
                camera.log(
                    "⚠ Gated capture is enabled but the app is NOT running as "
                    "Administrator. If the camera fails to reopen after an "
                    "off-peak window, automatic USB recovery (disable/enable) "
                    "cannot run. Recommended: run the app as Administrator for "
                    "unattended scheduled capture."
                )
        except Exception:
            pass  # Diagnostic only — never block capture startup
    elif mode == "variable":
        camera.log(
            f"Scheduled capture (variable rates): {camera.scheduled_window_interval}s inside "
            f"{camera.scheduled_start_time}-{camera.scheduled_end_time}, "
            f"{camera.capture_interval}s outside"
        )
    else:
        camera.log("Scheduled capture disabled: will run continuously")

    consecutive_errors = 0
    max_reconnect_attempts = 5
    # Long-interval retry state: after max_reconnect_attempts, rather than
    # permanently exiting (which strands a 24/7 unattended rig), we sleep
    # for an escalating interval and then run the whole recovery cycle
    # again. The flag is only used to gate one-shot Discord alerts so we
    # don't spam on every cycle.
    long_retry_mode = False
    # Backoff schedule: 5m -> 15m -> 1h -> stay at 1h. Reduces Discord/log
    # noise for a permanently dead camera while still trying often enough
    # to self-recover after a transient outage.
    long_retry_schedule = [300, 900, 3600]
    long_retry_cycle = 0
    last_schedule_log = None
    frames_captured = 0
    # The first frame after ANY reconnect (scheduled-window transition OR
    # error-recovery) runs against a freshly (re)opened SDK handle. The ZWO
    # SDK's first control op in that state frequently fails once with "Camera
    # closed" and recovers on a clean reopen. When set, the next capture
    # failure is absorbed quietly (no Discord alert, no consecutive-error
    # count) via one silent reopen, instead of masquerading as a fault and
    # kicking off another full disconnect/reconnect cycle. Leaving the
    # error-recovery path WITHOUT this absorption is what produced three
    # open/close cycles in 35s on 2026-06-03 16:32 and wedged the ZWO DLL
    # (the SDK can't take that churn — it recommends 10-15s between ops).
    # See also the 2026-06-02 16:00 scheduled-reconnect incident.
    warmup_pending = False
    # Heartbeat + state flags observed by the UI watchdog. _last_frame_time
    # is updated after every successful capture. long_retry_mode_public
    # mirrors the local long_retry_mode so the watchdog can skip bogus
    # "wedged" alerts while we're intentionally sleeping between retries.
    camera._last_frame_time = time.time()
    camera.long_retry_mode_public = False

    # Recalibration rate limiting to prevent infinite loops
    # (e.g., someone turning lights on/off repeatedly)
    last_recalibration_time = 0
    recalibration_cooldown_sec = 60
    recalibration_count = 0
    recalibration_window_start = time.time()
    max_recalibrations_per_window = 3
    recalibration_window_sec = 600

    try:
        if camera.auto_exposure and not camera.calibration_complete:
            try:
                camera.run_calibration()
            except Exception as e:
                camera.log(f"Calibration failed: {e}. Continuing with current settings.")
                camera.calibration_complete = True
    except Exception as e:
        camera.log(f"Error during calibration: {e}")

    try:
        while camera.is_capturing:
            try:
                within_window = camera.is_within_scheduled_window()

                if not within_window:
                    current_status = "outside_window"
                    if last_schedule_log != current_status:
                        camera.log(
                            f"⏸ Outside scheduled capture window "
                            f"({camera.scheduled_start_time} - {camera.scheduled_end_time})"
                        )
                        camera.log(
                            "Entering off-peak mode: disconnecting camera to reduce hardware load..."
                        )
                        last_schedule_log = current_status

                        if camera.camera:
                            try:
                                was_capturing = camera.is_capturing
                                camera.is_capturing = False

                                try:
                                    if camera.exposure_start_time is not None:
                                        camera.camera.stop_exposure()
                                        camera.exposure_start_time = None
                                        camera.exposure_remaining = 0.0
                                except Exception:
                                    pass

                                # release_sdk=True: off-peak gaps span hours, and
                                # reusing a stale SDK handle across that idle is
                                # what left the camera unopenable on the next
                                # scheduled window. Drop the SDK so reconnect
                                # re-inits cleanly.
                                camera._connection.disconnect(release_sdk=True)
                                camera.log(
                                    "✓ Camera disconnected for off-peak hours (reducing hardware load)"
                                )

                                camera.is_capturing = was_capturing

                                if camera.status_callback:
                                    camera.status_callback(
                                        f"Idle (off-peak until {camera.scheduled_start_time})"
                                    )
                            except Exception as e:
                                camera.log(f"Error disconnecting camera: {e}")
                                camera.is_capturing = was_capturing

                    # Keep _last_frame_time fresh so the UI watchdog doesn't
                    # mistake intentional off-peak idle for a wedged capture.
                    camera._last_frame_time = time.time()
                    wait_end = time.time() + 30.0
                    while camera.is_capturing and time.time() < wait_end:
                        time.sleep(0.2)
                    continue
                else:
                    if last_schedule_log == "outside_window":
                        camera.log(
                            f"▶ Entered scheduled capture window "
                            f"({camera.scheduled_start_time} - {camera.scheduled_end_time})"
                        )
                        camera.log("Transitioning to active capture mode: reconnecting camera...")
                        last_schedule_log = "inside_window"

                        if camera.status_callback:
                            camera.status_callback("Reconnecting for scheduled window...")

                        if not camera.camera:
                            camera.log("Attempting to reconnect camera (re-detecting cameras)...")
                            if not camera.reconnect_camera_safe():
                                camera.log("✗ ERROR: Failed to reconnect camera for scheduled window")
                                camera.log("Will retry in 5 seconds...")
                                wait_end = time.time() + 5.0
                                while camera.is_capturing and time.time() < wait_end:
                                    time.sleep(0.2)
                                continue
                            camera.log("✓ Camera reconnected successfully for scheduled captures")
                            # Mirror the recovery path's post-reconnect settle:
                            # a cold-re-inited SDK needs the USB bus to stabilise
                            # before the first control op, otherwise the first
                            # frame reliably fails with "Camera closed".
                            wait_end = time.time() + 3.0
                            while camera.is_capturing and time.time() < wait_end:
                                time.sleep(0.2)
                            warmup_pending = True
                            # Suppress watchdog during the first post-reconnect exposure.
                            camera._last_frame_time = time.time()

                if not camera.camera:
                    raise Exception("Camera disconnected")

                img, metadata = camera.capture_single_frame()

                consecutive_errors = 0
                warmup_pending = False
                camera._last_frame_time = time.time()
                if long_retry_mode:
                    long_retry_mode = False
                    camera.long_retry_mode_public = False
                    long_retry_cycle = 0
                    camera.log("✓ Capture recovered from long-retry mode")
                    if hasattr(camera, 'on_error_callback') and camera.on_error_callback:
                        try:
                            camera.on_error_callback("Camera recovered — capture resumed")
                        except Exception:
                            pass

                if camera.auto_exposure:
                    img_array = np.array(img)
                    exposure_result = camera.adjust_exposure_auto(img_array)
                    if exposure_result and exposure_result.get('needs_recalibration', False):
                        current_time = time.time()

                        if current_time - recalibration_window_start > recalibration_window_sec:
                            recalibration_count = 0
                            recalibration_window_start = current_time

                        time_since_last = current_time - last_recalibration_time
                        can_recalibrate = (
                            time_since_last >= recalibration_cooldown_sec
                            and recalibration_count < max_recalibrations_per_window
                        )

                        if can_recalibrate:
                            camera.log("⚠ Drastic scene change detected - running rapid calibration")
                            camera.log(
                                f"  (Recalibration {recalibration_count + 1}/"
                                f"{max_recalibrations_per_window} in current window)"
                            )

                            if camera.on_calibration_callback:
                                camera.on_calibration_callback(True)

                            try:
                                camera.run_calibration()
                                last_recalibration_time = time.time()
                                recalibration_count += 1
                            except Exception as cal_error:
                                camera.log(
                                    f"Recalibration error: {cal_error} - continuing with adjusted exposure"
                                )

                            if camera.on_calibration_callback:
                                camera.on_calibration_callback(False)

                            # Skip publishing this badly-exposed frame;
                            # next iteration will capture with calibrated exposure.
                            continue
                        else:
                            if time_since_last < recalibration_cooldown_sec:
                                wait_time = int(recalibration_cooldown_sec - time_since_last)
                                camera.log(
                                    f"⚠ Scene change detected but recalibration on cooldown "
                                    f"({wait_time}s remaining)"
                                )
                            else:
                                camera.log(
                                    f"⚠ Scene change detected but max recalibrations reached "
                                    f"({max_recalibrations_per_window} per "
                                    f"{recalibration_window_sec//60}min window)"
                                )
                            camera.log("  Using aggressive auto-exposure adjustment instead")

                if camera.on_frame_callback:
                    camera.on_frame_callback(img, metadata)

                frames_captured += 1
                if frames_captured == 1 or frames_captured % 100 == 0:
                    camera.log(f"Captured {frames_captured} frames (latest: {metadata['FILENAME']})")

                try:
                    dropped = camera.camera.get_dropped_frames()
                    if dropped > 0:
                        camera.log(f"⚠ USB performance warning: {dropped} dropped frames detected")
                        camera.log(
                            "  Consider: reducing bandwidth_overload, lowering frame rate, "
                            "or checking USB connection"
                        )
                except Exception:
                    pass

                # Each frame now owns its arrays (~100 MB at 3552x3552 RAW16),
                # so holding these locals across the inter-frame wait would keep
                # a finished frame resident alongside the next one.
                img = None
                metadata = None

                if camera.is_capturing:
                    wait_end = time.time() + camera.effective_capture_interval
                    while camera.is_capturing and time.time() < wait_end:
                        time.sleep(0.2)

            except Exception as e:
                if not camera.is_capturing:
                    break

                # First frame after a scheduled-window reconnect: absorb a
                # single "Camera closed" quietly. The off-peak path releases the
                # SDK, so the window-transition reconnect runs against a cold
                # re-init whose first control op is flaky and heals on a clean
                # reopen. Reuse the recovery reopen flow, but without a Discord
                # alert or a consecutive-error count so the expected cold-open
                # quirk doesn't read as a fault (see 2026-06-02 16:00 incident).
                if warmup_pending:
                    warmup_pending = False
                    camera.log(
                        f"First frame after reconnect failed ({e}) — reopening "
                        "silently (known ZWO cold-open quirk, no fault raised)"
                    )
                    try:
                        if camera.calibration_manager:
                            camera.calibration_manager.abort()
                        if camera.camera:
                            camera._connection.disconnect()
                        wait_end = time.time() + 8.0
                        while camera.is_capturing and time.time() < wait_end:
                            time.sleep(0.2)
                        if camera.reconnect_camera_safe():
                            camera.log("✓ Camera reopened after scheduled-reconnect warm-up")
                            camera._last_frame_time = time.time()
                        else:
                            camera.log(
                                "⚠ Warm-up reopen failed — normal recovery will handle it"
                            )
                    except Exception as warmup_err:
                        camera.log(
                            f"Warm-up reopen error: {warmup_err} — "
                            "normal recovery will handle it"
                        )
                    continue

                consecutive_errors += 1
                error_msg = str(e)
                camera.log(f"✗ ERROR in capture loop: {error_msg}")
                camera.log(f"Consecutive errors: {consecutive_errors}/{max_reconnect_attempts}")
                camera.log(f"Stack trace: {traceback.format_exc()}")

                capture_error(e, context='camera_capture_loop')

                if (
                    consecutive_errors == 1
                    and hasattr(camera, 'on_error_callback')
                    and camera.on_error_callback
                ):
                    camera.on_error_callback(
                        f"Capture error: {error_msg} - attempting recovery..."
                    )

                if consecutive_errors <= max_reconnect_attempts:
                    camera.log(
                        f"Initiating reconnection attempt "
                        f"{consecutive_errors}/{max_reconnect_attempts}..."
                    )
                    try:
                        # Abort any running calibration before disconnecting so it
                        # doesn't keep calling SDK methods on a dying camera handle.
                        if camera.calibration_manager:
                            camera.calibration_manager.abort()

                        if camera.camera:
                            camera.log("Cleaning up existing camera connection...")
                            camera._connection.disconnect()

                        # ZWO SDK docs recommend waiting 10-15s before reopening
                        # a camera after an error. 0.5s almost guaranteed
                        # "Invalid ID" on first reopen, wasting one of five
                        # recovery attempts. 8s interruptible keeps Stop
                        # responsive.
                        pre_reconnect_wait = 8.0
                        camera.log(
                            f"Waiting {pre_reconnect_wait:.0f}s before reconnection attempt "
                            "(USB bus settle)..."
                        )
                        wait_end = time.time() + pre_reconnect_wait
                        while camera.is_capturing and time.time() < wait_end:
                            time.sleep(0.2)

                        if camera.reconnect_camera_safe():
                            camera.log("✓ Camera reconnected successfully")
                            consecutive_errors = 0
                            # Absorb the cold-open quirk on the FIRST frame after
                            # this reopen (same as the scheduled-window path).
                            # Without this, that benign "Camera closed" counted
                            # as a fresh fault and triggered another full
                            # reconnect — the churn that wedged the DLL.
                            warmup_pending = True
                            camera.log("Waiting 3s for USB bus to stabilise...")
                            wait_end = time.time() + 3.0
                            while camera.is_capturing and time.time() < wait_end:
                                time.sleep(0.2)
                            # No explicit probe here: an SDK call that hangs
                            # (e.g. get_camera_property after a wedged USB bus)
                            # would block forever since it cannot be interrupted.
                            # capture_single_frame on the next loop iteration
                            # has bounded timeouts and will raise cleanly.
                            camera._last_frame_time = time.time()
                            continue
                        else:
                            raise Exception("Failed to reconnect camera")
                    except Exception as reconnect_error:
                        camera.log(f"✗ Reconnection attempt failed: {reconnect_error}")
                        camera.log(f"Stack trace: {traceback.format_exc()}")
                        backoff_time = min(2 ** consecutive_errors, 32)
                        camera.log(
                            f"Using exponential backoff: waiting {backoff_time}s "
                            f"before next recovery cycle "
                            f"(attempt {consecutive_errors}/{max_reconnect_attempts} failed)..."
                        )
                        wait_end = time.time() + backoff_time
                        while camera.is_capturing and time.time() < wait_end:
                            time.sleep(0.2)
                else:
                    # Max attempts reached — enter long-interval retry mode
                    # instead of permanently exiting. The rig is unattended;
                    # we'd rather keep trying every few minutes than leave
                    # the user staring at a stale image all night.
                    interval = long_retry_schedule[
                        min(long_retry_cycle, len(long_retry_schedule) - 1)
                    ]
                    if not long_retry_mode:
                        long_retry_mode = True
                        camera.long_retry_mode_public = True
                        camera.log(
                            f"✗ Maximum reconnection attempts ({max_reconnect_attempts}) reached"
                        )
                        camera.log(
                            f"⏳ Entering long-interval retry mode — first retry in {interval}s "
                            "(backoff: 5m → 15m → 1h)"
                        )
                        camera.log("Troubleshooting steps:")
                        camera.log("  1. Check USB cable connection")
                        camera.log("  2. Check camera power supply")
                        camera.log("  3. Try: Physically disconnect USB, wait 5 seconds, reconnect")
                        camera.log("  4. Check Windows Device Manager for USB errors")
                        camera.log(
                            "  5. If persistent: Update ZWO drivers from astronomy-imaging-camera.com"
                        )
                        if hasattr(camera, 'on_error_callback') and camera.on_error_callback:
                            try:
                                camera.on_error_callback(
                                    f"Camera unreachable — retrying every {interval // 60} min"
                                )
                            except Exception:
                                pass
                    else:
                        camera.log(
                            f"⏳ Long-retry cycle {long_retry_cycle + 1} — "
                            f"next retry in {interval}s"
                        )

                    wait_end = time.time() + interval
                    while camera.is_capturing and time.time() < wait_end:
                        time.sleep(0.2)

                    long_retry_cycle += 1
                    consecutive_errors = 0
    finally:
        camera.log("Capture loop exiting - cleaning up...")
        # Note: snapshot mode (start_exposure/get_data_after_exposure),
        # NOT video mode. Camera cleanup handled by disconnect_camera()
        # via stop_capture().

        # If capture is exiting while is_capturing is still True, something
        # fatal (unhandled exception) forced us out — tell the UI so it can
        # tear down state, not sit pretending we're still running.
        if (
            camera.is_capturing
            and hasattr(camera, 'on_error_callback')
            and camera.on_error_callback
        ):
            camera.is_capturing = False
            try:
                camera.on_error_callback(
                    "Capture loop terminated unexpectedly",
                    is_fatal=True,
                )
            except TypeError:
                try:
                    camera.on_error_callback("Capture loop terminated unexpectedly")
                except Exception:
                    pass
            except Exception:
                pass

    camera.log("Capture loop stopped")
