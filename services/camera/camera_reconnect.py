"""
Camera reconnection and USB recovery logic for ZWO ASI cameras.

Module-level functions that operate on a CameraConnection instance.
Used internally by CameraConnection — do not import directly from other modules.
"""
import time
from typing import Optional


def wait_for_stable_detection(conn, camera_name: str,
                               timeout_sec: float = 10.0,
                               poll_interval: float = 2.0) -> Optional[int]:
    """
    Poll detect_cameras() until the target camera appears at the same index
    on two consecutive polls, or timeout.

    Right after a USB disable/enable cycle, the SDK can briefly show the
    camera before the driver is fully bound — connect() then fails with
    "Invalid ID". Waiting for a stable detection avoids that race.

    Args:
        conn: CameraConnection instance
        camera_name: Name substring to search for
        timeout_sec: Max wait time
        poll_interval: Seconds between polls

    Returns:
        Stable camera index, or None if not seen stably within timeout.
    """
    deadline = time.time() + timeout_sec
    last_index: Optional[int] = None

    while time.time() < deadline:
        detected = conn.detect_cameras()
        if detected:
            idx = conn._find_camera_index_by_name(detected, camera_name)
            if idx is not None and idx == last_index:
                conn.log(f"  ✓ Target stable at index {idx}")
                return idx
            last_index = idx
        else:
            last_index = None
        try:
            time.sleep(poll_interval)
        except OSError:
            return None

    conn.log(f"  ⚠ Target not stably detected within {timeout_sec}s")
    return last_index  # Best effort — caller can still try this index


def run_recovery_ladder(conn, camera_to_find: str,
                        force_disable_enable: bool = False):
    """
    Escalating USB/SDK recovery for a camera that is either missing OR
    present-but-unopenable.

    Steps, in order of increasing aggressiveness:
      1. USB soft re-enumeration (Windows API)
      2. SDK reset + re-detect
      3. USB disable/enable (Device-Manager-style reset)

    force_disable_enable handles the critical "detected but Invalid ID" case:
    when open() fails on a camera that *does* enumerate, the driver is holding
    a stale handle that a soft reset / SDK reset cannot clear — only a
    disable/enable does. In that case step 2 will "find" the camera (detection
    works fine) and would normally short-circuit step 3, so the caller forces
    step 3 to run anyway.

    Returns:
        (target_found, target_index, post_recovery)
        post_recovery is True only when a disable/enable cycle succeeded, so the
        caller can use connect()'s longer driver-settle retry schedule.
    """
    target_found = False
    target_index: Optional[int] = None
    post_recovery = False

    # Step 1: Try soft USB re-enumeration (Windows only)
    if conn._usb_reset_available:
        conn.log("Step 1: Attempting USB device soft reset...")
        try:
            if conn._usb_reset_func(camera_name=camera_to_find, logger=conn.log):
                conn.log("✓ USB soft reset completed, waiting for re-enumeration...")
                time.sleep(10)
            else:
                conn.log("⚠ USB soft reset failed or not applicable")
        except Exception as e:
            conn.log(f"⚠ USB soft reset error: {e}")

    # Step 2: SDK reset + re-detect
    conn.log("Step 2: Attempting SDK reset...")
    conn.asi = None
    if conn.initialize_sdk():
        detected = conn.detect_cameras()
        if detected:
            idx = conn._find_camera_index_by_name(detected, camera_to_find)
            if idx is not None:
                target_found = True
                target_index = idx
                conn.log("✓ Target camera detected after SDK reset")

    # Step 3: Aggressive USB disable/enable (Device Manager style).
    # Run when the camera is still missing, OR when the caller forces it
    # because open() failed on a detected camera (stuck handle).
    needs_disable_enable = force_disable_enable or not target_found
    if needs_disable_enable and conn._usb_disable_enable_func:
        if force_disable_enable and target_found:
            conn.log(
                "Step 3: Camera enumerates but failed to open (stale driver handle) "
                "— forcing USB device disable/enable..."
            )
        else:
            conn.log("Step 3: Attempting USB device disable/enable (Device Manager reset)...")
        conn.log("This replicates: Device Manager > Disable > Wait 15s > Enable")
        try:
            if conn._usb_disable_enable_func(
                camera_name=camera_to_find,
                disable_seconds=15,
                logger=conn.log
            ):
                conn.log("✓ USB disable/enable completed, reinitializing SDK...")
                conn.asi = None
                if conn.initialize_sdk():
                    # Detection-settle: SDK may briefly report the camera
                    # before it's stable. Poll until we see the target name
                    # twice in a row at the same index, or give up after ~10s.
                    target_index = wait_for_stable_detection(
                        conn, camera_to_find, timeout_sec=10
                    )
                    target_found = target_index is not None
                    if target_found:
                        conn.log("✓ Camera recovered via disable/enable!")
                        post_recovery = True
            else:
                conn.log("⚠ USB disable/enable failed or not applicable")
        except Exception as e:
            conn.log(f"⚠ USB disable/enable error: {e}")

    return target_found, target_index, post_recovery


