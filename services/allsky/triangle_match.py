"""
Triangle hash matching for fisheye calibration fallback.

Geometric hashing of star triangle shapes (astrometry.net-inspired,
adapted for fisheye).  Called automatically when the grid search in
calibration.py fails.  Works with as few as 4-5 detected stars.
"""
import math
import time as _time
import numpy as np
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from typing import List, Optional, Tuple

from services.logger import app_logger as log

# Pre-import scipy at module level so background threads never trigger
# a first-time import (causes segfault in PyInstaller builds).
try:
    from scipy.stats import binom as _binom
except Exception as _e:
    _binom = None
    log.error(f"scipy.stats import failed in triangle_match: {type(_e).__name__}: {_e}")

from .fisheye import FisheyeModel
from .calibration import (
    CalibrationError,
    _brightness_match,
    _iterative_fit,
    _catalog_altaz,
    _get_image_size,
)
from .star_centroid import detect_stars, estimate_sky_circle
from .catalogs import get_bright_stars
from .calibration_validate import (
    validate_bright_anchors,
    validate_lens_polynomial,
    tol_scale,
    a1_from_sky_radius,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BIN_SIZE = 0.015          # shape ratio quantisation step
MATCH_TOL = 0.05          # matching tolerance in ratio space
MAX_SEP_DEG = 80.0        # max angular separation for indexed triplets
MAX_DET_STARS = 12        # brightest detected stars used for triplets
MAX_HYPOTHESES = 500      # early-stop after scoring this many
MIN_SCORE = 4             # minimum matches for a useful hypothesis
MAX_CAT_MAG = 5.5         # faintest catalog star in index
MAX_CAT_STARS = 150       # hard cap on catalog stars indexed — C(N,3) is cubic,
                          # 150 stars → ~550k triplets (~1s), 1500 → ~560M (~10 min)
MATCH_PROB_THRESHOLD = 1e-3   # binomial false-positive probability threshold


# ---------------------------------------------------------------------------
# Angular geometry
# ---------------------------------------------------------------------------

def _angular_sep_matrix(ra_deg: np.ndarray, dec_deg: np.ndarray) -> np.ndarray:
    """Pairwise great-circle separation matrix (degrees) from RA/Dec.

    Uses chord formula 2*arcsin(||v1-v2||/2) for numerical stability.
    """
    ra = np.radians(ra_deg)
    dec = np.radians(dec_deg)
    vecs = np.column_stack([
        np.cos(dec) * np.cos(ra),
        np.cos(dec) * np.sin(ra),
        np.sin(dec),
    ])
    # Pairwise chord distances via broadcasting
    diff = vecs[:, np.newaxis, :] - vecs[np.newaxis, :, :]   # (N, N, 3)
    chord = np.sqrt(np.sum(diff * diff, axis=2))              # (N, N)
    return np.degrees(2.0 * np.arcsin(np.clip(chord * 0.5, 0.0, 1.0)))


def _triangle_shape(d1: float, d2: float, d3: float):
    """Scale-invariant triangle descriptor: (short/long, mid/long).

    Returns None for degenerate triangles (longest side < 0.5 deg).
    """
    sides = sorted([d1, d2, d3])
    if sides[2] < 0.5:
        return None
    return (sides[0] / sides[2], sides[1] / sides[2])


def _bin_key(r1: float, r2: float) -> Tuple[int, int]:
    return (round(r1 / BIN_SIZE), round(r2 / BIN_SIZE))


# ---------------------------------------------------------------------------
# Pixel / direction conversion
# ---------------------------------------------------------------------------

def _pixel_to_direction(x, y, cx, cy, a1, east_left):
    """Convert pixel to unit vector in camera frame (equidistant approx).

    Returns a length-3 numpy array, or None if outside FOV.
    """
    dx = x - cx
    dy = y - cy
    r = math.sqrt(dx * dx + dy * dy)
    if r < 0.5:
        return np.array([0.0, 0.0, 1.0])
    theta = r / a1
    if theta > math.pi:
        return None
    east_sign = -1.0 if east_left else 1.0
    sin_phi = dx / (east_sign * r)
    cos_phi = -dy / r
    phi = math.atan2(sin_phi, cos_phi)
    sin_t = math.sin(theta)
    return np.array([sin_t * math.sin(phi),
                     sin_t * math.cos(phi),
                     math.cos(theta)])


def _altaz_to_direction(alt_deg, az_deg):
    """AltAz -> unit vector in horizon frame (East, North, Up)."""
    alt_r = math.radians(alt_deg)
    az_r = math.radians(az_deg)
    return np.array([
        math.cos(alt_r) * math.sin(az_r),
        math.cos(alt_r) * math.cos(az_r),
        math.sin(alt_r),
    ])


def _angular_sep_pixels(x1, y1, x2, y2, cx, cy, a1, east_left):
    """Angular separation in degrees between two pixel positions.

    Uses the chord formula for numerical stability.
    """
    v1 = _pixel_to_direction(x1, y1, cx, cy, a1, east_left)
    v2 = _pixel_to_direction(x2, y2, cx, cy, a1, east_left)
    if v1 is None or v2 is None:
        return None
    chord = float(np.linalg.norm(v1 - v2))
    return math.degrees(2.0 * math.asin(min(chord * 0.5, 1.0)))


# ---------------------------------------------------------------------------
# Wahba rotation solver (SVD)
# ---------------------------------------------------------------------------

def _solve_wahba(pixel_dirs: np.ndarray, horizon_dirs: np.ndarray):
    """SVD rotation solver (Wahba's problem): horizon -> camera.

    Returns (roll_rad, axis_alt_deg, axis_az_deg) or None.
    """
    H = horizon_dirs.T @ pixel_dirs
    try:
        U, _S, Vt = np.linalg.svd(H)
    except np.linalg.LinAlgError:
        return None
    d = np.linalg.det(Vt.T @ U.T)
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    return _rotation_to_params(R)


def _rotation_to_params(R: np.ndarray):
    """Extract (roll_rad, axis_alt_deg, axis_az_deg) from rotation matrix.

    R = Rz(-roll) @ Rx(-(90-axis_alt)) @ Rz(-axis_az), horizon -> camera.
    """
    cos_beta = float(np.clip(R[2, 2], -1.0, 1.0))
    sin_beta_sq = max(0.0, 1.0 - cos_beta * cos_beta)
    # beta = axis_alt - 90 (radians); axis_alt in [45,90] -> beta in [-45,0]
    sin_beta = -math.sqrt(sin_beta_sq)

    if abs(sin_beta) < 1e-6:
        # Gimbal lock: axis_alt ~ 90
        roll = -math.atan2(float(R[1, 0]), float(R[0, 0]))
        return roll, 90.0, 0.0

    gamma = math.atan2(float(R[2, 0]) / sin_beta,
                       float(R[2, 1]) / sin_beta)
    alpha = math.atan2(float(R[0, 2]) / sin_beta,
                       -float(R[1, 2]) / sin_beta)
    beta = math.atan2(sin_beta, cos_beta)

    roll = -alpha
    axis_alt = 90.0 + math.degrees(beta)
    axis_az = math.degrees(-gamma) % 360.0
    return roll, axis_alt, axis_az


# ---------------------------------------------------------------------------
# Triangle hash table
# ---------------------------------------------------------------------------

class TriangleIndex:
    """Hash table of catalog star triplet shapes for geometric matching."""

    def __init__(self, sep_matrix: np.ndarray):
        self._sep = sep_matrix
        self._table: dict = defaultdict(list)

    def build(self) -> int:
        """Populate the hash table.  Returns number of indexed triplets."""
        n = self._sep.shape[0]
        count = 0
        for i, j, k in combinations(range(n), 3):
            d_ij = self._sep[i, j]
            d_ik = self._sep[i, k]
            d_jk = self._sep[j, k]
            if d_ij > MAX_SEP_DEG or d_ik > MAX_SEP_DEG or d_jk > MAX_SEP_DEG:
                continue
            shape = _triangle_shape(d_ij, d_ik, d_jk)
            if shape is None:
                continue
            self._table[_bin_key(*shape)].append((i, j, k))
            count += 1
        return count

    def lookup(self, shape: Tuple[float, float]) -> List[Tuple[int, int, int]]:
        """Return catalog triplets whose shape is within MATCH_TOL."""
        r1, r2 = shape
        results = []
        lo1 = int((r1 - MATCH_TOL) / BIN_SIZE) - 1
        hi1 = int((r1 + MATCH_TOL) / BIN_SIZE) + 2
        lo2 = int((r2 - MATCH_TOL) / BIN_SIZE) - 1
        hi2 = int((r2 + MATCH_TOL) / BIN_SIZE) + 2
        for b1 in range(lo1, hi1):
            for b2 in range(lo2, hi2):
                for triplet in self._table.get((b1, b2), []):
                    i, j, k = triplet
                    cat_shape = _triangle_shape(
                        self._sep[i, j], self._sep[i, k], self._sep[j, k],
                    )
                    if cat_shape is None:
                        continue
                    if (abs(cat_shape[0] - r1) <= MATCH_TOL
                            and abs(cat_shape[1] - r2) <= MATCH_TOL):
                        results.append(triplet)
        return results


# ---------------------------------------------------------------------------
# Vertex correspondence from matched triangle sides
# ---------------------------------------------------------------------------

def _resolve_correspondence(det_triple, cat_triple, det_side_info, cat_sep):
    """Determine vertex mapping by aligning sorted side lengths.

    Returns [(det_idx, cat_idx), ...] list of 3 correspondences, or None.
    """
    ci, cj, ck = cat_triple
    cat_side_info = [
        (cat_sep[ci, cj], 2),   # side i-j, opposite k (pos 2)
        (cat_sep[ci, ck], 1),   # side i-k, opposite j (pos 1)
        (cat_sep[cj, ck], 0),   # side j-k, opposite i (pos 0)
    ]

    det_sorted = sorted(det_side_info)
    cat_sorted = sorted(cat_side_info)

    det_arr = list(det_triple)
    cat_arr = list(cat_triple)

    mapping = {}
    for (_, d_opp), (_, c_opp) in zip(det_sorted, cat_sorted):
        if d_opp in mapping and mapping[d_opp] != c_opp:
            return None
        mapping[d_opp] = c_opp

    if len(set(mapping.values())) != 3:
        return None

    return [(det_arr[d], cat_arr[mapping[d]]) for d in range(3)]


# ---------------------------------------------------------------------------
# Statistical validation (binomial false-positive test, cf. tetra3)
# ---------------------------------------------------------------------------

def _match_probability(
    n_matches: int,
    n_detected: int,
    n_catalog_projected: int,
    match_radius_fraction: float,
) -> float:
    """Binomial probability that *n_matches* or more occur by chance.

    Each detected star is a Bernoulli trial with success probability
    p = n_catalog * radius^2 (fraction of image covered by match discs).
    Subtracts 3 degrees of freedom for the rotation estimate.
    """
    if _binom is None:
        return 1.0  # Cannot compute without scipy — assume plausible
    p_single = min(n_catalog_projected * match_radius_fraction ** 2, 1.0)
    if p_single <= 0 or n_matches <= 0:
        return 1.0
    effective = max(n_matches - 3, 0)
    return float(_binom.sf(effective - 1, n_detected, p_single))


# ---------------------------------------------------------------------------
# Hypothesis generation and scoring
# ---------------------------------------------------------------------------

def _generate_and_score(
    detected, above_horizon, index, catalog_altaz, sep_matrix,
    cx, cy, a1_est, east_left, tol_scale_factor: float = 1.0,
):
    """Match detected triplets, solve pose, score with binomial CDF.

    Returns (best_model, best_score, best_matches, best_prob).
    """
    n_det = min(len(detected), MAX_DET_STARS)
    det_top = detected[:n_det]

    # Pre-compute detected pairwise angular separations
    det_sep = np.full((n_det, n_det), -1.0)
    for a in range(n_det):
        for b in range(a + 1, n_det):
            sep = _angular_sep_pixels(
                det_top[a][0], det_top[a][1],
                det_top[b][0], det_top[b][1],
                cx, cy, a1_est, east_left,
            )
            if sep is not None:
                det_sep[a, b] = sep
                det_sep[b, a] = sep

    # Count how many catalog stars project into the image (for probability)
    tol_match = 35.0 * tol_scale_factor
    sky_r = a1_est * (np.pi / 2.0)
    match_frac = tol_match / (2.0 * sky_r) if sky_r > 0 else 0.01
    n_cat_proj = sum(
        1 for s, alt, _ in above_horizon
        if alt > 3.0 and s.get('vmag', 99) <= 6.5
    )

    best_model = None
    best_score = 0
    best_prob = 1.0
    best_matches = []
    n_scored = 0

    for a, b, c in combinations(range(n_det), 3):
        s_ab = det_sep[a, b]
        s_ac = det_sep[a, c]
        s_bc = det_sep[b, c]
        if s_ab < 0 or s_ac < 0 or s_bc < 0:
            continue

        shape = _triangle_shape(s_ab, s_ac, s_bc)
        if shape is None:
            continue

        for ci, cj, ck in index.lookup(shape):
            det_side_info = [
                (s_ab, 2),   # side a-b, opposite c
                (s_ac, 1),   # side a-c, opposite b
                (s_bc, 0),   # side b-c, opposite a
            ]
            corr = _resolve_correspondence(
                (a, b, c), (ci, cj, ck), det_side_info, sep_matrix,
            )
            if corr is None:
                continue

            # Build direction arrays for Wahba solver
            pixel_dirs = []
            horizon_dirs = []
            valid = True
            for det_i, cat_i in corr:
                pdir = _pixel_to_direction(
                    det_top[det_i][0], det_top[det_i][1],
                    cx, cy, a1_est, east_left,
                )
                if pdir is None:
                    valid = False
                    break
                alt, az = catalog_altaz[cat_i]
                horizon_dirs.append(_altaz_to_direction(alt, az))
                pixel_dirs.append(pdir)

            if not valid:
                continue

            params = _solve_wahba(
                np.array(pixel_dirs), np.array(horizon_dirs),
            )
            if params is None:
                continue

            roll, axis_alt, axis_az = params
            if axis_alt < 45.0 or axis_alt > 90.5:
                continue

            model = FisheyeModel(
                cx=cx, cy=cy, a1=a1_est,
                roll=roll, axis_alt=min(axis_alt, 90.0),
                axis_az=axis_az, east_left=east_left,
            )
            matches = _brightness_match(
                detected, above_horizon, model, tol_px=tol_match,
            )
            score = len(matches)
            if score < MIN_SCORE:
                n_scored += 1
                if n_scored >= MAX_HYPOTHESES:
                    break
                continue

            # Binomial false-positive probability
            prob = _match_probability(
                score, len(detected), n_cat_proj, match_frac,
            )

            if prob < best_prob or (prob == best_prob and score > best_score):
                best_prob = prob
                best_score = score
                best_model = model
                best_matches = matches
                if prob < MATCH_PROB_THRESHOLD:
                    log.debug(f"  Strong match: {score} stars, "
                              f"prob={prob:.2e}")
                    return best_model, best_score, best_matches, best_prob

            n_scored += 1
            if n_scored >= MAX_HYPOTHESES:
                break

        if n_scored >= MAX_HYPOTHESES:
            break

    return best_model, best_score, best_matches, best_prob


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def triangle_calibrate(
    image,
    lat_deg: float,
    lon_deg: float,
    dt: Optional[datetime] = None,
    detected: Optional[list] = None,
    above_horizon: Optional[list] = None,
    sky_cx: Optional[float] = None,
    sky_cy: Optional[float] = None,
    sky_radius: Optional[float] = None,
    min_matches: int = 5,
    max_residual_px: float = 20.0,
    seed_only: bool = False,
) -> FisheyeModel:
    """Calibrate using geometric triangle hashing (fallback).

    Accepts optional pre-computed data from calibrate() to avoid
    redundant star detection.  Tries both east_left orientations.

    seed_only: when True, return the coarse oriented hypothesis after a light
        refinement WITHOUT enforcing the strict single-frame RMS/anchor gates.
        Used to bootstrap multi-image calibration on obstructed scenes where no
        single frame can pass on its own — the joint fit and its gates decide
        the final model. When detected/above_horizon/sky params are supplied,
        `image` may be None (no pixels are read in this mode).

    Raises CalibrationError if matching fails.
    """
    t0 = _time.monotonic()

    if dt is None:
        dt = datetime.now(timezone.utc)

    # --- Sky circle ---
    if sky_cx is None or sky_cy is None or sky_radius is None:
        sky_cx, sky_cy, sky_radius = estimate_sky_circle(image)

    # --- Star detection ---
    if detected is None:
        detected = detect_stars(
            image, max_stars=200,
            sky_cx=sky_cx, sky_cy=sky_cy, sky_radius=sky_radius,
        )

    if len(detected) < 4:
        raise CalibrationError(
            f"Triangle match: only {len(detected)} stars detected (need >= 4)."
        )

    # --- Catalog ---
    if above_horizon is None:
        catalog = get_bright_stars(max_mag=6.5)
        cat_altaz = _catalog_altaz(catalog, lat_deg, lon_deg, dt)
        above_horizon = [(s, alt, az) for s, alt, az in cat_altaz if alt > 3.0]
        above_horizon.sort(key=lambda x: x[0]['vmag'])

    # --- Build triangle index from bright visible stars ---
    # Cap catalog size: C(N,3) is cubic. above_horizon is already sorted
    # brightest-first by caller, so slicing keeps the top anchors.
    bright_ah = [
        (s, a, z) for s, a, z in above_horizon
        if s.get('vmag', 99) <= MAX_CAT_MAG
    ][:MAX_CAT_STARS]
    if len(bright_ah) < 4:
        raise CalibrationError(
            "Triangle match: fewer than 4 bright catalog stars above horizon."
        )

    catalog_stars = [s for s, _, _ in bright_ah]
    catalog_altaz = [(a, z) for _, a, z in bright_ah]

    ra_arr = np.array([s['ra_deg'] for s in catalog_stars])
    dec_arr = np.array([s['dec_deg'] for s in catalog_stars])
    sep_matrix = _angular_sep_matrix(ra_arr, dec_arr)

    log.info(f"Triangle index: building for {len(catalog_stars)} stars "
             f"(capped from {sum(1 for s, _, _ in above_horizon if s.get('vmag', 99) <= MAX_CAT_MAG)})")
    t_idx = _time.monotonic()
    index = TriangleIndex(sep_matrix)
    n_triplets = index.build()
    log.info(f"Triangle index: built in {_time.monotonic() - t_idx:.1f}s — "
             f"{n_triplets} triplets, {len(index._table)} bins")

    # Seed a1 from the trimmed sky radius (helper divides the trim back out;
    # otherwise a1 is ~15% small and every projected star lands short, F10).
    a1_est = a1_from_sky_radius(sky_radius)

    # Resolution-independent match tolerances, keyed off the trimmed radius to
    # match the reference (F10).
    _ts = tol_scale(sky_radius)

    # --- Try both image orientations ---
    log.info("Triangle hypothesis search: starting")
    t_hyp = _time.monotonic()
    overall_best = None
    for east_left in (True, False):
        model, score, matches, prob = _generate_and_score(
            detected, above_horizon, index, catalog_altaz, sep_matrix,
            sky_cx, sky_cy, a1_est, east_left, tol_scale_factor=_ts,
        )
        if model is not None:
            if overall_best is None or prob < overall_best[3]:
                overall_best = (model, score, matches, prob)
    log.info(f"Triangle hypothesis search: done in "
             f"{_time.monotonic() - t_hyp:.1f}s")

    if overall_best is None or overall_best[1] < min_matches:
        found = overall_best[1] if overall_best else 0
        raise CalibrationError(
            f"Triangle match: best hypothesis has {found} matches "
            f"(need >= {min_matches})."
        )

    model, score, matches, prob = overall_best
    log.info(f"Triangle match: best hypothesis {score} matches, "
             f"prob={prob:.2e}, east_left={model.east_left}, "
             f"a1={model.a1:.1f}")

    # --- Refine with iterative least_squares ---
    model, rms = _iterative_fit(
        matches, model, lat_deg, lon_deg, dt,
        above_horizon, detected, min_matches, max_residual_px,
        tol_scale=_ts,
    )

    if seed_only:
        # Coarse oriented seed for multi-image bootstrap. Skip the strict
        # single-frame accuracy/anchor gates — the joint fit decides.
        if image is not None:
            img_h, img_w = _get_image_size(image)
            model.image_width = img_w
            model.image_height = img_h
        log.info(f"Triangle seed (seed_only): {score} matches, "
                 f"east_left={model.east_left}, a1={model.a1:.1f}, rms={rms:.1f}px")
        return model

    if rms > max_residual_px:
        raise CalibrationError(
            f"Triangle match: refined RMS {rms:.1f}px "
            f"exceeds limit {max_residual_px}px."
        )

    poly_ok, poly_msg = validate_lens_polynomial(model)
    anch_ok, anch_msg = validate_bright_anchors(
        model, above_horizon, detected, sky_r=sky_radius)
    if not (poly_ok and anch_ok):
        reason = "; ".join(
            m for ok, m in ((poly_ok, poly_msg), (anch_ok, anch_msg)) if not ok
        )
        raise CalibrationError(f"Triangle match failed sanity check: {reason}")

    elapsed = _time.monotonic() - t0
    # Resolution-bind the model (F5): the renderer scales cx/cy/a1/a3/a5 by the
    # ratio of render size to these dims. Without them the triangle-fallback path
    # would save a model with dims 0,0 — treated as "legacy, never scale" — and
    # reintroduce the resize_percent misalignment in exactly the hard-to-solve
    # frames the fallback exists for.
    img_h, img_w = _get_image_size(image)
    model.image_width = img_w
    model.image_height = img_h
    model.calibrated_at = datetime.now(timezone.utc).isoformat()
    log.info(f"Triangle calibration succeeded: {model}, {elapsed:.1f}s "
             f"({poly_msg}; {anch_msg})")
    return model
