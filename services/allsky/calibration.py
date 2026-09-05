"""
All-sky camera fisheye lens calibration.

Algorithm:
  1. Detect stars in the frame (OpenCV blob detection + weighted centroid)
  2. Grid-search over a1 (radial scale) to find the best initial model
  3. Match detected stars to BSC5 catalog using the best initial model
  4. Iteratively fit fisheye polynomial model with scipy.optimize.least_squares
  5. Converge until median residual < 2px or max iterations reached
  6. Reject matches if < min_matches or residual > max_residual_px (fail gracefully)

Dependencies: scipy (must be available; removed from PyInstaller excludes).
"""
import numpy as np
from datetime import datetime, timezone
from typing import List, Tuple, Optional, Dict

from services.logger import app_logger as log

# Pre-import scipy submodules at module level so background threads
# never trigger a first-time import (causes segfault in PyInstaller).
_scipy_import_error: Optional[str] = None
try:
    from scipy.spatial.distance import cdist as _cdist
    from scipy.optimize import least_squares as _least_squares
except Exception as _e:
    _cdist = None
    _least_squares = None
    _scipy_import_error = f"{type(_e).__name__}: {_e}"
    log.error(f"scipy import failed at module load: {_scipy_import_error}")

from .star_centroid import detect_stars, fallback_sky_circle, measure_sky_circle
from .fisheye import FisheyeModel
from .catalogs import get_bright_stars
from .coords import radec_to_altaz
from .calibration_validate import (
    A3_MAX,
    A3_MIN,
    A3_SEED_DEFAULT,
    score_matches_with_spread,
    validate_a1_scale,
    validate_bright_anchors,
    validate_lens_polynomial,
    warn_sky_coverage,
    tol_scale,
)



