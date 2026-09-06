"""Tests for services.allsky.incumbent_evidence — what the live buffer says
about the model on disk.

Fixture shape follows the 2026-09-05 rig log: a correct incumbent that a
trusted pole confirms, whose seeded refinements nevertheless keep failing
the bright-anchor gate.
"""
import os
import sys
from dataclasses import replace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.allsky.fisheye import FisheyeModel
from services.allsky.incumbent_evidence import (
    ANCHOR_MIN_HITS,
    corroborate_incumbent,
    incumbent_anchor_health,
)
from services.allsky.model_admission import (
    PROVENANCE_GUIDED, PROVENANCE_POLE, projected_pole)
from services.allsky.pole_finder import PoleEstimate

LAT = 37.0
W, H = 1920, 1080


def _model(**over):
    m = FisheyeModel(cx=960.0, cy=540.0, a1=600.0, rms_residual=8.0,
                     n_matches=700, n_images=30, span_minutes=60.0,
                     image_width=W, image_height=H)
    for k, v in over.items():
        setattr(m, k, v)
    return m


def _pole_at(xy, east_left=True):
    return PoleEstimate(x=float(xy[0]), y=float(xy[1]), east_left=east_left,
                        sign=-1, n_frames=12, span_minutes=47.0, drift_px=2.4,
                        flux=3600.0, sign_votes=(300, 1000))


# Eight bright anchors above the 40° floor plus two below it.
ANCHORS = [
    ({'name': f'A{i}', 'vmag': 0.1 * i}, alt, az)
    for i, (alt, az) in enumerate([
        (80.0, 10.0), (75.0, 100.0), (70.0, 200.0), (65.0, 300.0),
        (60.0, 45.0), (55.0, 135.0), (50.0, 225.0), (45.0, 315.0),
        (30.0, 90.0), (20.0, 270.0),
    ])
]


def _frame(model, shift=(0.0, 0.0), scale=1.0, anchors=ANCHORS):
    """A buffer frame whose detections sit where `model` projects the
    anchors (optionally displaced), in a frame `scale` times the model's."""
    det = []
    for _s, alt, az in anchors:
        xy = model.altaz_to_pixel(alt, az)
        det.append(((xy[0] + shift[0]) * scale, (xy[1] + shift[1]) * scale, 500.0))
    return {
        'detected': det, 'above_horizon': list(anchors),
        'sky_r': 500.0 * scale,
        'image_width': int(W * scale), 'image_height': int(H * scale),
    }


class TestCorroborate:
    def test_trusted_pole_that_agrees_stamps_pole(self):
        m = _model()
        stamped, why = corroborate_incumbent(m, LAT, _pole_at(projected_pole(m, LAT)), 500.0)
        assert stamped and m.provenance == PROVENANCE_POLE
        assert 'corroborated' in why

    def test_pole_that_disagrees_does_not_stamp_or_demote(self):
        m = _model()
        x, y = projected_pole(m, LAT)
        stamped, why = corroborate_incumbent(m, LAT, _pole_at((x + 400, y)), 500.0)
        assert not stamped and m.provenance == ''
        assert 'wrong-basin' in why

    def test_no_pole_is_nothing_to_do(self):
        m = _model()
        assert corroborate_incumbent(m, LAT, None, 500.0) == (False, "no trusted pole this run")
        assert m.provenance == ''

    def test_guided_incumbent_is_left_alone(self):
        m = _model(provenance=PROVENANCE_GUIDED)
        stamped, _ = corroborate_incumbent(m, LAT, _pole_at(projected_pole(m, LAT)), 500.0)
        assert not stamped and m.provenance == PROVENANCE_GUIDED

    def test_already_corroborated_is_idempotent(self):
        m = _model(provenance=PROVENANCE_POLE)
        stamped, why = corroborate_incumbent(m, LAT, _pole_at(projected_pole(m, LAT)), 500.0)
        assert not stamped and 'already' in why

    def test_missing_or_invalid_incumbent(self):
        assert corroborate_incumbent(None, LAT, _pole_at((1, 1)), 500.0)[0] is False
        assert corroborate_incumbent(_model(n_matches=0), LAT, _pole_at((1, 1)), 500.0)[0] is False

    def test_pole_measured_at_another_resolution_is_rescaled(self):
        """Buffer fed post-resize (half size) while the model is native."""
        m = _model()
        x, y = projected_pole(m, LAT)
        pole = _pole_at((x / 2, y / 2))
        stamped, _ = corroborate_incumbent(m, LAT, pole, 250.0,
                                           pole_image_width=W // 2,
                                           pole_image_height=H // 2)
        assert stamped

    def test_mirror_disagreement_blocks_corroboration(self):
        m = _model(east_left=True)
        stamped, why = corroborate_incumbent(
            m, LAT, _pole_at(projected_pole(m, LAT), east_left=False), 500.0)
        assert not stamped and 'mirrored' in why


class TestAnchorHealth:
    def test_incumbent_hitting_its_anchors_is_healthy(self):
        m = _model()
        assert incumbent_anchor_health(m, [_frame(m) for _ in range(3)]) is True

    def test_incumbent_missing_its_anchors_is_unhealthy(self):
        m = _model()
        frames = [_frame(m, shift=(200.0, 150.0)) for _ in range(3)]
        assert incumbent_anchor_health(m, frames) is False

    def test_majority_rule_two_of_three(self):
        m = _model()
        good, bad = _frame(m), _frame(m, shift=(200.0, 150.0))
        assert incumbent_anchor_health(m, [bad, good, good]) is True
        assert incumbent_anchor_health(m, [good, bad, bad]) is False

    def test_only_the_recent_frames_count(self):
        m = _model()
        old_bad = [_frame(m, shift=(300.0, 0.0)) for _ in range(10)]
        assert incumbent_anchor_health(m, old_bad + [_frame(m)] * 3) is True

    def test_too_few_anchors_is_unknown(self):
        m = _model()
        few = ANCHORS[:ANCHOR_MIN_HITS - 1]
        frames = [_frame(m, anchors=few) for _ in range(3)]
        assert incumbent_anchor_health(m, frames) is None

    def test_no_detections_is_unknown(self):
        m = _model()
        f = _frame(m)
        f['detected'] = []
        assert incumbent_anchor_health(m, [f, f, f]) is None

    def test_one_testable_frame_out_of_three_is_unknown(self):
        m = _model()
        blank = _frame(m)
        blank['detected'] = []
        assert incumbent_anchor_health(m, [blank, blank, _frame(m)]) is None

    def test_no_model_or_frames(self):
        assert incumbent_anchor_health(None, [_frame(_model())]) is None
        assert incumbent_anchor_health(_model(), []) is None

    def test_model_is_rescaled_into_the_frame(self):
        """Buffer at half resolution, model at native: still healthy."""
        m = _model()
        assert incumbent_anchor_health(m, [_frame(m, scale=0.5)] * 3) is True

    def test_different_basin_model_is_unhealthy_on_the_same_frames(self):
        truth = _model()
        frames = [_frame(truth) for _ in range(3)]
        wrong = replace(truth, axis_alt=67.0, cx=truth.cx - 41.0, cy=truth.cy + 89.0)
        assert incumbent_anchor_health(wrong, frames) is False
