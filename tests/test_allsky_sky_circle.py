"""
Tests for services/allsky/star_centroid.py sky-circle estimation.

Covers (issue #10):
  - exposure invariance: a fixed camera's sky circle must not change with
    the frame's brightness, down to the ~2 ADU sky median of a correctly
    exposed linear all-sky frame;
  - the failure path is reported, not disguised: measure_sky_circle()
    returns None, estimate_sky_circle() logs a WARNING and returns the
    documented frame-centred fallback.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.allsky import star_centroid as sc

pytest.importorskip('cv2')


# ---------------------------------------------------------------------------
# Synthetic all-sky frame
# ---------------------------------------------------------------------------

TRUE_CX, TRUE_CY, TRUE_R = 412.0, 396.0, 330.0


def _fisheye_frame(size: int = 800, sky: float = 120.0, seed: int = 0) -> np.ndarray:
    """Illuminated disc with radial vignetting, noise, stars and a pier shadow
    on black corners, as float32 in 8-bit units (not yet quantised)."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    rr = np.hypot(xx - TRUE_CX, yy - TRUE_CY)
    inside = rr <= TRUE_R
    vignette = 1.0 - 0.5 * (rr / TRUE_R) ** 2
    img = np.where(inside, sky * vignette, 0.0).astype(np.float32)
    # Pier: a dark wedge from the centre out to the rim.
    ang = np.degrees(np.arctan2(yy - TRUE_CY, xx - TRUE_CX))
    img[(np.abs(ang - 60.0) < 8.0) & inside] *= 0.05
    # Stars: 150 point sources of varied brightness.
    for _ in range(150):
        theta = rng.uniform(0, 2 * np.pi)
        rad = rng.uniform(0, TRUE_R * 0.95)
        x, y = int(TRUE_CX + rad * np.cos(theta)), int(TRUE_CY + rad * np.sin(theta))
        img[y - 1:y + 2, x - 1:x + 2] += rng.uniform(40, 200)
    img += rng.normal(0.0, 3.0, img.shape).astype(np.float32)
    return np.clip(img, 0, None)


def _quantise(img: np.ndarray, scale: float) -> np.ndarray:
    return np.clip(np.round(img * scale), 0, 255).astype(np.uint8)


@pytest.fixture(scope='module')
def synthetic_frame():
    return _fisheye_frame()


# ---------------------------------------------------------------------------
# Exposure invariance
# ---------------------------------------------------------------------------

class TestExposureInvariance:

    def test_bright_frame_recovers_true_circle(self, synthetic_frame):
        cx, cy, r = sc.measure_sky_circle(_quantise(synthetic_frame, 1.0))
        assert abs(cx - TRUE_CX) < 6
        assert abs(cy - TRUE_CY) < 6
        # Returned radius is the trimmed one (15% inward).
        assert abs(r - TRUE_R * 0.85) < TRUE_R * 0.04

    @pytest.mark.parametrize('scale', [0.5, 0.2, 0.1, 0.05, 0.02])
    def test_radius_stable_under_brightness_scaling(self, synthetic_frame, scale):
        """The reported failure: consecutive frames from a fixed camera read
        569 / 964 / 1563 px purely from exposure. Scaling the same frame
        must return the same circle, and never the fallback."""
        ref = sc.measure_sky_circle(_quantise(synthetic_frame, 1.0))
        got = sc.measure_sky_circle(_quantise(synthetic_frame, scale))
        assert got is not None, f"fell back at x{scale}"
        assert abs(got[2] - ref[2]) < ref[2] * 0.04, f"x{scale}: {got[2]:.0f} vs {ref[2]:.0f}"
        assert abs(got[0] - ref[0]) < 6 and abs(got[1] - ref[1]) < 6

    def test_linear_frame_with_2_adu_sky_median(self, synthetic_frame):
        """A correctly exposed linear all-sky frame has a sky median near
        2/255 (issue #10 log). That is x0.02 of this synthetic frame, which
        leaves only a handful of grey levels — still measurable."""
        img = _quantise(synthetic_frame, 2.0 / 120.0)
        assert 1 <= np.median(img[img > 0]) <= 3
        ref = sc.measure_sky_circle(_quantise(synthetic_frame, 1.0))
        got = sc.measure_sky_circle(img)
        assert got is not None
        assert abs(got[2] - ref[2]) < ref[2] * 0.05


