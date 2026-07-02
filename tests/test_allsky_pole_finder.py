"""Tests for services.allsky.pole_finder — synthetic rotating star fields.

Geometry mirrors the reference rig (3552px frame, trimmed sky radius ~1563px,
pole ~1120px from the circle centre) so tolerances exercise the real scales.
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from services.allsky.pole_finder import (
    MIN_FRAMES,
    MIN_SPAN_MINUTES,
    SIDEREAL_DEG_PER_MIN,
    PoleEstimate,
    find_pole,
    predicted_polaris_arc_px,
)

SKY_CX, SKY_CY, SKY_R = 1776.0, 1776.0, 1563.0
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
):
    """Synthetic detection buffer: field stars arc around POLE at the sidereal
    rate with direction `sign`; optional Polaris (bright, 13px from pole);
    optional contaminants as (x, y, flux, drift_px_over_window) tuples."""
    rng = np.random.default_rng(seed)
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
            if np.hypot(x - SKY_CX, y - SKY_CY) > SKY_R - 30:
                continue
            det.append((x + rng.normal(0, NOISE_PX),
                        y + rng.normal(0, NOISE_PX), fl))
        if with_polaris:
            px = POLE[0] + 13.0 * np.cos(0.4)
            py = POLE[1] + 13.0 * np.sin(0.4)
            px, py = _rotate_about(px, py, POLE[0], POLE[1], theta)
            det.append((px + rng.normal(0, NOISE_PX),
                        py + rng.normal(0, NOISE_PX), 4000.0))
        for (cx, cy, cfl, cdrift) in contaminants:
            frac = k / (n_frames - 1)
            det.append((cx + cdrift * frac + rng.normal(0, NOISE_PX),
                        cy + rng.normal(0, NOISE_PX), cfl))
        frames.append({
            'dt': dt, 'detected': det,
            'sky_cx': SKY_CX, 'sky_cy': SKY_CY, 'sky_r': SKY_R,
        })
    return frames


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


class TestPredictedArc:
    def test_reference_rig_value(self):
        # Measured on sample_images: Polaris drifted 3.3px over a 61-min
        # window at sky_r=1563. The prediction must land close to that.
        arc = predicted_polaris_arc_px(1563.0, 61.0)
        assert 2.8 < arc < 3.9

    def test_scales_with_resolution(self):
        assert predicted_polaris_arc_px(780.0, 60.0) == pytest.approx(
            predicted_polaris_arc_px(1560.0, 60.0) / 2.0)
