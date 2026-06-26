"""
Per-camera settings profiles for ZWO cameras, keyed by hardware serial.

Camera settings (gain, exposure, target brightness, WB calibration, …) belong
to a physical body, not a model: two ZWO ASI676MC bodies need different gains.
The model name is shared and the SDK index is volatile, so profiles key off the
hardware serial when it is known (learned on the first clean connect), falling
back to the model name for configs/cameras that predate the serial.

A legacy name-keyed profile is copied to the serial key on first use so the body
keeps its tuned settings; the name profile is left as a template for any
same-model body that hasn't learned its own serial yet.

Functions operate on a Config instance (config.data / config.save). Called
through Config's thin delegators — do not import directly elsewhere.
"""
import re

from .config import DEFAULT_CAMERA_PROFILE

# Profile keys that are artefacts of the pre-serial name bug — no real ZWO body
# is named "Camera 0" or carries an "(Index: N)" suffix.
_BOGUS_PROFILE_RE = re.compile(r'^Camera \d+$')


def _is_bogus_key(key: str) -> bool:
    return bool(_BOGUS_PROFILE_RE.match(key)) or '(Index:' in key


def prune_bogus_profiles(data: dict) -> dict:
    """Remove profiles whose key is a known name-bug artefact. Mutates data."""
    profiles = data.get('camera_profiles')
    if not isinstance(profiles, dict):
        return data
    for key in [k for k in profiles if _is_bogus_key(k)]:
        del profiles[key]
    return data


def _resolve_key(profiles, name, serial):
    """Return (key, created) for this camera, preferring the serial.

    Lazily copies a legacy name-keyed profile under the serial key so the body
    keeps its settings; the name profile stays as a same-model template.
    """
    s = (serial or '').strip()
    n = (name or '').strip()
    if s:
        if s in profiles:
            return s, False
        if n and n in profiles:
            profiles[s] = dict(profiles[n])
            profiles[s]['name'] = n
            return s, True
        return s, True
    if n:
        return n, n not in profiles
    return None, False


def get_camera_profile(config, camera_name, serial=None):
    """Return the settings profile for a camera, keyed by serial when known.

    Seeds a new profile from DEFAULT_CAMERA_PROFILE if none exists. Returns the
    live dict (callers may mutate then save_camera_profile). None if neither a
    name nor a serial is given.
    """
    if not camera_name and not serial:
        return None

    profiles = config.data.setdefault('camera_profiles', {})
    key, created = _resolve_key(profiles, camera_name, serial)
    if not key:
        return None

    if key not in profiles:
        profile = dict(DEFAULT_CAMERA_PROFILE)
        if camera_name:
            profile['name'] = camera_name
        profiles[key] = profile
        created = True

    if created:
        config.save()
        from .logger import app_logger
        label = f"serial {key} ({camera_name})" if (serial or '').strip() else key
        app_logger.info(f"Created camera profile: {label}")
    return profiles[key]


def save_camera_profile(config, camera_name, profile_data, serial=None):
    """Persist a full profile dict for a camera under its serial (or name) key."""
    if not camera_name and not serial:
        return
    profiles = config.data.setdefault('camera_profiles', {})
    key, _ = _resolve_key(profiles, camera_name, serial)
    if not key:
        return
    if camera_name and 'name' not in profile_data:
        profile_data = {**profile_data, 'name': camera_name}
    profiles[key] = profile_data
    config.save()


def update_camera_profile(config, camera_name, serial=None, **kwargs):
    """Update individual keys in a camera's profile (e.g. gain=150)."""
    profile = get_camera_profile(config, camera_name, serial)
    if profile is not None:
        profile.update(kwargs)
        save_camera_profile(config, camera_name, profile, serial)


def list_camera_profiles(config):
    """All profile keys (serials and/or legacy names)."""
    return list(config.data.get('camera_profiles', {}).keys())


def delete_camera_profile(config, camera_name, serial=None):
    """Delete a camera profile by serial (preferred) or name key."""
    profiles = config.data.get('camera_profiles', {})
    key = (serial or '').strip() or camera_name
    if key in profiles:
        del profiles[key]
        config.save()
        from .logger import app_logger
        app_logger.info(f"Deleted camera profile: {key}")