# ---------------------------------------------------------------------------
# Honest failure path
# ---------------------------------------------------------------------------

class TestFailurePath:

    def test_measure_returns_none_on_black_frame(self):
        assert sc.measure_sky_circle(np.zeros((600, 800), np.uint8)) is None

    def test_measure_returns_none_on_unreadable_input(self):
        assert sc.measure_sky_circle(object()) is None

    def test_estimate_falls_back_and_warns(self, monkeypatch):
        warnings = []
        monkeypatch.setattr(sc.log, 'warning', lambda m: warnings.append(m))
        cx, cy, r = sc.estimate_sky_circle(np.zeros((600, 800), np.uint8))
        assert (cx, cy, r) == sc.fallback_sky_circle(800, 600)
        assert len(warnings) == 1
        assert 'NOT measured' in warnings[0]
        assert 'fallback' in warnings[0]

    def test_estimate_does_not_warn_on_success(self, monkeypatch, synthetic_frame):
        warnings = []
        monkeypatch.setattr(sc.log, 'warning', lambda m: warnings.append(m))
        est = sc.estimate_sky_circle(_quantise(synthetic_frame, 1.0))
        assert est == sc.measure_sky_circle(_quantise(synthetic_frame, 1.0))
        assert warnings == []

    def test_fallback_is_the_documented_assumption(self):
        """The fallback radius on a 3552 px frame is 1563 px — numerically
        the same as REF_SKY_R_PX. That coincidence hid a total failure as a
        reference-scale measurement (issue #10); the WARNING above and the
        None from measure_sky_circle() are what now tell them apart."""
        from services.allsky.calibration_validate import REF_SKY_R_PX
        cx, cy, r = sc.fallback_sky_circle(3552, 3552)
        assert (cx, cy) == (1776.0, 1776.0)
        assert r == pytest.approx(1776.0 * sc.SKY_CIRCLE_FALLBACK_FRACTION)
        assert r == pytest.approx(REF_SKY_R_PX, abs=0.5)


# ---------------------------------------------------------------------------
# Real reference frame (skipped when sample_images is absent)
# ---------------------------------------------------------------------------

_FRAME = os.path.join(os.path.dirname(__file__), '..', 'sample_images',
                      'lum_20260116_021511.fits')


@pytest.fixture(scope='module')
def reference_frame():
    astro = pytest.importorskip('astropy.io.fits')
    if not os.path.exists(_FRAME):
        pytest.skip('sample_images reference frame not present')
    with astro.open(_FRAME) as hdu:
        data = np.array(hdu[0].data)
    return sc.percentile_stretch(data)


class TestReferenceFrame:

    def test_reference_radius_is_measured_not_fallback(self, reference_frame):
        """Guards the effective tolerance scale: the anchor-gate parameters
        were validated with this frame reading ~1386 px (tol_scale ~0.89)."""
        got = sc.measure_sky_circle(reference_frame)
        assert got is not None
        assert abs(got[2] - 1386.0) < 1386.0 * 0.02

    @pytest.mark.parametrize('scale', [0.2, 0.1, 0.05])
    def test_reference_radius_stable_when_underexposed(self, reference_frame, scale):
        """Before the fix: x0.2 -> 1285, x0.1 -> 1255, x0.05 -> fallback 1563."""
        ref = sc.measure_sky_circle(reference_frame)
        dark = np.clip(reference_frame.astype(np.float32) * scale, 0, 255).astype(np.uint8)
        got = sc.measure_sky_circle(dark)
        assert got is not None, f"fell back at x{scale}"
        assert abs(got[2] - ref[2]) < ref[2] * 0.04, f"x{scale}: {got[2]:.0f} vs {ref[2]:.0f}"
