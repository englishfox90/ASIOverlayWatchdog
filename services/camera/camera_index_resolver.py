"""
Resolve a ZWO camera's current SDK index from its stored identity.

The saved index is only a hint — it shifts whenever any USB camera appears or
drops. We re-enumerate and match on the model name, refusing to guess when the
identity is unknown and the choice is ambiguous. This previously auto-selected
"the first camera" whenever no name was stored, which hijacked a user's guide
camera after a config reset (June 2026).

This resolves a *starting* index only. The hardware serial is the authoritative
key but requires opening the camera, so the final serial-checked decision is
made in the connection layer (CameraConnection.connect serial-verifies and
reconnect_safe probes serials). Same-model ambiguity here is therefore safe:
connect() rejects the wrong body and the serial probe finds the right one.
"""
import os
from typing import List, Tuple

from services.logger import app_logger
from .camera_utils import clean_camera_name, call_with_timeout, SDKTimeoutError


def _list_camera_names(sdk_path: str) -> List[Tuple[int, str]]:
    """Enumerate (index, name) for connected ZWO cameras. Raises on failure."""
    import zwoasi as asi

    if not sdk_path or not os.path.exists(sdk_path):
        raise Exception("SDK path not configured or not found.")
    try:
        asi.init(sdk_path)
    except Exception as e:
        if "already" not in str(e).lower():
            raise Exception(f"SDK init failed: {e}")

    num_cameras = asi.get_num_cameras()
    if num_cameras == 0:
        raise Exception("No ZWO cameras detected. Check USB connections.")

    # Wrap list_cameras() in a timeout — a wedged camera in a bad USB state can
    # otherwise hang the capture-start worker indefinitely.
    try:
        names = call_with_timeout(
            lambda: list(asi.list_cameras()), 8.0,
            hint="list_cameras() — camera may be in a bad USB state, try the Revive button",
        )
    except SDKTimeoutError as e:
        raise Exception(str(e))
    return list(enumerate(names or []))


def resolve_camera_index(config, sdk_path: str, camera_name: str, saved_index: int) -> int:
    """Re-enumerate and resolve the starting SDK index by name.

    Persists index/availability corrections to config and returns the resolved
    index. Raises when the camera can't be chosen safely: target not found, or
    no identity on a multi-camera rig (we refuse to grab an arbitrary camera).
    """
    fresh = _list_camera_names(sdk_path)
    if not fresh:
        raise Exception("No ZWO cameras could be enumerated.")

    available_list = [f"{n} (Index: {i})" for i, n in fresh]
    clean = clean_camera_name(camera_name)

    # No usable identity: only safe to auto-pick when the rig is unambiguous.
    if not clean or clean == 'Unknown':
        if len(fresh) == 1:
            idx, name = fresh[0]
            app_logger.warning(
                f"No saved camera name — single camera present, selecting "
                f"'{name}' at index {idx}"
            )
            config.set('zwo_selected_camera', idx)
            config.set('zwo_selected_camera_name', name)
            config.set('zwo_selected_camera_serial', '')  # re-learn on connect
            config.set('available_cameras', available_list)
            config.save()
            return idx
        available = ", ".join(f"[{i}] {n}" for i, n in fresh)
        raise Exception(
            f"No camera selected and {len(fresh)} cameras present ({available}). "
            "Refusing to guess — select the correct camera on the Capture tab."
        )

    # Honour the saved index when it still holds a camera of the right model.
    # Two same-model bodies (e.g. dual imaging rigs) are indistinguishable by
    # name, so the user disambiguates them by index at selection time — before
    # a serial has been learned, that index IS the only identity we have. Once a
    # serial is on file the connection layer makes the authoritative call and
    # re-resolves if this index turns out to be the wrong body.
    if 0 <= saved_index < len(fresh):
        if clean == clean_camera_name(fresh[saved_index][1]):
            app_logger.info(f"Camera '{clean}' confirmed at saved index {saved_index}")
            config.set('available_cameras', available_list)
            return saved_index

    for idx, name in fresh:
        if clean == clean_camera_name(name):
            if idx != saved_index:
                app_logger.warning(
                    f"Camera index changed: '{clean}' moved from index "
                    f"{saved_index} to {idx}  (other cameras may have come online)"
                )
                config.set('zwo_selected_camera', idx)
                config.save()
            else:
                app_logger.info(f"Camera '{clean}' confirmed at index {idx}")
            config.set('available_cameras', available_list)
            return idx

    available = ", ".join(f"[{i}] {n}" for i, n in fresh)
    raise Exception(
        f"Camera '{clean}' not found. Available cameras: {available}. "
        "Please click 'Detect Cameras' and select the correct camera."
    )
