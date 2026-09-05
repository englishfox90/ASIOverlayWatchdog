"""Real-data acceptance regression for the bright-anchor gate.

The June-13 failure analysis (docs/dev/allsky_single_image_failure_2026-06-13.md)
set the acceptance criterion: the committed known-good multi_calibration.json
MUST pass the gate on the hand-confirmed frame lum_20260116_021511.fits, and
wrong-basin variants must still fail. The old 15° altitude floor violated the
first half (it judged the model where every fisheye fit is weakest); the 40°
floor satisfies both — verified by the 2026-07-01 parameter sweep in
docs/ALLSKY_POLE_ANCHOR_PLAN.md.
"""
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.allsky.calibration_validate import (
    validate_a1_scale, validate_bright_anchors)
from services.allsky.fisheye import FisheyeModel

REPO = os.path.join(os.path.dirname(__file__), '..')
FRAME = os.path.join(REPO, 'sample_images', 'lum_20260116_021511.fits')
CAL = os.path.join(REPO, 'sample_images', 'multi_calibration.json')
LAT, LON = 38.9717, -95.2353


@pytest.fixture(scope='module')
def frame_data():
    astro = pytest.importorskip('astropy.io.fits')
    if not (os.path.exists(FRAME) and os.path.exists(CAL)):
        pytest.skip('sample_images reference data not present')

    from services.allsky.star_centroid import detect_stars, measure_sky_circle
    from services.allsky.catalogs import get_bright_stars
    from services.allsky.coords import radec_to_altaz

    with astro.open(FRAME) as hdu:
        data = hdu[0].data
    flat = data.flatten().astype(np.float32)
    lo, hi = np.percentile(flat, 1), np.percentile(flat, 99)
    img = ((data.astype(np.float32) - lo) / max(hi - lo, 1) * 255
           ).clip(0, 255).astype(np.uint8)

    circle = measure_sky_circle(img)
    assert circle is not None, "reference frame must yield a measured sky circle"
    cx, cy, r = circle
    det = detect_stars(img, max_stars=200, sky_cx=cx, sky_cy=cy, sky_radius=r)

    m = re.search(r'_(\d{8})_(\d{6})', os.path.basename(FRAME))
    d, t = m.group(1), m.group(2)
    # Filenames are CST; true UTC = +6 h.
    dt = datetime(2026, int(d[4:6]), int(d[6:]), int(t[:2]), int(t[2:4]),
                  int(t[4:]), tzinfo=timezone.utc) + timedelta(hours=6)

    ah = []
    for s in get_bright_stars(max_mag=6.5):
        alt, az = radec_to_altaz(s['ra_deg'], s['dec_deg'], LAT, LON, dt)
        if float(alt) > 3.0:
            ah.append((s, float(alt), float(az)))
    ah.sort(key=lambda x: x[0]['vmag'])
    return {'above_horizon': ah, 'detected': det, 'sky_r': r}


def _incident_model():
    """The 2026-06-23 shipped wrong-basin fit, scaled to this frame size,
    with the mirror corrected so only the gate under test can reject it."""
    s = 3552.0 / 2628.0
    return FisheyeModel(
        cx=1154.452083684348 * s, cy=1322.8234646056446 * s,
        a1=480.5981324229242 * s, a3=19.99999999975631 * s,
        a5=-12.349397496767505 * s, roll=-0.20656450436385085,
        axis_alt=78.18606880664784, axis_az=12.576781341950102,
        east_left=True)


def test_known_good_model_passes_a1_gate(frame_data):
    """The sky circle is a weak prior on a1: the known-good model's ratio
    against the MEASURED radius is ~1.23 (the horizon circle overfills the
    sensor on this rig) and must pass without the obstruction warning."""
    ok, msg = validate_a1_scale(FisheyeModel.load(CAL), frame_data['sky_r'])
    assert ok, msg
    assert 'obstructed' not in msg


def test_incident_model_fails_a1_gate(frame_data):
    ok, msg = validate_a1_scale(_incident_model(), frame_data['sky_r'])
    assert not ok
    assert 'skipped' not in msg


def test_known_good_model_passes(frame_data):
    model = FisheyeModel.load(CAL)
    ok, msg = validate_bright_anchors(
        model, frame_data['above_horizon'], frame_data['detected'],
        sky_r=frame_data['sky_r'])
    assert ok, f"known-good model rejected by the anchor gate: {msg}"


def test_mirrored_model_fails(frame_data):
    model = FisheyeModel.load(CAL)
    model.east_left = not model.east_left
    ok, msg = validate_bright_anchors(
        model, frame_data['above_horizon'], frame_data['detected'],
        sky_r=frame_data['sky_r'])
    assert not ok
    assert 'skipping' not in msg


def test_rolled_model_fails(frame_data):
    model = FisheyeModel.load(CAL)
    model.roll += np.pi
    ok, msg = validate_bright_anchors(
        model, frame_data['above_horizon'], frame_data['detected'],
        sky_r=frame_data['sky_r'])
    assert not ok
    assert 'skipping' not in msg


def test_incident_wrong_basin_model_fails(frame_data):
    ok, msg = validate_bright_anchors(
        _incident_model(), frame_data['above_horizon'], frame_data['detected'],
        sky_r=frame_data['sky_r'])
    assert not ok
    assert 'skipping' not in msg
