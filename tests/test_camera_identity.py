"""Tests for stable serial-based camera identity (services/camera/camera_identity.py).

These guard the June 2026 guide-camera-hijack fix: identity must key off the
hardware serial, not the volatile index or shared model name.
"""
import threading
import time
import types

from unittest.mock import MagicMock

from services.camera import camera_identity as ci
from services.camera.camera_config import verify_camera_identity


# ---------------------------------------------------------------------------
# normalize / match
# ---------------------------------------------------------------------------

def test_normalize_serial_strips_separators_and_case():
    assert ci.normalize_serial("AB:cd-12 34") == "abcd1234"
    assert ci.normalize_serial(None) == ""


def test_serials_match_requires_both_present():
    assert ci.serials_match("ABCD", "abcd")
    assert not ci.serials_match("", "")          # absence is not identity
    assert not ci.serials_match("abcd", None)
    assert not ci.serials_match("abcd", "ef01")


def test_read_serial_none_without_sdk(monkeypatch):
    monkeypatch.setattr(ci, "_zwolib", lambda: None)
    assert ci.read_serial(types.SimpleNamespace(id=0)) is None


# ---------------------------------------------------------------------------
# verify_camera_identity — the runtime gate before any configure()
# ---------------------------------------------------------------------------

class _Cam:
    def __init__(self, name):
        self._name = name

    def get_camera_property(self):
        return {"Name": self._name}


def test_verify_passes_on_serial_match(monkeypatch):
    monkeypatch.setattr(ci, "read_serial", lambda c: "abcd")
    assert verify_camera_identity(
        _Cam("ZWO ASI676MC"), "ZWO ASI676MC", lambda _: None, camera_serial="abcd"
    )


def test_verify_refuses_on_serial_mismatch_even_if_name_matches(monkeypatch):
    # The hijack guard: same model name, different physical body → refuse.
    monkeypatch.setattr(ci, "read_serial", lambda c: "ffff")
    assert not verify_camera_identity(
        _Cam("ZWO ASI676MC"), "ZWO ASI676MC", lambda _: None, camera_serial="abcd"
    )


def test_verify_falls_back_to_name_when_serial_unreadable(monkeypatch):
    monkeypatch.setattr(ci, "read_serial", lambda c: None)
    assert verify_camera_identity(
        _Cam("ZWO ASI676MC"), "ZWO ASI676MC", lambda _: None, camera_serial="abcd"
    )
    assert not verify_camera_identity(
        _Cam("ZWO ASI462MM"), "ZWO ASI676MC", lambda _: None, camera_serial="abcd"
    )


# ---------------------------------------------------------------------------
# find_index_by_serial — locate the right body when the index has shifted
# ---------------------------------------------------------------------------

class _FakeHandle:
    def __init__(self, idx, serial):
        self.id = idx
        self._serial = serial
        self.closed = False

    def close(self):
        self.closed = True


class _FakeConn:
    def __init__(self, cams, serial_map):
        self._cams = cams
        self._serial_map = serial_map
        self.sdk_lock = threading.Lock()
        self.opened = []
        self.asi = types.SimpleNamespace(Camera=self._open)

    def detect_cameras(self):
        return self._cams

    def _open(self, idx):
        self.opened.append(idx)
        return _FakeHandle(idx, self._serial_map.get(idx))

    def log(self, _m):
        pass


def test_find_index_locates_correct_same_model_body(monkeypatch):
    cams = [{"index": 0, "name": "ZWO ASI676MC"},
            {"index": 1, "name": "ZWO ASI676MC"}]
    conn = _FakeConn(cams, {0: "aaaa", 1: "bbbb"})
    monkeypatch.setattr(ci, "read_serial", lambda h: h._serial)
    assert ci.find_index_by_serial(conn, "bbbb", "ZWO ASI676MC") == 1


def test_find_index_never_opens_a_different_model(monkeypatch):
    # A guide camera of a different model must not even be opened during probe.
    cams = [{"index": 0, "name": "ZWO ASI120MM Mini"},
            {"index": 1, "name": "ZWO ASI676MC"}]
    conn = _FakeConn(cams, {0: "guide", 1: "main"})
    monkeypatch.setattr(ci, "read_serial", lambda h: h._serial)
    assert ci.find_index_by_serial(conn, "main", "ZWO ASI676MC") == 1
    assert 0 not in conn.opened


