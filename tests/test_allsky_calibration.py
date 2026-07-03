"""
Tests for services/allsky/fisheye.py and services/allsky/calibration.py.

Uses synthetic star fields so no hardware or network access is required.
"""
import math
import json
import tempfile
import os
import numpy as np
import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.allsky.fisheye import FisheyeModel


# ===================================================================
# FisheyeModel — projection
# ===================================================================

class TestFisheyeProjection:
    """Test FisheyeModel coordinate projection."""

    def _default_model(self) -> FisheyeModel:
        """Create a simple centred equidistant model (axis pointing at zenith)."""
        return FisheyeModel(
            cx=960.0, cy=540.0,
            a1=600.0, a3=0.0, a5=0.0,
            roll=0.0,
            axis_alt=90.0, axis_az=0.0,
        )

    def test_zenith_maps_to_centre(self):
        """Alt=90° (zenith) should project to the optical centre."""
        model = self._default_model()
        xy = model.altaz_to_pixel(90.0, 0.0)
        assert xy is not None
        assert abs(xy[0] - 960.0) < 2.0, f"Zenith x={xy[0]} ≠ 960"
        assert abs(xy[1] - 540.0) < 2.0, f"Zenith y={xy[1]} ≠ 540"

    def test_below_horizon_returns_none(self):
        """Alt < 0 should return None."""
        model = self._default_model()
        assert model.altaz_to_pixel(-5.0, 0.0) is None

    def test_north_is_up(self):
        """Az=0° (North) at low altitude should project above the centre (lower y)."""
        model = self._default_model()
        xy = model.altaz_to_pixel(30.0, 0.0)   # North, 30° up
        assert xy is not None
        assert xy[1] < 540.0, f"North should be above centre; y={xy[1]}"

    def test_south_is_below(self):
        """Az=180° (South) should project below the centre (higher y)."""
        model = self._default_model()
        xy_s = model.altaz_to_pixel(30.0, 180.0)
        xy_n = model.altaz_to_pixel(30.0, 0.0)
        assert xy_s is not None and xy_n is not None
        assert xy_s[1] > xy_n[1], "South should have higher y than North"

    def test_east_west_symmetric(self):
        """East (Az=90°) and West (Az=270°) should be symmetric about centre."""
        model = self._default_model()
        xy_e = model.altaz_to_pixel(30.0, 90.0)
        xy_w = model.altaz_to_pixel(30.0, 270.0)
        assert xy_e is not None and xy_w is not None
        # x should be symmetric about cx=960
        assert abs((xy_e[0] - 960.0) + (xy_w[0] - 960.0)) < 2.0

    def test_radial_distance_increases_with_altitude_decrease(self):
        """Objects at lower altitude (further from zenith) should be further from centre."""
        model = self._default_model()
        xy_70 = model.altaz_to_pixel(70.0, 0.0)
        xy_30 = model.altaz_to_pixel(30.0, 0.0)
        assert xy_70 is not None and xy_30 is not None
        r_70 = math.hypot(xy_70[0] - 960.0, xy_70[1] - 540.0)
        r_30 = math.hypot(xy_30[0] - 960.0, xy_30[1] - 540.0)
        assert r_30 > r_70, f"r(30°)={r_30:.1f} should > r(70°)={r_70:.1f}"

    def test_vectorised_matches_scalar(self):
        """altaz_array_to_pixels should give same result as scalar altaz_to_pixel."""
        model = self._default_model()
        alts = np.array([10.0, 30.0, 60.0, 80.0])
        azs  = np.array([0.0, 90.0, 180.0, 270.0])
        px_v, py_v, vis = model.altaz_array_to_pixels(alts, azs)
        for i, (alt, az) in enumerate(zip(alts, azs)):
            xy = model.altaz_to_pixel(float(alt), float(az))
            assert xy is not None
            assert abs(px_v[i] - xy[0]) < 1.0
            assert abs(py_v[i] - xy[1]) < 1.0


# ===================================================================
# FisheyeModel — JSON persistence
# ===================================================================