def calibrate(
    image,
    lat_deg: float,
    lon_deg: float,
    dt: Optional[datetime] = None,
    max_stars: int = 200,
    min_matches: int = 8,
    max_residual_px: float = 15.0,
    image_cx: Optional[float] = None,
    image_cy: Optional[float] = None,
    sky_radius_px: Optional[float] = None,
) -> FisheyeModel:
    """
    Calibrate fisheye lens from a clear-sky all-sky image.

    Args:
        image: PIL Image or numpy array (clear-sky frame).
        lat_deg: Observer latitude (degrees, north positive).
        lon_deg: Observer longitude (degrees, east positive).
        dt: UTC datetime of the frame (defaults to now).
        max_stars: Max detected stars to use.
        min_matches: Minimum required star matches.
        max_residual_px: Maximum allowed median residual to accept calibration.
        image_cx: Optical centre x guess (default = image width / 2).
        image_cy: Optical centre y guess (default = image height / 2).
        sky_radius_px: Known sky circle radius in pixels. If provided, only that
                       a1 value is tested; otherwise a grid search is performed.

    Returns:
        Calibrated FisheyeModel.

    Raises:
        CalibrationError on insufficient matches or poor fit.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)

    # --- Step 1: Auto-detect sky circle, then detect stars inside it ---
    # The sky circle is measured once here so both detection and the initial
    # optical-centre guess use the same circle.
    # _sky_r_ref is the radius the scale-dependent gates and tolerances see:
    # None when the circle was never measured, so they run at native scale
    # instead of judging the fit against an assumed frame-filling disc.
    _sky_r_ref: Optional[float]
    if sky_radius_px is not None:
        img_h, img_w = _get_image_size(image)
        _sky_cx = image_cx if image_cx is not None else img_w / 2.0
        _sky_cy = image_cy if image_cy is not None else img_h / 2.0
        _sky_r  = sky_radius_px
        _sky_r_ref = _sky_r
    elif (circle := measure_sky_circle(image)) is not None:
        _sky_cx, _sky_cy, _sky_r = circle
        _sky_r_ref = _sky_r
        log.info(f"Calibration: sky circle measured at "
                 f"({_sky_cx:.0f}, {_sky_cy:.0f}) r={_sky_r:.0f}px")
    else:
        img_h, img_w = _get_image_size(image)
        _sky_cx, _sky_cy, _sky_r = fallback_sky_circle(img_w, img_h)
        _sky_r_ref = None
        log.warning(
            "Calibration: sky circle NOT measured (no illuminated disc found) — "
            f"detecting inside a frame-centred fallback r={_sky_r:.0f}px; the "
            "a1-scale gate is skipped and tolerances run at native scale")

    detected = detect_stars(
        image, max_stars=max_stars,
        sky_cx=_sky_cx, sky_cy=_sky_cy, sky_radius=_sky_r,
    )
    log.info(f"Calibration: detected {len(detected)} candidate stars")

    if len(detected) < min_matches:
        raise CalibrationError(
            f"Only {len(detected)} stars detected — need ≥ {min_matches} "
            "for calibration. Ensure a clear night sky with good seeing."
        )

    # --- Step 2: Get image dimensions and optical-centre guess ---
    img_h, img_w = _get_image_size(image)
    cx0 = image_cx if image_cx is not None else _sky_cx
    cy0 = image_cy if image_cy is not None else _sky_cy

    # --- Step 3: Load catalog stars, compute AltAz ---
    catalog = get_bright_stars(max_mag=6.5)
    cat_altaz = _catalog_altaz(catalog, lat_deg, lon_deg, dt)
    above_horizon = [(s, alt, az) for s, alt, az in cat_altaz if alt > 3.0]
    above_horizon.sort(key=lambda x: x[0]['vmag'])
    log.info(f"Calibration: {len(above_horizon)} catalog stars above horizon")

    if len(above_horizon) < min_matches:
        raise CalibrationError(
            f"Only {len(above_horizon)} catalog stars above horizon — "
            "check lat/lon configuration and UTC datetime."
        )

    # Resolution-independent match tolerances: scale every pixel tolerance by
    # the actual sky radius relative to the reference resolution (F10).
    _tol_scale = tol_scale(_sky_r_ref)

    # --- Step 4: Grid search for best initial a1 ---
    model, matches = _find_best_initial_model(
        detected, above_horizon, cx0, cy0, sky_radius_px, tol_scale=_tol_scale,
    )
    log.info(f"Calibration: best initial model a1={model.a1:.1f}, "
             f"{len(matches)} initial matches")

    if len(matches) < max(3, min_matches // 3):
        # --- Fallback: triangle hash matching ---
        try:
            from .triangle_match import triangle_calibrate
            log.info("Grid search matched too few stars — trying triangle hash fallback")
            return triangle_calibrate(
                image, lat_deg, lon_deg, dt,
                detected=detected, above_horizon=above_horizon,
                sky_cx=_sky_cx, sky_cy=_sky_cy, sky_radius=_sky_r,
                min_matches=min_matches, max_residual_px=max_residual_px,
            )
        except CalibrationError as e:
            log.info(f"Triangle fallback also failed: {e}")

        raise CalibrationError(
            f"Could not match enough stars ({len(matches)}) even after grid search. "
            f"Detected {len(detected)} stars, {len(above_horizon)} catalog stars above horizon.\n"
            "Suggestions:\n"
            "  - Verify lat/lon and UTC datetime are correct\n"
            "  - Use a raw/unresized image for better star detection\n"
            "  - Pass --sky-radius <pixels> if you know the sky circle size\n"
            "  - Calibrate on a clear night with more stars visible"
        )

    # --- Step 5: Iterative fit ---
    model, rms = _iterative_fit(
        matches, model, lat_deg, lon_deg, dt,
        above_horizon, detected, min_matches, max_residual_px,
        tol_scale=_tol_scale,
    )

    if rms > max_residual_px:
        raise CalibrationError(
            f"Calibration residual {rms:.1f}px exceeds limit {max_residual_px}px. "
            "Frame may not be a clear-sky all-sky image."
        )

    # --- Step 6: Sanity-check the fit ---
    # Three independent guards — all must pass, or we fall through to the
    # triangle-hash fallback:
    #   (a) lens polynomial within physical range (and not pinned at a bound)
    #       — rejects cases where the optimiser bent the radial curve to fit
    #       a wrong orientation.
    #   (b) a1 consistent with the measured sky circle — rejects fits that
    #       converged at the wrong plate scale.
    #   (c) the brightest N anchors actually land on detected stars —
    #       rejects spurious density-noise fits that look fine on average
    #       but miss Sirius/Vega/etc. by 100+ px.
    poly_ok, poly_msg = validate_lens_polynomial(model)
    scale_ok, scale_msg = validate_a1_scale(model, _sky_r_ref)
    anch_ok, anch_msg = validate_bright_anchors(
        model, above_horizon, detected, sky_r=_sky_r_ref)
    if not (poly_ok and scale_ok and anch_ok):
        reason = "; ".join(m for ok, m in ((poly_ok, poly_msg),
                                           (scale_ok, scale_msg),
                                           (anch_ok, anch_msg)) if not ok)
        log.warning(
            f"Grid calibration failed sanity check: {reason}. "
            "Falling through to triangle-hash fallback."
        )
        try:
            from .triangle_match import triangle_calibrate
            return triangle_calibrate(
                image, lat_deg, lon_deg, dt,
                detected=detected, above_horizon=above_horizon,
                sky_cx=_sky_cx, sky_cy=_sky_cy, sky_radius=_sky_r,
                min_matches=min_matches, max_residual_px=max_residual_px,
            )
        except CalibrationError as e:
            raise CalibrationError(
                f"Grid fit failed sanity check ({reason}); "
                f"triangle-hash fallback also failed: {e}"
            )
    log.info(f"Sanity checks passed: {poly_msg}; {scale_msg}; {anch_msg}")

    warn_sky_coverage(model)

    model.image_width = img_w
    model.image_height = img_h
    model.calibrated_at = datetime.now(timezone.utc).isoformat()
    log.info(f"Calibration succeeded: {model}")
    return model


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

class CalibrationError(Exception):
    pass


def _find_best_initial_model(
    detected: List[Tuple],
    above_horizon: List[Tuple],
    cx0: float,
    cy0: float,
    sky_radius_px: Optional[float],
    tol_scale: float = 1.0,
) -> Tuple[FisheyeModel, List[Tuple]]:
    """
    Grid search over a1, axis_alt, and axis_az to find the initial model that
    produces the most star matches.

    Searches:
      a1        — radial scale (px/rad), derived from sky circle radius fractions
      axis_alt  — camera tilt from horizontal (60..90 deg), covers straight-up
                  and moderately-tilted all-sky mounts
      axis_az   — direction of tilt (0..315 deg, 8 compass points); only swept
                  for tilted cameras — at axis_alt=90 all azimuths are equivalent
      cx/cy     — small offsets around the sky-circle centre estimate

    For equidistant projection: a1 = sky_radius_px / (pi/2)
    """
    min_half = min(cx0, cy0)

    if sky_radius_px is not None:
        a1_candidates = [sky_radius_px / (np.pi / 2.0)]
    else:
        radii_fractions = [0.40, 0.50, 0.58, 0.65, 0.72, 0.78, 0.83, 0.88, 0.92, 0.96, 0.99]
        a1_candidates = [min_half * f / (np.pi / 2.0) for f in radii_fractions]

    # axis_alt candidates: 90 (zenith), plus tilted cases down to 60 deg.
    # For axis_alt=90 azimuth is irrelevant; for tilted cameras sweep 8 compass points.
    axis_orientation_candidates = [
        (90.0, [0.0]),
        (80.0, [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]),
        (70.0, [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]),
        (60.0, [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]),
    ]

    # Try both image orientations: FITS/astronomical (east=LEFT) and normal photo (east=RIGHT).
    # The one that produces more star matches is the correct convention for this camera.
    east_left_candidates = [True, False]

    best_matches: List[Tuple] = []
    best_model: Optional[FisheyeModel] = None
    best_score = -1.0

    for east_left in east_left_candidates:
        for a1 in a1_candidates:
            for axis_alt, az_list in axis_orientation_candidates:
                for axis_az in az_list:
                    for dcx, dcy in [(0, 0), (-20, 0), (20, 0), (0, -20), (0, 20)]:
                        model = FisheyeModel(
                            cx=cx0 + dcx, cy=cy0 + dcy,
                            a1=a1,
                            axis_alt=axis_alt,
                            axis_az=axis_az,
                            east_left=east_left,
                        )
                        matches = _brightness_match(detected, above_horizon, model,
                                                    tol_px=50.0 * tol_scale)
                        score = score_matches_with_spread(matches)
                        if score > best_score:
                            best_score = score
                            best_matches = matches
                            best_model = model

            log.debug(f"  east_left={east_left} a1={a1:.1f}: best score={best_score:.1f} "
                      f"({len(best_matches)} matches)")

    mirror_str = "east=LEFT (FITS)" if best_model.east_left else "east=RIGHT (photo)"
    log.info(f"Initial grid search complete: best score={best_score:.1f} "
             f"({len(best_matches)} matches), "
             f"a1={best_model.a1:.1f}, axis_alt={best_model.axis_alt:.1f}, "
             f"axis_az={best_model.axis_az:.1f}, {mirror_str}")

    if best_model is None:
        best_model = FisheyeModel(cx=cx0, cy=cy0, a1=min_half / (np.pi / 2.0))

    # --- Phase 2: roll sweep on the best model found ---
    # The phase-1 grid never varies roll (default 0°).  Cameras with a
    # non-zero physical roll (image rotated relative to North) will have
    # yielded a sub-optimal phase-1 match.  Sweeping 16 roll angles here
    # costs only 16 extra _brightness_match calls — negligible overhead.
    best_model, best_matches, best_score = _roll_sweep(
        best_model, best_matches, best_score, detected, above_horizon,
        tol_px=50.0 * tol_scale,
    )
    log.info(f"  Roll sweep: best roll={np.degrees(best_model.roll):.1f}°, "
             f"score={best_score:.1f} ({len(best_matches)} matches)")

    return best_model, best_matches


def _roll_sweep(
    model: FisheyeModel,
    current_matches: list,
    current_score: float,
    detected: list,
    above_horizon: list,
    tol_px: float,
) -> tuple:
    """
    Sweep 16 roll angles (0° – 337.5°) on a fixed base model and return
    whichever roll produces the best spread-weighted score.

    Roll is degenerate with axis_az when axis_alt=90 in a single image, but
    the sweep still ensures the iterative fit starts from the right basin.
    """
    best_model = model
    best_matches = current_matches
    best_score = current_score

    for k in range(16):
        roll_r = k * np.pi / 8.0   # 0°, 22.5°, 45° … 337.5°
        candidate = FisheyeModel(
            cx=model.cx, cy=model.cy,
            a1=model.a1,
            axis_alt=model.axis_alt,
            axis_az=model.axis_az,
            east_left=model.east_left,
            roll=roll_r,
        )
        matches = _brightness_match(detected, above_horizon, candidate, tol_px=tol_px)
        score = score_matches_with_spread(matches)
        if score > best_score:
            best_score = score
            best_matches = matches
            best_model = candidate

    return best_model, best_matches, best_score


def _get_image_size(image) -> Tuple[int, int]:
    """Return (height, width) of image."""
    try:
        from PIL import Image as PILImage
        if isinstance(image, PILImage.Image):
            w, h = image.size
            return h, w
    except ImportError:
        pass
    if hasattr(image, 'shape'):
        return image.shape[0], image.shape[1]
    return 1080, 1920


def _catalog_altaz(
    catalog: List[Dict],
    lat: float,
    lon: float,
    dt: datetime,
) -> List[Tuple[Dict, float, float]]:
    """Return [(star_dict, alt_deg, az_deg), ...] for catalog stars."""
    results = []
    for star in catalog:
        alt, az = radec_to_altaz(
            star['ra_deg'], star['dec_deg'], lat, lon, dt, refraction=True
        )
        results.append((star, float(alt), float(az)))
    return results


def _altaz_to_xy(alt: float, az: float, model: FisheyeModel):
    """Project a single catalog star to pixel space using current model."""
    return model.altaz_to_pixel(alt, az)


def _brightness_match(
    detected: List[Tuple],
    catalog_sorted: List[Tuple],
    model: FisheyeModel,
    tol_px: float,
) -> List[Tuple]:
    """
    Match detected stars to catalog stars by proximity in pixel space.

    Uses vectorised distance matrix (scipy cdist when available, numpy
    fallback otherwise) for O(D*C) instead of a nested Python loop.
    catalog_sorted is sorted by vmag (brightest first).
    Returns [(detected_xy, star_dict, cat_altaz), ...] match list.
    """
    # Project top catalog stars to pixel space
    n_catalog = min(len(detected) * 5, 400)
    projected = []
    for i, (star, alt, az) in enumerate(catalog_sorted[:n_catalog]):
        xy = _altaz_to_xy(alt, az, model)
        if xy is not None:
            projected.append((i, star, xy, alt, az))

    if not projected or not detected:
        return []

    # Build coordinate arrays for vectorised matching
    det_xy = np.array([(dx, dy) for dx, dy, _ in detected])
    cat_xy = np.array([(cx, cy) for _, _, (cx, cy), _, _ in projected])

    # All-pairs distance matrix  (D × C)
    if _cdist is not None:
        dists = _cdist(det_xy, cat_xy)
    else:
        diff = det_xy[:, np.newaxis, :] - cat_xy[np.newaxis, :, :]
        dists = np.sqrt(np.sum(diff * diff, axis=2))

    # Greedy 1-to-1 nearest-neighbour assignment (brightest catalog first)
    matches = []
    used_det = set()
    used_cat = set()

    # For each detected star find the closest projected catalog star
    best_cat = np.argmin(dists, axis=1)
    best_dist = dists[np.arange(len(detected)), best_cat]

    # Sort by best distance so the tightest pairs are assigned first
    order = np.argsort(best_dist)
    for d_idx in order:
        c_local = int(best_cat[d_idx])
        if best_dist[d_idx] >= tol_px:
            continue
        if d_idx in used_det or c_local in used_cat:
            # Slot taken — find next-best unused catalog star
            row = dists[d_idx]
            sorted_cats = np.argsort(row)
            found = False
            for c2 in sorted_cats:
                if row[c2] >= tol_px:
                    break
                if c2 not in used_cat:
                    c_local = int(c2)
                    found = True
                    break
            if not found:
                continue

        c_orig_idx, star, _xy, alt, az = projected[c_local]
        dx, dy, _ = detected[d_idx]
        matches.append(((dx, dy), star, (alt, az)))
        used_det.add(d_idx)
        used_cat.add(c_local)

    return matches


def _iterative_fit(
    matches, model, lat, lon, dt, above_horizon, detected, min_matches, max_residual,
    tol_scale: float = 1.0,
):
    """Iterative fit with scipy.optimize.least_squares."""
    if _least_squares is None:
        detail = f" (import error: {_scipy_import_error})" if _scipy_import_error else ""
        raise CalibrationError(
            f"scipy is required for calibration. Install scipy>=1.10.0.{detail}"
        )

    # east_left is discrete — fixed from grid search, not part of continuous optimisation.
    east_left = model.east_left

    # Physical prior: real fisheye lenses have modest-negative a3 (barrel
    # distortion correction). Seeding a3=0 gives the optimiser no hint and
    # lets it drift into unphysical positive territory when prunings shrink
    # the match set. A3_SEED_DEFAULT is a conservative prior that still allows
    # the fit to recover a3 in roughly [-80, 0] for real lenses.
    if abs(model.a3) < 1e-6:
        model.a3 = A3_SEED_DEFAULT

    # a3/a5 bounds tightened to physical range for fisheye lenses. Wide-open
    # bounds let the optimiser bend the polynomial to fit a handful of
    # zenith-region stars while abandoning far-from-axis ones; the residual
    # RMS looks fine but the sky is rotated wrong.
    fit_lo = np.array([50.0, 50.0, 50.0, A3_MIN, -1500.0, -np.pi, 60.0, 0.0])
    fit_hi = np.array([4000.0, 4000.0, 2000.0, A3_MAX, 500.0, np.pi, 90.0, 360.0])

    for iteration in range(8):
        params = np.array([
            model.cx, model.cy, model.a1, model.a3, model.a5,
            model.roll, model.axis_alt, model.axis_az,
        ])
        # A seed from a grid/triangle hypothesis can sit outside the fit
        # bounds — the triangle orientation extraction admits axis_alt >= 45
        # and returns roll/axis_az unwrapped — and least_squares('trf')
        # rejects an infeasible x0 outright ("Initial guess is outside of
        # provided bounds"), aborting refinement of an otherwise-correct
        # hypothesis. Wrap the angles and clamp instead.
        params[5] = (params[5] + np.pi) % (2.0 * np.pi) - np.pi
        params[7] = params[7] % 360.0
        params = np.clip(params, fit_lo, fit_hi)

        def residuals(p):
            m = _params_to_model(p, east_left)
            res = []
            for (dx, dy), _star, (alt, az) in matches:
                xy = m.altaz_to_pixel(alt, az)
                if xy is None:
                    res.extend([30.0, 30.0])
                else:
                    res.extend([dx - xy[0], dy - xy[1]])
            return res

        try:
            result = _least_squares(
                residuals, params,
                bounds=(fit_lo, fit_hi),
                method='trf',
                max_nfev=8000,
                ftol=1e-5,
            )
            model = _params_to_model(result.x, east_left)
        except Exception as e:
            log.warning(f"Calibration fit iteration {iteration} failed: {e}")
            break

        # Re-match with tighter tolerance as fit improves. The 50->10 px
        # schedule shape is preserved (an invariant); only the endpoints are
        # scaled to the sky radius so behaviour is resolution-independent.
        tol = tol_scale * max(10.0, 50.0 - iteration * 6.0)
        matches = _brightness_match(detected, above_horizon, model, tol_px=tol)
        rms = _compute_rms(matches, model)
        log.info(f"  Iteration {iteration}: {len(matches)} matches, RMS={rms:.2f}px, "
                 f"tol={tol:.0f}px")

        if rms < 2.0 and len(matches) >= min_matches:
            break

    model.n_matches = len(matches)
    model.rms_residual = float(_compute_rms(matches, model))

    # Build per-match diagnostics so the debug tool can show which stars were matched
    matched_stars = []
    for (dx, dy), star, (alt, az) in matches:
        cat_px = model.altaz_to_pixel(alt, az)
        res_px = float(np.hypot(dx - cat_px[0], dy - cat_px[1])) if cat_px else 999.0
        matched_stars.append({
            'name': star.get('name', ''),
            'vmag': float(star.get('vmag', 0.0)),
            'alt': float(alt),
            'az': float(az),
            'detected_px': (float(dx), float(dy)),
            'catalog_px': (float(cat_px[0]), float(cat_px[1])) if cat_px else None,
            'residual_px': res_px,
        })
    matched_stars.sort(key=lambda s: s['residual_px'])
    model.matched_stars = matched_stars

    return model, model.rms_residual


def _params_to_model(p, east_left: bool = True) -> FisheyeModel:
    """Build a FisheyeModel from an 8-element parameter vector.
    east_left is not part of the continuous optimisation — it is fixed at
    whichever orientation the grid search found to be correct.
    """
    return FisheyeModel(
        cx=p[0], cy=p[1], a1=p[2], a3=p[3], a5=p[4],
        roll=p[5], axis_alt=p[6], axis_az=p[7],
        east_left=east_left,
    )


def _compute_rms(matches, model) -> float:
    if not matches:
        return 999.0
    residuals = []
    for (dx, dy), _star, (alt, az) in matches:
        xy = model.altaz_to_pixel(alt, az)
        if xy is not None:
            residuals.append(np.hypot(dx - xy[0], dy - xy[1]))
    return float(np.median(residuals)) if residuals else 999.0
