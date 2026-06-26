"""
Camera configuration helpers for ZWO ASI cameras.

Pure helper functions used by CameraConnection.configure() — do not import directly
from other modules; call through the CameraConnection interface.
"""
import time
from typing import Any, Dict, Optional, Tuple


def _set_roi_with_retry(camera, width, height, image_type, log, attempts=5, delay=1.0):
    """Call camera.set_roi() and retry on ASI_ERROR_INVALID_SIZE.

    The camera may not be fully settled immediately after open().  Invalid-size
    errors on a known-good resolution (e.g. full-frame RAW8) are transient; a
    brief sleep and retry usually succeeds on the next attempt.
    """
    for i in range(attempts):
        try:
            camera.set_roi(start_x=0, start_y=0, width=width, height=height,
                           bins=1, image_type=image_type)
            camera.set_image_type(image_type)
            return
        except Exception as e:
            if i == attempts - 1 or "invalid size" not in str(e).lower():
                raise
            log(f"  set_roi attempt {i + 1}/{attempts} returned Invalid size — retrying in {delay}s")
            time.sleep(delay)


def wait_for_controls_ready(camera, log, timeout: float = 8.0, poll_interval: float = 0.5) -> Dict:
    """Poll get_controls() until the control count stops growing, then return it.

    A freshly-opened ASI camera enumerates its controls incrementally: the
    ASI676MC reports only ~10 of its ~17 controls in the first ~1s after
    open(), and set_roi() returns ASI_ERROR_INVALID_SIZE for the whole
    interval the firmware is still coming up.  A fixed sleep guesses at how
    long that takes; polling until two consecutive reads return the same
    count adapts to a slow cold boot without over-waiting on a warm reconnect.

    Returns the final controls dict (so the caller need not re-fetch).
    """
    deadline = time.time() + timeout
    prev_count = None
    while True:
        controls = camera.get_controls()
        count = len(controls)
        if count == prev_count:
            break  # unchanged across two consecutive reads — enumeration settled
        if prev_count is not None:
            log(f"  Controls still enumerating: {prev_count} → {count}")
        prev_count = count
        if time.time() >= deadline:
            log(f"  ⚠ Control count still changing at timeout ({count}) — proceeding anyway")
            break
        time.sleep(poll_interval)
    log(f"  Available controls: {len(controls)} (enumeration settled)")
    return controls


def validate_control(controls, control_type, value, name, log) -> Tuple[Any, Optional[Dict]]:
    """Validate and clamp a control value to the camera's supported range."""
    ctrl = next((c for c in controls.values() if c['ControlType'] == control_type), None)
    if ctrl:
        validated = max(ctrl['MinValue'], min(ctrl['MaxValue'], value))
        if validated != value:
            log(f"  ⚠ {name} {value} out of range [{ctrl['MinValue']}-{ctrl['MaxValue']}], using {validated}")
        return validated, ctrl
    return value, None


def verify_camera_identity(camera, camera_name: Optional[str], log,
                           camera_serial: Optional[str] = None) -> bool:
    """
    Verify the open camera handle still points to the expected physical camera.
    Returns True if identity matches, False if mismatch or no camera.

    When a hardware serial is on file it is the authoritative check — the model
    name is shared by every body of the same model, so a name-only match can
    still let one camera's settings be written to another (the guide-camera
    hijack, June 2026). The serial uniquely identifies the physical device.
    Falls back to an exact name match (after strip) for bodies/configs without
    a serial.
    """
    if not camera:
        return False
    from .camera_identity import read_serial, serials_match

    if camera_serial:
        actual_serial = read_serial(camera)
        if serials_match(camera_serial, actual_serial):
            return True
        # A None actual_serial means the SDK couldn't read it this call (not a
        # confirmed different camera); fall through to the name check rather
        # than hard-failing a camera that genuinely matches by name.
        if actual_serial is not None:
            log(
                f"✗ Camera identity MISMATCH by serial: expected "
                f"{camera_serial}, SDK returned {actual_serial}. Refusing operation."
            )
            return False

    if not camera_name:
        # No name to fall back on and serial (if any) was unreadable — cannot
        # confirm identity, so refuse (matches the original conservative gate).
        return False
    try:
        actual_name = (camera.get_camera_property().get('Name') or '').strip()
        expected = camera_name.strip()
        if expected != actual_name:
            log(
                f"✗ Camera identity MISMATCH: expected '{expected}', "
                f"SDK returned '{actual_name}'. Refusing operation."
            )
            return False
        return True
    except Exception as e:
        log(f"✗ Camera identity check failed: {e}")
        return False


