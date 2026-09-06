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

Authority follows evidence. An incumbent may constrain its replacement only
to the extent something other than its own fit vouched for it — the
per-model gates demonstrably do not separate the wrong-scale basin (the #10
escape candidates passed all of them), so an incumbent that was admitted on
"no pole estimate — check skipped" has no standing to lock anything. The
first cut of this module let any gate-passing incumbent lock mirror and
scale, which turned a wrong-scale cold-start fit into a permanent lockout:
the correct model was rejected as "1.25x the incumbent's plate scale" on
every later run, no matter how much evidence arrived with it.

Trust ladder, highest first. `FisheyeModel.provenance` records the rung:

1. GUIDED ('guided') — solved from user-identified anchors, or admitted as
   the same basin as such a model. Defines the basin: a replacement must
   keep its mirror, its plate scale and project the celestial pole where
   the incumbent does; the measured pole is advisory (logged, never a
   veto). The user's clicks outrank a pole measured from a field of
   tracking-mount lights — on the #10 rig the guided solve (RMS 2.4 px,
   a1 = 1269) and the vetoed refinements (a1 = 1283) agreed to 1.1 %.
2. POLE-CORROBORATED ('pole') — admitted while a trusted measured pole
   (pole_consensus) confirmed where it projects the pole, or admitted as
   the same basin as such a model. Locks mirror, scale and basin exactly
   as a guided model does, for as long as nothing better is known. When a
   trusted pole is available on a later run, that fresh measurement
   outranks the incumbent's older one: a candidate that passes the pole
   gate is admitted and any continuity conflict is logged, so a model
   corroborated by a stable contaminant can still be displaced once the
   genuine pole is measured. The one exception is the mirror when the
   current pole has no repeated rotation vote — then the incumbent's
   verified mirror is the only mirror evidence and still binds.
   The rung AGES: it is honoured only while the pole has been trusted
   within the last POLE_AUTHORITY_MAX_UNTRUSTED_RUNS recorded runs. The
   stamp is persisted, but the evidence behind it is a measurement of the
   field, and a camera repositioned during maintenance (a documented event
   on this project's own rig) into an orientation where Polaris is hidden
   would otherwise reject the correct new-geometry bootstrap as "different
   basin" against an incumbent nothing has vouched for since the move —
   every escape, forever. The horizon is the pole history length: once
   nothing in the history corroborates the field any more, the incumbent's
   corroboration is off the record too. It is reversible — the next
   trusted pole resets the count and the stamp binds again.
3. UNCORROBORATED ('' — automatic fit admitted without a trusted pole,
   Calibrate Now without one, or a legacy file) — inherits nothing. The
   candidate is gated by the measured pole alone, and only when
   pole_consensus trusts one. Two uncorroborated fits at different scales
   are symmetric ignorance; neither may veto the other.

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

The admit_* functions stamp `candidate.provenance` on admission, because
admission is where the evidence is weighed: that stamp is what gives the
model its authority as the next incumbent.
"""
from typing import List, Optional, Tuple

import numpy as np

from services.logger import app_logger as log

from .calibration_validate import (
    POLE_TOL_REF_PX,
    tol_scale,
    validate_lens_polynomial,
    validate_pole,
)
from .pole_consensus import POLE_HISTORY_LEN

PROVENANCE_GUIDED = 'guided'
PROVENANCE_POLE = 'pole'
SCALE_CONTINUITY_MAX_DEV = 0.10

# Consecutive recorded runs with no trusted pole after which a 'pole'
# incumbent stops constraining its replacement (module doc, rung 2).
POLE_AUTHORITY_MAX_UNTRUSTED_RUNS = POLE_HISTORY_LEN

# Frames whose aspect ratios differ by more than this are a crop, not a
# resize — no single scale factor relates their pixels (as validate_pole).
_ASPECT_TOL = 0.02


def is_guided(model) -> bool:
    return bool(model is not None
                and getattr(model, 'provenance', '') == PROVENANCE_GUIDED)


def is_pole_corroborated(model) -> bool:
    return bool(model is not None
                and getattr(model, 'provenance', '') == PROVENANCE_POLE)


def incumbent_authority(model, runs_without_pole: int = 0) -> Optional[str]:
    """The provenance rung on which `model` may constrain its replacement.

    PROVENANCE_GUIDED, PROVENANCE_POLE, or None when the incumbent has no
    standing (missing, invalid, uncorroborated, a pole-corroborated model
    whose corroboration has aged out — `runs_without_pole` is
    PoleHistory.runs_since_trusted — or, for a corroborated model, an
    implausible lens polynomial, which a stamped file should never carry
    but a hand-edited one might). The a1-vs-sky-circle gate is
    deliberately NOT re-run here: it was applied in the incumbent's own
    frame when it was admitted, and the buffer's sky radius is in the
    candidate's frame, which differs whenever the incumbent came from a
    manual or guided fit against the pre-resize raw frame.
    """
    if model is None or not model.is_valid():
        return None
    if is_guided(model):
        return PROVENANCE_GUIDED
    if (is_pole_corroborated(model)
            and runs_without_pole < POLE_AUTHORITY_MAX_UNTRUSTED_RUNS
            and validate_lens_polynomial(model)[0]):
        return PROVENANCE_POLE
    return None


def is_credible_incumbent(model, runs_without_pole: int = 0) -> bool:
    """Can this incumbent vouch for the rig's mirror and plate scale?"""
    return incumbent_authority(model, runs_without_pole) is not None


def admission_evidence(incumbent, pole, runs_without_pole: int = 0) -> bool:
    """Did admit_candidate weigh anything beyond the candidate's own fit?

    True when the incumbent had authority (the candidate passed continuity
    with it, or a trusted pole outranked it) or a trusted pole gated the
    candidate. False is the "no pole estimate — check skipped; incumbent is
    uncorroborated" admission: the candidate proved nothing except that it
    passed the per-model gates, which the #10 wrong-scale escapes also did.
    calibration_service lets a basin-escape result bypass the RMS guard
    only on evidence — on every pre-provenance installation the on-disk
    model loads uncorroborated, and a seedless bootstrap over a hazy
    buffer must not overwrite it unconditionally.
    """
    return (incumbent_authority(incumbent, runs_without_pole) is not None
            or pole is not None)


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


def east_left_hint(incumbent, pole, runs_without_pole: int = 0) -> Optional[bool]:
    """Mirror convention to restrict a cold-start/escape orientation search.

    A guided incumbent knows the rig's mirror outright; otherwise the
    consensus pole's repeated vote (fresh evidence); otherwise a
    pole-corroborated incumbent's; otherwise nothing (search both halves).
    A wrong hint is worse than none — it guarantees a wrong-basin result —
    which is why neither the raw single-run vote nor an uncorroborated
    incumbent is used here: the latter is how a wrong-mirror cold-start fit
    used to steer every later search into its own half.
    """
    authority = incumbent_authority(incumbent, runs_without_pole)
    if authority == PROVENANCE_GUIDED:
        return bool(incumbent.east_left)
    if pole is not None and pole.east_left is not None:
        return bool(pole.east_left)
    if authority == PROVENANCE_POLE:
        return bool(incumbent.east_left)
    return None


# ---------------------------------------------------------------------------
# Continuity checks against an incumbent with authority
# ---------------------------------------------------------------------------

_WHO = {PROVENANCE_GUIDED: "the guided (user-anchored) model",
        PROVENANCE_POLE: "the pole-corroborated incumbent"}


def _mirror_veto(candidate, incumbent, who: str) -> Optional[str]:
    if bool(candidate.east_left) == bool(incumbent.east_left):
        return None
    return (f"candidate east_left={candidate.east_left} contradicts "
            f"{who}'s {incumbent.east_left} — the mirror convention "
            "never changes on a rig; mirrored fit")


def _scale_veto(candidate, incumbent, who: str, notes: List[str]) -> Optional[str]:
    ratio = scale_ratio(candidate, incumbent)
    if ratio is None:
        notes.append("scale continuity skipped (resolutions not comparable)")
        return None
    if abs(ratio - 1.0) > SCALE_CONTINUITY_MAX_DEV:
        return (f"candidate a1={candidate.a1:.0f} is {ratio:.2f}x {who}'s "
                f"plate scale — the lens scale never changes on a rig (limit "
                f"±{SCALE_CONTINUITY_MAX_DEV:.0%}); wrong-scale fit")
    notes.append(f"plate scale {ratio:.3f}x incumbent")
    return None


def _basin_veto(candidate, incumbent, lat_deg: float, sky_r: Optional[float],
                who: str, notes: List[str]) -> Optional[str]:
    d = pole_offset_px(candidate, incumbent, lat_deg)
    tol = POLE_TOL_REF_PX * tol_scale(sky_r)
    if d is None:
        notes.append("pole continuity skipped (projection unavailable)")
        return None
    if d > tol:
        return (f"candidate places the celestial pole {d:.0f}px from where "
                f"{who} puts it — limit {tol:.0f}px; different basin")
    notes.append(f"pole {d:.0f}px from the incumbent's (tol {tol:.0f}px)")
    return None


def _continuity(candidate, incumbent, lat_deg: float, sky_r: Optional[float],
                who: str, notes: List[str]) -> Optional[str]:
    """First continuity failure against an authoritative incumbent, or None."""
    return (_mirror_veto(candidate, incumbent, who)
            or _scale_veto(candidate, incumbent, who, notes)
            or _basin_veto(candidate, incumbent, lat_deg, sky_r, who, notes))


# ---------------------------------------------------------------------------
# Admission
# ---------------------------------------------------------------------------

def admit_candidate(
    candidate,
    incumbent,
    lat_deg: float,
    pole,
    sky_r: Optional[float],
    pole_image_width: Optional[int] = None,
    pole_image_height: Optional[int] = None,
    runs_without_pole: int = 0,
) -> Tuple[bool, str]:
    """Gate an automatic candidate (refinement / bootstrap / basin escape).

    `pole` is the consensus-resolved estimate (pole_consensus.PoleHistory) or
    None when nothing is trusted; `sky_r` is the buffer's median sky radius,
    i.e. measured in the candidate's frame; `runs_without_pole` ages the
    incumbent's pole corroboration (incumbent_authority). On admission the
    candidate's provenance is stamped with the evidence it was admitted on
    (module doc). Whether that evidence existed at all is a separate
    question the caller asks admission_evidence() with the same inputs.
    """
    pole_kw = dict(sky_r=sky_r, pole_image_width=pole_image_width,
                   pole_image_height=pole_image_height)
    authority = incumbent_authority(incumbent, runs_without_pole)

    if authority is None:
        ok, msg = validate_pole(candidate, lat_deg, pole, **pole_kw)
        if not ok:
            return False, msg
        if pole is not None:
            candidate.provenance = PROVENANCE_POLE
        elif incumbent is not None:
            msg += ("; incumbent is uncorroborated — no mirror/scale "
                    "continuity inherited")
        return True, msg

    notes: List[str] = []
    veto = _continuity(candidate, incumbent, lat_deg, sky_r, _WHO[authority], notes)

    if authority == PROVENANCE_GUIDED:
        if veto:
            return False, veto
        if pole is not None:
            ok, msg = validate_pole(candidate, lat_deg, pole, **pole_kw)
            if not ok:
                log.warning(
                    f"Measured pole disagrees with a candidate admitted on "
                    f"the guided model's authority ({msg}) — the measured "
                    "pole is advisory when user anchors exist")
        candidate.provenance = PROVENANCE_GUIDED
        return True, "admitted against the guided incumbent: " + "; ".join(notes)

    # Pole-corroborated incumbent.
    if pole is None:
        if veto:
            return False, veto
        candidate.provenance = PROVENANCE_POLE
        return True, ("admitted against the pole-corroborated incumbent "
                      "(no pole this run): " + "; ".join(notes))

    ok, msg = validate_pole(candidate, lat_deg, pole, **pole_kw)
    if not ok:
        return False, msg
    mirror = _mirror_veto(candidate, incumbent, _WHO[authority])
    if mirror and pole.east_left is None:
        return False, mirror + " (measured pole has no repeated rotation vote)"
    if veto:
        log.warning(
            f"Candidate passes the measured pole but not continuity with the "
            f"pole-corroborated incumbent ({veto}) — the fresh pole measurement "
            "outranks the incumbent's older corroboration; admitting")
    candidate.provenance = PROVENANCE_POLE
    return True, "; ".join([msg] + notes)


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
    human-verified, the pole is measured from an uncontrolled field. A
    Calibrate Now result confirmed by a trusted pole is stamped
    pole-corroborated so it carries that authority as the incumbent.
    """
    pole_kw = dict(sky_r=sky_r, pole_image_width=pole_image_width,
                   pole_image_height=pole_image_height)
    if is_guided(candidate):
        if pole is not None:
            ok, msg = validate_pole(candidate, lat_deg, pole, **pole_kw)
            if not ok:
                log.warning(
                    f"Measured pole disagrees with the guided calibration ({msg}) "
                    "— trusting the user's anchors; if the overlay is wrong, "
                    "re-check the identified stars")
        return True, "guided calibration — user anchors outrank the measured pole"
    ok, msg = validate_pole(candidate, lat_deg, pole, **pole_kw)
    if ok and pole is not None:
        candidate.provenance = PROVENANCE_POLE
    return ok, msg
