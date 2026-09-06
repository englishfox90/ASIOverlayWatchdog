"""Tests for services.allsky.pole_consensus — cross-run trust in the pole.

The issue #10 log (2026-09) is the fixture: six mutually exclusive pole
positions across 20 runs of a fixed camera. Nothing in that sequence may be
trusted — yet the dominant contaminant is self-consistent to ±1 px, so a
stability test would admit it. Multi-modality is the signal.
"""
import os
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.allsky.calibration_validate import (
    POLE_TOL_REF_PX, REF_SKY_R_PX, validate_pole)
from services.allsky.fisheye import FisheyeModel
from services.allsky.pole_consensus import (
    DOMINANT_MODE_FRACTION,
    MIN_FOUND_FRACTION,
    MIN_REPEATED_SIGN_VOTES,
    MODE_LINK_REF_PX,
    POLE_HISTORY_LEN,
    PoleHistory,
    cluster_positions,
    consensus_east_left,
    independent_windows,
    to_frame,
)
from services.allsky.pole_finder import PoleEstimate

LAT = 38.9717


def est(x, y, east_left=True, sign=-1):
    return PoleEstimate(x=float(x), y=float(y), east_left=east_left, sign=sign,
                        n_frames=12, span_minutes=60.0, drift_px=3.3,
                        flux=3600.0, sign_votes=(300, 1700))


# The 20-run sequence from the issue #10 log, in a plausible interleaving
# (the log alternated between the far cluster and the near ones).
ISSUE_10_RUNS = [
    (1822, 2765), (988, 1792), (1905, 685), (1822, 2765), (1646, 667),
    (987, 1792), (1822, 2766), (1905, 685), (967, 1820), (1001, 1725),
    (1822, 2765), (1646, 667), (988, 1792), (1905, 686), (1822, 2764),
    (967, 1820), (1646, 667), (1905, 685), (988, 1792), (1822, 2765),
]


def _reference_model() -> FisheyeModel:
    """Known-good multi-image model of the reference rig (RMS ~8px)."""
    return FisheyeModel(
        cx=1532.277480022239, cy=1748.2333782530266,
        a1=1277.1768448604173, a3=-47.565326396085396, a5=-58.919100634659344,
        roll=1.2213944731235367, axis_alt=84.49275734968984,
        axis_az=280.49549589886345, east_left=True,
        rms_residual=7.8, n_matches=4561, n_images=40, span_minutes=80.0,
    )


class TestClustering:
    def test_single_linkage(self):
        pts = [(0, 0), (50, 0), (100, 0), (500, 0)]
        assert cluster_positions(pts, 60.0) == [[0, 1, 2], [3]]

    def test_link_tolerance_scales_with_sky_r(self):
        # Two estimates 100px apart: one mode at reference scale (link 70px
        # merges only if closer)… so they split at 1563 and merge at 2x.
        h = PoleHistory()
        h.record(est(1000, 1000), REF_SKY_R_PX)
        assert h.record(est(1100, 1000), REF_SKY_R_PX) is None
        h2 = PoleHistory()
        h2.record(est(1000, 1000), 2 * REF_SKY_R_PX)
        assert h2.record(est(1100, 1000), 2 * REF_SKY_R_PX) is not None

    def test_link_is_half_the_gate_tolerance(self):
        assert MODE_LINK_REF_PX == pytest.approx(0.5 * POLE_TOL_REF_PX)


