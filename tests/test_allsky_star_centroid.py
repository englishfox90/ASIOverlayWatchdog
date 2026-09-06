"""
Tests for services/allsky/star_centroid.py detect_stars() on LINEAR uint8 frames.

Guards a deliberate non-change (2026-09-05, issue #10). The sky-circle scan in
the same module percentile-stretches its input to be exposure-invariant, and it
is tempting to do the same in detect_stars() because a linear frame with a
~2 ADU sky median yields far fewer detections than the stretched FITS path
(63 vs 200+ on the reference frame). Measured on real data, that stretch is
harmful: its p99 clip turns every bright star into a flat 255 plateau, which
shifts the hand-confirmed anchors by 1-3 px, drops some of them once the
amplified halo exceeds max_area, and makes the known-good model fail the
bright-anchor gate at two of five exposure levels. Fewer but accurately
centred detections are the right trade for calibration, so these tests pin
the properties a stretch would break:

  - centroids on a dark linear frame track the linear flux-weighted centroid
    of the star profile, and do not move with exposure;
  - on the reference frame rendered as a linear 8-bit image with a median of
    2 ADU (the issue-#10 regime), all nine hand-confirmed anchors are found
    and centred, and the known-good model still passes the anchor gate.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.allsky import star_centroid as sc

pytest.importorskip('cv2')
PILImage = pytest.importorskip('PIL.Image')


# ---------------------------------------------------------------------------
# Synthetic dark linear frame with coma-like star wings
# ---------------------------------------------------------------------------

SIZE, SKY_CX, SKY_CY, SKY_R = 900, 450.0, 450.0, 400.0

# (x, y, core peak, wing peak). The wing is displaced radially outward from
# the optical centre, as lens coma is, so its centroid differs from the
# core's: a detector that clips bright profiles lands on the wrong point.
PLANTED = [(300.3, 280.6, 250, 8), (600.7, 330.2, 200, 6), (420.4, 620.8, 255, 10),
           (250.2, 520.5, 120, 3), (650.6, 600.3, 60, 0), (480.1, 400.7, 20, 0),
           (350.9, 700.2, 12, 0)]


def _linear_frame(sky: float, seed: int = 7):
    """Return (uint8 frame, [(x, y) linear flux centroid of each planted star])."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:SIZE, 0:SIZE].astype(np.float64)
    img = np.where(np.hypot(xx - SKY_CX, yy - SKY_CY) <= SKY_R, sky, 0.0)
    truth = []
    for x, y, peak, wing_peak in PLANTED:
        core = peak * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.5 ** 2))
        ang = np.arctan2(y - SKY_CY, x - SKY_CX)
        wx, wy = x + 4.0 * np.cos(ang), y + 4.0 * np.sin(ang)
        wing = wing_peak * np.exp(-((xx - wx) ** 2 + (yy - wy) ** 2) / (2 * 6.0 ** 2))
        prof = core + wing
        img += prof
        # Same 17x17 window the detector integrates over.
        x0, y0 = int(round(x)), int(round(y))
        win = (slice(y0 - 8, y0 + 9), slice(x0 - 8, x0 + 9))
        p = prof[win]
        truth.append((float((xx[win] * p).sum() / p.sum()),
                      float((yy[win] * p).sum() / p.sum())))
    img += rng.normal(0.0, 0.4, img.shape)
    return np.clip(np.round(img), 0, 255).astype(np.uint8), truth


def _detect(frame):
    return sc.detect_stars(PILImage.fromarray(frame, mode='L'), max_stars=50,
                           sky_cx=SKY_CX, sky_cy=SKY_CY, sky_radius=SKY_R)


def _nearest(det, x, y):
    if not det:
        return np.inf, None
    d = np.array([(dx, dy) for dx, dy, _ in det])
    dist = np.hypot(d[:, 0] - x, d[:, 1] - y)
    i = int(np.argmin(dist))
    return float(dist[i]), (float(d[i, 0]), float(d[i, 1]))


class TestSyntheticLinearFrame:

    @pytest.mark.parametrize('sky', [2.0, 6.0, 40.0])
    def test_centroids_track_linear_flux_centroid(self, sky):
        """Every planted star is found within 0.75 px of the linear flux
        centroid of its profile, wings included. A p99-clipped input puts the
        haloed stars 3-4 px off (and at sky=40 loses them altogether)."""
        frame, truth = _linear_frame(sky)
        assert float(np.median(frame)) == sky
        det = _detect(frame)
        for (tx, ty), planted in zip(truth, PLANTED):
            err, _ = _nearest(det, tx, ty)
            assert err < 0.75, f"star at {planted[:2]} off by {err:.2f}px at sky={sky}"

    def test_centroids_do_not_move_with_exposure(self):
        """The same field at a 2 ADU and a 40 ADU sky median gives the same
        centroids to 0.3 px: detection on the linear frame is exposure-stable
        where it matters, without any stretch."""
        dark, truth = _linear_frame(2.0)
        bright, _ = _linear_frame(40.0)
        det_dark, det_bright = _detect(dark), _detect(bright)
        for (tx, ty), planted in zip(truth, PLANTED):
            _, a = _nearest(det_dark, tx, ty)
            _, b = _nearest(det_bright, tx, ty)
            assert a is not None and b is not None
            shift = float(np.hypot(a[0] - b[0], a[1] - b[1]))
            assert shift < 0.3, f"star at {planted[:2]} moved {shift:.2f}px with exposure"


