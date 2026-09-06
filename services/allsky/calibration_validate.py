"""
Calibration scoring and post-fit validation.

Three concerns, one module:

1. score_matches_with_spread() — grid-search scoring that penalises
   solutions whose matches cluster in one azimuth arc. A wrong orientation
   over a dense star field can accumulate many accidental matches; the
   legitimate solution spreads matches around the whole sky.

2. validate_bright_anchors() — post-fit check that the brightest
   catalog stars above the horizon actually land on detected stars. A
   spurious fit can produce a respectable average residual (density-noise
   matching) while missing Sirius, Vega, etc. by 100+ pixels.

3. warn_sky_coverage() — informational log about how well the fit's
   matched stars cover the sky.  A single-quadrant fit extrapolates
   poorly to the rest of the sky.
"""
from dataclasses import replace
from typing import List, Optional, Tuple

import numpy as np

from services.logger import app_logger as log


# ---------------------------------------------------------------------------
# Resolution-independent match tolerances (F10)
# ---------------------------------------------------------------------------

# The all-sky match tolerances (50/35/40 px etc.) were tuned at the reference
# resolution (a 3552x3552 ASI frame). Pixel tolerances that are correct at that
# radius are too loose on a resized frame and too tight on a larger one, so
# matching behaviour drifted with resize_percent. Expressing every tolerance as
# `ref_px * tol_scale(sky_r)` makes it track the actual sky radius.
#
# Provenance (issue #10 investigation): 1563 is 0.88 x 1776 — the frame-centred
# FALLBACK estimate_sky_circle returns when its edge scan fails, not a measured
# radius. The measured trimmed radius on the reference frames is ~1386 px, so
# at native resolution tol_scale is ~0.89, and every gate parameter since the
# 2026-07-01 anchor-gate sweep was validated at that effective scale. Changing
# this constant rescales every tolerance on every rig; leave it unless the
# whole tolerance set is re-validated together.
REF_SKY_R_PX = 1563.0

# Inward trim applied by estimate_sky_circle (star_centroid.py). The triangle
# fallback seeds a1 from the sky radius; that radius is the *trimmed* circle, so
# it must be divided back out to recover the true optical radius.
SKY_TRIM_FRACTION = 0.15


def tol_scale(sky_r: Optional[float]) -> float:
    """Scale factor for pixel tolerances given the estimated sky radius.

    Returns 1.0 (neutral — native-resolution behaviour) when sky_r is unknown
    or non-positive.
    """
    if not sky_r or sky_r <= 0:
        return 1.0
    return float(sky_r) / REF_SKY_R_PX


def a1_from_sky_radius(sky_radius: float) -> float:
    """Seed the linear fisheye coefficient a1 from the trimmed sky radius.

    estimate_sky_circle returns the *trimmed* radius (inward by
    SKY_TRIM_FRACTION); a1 is defined against the true optical radius for an
    equidistant lens (r = a1·θ, so a1 = r_horizon / (π/2)). Divide the trim back
    out first. Shared by the triangle, multi-image and guided calibrators.
    """
    return (float(sky_radius) / (1.0 - SKY_TRIM_FRACTION)) / (np.pi / 2.0)


def median_frame_resolution(frames: List[dict]) -> Tuple[int, int]:
    """Median (width, height) across frames with a known image_width/height.

    Returns (0, 0) when no frame carries the metadata. Used by the pole-anchor
    admission gate (validate_pole) to know what resolution the pole was
    measured at, so a candidate model calibrated on a different-resolution
    frame (e.g. manual/guided calibration against the pre-resize raw cached
    frame, vs. the background service's post-resize preview buffer) can be
    rescaled into the pole's frame before the pixel comparison — see
    docs/ALLSKY_POLE_ANCHOR_PLAN.md P1.
    """
    ws = [f.get('image_width') for f in frames if f.get('image_width')]
    hs = [f.get('image_height') for f in frames if f.get('image_height')]
    if not ws or not hs:
        return 0, 0
    return int(np.median(ws)), int(np.median(hs))


# ---------------------------------------------------------------------------
# Grid-search scoring
# ---------------------------------------------------------------------------

