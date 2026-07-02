"""
Guided (anchor-assisted) all-sky calibration.

For installs where fully-automatic calibration can't determine orientation —
heavily obstructed views, near-vertical fisheyes, hazy skies — the user
identifies a handful of bright stars by clicking them in the latest frame and
naming each one. Those exact pixel <-> sky correspondences make the 8-parameter
fisheye pose well-determined regardless of equipment, latitude or obstruction,
so this is the dependable cold-start path; the background service then refines
the model over time.

This module owns ONLY the solve: given anchors + observer + sky circle, produce
a FisheyeModel. UI/threading live in ui/controllers/allsky_controller.py.

The projection ground truth is FisheyeModel.altaz_to_pixel() — never reimplement
the formula here (see docs/ALLSKY_CALIBRATION_PLAN.md).
"""
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import numpy as np

from services.logger import app_logger as log

try:
    from scipy.optimize import least_squares as _least_squares
except Exception as _e:  # pragma: no cover - scipy always present in prod
    _least_squares = None

from .fisheye import FisheyeModel
from .coords import radec_to_altaz
from .calibration import CalibrationError, _params_to_model
from .calibration_validate import (
    A3_MAX, A3_MIN, ORIENT_AXIS_ALT, ORIENT_AXIS_AZ, ORIENT_ROLL_DEG,
    REG_A3, REG_A5, a1_from_sky_radius, tol_scale,
    validate_a1_scale, validate_lens_polynomial,
)

# Minimum anchors. The pose has 6 free parameters here (cx/cy are fixed from the
# sky circle), i.e. 3 anchors = 6 residuals exactly determine it; 4+ gives
# overdetermination and a meaningful RMS. Require 4 for a trustworthy fit.
MIN_ANCHORS = 4

# With this many anchors the optical centre joins the fit (bounded near the
# sky-circle estimate). A slightly-off circle fit otherwise puts an RMS floor
# under even perfect identifications, pushing correct solves past the limit.
FREE_CENTRE_MIN_ANCHORS = 6
_CENTRE_RANGE_FRACTION = 0.05   # of sky radius, each axis

# a3 prior for the fit. Milder than the auto path's conservative default: exact
# anchors constrain a3 well, so this is just a gentle starting point.
_A3_PRIOR = -10.0

# Orientation grid (ORIENT_*) and ridge weights (REG_*) are shared with the
# multi-image fit via calibration_validate.


