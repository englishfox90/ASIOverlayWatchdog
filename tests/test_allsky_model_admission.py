"""Tests for services.allsky.model_admission — incumbent-relative admission.

Real numbers behind the fixtures (issue #10, 2026-09):
  - guided solve a1 = 1269 (RMS 2.4 px) vs converged refinements a1 = 1283:
    ratio 1.011 — same basin, must pass;
  - seedless "basin escape" candidates a1 = 1008–1044 vs the same 1283:
    ratios 0.79–0.81, passed every per-model gate, must be rejected when
    the incumbent has evidence behind it;
  - the 2026-06-23 incident model (a3 pinned, a1 at 0.57x the sky circle)
    is NOT a credible incumbent and must not lock anything;
  - review blocker: a wrong-scale model admitted at cold start with no pole
    (a1 = 1030 on the #10 rig) must never be able to lock out the truth.
"""
import json
import os
import sys
from dataclasses import replace

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.allsky.calibration_validate import POLE_TOL_REF_PX, tol_scale
from services.allsky.fisheye import FisheyeModel
from services.allsky.model_admission import (
    POLE_AUTHORITY_MAX_UNTRUSTED_RUNS,
    PROVENANCE_GUIDED,
    PROVENANCE_POLE,
    SCALE_CONTINUITY_MAX_DEV,
    admission_evidence,
    admit_candidate,
    admit_manual,
    east_left_hint,
    frame_scale,
    incumbent_authority,
    is_credible_incumbent,
    is_guided,
    is_pole_corroborated,
    pole_offset_px,
    projected_pole,
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


def _pole_of(model, east_left=True):
    """A trusted pole measured exactly where `model` projects it."""
    x, y = projected_pole(model, LAT)
    return _pole(x, y, east_left)


def _good(**over) -> FisheyeModel:
    """Known-good multi-image model of the reference rig (uncorroborated)."""
    m = FisheyeModel(
        cx=1532.277480022239, cy=1748.2333782530266,
        a1=1277.1768448604173, a3=-47.565326396085396, a5=-58.919100634659344,
        roll=1.2213944731235367, axis_alt=84.49275734968984,
        axis_az=280.49549589886345, east_left=True,
        rms_residual=7.8, n_matches=4561, n_images=40, span_minutes=80.0,
        image_width=W, image_height=H,
    )
    return replace(m, **over)


def _corroborated(**over) -> FisheyeModel:
    """The same model, admitted while a trusted pole confirmed it."""
    return _good(provenance=PROVENANCE_POLE, **over)


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
    def test_guided_is_credible(self):
        assert incumbent_authority(_guided()) == PROVENANCE_GUIDED
        assert is_credible_incumbent(_guided())

    def test_pole_corroborated_is_credible(self):
        assert incumbent_authority(_corroborated()) == PROVENANCE_POLE
        assert is_credible_incumbent(_corroborated())

    def test_uncorroborated_auto_model_has_no_authority(self):
        """Passing the per-model gates is not evidence: the #10 wrong-scale
        candidates passed them all."""
        assert incumbent_authority(_good()) is None
        assert not is_credible_incumbent(_good())

    def test_incident_model_is_not_credible(self):
        assert not is_credible_incumbent(_incident())
        assert not is_credible_incumbent(replace(_incident(), provenance=PROVENANCE_POLE))

    def test_none_and_invalid_are_not_credible(self):
        assert not is_credible_incumbent(None)
        assert not is_credible_incumbent(_corroborated(n_matches=0))

    def test_predicates(self):
        assert is_guided(_guided()) and not is_guided(_good()) and not is_guided(None)
        assert is_pole_corroborated(_corroborated())
        assert not is_pole_corroborated(_good()) and not is_pole_corroborated(None)


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
        They passed anchors + a1-vs-sky-circle; against an incumbent with
        evidence behind it the backstop must hold."""
        ok, msg = admit_candidate(_good(a1=a1), _corroborated(a1=1283.0), LAT,
                                  None, SKY_R, W, H)
        assert not ok
        assert 'plate scale' in msg and 'wrong-scale' in msg

    def test_same_basin_refinement_accepted(self):
        ok, msg = admit_candidate(_good(a1=1283.0), _corroborated(a1=1269.0), LAT,
                                  None, SKY_R, W, H)
        assert ok, msg
        assert 'plate scale 1.011x' in msg

    def test_band_edges(self):
        inc = _corroborated(a1=1000.0)
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

    def test_mirror_locked_by_corroborated_incumbent(self):
        ok, msg = admit_candidate(_good(east_left=False), _corroborated(), LAT,
                                  None, SKY_R, W, H)
        assert not ok and 'mirror' in msg


class TestBadIncumbentCannotLockOutTruth:
    """Review blocker 1 + 2: authority must follow evidence. The #10 rig
    (sky_r 1255, lat 36.58): truth a1 ~1283, wrong-scale bootstrap ~1030.
    Both pass every per-model gate."""

    RIG_LAT = 36.582222
    RIG_SKY_R = 1255.0

    def _rig(self, a1, **over):
        return _good(a1=a1, **over)

    def test_cold_start_wrong_scale_then_truth_recovers(self):
        wrong, truth = self._rig(1030.0), self._rig(1283.0)
        ok, msg = admit_candidate(wrong, None, self.RIG_LAT, None, self.RIG_SKY_R, W, H)
        assert ok and 'skipped' in msg                    # step 1: gets in
        assert wrong.provenance == ''                     # ...with no authority
        ok, msg = admit_candidate(truth, wrong, self.RIG_LAT, None, self.RIG_SKY_R, W, H)
        assert ok, msg                                    # step 2: truth is not locked out
        assert 'uncorroborated' in msg

    def test_truth_with_trusted_pole_recovers_and_is_corroborated(self):
        wrong, truth = self._rig(1030.0), self._rig(1283.0)
        pole = _pole(*projected_pole(truth, self.RIG_LAT), east_left=True)
        ok, msg = admit_candidate(truth, wrong, self.RIG_LAT, pole, self.RIG_SKY_R, W, H)
        assert ok, msg                                    # step 3: evidence rescues the rig
        assert truth.provenance == PROVENANCE_POLE

    def test_trusted_pole_keeps_wrong_scale_out_on_its_own(self):
        """With the pole trusted, the wrong-scale fit is caught by the pole
        gate itself (a 20% scale error moves the projected pole ~230px)."""
        wrong, truth = self._rig(1030.0), self._rig(1283.0)
        pole = _pole(*projected_pole(truth, self.RIG_LAT), east_left=True)
        px, py = projected_pole(wrong, self.RIG_LAT)
        assert np.hypot(px - pole.x, py - pole.y) > POLE_TOL_REF_PX * tol_scale(self.RIG_SKY_R)
        ok, msg = admit_candidate(wrong, truth, self.RIG_LAT, pole, self.RIG_SKY_R, W, H)
        assert not ok and 'measured position' in msg

    @pytest.mark.parametrize("bad", [
        pytest.param(dict(a1=1030.0), id="wrong-scale"),
        pytest.param(dict(east_left=False), id="wrong-mirror"),
        pytest.param(dict(roll=_good().roll + np.pi), id="wrong-basin"),
    ])
    def test_uncorroborated_bad_incumbent_cannot_reject_good_candidate(self, bad):
        """The missing test the review identified: the suite only ever
        checked a good incumbent rejecting a bad candidate."""
        ok, msg = admit_candidate(_good(), _good(**bad), LAT, None, SKY_R, W, H)
        assert ok, msg

    def test_wrong_mirror_uncorroborated_incumbent_gives_no_search_hint(self):
        """Blocker 2: the hint used to send every later search into the
        wrong half of the orientation space."""
        assert east_left_hint(_good(east_left=False), None) is None
        assert east_left_hint(_good(east_left=False), _pole(east_left=None)) is None
        assert east_left_hint(_good(east_left=False), _pole(east_left=True)) is True


class TestGuidedIncumbent:
    def test_refinement_admitted_despite_contaminated_pole(self):
        """The #10 failure in one call: converged refinement (a1 1283),
        guided incumbent (a1 1269), and a measured pole 1000+ px away.
        The guided basin outranks the pole: admitted, pole only advisory."""
        contaminant = _pole(1822.0, 2765.0, east_left=False)
        cand = _good(a1=1283.0)
        ok, msg = admit_candidate(cand, _guided(), LAT, contaminant, SKY_R, W, H)
        assert ok, msg
        assert 'guided' in msg
        assert cand.provenance == PROVENANCE_GUIDED

    def test_reporters_known_good_outcomes(self):
        """a1 = 1269 guided incumbent: 1283 refinement in; 0.79x / 0.82x
        escapes, a mirrored fit and a +700px centre out."""
        guided = _guided()
        assert admit_candidate(_good(a1=1283.0), guided, LAT, None, SKY_R, W, H)[0]
        for a1 in (1283.0 * 0.79, 1283.0 * 0.82):
            assert not admit_candidate(_good(a1=a1), guided, LAT, None, SKY_R, W, H)[0]
        assert not admit_candidate(_good(east_left=False), guided, LAT, None, SKY_R, W, H)[0]
        assert not admit_candidate(_good(cx=_good().cx + 700.0), guided, LAT, None,
                                   SKY_R, W, H)[0]

    def test_different_basin_rejected_against_guided(self):
        rolled = _good(roll=_good().roll + np.pi)
        ok, msg = admit_candidate(rolled, _guided(), LAT, None, SKY_R, W, H)
        assert not ok and 'different basin' in msg and 'user-anchored' in msg

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


class TestPoleCorroboratedIncumbent:
    def test_locks_mirror_scale_and_basin_when_no_pole_this_run(self):
        inc = _corroborated()
        assert not admit_candidate(_good(a1=1030.0), inc, LAT, None, SKY_R, W, H)[0]
        assert not admit_candidate(_good(east_left=False), inc, LAT, None, SKY_R, W, H)[0]
        rolled = _good(roll=_good().roll + np.pi)
        ok, msg = admit_candidate(rolled, inc, LAT, None, SKY_R, W, H)
        assert not ok and 'different basin' in msg

    def test_same_basin_inherits_corroboration(self):
        cand = _good(a1=1283.0)
        ok, msg = admit_candidate(cand, _corroborated(), LAT, None, SKY_R, W, H)
        assert ok, msg
        assert 'pole-corroborated' in msg
        assert cand.provenance == PROVENANCE_POLE

    def test_fresh_trusted_pole_outranks_stale_corroboration(self):
        """A model corroborated by a stable contaminant must not be a
        permanent lock either: once the genuine pole is measured, the
        candidate that matches it is admitted despite the scale conflict."""
        wrong = _corroborated(a1=1030.0)
        truth = _good(a1=1283.0)
        ok, msg = admit_candidate(truth, wrong, LAT, _pole_of(truth), SKY_R, W, H)
        assert ok, msg
        assert truth.provenance == PROVENANCE_POLE

    def test_trusted_pole_still_vetoes_a_candidate_that_misses_it(self):
        rolled = _good(roll=_good().roll + np.pi)
        ok, msg = admit_candidate(rolled, _corroborated(), LAT, _pole_of(_good()),
                                  SKY_R, W, H)
        assert not ok and 'measured position' in msg

    # A mirrored fit CAN put the pole on the measured spot (reflection about
    # the centre-pole line), so the pole position alone never settles the
    # mirror: measure the pole where the mirrored candidate projects it.

    def test_mirror_lock_holds_when_pole_has_no_repeated_vote(self):
        mirrored = _good(east_left=False)
        pole = _pole_of(mirrored, east_left=None)
        ok, msg = admit_candidate(mirrored, _corroborated(), LAT, pole, SKY_R, W, H)
        assert not ok and 'mirror' in msg and 'no repeated rotation vote' in msg

    def test_repeated_vote_overrides_incumbent_mirror(self):
        mirrored = _good(east_left=False)
        pole = _pole_of(mirrored, east_left=False)
        ok, msg = admit_candidate(mirrored, _corroborated(), LAT, pole, SKY_R, W, H)
        assert ok, msg
        assert mirrored.provenance == PROVENANCE_POLE


class TestProvenanceStamping:
    def test_no_incumbent_with_trusted_pole_is_corroborated(self):
        cand = _good()
        ok, _ = admit_candidate(cand, None, LAT, _pole_of(cand), SKY_R, W, H)
        assert ok and cand.provenance == PROVENANCE_POLE

    def test_no_incumbent_no_pole_stays_uncorroborated(self):
        cand = _good()
        ok, msg = admit_candidate(cand, None, LAT, None, SKY_R, W, H)
        assert ok and 'skipped' in msg
        assert cand.provenance == ''

    def test_rejected_candidate_is_not_stamped(self):
        cand = _good(a1=1030.0)
        assert not admit_candidate(cand, _guided(), LAT, None, SKY_R, W, H)[0]
        assert cand.provenance == ''

    def test_manual_result_confirmed_by_pole_is_corroborated(self):
        cand = _good()
        assert admit_manual(cand, LAT, _pole_of(cand), SKY_R, W, H)[0]
        assert cand.provenance == PROVENANCE_POLE
        plain = _good()
        assert admit_manual(plain, LAT, None, SKY_R, W, H)[0]
        assert plain.provenance == ''

    def test_guided_stays_guided(self):
        g = _guided()
        assert admit_manual(g, LAT, _pole(1822.0, 2765.0, east_left=False), SKY_R, W, H)[0]
        assert g.provenance == PROVENANCE_GUIDED


class TestMeasuredPoleStillGates:
    def test_no_incumbent_uses_pole(self):
        ok, msg = admit_candidate(_good(), None, LAT, _pole(), SKY_R, W, H)
        assert ok, msg
        mirrored = _good(east_left=False)
        assert not admit_candidate(mirrored, None, LAT, _pole(), SKY_R, W, H)[0]

    def test_uncorroborated_incumbent_still_subject_to_pole(self):
        rolled = _good(roll=_good().roll + np.pi)
        ok, msg = admit_candidate(rolled, _good(), LAT, _pole(), SKY_R, W, H)
        assert not ok and 'measured position' in msg

    def test_no_pole_no_incumbent_admits(self):
        ok, msg = admit_candidate(_good(), None, LAT, None, SKY_R, W, H)
        assert ok and 'skipped' in msg


class TestEastLeftHint:
    def test_guided_incumbent_outranks_pole(self):
        assert east_left_hint(_guided(), _pole(east_left=False)) is True

    def test_repeated_pole_vote_outranks_corroborated_incumbent(self):
        assert east_left_hint(_corroborated(), _pole(east_left=False)) is False

    def test_corroborated_incumbent_when_pole_is_silent(self):
        assert east_left_hint(_corroborated(), None) is True
        assert east_left_hint(_corroborated(), _pole(east_left=None)) is True

    def test_pole_when_no_credible_incumbent(self):
        assert east_left_hint(_incident(), _pole(east_left=True)) is True
        assert east_left_hint(_good(), _pole(east_left=False)) is False
        assert east_left_hint(None, _pole(east_left=False)) is False

    def test_nothing_known_searches_both_halves(self):
        assert east_left_hint(None, None) is None
        assert east_left_hint(_good(), None) is None
        assert east_left_hint(None, _pole(east_left=None)) is None


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
    @pytest.mark.parametrize("prov", [PROVENANCE_GUIDED, PROVENANCE_POLE])
    def test_round_trip(self, tmp_path, prov):
        p = tmp_path / "cal.json"
        _good(provenance=prov).save(str(p))
        assert FisheyeModel.load(str(p)).provenance == prov

    def test_legacy_file_without_provenance_loads_uncorroborated(self, tmp_path):
        p = tmp_path / "cal.json"
        _guided().save(str(p))
        legacy = json.loads(p.read_text())
        del legacy['provenance']
        p.write_text(json.dumps(legacy))
        loaded = FisheyeModel.load(str(p))
        assert loaded.provenance == ''
        assert incumbent_authority(loaded) is None


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
            pole = history.record(_pole(x, y, east_left=(i % 2 == 0)), SKY_R)
            refined = _good(a1=1283.0, n_matches=4561, rms_residual=7.7)
            ok, msg = admit_candidate(refined, guided, LAT, pole, SKY_R, W, H)
            assert ok, f"run {i}: {msg}"
            escape = _good(a1=1030.0, n_matches=900, rms_residual=6.0)
            ok, msg = admit_candidate(escape, guided, LAT, pole, SKY_R, W, H)
            assert not ok, f"run {i}: wrong-scale escape admitted: {msg}"

    def test_corroborated_incumbent_holds_the_scale_backstop(self):
        """A pole-corroborated auto incumbent locks the scale too, so the
        escape cannot silently move to 0.8x. The very first run's estimate
        is trusted (nothing contradicts it yet) and vetoes once; from the
        second distinct cluster on the gate is skipped and continuity
        carries the load."""
        history = PoleHistory()
        incumbent = _corroborated(a1=1283.0)
        for i, (x, y) in enumerate(self.RUNS):
            pole = history.record(_pole(x, y), SKY_R)
            escape = _good(a1=1030.0)
            assert not admit_candidate(escape, incumbent, LAT, pole, SKY_R, W, H)[0]
            refined = _good(a1=1290.0)
            ok, msg = admit_candidate(refined, incumbent, LAT, pole, SKY_R, W, H)
            if i == 0:
                assert not ok and 'measured position' in msg
            else:
                assert ok, f"run {i}: {msg}"

    def test_uncorroborated_incumbent_is_symmetric_ignorance(self):
        """Documents the trade-off: with no evidence on either side and no
        trusted pole, a wrong-scale escape can replace an uncorroborated
        good model — but the reverse is equally possible, so nothing is
        permanent. The remedies are a trusted pole or guided calibration."""
        history = PoleHistory()
        for x, y in self.RUNS[1:]:
            history.record(_pole(x, y), SKY_R)
        pole = history.record(_pole(*self.RUNS[0]), SKY_R)
        assert pole is None
        assert admit_candidate(_good(a1=1030.0), _good(a1=1283.0), LAT, pole, SKY_R, W, H)[0]
        assert admit_candidate(_good(a1=1283.0), _good(a1=1030.0), LAT, pole, SKY_R, W, H)[0]
        # ...but neither admission carries evidence, so calibration_service
        # holds an escape to the normal RMS/match comparison instead of
        # installing it outright (model_replacement).
        assert not admission_evidence(_good(a1=1283.0), pole)


class TestAdmissionEvidence:
    """What calibration_service needs to know before it lets an escape
    result bypass the RMS guard."""

    def test_uncorroborated_incumbent_and_no_pole_is_none(self):
        assert not admission_evidence(_good(), None)
        assert not admission_evidence(None, None)
        assert not admission_evidence(_incident(), None)

    def test_trusted_pole_is_evidence(self):
        assert admission_evidence(_good(), _pole())
        assert admission_evidence(None, _pole())

    def test_authoritative_incumbent_is_evidence(self):
        assert admission_evidence(_guided(), None)
        assert admission_evidence(_corroborated(), None)

    def test_expired_pole_rung_is_not_evidence(self):
        assert not admission_evidence(_corroborated(), None,
                                      runs_without_pole=POLE_AUTHORITY_MAX_UNTRUSTED_RUNS)


class TestPoleRungExpiry:
    """Review warning 3: with authority == 'pole' and no pole this run the
    continuity vetoes bound absolutely, and the candidate inherited the
    stamp without re-earning it — persisted across restarts. A camera
    repositioned into an orientation where Polaris is hidden had the
    correct new-geometry bootstrap rejected as 'different basin' forever."""

    N = POLE_AUTHORITY_MAX_UNTRUSTED_RUNS

    def test_horizon_is_the_history_length(self):
        from services.allsky.pole_consensus import POLE_HISTORY_LEN
        assert self.N == POLE_HISTORY_LEN

    def test_honoured_until_the_horizon(self):
        inc = _corroborated()
        for runs in (0, 1, self.N - 1):
            assert incumbent_authority(inc, runs) == PROVENANCE_POLE
            assert is_credible_incumbent(inc, runs)
        assert incumbent_authority(inc, self.N) is None
        assert incumbent_authority(inc, self.N + 5) is None

    def test_guided_never_expires(self):
        assert incumbent_authority(_guided(), 10 * self.N) == PROVENANCE_GUIDED

    def test_moved_camera_bootstrap_admitted_after_expiry(self):
        """The new geometry: different basin (roll + pi) and mirror-consistent.
        Rejected while the rung is honoured, admitted once it has aged."""
        inc = _corroborated()
        moved = _good(roll=_good().roll + np.pi)
        ok, msg = admit_candidate(moved, inc, LAT, None, SKY_R, W, H,
                                  runs_without_pole=self.N - 1)
        assert not ok and 'different basin' in msg
        ok, msg = admit_candidate(moved, inc, LAT, None, SKY_R, W, H,
                                  runs_without_pole=self.N)
        assert ok, msg
        assert 'uncorroborated' in msg
        assert moved.provenance == ''             # not inherited from a lapsed rung

    def test_expired_rung_gives_no_search_hint(self):
        assert east_left_hint(_corroborated(), None, self.N - 1) is True
        assert east_left_hint(_corroborated(), None, self.N) is None

    def test_default_is_no_drought(self):
        """Callers without a history (tests, tools) see the stamp honoured."""
        assert incumbent_authority(_corroborated()) == PROVENANCE_POLE