def configure_white_balance(camera, asi, settings: Dict[str, Any], log) -> None:
    """Configure white balance based on mode."""
    wb_mode = settings.get('wb_mode', 'asi_auto')

    if wb_mode == 'asi_auto':
        try:
            camera.set_control_value(asi.ASI_AUTO_MAX_BRIGHTNESS, 1)
            log("  White balance: ASI Auto")
        except Exception:
            pass
    else:
        try:
            camera.set_control_value(asi.ASI_AUTO_MAX_BRIGHTNESS, 0)
        except Exception:
            pass

        if wb_mode == 'manual':
            wb_r, wb_b = settings.get('wb_r', 75), settings.get('wb_b', 99)
            camera.set_control_value(asi.ASI_WB_R, wb_r)
            camera.set_control_value(asi.ASI_WB_B, wb_b)
            log(f"  White balance: Manual (R={wb_r}, B={wb_b})")
        elif wb_mode == 'gray_world':
            camera.set_control_value(asi.ASI_WB_R, 50)
            camera.set_control_value(asi.ASI_WB_B, 50)
            log("  White balance: Gray World (software)")


def configure_camera(camera, asi, settings: Dict[str, Any], supports_raw16: bool, log) -> Tuple[Any, int]:
    """
    Apply settings to a connected camera.

    Returns (image_type, current_bit_depth) for the caller to store on the
    CameraConnection instance.  Raises on SDK errors — callers should wrap in try/except.
    """
    camera_info = camera.get_camera_property()
    controls = camera.get_controls()

    if 'gain' in settings:
        gain, ctrl = validate_control(controls, asi.ASI_GAIN, settings['gain'], "Gain", log)
        camera.set_control_value(asi.ASI_GAIN, gain)
        rng = f" (range: {ctrl['MinValue']}-{ctrl['MaxValue']})" if ctrl else ""
        log(f"  Gain: {gain}{rng}")

    if 'exposure_sec' in settings:
        exposure_us = int(settings['exposure_sec'] * 1000000)
        exposure_us, ctrl = validate_control(controls, asi.ASI_EXPOSURE, exposure_us, "Exposure", log)
        camera.set_control_value(asi.ASI_EXPOSURE, exposure_us)
        log(f"  Exposure: {exposure_us/1000000}s ({exposure_us/1000}ms)")

    configure_white_balance(camera, asi, settings, log)

    camera.set_control_value(asi.ASI_BANDWIDTHOVERLOAD, 40)
    if 'offset' in settings:
        camera.set_control_value(asi.ASI_BRIGHTNESS, settings['offset'])

    flip = settings.get('flip', 0)
    if flip in (1, 3):
        camera.set_control_value(asi.ASI_FLIP, 1)
    if flip in (2, 3):
        camera.set_control_value(asi.ASI_FLIP, 2)

    use_raw16 = settings.get('use_raw16', False) and supports_raw16
    width = camera_info['MaxWidth']
    height = camera_info['MaxHeight']

    # Set ROI to full frame — required on every connect because the SDK can
    # retain a stale ROI from a prior session, causing reshape failures.
    # RAW16 at full res can fail with ASI_ERROR_INVALID_SIZE under USB-bus
    # contention or post-recovery SDK state; fall back to RAW8 so capture
    # continues rather than spiralling into a reshape crash loop.
    image_type = asi.ASI_IMG_RAW16 if use_raw16 else asi.ASI_IMG_RAW8
    current_bit_depth = 16 if use_raw16 else 8
    try:
        if use_raw16:
            # Single attempt for RAW16 — fall back to RAW8 immediately on any failure.
            camera.set_roi(start_x=0, start_y=0, width=width, height=height,
                           bins=1, image_type=image_type)
            camera.set_image_type(image_type)
        else:
            _set_roi_with_retry(camera, width, height, image_type, log)
    except Exception as e:
        if not use_raw16:
            raise
        log(
            f"  ⚠ set_roi failed at RAW16 ({width}x{height}): {e} — "
            "falling back to RAW8 so capture can proceed"
        )
        image_type = asi.ASI_IMG_RAW8
        current_bit_depth = 8
        _set_roi_with_retry(camera, width, height, image_type, log)

    # Read back the ROI and verify the SDK accepted what we asked for.
    # Some ZWO drivers silently ignore invalid combinations (e.g. RAW16 at
    # a specific ROI) and keep the previous setting.  If we trust the
    # request and the reality differs, every debayer call reshapes into
    # the wrong dimensions.
    actual_w, actual_h, _actual_bins, actual_image_type = camera.get_roi_format()
    if actual_w != width or actual_h != height or actual_image_type != image_type:
        log(
            f"  ⚠ set_roi requested {width}x{height} img_type={image_type} "
            f"but SDK reports {actual_w}x{actual_h} img_type={actual_image_type} "
            "— using actual ROI for subsequent captures"
        )
        image_type = actual_image_type
        current_bit_depth = 16 if image_type == asi.ASI_IMG_RAW16 else 8

    mode_str = "RAW16" if current_bit_depth == 16 else "RAW8"
    log(f"  ROI: Full frame {actual_w}x{actual_h} ({mode_str})")
    log("Camera configuration applied")

    return image_type, current_bit_depth