def calibrate_from_anchors(
    anchors: List[Tuple[float, float, float, float]],
    lat_deg: float,
    lon_deg: float,
    dt: Optional[datetime],
    sky_cx: float,
    sky_cy: float,
    sky_radius: float,
    image_width: int = 0,
    image_height: int = 0,
    max_rms_px: float = 15.0,
) -> FisheyeModel:
    """Solve a FisheyeModel from user-identified star anchors.

    Args:
        anchors: list of (pixel_x, pixel_y, ra_deg, dec_deg[, name]) — one per
            clicked and named star. RA/Dec are J2000-of-catalog (same frame the
            rest of the pipeline uses). The optional name is used only for
            per-anchor diagnostics in error messages.
        lat_deg, lon_deg: observer location.
        dt: capture time (UTC); defaults to now if None.
        sky_cx, sky_cy, sky_radius: sky-circle estimate (trimmed radius), used to
            fix the optical centre and seed a1.
        image_width/height: stored on the model for the renderer's scaling (F5).
        max_rms_px: reject the fit if anchor RMS exceeds this (scaled by sky_r).

    Returns:
        FisheyeModel (rms_residual = anchor RMS, n_matches = anchor count).

    Raises:
        CalibrationError on too few anchors, unresolved geometry, or high RMS.
    """
    if _least_squares is None:
        raise CalibrationError("scipy is required for guided calibration.")
    if len(anchors) < MIN_ANCHORS:
        raise CalibrationError(
            f"Need at least {MIN_ANCHORS} identified stars "
            f"(got {len(anchors)}) — click a few more spread across the sky."
        )
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    # Pixel targets and their catalog alt/az at capture time.
    px = np.array([(a[0], a[1]) for a in anchors], dtype=float)
    names = [str(a[4]) if len(a) > 4 else f"star {i + 1}"
             for i, a in enumerate(anchors)]
    alts = np.empty(len(anchors))
    azs = np.empty(len(anchors))
    for i, a in enumerate(anchors):
        alt, az = radec_to_altaz(float(a[2]), float(a[3]), lat_deg, lon_deg, dt)
        alts[i], azs[i] = float(alt), float(az)
    if np.any(alts <= 0):
        below = [n for n, a in zip(names, alts) if a <= 0]
        raise CalibrationError(
            f"Identified star(s) below the horizon at the capture time "
            f"({', '.join(below)}) — check the identifications and the "
            "system clock."
        )

    a1_seed = a1_from_sky_radius(sky_radius)
    cx, cy = float(sky_cx), float(sky_cy)
    rms_limit = max_rms_px * tol_scale(sky_radius)
    centre_range = (_CENTRE_RANGE_FRACTION * float(sky_radius)
                    if len(anchors) >= FREE_CENTRE_MIN_ANCHORS else 0.0)

    # Stage 1: refine EVERY top-k coarse candidate (fixed centre — lets the
    # orientation settle without the centre absorbing roll/axis errors) and
    # keep the best final RMS. The coarse grid has near-degenerate cells
    # (at axis_alt=90 many az/roll combos score alike), so trusting only the
    # single best cell drops the refine into a wrong basin on near-ties.
    # With a handful of anchors each refine is milliseconds.
    candidates = _coarse_search(alts, azs, px, cx, cy, a1_seed)
    model, rms = None, float('inf')
    for cand in candidates:
        m, r = _refine(alts, azs, px, cx, cy, a1_seed, cand)
        if r < rms:
            model, rms = m, r
    if centre_range > 0.0:
        # Stage 2: free the centre from the settled orientation. Only accept
        # the freed fit when it actually improves.
        settled = (0.0, model.east_left, model.axis_alt, model.axis_az,
                   float(np.degrees(model.roll)))
        model2, rms2 = _refine(alts, azs, px, cx, cy, model.a1,
                               settled, centre_range)
        if rms2 < rms:
            model, rms = model2, rms2

    if rms > rms_limit:
        raise CalibrationError(
            f"Guided calibration RMS {rms:.1f}px exceeds limit {rms_limit:.0f}px "
            f"over {len(anchors)} anchors. Per-star residuals: "
            f"{_residual_report(model, alts, azs, px, names)}. The largest "
            "residual usually marks a mis-identified or mis-clicked star — "
            "remove or re-click it and solve again."
        )

    poly_ok, poly_msg = validate_lens_polynomial(model)
    scale_ok, scale_msg = validate_a1_scale(model, sky_radius)
    if not (poly_ok and scale_ok):
        reason = "; ".join(m for ok, m in ((poly_ok, poly_msg),
                                           (scale_ok, scale_msg)) if not ok)
        raise CalibrationError(
            f"Guided calibration converged to an implausible model ({reason}). "
            f"Per-star residuals: {_residual_report(model, alts, azs, px, names)}."
        )

    model.image_width = int(image_width)
    model.image_height = int(image_height)
    model.n_matches = len(anchors)
    model.rms_residual = float(rms)
    model.calibrated_at = datetime.now(timezone.utc).isoformat()
    log.info(
        f"Guided calibration: {len(anchors)} anchors, RMS={rms:.2f}px, "
        f"east_left={model.east_left}, a1={model.a1:.1f}, "
        f"axis_alt={model.axis_alt:.1f}, axis_az={model.axis_az:.1f}"
    )
    return model


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _reproj_sq(model: FisheyeModel, alts, azs, px) -> float:
    """Sum of squared pixel reprojection errors over the anchors (vectorised)."""
    pxs, pys, vis = model.altaz_array_to_pixels(alts, azs)
    if not np.all(vis):
        return 1e12
    return float(np.sum((pxs - px[:, 0]) ** 2 + (pys - px[:, 1]) ** 2))


# Coarse candidates handed to the per-candidate refine. Near-degenerate grid
# cells (axis_alt=90 collapses az/roll into one rotation) can out-score the
# true cell before refinement; refining several candidates removes the
# sensitivity to which near-tie ranks first.
_COARSE_TOP_K = 5