class TestGenuinePole:
    def test_first_run_is_trusted_for_position_not_mirror(self):
        r = PoleHistory().record(est(1718, 646), 1563.0)
        assert r is not None
        assert (r.x, r.y) == (1718.0, 646.0)
        assert r.east_left is None       # a single decisive vote does not repeat

    def test_polaris_orbit_spread_stays_one_mode(self):
        # Polaris' mean over a window walks a ~12px-radius circle across a
        # night at reference scale; that must never split into modes.
        h = PoleHistory()
        pts = [(1718, 646), (1722, 655), (1730, 660), (1706, 650), (1719, 649)]
        out = [h.record(est(x, y), 1563.0) for x, y in pts]
        assert all(r is not None for r in out)
        assert out[-1].east_left is True

    def test_repeated_decisive_vote_asserts_mirror(self):
        h = PoleHistory()
        assert h.record(est(1718, 646), 1563.0).east_left is None
        assert h.record(est(1719, 647), 1563.0).east_left is True

    def test_one_dissenting_vote_withdraws_mirror(self):
        h = PoleHistory()
        h.record(est(1718, 646, east_left=True), 1563.0)
        h.record(est(1719, 647, east_left=True), 1563.0)
        r = h.record(est(1718, 648, east_left=False), 1563.0)
        assert r is not None            # position still trusted (one mode)
        assert r.east_left is None      # mirror no longer asserted

    def test_indecisive_votes_never_assert_mirror(self):
        votes = [est(1718, 646, east_left=None)] * 5
        assert consensus_east_left(votes) is None
        assert MIN_REPEATED_SIGN_VOTES == 2

    def test_genuine_pole_still_vetoes_wrong_basin(self):
        """The consensus must not weaken the gate where the pole is real."""
        h = PoleHistory()
        for _ in range(4):
            pole = h.record(est(1718, 646), 1563.0)
        good = _reference_model()
        assert validate_pole(good, LAT, pole, sky_r=1563.0)[0]
        mirrored = _reference_model()
        mirrored.east_left = False
        ok, msg = validate_pole(mirrored, LAT, pole, sky_r=1563.0)
        assert not ok and 'east_left' in msg
        rolled = _reference_model()
        rolled.roll += 3.14159
        ok, msg = validate_pole(rolled, LAT, pole, sky_r=1563.0)
        assert not ok and 'measured position' in msg


class TestReadWithoutRecording:
    """Review blocker 3: resolve() used to append on every call, so reading
    the consensus twice for one physical measurement manufactured the
    'repeated' vote the mirror assertion requires."""

    def test_current_does_not_record(self):
        h = PoleHistory()
        h.record(est(1718, 646), 1563.0)
        for _ in range(3):
            r = h.current(1563.0)
            assert r is not None
            assert r.east_left is None
        assert len(h) == 1

    def test_one_physical_reading_cannot_assert_mirror(self):
        h = PoleHistory()
        reading = est(1718, 646, east_left=True)
        first = h.record(reading, 1563.0)
        assert first.east_left is None
        assert h.current(1563.0).east_left is None
        assert h.current(1563.0).east_left is None
        # Only a second recorded run repeats the vote.
        assert h.record(est(1719, 647, east_left=True), 1563.0).east_left is True
        assert h.current(1563.0).east_left is True

    def test_current_on_empty_history(self):
        assert PoleHistory().current(1563.0) is None

    def test_current_uses_latest_found_run(self):
        h = PoleHistory()
        h.record(est(1718, 646), 1563.0)
        h.record(est(1720, 648), 1563.0)
        h.record(None, 1563.0)               # a miss does not erase the consensus
        r = h.current(1563.0)
        assert r is not None and (r.x, r.y) == (1720.0, 648.0)
        assert r.east_left is True

    def test_current_applies_the_same_trust_rules(self):
        h = PoleHistory()
        h.record(est(1822, 2765), 1563.0)
        h.record(est(988, 1792), 1563.0)
        assert h.current(1563.0) is None      # no dominant mode
        h2 = PoleHistory()
        h2.record(est(1718, 646), 1563.0)
        for _ in range(3):
            h2.record(None, 1563.0)
        assert h2.current(1563.0) is None     # found in 1/4 runs


class TestDominantMode:
    """One aircraft / satellite trail / cloud-edge outlier must not disable
    the gate for a full history length — that window is where an
    uncorroborated model gets in (model_admission)."""

    def test_fraction(self):
        assert DOMINANT_MODE_FRACTION == 0.75

    def test_one_outlier_in_four_keeps_the_pole(self):
        h = PoleHistory()
        h.record(est(1718, 646), 1563.0)
        h.record(est(1719, 647), 1563.0)
        assert h.record(est(2400, 1900), 1563.0) is None     # the outlier run itself
        r = h.record(est(1720, 648), 1563.0)                 # 3 of 4 agree
        assert r is not None and r.east_left is True
        assert h.current(1563.0) is not None

    def test_two_of_three_is_not_dominant(self):
        h = PoleHistory()
        h.record(est(1718, 646), 1563.0)
        h.record(est(2400, 1900), 1563.0)
        assert h.record(est(1719, 647), 1563.0) is None

    def test_estimate_outside_dominant_mode_is_not_trusted(self):
        h = PoleHistory()
        for _ in range(6):
            h.record(est(1718, 646), 1563.0)
        assert h.record(est(2400, 1900), 1563.0) is None
        assert h.current(1563.0) is None      # the latest run is the outlier
        assert h.record(est(1718, 646), 1563.0) is not None

    def test_mirror_votes_come_from_the_dominant_mode_only(self):
        h = PoleHistory()
        for _ in range(3):
            h.record(est(1718, 646, east_left=True), 1563.0)
        h.record(est(2400, 1900, east_left=False), 1563.0)
        r = h.record(est(1718, 646, east_left=True), 1563.0)
        assert r is not None and r.east_left is True


