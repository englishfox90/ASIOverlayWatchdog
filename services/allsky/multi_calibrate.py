"""
Multi-image all-sky fisheye calibration.

Jointly fits ONE FisheyeModel to N exposures from the same fixed camera.
All optical/mount parameters (cx, cy, a1, a3, a5, roll, axis_alt, axis_az)
are shared; each image only differs by observation time, which changes the
AltAz of every catalog star.

Benefits over single-image calibration
---------------------------------------
- Many more matched stars → better-constrained polynomial (a3, a5)
- Stars at different altitudes/azimuths in each frame → axis_alt/az
  is no longer degenerate and rarely hits the 90° upper bound
- Robust to a few bad frames (they contribute only a small fraction of
  the total residual)

Algorithm
---------
1.  Detect stars in every frame.
2.  For each frame, build initial matches against the BSC5 catalog using
    a seed FisheyeModel (derived from single-image calibration on the
    frame with the most detections, or supplied by the caller).
3.  Iteratively run scipy least_squares on the pooled residuals, then
    re-match each frame at successively tighter tolerances.
4.  Accept if total median residual < max_residual_px and total matches
    >= min_total_matches.

Dependencies: scipy (same as single-image calibration).
"""
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import numpy as np

from services.logger import app_logger as log

# Pre-import scipy at module level so background threads never trigger
# a first-time import (causes segfault in PyInstaller builds).
try:
    from scipy.optimize import least_squares as _least_squares
except Exception as _e:
    _least_squares = None
    log.error(f"scipy.optimize import failed in multi_calibrate: {type(_e).__name__}: {_e}")

from .star_centroid import detect_stars, estimate_sky_circle
from .fisheye import FisheyeModel
from .catalogs import get_bright_stars
from .coords import radec_to_altaz
from .calibration import (
    CalibrationError,
    _get_image_size,
    _catalog_altaz,
    _brightness_match,
    _params_to_model,
    _compute_rms,
    calibrate,
)
from .calibration_validate import (
    A3_MAX,
    A3_MIN,
    A3_SEED_DEFAULT,
    ORIENT_AXIS_ALT,
    ORIENT_AXIS_AZ,
    ORIENT_ROLL_DEG,
    REG_A3,
    REG_A5,
    a1_from_sky_radius,
    validate_bright_anchors,
    validate_lens_polynomial,
    tol_scale,
)


# ---------------------------------------------------------------------------
# Radial-polynomial regularisation (ridge prior toward the seed)
# ---------------------------------------------------------------------------
#
# On obstructed installs (pier cameras with the telescope OTA/mount in frame)
# the matched stars cluster in the unblocked sky region, leaving the radial
# polynomial (a3, a5) under-constrained. With even a slightly stale seed the
# optimiser bends a3 toward its bound to absorb an *orientation* error — landing
# in a low-RMS false minimum where roll/axis are wrong and the bright anchors
# are 50-90 px off (observed in production as the recurring "a3=25.0 outside
# plausible range" refinement failure). A soft ridge penalty pulling a3/a5 back
# toward the seed values forces the orientation parameters to take the
# correction instead. The penalty is weighted by sqrt(N residuals) so its
# strength relative to the data is independent of how many stars matched: when
# coverage genuinely constrains the polynomial the data still dominates; when it
# doesn't, the physical prior wins instead of the bound.
# Ridge weights REG_A3 / REG_A5 are shared with the guided fit (calibration_validate).


def _median_sky_r(frames) -> float:
    """Median trimmed sky radius across frames, or 0.0 if unknown.

    Used to scale match tolerances to the frame resolution (F10). Frames built
    by dev scripts may omit 'sky_r'; 0.0 makes tol_scale() neutral.
    """
    rs = [f.get('sky_r') for f in frames if f.get('sky_r')]
    return float(np.median(rs)) if rs else 0.0

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

# Cold-start orientation search: coarse grid over the mount/orientation
# parameters, scored across ALL accumulated frames at once.
_BOOT_MAX_FRAMES = 8     # frames sampled for the orientation search (speed)
_BOOT_MAX_CAT = 150      # brightest catalog stars used for scoring
# Orientation grid (ORIENT_AXIS_ALT / ORIENT_AXIS_AZ / ORIENT_ROLL_DEG) is shared
# with the guided fit (calibration_validate).