def test_find_index_returns_none_when_serial_absent(monkeypatch):
    cams = [{"index": 0, "name": "ZWO ASI676MC"}]
    conn = _FakeConn(cams, {0: "aaaa"})
    monkeypatch.setattr(ci, "read_serial", lambda h: h._serial)
    assert ci.find_index_by_serial(conn, "zzzz", "ZWO ASI676MC") is None


class _SlowConn(_FakeConn):
    """Opens of any index in ``slow`` block past the probe timeout. Records
    every handle it hands out so the test can assert it gets closed."""

    def __init__(self, cams, serial_map, slow, sleep=0.5):
        super().__init__(cams, serial_map)
        self._slow = slow
        self._sleep = sleep
        self.handles = {}

    def _open(self, idx):
        self.opened.append(idx)
        if idx in self._slow:
            time.sleep(self._sleep)
        h = _FakeHandle(idx, self._serial_map.get(idx))
        self.handles[idx] = h
        return h


def test_find_index_continues_past_a_timed_out_open(monkeypatch):
    # A slow/wedged body at index 0 must not hide the real serial match at a
    # later index — the probe keeps going instead of aborting on first timeout.
    cams = [{"index": 0, "name": "ZWO ASI676MC"},
            {"index": 1, "name": "ZWO ASI676MC"}]
    conn = _SlowConn(cams, {0: "aaaa", 1: "bbbb"}, slow={0})
    monkeypatch.setattr(ci, "read_serial", lambda h: h._serial)
    assert ci.find_index_by_serial(
        conn, "bbbb", "ZWO ASI676MC", open_timeout_sec=0.1) == 1


def test_find_index_closes_handle_from_abandoned_open(monkeypatch):
    # The open that timed out still completes later in its daemon worker; the
    # handle it creates must be closed or the ASI device hangs until reboot.
    cams = [{"index": 0, "name": "ZWO ASI676MC"},
            {"index": 1, "name": "ZWO ASI676MC"}]
    conn = _SlowConn(cams, {0: "aaaa", 1: "bbbb"}, slow={0})
    monkeypatch.setattr(ci, "read_serial", lambda h: h._serial)
    ci.find_index_by_serial(conn, "bbbb", "ZWO ASI676MC", open_timeout_sec=0.1)
    time.sleep(0.7)  # let the abandoned index-0 open finish and self-close
    assert conn.handles[0].closed is True


def test_find_index_aborts_after_repeated_timeouts(monkeypatch):
    # Many timeouts in a row mean the SDK itself is wedged: stop probing and let
    # the caller fall back to the name-based recovery ladder (return None).
    cams = [{"index": 0, "name": "ZWO ASI676MC"},
            {"index": 1, "name": "ZWO ASI676MC"},
            {"index": 2, "name": "ZWO ASI676MC"}]
    conn = _SlowConn(cams, {0: "x", 1: "y", 2: "bbbb"}, slow={0, 1, 2})
    monkeypatch.setattr(ci, "read_serial", lambda h: h._serial)
    assert ci.find_index_by_serial(
        conn, "bbbb", "ZWO ASI676MC", open_timeout_sec=0.1) is None
    # Stopped at the timeout cap — index 2 was never even probed.
    assert 2 not in conn.opened


# ---------------------------------------------------------------------------
# connect() — the authoritative gate before settings are written
# ---------------------------------------------------------------------------

def _make_conn():
    from services.camera.camera_connection import CameraConnection
    conn = CameraConnection(sdk_path=None, logger=lambda _: None)
    conn.asi = MagicMock()
    return conn


def test_connect_refuses_camera_with_wrong_serial(monkeypatch):
    conn = _make_conn()
    cam = MagicMock()
    cam.get_camera_property.return_value = {
        "Name": "ZWO ASI676MC", "MaxWidth": 100, "MaxHeight": 100, "PixelSize": 2.0,
    }
    conn.asi.Camera.return_value = cam
    monkeypatch.setattr(ci, "read_serial", lambda c: "wrongbody00000000")

    captured = {}
    conn.config_callback = lambda k, v: captured.__setitem__(k, v)

    ok = conn.connect(
        0, settings=None,
        expected_camera_name="ZWO ASI676MC",
        expected_camera_serial="rightbody00000000",
    )
    assert ok is False
    cam.close.assert_called()              # wrong camera released, not configured
    assert conn.camera is None
    assert "zwo_selected_camera_serial" not in captured  # never learned a wrong serial