def score_matches_with_spread(matches: List[Tuple]) -> float:
    """Grid-search quality score: match count weighted by azimuth spread.

    spread = 1 - R, where R is the unit-vector resultant length of match
    azimuths (R=0 → stars evenly spread on a circle, R=1 → all clustered
    in one direction). Final score = n * (0.5 + 0.5 * spread), giving a
    factor range [0.5, 1.0] × n. A clustered fit is halved; an evenly
    spread fit scores the raw count.

    matches: [((dx, dy), star_dict, (alt, az)), ...] as produced by
             calibration._brightness_match.
    """
    n = len(matches)
    if n < 3:
        return float(n)
    az_deg = np.array([az for (_xy, _star, (_alt, az)) in matches])
    az_r = np.radians(az_deg)
    R = float(np.hypot(np.mean(np.cos(az_r)), np.mean(np.sin(az_r))))
    spread = 1.0 - R
    return n * (0.5 + 0.5 * spread)


# ---------------------------------------------------------------------------
# Post-fit bright-anchor validation
# ---------------------------------------------------------------------------

def validate_bright_anchors(
    model,
    above_horizon: List[Tuple],
    detected: List[Tuple],
    top_n: int = 12,
    min_hits: int = 5,
    max_miss_px: float = 40.0,
    min_alt_deg: float = 40.0,
    sky_r: Optional[float] = None,
) -> Tuple[bool, str]:
    """Check the N brightest above-horizon catalog stars landed near detections.

    Rationale: a spurious orientation fit can produce a healthy RMS
    residual by coincidental density matching across hundreds of faint
    stars, while simultaneously missing the handful of bright anchors
    (Sirius, Vega, Capella, etc.) by huge margins. This check catches
    that failure mode cheaply.

    Altitude floor: the pool is restricted to anchors above 40° because the
    fisheye radial polynomial is extrapolating below that — measured on the
    reference rig, the KNOWN-GOOD model misses low-altitude anchors by
    46-406px (Sirius/Aldebaran/Betelgeuse at 20-30° alt) while nailing
    high-altitude ones at 7-35px; wrong-basin fits miss high-altitude
    anchors by 40-360px. Testing only the high-altitude region is what
    makes good and bad fits separable (the old 15° floor rejected the
    known-good production model — see allsky_single_image_failure_2026-06-13
    and the 2026-07-01 sweep in ALLSKY_POLE_ANCHOR_PLAN.md). Whole-sky
    correctness is covered by the a1-scale, lens-polynomial and pole gates.

    Obstruction tolerance: on obstructed installs (pier cameras with a
    telescope/mount in frame, dome-rim cuts, building horizons) a large
    fraction of the brightest stars can sit behind hardware and are never
    detected. Testing only the top 6 then becomes structurally unwinnable
    once ~half are blocked — a perfect fit still fails because its anchors
    land on the OTA. Widening the pool to the top 12 while keeping the 5-hit
    floor restores headroom: a correct fit hits the ~5-7 anchors that are in
    clear sky, while a genuinely wrong orientation still misses essentially
    all 12 (random-hit expectation is ~2). The lens-polynomial and RMS gates
    remain as independent backstops.

    Args:
        model: FisheyeModel to evaluate (uses altaz_to_pixel).
        above_horizon: [(star_dict, alt_deg, az_deg), ...] sorted
                       brightest-first (as produced by calibrate()).
        detected:      [(dx, dy, flux), ...] list of detected star
                       centroids.
        top_n: number of brightest above-horizon catalog stars to test.
               Default 12 so obstructed installs (telescope/mount/dome in
               frame) still have enough clear-sky anchors to reach min_hits.
        min_hits: minimum required anchors with a nearby detection.
        max_miss_px: maximum pixel distance from projected catalog
                     position to nearest detected star to count as a hit
                     (at the reference resolution; scaled by sky_r when given).
        min_alt_deg: skip anchors below this altitude — below it even a
                     correct model extrapolates poorly (see docstring), so
                     low anchors carry no signal about fit correctness.
        sky_r: estimated sky-circle radius (px). When provided, max_miss_px is
               scaled to it so the check is resolution-independent.

    Returns:
        (ok, message). When the check is skipped (insufficient anchors),
        returns ok=True with a note — we don't want to reject fits on
        cloudy/obstructed skies where bright anchors aren't visible.
    """
    if sky_r is not None:
        max_miss_px = max_miss_px * tol_scale(sky_r)

    n_bright = len(select_bright_anchors(above_horizon, top_n, min_alt_deg))
    if n_bright < min_hits:
        return True, (f"only {n_bright} bright anchors above "
                      f"{min_alt_deg:.0f}° — skipping validation")

    if not detected:
        return False, "no detected stars to validate against"

    hits, n_bright, misses = count_anchor_hits(
        model, above_horizon, detected, top_n=top_n,
        min_alt_deg=min_alt_deg, max_miss_px=max_miss_px)

    if hits >= min_hits:
        return True, f"{hits}/{n_bright} bright anchors matched"

    miss_str = ", ".join(
        f"{name}({d:.0f}px)" if np.isfinite(d) else f"{name}(off-image)"
        for name, d in misses[:5]
    )
    return False, (f"only {hits}/{n_bright} bright anchors within "
                   f"{max_miss_px:.0f}px (missed: {miss_str})")


