"""
Admission of a candidate calibration model against the incumbent.

The per-model gates (lens polynomial, a1 vs sky circle, bright anchors,
match count) judge a candidate on its own. This module judges it against
what is already known about the rig, which fixes the failure mode from
issue #10 (2026-09): a contaminated pole measurement vetoed a converged,
anchor-passing model 16 times in one night, while the seedless "basin
escape" that the vetoes triggered produced wrong-scale candidates
(a1 ≈ 1008–1044 against a true ~1283) that passed every per-model gate and
were only kept out by that same untrustworthy pole check.

Trust ladder, highest first:

1. A GUIDED incumbent (solved from user-identified anchors) defines the
   basin. A replacement must keep its mirror, its plate scale and project
   the celestial pole where the incumbent does; the measured pole becomes
   advisory (logged, never a veto). The user's clicks outrank a pole
   measured from a field of tracking-mount lights — on the #10 rig the
   guided solve (RMS 2.4 px, a1 = 1269) and the vetoed refinements
   (a1 = 1283) agreed to 1.1 %.
2. Any CREDIBLE incumbent — valid, and passing the lens-polynomial and
   a1-vs-sky-circle gates — vouches for the two rig invariants that never
   change on an installation: the mirror convention and the plate scale.
   Its orientation basin is not locked (that is what basin escape is for),
   so the measured pole still gates the candidate when one is trusted.
3. No incumbent, or an incumbent that fails its own physical gates (the
   2026-06-23 incident model: a3 pinned at the bound, a1 at 0.57× the sky
   circle) — nothing is inherited; only the measured pole applies, and
   only when pole_consensus trusts it.

Plate-scale continuity: SCALE_CONTINUITY_MAX_DEV = 10 %. Same-rig fits agree
far closer than that — guided vs refined on the #10 rig 1.011, bootstrap vs
truth on the reference rig 0.993 — while the wrong-scale escape candidates
sat at 0.79–0.81 and the incident model at 0.51. Ten percent is nine times
the observed same-basin spread and leaves nine points of margin to the
nearest wrong-scale fit ever observed.

Pole continuity between two models reuses POLE_TOL_REF_PX (140 px scaled):
the same generous "regional model error at the pole" tolerance the measured
pole gate uses — two good fits of one rig differ by 15–90 px there (P5
validation), wrong basins by 400–1400 px.
"""
from typing import Optional, Tuple

import numpy as np

from services.logger import app_logger as log

from .calibration_validate import (
    POLE_TOL_REF_PX,
    tol_scale,
    validate_a1_scale,
    validate_lens_polynomial,
    validate_pole,
)

PROVENANCE_GUIDED = 'guided'
SCALE_CONTINUITY_MAX_DEV = 0.10

# Frames whose aspect ratios differ by more than this are a crop, not a
# resize — no single scale factor relates their pixels (as validate_pole).
_ASPECT_TOL = 0.02


def is_guided(model) -> bool:
    return bool(model is not None
                and getattr(model, 'provenance', '') == PROVENANCE_GUIDED)


def is_credible_incumbent(model, sky_r: Optional[float]) -> bool:
    """Can this incumbent vouch for the rig's mirror and plate scale?"""
    if model is None or not model.is_valid():
        return False
    if is_guided(model):
        return True
    return validate_lens_polynomial(model)[0] and validate_a1_scale(model, sky_r)[0]


def frame_scale(candidate, incumbent) -> Optional[float]:
    """Pixel scale factor from the incumbent's frame to the candidate's.

    1.0 when both resolutions are unknown (assumed equal) or equal; None
    when exactly one is unknown or the aspect ratios differ (a crop) — we do
    not guess at a factor we cannot derive.
    """
    cw = int(getattr(candidate, 'image_width', 0) or 0)
    ch = int(getattr(candidate, 'image_height', 0) or 0)
    iw = int(getattr(incumbent, 'image_width', 0) or 0)
    ih = int(getattr(incumbent, 'image_height', 0) or 0)
    if cw <= 0 and iw <= 0:
        return 1.0
    if cw <= 0 or iw <= 0:
        return None
    if cw == iw and (ch == ih or ch <= 0 or ih <= 0):
        return 1.0
    if ch > 0 and ih > 0:
        ar_c, ar_i = cw / ch, iw / ih
        if abs(ar_c - ar_i) / max(ar_c, ar_i) > _ASPECT_TOL:
            return None
    return cw / iw


def scale_ratio(candidate, incumbent) -> Optional[float]:
    """candidate.a1 / incumbent.a1 with both expressed in the candidate's frame."""
    s = frame_scale(candidate, incumbent)
    if s is None or float(incumbent.a1) <= 0:
        return None
    return float(candidate.a1) / (float(incumbent.a1) * s)


def projected_pole(model, lat_deg: float) -> Optional[Tuple[float, float]]:
    """Where `model` puts the visible celestial pole (alt = |lat|, az N/S)."""
    return model.altaz_to_pixel(abs(float(lat_deg)), 0.0 if lat_deg >= 0 else 180.0)