_BOOT_TOP_K = 6          # coarse candidates handed to the joint fit


def _coarse_orientation_candidates(frames: List[dict], k: int = _BOOT_TOP_K):
    """Return up to k coarse orientation seeds, best-first, from a cross-frame grid.

    A single obstructed frame can't determine the full 8-parameter pose (the
    matched stars cluster in the unblocked sky region), so per-frame methods
    like triangle hashing settle on a wrong axis_alt/roll. The TRUE pose is the
    one that matches stars in *every* frame's clear window as the sky rotates; a
    false pose only fits one frame. This grid scores each (east_left, axis_alt,
    axis_az, roll) candidate by total matches summed across the sampled frames.

    Coarse scoring alone is not perfectly discriminative, so we return the top-k
    candidates: the caller joint-fits each and keeps the one that passes the
    bright-anchor gate (a false basin won't). cx/cy come from the reliable
    sky-circle estimate, a1 from the sky radius; the joint fit refines the rest.
    """
    from scipy.spatial import cKDTree

    # Evenly sample frames across the buffer for the search.
    n = len(frames)
    if n > _BOOT_MAX_FRAMES:
        idx = np.linspace(0, n - 1, _BOOT_MAX_FRAMES).round().astype(int)
        sample = [frames[i] for i in dict.fromkeys(idx.tolist())]
    else:
        sample = frames

    cx = float(np.median([f.get('sky_cx', 0.0) for f in sample]))
    cy = float(np.median([f.get('sky_cy', 0.0) for f in sample]))
    sky_r = _median_sky_r(sample)
    a1 = a1_from_sky_radius(sky_r) if sky_r else 600.0
    # Generous tolerance: coarse grid points (5° alt / 15° roll apart) place
    # stars only approximately, so matching must be forgiving to score the
    # right basin highest. The joint fit tightens from here.
    tol = max(35.0, 50.0 * tol_scale(sky_r))

    # Precompute per-frame: KDTree of detections + brightest catalog alt/az.
    prepared = []
    for f in sample:
        det = f.get('detected', [])
        if len(det) < 4:
            continue
        tree = cKDTree(np.array([(d[0], d[1]) for d in det], dtype=float))
        ah = f.get('above_horizon', [])[:_BOOT_MAX_CAT]
        alts = np.array([a for _s, a, _z in ah], dtype=float)
        azs = np.array([z for _s, _a, z in ah], dtype=float)
        prepared.append((tree, alts, azs))

    if not prepared:
        raise CalibrationError("Bootstrap: no frames with enough detections.")

    scored = []  # (n_match, east_left, axis_alt, axis_az, roll_deg)
    for east_left in (True, False):
        for axis_alt in ORIENT_AXIS_ALT:
            for axis_az in ORIENT_AXIS_AZ:
                for roll_deg in ORIENT_ROLL_DEG:
                    m = FisheyeModel(
                        cx=cx, cy=cy, a1=a1, a3=A3_SEED_DEFAULT, a5=0.0,
                        roll=np.radians(roll_deg), axis_alt=float(axis_alt),
                        axis_az=float(axis_az), east_left=east_left,
                    )
                    n_match = 0
                    for tree, alts, azs in prepared:
                        px, py, vis = m.altaz_array_to_pixels(alts, azs)
                        if not np.any(vis):
                            continue
                        pts = np.column_stack([px[vis], py[vis]])
                        d, _ = tree.query(pts, distance_upper_bound=tol)
                        n_match += int(np.count_nonzero(np.isfinite(d)))
                    scored.append((n_match, east_left, axis_alt, axis_az, roll_deg))

    scored.sort(key=lambda t: -t[0])
    img_w = frames[0].get('image_width', 0)
    img_h = frames[0].get('image_height', 0)
    out = []
    for n_match, east_left, axis_alt, axis_az, roll_deg in scored[:k]:
        m = FisheyeModel(
            cx=cx, cy=cy, a1=a1, a3=A3_SEED_DEFAULT, a5=0.0,
            roll=np.radians(roll_deg), axis_alt=float(axis_alt),
            axis_az=float(axis_az), east_left=east_left,
        )
        m.image_width, m.image_height = img_w, img_h
        out.append(m)
        log.info(f"Bootstrap candidate: matches={n_match} east_left={east_left} "
                 f"axis_alt={axis_alt} axis_az={axis_az} roll={roll_deg}° a1={a1:.0f}")
    return out