def select_bright_anchors(above_horizon: List[Tuple], top_n: int = 12,
                          min_alt_deg: float = 40.0) -> List[Tuple]:
    """The anchor pool validate_bright_anchors tests: brightest `top_n`
    catalog stars above `min_alt_deg` (input is sorted brightest-first)."""
    return [(s, alt, az) for s, alt, az in above_horizon
            if alt >= min_alt_deg][:top_n]


def count_anchor_hits(
    model,
    above_horizon: List[Tuple],
    detected: List[Tuple],
    top_n: int = 12,
    min_alt_deg: float = 40.0,
    max_miss_px: float = 40.0,
) -> Tuple[int, int, List[Tuple[str, float]]]:
    """(hits, n_bright, misses) for the bright-anchor pool against `detected`.

    `max_miss_px` is taken as already scaled to the frame. `misses` lists
    (name, distance) with inf for anchors the model projects off-image.
    Shared by validate_bright_anchors (candidate gate) and
    incumbent_evidence (is the model on disk still hitting its anchors?).
    """
    bright = select_bright_anchors(above_horizon, top_n, min_alt_deg)
    misses: List[Tuple[str, float]] = []
    if not detected:
        return 0, len(bright), [(s.get('name', '?'), float('inf'))
                                for s, _alt, _az in bright]
    det_xy = np.array([(dx, dy) for dx, dy, *_ in detected], dtype=float)
    hits = 0
    for star, alt, az in bright:
        xy = model.altaz_to_pixel(float(alt), float(az))
        if xy is None:
            misses.append((star.get('name', '?'), float('inf')))
            continue
        dx = det_xy[:, 0] - xy[0]
        dy = det_xy[:, 1] - xy[1]
        d_min = float(np.min(np.sqrt(dx * dx + dy * dy)))
        if d_min <= max_miss_px:
            hits += 1
        else:
            misses.append((star.get('name', '?'), d_min))
    return hits, len(bright), misses


def model_in_frame(model, frame_width: Optional[int], frame_height: Optional[int]):
    """`model` expressed in a (frame_width x frame_height) frame.

    Same cx/cy/a1/a3/a5 scaling overlay_renderer applies at render time.
    Returned unchanged when either resolution is unknown, when they already
    match, or when the aspect ratios differ (a crop, not a resize — no
    single factor relates the pixels, so the caller compares unscaled).
    """
    m_w = int(getattr(model, 'image_width', 0) or 0)
    m_h = int(getattr(model, 'image_height', 0) or 0)
    if not (frame_width and frame_height and m_w > 0 and m_h > 0):
        return model
    if int(frame_width) == m_w and int(frame_height) == m_h:
        return model
    ar_model = m_w / m_h
    ar_frame = frame_width / frame_height
    if abs(ar_model - ar_frame) / max(ar_model, ar_frame) > 0.02:
        log.debug(
            f"model_in_frame: model resolution {m_w}x{m_h} vs frame "
            f"{frame_width}x{frame_height} — aspect mismatch, comparing unscaled")
        return model
    s = float(frame_width) / m_w
    return replace(
        model,
        cx=model.cx * s, cy=model.cy * s,
        a1=model.a1 * s, a3=model.a3 * s, a5=model.a5 * s,
        image_width=int(frame_width), image_height=int(frame_height),
    )