class TestFisheyePersistence:
    def test_save_load_roundtrip(self):
        """Save model to temp file and reload; all fields must match."""
        model = FisheyeModel(
            cx=800.0, cy=600.0, a1=550.0, a3=10.0, a5=-0.5,
            roll=0.05, axis_alt=88.0, axis_az=5.0,
            rms_residual=1.23, n_matches=45,
            calibrated_at="2024-01-15T22:30:00+00:00",
        )
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            path = f.name

        try:
            model.save(path)
            loaded = FisheyeModel.load(path)

            assert abs(loaded.cx - model.cx) < 1e-6
            assert abs(loaded.cy - model.cy) < 1e-6
            assert abs(loaded.a1 - model.a1) < 1e-6
            assert abs(loaded.a3 - model.a3) < 1e-6
            assert abs(loaded.a5 - model.a5) < 1e-8
            assert abs(loaded.roll - model.roll) < 1e-6
            assert loaded.n_matches == model.n_matches
            assert abs(loaded.rms_residual - model.rms_residual) < 1e-6
        finally:
            os.unlink(path)

    def test_try_load_missing_file_returns_none(self):
        """try_load() should return None for a non-existent path."""
        result = FisheyeModel.try_load('/nonexistent/path/model.json')
        assert result is None

    def test_is_valid_requires_matches_and_positive_a1(self):
        """is_valid() should be False if n_matches < 5 or a1 <= 0."""
        m_bad = FisheyeModel(n_matches=3, a1=500.0)
        m_ok  = FisheyeModel(n_matches=25, a1=500.0)
        assert not m_bad.is_valid()
        assert m_ok.is_valid()


# ===================================================================
# CalibrationError (graceful degradation)
# ===================================================================