def test_connect_learns_serial_on_first_clean_connect(monkeypatch):
    conn = _make_conn()
    cam = MagicMock()
    cam.get_camera_property.return_value = {
        "Name": "ZWO ASI676MC", "MaxWidth": 100, "MaxHeight": 100, "PixelSize": 2.0,
    }
    conn.asi.Camera.return_value = cam
    monkeypatch.setattr(ci, "read_serial", lambda c: "learnedbody000000")

    captured = {}
    conn.config_callback = lambda k, v: captured.__setitem__(k, v)

    # No expected serial on file (migration): connect proceeds on the name
    # match and persists the learned serial for next time.
    ok = conn.connect(0, settings=None, expected_camera_name="ZWO ASI676MC")
    assert ok is True
    assert conn.camera_serial == "learnedbody000000"
    assert captured.get("zwo_selected_camera_serial") == "learnedbody000000"


# ---------------------------------------------------------------------------
# resolve_camera_index — hijack-safe starting-index resolution
# ---------------------------------------------------------------------------

class _FakeConfig:
    def __init__(self, store=None):
        self.store = dict(store or {})
        self.saved = False

    def get(self, k, default=None):
        return self.store.get(k, default)

    def set(self, k, v):
        self.store[k] = v

    def save(self):
        self.saved = True


def _patch_enum(monkeypatch, cams):
    from services.camera import camera_index_resolver as r
    monkeypatch.setattr(r, "_list_camera_names", lambda sdk_path: list(cams))
    return r


def test_resolve_refuses_to_guess_on_multi_camera_rig(monkeypatch):
    import pytest
    r = _patch_enum(monkeypatch, [(0, "ZWO ASI120MM Mini"), (1, "ZWO ASI676MC")])
    cfg = _FakeConfig()
    # No saved name and >1 camera: must refuse rather than grab the guide cam.
    with pytest.raises(Exception, match="Refusing to guess"):
        r.resolve_camera_index(cfg, "fake.dll", "", 0)


def test_resolve_autopicks_single_camera(monkeypatch):
    r = _patch_enum(monkeypatch, [(0, "ZWO ASI676MC")])
    cfg = _FakeConfig()
    assert r.resolve_camera_index(cfg, "fake.dll", "", 0) == 0
    assert cfg.get("zwo_selected_camera_name") == "ZWO ASI676MC"
    assert cfg.get("zwo_selected_camera_serial") == ""  # re-learn on connect


def test_resolve_follows_index_drift(monkeypatch):
    # Saved camera was at index 0 but is now at index 2 (guide cam came online).
    r = _patch_enum(monkeypatch, [
        (0, "ZWO ASI120MM Mini"), (1, "ZWO ASI220MM"), (2, "ZWO ASI676MC"),
    ])
    cfg = _FakeConfig()
    assert r.resolve_camera_index(cfg, "fake.dll", "ZWO ASI676MC", 0) == 2
    assert cfg.get("zwo_selected_camera") == 2


def test_resolve_honours_saved_index_for_same_model(monkeypatch):
    # Two identical bodies: the user's index pick is the only identity we have
    # until a serial is learned, so it must be honoured.
    r = _patch_enum(monkeypatch, [(0, "ZWO ASI676MC"), (1, "ZWO ASI676MC")])
    cfg = _FakeConfig()
    assert r.resolve_camera_index(cfg, "fake.dll", "ZWO ASI676MC", 1) == 1


def test_resolve_raises_when_saved_camera_absent(monkeypatch):
    import pytest
    r = _patch_enum(monkeypatch, [(0, "ZWO ASI462MM")])
    cfg = _FakeConfig()
    with pytest.raises(Exception, match="ZWO ASI676MC.*not found"):
        r.resolve_camera_index(cfg, "fake.dll", "ZWO ASI676MC", 0)