def _coarse_search(alts, azs, px, cx, cy, a1):
    """Grid over (east_left, axis_alt, axis_az, roll) by anchor reprojection.

    Returns the top-_COARSE_TOP_K cells, best-first, each as
    (err, east_left, axis_alt, axis_az, roll_deg).
    """
    scored = []
    for east_left in (True, False):
        for axis_alt in ORIENT_AXIS_ALT:
            for axis_az in ORIENT_AXIS_AZ:
                for roll_deg in ORIENT_ROLL_DEG:
                    m = FisheyeModel(
                        cx=cx, cy=cy, a1=a1, a3=_A3_PRIOR, a5=0.0,
                        roll=np.radians(roll_deg), axis_alt=float(axis_alt),
                        axis_az=float(axis_az), east_left=east_left,
                    )
                    err = _reproj_sq(m, alts, azs, px)
                    scored.append((err, east_left, float(axis_alt),
                                   float(axis_az), float(roll_deg)))
    scored.sort(key=lambda t: t[0])
    return scored[:_COARSE_TOP_K]


def _refine(alts, azs, px, cx, cy, a1_seed, best, centre_range: float = 0.0):
    """least_squares refine of [a1, a3, a5, roll, axis_alt, axis_az].

    centre_range > 0 additionally frees cx/cy within ±centre_range of the
    sky-circle estimate (only offered with enough anchors to constrain them).
    """
    _err, east_left, axis_alt0, axis_az0, roll0 = best
    n_terms = float(np.sqrt(2 * len(alts)))
    tx, ty = px[:, 0], px[:, 1]
    free_centre = centre_range > 0.0

    def residuals(p):
        if free_centre:
            pcx, pcy, a1, a3, a5, roll, axis_alt, axis_az = p
        else:
            a1, a3, a5, roll, axis_alt, axis_az = p
            pcx, pcy = cx, cy
        m = _params_to_model(
            [pcx, pcy, a1, a3, a5, roll, axis_alt, axis_az], east_left)
        pxs, pys, vis = m.altaz_array_to_pixels(alts, azs)
        dx = np.where(vis, pxs - tx, 1e4)
        dy = np.where(vis, pys - ty, 1e4)
        # Ridge prior keeps the polynomial physical when anchors are sparse.
        return np.concatenate([dx, dy, [
            REG_A3 * n_terms * (a3 - _A3_PRIOR),
            REG_A5 * n_terms * a5,
        ]])

    p0 = [a1_seed, _A3_PRIOR, 0.0, np.radians(roll0), axis_alt0, axis_az0]
    lo = [50.0,  A3_MIN, -1500.0, -np.pi, 60.0, -180.0]
    hi = [2000.0, A3_MAX,  500.0,  np.pi, 90.0,  540.0]
    if free_centre:
        p0 = [cx, cy] + p0
        lo = [cx - centre_range, cy - centre_range] + lo
        hi = [cx + centre_range, cy + centre_range] + hi
    result = _least_squares(
        residuals, p0, bounds=(lo, hi),
        method='trf', max_nfev=8000, ftol=1e-6,
    )
    if free_centre:
        rcx, rcy, a1, a3, a5, roll, axis_alt, axis_az = result.x
    else:
        a1, a3, a5, roll, axis_alt, axis_az = result.x
        rcx, rcy = cx, cy
    model = _params_to_model(
        [rcx, rcy, a1, a3, a5, roll, axis_alt, axis_az % 360.0], east_left)
    rms = float(np.sqrt(_reproj_sq(model, alts, azs, px) / len(alts)))
    return model, rms


def _residual_report(model, alts, azs, px, names) -> str:
    """Per-anchor residual summary, worst first, for error messages."""
    pxs, pys, vis = model.altaz_array_to_pixels(alts, azs)
    entries = []
    for i, name in enumerate(names):
        if not vis[i]:
            entries.append((float('inf'), f"{name} (off-image)"))
            continue
        d = float(np.hypot(pxs[i] - px[i, 0], pys[i] - px[i, 1]))
        entries.append((d, f"{name} {d:.0f}px"))
    entries.sort(key=lambda e: -e[0])
    return ", ".join(text for _d, text in entries)