class TestMultiCalibrateRegularization:
    """Multi-image refinement must keep the radial polynomial physical on
    obstructed installs, where clustered coverage + a stale seed used to drive
    a3 to its bound (the recurring 'a3=25.0 outside plausible range' failure).
    """

    def _obstructed(self, x, y):
        # Telescope/mount blob + dome-rim ring, mirroring a pier-camera frame.
        if 1150 < x < 1900 and 1150 < y < 2100:
            return True
        return math.hypot(x - 1137, y - 1306) > 980

    def _frame(self, true_model, dt):
        from services.allsky.catalogs import get_bright_stars
        from services.allsky.coords import radec_to_altaz
        rng = np.random.default_rng(7)
        above, detected = [], []
        for s in get_bright_stars(max_mag=4.0):
            alt, az = radec_to_altaz(s['ra_deg'], s['dec_deg'], 31.33, -100.46, dt)
            alt, az = float(alt), float(az)
            if alt <= 3.0:
                continue
            above.append((s, alt, az))
            if alt < 12:
                continue
            xy = true_model.altaz_to_pixel(alt, az)
            if xy is None or self._obstructed(*xy):
                continue
            detected.append((xy[0] + rng.normal(), xy[1] + rng.normal(), 1000.0))
        above.sort(key=lambda t: t[0]['vmag'])
        return {'dt': dt, 'detected': detected, 'above_horizon': above,
                'sky_cx': 1137.0, 'sky_cy': 1306.0, 'sky_r': 968.0,
                'image_width': 2628, 'image_height': 2628}

    def test_cold_start_bootstrap_no_seed(self, monkeypatch):
        """With no prior model (fresh install, any site), the cross-frame
        orientation search + joint fit must recover a valid model from cold.
        The grid is narrowed here for speed; the full-grid discrimination is
        exercised offline."""
        pytest.importorskip('scipy')
        from datetime import datetime, timezone, timedelta
        from services.allsky import multi_calibrate as MC
        from services.allsky.calibration_validate import validate_lens_polynomial

        # Narrow the coarse grid to a focused window around the true pose so the
        # test runs fast while still exercising search -> top-k -> fit -> gate.
        monkeypatch.setattr(MC, 'ORIENT_AXIS_ALT', range(75, 91, 5))
        monkeypatch.setattr(MC, 'ORIENT_AXIS_AZ', range(0, 60, 15))
        monkeypatch.setattr(MC, 'ORIENT_ROLL_DEG', range(-45, 15, 15))

        true_model = FisheyeModel(
            cx=1137.44, cy=1306.0, a1=643.39, a3=1.30, a5=-7.73,
            roll=-0.321, axis_alt=82.55, axis_az=16.90, east_left=True)
        base = datetime(2026, 6, 22, 5, 30, tzinfo=timezone.utc)
        frames = [self._frame(true_model, base + timedelta(minutes=20 * i))
                  for i in range(5)]

        model = MC.refine_from_detections(frames, None, max_residual_px=20.0)
        ok, msg = validate_lens_polynomial(model)
        assert ok, msg
        # Recovered orientation should be close to truth.
        assert abs(model.axis_alt - 82.55) < 6.0, f"axis_alt={model.axis_alt:.1f}"
        assert model.east_left is True

    def test_stale_seed_keeps_a3_physical(self):
        """A ~5° stale seed over a clustered/obstructed sky must not let a3 run
        to its bound — the ridge prior pulls it back into the physical range."""
        pytest.importorskip('scipy')
        import copy
        from datetime import datetime, timezone, timedelta
        from services.allsky import multi_calibrate as MC
        from services.allsky.calibration_validate import (
            tol_scale, validate_lens_polynomial, A3_MIN, A3_MAX)

        true_model = FisheyeModel(
            cx=1137.44, cy=1306.0, a1=643.39, a3=1.30, a5=-7.73,
            roll=-0.321, axis_alt=82.55, axis_az=16.90, east_left=True)
        base = datetime(2026, 6, 22, 5, 30, tzinfo=timezone.utc)
        frames = [self._frame(true_model, base + timedelta(minutes=20 * i))
                  for i in range(4)]

        stale = copy.deepcopy(true_model)
        stale.roll += math.radians(3.0)
        stale.axis_az += 4.0
        stale.axis_alt -= 2.0
        stale.a1 += 15.0

        # Drive the joint fit directly so the polynomial invariant is checked
        # regardless of whether the orientation happens to clear the anchor gate.
        ts = tol_scale(968.0)
        matches = MC._build_all_matches(frames, stale, tol_px=50.0 * ts, min_per_image=4)
        model, _rms = MC._joint_iterative_fit(
            matches, frames, stale, 4, 20, 20.0, tol_scale_factor=ts)

        ok, msg = validate_lens_polynomial(model)
        assert A3_MIN <= model.a3 <= A3_MAX, (
            f"a3={model.a3:.2f} escaped physical range [{A3_MIN}, {A3_MAX}]")
        assert ok, msg


