"""
Tests for services/allsky/calibration_validate.py.

Covers:
  - score_matches_with_spread():   azimuth spread lowers the score of
    clustered matches, leaves well-spread matches near their raw count.
  - validate_bright_anchors():     catches spurious fits by checking that
    projected bright catalog stars land on detected stars.
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.allsky.calibration_validate import (
    A3_MAX,
    A3_MIN,
    REF_SKY_R_PX,
    score_matches_with_spread,
    tol_scale,
    validate_a1_scale,
    validate_bright_anchors,
    validate_lens_polynomial,
    validate_pole,
    warn_sky_coverage,
)
from services.allsky.fisheye import FisheyeModel
from services.allsky.pole_finder import PoleEstimate


def _make_match(alt: float, az: float, xy=(0.0, 0.0)):
    """Build one match entry in the shape _brightness_match emits."""
    return (xy, {'name': 'x', 'vmag': 3.0}, (alt, az))


# ===================================================================
# score_matches_with_spread
# ===================================================================

class TestScoreMatchesWithSpread:
    def test_empty_returns_zero(self):
        assert score_matches_with_spread([]) == 0.0

    def test_small_list_returns_raw_count(self):
        matches = [_make_match(45.0, 0.0), _make_match(45.0, 0.0)]
        assert score_matches_with_spread(matches) == 2.0

    def test_well_spread_gets_full_score(self):
        """Eight matches at 45° azimuth intervals => spread ≈ 1.0 => score ≈ n."""
        matches = [_make_match(45.0, az) for az in range(0, 360, 45)]
        s = score_matches_with_spread(matches)
        assert math.isclose(s, len(matches), rel_tol=0.05), (
            f"Spread-8 score {s} not close to raw count {len(matches)}"
        )

    def test_clustered_matches_are_halved(self):
        """10 matches all near az=120° => factor ≈ 0.5 => score ≈ 5."""
        matches = [_make_match(30.0, 118.0 + i * 0.5) for i in range(10)]
        s = score_matches_with_spread(matches)
        assert 4.5 <= s <= 6.0, (
            f"Clustered score {s} should be about half of raw count 10"
        )

    def test_spread_outscores_cluster_at_equal_count(self):
        """Spread fit beats clustered fit when both have the same count."""
        spread = [_make_match(45.0, az) for az in (0, 45, 90, 135, 180, 225, 270, 315)]
        clustered = [_make_match(45.0, 120.0 + i * 0.3) for i in range(8)]
        assert score_matches_with_spread(spread) > score_matches_with_spread(clustered)


# ===================================================================
# validate_bright_anchors
# ===================================================================

class TestValidateBrightAnchors:
    def _zenith_model(self) -> FisheyeModel:
        return FisheyeModel(
            cx=960.0, cy=540.0, a1=600.0,
            a3=0.0, a5=0.0, roll=0.0,
            axis_alt=90.0, axis_az=0.0,
            east_left=True,
        )

    def _above_horizon(self, model: FisheyeModel, positions):
        """Build above_horizon list sorted brightest first for given (alt, az)s."""
        stars = []
        for i, (alt, az) in enumerate(positions):
            stars.append(({'name': f'S{i}', 'vmag': float(i)}, alt, az))
        return stars

    def _detect_from_projection(self, model, positions, jitter=0.0, skip_first=0):
        """Synthesise detections at projected positions of `positions[skip_first:]`."""
        det = []
        for alt, az in positions[skip_first:]:
            xy = model.altaz_to_pixel(alt, az)
            if xy is None:
                continue
            dx = xy[0] + jitter
            dy = xy[1] + jitter
            det.append((dx, dy, 1000.0))
        return det

    def test_all_anchors_match(self):
        model = self._zenith_model()
        positions = [(70.0, 0.0), (60.0, 60.0), (55.0, 120.0),
                     (50.0, 200.0), (45.0, 260.0), (40.0, 320.0)]
        ah = self._above_horizon(model, positions)
        det = self._detect_from_projection(model, positions, jitter=2.0)
        ok, msg = validate_bright_anchors(model, ah, det)
        assert ok, msg
        assert '6/6' in msg

    def test_all_anchors_miss(self):
        """Bright anchors have no detections anywhere near them."""
        model = self._zenith_model()
        positions = [(70.0, 0.0), (60.0, 60.0), (55.0, 120.0),
                     (50.0, 200.0), (45.0, 260.0), (40.0, 320.0)]
        ah = self._above_horizon(model, positions)
        # Detections only at totally unrelated pixels
        det = [(10.0, 10.0, 1.0), (20.0, 20.0, 1.0),
               (30.0, 30.0, 1.0), (40.0, 40.0, 1.0)]
        ok, msg = validate_bright_anchors(model, ah, det)
        assert not ok
        assert 'missed' in msg

    def test_partial_miss_below_min_hits_rejected(self):
        """2/6 anchors matched is below min_hits=5 → rejected."""
        model = self._zenith_model()
        positions = [(70.0, 0.0), (60.0, 60.0), (55.0, 120.0),
                     (50.0, 200.0), (45.0, 260.0), (40.0, 320.0)]
        ah = self._above_horizon(model, positions)
        # Only project last 2 stars into detections (skip first 4)
        det = self._detect_from_projection(model, positions, skip_first=4)
        ok, msg = validate_bright_anchors(model, ah, det)
        assert not ok

    def test_four_of_six_rejected(self):
        """4/6 is a former-pass case — now rejected under stricter 5/6 default."""
        model = self._zenith_model()
        positions = [(70.0, 0.0), (60.0, 60.0), (55.0, 120.0),
                     (50.0, 200.0), (45.0, 260.0), (40.0, 320.0)]
        ah = self._above_horizon(model, positions)
        # Project first 4 of 6 only
        det = []
        for alt, az in positions[:4]:
            xy = model.altaz_to_pixel(alt, az)
            det.append((xy[0], xy[1], 1.0))
        ok, msg = validate_bright_anchors(model, ah, det)
        assert not ok, f"Expected 4/6 to be rejected under min_hits=5; got ok={ok} ({msg})"

    def test_five_of_six_accepted(self):
        """5/6 anchors matched is at the threshold → accepted."""
        model = self._zenith_model()
        positions = [(70.0, 0.0), (60.0, 60.0), (55.0, 120.0),
                     (50.0, 200.0), (45.0, 260.0), (40.0, 320.0)]
        ah = self._above_horizon(model, positions)
        det = []
        for alt, az in positions[:5]:
            xy = model.altaz_to_pixel(alt, az)
            det.append((xy[0], xy[1], 1.0))
        ok, msg = validate_bright_anchors(model, ah, det)
        assert ok, f"Expected 5/6 to be accepted; got ({msg})"

    def test_obstructed_install_passes_with_5_of_12(self):
        """Pier-camera obstruction: the 7 brightest stars sit behind the OTA
        (never detected), but 5 fainter-but-still-bright anchors are in clear
        sky and match. With the top-12 pool + 5-hit floor this passes, whereas
        the old top-6 pool would have judged only the 6 obstructed stars and
        rejected a perfectly good fit.
        """
        model = self._zenith_model()
        # 12 bright anchors spread across the sky (all above the 40° floor),
        # brightest first.
        positions = [
            (75.0, 0.0), (70.0, 30.0), (65.0, 70.0), (60.0, 110.0),
            (55.0, 150.0), (52.0, 190.0),            # 6 brightest: obstructed
            (50.0, 230.0), (48.0, 270.0), (46.0, 300.0),
            (44.0, 330.0), (42.0, 20.0),             # 5 of these in clear sky
            (40.0, 200.0),
        ]
        ah = self._above_horizon(model, positions)
        # Only the last 5 anchors are detected (first 7 behind the obstruction).
        det = self._detect_from_projection(model, positions, jitter=2.0, skip_first=7)
        ok, msg = validate_bright_anchors(model, ah, det)
        assert ok, f"Expected 5/12 clear-sky anchors to pass; got reject ({msg})"

    def test_skips_when_too_few_anchors_visible(self):
        """Only 2 anchors above min_alt=15° → check is skipped (ok=True)."""
        model = self._zenith_model()
        ah = [
            ({'name': 'A', 'vmag': 1.0}, 30.0, 90.0),
            ({'name': 'B', 'vmag': 2.0}, 20.0, 270.0),
            # Rest below 15°, ignored
            ({'name': 'C', 'vmag': 3.0},  5.0, 180.0),
        ]
        det = [(0.0, 0.0, 1.0)]
        ok, msg = validate_bright_anchors(model, ah, det)
        assert ok
        assert 'skipping' in msg

    def test_altitude_floor_excludes_low_altitude_anchors(self):
        """Low-altitude anchors carry no signal: even a correct fisheye model
        extrapolates poorly there (measured 46-406px on the known-good
        reference model), and the detection mask's trim zone hides the lowest
        ones entirely. The 40° floor excludes them so the well-modelled
        high-altitude anchors decide the verdict.

        Setup: 3 detected stars above 40° + 3 low stars that are never
        detected.  With the 40° floor only 3 anchors remain < min_hits=5 →
        check skipped → accept.  With an explicit low floor all 6 are
        checked, only 3 hit → reject.
        """
        model = self._zenith_model()

        # 3 well-detected stars above the 40° floor
        positions_high = [(65.0, 0.0), (50.0, 120.0), (42.0, 240.0)]
        # 3 low stars — never in detections
        positions_dead = [(25.0, 60.0), (13.0, 180.0), (10.5, 300.0)]

        ah = self._above_horizon(model, positions_high + positions_dead)
        det = self._detect_from_projection(model, positions_high, jitter=1.0)

        # Default 40° floor: 3 high-alt anchors < min_hits=5 → skipped → ok
        ok_new, msg_new = validate_bright_anchors(model, ah, det)
        assert ok_new, f"40° floor: expected skip, got reject ({msg_new})"
        assert 'skipping' in msg_new

        # Old 10° floor: 6 anchors checked, only 3 hit → 3 < min_hits=5 → reject
        ok_old, _msg_old = validate_bright_anchors(
            model, ah, det, min_alt_deg=10.0,
        )
        assert not ok_old, "10° floor should reject when low anchors are missed"

    def test_empty_detections_rejects(self):
        model = self._zenith_model()
        positions = [(70.0, 0.0), (60.0, 60.0), (55.0, 120.0),
                     (50.0, 200.0), (45.0, 260.0), (40.0, 320.0)]
        ah = self._above_horizon(model, positions)
        ok, msg = validate_bright_anchors(model, ah, [])
        assert not ok
        assert 'no detected' in msg.lower()


# ===================================================================
# Resolution-independent tolerances (F10)
# ===================================================================

class TestToleranceScaling:
    def test_reference_radius_is_unity(self):
        assert abs(tol_scale(REF_SKY_R_PX) - 1.0) < 1e-9

    def test_scales_linearly_with_radius(self):
        assert abs(tol_scale(REF_SKY_R_PX / 2) - 0.5) < 1e-9
        assert abs(tol_scale(REF_SKY_R_PX * 2) - 2.0) < 1e-9

    def test_unknown_radius_is_neutral(self):
        assert tol_scale(None) == 1.0
        assert tol_scale(0) == 1.0
        assert tol_scale(-5.0) == 1.0

    def test_anchor_max_miss_scales_with_sky_r(self):
        """A fixed pixel miss that passes at native resolution must fail when
        the same model is judged at half resolution — the tolerance halves with
        the sky radius rather than staying a fixed pixel count."""
        model = FisheyeModel(
            cx=960.0, cy=540.0, a1=600.0, a3=0.0, a5=0.0,
            roll=0.0, axis_alt=90.0, axis_az=0.0, east_left=True,
        )
        positions = [(70.0, 0.0), (60.0, 60.0), (55.0, 120.0),
                     (50.0, 200.0), (45.0, 260.0), (40.0, 320.0)]
        ah = [({'name': f'S{i}', 'vmag': float(i)}, alt, az)
              for i, (alt, az) in enumerate(positions)]
        # Each detection sits 30 px from its projected anchor (single axis).
        det = []
        for alt, az in positions:
            xy = model.altaz_to_pixel(alt, az)
            det.append((xy[0] + 30.0, xy[1], 1000.0))

        # Native: effective max_miss = 40 px → 30 px miss passes.
        ok_native, _ = validate_bright_anchors(model, ah, det, sky_r=REF_SKY_R_PX)
        assert ok_native

        # Half resolution: effective max_miss = 20 px → 30 px miss fails.
        ok_half, _ = validate_bright_anchors(model, ah, det, sky_r=REF_SKY_R_PX / 2)
        assert not ok_half


# ===================================================================
# validate_lens_polynomial
# ===================================================================

class TestValidateLensPolynomial:
    def test_default_model_accepts(self):
        """Fresh FisheyeModel has a3=0, comfortably within range."""
        ok, _msg = validate_lens_polynomial(FisheyeModel())
        assert ok

    def test_typical_real_lens_accepts(self):
        """Real fisheye lenses have modest negative a3 (e.g. -47 to -50)."""
        m = FisheyeModel(a3=-48.0)
        ok, _msg = validate_lens_polynomial(m)
        assert ok

    def test_strongly_positive_a3_rejected(self):
        """a3=+23.86 (observed spurious-fit case) must be rejected."""
        m = FisheyeModel(a3=23.86)
        ok, msg = validate_lens_polynomial(m)
        assert not ok
        assert 'a3' in msg

    def test_very_negative_a3_rejected(self):
        m = FisheyeModel(a3=A3_MIN - 1.0)
        ok, _msg = validate_lens_polynomial(m)
        assert not ok

    def test_pinned_at_bounds_rejected(self):
        """Values AT the optimiser bounds are rejected as pinned — the fit
        fought the clamp (a wrong-basin model shipped with a3=19.99999997,
        inside the range but pinned)."""
        ok_min, msg_min = validate_lens_polynomial(FisheyeModel(a3=A3_MIN))
        ok_max, msg_max = validate_lens_polynomial(FisheyeModel(a3=A3_MAX))
        assert not ok_min and 'pinned' in msg_min
        assert not ok_max and 'pinned' in msg_max

    def test_shipped_wrong_basin_a3_rejected(self):
        """The exact a3 of the 2026-06-23 incident model must be rejected."""
        ok, msg = validate_lens_polynomial(FisheyeModel(a3=19.99999999975631))
        assert not ok
        assert 'pinned' in msg

    def test_just_inside_pin_epsilon_accepted(self):
        ok_min, _ = validate_lens_polynomial(FisheyeModel(a3=A3_MIN + 1.0))
        ok_max, _ = validate_lens_polynomial(FisheyeModel(a3=A3_MAX - 1.0))
        assert ok_min and ok_max


# ===================================================================
# validate_a1_scale — plate scale vs measured sky circle
# ===================================================================

# Parameters of the 2026-06-23 incident model (wrong-basin fit that shipped)
# and its frame geometry: 2628px frame, fisheye circle filling it, so the
# trimmed sky radius is ~0.85 * 1314.
_INCIDENT_A1 = 480.5981324229242
_INCIDENT_SKY_R = 1314.0 * 0.85


class TestValidateA1Scale:
    def test_incident_model_rejected(self):
        """a1 at ~0.57x the sky-circle-implied scale must be rejected."""
        ok, msg = validate_a1_scale(FisheyeModel(a1=_INCIDENT_A1), _INCIDENT_SKY_R)
        assert not ok
        assert 'plate scale' in msg or 'wrong' in msg

    def test_known_good_model_accepted(self):
        """The reference rig's known-good a1 (ratio ~1.09) must pass."""
        ok, msg = validate_a1_scale(FisheyeModel(a1=1277.18), 1563.0)
        assert ok, msg

    def test_unknown_sky_r_skips(self):
        ok, msg = validate_a1_scale(FisheyeModel(a1=100.0), None)
        assert ok
        assert 'skipped' in msg

    def test_double_scale_rejected(self):
        ok, _ = validate_a1_scale(FisheyeModel(a1=2400.0), 1563.0)
        assert not ok