def pole_offset_px(candidate, incumbent, lat_deg: float) -> Optional[float]:
    """Distance between the two models' projected poles, in candidate pixels.

    None when either projects the pole off-image or the frames cannot be
    related by a single scale factor.
    """
    s = frame_scale(candidate, incumbent)
    pc = projected_pole(candidate, lat_deg)
    pi = projected_pole(incumbent, lat_deg)
    if s is None or pc is None or pi is None:
        return None
    return float(np.hypot(pc[0] - pi[0] * s, pc[1] - pi[1] * s))


def east_left_hint(incumbent, pole, sky_r: Optional[float]) -> Optional[bool]:
    """Mirror convention to restrict a cold-start/escape orientation search.

    A credible incumbent knows the rig's mirror outright; otherwise the
    consensus pole's repeated vote; otherwise nothing (search both halves).
    A wrong hint is worse than none — it guarantees a wrong-basin result —
    which is why the raw single-run vote is never used here.
    """
    if is_credible_incumbent(incumbent, sky_r):
        return bool(incumbent.east_left)
    if pole is not None and pole.east_left is not None:
        return bool(pole.east_left)
    return None


def inherit_provenance(candidate, incumbent) -> None:
    """A candidate admitted as the same basin as a guided incumbent is
    human-anchored too — the lock must survive the replacement."""
    if is_guided(incumbent):
        candidate.provenance = PROVENANCE_GUIDED


def admit_candidate(
    candidate,
    incumbent,
    lat_deg: float,
    pole,
    sky_r: Optional[float],
    pole_image_width: Optional[int] = None,
    pole_image_height: Optional[int] = None,
) -> Tuple[bool, str]:
    """Gate an automatic candidate (refinement / bootstrap / basin escape).

    `pole` is the consensus-resolved estimate (pole_consensus.PoleHistory) or
    None when nothing is trusted; `sky_r` is the buffer's median sky radius,
    i.e. measured in the candidate's frame.
    """
    notes = []
    if is_credible_incumbent(incumbent, sky_r):
        if bool(candidate.east_left) != bool(incumbent.east_left):
            return False, (
                f"candidate east_left={candidate.east_left} contradicts the "
                f"incumbent's {incumbent.east_left} — the mirror convention "
                "never changes on a rig; mirrored fit"
            )
        ratio = scale_ratio(candidate, incumbent)
        if ratio is None:
            notes.append("scale continuity skipped (resolutions not comparable)")
        elif abs(ratio - 1.0) > SCALE_CONTINUITY_MAX_DEV:
            return False, (
                f"candidate a1={candidate.a1:.0f} is {ratio:.2f}x the incumbent's "
                f"plate scale — the lens scale never changes on a rig (limit "
                f"±{SCALE_CONTINUITY_MAX_DEV:.0%}); wrong-scale fit"
            )
        else:
            notes.append(f"plate scale {ratio:.3f}x incumbent")

        if is_guided(incumbent):
            d = pole_offset_px(candidate, incumbent, lat_deg)
            tol = POLE_TOL_REF_PX * tol_scale(sky_r)
            if d is None:
                notes.append("pole continuity skipped (projection unavailable)")
            elif d > tol:
                return False, (
                    f"candidate places the celestial pole {d:.0f}px from where "
                    f"the guided (user-anchored) model puts it — limit "
                    f"{tol:.0f}px; different basin"
                )
            else:
                notes.append(f"pole {d:.0f}px from the guided model's (tol {tol:.0f}px)")
            if pole is not None:
                ok, msg = validate_pole(candidate, lat_deg, pole, sky_r=sky_r,
                                        pole_image_width=pole_image_width,
                                        pole_image_height=pole_image_height)
                if not ok:
                    log.warning(
                        f"Measured pole disagrees with a candidate admitted on "
                        f"the guided model's authority ({msg}) — the measured "
                        "pole is advisory when user anchors exist")
            return True, "admitted against the guided incumbent: " + "; ".join(notes)

    ok, msg = validate_pole(candidate, lat_deg, pole, sky_r=sky_r,
                            pole_image_width=pole_image_width,
                            pole_image_height=pole_image_height)
    if not ok:
        return False, msg
    return True, "; ".join(notes + [msg])


def admit_manual(
    candidate,
    lat_deg: float,
    pole,
    sky_r: Optional[float],
    pole_image_width: Optional[int] = None,
    pole_image_height: Optional[int] = None,
) -> Tuple[bool, str]:
    """Gate a user-initiated result (Calibrate Now / guided).

    User intent wins over the incumbent — no continuity checks. A guided
    model is not vetoed by the measured pole at all: its basin is
    human-verified, the pole is measured from an uncontrolled field.
    """
    if is_guided(candidate):
        if pole is not None:
            ok, msg = validate_pole(candidate, lat_deg, pole, sky_r=sky_r,
                                    pole_image_width=pole_image_width,
                                    pole_image_height=pole_image_height)
            if not ok:
                log.warning(
                    f"Measured pole disagrees with the guided calibration ({msg}) "
                    "— trusting the user's anchors; if the overlay is wrong, "
                    "re-check the identified stars")
        return True, "guided calibration — user anchors outrank the measured pole"
    return validate_pole(candidate, lat_deg, pole, sky_r=sky_r,
                         pole_image_width=pole_image_width,
                         pole_image_height=pole_image_height)
