"""Tests for services.allsky.pole_finder — synthetic rotating star fields.

Geometry mirrors the reference rig (3552px frame, pole ~1120px from the
circle centre) so tolerances exercise the real scales. SKY_R = 1563 is
REF_SKY_R_PX — the tolerance reference every gate was tuned at — which is
the estimator's frame-centred FALLBACK (0.88 x half-frame), not a measured
radius; the estimator reads ~1330–1390 px on the reference frames. The
default stays at 1563 so these tests keep asserting at the tuned scale;
`make_frames(sky_r=...)` exercises the measured scale explicitly.
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from services.allsky.calibration_validate import SKY_TRIM_FRACTION
from services.allsky.pole_finder import (
    MIN_FRAMES,
    MIN_SPAN_MINUTES,
    POLARIS_POLAR_DEG,
    SIDEREAL_DEG_PER_MIN,
    PoleEstimate,
    find_pole,
    predicted_polaris_arc_px,
)

SKY_CX, SKY_CY, SKY_R = 1776.0, 1776.0, 1563.0
MEASURED_SKY_R = 1386.0
POLE = (1700.0, 650.0)
T0 = datetime(2026, 1, 16, 8, 0, 0, tzinfo=timezone.utc)
NOISE_PX = 0.3   # realistic sub-pixel centroid noise


def _rotate_about(x, y, cx, cy, ang):
    c, s = np.cos(ang), np.sin(ang)
    dx, dy = x - cx, y - cy
    return cx + c * dx - s * dy, cy + s * dx + c * dy


def make_frames(
    n_frames=12,
    span_min=66.0,
    sign=-1,
    with_polaris=True,
    n_field=40,
    contaminants=(),
    seed=42,
    sky_r=SKY_R,
    polaris_flux=4000.0,
):
    """Synthetic detection buffer: field stars arc around POLE at the sidereal
    rate with direction `sign`; optional Polaris (bright, orbiting the pole
    at its 0.65° radius — 13.3px at sky_r 1563); optional contaminants as
    (x, y, flux, drift_px_over_window) tuples drifting along +x."""
    rng = np.random.default_rng(seed)
    polaris_r = POLARIS_POLAR_DEG * (sky_r / (1.0 - SKY_TRIM_FRACTION)) / 90.0
    radii = rng.uniform(200, 1300, n_field)
    phases = rng.uniform(0, 2 * np.pi, n_field)
    fluxes = rng.uniform(300, 1500, n_field)

    frames = []
    for k in range(n_frames):
        t_min = span_min * k / (n_frames - 1)
        dt = T0 + timedelta(minutes=t_min)
        theta = sign * np.radians(SIDEREAL_DEG_PER_MIN * t_min)
        det = []
        for r, ph, fl in zip(radii, phases, fluxes):
            x = POLE[0] + r * np.cos(ph)
            y = POLE[1] + r * np.sin(ph)
            # Only keep stars inside the sky circle for realism.
            x, y = _rotate_about(x, y, POLE[0], POLE[1], theta)
            if np.hypot(x - SKY_CX, y - SKY_CY) > sky_r - 30:
                continue
            det.append((x + rng.normal(0, NOISE_PX),
                        y + rng.normal(0, NOISE_PX), fl))
        if with_polaris:
            px = POLE[0] + polaris_r * np.cos(0.4)
            py = POLE[1] + polaris_r * np.sin(0.4)
            px, py = _rotate_about(px, py, POLE[0], POLE[1], theta)
            det.append((px + rng.normal(0, NOISE_PX),
                        py + rng.normal(0, NOISE_PX), polaris_flux))
        for (cx, cy, cfl, cdrift) in contaminants:
            frac = k / (n_frames - 1)
            det.append((cx + cdrift * frac + rng.normal(0, NOISE_PX),
                        cy + rng.normal(0, NOISE_PX), cfl))
        frames.append({
            'dt': dt, 'detected': det,
            'sky_cx': SKY_CX, 'sky_cy': SKY_CY, 'sky_r': sky_r,
        })
    return frames


def tracking_light(x=2200.0, y=1500.0, flux=12000.0, arc_multiple=1.0,
                   span_min=66.0, sky_r=SKY_R):
    """A light on a sidereal-tracking mount: drifts a Polaris-like arc over
    the window, so the drift band cannot reject it. Default flux is 3x
    Polaris — brightness alone would pick it."""
    return (x, y, flux, arc_multiple * predicted_polaris_arc_px(sky_r, span_min))


class TestFindPole:
    def test_finds_polaris_position_sign_and_mirror(self):
        est = find_pole(make_frames(), lat_deg=39.0)
        assert isinstance(est, PoleEstimate)
        # Polaris orbits 13px from the pole; its mean position is the estimate.
        assert np.hypot(est.x - POLE[0], est.y - POLE[1]) < 20.0
        assert est.sign == -1
        assert est.east_left is True

    def test_opposite_rotation_gives_opposite_mirror(self):
        est = find_pole(make_frames(sign=+1), lat_deg=39.0)
        assert est is not None
        assert est.sign == +1
        assert est.east_left is False

    def test_southern_hemisphere_returns_none(self):
        assert find_pole(make_frames(), lat_deg=-33.0) is None

    def test_short_span_returns_none(self):
        frames = make_frames(span_min=MIN_SPAN_MINUTES - 10)
        assert find_pole(frames, lat_deg=39.0) is None

    def test_too_few_frames_returns_none(self):
        frames = make_frames(n_frames=MIN_FRAMES - 1)
        assert find_pole(frames, lat_deg=39.0) is None

    def test_edge_light_not_chosen_as_pole(self):
        # A very bright, perfectly static light at the sky-circle edge
        # (the classic equipment LED) must not out-rank Polaris.
        led = (SKY_CX + (SKY_R - 20), SKY_CY, 25000.0, 0.0)
        est = find_pole(make_frames(contaminants=[led]), lat_deg=39.0)
        assert est is not None
        assert np.hypot(est.x - POLE[0], est.y - POLE[1]) < 20.0

    def test_moving_ota_light_not_chosen_as_pole(self):
        # Bright light on a slowly moving telescope: drifts far more than the
        # predicted Polaris arc over the window -> outside the drift band.
        ota = (2200.0, 1500.0, 18000.0, 25.0)
        est = find_pole(make_frames(contaminants=[ota]), lat_deg=39.0)
        assert est is not None
        assert np.hypot(est.x - POLE[0], est.y - POLE[1]) < 20.0

    def test_no_polaris_returns_none(self):
        # Static edge light only, no true pole star: nothing satisfies the
        # drift band, so no pole is claimed.
        led = (SKY_CX + (SKY_R - 20), SKY_CY, 25000.0, 0.0)
        est = find_pole(make_frames(with_polaris=False, contaminants=[led]),
                        lat_deg=39.0)
        assert est is None

    def test_works_at_measured_sky_radius(self):
        # The estimator reads ~1386px on the reference frames, not 1563.
        est = find_pole(make_frames(sky_r=MEASURED_SKY_R), lat_deg=39.0)
        assert est is not None
        assert np.hypot(est.x - POLE[0], est.y - POLE[1]) < 20.0
        assert est.east_left is True


class TestTrackingMountContaminant:
    """Issue #10: a light on a tracking mount drifts ~1x the Polaris arc —
    squarely inside the drift band — and at a hosting site it is brighter
    than Polaris. Brightness-first selection picked it every run; rotation
    support must pick the point the field actually rotates about."""

    def test_brighter_tracking_light_does_not_displace_polaris(self):
        light = tracking_light()
        est = find_pole(make_frames(contaminants=[light]), lat_deg=39.0)
        assert est is not None
        assert np.hypot(est.x - POLE[0], est.y - POLE[1]) < 20.0
        assert est.east_left is True
        assert est.flux == pytest.approx(4000.0, rel=0.2)

    @pytest.mark.parametrize("arc_multiple", [0.6, 1.0, 1.8])
    def test_across_the_drift_band(self, arc_multiple):
        light = tracking_light(arc_multiple=arc_multiple)
        est = find_pole(make_frames(contaminants=[light]), lat_deg=39.0)
        assert est is not None
        assert np.hypot(est.x - POLE[0], est.y - POLE[1]) < 20.0

    def test_several_tracking_lights(self):
        lights = [tracking_light(2200.0, 1500.0, 12000.0),
                  tracking_light(1000.0, 2400.0, 20000.0, 0.8),
                  tracking_light(2600.0, 2300.0, 9000.0, 1.4)]
        est = find_pole(make_frames(contaminants=lights), lat_deg=39.0)
        assert est is not None
        assert np.hypot(est.x - POLE[0], est.y - POLE[1]) < 20.0

    def test_hidden_polaris_with_tracking_light_yields_no_pole(self):
        # The #10 shape: Polaris behind a pier, a tracking light in band.
        # A contaminated field must yield NO pole, not the light.
        light = tracking_light()
        est = find_pole(make_frames(with_polaris=False, contaminants=[light]),
                        lat_deg=39.0)
        assert est is None

    def test_hidden_polaris_with_several_lights_yields_no_pole(self):
        lights = [tracking_light(2200.0, 1500.0, 12000.0),
                  tracking_light(1000.0, 2400.0, 20000.0, 0.8)]
        est = find_pole(make_frames(with_polaris=False, contaminants=lights),
                        lat_deg=39.0)
        assert est is None

    def test_faint_polaris_still_wins_on_rotation_support(self):
        # Even a Polaris fainter than the field (thin cloud) beats a bright
        # contaminant: support, not flux, decides.
        light = tracking_light(flux=30000.0)
        est = find_pole(make_frames(contaminants=[light], polaris_flux=350.0),
                        lat_deg=39.0)
        assert est is not None
        assert np.hypot(est.x - POLE[0], est.y - POLE[1]) < 20.0


class TestPredictedArc:
    def test_reference_rig_value(self):
        # Measured on sample_images: Polaris drifted 3.3px over a 61-min
        # window at sky_r=1563. The prediction must land close to that.
        arc = predicted_polaris_arc_px(1563.0, 61.0)
        assert 2.8 < arc < 3.9

    def test_scales_with_resolution(self):
        assert predicted_polaris_arc_px(780.0, 60.0) == pytest.approx(
            predicted_polaris_arc_px(1560.0, 60.0) / 2.0)