# ===================================================================
# validate_pole — measured celestial pole as an admission gate
# ===================================================================

def _pole(x=1718.0, y=646.0, east_left=True):
    return PoleEstimate(x=x, y=y, east_left=east_left, sign=-1,
                        n_frames=12, span_minutes=60.0, drift_px=3.3,
                        flux=3600.0, sign_votes=(300, 1700))


def _reference_model() -> FisheyeModel:
    """The known-good multi-image model of the reference rig."""
    return FisheyeModel(
        cx=1532.277480022239, cy=1748.2333782530266,
        a1=1277.1768448604173, a3=-47.565326396085396, a5=-58.919100634659344,
        roll=1.2213944731235367, axis_alt=84.49275734968984,
        axis_az=280.49549589886345, east_left=True,
    )


class TestValidatePole:
    LAT = 38.9717

    def test_no_estimate_skips(self):
        ok, msg = validate_pole(_reference_model(), self.LAT, None)
        assert ok
        assert 'skipped' in msg

    def test_known_good_model_passes_measured_pole(self):
        """The reference model carries ~70px of regional error at the pole —
        the generous tolerance must still accept it."""
        ok, msg = validate_pole(_reference_model(), self.LAT, _pole(),
                                sky_r=1563.0)
        assert ok, msg

    def test_mirrored_model_rejected(self):
        m = _reference_model()
        m.east_left = False
        ok, msg = validate_pole(m, self.LAT, _pole(), sky_r=1563.0)
        assert not ok
        assert 'east_left' in msg or 'mirror' in msg.lower()

    def test_wrong_basin_position_rejected(self):
        """The incident model (scaled to the reference frame) puts the pole
        hundreds of pixels from its measured position."""
        s = 3552.0 / 2628.0
        m = FisheyeModel(
            cx=1154.452083684348 * s, cy=1322.8234646056446 * s,
            a1=_INCIDENT_A1 * s, a3=19.99999999975631 * s,
            a5=-12.349397496767505 * s, roll=-0.20656450436385085,
            axis_alt=78.18606880664784, axis_az=12.576781341950102,
            east_left=True,  # mirror fixed so the *position* check is exercised
        )
        ok, msg = validate_pole(m, self.LAT, _pole(), sky_r=1563.0)
        assert not ok
        assert 'measured position' in msg

    def test_inconclusive_sign_still_checks_position(self):
        est = _pole(east_left=None)
        m = _reference_model()
        m.east_left = False   # mirror check must be skipped when sign unknown…
        ok1, _ = validate_pole(_reference_model(), self.LAT, est, sky_r=1563.0)
        assert ok1
        # …but a mirrored model still fails on position (projects elsewhere).
        ok2, _ = validate_pole(m, self.LAT, est, sky_r=1563.0)
        assert not ok2


# ===================================================================
# warn_sky_coverage (smoke test — just make sure it doesn't raise)
# ===================================================================

class TestWarnSkyCoverage:
    def test_no_matched_stars_attr_is_safe(self):
        warn_sky_coverage(FisheyeModel())  # should not raise

    def test_clustered_stars_does_not_raise(self):
        model = FisheyeModel()
        model.matched_stars = [
            {'az': 120.0}, {'az': 121.0}, {'az': 119.0}, {'az': 122.0},
        ]
        warn_sky_coverage(model)   # logs a warning; no assert needed

    def test_spread_stars_does_not_raise(self):
        model = FisheyeModel()
        model.matched_stars = [
            {'az': az} for az in (0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0)
        ]
        warn_sky_coverage(model)
