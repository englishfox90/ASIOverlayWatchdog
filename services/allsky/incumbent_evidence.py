"""
Evidence about the model on disk, gathered from the live detection buffer.

model_admission judges a *candidate* against what is known about the rig.
Nothing judged the *incumbent*: a calibration loaded from disk stayed
uncorroborated for as long as no refinement was admitted, and the basin
escape trigger inferred "the seed is poison" from candidate failures alone.
Both gaps are what let a correct model be overwritten on 2026-09-05:

  * the pole finder had reported the same genuine pole in 11 consecutive
    runs, and the incumbent projected the pole right there, yet the
    incumbent never gained the 'pole' rung because the stamp is only ever
    applied to an admitted candidate;
  * 26 consecutive seeded refinements failed the bright-anchor gate while
    the overlay drawn from the incumbent was visibly right — the refinements
    were what was failing, not the seed — and the eighth escape they
    triggered installed an axis_alt=67° model on a 0.01 px RMS margin.

Two questions, answered from the same buffer the refine worker uses:

corroborate_incumbent — does a trusted measured pole confirm where the
    incumbent puts it? If so the incumbent is stamped PROVENANCE_POLE in
    place, exactly as an admitted candidate would be, and the caller
    persists it. From then on model_admission locks mirror, scale and
    basin against it for automatic replacements. A guided model is left
    alone (it outranks the pole); a model that contradicts the trusted
    pole is reported but not demoted here — the escape path already
    handles a wrong incumbent, and a stable contaminant must not be able
    to strip authority any more than it can grant it.

incumbent_anchor_health — does the incumbent hit its bright anchors on
    the most recent frames, the same test every candidate must pass? A
    healthy seed means repeated refinement failures are a refinement
    problem, and a seedless escape has no premise. Tri-state: None when the
    frames cannot support the test (too few anchors above the altitude
    floor, no detections), so an obstructed or cloudy buffer neither
    licenses nor blocks an escape on its own.
"""
from typing import List, Optional, Tuple

from services.logger import app_logger as log

from .calibration_validate import (
    count_anchor_hits,
    model_in_frame,
    tol_scale,
    validate_pole,
)
from .model_admission import PROVENANCE_POLE, is_guided, is_pole_corroborated

# The bright-anchor gate's own parameters (calibration_validate
# .validate_bright_anchors defaults) — the incumbent is held to the same
# test as a candidate, no stricter and no looser.
ANCHOR_TOP_N = 12
ANCHOR_MIN_HITS = 5
ANCHOR_MAX_MISS_REF_PX = 40.0
ANCHOR_MIN_ALT_DEG = 40.0
RECENT_FRAMES = 3


def corroborate_incumbent(
    incumbent,
    lat_deg: float,
    pole,
    sky_r: Optional[float],
    pole_image_width: Optional[int] = None,
    pole_image_height: Optional[int] = None,
) -> Tuple[bool, str]:
    """Stamp `incumbent` PROVENANCE_POLE when the trusted `pole` confirms it.

    Returns (stamped, message). False with a reason when there is nothing
    to do (no incumbent, no trusted pole, already guided or corroborated)
    or when the incumbent contradicts the pole. Mutates `incumbent` on
    success — the caller owns persistence.
    """
    if incumbent is None or not incumbent.is_valid():
        return False, "no valid incumbent"
    if pole is None:
        return False, "no trusted pole this run"
    if is_guided(incumbent):
        return False, "guided incumbent — user anchors outrank the pole"
    if is_pole_corroborated(incumbent):
        return False, "incumbent already pole-corroborated"
    ok, msg = validate_pole(incumbent, lat_deg, pole, sky_r=sky_r,
                            pole_image_width=pole_image_width,
                            pole_image_height=pole_image_height)
    if not ok:
        log.warning(
            f"Incumbent contradicts the trusted measured pole ({msg}) — "
            "left uncorroborated; a seeded refinement or escape decides")
        return False, msg
    incumbent.provenance = PROVENANCE_POLE
    return True, f"incumbent corroborated by the measured pole ({msg})"


def incumbent_anchor_health(model, frames: List[dict],
                            recent_n: int = RECENT_FRAMES) -> Optional[bool]:
    """Does `model` pass the bright-anchor gate on the last `recent_n` frames?

    True when it passes on a majority (the candidate rule: 2 of 3), False
    when it fails on a majority, None when fewer than half the frames can
    support the test. Frames are buffer dicts as built by
    CalibrationService._detect_frame; the model is rescaled into each
    frame's resolution first (model_in_frame).
    """
    if model is None or not frames:
        return None
    recent = frames[-recent_n:]
    passed = failed = 0
    for f in recent:
        proj = model_in_frame(model, f.get('image_width'), f.get('image_height'))
        max_miss = ANCHOR_MAX_MISS_REF_PX * tol_scale(f.get('sky_r'))
        hits, n_bright, _misses = count_anchor_hits(
            proj, f.get('above_horizon', []), f.get('detected', []),
            top_n=ANCHOR_TOP_N, min_alt_deg=ANCHOR_MIN_ALT_DEG,
            max_miss_px=max_miss)
        if n_bright < ANCHOR_MIN_HITS or not f.get('detected'):
            continue
        if hits >= ANCHOR_MIN_HITS:
            passed += 1
        else:
            failed += 1
    tested = passed + failed
    if tested == 0 or tested < (len(recent) + 1) // 2:
        return None
    need = max(1, tested - 1) if tested >= 3 else tested
    return passed >= need
