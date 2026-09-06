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

Rotation support (issue #10, 2026-09-05): the drift band cannot separate
Polaris from a light on a *tracking* mount (or a static LED whose centroid
jitters 2–5 px in a stretched preview) — both sit inside the band, and
"brightest in-band track" then picks the light every run, self-consistently
(measured: 26/26 runs on the reference frames with one synthetic 2×-flux
tracking light). The discriminator is that the star field demonstrably
rotates about the true pole and not about a contaminant: rotating each
frame's detections about the candidate by ±(sidereal × gap), the correct
direction explained 4.2–5.5× as many detections as the wrong one at Polaris
in every 35–83 min window, versus 1.0–1.35× at the contaminant positions
(neither direction explains anything). Candidates are therefore ranked by
that ratio, and no estimate is returned unless the winner clears
POLE_MIN_ROTATION_RATIO — a contaminated field yields *no* pole rather than
a wrong one.

Operates on the CalibrationService buffer format: a list of dicts with keys
'dt' (aware datetime) and 'detected' ([(x, y, flux), ...]); 'sky_cx'/'sky_cy'/
'sky_r' are used when present.

Southern hemisphere: there is no bright pole star (σ Oct is mag 5.5), so this
module returns None below the equator rather than guess. The sign→east_left
mapping is still written hemisphere-aware for when a southern path exists.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

import numpy as np

from services.logger import app_logger as log

from .calibration_validate import SKY_TRIM_FRACTION, median_frame_resolution, tol_scale

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

# A stationary track only counts as the pole if the field rotates about it
# decisively: the winning direction must explain at least this many times
# as many detections as the losing one (plus SIGN_MIN_MARGIN absolute). On
# the reference frames the true pole scored 4.17–5.52 across 26 windows of
# 35–83 min; in-band contaminants far from the pole scored 1.00–1.35, and
# one 200 px / 290 px from a *hidden* pole cleared 2.0 in 26 / 12 of 26 runs
# but 2.5 in only 8 / 2. The support landscape is broad (±200 px) so no
# floor removes near-pole lights entirely; 2.5 keeps a 1.67× margin under
# the weakest genuine ratio. Erring high is the safe side: a withheld pole
# skips an optional gate, a wrong pole vetoes good models.
POLE_MIN_ROTATION_RATIO = 2.5
# Among candidates that clear the floor, those whose ratio is within this
# fraction of the best are considered tied and the brightest wins (a faint
# star within ~1° of the pole scores the same as Polaris; Polaris is the
# better position anchor).
_ROTATION_TIE_FRACTION = 0.9

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
    # The buffer window the estimate was measured over. Two estimates are
    # independent evidence only when their windows do not overlap
    # (pole_consensus); consecutive refine runs share most of one rolling
    # buffer. None = unknown (an estimate not produced by find_pole).
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    # Resolution of the frames x/y were measured on; 0 = unknown. The
    # history compares and rescales positions across resize changes.
    image_width: int = 0
    image_height: int = 0


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
    candidates = _stationary_candidates(
        dets, sample, sky_cx, sky_cy, sky_r, tol, span_min)
    if not candidates:
        return None

    # Rank by rotation support; the floor is applied to every candidate
    # BEFORE the brightness tie-break, so a brighter light just inside the
    # tie band cannot drag a genuine rotation centre below the floor and
    # withhold the pole (the tie-break only ever chooses among survivors).
    scored = []
    for cand in candidates:
        votes = _rotation_votes(sample, dets, cand[0], cand[1], sky_r)
        scored.append((_vote_ratio(votes), cand, votes))
    scored.sort(key=lambda t: (t[0], t[1][3]), reverse=True)
    supported = [t for t in scored if _decisive(t[2], POLE_MIN_ROTATION_RATIO)]
    if not supported:
        best_ratio, (bx, by, *_), best_votes = scored[0]
        log.info(
            f"Pole estimate withheld: no stationary candidate is a rotation "
            f"centre (best support {best_ratio:.2f}x at ({bx:.0f}, {by:.0f}), "
            f"votes {best_votes}, {len(candidates)} in-band candidate(s), need "
            f"{POLE_MIN_ROTATION_RATIO}x) — field contaminated or Polaris hidden"
        )
        return None
    best_ratio = supported[0][0]
    tied = [t for t in supported if t[0] >= _ROTATION_TIE_FRACTION * best_ratio]
    _ratio, (pole_x, pole_y, drift, flux, n_hits), votes = max(
        tied, key=lambda t: t[1][3])

    sign = _sign_from_votes(votes)
    east_left = None
    if sign != 0:
        # Empirical calibration (northern hemisphere, reference rig):
        # east_left=True frames rotate clockwise in array coords (sign=-1).
        # Southern hemisphere rotates the other way around the SCP.
        east_left = (sign < 0) if lat_deg >= 0 else (sign > 0)

    img_w, img_h = median_frame_resolution(usable)
    est = PoleEstimate(
        x=float(pole_x), y=float(pole_y), east_left=east_left, sign=sign,
        n_frames=len(sample), span_minutes=float(span_min),
        drift_px=float(drift), flux=float(flux), sign_votes=votes,
        window_start=usable[0]['dt'], window_end=usable[-1]['dt'],
        image_width=img_w, image_height=img_h,
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


def _stationary_candidates(
    dets: List[np.ndarray],
    sample: List[dict],
    sky_cx: float,
    sky_cy: float,
    sky_r: float,
    tol: float,
    span_min: float,
) -> List[Tuple[float, float, float, float, int]]:
    """Every detection track that stays put within the drift band.

    Returns [(x, y, drift, flux, n_hits), ...]. Seeds come from three probe
    frames (first / middle / last) so a pole star occluded at the window
    start is still found; presence is then counted against every sampled
    frame. Which survivor is the pole is decided by rotation support in
    find_pole — brightness alone picks a tracking-mount light every time.
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

    out: List[Tuple[float, float, float, float, int]] = []
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
        out.append((float(h[:, 0].mean()), float(h[:, 1].mean()),
                    drift, flux, len(hits)))
    return out


def _rotation_votes(
    sample: List[dict],
    dets: List[np.ndarray],
    pole_x: float,
    pole_y: float,
    sky_r: float,
) -> Tuple[int, int]:
    """Count detections explained by ±sidereal rotation about a candidate.

    For each long-baseline frame pair, rotate the earlier detections about the
    candidate by ±(sidereal × gap) and count how many land on a detection in
    the later frame. Fisheye distortion degrades the *count* symmetrically, so
    the comparison stays valid even though the rotation model is approximate.
    Returns (matches for +1, matches for -1).
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
    return votes[1], votes[-1]


def _vote_ratio(votes: Tuple[int, int]) -> float:
    win, lose = max(votes), min(votes)
    return win / max(lose, 1)


def _decisive(votes: Tuple[int, int], min_ratio: float) -> bool:
    win, lose = max(votes), min(votes)
    return win >= min_ratio * max(lose, 1) and win - lose >= SIGN_MIN_MARGIN


def _sign_from_votes(votes: Tuple[int, int]) -> int:
    """Field-rotation direction (+1/-1), or 0 when the vote is inconclusive."""
    if not _decisive(votes, SIGN_MIN_RATIO):
        return 0
    plus, minus = votes
    return 1 if plus > minus else -1


def _rotation_sign(
    sample: List[dict],
    dets: List[np.ndarray],
    pole_x: float,
    pole_y: float,
    sky_r: float,
) -> Tuple[int, Tuple[int, int]]:
    """Vote on the field-rotation direction around a point: (sign, votes)."""
    votes = _rotation_votes(sample, dets, pole_x, pole_y, sky_r)
    return _sign_from_votes(votes), votes


def _rotate(pts: np.ndarray, cx: float, cy: float, ang: float) -> np.ndarray:
    c, s = np.cos(ang), np.sin(ang)
    x, y = pts[:, 0] - cx, pts[:, 1] - cy
    return np.column_stack([cx + c * x - s * y, cy + s * x + c * y])
