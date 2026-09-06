"""Tests for services.allsky.model_replacement — does an admitted automatic
fit replace the incumbent?

The basin-escape rules are the point: an escape result bypasses the RMS
guard only when it was admitted on evidence. Without evidence (an
uncorroborated incumbent — every pre-provenance installation — and no
trusted pole) it is held to the normal comparison, so a wrong-scale
bootstrap over a hazy buffer cannot overwrite a working model, while a
genuinely better candidate can still displace a wrong cold-start one.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.allsky.calibration_quality import model_quality
from services.allsky.fisheye import FisheyeModel
from services.allsky.model_replacement import RMS_REGRESSION_TOLERANCE, should_replace


def _m(rms, n_matches, n_images=20, span=60.0, **over):
    m = FisheyeModel(cx=960.0, cy=540.0, a1=600.0, rms_residual=rms,
                     n_matches=n_matches, n_images=n_images, span_minutes=span)
    for k, v in over.items():
        setattr(m, k, v)
    return m


def _q(m):
    return model_quality(m, m.n_images, m.span_minutes)


def _decide(inc, cand, **kw):
    return should_replace(inc, _q(inc), cand, _q(cand), **kw)


class TestNoIncumbent:
    def test_anything_replaces_nothing(self):
        ok, why = should_replace(None, 'none', _m(15.0, 10), 'preliminary')
        assert ok and 'no incumbent' in why


class TestBasinEscape:
    # The #10 shape: a working excellent model vs a wrong-scale escape with
    # fewer matches and a plausible RMS.
    WORKING = dict(rms=7.7, n_matches=4561, n_images=40, span=80.0)
    WRONG_SCALE = dict(rms=6.0, n_matches=900, n_images=20, span=60.0)

    def test_escape_on_evidence_bypasses_rms_guard(self):
        flattering = _m(4.0, 11, n_images=1, span=0.0)
        honest = _m(9.0, 200)
        ok, why = _decide(flattering, honest, escape=True, evidence=True)
        assert ok and 'without the RMS guard' in why

    def test_escape_without_evidence_cannot_demote_working_model(self):
        """The review blocker, as the decision sees it."""
        ok, why = _decide(_m(**self.WORKING), _m(**self.WRONG_SCALE),
                          escape=True, evidence=False)
        assert not ok
        assert 'without evidence' in why and 'normal comparison' in why

    def test_same_candidate_wins_on_evidence(self):
        """Same numbers, admitted against a trusted pole or an authoritative
        incumbent: the escape premise holds and the RMS guard is waived."""
        ok, _ = _decide(_m(**self.WORKING), _m(**self.WRONG_SCALE),
                        escape=True, evidence=True)
        assert ok

    def test_escape_without_evidence_still_wins_when_better(self):
        """Blocker-1 regression guard: no permanent lockout on no evidence."""
        wrong_cold_start = _m(9.0, 300)
        truth = _m(7.0, 1200, n_images=25, span=70.0)
        ok, _ = _decide(wrong_cold_start, truth, escape=True, evidence=False)
        assert ok

    def test_escape_without_evidence_respects_rms_guard(self):
        ok, why = _decide(_m(4.0, 100), _m(9.0, 200), escape=True, evidence=False)
        assert not ok and 'worse' in why

    def test_evidence_without_escape_changes_nothing(self):
        """Evidence only waives the guard for an escape; a seeded refinement
        admitted on evidence is still held to the normal comparison."""
        ok, _ = _decide(_m(4.0, 100), _m(9.0, 200), escape=False, evidence=True)
        assert not ok


class TestGuidedSingleSolve:
    def _guided(self):
        return _m(2.4, 7, n_images=1, span=0.0, provenance='guided')

    def test_multi_image_candidate_replaces_on_rank(self):
        ok, why = _decide(self._guided(), _m(7.7, 4561, n_images=40, span=80.0))
        assert ok and 'guided single solve' in why

    def test_single_image_candidate_does_not(self):
        ok, _ = _decide(self._guided(), _m(6.0, 40, n_images=1, span=0.0))
        assert not ok

    def test_multi_image_guided_incumbent_uses_normal_guard(self):
        inc = _m(7.7, 4561, n_images=40, span=80.0, provenance='guided')
        assert not _decide(inc, _m(12.0, 5000, n_images=45, span=90.0))[0]


class TestRmsGuard:
    def test_tolerance(self):
        assert RMS_REGRESSION_TOLERANCE == pytest.approx(1.15)

    def test_rank_upgrade_within_bound(self):
        inc = _m(10.0, 50, n_images=3, span=30.0)
        cand = _m(11.0, 110, n_images=12, span=40.0)
        ok, why = _decide(inc, cand)
        assert ok and 'rank upgrade' in why

    def test_rank_upgrade_beyond_bound_rejected(self):
        inc = _m(3.0, 100, n_images=3, span=30.0)
        assert not _decide(inc, _m(4.0, 120, n_images=12, span=40.0))[0]

    def test_strict_improvement(self):
        ok, why = _decide(_m(8.0, 80), _m(6.0, 85))
        assert ok and 'lower RMS' in why

    def test_fewer_matches_is_not_an_improvement(self):
        ok, why = _decide(_m(8.0, 80), _m(6.0, 60))
        assert not ok and 'not better' in why