class TestContaminatedField:
    def test_issue_10_sequence_is_never_trusted(self):
        """Regression: the 20-run, six-cluster sequence from the #10 log.
        After the second distinct cluster appears, no run's estimate may
        reach the gate — including the runs on the self-consistent
        dominant contaminant."""
        h = PoleHistory()
        outcomes = [h.record(est(x, y), 1563.0) for x, y in ISSUE_10_RUNS]
        assert outcomes[0] is not None          # nothing to contradict yet
        assert all(r is None for r in outcomes[1:])
        assert h.current(1563.0) is None

    def test_good_model_not_vetoed_by_contaminated_pole(self):
        """The actual failure: a converged, anchor-passing model was vetoed
        16 times by whichever cluster the latest run returned. Through the
        consensus the gate is skipped; against the raw estimate it would
        still fire (proving the test exercises the fix, not the tolerance)."""
        good = _reference_model()
        h = PoleHistory()
        vetoed_raw = 0
        for x, y in ISSUE_10_RUNS:
            raw = est(x, y)
            if not validate_pole(good, LAT, raw, sky_r=1563.0)[0]:
                vetoed_raw += 1
            pole = h.record(raw, 1563.0)
            if len(h) > 1:
                ok, msg = validate_pole(good, LAT, pole, sky_r=1563.0)
                assert ok, msg
                assert 'skipped' in msg
        # 17/20: the (1646, 667) cluster is from a different rig and happens
        # to sit ~100px from the reference rig's pole, inside the tolerance.
        assert vetoed_raw >= 17

    def test_stable_wrong_pole_is_not_caught_by_consensus_alone(self):
        """Documents the limit: a single self-consistent contaminant is
        unimodal, so the consensus trusts it. Rejecting it is the job of
        pole_finder's rotation-support floor and, failing that, the
        incumbent-relative admission in model_admission."""
        h = PoleHistory()
        for _ in range(6):
            r = h.record(est(1822, 2765), 1563.0)
        assert r is not None

    def test_intermittent_estimate_not_trusted(self):
        """A pole found in under half the recent runs is flickering — a
        genuine Polaris was found in 26/26 windows; a near-pole contaminant
        cleared the rotation floor in 2–8 of 26."""
        h = PoleHistory()
        seq = [None, None, est(1900, 700), None, est(1901, 701), None, None]
        out = [h.record(e, 1563.0) for e in seq]
        assert all(r is None for r in out)
        assert MIN_FOUND_FRACTION == 0.5

    def test_recovers_after_history_rolls_over(self):
        h = PoleHistory(maxlen=4)
        h.record(est(1822, 2765), 1563.0)
        for _ in range(4):
            r = h.record(est(1718, 646), 1563.0)
        assert r is not None            # the contaminant run has rolled out

    def test_clear(self):
        h = PoleHistory()
        h.record(est(1822, 2765), 1563.0)
        h.record(est(1718, 646), 1563.0)
        h.clear()
        assert len(h) == 0
        assert h.record(est(1718, 646), 1563.0) is not None

    def test_history_length(self):
        assert POLE_HISTORY_LEN == 12
        h = PoleHistory()
        for i in range(30):
            h.record(est(1718 + i * 0.1, 646), 1563.0)
        assert len(h) == POLE_HISTORY_LEN

    def test_none_passes_through(self):
        h = PoleHistory()
        assert h.record(None, 1563.0) is None


# ---------------------------------------------------------------------------
# Review warning 1: a reader with its own measurement
# ---------------------------------------------------------------------------