# ---------------------------------------------------------------------------
# Physical-plausibility check on the lens polynomial
# ---------------------------------------------------------------------------

# Physical fisheye lenses have modest-negative cubic coefficients (barrel
# distortion correction). A strongly-positive a3 would mean the lens becomes
# more curved with increasing angle, which no real fisheye design produces —
# it's always the optimiser compensating for a wrong orientation.
A3_MIN = -80.0
A3_MAX =  20.0

# An a3 sitting *at* an optimiser bound is as diagnostic as one outside it:
# the fit fought the bound trying to bend the polynomial toward a wrong
# orientation and was only stopped by the clamp (a wrong-basin model shipped
# with a3=19.99999997 — inside the range, pinned at the bound).
A3_PIN_EPS = 0.5

# Conservative physical prior for a3 when the data can't constrain the radial
# polynomial (no anchors / sparse clustered coverage). Real fisheyes sit in
# roughly [-60, 0]; -30 is a neutral mid-range seed. Shared by the single-image,
# multi-image and triangle fits.
A3_SEED_DEFAULT = -30.0

# Ridge-prior weights pulling (a3, a5) toward the seed when coverage is sparse,
# so the optimiser corrects orientation instead of bending the polynomial to a
# false minimum. Shared by the multi-image and guided fits (a5 spans a ~100x
# larger range than a3, hence the smaller weight).
REG_A3 = 0.5
REG_A5 = 0.02

# Coarse orientation hypothesis grid (degrees), shared by the cross-frame
# (multi-image) and anchor (guided) orientation searches. Same parameter space;
# only the per-candidate scoring differs between the two callers.
ORIENT_AXIS_ALT = range(60, 91, 5)     # camera tilt from vertical
ORIENT_AXIS_AZ = range(0, 360, 30)     # tilt azimuth
ORIENT_ROLL_DEG = range(-180, 180, 15)  # rotation about the optical axis


def validate_lens_polynomial(model) -> Tuple[bool, str]:
    """Reject physically-implausible lens polynomial coefficients.

    The radial projection model is `r = a1·θ + a3·θ³ + a5·θ⁵`. Real fisheye
    lenses have `a3` in roughly `[-60, 0]`; values well outside that range
    mean the optimiser is bending the polynomial to fit a wrong orientation
    rather than describing real lens distortion.

    Returns (ok, message). Doesn't depend on observer, detections, or
    catalog — this is a pure sanity check on fit parameters.
    """
    a3 = float(getattr(model, 'a3', 0.0))
    if a3 < A3_MIN or a3 > A3_MAX:
        return False, (
            f"lens polynomial a3={a3:.1f} is outside the physically plausible "
            f"range [{A3_MIN:.0f}, {A3_MAX:.0f}] — optimiser likely compensating "
            "for a wrong orientation"
        )
    if a3 > A3_MAX - A3_PIN_EPS or a3 < A3_MIN + A3_PIN_EPS:
        return False, (
            f"lens polynomial a3={a3:.2f} is pinned at its optimiser bound "
            f"[{A3_MIN:.0f}, {A3_MAX:.0f}] — the fit fought the clamp, which "
            "means it was bending the polynomial toward a wrong orientation"
        )
    return True, f"lens polynomial a3={a3:.1f} within plausible range"


# ---------------------------------------------------------------------------
# Physical scale check: a1 vs the measured sky circle
# ---------------------------------------------------------------------------