class TestGuidedCalibration:
    """Anchor-assisted (user-clicked) calibration: exact star<->pixel pairs must
    recover a correct model on any orientation, the dependable cold-start path."""

    def _true_model(self):
        return FisheyeModel(
            cx=1137.0, cy=1306.0, a1=643.0, a3=1.3, a5=-7.7,
            roll=-0.321, axis_alt=82.5, axis_az=16.9, east_left=True)

    def _anchors(self, true_model, lat, lon, dt, n=6):
        """Project the n brightest well-spread above-horizon stars to pixels."""
        from services.allsky.catalogs import get_bright_stars
        from services.allsky.coords import radec_to_altaz
        out = []
        for s in get_bright_stars(max_mag=2.5):
            alt, az = radec_to_altaz(s['ra_deg'], s['dec_deg'], lat, lon, dt)
            if float(alt) < 25:
                continue
            xy = true_model.altaz_to_pixel(float(alt), float(az))
            if xy is None:
                continue
            out.append((xy[0], xy[1], s['ra_deg'], s['dec_deg'], float(az)))
        # spread across azimuth: sort by az and sample evenly
        out.sort(key=lambda t: t[4])
        if len(out) > n:
            idx = np.linspace(0, len(out) - 1, n).round().astype(int)
            out = [out[i] for i in dict.fromkeys(idx.tolist())]
        return [(x, y, ra, dec) for x, y, ra, dec, _az in out]

    def test_recovers_known_model_from_anchors(self):
        pytest.importorskip('scipy')
        from datetime import datetime, timezone
        from services.allsky.guided_calibration import calibrate_from_anchors

        true_model = self._true_model()
        lat, lon = 31.33, -100.46
        dt = datetime(2026, 6, 22, 6, 0, tzinfo=timezone.utc)
        anchors = self._anchors(true_model, lat, lon, dt, n=6)
        assert len(anchors) >= 4

        m = calibrate_from_anchors(
            anchors, lat, lon, dt,
            sky_cx=1137.0, sky_cy=1306.0, sky_radius=968.0,
            image_width=2628, image_height=2628)

        assert m.rms_residual < 3.0, f"RMS {m.rms_residual:.1f}px"
        assert m.east_left is True
        assert abs(m.a1 - 643.0) < 25
        assert abs(m.axis_alt - 82.5) < 3.0
        # azimuth difference modulo 360
        daz = abs(((m.axis_az - 16.9 + 180) % 360) - 180)
        assert daz < 5.0, f"axis_az off by {daz:.1f}"

    def test_too_few_anchors_raises(self):
        pytest.importorskip('scipy')
        from datetime import datetime, timezone
        from services.allsky.guided_calibration import calibrate_from_anchors, MIN_ANCHORS
        from services.allsky.calibration import CalibrationError

        true_model = self._true_model()
        lat, lon = 31.33, -100.46
        dt = datetime(2026, 6, 22, 6, 0, tzinfo=timezone.utc)
        anchors = self._anchors(true_model, lat, lon, dt, n=MIN_ANCHORS - 1)[:MIN_ANCHORS - 1]
        with pytest.raises(CalibrationError, match="at least"):
            calibrate_from_anchors(anchors, lat, lon, dt, 1137.0, 1306.0, 968.0)

    def test_free_centre_recovers_offset_sky_circle(self):
        """With >=6 anchors the optical centre joins the fit: a sky-circle
        estimate 30px off the true centre must no longer put an RMS floor
        under perfect identifications."""
        pytest.importorskip('scipy')
        from datetime import datetime, timezone
        from services.allsky.guided_calibration import calibrate_from_anchors

        true_model = self._true_model()
        lat, lon = 31.33, -100.46
        dt = datetime(2026, 6, 22, 6, 0, tzinfo=timezone.utc)
        anchors = self._anchors(true_model, lat, lon, dt, n=7)
        assert len(anchors) >= 6

        m = calibrate_from_anchors(
            anchors, lat, lon, dt,
            sky_cx=1137.0 + 30.0, sky_cy=1306.0 - 30.0, sky_radius=968.0,
            image_width=2628, image_height=2628)
        assert m.rms_residual < 4.0, f"RMS {m.rms_residual:.1f}px"
        assert abs(m.cx - 1137.0) < 20.0
        assert abs(m.cy - 1306.0) < 20.0

    def test_bad_anchor_excluded_and_named(self):
        """One mis-clicked anchor among six must not sink the solve: the
        rescue path excludes it (or reassigns it), names it in the note,
        and still recovers the true model from the rest."""
        pytest.importorskip('scipy')
        from datetime import datetime, timezone
        from services.allsky.guided_calibration import calibrate_from_anchors

        true_model = self._true_model()
        lat, lon = 31.33, -100.46
        dt = datetime(2026, 6, 22, 6, 0, tzinfo=timezone.utc)
        base = self._anchors(true_model, lat, lon, dt, n=6)
        named = [(x, y, ra, dec, f"Star{i}") for i, (x, y, ra, dec)
                 in enumerate(base)]
        # Corrupt one anchor's click by 200px.
        x, y, ra, dec, name = named[2]
        named[2] = (x + 200.0, y, ra, dec, name)

        m = calibrate_from_anchors(named, lat, lon, dt, 1137.0, 1306.0, 968.0)
        note = getattr(m, 'guided_note', '')
        assert "Star2" in note
        assert m.rms_residual < 5.0, f"RMS {m.rms_residual:.1f}px"
        assert abs(m.a1 - 643.0) < 25

    def test_unrescuable_set_still_raises_with_residuals(self):
        """When too many anchors are bad for any subset to reach consensus,
        the solve must still fail loudly with per-anchor residuals — the
        rescue must not accept a garbage fit."""
        pytest.importorskip('scipy')
        from datetime import datetime, timezone
        from services.allsky.guided_calibration import calibrate_from_anchors
        from services.allsky.calibration import CalibrationError

        true_model = self._true_model()
        lat, lon = 31.33, -100.46
        dt = datetime(2026, 6, 22, 6, 0, tzinfo=timezone.utc)
        base = self._anchors(true_model, lat, lon, dt, n=5)
        named = [(x, y, ra, dec, f"Star{i}") for i, (x, y, ra, dec)
                 in enumerate(base)]
        # Two badly corrupted clicks out of five: any 4-anchor subset keeps
        # at least one, so no exclusion can reach a clean consensus.
        x, y, ra, dec, name = named[1]
        named[1] = (x + 300.0, y - 250.0, ra, dec, name)
        x, y, ra, dec, name = named[3]
        named[3] = (x - 280.0, y + 320.0, ra, dec, name)

        with pytest.raises(CalibrationError) as exc:
            calibrate_from_anchors(named, lat, lon, dt, 1137.0, 1306.0, 968.0)
        msg = str(exc.value)
        assert "px" in msg and "Star" in msg

    def test_misidentified_anchor_reassigned(self):
        """A correct click under a wrong star name (e.g. Mizar clicked but
        labeled Alkaid — the 2026-07-02 field failure) must be reassigned to
        the star the click actually sits on, using all anchors."""
        pytest.importorskip('scipy')
        from datetime import datetime, timezone
        from services.allsky.catalogs import get_bright_stars
        from services.allsky.coords import radec_to_altaz
        from services.allsky.guided_calibration import calibrate_from_anchors

        true_model = self._true_model()
        lat, lon = 31.33, -100.46
        dt = datetime(2026, 6, 22, 6, 0, tzinfo=timezone.utc)

        cands = []
        for s in get_bright_stars(max_mag=2.5):
            alt, az = radec_to_altaz(s['ra_deg'], s['dec_deg'], lat, lon, dt)
            if float(alt) < 25:
                continue
            xy = true_model.altaz_to_pixel(float(alt), float(az))
            if xy is None:
                continue
            cands.append((xy[0], xy[1], s['ra_deg'], s['dec_deg'],
                          s.get('name') or 'unnamed', float(az)))
        cands.sort(key=lambda t: t[5])
        idx = np.linspace(0, len(cands) - 1, 8).round().astype(int)
        picked = [cands[i] for i in dict.fromkeys(idx.tolist())]
        assert len(picked) >= 8
        anchors = [(x, y, ra, dec, nm) for x, y, ra, dec, nm, _az
                   in picked[:7]]
        wrong = picked[7]
        # Anchor 2 keeps its true click pixel but is labeled as `wrong`.
        x, y, _ra, _dec, name = anchors[2]
        anchors[2] = (x, y, wrong[2], wrong[3], wrong[4])

        m = calibrate_from_anchors(anchors, lat, lon, dt,
                                   1137.0, 1306.0, 968.0)
        note = getattr(m, 'guided_note', '')
        assert "actually" in note and wrong[4] in note
        assert m.n_matches == 7      # reassigned, not dropped
        assert m.rms_residual < 3.0, f"RMS {m.rms_residual:.1f}px"
        assert abs(m.a1 - 643.0) < 25