def refine_from_detections(
    frames: List[dict],
    seed_model: Optional[FisheyeModel] = None,
    min_matches_per_image: int = 4,
    min_total_matches: int = 20,
    max_residual_px: float = 20.0,
) -> FisheyeModel:
    """
    Joint calibration from pre-processed frame data.

    Unlike multi_calibrate(), this skips star detection (already done).
    Designed for the background calibration service which detects stars on
    arrival and stores only the detections.

    Args:
        frames: list of dicts with keys: dt, detected, above_horizon.
        seed_model: starting FisheyeModel. When None, a coarse seed is derived
            from scratch via a cross-frame orientation search (cold-start
            bootstrap, no prior model and any site).
        min_matches_per_image: discard frames with fewer matches.
        min_total_matches: fail if total matches below this.
        max_residual_px: maximum accepted median residual (pixels).

    Returns:
        Refined FisheyeModel.

    Raises:
        CalibrationError on insufficient data or poor fit.
    """
    if len(frames) < 1:
        raise CalibrationError("No frames provided for refinement.")

    # --- Warm path: refine an existing model ---
    if seed_model is not None:
        log.info(f"Refining from {len(frames)} pre-processed frame(s)")
        return _fit_and_validate(
            frames, seed_model, min_matches_per_image,
            min_total_matches, max_residual_px,
        )

    # --- Cold start: fit EVERY coarse orientation candidate through the joint
    # fit + gates, then pick the one that retained the most matches. A correct
    # orientation matches far more stars across frames than a degenerate basin
    # that survives on coincidental alignments, so match count is the
    # discriminator (returning merely the first that passes can lock onto a
    # degenerate basin that happens to clear the gate). ---
    candidates = _coarse_orientation_candidates(frames)
    passed = []   # (n_matches, model)
    last_err = None
    for i, seed in enumerate(candidates):
        try:
            model = _fit_and_validate(
                frames, seed, min_matches_per_image,
                min_total_matches, max_residual_px,
            )
            passed.append((model.n_matches, model))
            log.info(f"Bootstrap candidate {i + 1}/{len(candidates)} passed: "
                     f"n_matches={model.n_matches}, rms={model.rms_residual:.1f}px")
        except CalibrationError as e:
            last_err = e
            log.info(f"Bootstrap candidate {i + 1}/{len(candidates)} rejected: {e}")

    if not passed:
        raise CalibrationError(
            f"Cold-start bootstrap failed: no candidate orientation passed "
            f"({last_err})."
        )

    passed.sort(key=lambda t: -t[0])
    best = passed[0][1]
    log.info(f"Cold-start bootstrap: selected best of {len(passed)} passing "
             f"candidate(s) by match count (n_matches={best.n_matches})")
    return best


