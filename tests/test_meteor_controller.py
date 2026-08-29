"""Tests for ui/controllers/meteor_controller.py detection orchestration.

These drive _run_detection directly (synchronously) — the threading wrapper
is exercised in live/replay use; what needs regression coverage is the
release sequencing: a candidate held by the PersistenceFilter must be
reported as a meteor when the NEXT frame is empty, and the thumbnail must
come from the frame the streak appeared in, not the empty one.
"""
import os
import sys

import numpy as np
import pytest
from PIL import Image

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from PySide6.QtWidgets import QApplication

from services.meteor.detection_scale import DetectionScale
from services.meteor.noise import DiffNoiseEMA
from services.meteor.persistence import PersistenceFilter
from ui.controllers.meteor_controller import MeteorController


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


W, H = 320, 240

CFG = {
    "enabled": True,
    "min_length": 50,
    "min_brightness": 20,
    "max_nonline_prob": 0.25,
    "max_length_frac": 0.5,
    "noise_sensitivity": "normal",
    "detection_cooldown": 0,
    "save_detections": False,
    "save_annotated": False,
}


def _make_controller(qapp) -> MeteorController:
    ctrl = MeteorController(None)
    ctrl._status_timer.stop()
    ctrl._filter = PersistenceFilter()
    ctrl._noise_ema = DiffNoiseEMA()
    ctrl._detection_scale = DetectionScale(factor=1.0)
    return ctrl


def _streak_transient() -> np.ndarray:
    """Transient map with a 3-px-tall, 100-px-long bright streak."""
    arr = np.zeros((H, W), dtype=np.uint8)
    arr[118:121, 100:200] = 200
    return arr


def _empty_transient() -> np.ndarray:
    return np.zeros((H, W), dtype=np.uint8)


def _full_res_with_streak() -> Image.Image:
    return Image.fromarray(
        np.stack([_streak_transient()] * 3, axis=-1))


def _full_res_empty() -> Image.Image:
    return Image.fromarray(np.zeros((H, W, 3), dtype=np.uint8))


class _FakeConfig:
    def __init__(self, cfg):
        self._cfg = cfg

    def get(self, key, default=None):
        return self._cfg if key == "meteor" else default


class _FakeMainWindow:
    def __init__(self, cfg, ml_results):
        self.config = _FakeConfig(cfg)
        self.last_ml_results = ml_results


class TestRoofGate:
    """Detection must run only when the roof is confidently open — suspended on
    a 'Closed' OR an uncertain 'N/A' reading, but allowed when no roof
    classifier is reporting at all (roof_status absent)."""

    def _driven(self, qapp, ml_results):
        ctrl = MeteorController(None)
        ctrl._status_timer.stop()
        ctrl._main_window = _FakeMainWindow(dict(CFG, enabled=True), ml_results)
        ctrl._sky_circle = (160.0, 120.0, 9999.0)   # skip calibration lookup
        ctrl._filter = PersistenceFilter()           # skip exposure lookup
        gray = Image.fromarray(np.full((H, W), 25, dtype=np.uint8))
        full = Image.fromarray(np.zeros((H, W, 3), dtype=np.uint8))
        ctrl.on_frame_ready(gray, full)
        return ctrl

    def test_suspended_when_roof_closed(self, qapp):
        ctrl = self._driven(qapp, {"roof_status": "Closed"})
        assert ctrl._stack is None, "No frame may be ingested while roof closed"

    def test_suspended_when_roof_uncertain(self, qapp):
        ctrl = self._driven(qapp, {"roof_status": "N/A"})
        assert ctrl._stack is None, "Uncertain roof must suspend detection"

    def test_runs_when_roof_open(self, qapp):
        ctrl = self._driven(qapp, {"roof_status": "Open"})
        assert ctrl._stack is not None and ctrl._stack.count == 1

    def test_runs_when_no_roof_classifier(self, qapp):
        ctrl = self._driven(qapp, {})
        assert ctrl._stack is not None and ctrl._stack.count == 1


class TestThumbnailPersistence:
    """Regression: thumbnails were written then deleted — on_capture_stopped
    wiped the whole session's unconfirmed crops (so 24/7 use lost them every
    dawn) and the 20-item UI cap deleted older ones. The crop is the only
    on-disk record of a detection; it must survive until explicit rejection."""

    def _event_with_file(self, tmp_path, name):
        p = tmp_path / f"{name}.jpg"
        Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8)).save(str(p), "JPEG")
        return {"timestamp": name, "thumbnail_path": str(p),
                "annotated_path": "", "confirmed": False}

    def test_capture_stop_keeps_unconfirmed_thumbnails(self, qapp, tmp_path):
        ctrl = _make_controller(qapp)
        events = [self._event_with_file(tmp_path, f"m{i}") for i in range(25)]
        ctrl._recent_events = list(events)

        ctrl.on_capture_stopped()

        assert ctrl._recent_events == [], "UI list must clear on stop"
        for e in events:
            assert os.path.isfile(e["thumbnail_path"]), (
                "Thumbnail must survive capture stop — it is the only on-disk "
                "record of the detection")

    def test_report_beyond_cap_keeps_files_on_disk(self, qapp, tmp_path):
        ctrl = _make_controller(qapp)
        events = [self._event_with_file(tmp_path, f"c{i}") for i in range(25)]
        # Simulate the 20-cap trim exactly as _report_detections now does.
        for e in events:
            ctrl._recent_events = ([e] + ctrl._recent_events)[:20]
        assert len(ctrl._recent_events) == 20, "UI list is still capped at 20"
        for e in events:
            assert os.path.isfile(e["thumbnail_path"]), (
                "Files scrolled off the UI list must remain on disk")

    def test_explicit_rejection_still_deletes_file(self, qapp, tmp_path):
        ctrl = _make_controller(qapp)
        e = self._event_with_file(tmp_path, "rejected")
        ctrl._evict_event_files(e)   # the path on_detection_rejected takes
        assert not os.path.isfile(e["thumbnail_path"]), (
            "Rejection cleanup must still delete the thumbnail")