class TestFitSeedFeasibility:
    """A grid/triangle hypothesis can seed _iterative_fit outside its bounds
    (the triangle orientation extraction admits axis_alt >= 45; roll/axis_az
    come back unwrapped). least_squares('trf') rejects an infeasible x0
    outright, which used to abort refinement of a correct hypothesis
    (2026-07-02 field failure: 'Initial guess is outside of provided
    bounds'). The seed must be wrapped/clamped instead."""

    def test_out_of_bounds_seed_is_clamped_not_fatal(self):
        pytest.importorskip('scipy')
        from datetime import datetime, timezone
        from services.allsky.calibration import _iterative_fit

        true_model = FisheyeModel(
            cx=1137.0, cy=1306.0, a1=643.0, a3=1.3, a5=-7.7,
            roll=-0.321, axis_alt=82.5, axis_az=16.9, east_left=True)

        rng = np.random.default_rng(7)
        detected, catalog, matches = [], [], []
        for i in range(40):
            alt = float(rng.uniform(20, 85))
            az = float(rng.uniform(0, 360))
            xy = true_model.altaz_to_pixel(alt, az)
            if xy is None:
                continue
            star = {'name': f'S{i}', 'vmag': 1.0 + 0.05 * i,
                    'ra_deg': 0.0, 'dec_deg': 0.0}
            detected.append((xy[0], xy[1], 1000.0))
            catalog.append((star, alt, az))
            matches.append(((xy[0], xy[1]), star, (alt, az)))
        assert len(matches) >= 15

        # Same orientation as truth, expressed infeasibly: roll a full turn
        # low, axis_az a full turn high, axis_alt below the 60-deg bound.
        seed = FisheyeModel(
            cx=1137.0, cy=1306.0, a1=643.0, a3=1.3, a5=-7.7,
            roll=-0.321 - 2 * np.pi, axis_alt=55.0, axis_az=376.9,
            east_left=True)
        model, rms = _iterative_fit(
            matches, seed, 31.33, -100.46,
            datetime(2026, 6, 22, 6, 0, tzinfo=timezone.utc),
            catalog, detected, min_matches=10, max_residual=15.0)

        assert 60.0 <= model.axis_alt <= 90.0
        assert rms < 5.0, f"refinement did not run/converge: RMS {rms:.1f}px"