def _fit_and_validate(
    frames: List[dict],
    seed_model: FisheyeModel,
    min_matches_per_image: int,
    min_total_matches: int,
    max_residual_px: float,
) -> FisheyeModel:
    """Joint-fit from a seed and enforce the residual + sanity gates."""
    _ts = tol_scale(_median_sky_r(frames))
    all_matches = _build_all_matches(frames, seed_model, tol_px=50.0 * _ts,
                                     min_per_image=min_matches_per_image)
    total = sum(len(m) for m in all_matches)
    log.info(f"Initial matches: {total} across {len(all_matches)} frame(s)")

    if total < max(3, min_total_matches // 4):
        raise CalibrationError(
            f"Only {total} initial matches across all frames — cannot refine."
        )

    model, rms = _joint_iterative_fit(
        all_matches, frames, seed_model,
        min_matches_per_image, min_total_matches, max_residual_px,
        tol_scale_factor=_ts,
    )

    if rms > max_residual_px:
        raise CalibrationError(
            f"Refinement residual {rms:.1f}px exceeds limit {max_residual_px}px."
        )

    # Minimum total matches. A wrong/degenerate orientation (e.g. a 180° roll
    # flip) loses almost all matches as the tolerance tightens — it survives on
    # a handful of coincidental alignments that can still include enough bright
    # anchors to fool the anchor gate (observed: a rotated fit saved with only
    # 13 matches, placing Polaris on the wrong side). A correct fit keeps tens
    # to hundreds of matches across frames, so this cleanly rejects the
    # degenerate basins the joint fit can otherwise reach.
    if model.n_matches < min_total_matches:
        raise CalibrationError(
            f"Refinement matched only {model.n_matches} stars "
            f"(need >= {min_total_matches}) — likely a degenerate or wrong "
            "orientation."
        )

    # Sanity checks — multi-image fits over a short span (minutes) can
    # converge to non-physical basins where roll + polynomial + axis_alt
    # collude to satisfy all frames simultaneously without matching the
    # real sky. Guard with lens-polynomial physics + bright-anchor hit rate
    # on the most recent frames.
    poly_ok, poly_msg = validate_lens_polynomial(model)

    # Validate bright anchors on the 3 most recent frames — require majority
    # (at least 2 of 3) to pass. Single-frame validation was fragile: one
    # partially-cloudy frame could silently gate the entire calibration path.
    recent = frames[-3:]
    anch_results = [
        validate_bright_anchors(model, f['above_horizon'], f['detected'],
                                sky_r=f.get('sky_r'))
        for f in recent
    ]
    n_ok = sum(1 for ok, _ in anch_results if ok)
    min_ok = max(1, len(recent) - 1)  # 2/3 frames, 1/2 frames, or 1/1 frame
    anch_ok = n_ok >= min_ok
    if anch_ok:
        anch_msg = f"{n_ok}/{len(recent)} recent frames pass anchor check"
    else:
        fail_msgs = [m for ok, m in anch_results if not ok]
        anch_msg = (f"only {n_ok}/{len(recent)} recent frames pass anchor check: "
                    + "; ".join(fail_msgs[:2]))

    if not (poly_ok and anch_ok):
        reason = "; ".join(
            m for ok, m in ((poly_ok, poly_msg), (anch_ok, anch_msg)) if not ok
        )
        raise CalibrationError(f"Refinement failed sanity check: {reason}")

    latest = frames[-1]
    model.image_width = latest.get('image_width', 0)
    model.image_height = latest.get('image_height', 0)
    model.calibrated_at = datetime.now(timezone.utc).isoformat()
    log.info(f"Refinement succeeded: {model} ({poly_msg}; {anch_msg})")
    return model


def multi_calibrate(
    images_and_times: List[Tuple],
    lat_deg: float,
    lon_deg: float,
    seed_model: Optional[FisheyeModel] = None,
    max_stars: int = 200,
    min_matches_per_image: int = 4,
    min_total_matches: int = 20,
    max_residual_px: float = 10.0,
) -> FisheyeModel:
    """
    Calibrate a fisheye lens model from multiple exposures.

    Args:
        images_and_times: List of (image, utc_datetime) where image is a
                          PIL Image or numpy array.
        lat_deg: Observer latitude (degrees, north positive).
        lon_deg: Observer longitude (degrees, east positive).
        seed_model: Optional starting model.  If None, the best single-frame
                    calibration is used as the seed.
        max_stars: Max detected stars per image (passed to detect_stars).
        min_matches_per_image: Images with fewer matches are discarded.
        min_total_matches: Minimum total matches required across all images.
        max_residual_px: Maximum accepted median residual (pixels).

    Returns:
        Calibrated FisheyeModel.

    Raises:
        CalibrationError on insufficient data or poor fit.
    """
    if len(images_and_times) < 1:
        raise CalibrationError("No images provided for multi-image calibration.")

    log.info(f"Multi-calibrate: {len(images_and_times)} image(s)")

    # ------------------------------------------------------------------
    # Step 1: Star detection for every frame
    # ------------------------------------------------------------------
    frames = []                         # [{image, dt, detections, catalog_altaz}, ...]
    img_cx0, img_cy0 = None, None       # shared optical-centre seed

    for image, dt in images_and_times:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        sky_cx, sky_cy, sky_r = estimate_sky_circle(image)
        if img_cx0 is None:
            img_cx0, img_cy0 = sky_cx, sky_cy

        detected = detect_stars(
            image, max_stars=max_stars,
            sky_cx=sky_cx, sky_cy=sky_cy, sky_radius=sky_r,
        )
        log.info(f"  {dt.isoformat()}: {len(detected)} candidate stars")

        catalog     = get_bright_stars(max_mag=6.5)
        cat_altaz   = _catalog_altaz(catalog, lat_deg, lon_deg, dt)
        above_horiz = [(s, a, z) for s, a, z in cat_altaz if a > 3.0]
        above_horiz.sort(key=lambda x: x[0]['vmag'])

        frames.append({
            'image': image,
            'dt':    dt,
            'detected':     detected,
            'above_horizon': above_horiz,
            'sky_cx': sky_cx, 'sky_cy': sky_cy, 'sky_r': sky_r,
        })

    # ------------------------------------------------------------------
    # Step 2: Seed model
    # ------------------------------------------------------------------
    if seed_model is None:
        seed_model = _best_single_frame_model(
            frames, lat_deg, lon_deg, img_cx0, img_cy0
        )
        log.info(f"Seed model: a1={seed_model.a1:.1f}, "
                 f"axis_alt={seed_model.axis_alt:.2f}, rms={seed_model.rms_residual:.2f}px")
    else:
        log.info("Using supplied seed model.")

    # ------------------------------------------------------------------
    # Step 3: Initial matching for all frames using the seed model
    # ------------------------------------------------------------------
    _ts = tol_scale(_median_sky_r(frames))
    all_matches = _build_all_matches(frames, seed_model, tol_px=50.0 * _ts,
                                     min_per_image=min_matches_per_image)
    total = sum(len(m) for m in all_matches)
    log.info(f"Initial total matches: {total} across {len(all_matches)} frame(s)")

    if total < max(3, min_total_matches // 4):
        raise CalibrationError(
            f"Only {total} initial matches across all frames — cannot proceed.\n"
            "  Ensure images show a clear night sky and lat/lon/time are correct."
        )

    # ------------------------------------------------------------------
    # Step 4: Joint iterative fit
    # ------------------------------------------------------------------
    model, rms = _joint_iterative_fit(
        all_matches, frames, seed_model,
        min_matches_per_image, min_total_matches, max_residual_px,
        tol_scale_factor=_ts,
    )

    if rms > max_residual_px:
        raise CalibrationError(
            f"Multi-calibration residual {rms:.1f}px exceeds limit {max_residual_px}px."
        )

    log.info(f"Multi-calibration succeeded: {model}, RMS={rms:.2f}px")
    return model


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _best_single_frame_model(frames, lat, lon, cx0, cy0) -> FisheyeModel:
    """Run single-image calibration on the frame with the most detections."""
    best_frame = max(frames, key=lambda f: len(f['detected']))
    try:
        model = calibrate(
            best_frame['image'], lat, lon, dt=best_frame['dt'],
            image_cx=cx0, image_cy=cy0,
        )
        return model
    except CalibrationError as e:
        log.warning(f"Single-frame seed failed: {e}; using default model.")
        img_h, img_w = _get_image_size(best_frame['image'])
        a1_guess = min(img_w, img_h) * 0.5 * 0.75 / (np.pi / 2.0)
        return FisheyeModel(cx=cx0, cy=cy0, a1=a1_guess)


def _build_all_matches(frames, model, tol_px: float,
                       min_per_image: int,
                       max_vmag: Optional[float] = None,
                       _log: bool = True) -> List[list]:
    """Match each frame's detections to catalog using the current model."""
    all_matches = []
    discarded = 0
    total_matched = 0
    for f in frames:
        horizon = f['above_horizon']
        if max_vmag is not None:
            horizon = [(s, a, z) for s, a, z in horizon if s.get('vmag', 9.0) <= max_vmag]
        matches = _brightness_match(f['detected'], horizon, model, tol_px=tol_px)
        if len(matches) >= min_per_image:
            all_matches.append(matches)
            total_matched += len(matches)
        else:
            discarded += 1
    # One summary line per call rather than one per frame: at ~60 frames over
    # 10 tightening iterations the per-frame form emitted ~600 DEBUG lines per
    # refinement cycle (every couple of minutes). The per-iteration INFO summary
    # in _joint_iterative_fit covers the convergence story.
    if _log:
        log.debug(f"  tol={tol_px:.0f}px: kept {len(all_matches)} frames "
                  f"({total_matched} matches), discarded {discarded} "
                  f"(min={min_per_image}/frame)")
    return all_matches


def _joint_iterative_fit(
    all_matches, frames, model, min_per_image, min_total, max_residual,
    cx_range: float = 100.0,
    cy_range: float = 100.0,
    tol_scale_factor: float = 1.0,
) -> Tuple[FisheyeModel, float]:
    """
    Iterative joint optimisation over all matched frames.

    Each iteration:
      1. Run scipy least_squares on the pooled residuals.
      2. Re-match every frame at a tightening tolerance.
      3. Discard frames that fall below min_per_image matches.

    cx_range / cy_range: maximum allowed drift of the optical centre from
    the seed value (pixels).  Keeps the optimizer from drifting to a
    degenerate local minimum — the sky-circle centre is a hard physical
    constraint that orientation/polynomial parameters cannot compensate for.
    """
    if _least_squares is None:
        raise CalibrationError("scipy is required for calibration.")

    # Anchor cx/cy within cx_range/cy_range of the seed model.
    # east_left is discrete — fixed from seed, not part of continuous optimisation.
    seed_cx, seed_cy = model.cx, model.cy
    east_left = model.east_left

    # Polynomial regularisation toward the seed (physical prior). See the
    # ridge-prior note above _joint_iterative_fit and REG_A3/REG_A5 rationale.
    seed_a3, seed_a5 = model.a3, model.a5

    # Bright anchor matches: kept at a fixed large tolerance throughout all iterations
    # so that easily-identified bright stars (vmag < 3.5) always participate in the
    # loss even when the tightening regular tolerance would exclude them.  Without
    # this, the optimizer can settle into a false minimum where hundreds of dim stars
    # match well but Arcturus/Vega/Antares/Deneb are 50-90 px off.
    _ANCH_TOL = 100.0 * tol_scale_factor
    _ANCH_MAX_VMAG = 3.5
    _ANCH_WEIGHT = 4.0  # multiply residuals → 16x contribution to squared loss
    anchor_matches = _build_all_matches(
        frames, model, tol_px=_ANCH_TOL, min_per_image=0,
        max_vmag=_ANCH_MAX_VMAG, _log=False,
    )

    for iteration in range(10):
        params = np.array([
            model.cx, model.cy, model.a1, model.a3, model.a5,
            model.roll, model.axis_alt, model.axis_az,
        ])

        # Capture by name; both are reassigned after _least_squares returns.
        current_matches = all_matches
        current_anchor = anchor_matches

        def residuals(p):
            m = _params_to_model(p, east_left)
            res = []
            for img_matches in current_matches:
                for (dx, dy), _star, (alt, az) in img_matches:
                    xy = m.altaz_to_pixel(alt, az)
                    if xy is None:
                        res.extend([30.0, 30.0])
                    else:
                        res.extend([dx - xy[0], dy - xy[1]])
            # Bright anchor terms: fixed large tolerance, high weight.
            # These prevent the false minimum where dim-star density produces low RMS
            # but the easily-identified bright anchors are far from any detection.
            for img_anchors in current_anchor:
                for (dx, dy), _star, (alt, az) in img_anchors:
                    xy = m.altaz_to_pixel(alt, az)
                    if xy is None:
                        res.extend([30.0 * _ANCH_WEIGHT, 30.0 * _ANCH_WEIGHT])
                    else:
                        res.extend([(dx - xy[0]) * _ANCH_WEIGHT,
                                    (dy - xy[1]) * _ANCH_WEIGHT])
            # Ridge prior on the radial polynomial (see note above). Weighted by
            # sqrt(N) so the prior's strength tracks the data volume.
            if res and (REG_A3 > 0 or REG_A5 > 0):
                w = float(np.sqrt(len(res)))
                res.append(REG_A3 * w * (m.a3 - seed_a3))
                res.append(REG_A5 * w * (m.a5 - seed_a5))
            return res

        try:
            # a3/a5 bounds match single-image fit: physical fisheye range.
            # axis_alt lower bound is 60° (not 45°) to match the grid-search floor —
            # allowing lower values lets the optimizer drift to a zenith-magnified false
            # minimum where dim stars cluster densely but bright anchors are missed.
            result = _least_squares(
                residuals, params,
                bounds=(
                    [seed_cx - cx_range, seed_cy - cy_range,
                     50,  A3_MIN, -1500.0, -np.pi, 60.0, -180.0],
                    [seed_cx + cx_range, seed_cy + cy_range,
                     2000,  A3_MAX,   500.0,  np.pi, 90.0,  540.0],
                ),
                method='trf',
                max_nfev=12000,
                ftol=1e-5,
            )
            raw = result.x.copy()
            raw[7] = raw[7] % 360.0   # normalise axis_az to [0, 360)
            model = _params_to_model(raw, east_left)
        except Exception as e:
            log.warning(f"Joint fit iteration {iteration} failed: {e}")
            break

        # Re-match every frame at tightening tolerance (schedule shape fixed;
        # endpoints scaled to the sky radius for resolution-independence, F10).
        # Floor at 18px (≈11px at this sky radius): on real frames a 5-8px floor
        # over-prunes — centroid noise + residual model error drop good matches
        # below min_per_image, the frames get discarded, and a genuinely correct
        # fit collapses to a handful of matches (observed: a correct orientation
        # held 79 matches at 9px then fell to 4 at 5px). A moderate floor keeps
        # the match set populated so correct fits survive and degenerate ones
        # are still distinguished by far lower counts.
        tol = tol_scale_factor * max(18.0, 50.0 - iteration * 5.0)
        all_matches = _build_all_matches(frames, model, tol_px=tol,
                                         min_per_image=min_per_image)
        # Rebuild anchor matches with updated model (fixed large tolerance)
        anchor_matches = _build_all_matches(
            frames, model, tol_px=_ANCH_TOL, min_per_image=0,
            max_vmag=_ANCH_MAX_VMAG, _log=False,
        )

        total   = sum(len(m) for m in all_matches)
        rms     = _joint_rms(all_matches, model)
        n_imgs  = len(all_matches)
        log.info(f"  Iter {iteration}: {total} matches / {n_imgs} frames, "
                 f"RMS={rms:.2f}px, tol={tol:.0f}px, "
                 f"axis_alt={model.axis_alt:.3f}")

        if rms < 2.5 and total >= min_total:
            break

    total = sum(len(m) for m in all_matches)
    rms   = _joint_rms(all_matches, model)

    model.n_matches    = total
    model.rms_residual = float(rms)
    model.matched_stars = _collect_diagnostics(all_matches, model, frames)
    return model, rms


def _joint_rms(all_matches, model) -> float:
    """Median pixel residual across all matches in all frames."""
    residuals = []
    for img_matches in all_matches:
        for (dx, dy), _star, (alt, az) in img_matches:
            xy = model.altaz_to_pixel(alt, az)
            if xy is not None:
                residuals.append(float(np.hypot(dx - xy[0], dy - xy[1])))
    return float(np.median(residuals)) if residuals else 999.0


def _collect_diagnostics(all_matches, model, frames) -> list:
    """Build per-match diagnostic list (same format as single-image calibration)."""
    diag = []
    for img_idx, img_matches in enumerate(all_matches):
        dt_label = frames[img_idx]['dt'].isoformat() if img_idx < len(frames) else ''
        for (dx, dy), star, (alt, az) in img_matches:
            cat_px  = model.altaz_to_pixel(alt, az)
            res_px  = float(np.hypot(dx - cat_px[0], dy - cat_px[1])) if cat_px else 999.0
            diag.append({
                'name':       star.get('name', ''),
                'vmag':       float(star.get('vmag', 0.0)),
                'alt':        float(alt),
                'az':         float(az),
                'frame_time': dt_label,
                'detected_px': (float(dx), float(dy)),
                'catalog_px':  (float(cat_px[0]), float(cat_px[1])) if cat_px else None,
                'residual_px': res_px,
            })
    diag.sort(key=lambda s: s['residual_px'])
    return diag
