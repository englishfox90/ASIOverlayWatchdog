"""Tests for services.allsky.model_admission — incumbent-relative admission.

Real numbers behind the fixtures (issue #10, 2026-09):
  - guided solve a1 = 1269 (RMS 2.4 px) vs converged refinements a1 = 1283:
    ratio 1.011 — same basin, must pass;
  - seedless "basin escape" candidates a1 = 1008–1044 vs the same 1283:
    ratios 0.79–0.81, passed every per-model gate, must be rejected;
  - the 2026-06-23 incident model (a3 pinned, a1 at 0.57x the sky circle)
    is NOT a credible incumbent and must not lock anything.
"""
import json
import os
import sys
from dataclasses import replace

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.allsky.calibration_validate import POLE_TOL_REF_PX
from services.allsky.fisheye import FisheyeModel
from services.allsky.model_admission import (
    PROVENANCE_GUIDED,
    SCALE_CONTINUITY_MAX_DEV,
    admit_candidate,
    admit_manual,
    east_left_hint,
    frame_scale,
    inherit_provenance,
    is_credible_incumbent,
    is_guided,
    pole_offset_px,
    scale_ratio,
)
from services.allsky.pole_consensus import PoleHistory
from services.allsky.pole_finder import PoleEstimate

LAT = 38.9717
SKY_R = 1563.0
W = H = 3552


def _pole(x=1718.0, y=646.0, east_left=True):
    return PoleEstimate(x=x, y=y, east_left=east_left, sign=-1, n_frames=12,
                        span_minutes=60.0, drift_px=3.3, flux=3600.0,
                        sign_votes=(300, 1700))


def _good(**over) -> FisheyeModel:
    """Known-good multi-image model of the reference rig."""
    m = FisheyeModel(
        cx=1532.277480022239, cy=1748.2333782530266,
        a1=1277.1768448604173, a3=-47.565326396085396, a5=-58.919100634659344,
        roll=1.2213944731235367, axis_alt=84.49275734968984,
        axis_az=280.49549589886345, east_left=True,
        rms_residual=7.8, n_matches=4561, n_images=40, span_minutes=80.0,
        image_width=W, image_height=H,
    )
    return replace(m, **over)


def _guided() -> FisheyeModel:
    """The user's guided solve: same basin, slightly different a1 (1269 vs
    1283 on the #10 rig -> apply the same 1.1% here), anchor RMS."""
    return _good(a1=1277.1768448604173 / 1.011, rms_residual=2.4, n_matches=7,
                 n_images=1, span_minutes=0.0, provenance=PROVENANCE_GUIDED)


def _incident() -> FisheyeModel:
    """The 2026-06-23 wrong-basin fit, scaled to the reference frame."""
    s = 3552.0 / 2628.0
    return FisheyeModel(
        cx=1154.452083684348 * s, cy=1322.8234646056446 * s,
        a1=480.5981324229242 * s, a3=19.99999999975631 * s,
        a5=-12.349397496767505 * s, roll=-0.20656450436385085,
        axis_alt=78.18606880664784, axis_az=12.576781341950102,
        east_left=False, rms_residual=4.2, n_matches=11,
        image_width=W, image_height=H,
    )


class TestCredibility:
    def test_guided_is_credible_regardless_of_sky_r(self):
        assert is_credible_incumbent(_guided(), None)
        assert is_credible_incumbent(_guided(), SKY_R)

    def test_good_auto_model_is_credible(self):
        assert is_credible_incumbent(_good(), SKY_R)

    def test_incident_model_is_not_credible(self):
        assert not is_credible_incumbent(_incident(), SKY_R)

    def test_none_and_invalid_are_not_credible(self):
        assert not is_credible_incumbent(None, SKY_R)
        assert not is_credible_incumbent(_good(n_matches=0), SKY_R)

    def test_is_guided(self):
        assert is_guided(_guided())
        assert not is_guided(_good())
        assert not is_guided(None)


