"""
Cross-run consensus on the measured celestial pole.

find_pole is stateless: one buffer window in, one estimate out. On a fixed
camera the pole cannot move, so the *sequence* of estimates over a night is
itself evidence about whether any of them can be trusted (issue #10, 2026-09):
a hosting-site rig produced six mutually exclusive pole positions across 20
runs — (1822,2765)×6, (988,1792)×4, (1905,685)×4, (1646,667)×3, … — and the
admission gate vetoed a good, converged model 16 times on the strength of
whichever one the latest run happened to return.

What this module does NOT do is require self-consistency: the dominant
contaminant in that log was stable to ±1 px across 43 minutes. Stability
admits it. The discriminating signal is the opposite one — several distinct
clusters from a camera that cannot have moved means the field is
contaminated and *no* estimate should gate anything. So:

  - a history with no dominant mode → the pole is UNKNOWN (None, and
    calibration_validate.validate_pole skips on None). A dominant mode is
    one cluster holding at least DOMINANT_MODE_FRACTION of the found runs:
    strict unimodality let a single aircraft, satellite trail or cloud-edge
    outlier disable the gate for a full history length, which was exactly
    the window in which an uncorroborated model could get in
    (model_admission). The #10 log never puts more than a third of any
    window into one cluster, so it is still rejected outright;
  - an estimate that is itself outside the dominant mode is the outlier
    and is not trusted, even though the history is;
  - a pole found in fewer than half of the recent runs is flickering — a
    genuine Polaris was found in 26/26 windows on the reference frames,
    while a near-pole contaminant on a hidden pole cleared the rotation
    floor in 2–8 of 26 — so it is treated as unknown too;
  - the mirror (east_left) is only asserted when a decisive rotation vote
    REPEATS: two or more RECORDED runs agree and none disagree. In the #10
    log the one decisive vote in the window came from a contaminant and
    was wrong.

Recording and reading are separate operations. The refine worker records
one entry per run (record); every other reader — the manual Calibrate Now /
guided paths, which ask what the field has established — uses current(),
which never writes. The first cut had a single resolve() that appended on
every call, so two reads of the same buffer manufactured a "repeated" vote
from one physical measurement (Calibrate Now clicked twice inside the
cooldown was enough).

Known limit: consecutive refine runs a few minutes apart share most of a
60-frame rolling buffer, so two recorded votes are correlated, not
independent. The repeat requirement defeats a single contaminated window;
it is not a statistical guarantee.

The link tolerance for "same cluster" is half the pole gate's own tolerance
(POLE_TOL_REF_PX / 2 = 70 px at reference scale, resolution-scaled). A
genuine Polaris estimate is the mean of its 0.65° orbit over the window, so
two windows hours apart differ by at most ~2 × 12 px ≈ 24 px at reference
scale: three times inside the link. Contaminant clusters in the #10 log were
35–1200 px apart; the sub-100 px ones merge, which changes nothing — the
history still has no dominant mode.

Thread-safe: record() runs on the refine worker thread, current() on the
GUI thread (manual calibration paths). Both snapshot the deque under the
lock and evaluate the copy.
"""
import threading
from collections import deque
from dataclasses import replace
from typing import Deque, List, Optional, Sequence, Tuple

import numpy as np

from services.logger import app_logger as log

from .calibration_validate import POLE_TOL_REF_PX, tol_scale
from .pole_finder import PoleEstimate

# Runs retained. Refinements run every few minutes; a dozen spans the better
# part of an hour of runs, long enough for a slewing mount to show up twice.
POLE_HISTORY_LEN = 12

# Two estimates closer than this (at reference resolution) are one mode.
MODE_LINK_REF_PX = 0.5 * POLE_TOL_REF_PX

# A pole must have been found in at least this fraction of retained runs.
MIN_FOUND_FRACTION = 0.5

# The largest cluster must hold at least this fraction of the found runs to
# be trusted. 3-of-4 survives one outlier; the #10 log peaks at ~1/3.
DOMINANT_MODE_FRACTION = 0.75

# Decisive sign votes needed (all agreeing) before east_left is asserted.
MIN_REPEATED_SIGN_VOTES = 2