class TestCalibrationError:
    def test_insufficient_stars_raises(self):
        """Calibration should raise CalibrationError if too few stars detected."""
        pytest.importorskip('scipy')
        from services.allsky.calibration import calibrate, CalibrationError
        from PIL import Image as PILImage

        # All-black image → no stars
        blank = PILImage.new('RGB', (1920, 1080), color=(0, 0, 0))
        with pytest.raises(CalibrationError, match="star"):
            calibrate(blank, lat_deg=51.5, lon_deg=-0.1, min_matches=20)

    def test_synthetic_bright_stars(self):
        """
        Plant synthetic Gaussian star blobs at known pixel positions and verify
        that detection finds most of them. Does NOT run the full fit.
        """
        from services.allsky.star_centroid import detect_stars
        import numpy as np
        from PIL import Image as PILImage

        rng = np.random.default_rng(42)
        img_arr = np.zeros((1080, 1920), dtype=np.uint8)

        # Plant 30 Gaussian blobs
        planted_positions = []
        for _ in range(30):
            x = int(rng.integers(50, 1870))
            y = int(rng.integers(50, 1030))
            # 2D Gaussian
            ys, xs = np.mgrid[max(0, y-8):min(1080, y+9),
                               max(0, x-8):min(1920, x+9)]
            blob = 200 * np.exp(-((xs - x)**2 + (ys - y)**2) / (2 * 2.5**2))
            img_arr[ys, xs] = np.clip(img_arr[ys, xs] + blob, 0, 255).astype(np.uint8)
            planted_positions.append((x, y))

        img = PILImage.fromarray(img_arr, mode='L')
        detected = detect_stars(img, max_stars=50, border_px=15,
                               sky_cx=960, sky_cy=540, sky_radius=1000)

        # Should find at least 20 of the 30 planted stars
        assert len(detected) >= 20, f"Found {len(detected)} of 30 planted stars"

        # Each detected position should be within 5px of a planted position
        matched = 0
        for dx, dy, dflux in detected:
            for px, py in planted_positions:
                if math.hypot(dx - px, dy - py) < 5.0:
                    matched += 1
                    break
        assert matched >= 15, f"Only {matched}/30 detected stars match planted positions"