def reconnect_safe(conn, target_camera_name: Optional[str] = None,
                   settings=None, allow_fallback: bool = False,
                   target_camera_serial: Optional[str] = None) -> bool:
    """
    Safely reconnect to camera by re-detecting available cameras first.

    Args:
        conn: CameraConnection instance
        target_camera_name: Name of camera to reconnect to (defaults to last connected)
        settings: Camera settings dict to apply after reconnection (ROI, gain, etc.)
                 CRITICAL: Without settings, camera may use default ROI causing
                 resolution mismatch and reshape errors during capture.
        allow_fallback: If False (default), reconnection fails if target camera not found.
                       If True, falls back to first available camera.
        target_camera_serial: Stable hardware serial of the camera to reconnect
                 to (defaults to last connected). When known it is the
                 authoritative identity — resolved first by probing serials, and
                 passed to connect() so the wrong body is rejected before any
                 settings are written.

    Returns:
        True if reconnection successful, False otherwise
    """
    conn.log("=== Safe Camera Reconnection ===")
    camera_to_find = target_camera_name or conn.camera_name
    serial_to_find = target_camera_serial or conn.camera_serial

    if camera_to_find:
        conn.log(f"Target camera: '{camera_to_find}'")
    else:
        conn.log("No target camera name specified - will use first available")

    # Serial-first fast path: the index may have shifted, so locate the body by
    # its stable serial before falling back to name-based detection/recovery.
    if serial_to_find:
        from .camera_identity import find_index_by_serial
        serial_index = find_index_by_serial(conn, serial_to_find, camera_to_find)
        if serial_index is not None:
            conn.camera_index = serial_index
            if conn.connect(serial_index, settings,
                            expected_camera_name=camera_to_find,
                            expected_camera_serial=serial_to_find,
                            _skip_roi_usb_recovery=True):
                return True
            conn.log("⚠ Serial-resolved connect failed — falling back to full recovery ladder")

    # --- Detection Phase ---
    # Detect cameras, then check if our TARGET camera is present.
    # Other cameras being visible (e.g. guide camera) doesn't help us.
    detected = conn.detect_cameras()
    target_found = False
    # post_recovery flips True only if we needed disable/enable and it worked;
    # tells connect() to use the longer retry schedule for driver settle.
    post_recovery = False

    if detected and camera_to_find:
        target_index = conn._find_camera_index_by_name(detected, camera_to_find)
        target_found = target_index is not None
    elif detected:
        target_found = True  # No specific target, any camera will do

    # --- Recovery Phase ---
    # Trigger recovery if target camera is NOT in the detected list,
    # even if other cameras (guide cam, etc.) are visible.
    if not target_found and camera_to_find:
        other_cams = [c['name'] for c in detected] if detected else []
        if other_cams:
            conn.log(f"⚠ Target camera '{camera_to_find}' not found (other cameras visible: {', '.join(other_cams)})")
        else:
            conn.log("✗ No cameras detected at all")
        conn.log("Attempting recovery steps for missing camera...")

        target_found, target_index, post_recovery = run_recovery_ladder(
            conn, camera_to_find, force_disable_enable=False
        )
        if target_found:
            # Refresh the local `detected` view so the post-recovery index
            # lookup below doesn't key off the stale pre-recovery list
            # (which didn't include the target).
            detected = conn.cameras

        # All recovery failed
        if not target_found:
            conn.log("✗ All recovery attempts failed")
            if conn._usb_disable_enable_func and not conn._is_running_as_admin():
                conn.log("⚠ USB disable/enable was skipped because app is not running as Administrator")
                conn.log("  To enable full recovery: right-click app shortcut > Properties > Compatibility > 'Run as administrator'")
            if not allow_fallback:
                conn.log(f"✗ RECONNECTION FAILED: Target camera '{camera_to_find}' not found")
                conn.log("The originally-selected camera is not available.")
                conn.log("⚠ Camera may require physical disconnect/reconnect or")
                conn.log("  Device Manager > Disable device > wait 15s > Enable device")
                return False
            else:
                if detected:
                    conn.log(f"⚠ Falling back to first available camera")
                    target_index = detected[0]['index']
                else:
                    conn.log("✗ No cameras available at all")
                    return False

    elif not detected:
        # No cameras at all and no specific target to recover
        conn.log("✗ No cameras detected")
        return False

    # If we have no target_index yet (no recovery was needed), find it
    if camera_to_find and target_found:
        target_index = conn._find_camera_index_by_name(detected, camera_to_find)
    elif not camera_to_find:
        target_index = detected[0]['index']
        conn.log(f"Using first available camera at index {target_index}")

    conn.camera_index = target_index

    # Connect with settings.
    # post_recovery extends the per-open retry budget when we just came
    # out of a disable/enable cycle — the driver may still be binding.
    # _skip_roi_usb_recovery: this function owns USB escalation (the
    # stuck-handle block below), so suppress connect()'s own escalation to
    # avoid a double disable/enable on a set_roi "Invalid size".
    if conn.connect(target_index, settings,
                    expected_camera_name=camera_to_find,
                    expected_camera_serial=serial_to_find,
                    post_recovery=post_recovery,
                    _skip_roi_usb_recovery=True):
        return True

    # --- Stuck-handle escalation ---
    # We get here when the camera enumerates fine but open() failed (typically
    # "Invalid ID"): a stale driver/SDK handle, often left after an off-peak
    # disconnect. An SDK reset alone does NOT clear this — the driver still
    # holds the device — so re-detecting and retrying just loops forever (see
    # production log 2026-05-31 16:00→21:38, ~5h of "Invalid ID" with no
    # recovery). Escalate through the full ladder and force the USB
    # disable/enable that actually releases the handle.
    if camera_to_find:
        conn.log("⚠ Camera detected but failed to open — escalating to USB recovery...")
        target_found, target_index, post_recovery = run_recovery_ladder(
            conn, camera_to_find, force_disable_enable=True
        )
        if target_found and target_index is not None:
            conn.camera_index = target_index
            if conn.connect(target_index, settings,
                            expected_camera_name=camera_to_find,
                            expected_camera_serial=serial_to_find,
                            post_recovery=True, _skip_roi_usb_recovery=True):
                return True
        if conn._usb_disable_enable_func and not conn._is_running_as_admin():
            conn.log("⚠ USB disable/enable was skipped because app is not running as Administrator")
            conn.log("  To enable full recovery: right-click app shortcut > Properties > Compatibility > 'Run as administrator'")
        conn.log("✗ RECONNECTION FAILED: camera detected but could not be opened after USB recovery")
        return False

    # No named target (fallback / first-available case): a plain SDK reset is
    # the most we can safely do without knowing which camera to power-cycle.
    conn.log("⚠ Connection failed, attempting complete SDK reset...")
    if not conn.reset_sdk_completely():
        return False

    detected = conn.detect_cameras()
    if not detected:
        conn.log("✗ No cameras detected after SDK reset")
        return False

    target_index = detected[0]['index']
    conn.camera_index = target_index
    return conn.connect(target_index, settings, expected_camera_name=camera_to_find,
                        expected_camera_serial=serial_to_find,
                        _skip_roi_usb_recovery=True)