def cluster_positions(points: Sequence[Tuple[float, float]],
                      link_px: float) -> List[List[int]]:
    """Single-linkage clusters of 2-D points; returns index lists."""
    clusters: List[List[int]] = []
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    for i, p in enumerate(pts):
        for c in clusters:
            member = pts[c]
            if np.min(np.hypot(member[:, 0] - p[0], member[:, 1] - p[1])) <= link_px:
                c.append(i)
                break
        else:
            clusters.append([i])
    return clusters


def consensus_east_left(estimates: Sequence[PoleEstimate]) -> Optional[bool]:
    """Mirror convention only when decisive votes repeat and never conflict."""
    votes = [e.east_left for e in estimates if e.east_left is not None]
    if len(votes) < MIN_REPEATED_SIGN_VOTES or len(set(votes)) != 1:
        return None
    return votes[0]


def consensus(runs: Sequence[Optional[PoleEstimate]],
              sky_r: Optional[float] = None) -> Optional[PoleEstimate]:
    """The estimate the gate may use given `runs` (misses as None), or None.

    The estimate under judgement is the most recent found run. Returns a
    copy of it whose east_left is the repeated-vote consensus (None until
    it repeats).
    """
    found = [e for e in runs if e is not None]
    if not found:
        return None
    if len(found) / len(runs) < MIN_FOUND_FRACTION:
        log.info(
            f"Pole gate skipped: pole found in only {len(found)}/{len(runs)} "
            "recent runs — intermittent estimate, not trusted"
        )
        return None
    link = MODE_LINK_REF_PX * tol_scale(sky_r)
    modes = sorted(cluster_positions([(e.x, e.y) for e in found], link),
                   key=len, reverse=True)
    if len(modes) > 1:
        dominant = modes[0]
        summary = "; ".join(
            f"({np.mean([found[i].x for i in c]):.0f}, "
            f"{np.mean([found[i].y for i in c]):.0f})x{len(c)}" for c in modes)
        if len(dominant) < DOMINANT_MODE_FRACTION * len(found):
            log.warning(
                f"Pole gate skipped: the last {len(found)} pole estimates form "
                f"{len(modes)} distinct clusters ({summary}; link {link:.0f}px) on "
                "a fixed camera — the field is contaminated (lights on piers or "
                "tracking mounts), no estimate is trusted"
            )
            return None
        if len(found) - 1 not in dominant:
            log.warning(
                f"Pole gate skipped: the latest estimate ({found[-1].x:.0f}, "
                f"{found[-1].y:.0f}) is outside the dominant cluster ({summary}) "
                "— treated as a one-off outlier"
            )
            return None
        log.info(
            f"Pole history has {len(modes)} clusters ({summary}) but the "
            f"dominant one holds {len(dominant)}/{len(found)} — trusting it")
        found = [found[i] for i in dominant]
    return replace(found[-1], east_left=consensus_east_left(found))


class PoleHistory:
    """Rolling record of find_pole results with a trust decision per run."""

    def __init__(self, maxlen: int = POLE_HISTORY_LEN):
        self._lock = threading.Lock()
        # None entries record runs where no pole was found (misses).
        self._runs: Deque[Optional[PoleEstimate]] = deque(maxlen=maxlen)

    def record(self, estimate: Optional[PoleEstimate],
               sky_r: Optional[float] = None) -> Optional[PoleEstimate]:
        """Record this run's estimate and return the one the gate may use.

        One call per physical measurement (the refine worker, once per run).
        Returns None when there is nothing to trust: no estimate this run,
        no dominant mode, this estimate outside it, or a pole found in
        fewer than half the recent runs.
        """
        with self._lock:
            self._runs.append(estimate)
            runs = list(self._runs)
        if estimate is None:
            return None
        return consensus(runs, sky_r)

    def current(self, sky_r: Optional[float] = None) -> Optional[PoleEstimate]:
        """What the recorded history establishes, without recording anything.

        For readers that have no measurement of their own. The position is
        the most recent found run's (any member of the dominant mode is
        within the link tolerance of the others); the same trust rules as
        record() apply. None when nothing has been recorded or nothing is
        trusted.
        """
        with self._lock:
            runs = list(self._runs)
        return consensus(runs, sky_r) if runs else None

    def clear(self) -> None:
        with self._lock:
            self._runs.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._runs)
