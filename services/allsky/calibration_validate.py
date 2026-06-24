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
from typing import List, Optional, Tuple

import numpy as np

from services.logger import app_logger as log


# ---------------------------------------------------------------------------
# Resolution-independent match tolerances (F10)
# ---------------------------------------------------------------------------

# The all-sky match tolerances (50/35/40 px etc.) were tuned at the reference
# resolution, where the trimmed sky-circle radius is ~1563 px (a 3552x3552 ASI
# frame). Pixel tolerances that are correct at that radius are too loose on a
# resized frame and too tight on a larger one, so matching behaviour drifted
# with resize_percent. Expressing every tolerance as `ref_px * tol_scale(sky_r)`
# makes it track the actual sky radius. At the reference radius the scale is
# 1.0, so native-resolution behaviour is unchanged.
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
    min_alt_deg: float = 15.0,
    sky_r: Optional[float] = None,
) -> Tuple[bool, str]:
    """Check the N brightest above-horizon catalog stars landed near detections.

    Rationale: a spurious orientation fit can produce a healthy RMS
    residual by coincidental density matching across hundreds of faint
    stars, while simultaneously missing the handful of bright anchors
    (Sirius, Vega, Capella, etc.) by huge margins. This check catches
    that failure mode cheaply.

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
        min_alt_deg: skip anchors below this altitude (refraction / horizon
                     obstructions make low anchors unreliable).
        sky_r: estimated sky-circle radius (px). When provided, max_miss_px is
               scaled to it so the check is resolution-independent.

    Returns:
        (ok, message). When the check is skipped (insufficient anchors),
        returns ok=True with a note — we don't want to reject fits on
        cloudy/obstructed skies where bright anchors aren't visible.
    """
    if sky_r is not None:
        max_miss_px = max_miss_px * tol_scale(sky_r)

    bright = [
        (s, alt, az) for s, alt, az in above_horizon
        if alt >= min_alt_deg
    ][:top_n]

    if len(bright) < min_hits:
        return True, (f"only {len(bright)} bright anchors above "
                      f"{min_alt_deg:.0f}° — skipping validation")

    if not detected:
        return False, "no detected stars to validate against"

    det_xy = np.array([(dx, dy) for dx, dy, *_ in detected], dtype=float)

    hits = 0
    misses: List[Tuple[str, float]] = []
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

    if hits >= min_hits:
        return True, f"{hits}/{len(bright)} bright anchors matched"

    miss_str = ", ".join(
        f"{name}({d:.0f}px)" if np.isfinite(d) else f"{name}(off-image)"
        for name, d in misses[:5]
    )
    return False, (f"only {hits}/{len(bright)} bright anchors within "
                   f"{max_miss_px:.0f}px (missed: {miss_str})")


# ---------------------------------------------------------------------------
# Physical-plausibility check on the lens polynomial
# ---------------------------------------------------------------------------

# Physical fisheye lenses have modest-negative cubic coefficients (barrel
# distortion correction). A strongly-positive a3 would mean the lens becomes
# more curved with increasing angle, which no real fisheye design produces —
# it's always the optimiser compensating for a wrong orientation.
A3_MIN = -80.0
A3_MAX =  20.0

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
    return True, f"lens polynomial a3={a3:.1f} within plausible range"


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