# ---------------------------------------------------------------------------
# Real reference frame at the issue-#10 operating point
# ---------------------------------------------------------------------------

REPO = os.path.join(os.path.dirname(__file__), '..')
FRAME = os.path.join(REPO, 'sample_images', 'lum_20260116_021511.fits')
CAL = os.path.join(REPO, 'sample_images', 'multi_calibration.json')
LAT, LON = 38.9717, -95.2353

# docs/ALLSKY_CALIBRATION_PLAN.md hand-confirmed pairs (Sirius excluded: uncertain).
# These pixel positions came from the stretched FITS path and carry its 1-5 px
# bias on the brightest stars; the fixture re-centres each one on the float
# data, which is the quantisation-free reference the assertions use.
ANCHORS = {
    'Regulus': (1160.5, 2274.4), 'Procyon': (1991.3, 2458.4), 'Alkaid': (769.6, 1028.4),
    'Mizar': (916.2, 1006.7), 'Alioth': (982.5, 1056.2), 'Megrez': (1077.8, 1118.2),
    'Phecda': (1072.7, 1216.0), 'Merak': (1242.8, 1243.3), 'Dubhe': (1303.3, 1137.1),
}


def _float_centroid(data, x, y, rad=8):
    x0, y0 = int(round(x)), int(round(y))
    patch = data[y0 - rad:y0 + rad + 1, x0 - rad:x0 + rad + 1].astype(np.float64)
    ring = np.concatenate([patch[0], patch[-1], patch[:, 0], patch[:, -1]])
    patch = np.clip(patch - np.median(ring), 0, None)
    ys, xs = np.mgrid[y0 - rad:y0 + rad + 1, x0 - rad:x0 + rad + 1]
    return float((xs * patch).sum() / patch.sum()), float((ys * patch).sum() / patch.sum())


@pytest.fixture(scope='module')
def linear_median2():
    astro = pytest.importorskip('astropy.io.fits')
    if not (os.path.exists(FRAME) and os.path.exists(CAL)):
        pytest.skip('sample_images reference data not present')
    with astro.open(FRAME) as hdu:
        data = np.array(hdu[0].data)
    # data*255 renders this frame with a 7 ADU sky median; /3 puts it at the
    # ~2 ADU the issue-#10 rig produces with auto-exposure pinned at max.
    lin = np.clip(np.round(data * (255.0 / 3.0)), 0, 255).astype(np.uint8)
    assert float(np.median(lin)) == 2.0
    circle = sc.measure_sky_circle(lin)
    assert circle is not None, "linear frame must still yield a measured sky circle"
    cx, cy, r = circle
    det = sc.detect_stars(PILImage.fromarray(lin, mode='L'), max_stars=200,
                          sky_cx=cx, sky_cy=cy, sky_radius=r)
    refs = {name: _float_centroid(data, *pos) for name, pos in ANCHORS.items()}
    return {'detected': det, 'refs': refs, 'sky_r': r}


class TestReferenceFrameLinearMedian2:

    def test_all_anchors_found_and_centred(self, linear_median2):
        """Measured: 9/9 found, median error 0.09 px, max 1.26 px (Procyon,
        whose halo makes even the float reference ~1 px uncertain). The
        stretched path on the same frame: 8/9 found, median 1.4 px, max 2.9."""
        det = linear_median2['detected']
        errs = {name: _nearest(det, *ref)[0] for name, ref in linear_median2['refs'].items()}
        assert all(e < 2.0 for e in errs.values()), errs
        assert float(np.median(list(errs.values()))) < 0.5, errs

    def test_detection_count_is_usable(self, linear_median2):
        """63 measured. Far below the 200 cap, and enough for the matcher and
        the anchor gate; a stretch would report thousands, most of them
        quantisation residue that adds no catalog precision."""
        assert len(linear_median2['detected']) >= 30

    def test_known_good_model_passes_anchor_gate(self, linear_median2):
        from services.allsky.calibration_validate import validate_bright_anchors
        from services.allsky.catalogs import get_bright_stars
        from services.allsky.coords import radec_to_altaz
        from services.allsky.fisheye import FisheyeModel

        # Filename is CST; true UTC = +6 h.
        dt = datetime(2026, 1, 16, 2, 15, 11, tzinfo=timezone.utc) + timedelta(hours=6)
        above = []
        for s in get_bright_stars(max_mag=6.5):
            alt, az = radec_to_altaz(s['ra_deg'], s['dec_deg'], LAT, LON, dt)
            if float(alt) > 3.0:
                above.append((s, float(alt), float(az)))
        above.sort(key=lambda x: x[0]['vmag'])

        good = FisheyeModel.load(CAL)
        ok, msg = validate_bright_anchors(good, above, linear_median2['detected'],
                                          sky_r=linear_median2['sky_r'])
        assert ok, f"known-good model rejected on the linear median-2 frame: {msg}"

        mirrored = FisheyeModel.load(CAL)
        mirrored.east_left = not mirrored.east_left
        ok, msg = validate_bright_anchors(mirrored, above, linear_median2['detected'],
                                          sky_r=linear_median2['sky_r'])
        assert not ok
        assert 'skipping' not in msg