class TestReleaseSequencing:
    def test_meteor_released_when_next_frame_empty(self, qapp):
        """Streak in frame T, nothing in T+1 → reported after T+1.

        Regression: the released list from filter.update([]) was discarded,
        so the canonical meteor signature was never reported.
        """
        ctrl = _make_controller(qapp)
        reports = []
        ctrl._report_detections = lambda dets, img, cfg: reports.append((dets, img))

        hot = np.zeros((H, W), dtype=np.uint8)
        frame_t_img = _full_res_with_streak()

        ctrl._run_detection(_streak_transient(), hot, frame_t_img, CFG, 1)
        assert not reports, "Candidate must be held, not reported immediately"

        ctrl._run_detection(_empty_transient(), hot, _full_res_empty(), CFG, 2)
        assert len(reports) == 1, "Held candidate must be released on empty frame"
        dets, _ = reports[0]
        assert len(dets) == 1
        assert dets[0].length >= 50

    def test_released_meteor_uses_held_frame_image(self, qapp):
        """The thumbnail source must be the frame the streak appeared in —
        the streak is absent from the releasing (empty) frame by definition."""
        ctrl = _make_controller(qapp)
        reports = []
        ctrl._report_detections = lambda dets, img, cfg: reports.append((dets, img))

        hot = np.zeros((H, W), dtype=np.uint8)
        frame_t_img = _full_res_with_streak()
        frame_t1_img = _full_res_empty()

        ctrl._run_detection(_streak_transient(), hot, frame_t_img, CFG, 1)
        ctrl._run_detection(_empty_transient(), hot, frame_t1_img, CFG, 2)

        assert len(reports) == 1
        _, img = reports[0]
        assert img is frame_t_img, "Report must use the held frame's image"

    def test_collinear_advancing_streaks_not_reported(self, qapp):
        """Plane signature: collinear streak advancing across frames → no report."""
        ctrl = _make_controller(qapp)
        reports = []
        ctrl._report_detections = lambda dets, img, cfg: reports.append((dets, img))

        hot = np.zeros((H, W), dtype=np.uint8)

        first = np.zeros((H, W), dtype=np.uint8)
        first[118:121, 20:120] = 200
        second = np.zeros((H, W), dtype=np.uint8)
        second[118:121, 140:240] = 200

        ctrl._run_detection(first, hot, Image.fromarray(
            np.stack([first] * 3, axis=-1)), CFG, 1)
        ctrl._run_detection(second, hot, Image.fromarray(
            np.stack([second] * 3, axis=-1)), CFG, 2)
        ctrl._run_detection(_empty_transient(), hot, _full_res_empty(), CFG, 3)

        assert not reports, "Advancing collinear track is a plane — never reported"

    def test_transient_residue_reported_exactly_once(self, qapp):
        """Production behaviour: a streak stays in the max−mean transient map
        until its frame evicts (~stack-depth runs). The repeated re-detections
        must yield exactly ONE report, not one per run."""
        ctrl = _make_controller(qapp)
        ctrl._filter = PersistenceFilter(residue_suppress_frames=8)
        reports = []
        ctrl._report_detections = lambda dets, img, cfg: reports.append((dets, img))

        hot = np.zeros((H, W), dtype=np.uint8)
        img = _full_res_with_streak()
        for idx in range(1, 7):
            ctrl._run_detection(_streak_transient(), hot, img, CFG, idx)

        assert len(reports) == 1, (
            f"Residue must be reported once, got {len(reports)} reports")

    def test_sky_spanning_streak_rejected_by_length_ceiling(self, qapp):
        """Streak longer than max_length_frac × frame width → never held/reported."""
        ctrl = _make_controller(qapp)
        reports = []
        ctrl._report_detections = lambda dets, img, cfg: reports.append((dets, img))

        hot = np.zeros((H, W), dtype=np.uint8)
        spanning = np.zeros((H, W), dtype=np.uint8)
        spanning[118:121, 10:310] = 200  # 300 px on a 320 px frame

        ctrl._run_detection(spanning, hot, Image.fromarray(
            np.stack([spanning] * 3, axis=-1)), CFG, 1)
        ctrl._run_detection(_empty_transient(), hot, _full_res_empty(), CFG, 2)

        assert not reports, "Sky-spanning streak must be rejected as satellite/plane"
