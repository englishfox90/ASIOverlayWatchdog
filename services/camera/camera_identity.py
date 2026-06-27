"""
Stable per-device identity for ZWO ASI cameras.

A camera's SDK *index* is just enumeration order: it shifts whenever any USB
camera appears or drops (a guide cam powering up, NINA opening the main cam, a
hub re-enumerating). The *model name* (e.g. "ZWO ASI676MC") is shared by every
body of that model. Neither uniquely identifies a physical camera, which is how
the app could connect to — and reconfigure — the wrong camera when indices moved
(the guide-camera hijack, June 2026).

ASCOM and ASIStudio identify a body by its hardware **serial number**
(ASIGetSerialNumber), with the user-writable flash **ID** (ASIGetID) as an
optional human label. Both require the camera to be *open* (ASIOpenCamera). The
zwoasi 0.2.0 wrapper binds get_id() but not the serial, so we bind
ASIGetSerialNumber ourselves against the same loaded DLL — exactly the call the
ASCOM driver makes.

This module is intentionally low-level: it only reads identity off an already
open handle. The probe-and-resolve loop (open each candidate, read serial,
close non-matches) lives in camera_reconnect.py where the SDK lifecycle and
sdk_lock already live.
"""
import ctypes
import threading
from typing import Optional


class _ASI_SN(ctypes.Structure):
    # ASI_SN in the SDK is `unsigned char id[8]` — same shape as ASI_ID.
    _fields_ = [("id", ctypes.c_ubyte * 8)]


_NULL_SERIAL = "0000000000000000"

# How many probe opens may time out before we conclude the SDK itself is wedged
# and abort the serial search. A single slow body must NOT stop us finding a
# healthy matching camera at a later index; repeated timeouts mean the SDK is
# unstable, so we stop hammering it and let the caller fall back to recovery.
_MAX_PROBE_TIMEOUTS = 2


def _zwolib():
    """Return the loaded ASICamera2 DLL handle, or None if the SDK isn't initialised.

    zwoasi.init() sets the module global ``zwolib``; before that it is None and
    no SDK call (including serial reads) is possible.
    """
    try:
        import zwoasi
        return getattr(zwoasi, "zwolib", None)
    except Exception:
        return None


_serial_unsupported_warned = False


def _warn_serial_unsupported():
    """Log once that the loaded ASI SDK can't read hardware serials."""
    global _serial_unsupported_warned
    if _serial_unsupported_warned:
        return
    _serial_unsupported_warned = True
    try:
        from services.logger import app_logger
        app_logger.warning(
            "Loaded ASICamera2 SDK has no ASIGetSerialNumber — camera identity "
            "falls back to model-name matching only; same-model bodies cannot be "
            "told apart. Update the bundled SDK to restore serial-based protection."
        )
    except Exception:
        pass


def normalize_serial(serial: Optional[str]) -> str:
    """Canonical form for comparison/storage: lowercase, stripped, no separators."""
    if not serial:
        return ""
    return serial.strip().lower().replace(":", "").replace("-", "").replace(" ", "")


def serials_match(a: Optional[str], b: Optional[str]) -> bool:
    """True only when both serials are present and equal after normalization.

    Two missing serials never "match" — absence is not identity. Callers must
    fall back to an exact name check (and refuse to guess) when no serial is on
    file for either side.
    """
    na, nb = normalize_serial(a), normalize_serial(b)
    return bool(na) and na == nb


def persist_camera_serial(config, serial: Optional[str]) -> bool:
    """Write a freshly-learned hardware serial to config when it's new.

    ZWOCamera learns the serial on its first clean connect but only in memory.
    Without persisting it the serial would be re-learned every session and never
    available to reject the wrong camera after the index shifts — the exact
    cross-restart hijack this guards against. Returns True when a new serial was
    written so the caller can log it in its own voice (GUI vs headless).
    """
    if serial and serial != config.get('zwo_selected_camera_serial', ''):
        config.set('zwo_selected_camera_serial', serial)
        config.save()
        return True
    return False


def read_serial(camera) -> Optional[str]:
    """Read the hardware serial from an *open* zwoasi Camera handle.

    Returns a 16-char lowercase hex string, or None if unavailable (older body
    or DLL without ASIGetSerialNumber, the SDK not initialised, or the call
    failed). The serial is read-only and stable for the life of the device.
    A returned value of all-zeros is treated as "no serial" (None).
    """
    if camera is None:
        return None
    lib = _zwolib()
    if lib is None:
        return None
    if not hasattr(lib, "ASIGetSerialNumber"):
        # Warn once: without this symbol the whole serial-identity feature
        # silently degrades to the old name-only matching (the same-model
        # hijack it guards against can recur), so make the gap observable
        # rather than appear protected. lib is None is transient (SDK not yet
        # initialised) and deliberately not warned.
        _warn_serial_unsupported()
        return None
    try:
        sn = _ASI_SN()
        fn = lib.ASIGetSerialNumber
        # Set argtypes/restype on our own reference — zwoasi 0.2.0 never binds
        # this symbol, so its argtypes are unset and a bare call would marshal
        # the pointer wrong on 64-bit.
        fn.argtypes = [ctypes.c_int, ctypes.POINTER(_ASI_SN)]
        fn.restype = ctypes.c_int
        rc = fn(int(camera.id), ctypes.byref(sn))
        if rc != 0:
            return None
        hexs = "".join(f"{b:02x}" for b in sn.id)
        return None if hexs == _NULL_SERIAL else hexs
    except Exception:
        return None