# The linear coefficient a1 IS the plate scale (px/rad); the sky-circle fit is
# an independent measurement of a related quantity: the radius of the
# ILLUMINATED disc. a1_from_sky_radius() converts that radius to a1 by assuming
# the disc edge is the horizon (theta = 90 deg). On a real rig the edge sits
# above the horizon — the lens overfills the sensor (reference rig: the
# horizon circle is ~2006 px on a 1776 px half-frame), or piers, domes and
# buildings vignette the low sky (issue #10 rig: aperture ends near 23 deg
# altitude). Both make the implied a1 an UNDER-estimate, never an over-estimate,
# so the ratio model.a1 / implied is a one-sided physical quantity:
#
#   ratio = (pi/2) / theta_edge,   i.e.  edge altitude = 90 * (1 - 1/ratio) deg
#
# Measured ratios: reference rig known-good model 1.23 (edge ~17 deg); issue #10
# rig, guided solve at RMS 2.4 px, ~1.35 (edge ~23 deg); the wrong-basin model
# that shipped 0.57 — its horizon lay INSIDE the illuminated disc, which is
# impossible. That low side is the failure mode this gate exists for.
#
# Floor: ratio < 1 is unphysical; 0.7 leaves 30% for estimator noise (measured
# +/-4% on the reference frames after the exposure-invariance fix) and for
# horizon glow pushing the measured edge outward.
A1_SCALE_MIN = 0.7
# Above this the model says the illuminated edge sits above 30 deg altitude:
# plausible only with heavy obstruction, so the fit is accepted with a WARNING
# rather than silently. The sky circle is a weak prior on a1, not a constraint.
A1_SCALE_OBSTRUCTED = 1.5
# Hard ceiling: an illuminated edge above 40 deg altitude is a 100 deg field,
# not an all-sky camera. A 1.5x wrong-scale basin on the most obstructed real
# rig we have (1.35 x 1.5 = 2.0) and the double-scale case (2.05) both fall
# outside it; a correct fit on that rig keeps ~30% headroom below it.
A1_SCALE_MAX = 1.8


def implied_edge_altitude_deg(ratio: float) -> float:
    """Altitude (deg) at which a model with a1 = ratio x a1_from_sky_radius(r)
    places the illuminated disc's edge. 0 deg at ratio 1 (edge is the horizon);
    negative below 1 (horizon inside the lit disc — unphysical)."""
    if ratio <= 0:
        return -90.0
    return 90.0 * (1.0 - 1.0 / ratio)


def validate_a1_scale(model, sky_r: Optional[float]) -> Tuple[bool, str]:
    """Reject models whose plate scale contradicts the measured sky circle.

    A wrong-basin fit routinely converges with a1 at ~half the value the sky
    circle implies (the dense star field offers coincidental matches at any
    scale). The sky-circle estimate is model-free, so this is a hard physical
    cross-check on the low side. On the high side it is only a weak prior —
    see the band constants — so an obstructed-aperture ratio between
    A1_SCALE_OBSTRUCTED and A1_SCALE_MAX passes with a logged warning.
    Skipped (ok=True) when sky_r is unknown (None/0: never measured).
    """
    if not sky_r or sky_r <= 0:
        return True, "sky radius unknown — a1 scale check skipped"
    expected = a1_from_sky_radius(sky_r)
    ratio = float(getattr(model, 'a1', 0.0)) / expected
    edge_alt = implied_edge_altitude_deg(ratio)
    if ratio < A1_SCALE_MIN:
        return False, (
            f"a1={model.a1:.0f} is {ratio:.2f}x the sky-circle-implied scale "
            f"(~{expected:.0f}) — below {A1_SCALE_MIN}: the model's horizon lies "
            "inside the illuminated disc; the fit landed at the wrong plate scale"
        )
    if ratio > A1_SCALE_MAX:
        return False, (
            f"a1={model.a1:.0f} is {ratio:.2f}x the sky-circle-implied scale "
            f"(~{expected:.0f}) — above {A1_SCALE_MAX}: it puts the illuminated "
            f"edge at {edge_alt:.0f}° altitude, which is not an all-sky field; "
            "the fit landed at the wrong plate scale"
        )
    if ratio > A1_SCALE_OBSTRUCTED:
        msg = (f"a1 scale ratio {ratio:.2f} implies the illuminated edge sits at "
               f"{edge_alt:.0f}° altitude — accepted as an obstructed aperture "
               f"(limit {A1_SCALE_MAX})")
        log.warning(f"Calibration: {msg}. If the horizon is actually visible in "
                    "the frame, this fit is at the wrong plate scale.")
        return True, msg
    return True, (f"a1 scale ratio {ratio:.2f} consistent with sky circle "
                  f"(illuminated edge ~{edge_alt:.0f}° altitude)")


# ---------------------------------------------------------------------------
# Pole-anchor check (see pole_finder.py and ALLSKY_POLE_ANCHOR_PLAN.md)
# ---------------------------------------------------------------------------

# Generous by design: even a good model can carry 50-70px of regional error at
# the pole (measured on the reference rig), while wrong-basin fits miss it by
# 400-1400px. The measurement itself is good to ~15px.
POLE_TOL_REF_PX = 140.0


