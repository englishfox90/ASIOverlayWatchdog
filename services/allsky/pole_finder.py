"""
Celestial-pole localisation from buffered star detections.

The pole is the one piece of ground truth the sky gives us for free: over a
long-enough window, every star arcs around the projected celestial pole at the
sidereal rate while the pole itself stays put. Polaris (mag 2.0, 0.65° from the
NCP) is the brightest near-stationary detection on any northern-hemisphere
install, so its mean position IS the pole to within ~1° of pixel scale — no
fisheye model required. The rotation *direction* of the surrounding field
determines the image mirror convention (east_left) outright.

Both facts are admission gates for calibration models (calibration_validate.
validate_pole): a wrong-basin fit places the pole hundreds of pixels away
and/or mirrors the sky, so this kills the degenerate fits that survive
residual-based checks on coincidental matches.

Contaminant rejection (validated against sample_images, 2026-07-01):
  - Equipment LEDs are bright and perfectly stationary → rejected by the
    edge margin (they sit at the sky-circle boundary) and the drift band
    (they drift ~0.2× the predicted Polaris arc; Polaris drifts ~1.0×).
  - Lights on a moving telescope are bright and *semi*-stationary → they
    drift 5–10× the predicted arc, outside the band.
  - A whole-field rigid-rotation fit is NOT used for position: fisheye
    distortion biases the aggregate fixed-point estimate by 100+ px. It is
    only used to vote on the rotation sign, which it gets right robustly.

Operates on the CalibrationService buffer format: a list of dicts with keys
'dt' (aware datetime) and 'detected' ([(x, y, flux), ...]); 'sky_cx'/'sky_cy'/
'sky_r' are used when present.

Southern hemisphere: there is no bright pole star (σ Oct is mag 5.5), so this
module returns None below the equator rather than guess. The sign→east_left
mapping is still written hemisphere-aware for when a southern path exists.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from services.logger import app_logger as log

from .calibration_validate import SKY_TRIM_FRACTION, tol_scale

# Sidereal rotation rate.
SIDEREAL_DEG_PER_MIN = 360.0 / (23.9345 * 60.0)

# Polaris's angular distance from the NCP (~0.65° epoch-2026; shrinks slowly).
POLARIS_POLAR_DEG = 0.65

# Window requirements. Below ~35 min the predicted Polaris arc (~2 px at
# reference resolution) is too close to centroid noise to separate a true
# pole star from a static light. 35 min also matches the cold-start
# bootstrap's minimum baseline, so a bootstrap always has a pole window.
MIN_FRAMES = 6
MIN_SPAN_MINUTES = 35.0

# A stationary candidate must be present (within the cluster tolerance) in at
# least this fraction of the window's frames.
PRESENCE_FRACTION = 0.7

# Cluster tolerance and static-light drift floor at the reference resolution
# (both scaled by tol_scale). 18 px comfortably contains Polaris's drift over
# any window while separating neighbouring stars.
CLUSTER_TOL_REF_PX = 18.0

# Accepted measured-drift band relative to the predicted Polaris arc.
# Static lights measure ~0.2× (pure centroid noise); lights on a moving
# telescope measured 5–10×; Polaris measured 1.0× on the reference rig.
DRIFT_BAND = (0.35, 2.5)

# Absolute lower bound on accepted drift, regardless of the band. A perfectly
# static source still shows a noise-only extent of ~1.1–1.3 px over a dozen
# frames (sub-pixel centroid jitter), which at short windows can exceed
# DRIFT_BAND[0] × arc — without this floor a bright interior LED could
# out-flux Polaris and poison every pole check. Centroid noise is
# resolution-independent, so the floor is absolute pixels.
STATIC_NOISE_FLOOR_PX = 1.5

# Candidates closer than this fraction of sky_r to the circle edge are
# equipment/horizon lights, not sky (Polaris sits well inside for any
# latitude where it's worth calibrating).
EDGE_MARGIN_FRACTION = 0.05

# The pole must be at altitude == |latitude|; below this it is too close to
# the trimmed detection edge to ever be measured.
MIN_LATITUDE_DEG = 20.0

# Sign vote: the winning direction must beat the loser by this factor AND by
# this many absolute matches to be trusted for east_left.
SIGN_MIN_RATIO = 1.3
SIGN_MIN_MARGIN = 8

# Frames sampled from large buffers (clustering and voting are O(frames²)ish).
_MAX_SAMPLE_FRAMES = 12


@dataclass
class PoleEstimate:
    """Measured celestial-pole pixel position + field-rotation direction."""
    x: float
    y: float
    east_left: Optional[bool]   # None when the sign vote was inconclusive
    sign: int                   # -1 = clockwise in array coords (y down)
    n_frames: int
    span_minutes: float
    drift_px: float             # measured drift of the pole-star track
    flux: float                 # median flux of the pole-star track
    sign_votes: Tuple[int, int]  # (matches for +1, matches for -1)


def predicted_polaris_arc_px(sky_r: float, span_minutes: float) -> float:
    """Pixel arc Polaris sweeps around the pole over the window.

    px/deg is approximated from the untrimmed sky radius spanning ~90° of
    altitude — measured to match the reference rig within a few percent.
    """
    px_per_deg = (float(sky_r) / (1.0 - SKY_TRIM_FRACTION)) / 90.0
    rot_rad = np.radians(SIDEREAL_DEG_PER_MIN * float(span_minutes))
    return POLARIS_POLAR_DEG * px_per_deg * rot_rad


def find_pole(
    frames: List[dict],
    lat_deg: float,
    sky_cx: Optional[float] = None,
    sky_cy: Optional[float] = None,
    sky_r: Optional[float] = None,
) -> Optional[PoleEstimate]:
    """Locate the celestial pole from buffered detections, or None.

    None is a normal outcome (short window, cloudy pole, obstructed Polaris,
    southern hemisphere) — callers must treat the pole as an *optional* extra
    constraint, never a requirement.
    """
    if lat_deg < MIN_LATITUDE_DEG:
        return None
    usable = [f for f in frames if f.get('detected') and f.get('dt') is not None]
    if len(usable) < MIN_FRAMES:
        return None

    usable.sort(key=lambda f: f['dt'])
    span_min = (usable[-1]['dt'] - usable[0]['dt']).total_seconds() / 60.0
    if span_min < MIN_SPAN_MINUTES:
        return None

    if sky_cx is None or sky_cy is None or sky_r is None:
        rs = [(f.get('sky_cx'), f.get('sky_cy'), f.get('sky_r'))
              for f in usable if f.get('sky_r')]
        if not rs:
            return None
        sky_cx = float(np.median([r[0] for r in rs]))
        sky_cy = float(np.median([r[1] for r in rs]))
        sky_r = float(np.median([r[2] for r in rs]))

    sample = _sample_frames(usable, _MAX_SAMPLE_FRAMES)
    dets = [np.asarray([(d[0], d[1], d[2]) for d in f['detected']], dtype=float)
            for f in sample]

    tol = CLUSTER_TOL_REF_PX * tol_scale(sky_r)
    candidate = _best_stationary_candidate(
        dets, sample, sky_cx, sky_cy, sky_r, tol, span_min)
    if candidate is None:
        return None
    pole_x, pole_y, drift, flux, n_hits = candidate

    sign, votes = _rotation_sign(sample, dets, pole_x, pole_y, sky_r)
    east_left = None
    if sign != 0:
        # Empirical calibration (northern hemisphere, reference rig):
        # east_left=True frames rotate clockwise in array coords (sign=-1).
        # Southern hemisphere rotates the other way around the SCP.
        east_left = (sign < 0) if lat_deg >= 0 else (sign > 0)

    est = PoleEstimate(
        x=float(pole_x), y=float(pole_y), east_left=east_left, sign=sign,
        n_frames=len(sample), span_minutes=float(span_min),
        drift_px=float(drift), flux=float(flux), sign_votes=votes,
    )
    log.info(
        f"Pole estimate: ({est.x:.1f}, {est.y:.1f}) from {n_hits}/{len(sample)} "
        f"frames over {span_min:.0f} min (drift {drift:.1f}px, "
        f"sign {sign:+d}, east_left={east_left}, votes {votes})"
    )
    return est


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _sample_frames(frames: List[dict], k: int) -> List[dict]:
    if len(frames) <= k:
        return frames
    idx = np.linspace(0, len(frames) - 1, k).round().astype(int)
    return [frames[i] for i in dict.fromkeys(idx.tolist())]


def _best_stationary_candidate(
    dets: List[np.ndarray],
    sample: List[dict],
    sky_cx: float,
    sky_cy: float,
    sky_r: float,
    tol: float,
    span_min: float,
) -> Optional[Tuple[float, float, float, float, int]]:
    """Brightest detection track that stays put — Polaris.

    Seeds come from three probe frames (first / middle / last) so a pole star
    occluded at the window start is still found; presence is then counted
    against every sampled frame.
    """
    probes = [dets[0], dets[len(dets) // 2], dets[-1]]
    seeds = np.vstack(probes)[:, :2]
    # Deduplicate seeds within tol (vectorised greedy pass).
    keep: List[np.ndarray] = []
    for s in seeds:
        if keep and np.min(np.hypot(*(np.array(keep) - s).T)) < tol:
            continue
        keep.append(s)
    seeds = np.array(keep)

    arc = predicted_polaris_arc_px(sky_r, span_min)
    min_drift = max(DRIFT_BAND[0] * arc, STATIC_NOISE_FLOOR_PX)
    max_drift = DRIFT_BAND[1] * arc
    edge_r = sky_r - max(40.0, EDGE_MARGIN_FRACTION * sky_r)

    best = None  # (flux, x, y, drift, n_hits)
    need = int(np.ceil(PRESENCE_FRACTION * len(dets)))
    for sx, sy in seeds:
        if np.hypot(sx - sky_cx, sy - sky_cy) > edge_r:
            continue
        hits = []
        for det in dets:
            d = np.hypot(det[:, 0] - sx, det[:, 1] - sy)
            j = int(np.argmin(d))
            if d[j] <= tol:
                hits.append(det[j])
        if len(hits) < need:
            continue
        h = np.array(hits)
        drift = float(np.hypot(h[:, 0].max() - h[:, 0].min(),
                               h[:, 1].max() - h[:, 1].min()))
        if not (min_drift <= drift <= max_drift):
            continue
        flux = float(np.median(h[:, 2]))
        if best is None or flux > best[0]:
            best = (flux, float(h[:, 0].mean()), float(h[:, 1].mean()),
                    drift, len(hits))
    if best is None:
        return None
    flux, x, y, drift, n_hits = best
    return x, y, drift, flux, n_hits


def _rotation_sign(
    sample: List[dict],
    dets: List[np.ndarray],
    pole_x: float,
    pole_y: float,
    sky_r: float,
) -> Tuple[int, Tuple[int, int]]:
    """Vote on the field-rotation direction around the measured pole.

    For each long-baseline frame pair, rotate the earlier detections about the
    pole by ±(sidereal × gap) and count how many land on a detection in the
    later frame. Fisheye distortion degrades the *count* symmetrically, so the
    comparison stays valid even though the rotation model is approximate.
    """
    tol = 20.0 * tol_scale(sky_r)
    votes = {1: 0, -1: 0}
    for i in range(len(sample)):
        for j in range(i + 1, len(sample)):
            gap_min = (sample[j]['dt'] - sample[i]['dt']).total_seconds() / 60.0
            if gap_min < 15.0:
                continue
            theta = np.radians(SIDEREAL_DEG_PER_MIN * gap_min)
            a, b = dets[i][:, :2], dets[j][:, :2]
            for sign in (1, -1):
                rot = _rotate(a, pole_x, pole_y, sign * theta)
                d2 = ((rot[:, None, :] - b[None, :, :]) ** 2).sum(-1)
                votes[sign] += int((d2.min(axis=1) <= tol * tol).sum())

    plus, minus = votes[1], votes[-1]
    win, lose = max(plus, minus), min(plus, minus)
    if win >= SIGN_MIN_RATIO * max(lose, 1) and win - lose >= SIGN_MIN_MARGIN:
        return (1 if plus > minus else -1), (plus, minus)
    return 0, (plus, minus)


def _rotate(pts: np.ndarray, cx: float, cy: float, ang: float) -> np.ndarray:
    c, s = np.cos(ang), np.sin(ang)
    x, y = pts[:, 0] - cx, pts[:, 1] - cy
    return np.column_stack([cx + c * x - s * y, cy + s * x + c * y])