def _probe_serial(conn, idx, name, open_timeout_sec):
    """Open camera ``idx`` read-only under sdk_lock, read its serial, close it.

    Returns ``(serial_or_None, outcome)`` where outcome is one of:
      "ok"      opened and closed cleanly (serial may be None if unreadable)
      "busy"    sdk_lock held by a live worker — caller should stop probing
      "timeout" open exceeded the bound; the abandoned worker self-closes
      "error"   not openable (e.g. held by PHD2/NINA) — skip this candidate

    call_with_timeout abandons its worker on timeout, so the open may finish
    *after* this returns. probe_lock + the abandoned cell hand handle-cleanup
    to whichever side runs last, so the handle is never leaked — an open ASI
    device hangs until reboot.
    """
    from .camera_utils import call_with_timeout, SDKTimeoutError

    if not conn.sdk_lock.acquire(timeout=2.0):
        conn.log("⚠ Serial probe skipped — SDK busy; falling back to name resolution")
        return None, "busy"

    handle = [None]
    abandoned = [False]
    probe_lock = threading.Lock()

    def _open(_idx=idx, _handle=handle, _abandoned=abandoned, _lock=probe_lock):
        h = conn.asi.Camera(_idx)
        with _lock:
            if not _abandoned[0]:
                _handle[0] = h
                return h
        # Probe abandoned on timeout (sdk_lock released); this late open owns
        # the handle. Re-acquire sdk_lock briefly so the close can't race a
        # concurrent probe — best-effort, and outside `with _lock` to keep the
        # main path's lock order (sdk_lock then probe_lock).
        got = conn.sdk_lock.acquire(timeout=2.0)
        try:
            h.close()
        except Exception:
            pass
        finally:
            if got:
                conn.sdk_lock.release()
        return None

    try:
        sn = read_serial(call_with_timeout(_open, open_timeout_sec, hint="serial probe open"))
        return sn, "ok"
    except SDKTimeoutError as e:
        conn.log(f"  Serial probe: index {idx} ('{name}') open timed out ({e})")
        return None, "timeout"
    except Exception as e:
        conn.log(f"  Serial probe: index {idx} ('{name}') not openable ({e}) — skipping")
        return None, "error"
    finally:
        with probe_lock:
            abandoned[0] = True
            if handle[0] is not None:
                try:
                    handle[0].close()
                except Exception:
                    pass
        conn.sdk_lock.release()


def find_index_by_serial(conn, expected_serial: Optional[str],
                         expected_name: Optional[str] = None,
                         open_timeout_sec: float = 15.0) -> Optional[int]:
    """Probe enumerated cameras and return the index whose serial matches.

    Opens each candidate read-only, reads its serial, and closes it again,
    returning the SDK index of the exact serial match — or None if no connected
    camera carries that serial (so the caller refuses rather than guessing).

    Candidates are limited to bodies whose model name equals ``expected_name``
    (when given) to minimise opens. A camera already held by another app
    (PHD2/NINA) simply fails to open and is skipped, so probing never disturbs
    an in-use guide camera. Operates on a CameraConnection: uses its SDK handle,
    sdk_lock, and bounded-open helper.
    """
    target = normalize_serial(expected_serial)
    if not target:
        return None

    detected = conn.detect_cameras()
    if not detected:
        return None

    want_name = (expected_name or '').strip()
    timeouts = 0
    for cam in detected:
        idx, name = cam['index'], cam['name']
        if want_name and (name or '').strip() != want_name:
            continue
        sn, outcome = _probe_serial(conn, idx, name, open_timeout_sec)
        if outcome == "busy":
            return None
        if target == normalize_serial(sn):
            conn.log(f"✓ Serial {expected_serial} matches camera at index {idx} ('{name}')")
            return idx
        if outcome == "timeout":
            # Don't let one slow body hide a healthy match at a later index —
            # keep probing. Abort only once repeated timeouts mean the SDK
            # itself is wedged (caller falls back to the name recovery ladder).
            timeouts += 1
            if timeouts >= _MAX_PROBE_TIMEOUTS:
                conn.log(f"⚠ Aborting serial probe after {timeouts} timed-out "
                         "opens — SDK may be wedged")
                return None

    conn.log(f"✗ No connected camera matches serial {expected_serial}")
    return None