class TestEvaluate:
    def test_fresh_measurement_gates_on_an_empty_history(self):
        """The first Calibrate Now on a fresh install: nothing recorded yet,
        but the buffer yields a pole — it must be used."""
        h = PoleHistory()
        r = h.evaluate(est(1718, 646), 1563.0)
        assert r is not None and (r.x, r.y) == (1718.0, 646.0)
        assert r.east_left is None
        assert len(h) == 0

    def test_evaluate_never_records(self):
        h = PoleHistory()
        h.record(est(1718, 646), 1563.0)
        for _ in range(3):
            assert h.evaluate(est(1719, 647), 1563.0) is not None
        assert len(h) == 1
        assert h.runs_since_trusted == 0

    def test_one_reading_evaluated_repeatedly_never_asserts_mirror(self):
        h = PoleHistory()
        reading = est(1718, 646, east_left=True)
        for _ in range(4):
            assert h.evaluate(reading, 1563.0).east_left is None

    def test_fresh_outlier_is_not_trusted(self):
        h = PoleHistory()
        for _ in range(4):
            h.record(est(1718, 646), 1563.0)
        assert h.evaluate(est(2400, 1900), 1563.0) is None

    def test_fresh_miss_keeps_an_established_consensus(self):
        """A miss lowers the found fraction but does not erase what the
        field has shown: the manual result is still held to it."""
        h = PoleHistory()
        for _ in range(4):
            h.record(est(1718, 646), 1563.0)
        r = h.evaluate(None, 1563.0)
        assert r is not None and (r.x, r.y) == (1718.0, 646.0)
        assert PoleHistory().evaluate(None, 1563.0) is None

    def test_fresh_second_cluster_withdraws_trust(self):
        h = PoleHistory()
        h.record(est(1822, 2765), 1563.0)
        assert h.evaluate(est(988, 1792), 1563.0) is None


# ---------------------------------------------------------------------------
# Review warning 2: "repeated" votes must be independent
# ---------------------------------------------------------------------------

T0 = datetime(2026, 1, 16, 8, 0, tzinfo=timezone.utc)


def windowed(x, y, start_min, end_min, east_left=True):
    return replace(est(x, y, east_left=east_left),
                   window_start=T0 + timedelta(minutes=start_min),
                   window_end=T0 + timedelta(minutes=end_min))


class TestIndependentWindows:
    def test_overlapping_windows_do_not_repeat(self):
        """Consecutive runs 2 min apart over a 30-min buffer: the same
        measurement twice, not a repeated vote."""
        h = PoleHistory()
        h.record(windowed(1718, 646, 0, 30), 1563.0)
        r = h.record(windowed(1719, 647, 2, 32), 1563.0)
        assert r is not None and r.east_left is None
        r = h.record(windowed(1719, 647, 4, 34), 1563.0)
        assert r.east_left is None

    def test_disjoint_windows_repeat(self):
        h = PoleHistory()
        h.record(windowed(1718, 646, 0, 30), 1563.0)
        assert h.record(windowed(1719, 647, 30, 60), 1563.0).east_left is True

    def test_counts_mutually_disjoint_sets(self):
        assert independent_windows([windowed(0, 0, 0, 30), windowed(0, 0, 10, 40),
                                    windowed(0, 0, 35, 60)]) == 2
        assert independent_windows([windowed(0, 0, 0, 30), windowed(0, 0, 10, 40),
                                    windowed(0, 0, 20, 50)]) == 1

    def test_unstamped_estimates_count_as_independent(self):
        """Documented: only find_pole makes estimates in production and it
        always stamps them; an unstamped one cannot be shown to overlap."""
        assert independent_windows([est(0, 0), est(0, 0)]) == 2
        assert independent_windows([est(0, 0), windowed(0, 0, 0, 30)]) == 2

    def test_ledger_outlives_the_position_history(self):
        """On a fast rig the 12-run history is shorter than one buffer span,
        so no two windows inside it are ever disjoint: the vote must draw
        on runs that have already rolled out of the position history."""
        h = PoleHistory(maxlen=4)
        for k in range(8):                       # 2-min cadence, 30-min buffer
            r = h.record(windowed(1718, 646, 2 * k, 2 * k + 30), 1563.0)
        assert r.east_left is None               # 14 min apart at most
        for k in range(8, 20):
            r = h.record(windowed(1718, 646, 2 * k, 2 * k + 30), 1563.0)
        assert len(h) == 4
        assert r.east_left is True               # run 0 and run 15+ are disjoint

    def test_votes_at_another_position_do_not_count(self):
        """A contaminant's (or pre-move) vote elsewhere in the frame never
        speaks for the current pole position."""
        h = PoleHistory(maxlen=4)
        h.record(windowed(1822, 2765, 0, 30, east_left=False), 1563.0)
        for _ in range(4):
            h.record(None, 1563.0)               # roll the contaminant out
        h.record(windowed(1718, 646, 60, 90, east_left=True), 1563.0)
        r = h.record(windowed(1719, 647, 62, 92, east_left=True), 1563.0)
        assert r is not None
        assert r.east_left is None               # the far dissent is ignored...
        r = h.record(windowed(1719, 647, 100, 130, east_left=True), 1563.0)
        assert r.east_left is True               # ...and so is its window

    def test_dissent_in_the_ledger_withdraws_mirror(self):
        h = PoleHistory()
        h.record(windowed(1718, 646, 0, 30, east_left=True), 1563.0)
        h.record(windowed(1719, 647, 40, 70, east_left=False), 1563.0)
        assert h.record(windowed(1718, 646, 80, 110, east_left=True), 1563.0).east_left is None

    def test_find_pole_stamps_window_and_resolution(self):
        from services.allsky.pole_finder import find_pole
        from tests.test_allsky_pole_finder import make_frames
        frames = make_frames(n_frames=12, span_min=66.0)
        for f in frames:
            f['image_width'], f['image_height'] = 3552, 3552
        e = find_pole(frames, lat_deg=39.0)
        assert e is not None
        assert e.window_start == frames[0]['dt'] and e.window_end == frames[-1]['dt']
        assert (e.image_width, e.image_height) == (3552, 3552)

    def test_clear_empties_the_ledger(self):
        h = PoleHistory()
        h.record(windowed(1718, 646, 0, 30), 1563.0)
        h.clear()
        h.record(windowed(1718, 646, 60, 90), 1563.0)
        assert h.current(1563.0).east_left is None


