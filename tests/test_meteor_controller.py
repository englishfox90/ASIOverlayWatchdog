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
