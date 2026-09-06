"""
Does a completed automatic fit replace the incumbent model?

model_admission decides whether a candidate is *admissible* — the right
mirror, scale and basin for the rig. This module decides the separate
question CalibrationService asks once a candidate has been admitted: is it
a better model than the one on disk? The two are kept apart because they
weigh different things: admission weighs evidence about the rig, replacement
weighs fit quality — and fit quality alone is exactly what the #10
wrong-scale escapes had plenty of.

Rules, in order:

1. No incumbent: any admitted model is an upgrade from "no model".
2. Basin escape ON EVIDENCE: replace without the RMS guard. The escape ran
   because refinements seeded by the incumbent kept failing, and the
   candidate was admitted against something real — continuity with an
   authoritative incumbent, or a trusted measured pole. The incumbent's own
   (possibly flattering) RMS is what is in doubt and must not veto it.
   An escape with NO evidence — uncorroborated incumbent, no trusted pole —
   gets no such bypass and falls through to the normal comparison. Every
   pre-provenance installation loads its calibration uncorroborated, and
   three refinement failures on a hazy night are routine: a seedless
   bootstrap over a partly clouded buffer can produce a wrong-scale
   candidate that passes every per-model gate (the #10 a1≈1008–1044
   family), and with no evidence to admit it on, unconditional replacement
   would save that over a working model. The candidate can still win when
   it is genuinely better on the numbers (rule 4), so a wrong cold-start
   model is not a permanent lock either.
3. Guided single-solve incumbent vs a multi-image candidate: rank only. The
   guided solve's RMS is over a handful of clicked anchors, a joint fit's is
   over thousands of matches across the sky — not comparable — and the
   joint fit is the better whole-sky model (ALLSKY_CALIBRATION_PLAN:
   multi-3h beat the 9-anchor V5 fit despite the higher reported RMS). The
   candidate was admitted as the same basin, so a rank upgrade is enough.
   Once replaced, both sides carry joint RMS and rule 4 applies again.
4. Otherwise the RMS guard: reject if more than 15 % worse by RMS — a
   quality-rank upgrade is not sufficient justification for overwriting a
   precise model (a 15–20 px model used to overwrite a 3 px one just by
   accumulating frames) — and then require either a rank upgrade or a
   strict improvement (lower RMS with at least as many matches).
"""
from typing import Tuple

from .calibration_quality import CalibrationQuality
from .model_admission import is_guided

RMS_REGRESSION_TOLERANCE = 1.15


def should_replace(
    incumbent,
    incumbent_quality: str,
    candidate,
    candidate_quality: str,
    escape: bool = False,
    evidence: bool = False,
) -> Tuple[bool, str]:
    """(replace?, reason). `escape`: the candidate came from a seedless basin
    escape; `evidence`: model_admission.admission_evidence for its admission.
    """
    if incumbent is None:
        return True, "no incumbent"

    if escape and evidence:
        return True, (
            "basin escape admitted on evidence — replacing the "
            f"repeatedly-rejected model (RMS {incumbent.rms_residual:.1f}px) "
            f"with the re-calibrated one (RMS {candidate.rms_residual:.1f}px) "
            "without the RMS guard")

    rank_up = (CalibrationQuality.rank(candidate_quality)
               > CalibrationQuality.rank(incumbent_quality))

    if (is_guided(incumbent) and incumbent.n_images <= 1
            and candidate.n_images >= 3):
        if rank_up:
            return True, "multi-image refinement supersedes the guided single solve"
        return False, "no rank upgrade over the guided single solve"

    prefix = ("basin escape without evidence (uncorroborated incumbent, no "
              "trusted pole) — held to the normal comparison: "
              if escape else "")
    if candidate.rms_residual > incumbent.rms_residual * RMS_REGRESSION_TOLERANCE:
        return False, (prefix + f"RMS {candidate.rms_residual:.2f}px is more than "
                       f"{RMS_REGRESSION_TOLERANCE - 1:.0%} worse than "
                       f"{incumbent.rms_residual:.2f}px")
    if rank_up:
        return True, prefix + "quality rank upgrade within the RMS guard"
    if (candidate.rms_residual < incumbent.rms_residual
            and candidate.n_matches >= incumbent.n_matches):
        return True, prefix + "lower RMS with at least as many matches"
    return False, (prefix + f"not better (RMS {candidate.rms_residual:.2f}px vs "
                   f"{incumbent.rms_residual:.2f}px, {candidate.n_matches} vs "
                   f"{incumbent.n_matches} matches)")