class TestScaleContinuity:
    def test_same_basin_refinement_ratio(self):
        assert scale_ratio(_good(), _guided()) == pytest.approx(1.011, abs=1e-3)

    def test_normalises_across_resolutions(self):
        half = _good(a1=1277.18 / 2, cx=766.1, cy=874.1, image_width=W // 2,
                     image_height=H // 2)
        assert scale_ratio(half, _good()) == pytest.approx(1.0, abs=1e-3)
        assert frame_scale(half, _good()) == pytest.approx(0.5)

    def test_one_unknown_resolution_is_not_guessed(self):
        assert frame_scale(_good(image_width=0, image_height=0), _good()) is None
        assert scale_ratio(_good(image_width=0, image_height=0), _good()) is None

    def test_both_unknown_assumed_equal(self):
        a = _good(image_width=0, image_height=0)
        assert frame_scale(a, a) == 1.0

    def test_crop_is_not_a_resize(self):
        cropped = _good(image_width=1200, image_height=H)
        assert frame_scale(cropped, _good()) is None

    @pytest.mark.parametrize("a1", [1008.0, 1044.0])
    def test_wrong_scale_escape_candidate_rejected(self, a1):
        """The #10 bootstrap candidates: 0.79–0.81x the incumbent's scale.
        They passed anchors + a1-vs-sky-circle; the backstop must hold."""
        incumbent = _good(a1=1283.0)
        cand = _good(a1=a1)
        ok, msg = admit_candidate(cand, incumbent, LAT, None, SKY_R, W, H)
        assert not ok
        assert 'plate scale' in msg and 'wrong-scale' in msg

    def test_same_basin_refinement_accepted(self):
        ok, msg = admit_candidate(_good(a1=1283.0), _good(a1=1269.0), LAT,
                                  None, SKY_R, W, H)
        assert ok, msg

    def test_band_edges(self):
        inc = _good(a1=1000.0)
        lo = 1.0 - SCALE_CONTINUITY_MAX_DEV
        hi = 1.0 + SCALE_CONTINUITY_MAX_DEV
        assert admit_candidate(_good(a1=1000.0 * (lo + 0.005)), inc, LAT, None, SKY_R)[0]
        assert admit_candidate(_good(a1=1000.0 * (hi - 0.005)), inc, LAT, None, SKY_R)[0]
        assert not admit_candidate(_good(a1=1000.0 * (lo - 0.02)), inc, LAT, None, SKY_R)[0]
        assert not admit_candidate(_good(a1=1000.0 * (hi + 0.02)), inc, LAT, None, SKY_R)[0]

    def test_incident_incumbent_does_not_lock_scale(self):
        """Basin escape from a non-credible incumbent must be free to move
        to the true plate scale (0.51x -> 1.0x here)."""
        ok, msg = admit_candidate(_good(), _incident(), LAT, None, SKY_R, W, H)
        assert ok, msg

    def test_mirror_locked_by_credible_incumbent(self):
        ok, msg = admit_candidate(_good(east_left=False), _good(), LAT,
                                  None, SKY_R, W, H)
        assert not ok and 'mirror' in msg


class TestGuidedIncumbent:
    def test_refinement_admitted_despite_contaminated_pole(self):
        """The #10 failure in one call: converged refinement (a1 1283),
        guided incumbent (a1 1269), and a measured pole 1000+ px away.
        The guided basin outranks the pole: admitted, pole only advisory."""
        contaminant = _pole(1822.0, 2765.0, east_left=False)
        ok, msg = admit_candidate(_good(a1=1283.0), _guided(), LAT, contaminant,
                                  SKY_R, W, H)
        assert ok, msg
        assert 'guided' in msg

    def test_different_basin_rejected_against_guided(self):
        rolled = _good(roll=_good().roll + np.pi)
        ok, msg = admit_candidate(rolled, _guided(), LAT, None, SKY_R, W, H)
        assert not ok and 'different basin' in msg

    def test_mirrored_rejected_against_guided(self):
        ok, msg = admit_candidate(_good(east_left=False), _guided(), LAT,
                                  None, SKY_R, W, H)
        assert not ok and 'mirror' in msg

    def test_pole_continuity_across_resolutions(self):
        guided_raw = _guided()                      # 3552 px frame
        g = _good()
        half = _good(a1=g.a1 / 2, cx=g.cx / 2, cy=g.cy / 2, a3=g.a3 / 2,
                     a5=g.a5 / 2, image_width=W // 2, image_height=H // 2)
        d = pole_offset_px(half, guided_raw, LAT)
        # The guided fixture differs from `half` only by its 1.1% a1 offset.
        assert d is not None and d < 10.0
        ok, msg = admit_candidate(half, guided_raw, LAT, None, SKY_R / 2,
                                  W // 2, H // 2)
        assert ok, msg

    def test_pole_continuity_uses_gate_tolerance(self):
        shifted = _good(cx=_good().cx + POLE_TOL_REF_PX + 30.0)
        d = pole_offset_px(shifted, _guided(), LAT)
        assert d > POLE_TOL_REF_PX
        ok, _ = admit_candidate(shifted, _guided(), LAT, None, SKY_R, W, H)
        assert not ok
        near = _good(cx=_good().cx + 60.0)
        assert admit_candidate(near, _guided(), LAT, None, SKY_R, W, H)[0]

    def test_provenance_inherited_only_from_guided(self):
        cand = _good()
        inherit_provenance(cand, _guided())
        assert cand.provenance == PROVENANCE_GUIDED
        cand2 = _good()
        inherit_provenance(cand2, _good())
        assert cand2.provenance == ''
        inherit_provenance(cand2, None)
        assert cand2.provenance == ''


class TestMeasuredPoleStillGates:
    def test_no_incumbent_uses_pole(self):
        ok, msg = admit_candidate(_good(), None, LAT, _pole(), SKY_R, W, H)
        assert ok, msg
        mirrored = _good(east_left=False)
        assert not admit_candidate(mirrored, None, LAT, _pole(), SKY_R, W, H)[0]

    def test_credible_non_guided_incumbent_still_subject_to_pole(self):
        rolled = _good(roll=_good().roll + np.pi)
        ok, msg = admit_candidate(rolled, _good(), LAT, _pole(), SKY_R, W, H)
        assert not ok and 'measured position' in msg

    def test_no_pole_no_incumbent_admits(self):
        ok, msg = admit_candidate(_good(), None, LAT, None, SKY_R, W, H)
        assert ok and 'skipped' in msg


class TestEastLeftHint:
    def test_credible_incumbent_wins(self):
        assert east_left_hint(_good(), _pole(east_left=False), SKY_R) is True

    def test_pole_when_no_credible_incumbent(self):
        assert east_left_hint(_incident(), _pole(east_left=True), SKY_R) is True
        assert east_left_hint(None, _pole(east_left=False), SKY_R) is False

    def test_nothing_known_searches_both_halves(self):
        assert east_left_hint(None, None, SKY_R) is None
        assert east_left_hint(None, _pole(east_left=None), SKY_R) is None


class TestManualPaths:
    def test_guided_candidate_never_vetoed(self):
        contaminant = _pole(1822.0, 2765.0, east_left=False)
        ok, msg = admit_manual(_guided(), LAT, contaminant, SKY_R, W, H)
        assert ok and 'guided' in msg

    def test_calibrate_now_result_still_gated(self):
        mirrored = _good(east_left=False)
        assert not admit_manual(mirrored, LAT, _pole(), SKY_R, W, H)[0]
        assert admit_manual(_good(), LAT, _pole(), SKY_R, W, H)[0]


class TestProvenancePersistence:
    def test_round_trip_and_legacy_file(self, tmp_path):
        p = tmp_path / "cal.json"
        _guided().save(str(p))
        assert FisheyeModel.load(str(p)).provenance == PROVENANCE_GUIDED
        legacy = json.loads(p.read_text())
        del legacy['provenance']
        p.write_text(json.dumps(legacy))
        assert FisheyeModel.load(str(p)).provenance == ''


class TestIssue10EndToEnd:
    """The night as the service would now see it: contaminated pole
    history, a guided incumbent, converged refinements, and wrong-scale
    escape candidates."""

    RUNS = [(1822, 2765), (988, 1792), (1905, 685), (1646, 667),
            (967, 1820), (1001, 1725), (1822, 2765), (988, 1792)]

    def test_refinements_admitted_escapes_rejected(self):
        history = PoleHistory()
        guided = _guided()
        for i, (x, y) in enumerate(self.RUNS):
            pole = history.resolve(_pole(x, y, east_left=(i % 2 == 0)), SKY_R)
            refined = _good(a1=1283.0, n_matches=4561, rms_residual=7.7)
            ok, msg = admit_candidate(refined, guided, LAT, pole, SKY_R, W, H)
            assert ok, f"run {i}: {msg}"
            escape = _good(a1=1030.0, n_matches=900, rms_residual=6.0)
            ok, msg = admit_candidate(escape, guided, LAT, pole, SKY_R, W, H)
            assert not ok, f"run {i}: wrong-scale escape admitted: {msg}"

    def test_without_guided_incumbent_the_scale_backstop_still_holds(self):
        """A credible auto incumbent (Calibrate Now / bootstrap) locks the
        scale too, so the escape cannot silently move to 0.8x. Its basin is
        not locked, so the measured pole still gates: the very first run's
        estimate is trusted (nothing contradicts it yet) and vetoes once;
        from the second distinct cluster on the gate is skipped."""
        history = PoleHistory()
        incumbent = _good(a1=1283.0)
        for i, (x, y) in enumerate(self.RUNS):
            pole = history.resolve(_pole(x, y), SKY_R)
            escape = _good(a1=1030.0)
            assert not admit_candidate(escape, incumbent, LAT, pole, SKY_R, W, H)[0]
            refined = _good(a1=1290.0)
            ok, msg = admit_candidate(refined, incumbent, LAT, pole, SKY_R, W, H)
            if i == 0:
                assert not ok and 'measured position' in msg
            else:
                assert ok, f"run {i}: {msg}"