# ---------------------------------------------------------------------------
# Review warning 3: runs without a trusted pole
# ---------------------------------------------------------------------------

class TestRunsSinceTrusted:
    def test_counts_and_resets(self):
        h = PoleHistory()
        assert h.runs_since_trusted == 0
        h.record(None, 1563.0)
        h.record(None, 1563.0)
        assert h.runs_since_trusted == 2
        h.record(est(1718, 646), 1563.0)         # found in 1/3 — not trusted
        assert h.runs_since_trusted == 3
        h.record(est(1718, 646), 1563.0)         # 2/4 — trusted
        assert h.runs_since_trusted == 0
        h.record(est(2400, 1900), 1563.0)        # outlier run
        assert h.runs_since_trusted == 1

    def test_clear_resets(self):
        h = PoleHistory()
        h.record(None, 1563.0)
        h.clear()
        assert h.runs_since_trusted == 0


# ---------------------------------------------------------------------------
# Review warning 4: positions are compared in one frame
# ---------------------------------------------------------------------------

def at_res(x, y, w, h, east_left=True):
    return replace(est(x, y, east_left=east_left), image_width=w, image_height=h)


class TestResolution:
    def test_resize_mid_session_is_rescaled_not_split(self):
        """Full-res runs then resize_percent=50: the half-res estimate is
        the same pole and must join the same mode, in the new frame."""
        h = PoleHistory()
        for _ in range(3):
            h.record(at_res(1718, 646, 3552, 3552), 1563.0)
        r = h.record(at_res(859, 323, 1776, 1776), 781.5)
        assert r is not None
        assert (r.x, r.y) == (859.0, 323.0)
        assert (r.image_width, r.image_height) == (1776, 1776)
        assert r.east_left is True

    def test_current_rescales_into_the_requested_frame(self):
        h = PoleHistory()
        h.record(at_res(1718, 646, 3552, 3552), 1563.0)
        h.record(at_res(1720, 648, 3552, 3552), 1563.0)
        r = h.current(781.5, image_width=1776, image_height=1776)
        assert r.x == pytest.approx(860.0) and r.y == pytest.approx(324.0)

    def test_crop_is_dropped_not_compared(self):
        h = PoleHistory()
        h.record(at_res(1718, 646, 3552, 3552), 1563.0)
        h.record(at_res(1718, 646, 3552, 3552), 1563.0)
        r = h.record(at_res(500, 400, 1200, 3552), 1563.0)
        assert r is not None and (r.x, r.y) == (500.0, 400.0)
        assert r.east_left is None                # nothing comparable to vote

    def test_unknown_resolution_compares_as_is(self):
        h = PoleHistory()
        h.record(est(1718, 646), 1563.0)
        assert h.record(at_res(1719, 647, 3552, 3552), 1563.0) is not None

    def test_to_frame(self):
        e = at_res(1000, 500, 2000, 1000)
        f = to_frame(e, 1000, 500)
        assert (f.x, f.y, f.image_width, f.image_height) == (500.0, 250.0, 1000, 500)
        assert to_frame(e, 1000, 800) is None
        assert to_frame(e, 0, 0) is e
        assert to_frame(est(1, 1), 1000, 500) is not None
