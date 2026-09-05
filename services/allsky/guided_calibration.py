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

The solve is outlier-tolerant: when the full anchor set fails the RMS limit,
one or two anchors are excluded (worst-first) and, where the excluded click
sits on a different catalog star through the consensus model, the anchor is
reinstated under the corrected identity. Field data 2026-07-02: a Big Dipper
handle mix-up ("Alkaid" clicked on Mizar) plus one sloppy click took an
otherwise-perfect 7-anchor set from RMS 55px to a passing solve.

The projection ground truth is FisheyeModel.altaz_to_pixel() — never reimplement
the formula here (see docs/ALLSKY_CALIBRATION_PLAN.md).
"""
import itertools
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
# overdetermination and a meaningful RMS. Require 5 — not 4 — because
# FisheyeModel.is_valid() hard-requires n_matches >= 5 (fisheye.py); a 4-anchor
# solve used to sail through this module's own checks, get saved to disk as
# "Calibrated: 4 stars", and then read back as "Not calibrated" on the next
# load (is_valid() rejects it, and the overlay never rendered in between
# either). MIN_ANCHORS must never be lower than FisheyeModel's floor.
MIN_ANCHORS = 5

# With this many anchors the optical centre joins the fit (bounded near the
# sky-circle estimate). A slightly-off circle fit otherwise puts an RMS floor
# under even perfect identifications, pushing correct solves past the limit.
# 5 (not 6): on the field rig the circle estimate sits ~165px from the true
# centre, and a frozen-centre 5-anchor solve of five verified-correct clicks
# bottomed out at 27.5px (2026-07-02 23:43 attempt). Freed, the same anchors
# solved at 7.5px and matched the independent 7-anchor consensus to a few px,
# while a deliberate mis-ID still failed loudly (40.6px) — 10 observations
# against 8 parameters plus the ridge priors and admission gates held. Equal
# to MIN_ANCHORS: the smallest solvable anchor set already frees the centre,
# so there is no longer a frozen-centre tier at all — verified feasible
# above (5 anchors = 10 observations vs. 8 free params with the centre freed).
FREE_CENTRE_MIN_ANCHORS = 5

# Progressive centre leash (fractions of sky radius, each axis). The first
# stage always runs; wider stages run only while the fit still fails the RMS
# limit, so a well-estimated circle keeps the tight leash. Field data
# 2026-07-02: after the camera was physically re-mounted the true centre sat
# ~0.15·sky_r from the circle estimate — a fixed 5% leash pinned the fit at
# the range corner (RMS 14.5px) where 15% solved the same anchors at 1.8px.
_CENTRE_RANGE_FRACTIONS = (0.05, 0.10, 0.15)

# Outlier rescue: an excluded anchor may be reinstated as the catalog star
# its click actually lands on, if that star is within this fraction of the
# sky radius (matches the click-snap scale) and at least this bright.
_REASSIGN_RADIUS_FRACTION = 0.05
_REASSIGN_MAX_MAG = 3.5

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

    # Full input record at INFO — a failed attempt must be replayable from
    # the log alone (we lost a night's diagnosis to unlogged click pixels).
    log.info(
        f"Guided solve input: dt={dt.isoformat()}, "
        f"sky_circle=({cx:.0f}, {cy:.0f}, r={float(sky_radius):.0f}), "
        f"rms_limit={rms_limit:.1f}px, anchors: "
        + "; ".join(f"{n}@({a[0]:.1f},{a[1]:.1f}) ra={a[2]:.4f} dec={a[3]:.4f}"
                    for n, a in zip(names, anchors))
    )

    model, rms = _solve_anchor_set(alts, azs, px, cx, cy, a1_seed,
                                   sky_radius, rms_limit)

    note = None
    used = list(range(len(anchors)))
    if rms > rms_limit and len(anchors) > MIN_ANCHORS:
        rescue = _rescue_outliers(
            model, names, alts, azs, px, cx, cy, a1_seed, sky_radius,
            rms_limit, anchors, lat_deg, lon_deg, dt)
        if rescue is not None:
            model, rms, note, used, names, alts, azs = rescue

    if rms > rms_limit:
        raise CalibrationError(
            f"Guided calibration RMS {rms:.1f}px exceeds limit {rms_limit:.0f}px "
            f"over {len(anchors)} anchors. Per-star residuals: "
            f"{_residual_report(model, alts, azs, px, names)}. The largest "
            "residual usually marks a mis-identified or mis-clicked star — "
            "remove or re-click it and solve again."
        )

    idx = np.array(used)
    poly_ok, poly_msg = validate_lens_polynomial(model)
    scale_ok, scale_msg = validate_a1_scale(model, sky_radius)
    if not (poly_ok and scale_ok):
        reason = "; ".join(m for ok, m in ((poly_ok, poly_msg),
                                           (scale_ok, scale_msg)) if not ok)
        raise CalibrationError(
            f"Guided calibration converged to an implausible model ({reason}). "
            f"Per-star residuals: "
            f"{_residual_report(model, alts[idx], azs[idx], px[idx], [names[i] for i in used])}."
        )

    model.image_width = int(image_width)
    model.image_height = int(image_height)
    model.n_matches = len(used)
    model.rms_residual = float(rms)
    model.calibrated_at = datetime.now(timezone.utc).isoformat()
    # Human-identified anchors outrank every model-free measurement in the
    # admission gates (see model_admission.py) — mark the basin as such.
    model.provenance = 'guided'
    if note:
        model.guided_note = note   # session-only; surfaced in the status msg
        log.warning(f"Guided calibration rescue: {note}")
    log.info(
        f"Guided calibration: {len(used)}/{len(anchors)} anchors, "
        f"RMS={rms:.2f}px, east_left={model.east_left}, a1={model.a1:.1f}, "
        f"axis_alt={model.axis_alt:.1f}, axis_az={model.axis_az:.1f}"
    )
    return model


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _solve_anchor_set(alts, azs, px, cx, cy, a1_seed, sky_radius, rms_limit):
    """Solve one anchor set: coarse orientation search, per-candidate refine,
    then progressive centre freeing.

    Stage 1 refines EVERY top-k coarse candidate (fixed centre — lets the
    orientation settle without the centre absorbing roll/axis errors) and
    keeps the best final RMS. The coarse grid has near-degenerate cells
    (at axis_alt=90 many az/roll combos score alike), so trusting only the
    single best cell drops the refine into a wrong basin on near-ties.

    Stage 2 (>=FREE_CENTRE_MIN_ANCHORS) frees the centre from the settled
    orientation, widening the leash only while the fit still fails the
    limit, and only ever accepting an improvement.
    """
    candidates = _coarse_search(alts, azs, px, cx, cy, a1_seed)
    model, rms = None, float('inf')
    for cand in candidates:
        m, r = _refine(alts, azs, px, cx, cy, a1_seed, cand)
        if r < rms:
            model, rms = m, r
    if len(alts) >= FREE_CENTRE_MIN_ANCHORS:
        for stage, frac in enumerate(_CENTRE_RANGE_FRACTIONS):
            if stage and rms <= rms_limit:
                break
            settled = (0.0, model.east_left, model.axis_alt, model.axis_az,
                       float(np.degrees(model.roll)))
            m2, r2 = _refine(alts, azs, px, cx, cy, model.a1, settled,
                             frac * float(sky_radius))
            if r2 < rms:
                model, rms = m2, r2
    return model, rms


def _rescue_outliers(full_model, names, alts, azs, px, cx, cy, a1_seed,
                     sky_radius, rms_limit, anchors, lat_deg, lon_deg, dt):
    """Recover from one or two bad anchors in a failed full solve.

    Try every single-anchor exclusion (then pairs from the worst three when
    enough anchors remain) and keep the subset with the best passing RMS —
    the suspect ranking comes from the failed full model, which may itself
    sit in a wrong basin, so first-passing is not good enough. A passing
    subset gives a trustworthy consensus model; each excluded click is then
    audited against the catalog through it — if the click sits on a
    *different* bright star, the anchor is reinstated under that identity
    and the full set re-solved (a mis-identification, the common case, loses
    no data). Otherwise the anchor stays excluded (a mis-click).

    Returns (model, rms, note, used_indices, names, alts, azs) or None if
    no subset passes.
    """
    n = len(alts)
    pxs, pys, vis = full_model.altaz_array_to_pixels(alts, azs)
    res = np.where(vis, np.hypot(pxs - px[:, 0], pys - px[:, 1]), np.inf)
    order = [int(i) for i in np.argsort(-res)]

    def try_drop(drop):
        keep = [k for k in range(n) if k not in drop]
        if len(keep) < MIN_ANCHORS:
            return None
        # A MIN_ANCHORS-sized subset barely overdetermines the pose (10
        # observations vs 8 free parameters — the centre is freed at exactly
        # this size, see FREE_CENTRE_MIN_ANCHORS), so its RMS gate has little
        # power — demand a clearly better fit before trusting it.
        limit = rms_limit if len(keep) > MIN_ANCHORS else 0.5 * rms_limit
        idx = np.array(keep)
        m, r = _solve_anchor_set(alts[idx], azs[idx], px[idx], cx, cy,
                                 a1_seed, sky_radius, limit)
        return (r, drop, keep, m) if r <= limit else None

    passing = [t for t in (try_drop((i,)) for i in order) if t is not None]
    if not passing and n >= MIN_ANCHORS + 2:
        passing = [t for t in (try_drop(d) for d in
                               itertools.combinations(order[:3], 2))
                   if t is not None]
    if not passing:
        return None
    r, drop, keep, m = min(passing, key=lambda t: t[0])

    # Audit each excluded click against the consensus model: does it sit on
    # a different catalog star than the user named? Identities already held
    # by kept anchors (or claimed by a previous hit) are off-limits so a
    # rescue can never assign two anchors to the same star.
    taken = [(float(anchors[k][2]), float(anchors[k][3])) for k in keep]
    hits = {}
    for i in drop:
        hit = _nearest_catalog_star(
            m, float(px[i, 0]), float(px[i, 1]), lat_deg, lon_deg, dt,
            sky_radius,
            exclude_radecs=taken + [(float(anchors[i][2]),
                                     float(anchors[i][3]))])
        if hit is not None:
            hits[i] = hit
            taken.append((hit[1], hit[2]))

    if hits and len(hits) == len(drop):
        alts2, azs2 = alts.copy(), azs.copy()
        names2 = list(names)
        for i, (star_name, ra, dec, dist) in hits.items():
            alt, az = radec_to_altaz(ra, dec, lat_deg, lon_deg, dt)
            alts2[i], azs2[i] = float(alt), float(az)
            names2[i] = star_name
        m2, r2 = _solve_anchor_set(alts2, azs2, px, cx, cy, a1_seed,
                                   sky_radius, rms_limit)
        if r2 <= rms_limit:
            swaps = ", ".join(
                f"'{names[i]}' is actually {hits[i][0]} "
                f"({hits[i][3]:.0f}px from its catalog position)"
                for i in drop)
            note = (f"Corrected identification: {swaps}. "
                    f"All {n} anchors used.")
            return m2, r2, note, list(range(n)), names2, alts2, azs2

    dropped_txt = ", ".join(f"'{names[i]}'" for i in drop)
    hint = "".join(
        f" The '{names[i]}' click sits near {hits[i][0]} — if that is "
        f"what you clicked, re-identify it."
        for i in drop if i in hits)
    note = (f"Solved from {len(keep)} of {n} anchors — {dropped_txt} "
            f"did not fit the consensus and was excluded (mis-click or "
            f"mis-identification).{hint}")
    return m, r, note, keep, list(names), alts, azs


def _nearest_catalog_star(model, x, y, lat_deg, lon_deg, dt, sky_radius,
                          exclude_radecs):
    """Nearest bright catalog star to pixel (x, y) through `model`.

    Returns (name, ra_deg, dec_deg, dist_px) when the nearest star not in
    `exclude_radecs` (the anchor's original identity plus every identity
    already assigned to another anchor) lies within the reassignment
    radius; None otherwise.
    """
    from .catalogs import get_bright_stars
    best = None
    for s in get_bright_stars(max_mag=_REASSIGN_MAX_MAG):
        if any(abs(s['ra_deg'] - ra) < 1e-3 and abs(s['dec_deg'] - dec) < 1e-3
               for ra, dec in exclude_radecs):
            continue
        alt, az = radec_to_altaz(s['ra_deg'], s['dec_deg'],
                                 lat_deg, lon_deg, dt)
        if float(alt) <= 0.0:
            continue
        xy = model.altaz_to_pixel(float(alt), float(az))
        if xy is None:
            continue
        d = float(np.hypot(xy[0] - x, xy[1] - y))
        if best is None or d < best[3]:
            best = (s.get('name') or f"HR{s.get('hr', '?')}",
                    float(s['ra_deg']), float(s['dec_deg']), d)
    if best is not None and best[3] <= _REASSIGN_RADIUS_FRACTION * float(sky_radius):
        return best
    return None


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