def validate_pole(
    model,
    lat_deg: float,
    pole,
    sky_r: Optional[float] = None,
    pole_image_width: Optional[int] = None,
    pole_image_height: Optional[int] = None,
) -> Tuple[bool, str]:
    """Check the model projects the celestial pole where it was measured.

    pole: a pole_finder.PoleEstimate (duck-typed: .x, .y, .east_left). The
    caller only invokes this when a pole estimate exists — the pole is an
    optional extra constraint, never a requirement.

    pole_image_width/height: resolution of the frames the pole was measured
    on (the CalibrationService buffer). A candidate model is not guaranteed
    to be calibrated at that same resolution — manual ("Calibrate Now") and
    guided calibration fit against the pre-resize raw cached frame, while the
    buffer is fed the post-resize preview in camera mode with
    resize_percent < 100 (see docs/ALLSKY_POLE_ANCHOR_PLAN.md P1). Comparing
    model.altaz_to_pixel() output directly against pole.x/y in that case
    compares pixels from two different resolutions. When both resolutions
    are known, non-zero, and differ, the model is rescaled into the pole's
    frame first — same cx/cy/a1/a3/a5 * (pole_width / model.image_width)
    technique overlay_renderer.py uses at render time. Either resolution
    unknown, or an aspect-ratio mismatch (a crop, not a resize) keeps the old
    unscaled comparison — we don't guess at a scale factor we can't derive.

    Two independent kills for wrong-basin fits:
      1. mirror: model.east_left must agree with the measured field-rotation
         direction (when the sign vote was decisive);
      2. position: the projected pole (alt=|lat|, az=0 north / 180 south)
         must land within POLE_TOL_REF_PX (scaled) of the measured pole.
    """
    if pole is None:
        return True, "no pole estimate — check skipped"

    if pole.east_left is not None and bool(model.east_left) != bool(pole.east_left):
        return False, (
            f"model east_left={model.east_left} contradicts the measured "
            f"field-rotation direction (east_left={pole.east_left}) — "
            "mirrored fit"
        )

    proj_model = model_in_frame(model, pole_image_width, pole_image_height)

    alt = abs(float(lat_deg))
    az = 0.0 if lat_deg >= 0 else 180.0
    xy = proj_model.altaz_to_pixel(alt, az)
    if xy is None:
        return False, "model projects the celestial pole off-image"
    tol = POLE_TOL_REF_PX * tol_scale(sky_r)
    d = float(np.hypot(xy[0] - pole.x, xy[1] - pole.y))
    if d <= tol:
        return True, f"pole projected {d:.0f}px from measured (tol {tol:.0f}px)"
    return False, (
        f"model places the celestial pole {d:.0f}px from its measured position "
        f"({pole.x:.0f}, {pole.y:.0f}) — limit {tol:.0f}px; wrong-basin fit"
    )


# ---------------------------------------------------------------------------
# Post-fit sky-coverage warning
# ---------------------------------------------------------------------------

def warn_sky_coverage(model) -> None:
    """Log a warning when matched stars cover a narrow azimuth arc.

    Reads model.matched_stars (written by _iterative_fit).  A tight cluster
    signals a biased fit that will extrapolate poorly across the rest of
    the sky.
    """
    stars = getattr(model, 'matched_stars', None)
    if not stars or len(stars) < 4:
        return

    az_r = np.radians([s['az'] for s in stars])
    mean_x = float(np.mean(np.cos(az_r)))
    mean_y = float(np.mean(np.sin(az_r)))
    R = float(np.hypot(mean_x, mean_y))
    if R > 0.85:   # < ~30° azimuth spread
        mean_az = np.degrees(np.arctan2(mean_y, mean_x)) % 360
        log.warning(
            f"Calibration warning: matched stars cluster within a narrow "
            f"azimuth arc (R={R:.2f}, mean az≈{mean_az:.0f}°). "
            "Cross-sky accuracy may be poor. Consider multi-image "
            "calibration or adding anchor stars in other quadrants."
        )
    elif R > 0.65:  # < ~60° spread
        log.info(
            f"Calibration note: matched stars cover a limited azimuth arc "
            f"(R={R:.2f}). Accuracy may degrade toward unsampled regions."
        )
