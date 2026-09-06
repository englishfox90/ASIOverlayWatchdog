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
    strict unimodality let a single outlier run disable the gate for a
    full history length. The #10 log never puts more than a third of any
    window into one cluster, so it is still rejected outright;
  - a run in which no pole was found (a withheld window) is judged against
    the history like any other: an established consensus is still returned
    for it. A withheld run is not free — with the gate off, an escape is
    admitted "no pole estimate — check skipped" and, against an
    uncorroborated incumbent, wins on fit numbers alone; that is how a
    wrong-basin model was installed on 2026-09-05 between two trusted
    readings of the same pole;
  - an estimate that is itself outside the dominant mode is the outlier
    and is not trusted, even though the history is;
  - a pole found in fewer than half of the recent runs is flickering — a
    genuine Polaris was found in 26/26 windows on the reference frames,
    while a near-pole contaminant on a hidden pole cleared the rotation
    floor in 2–8 of 26 — so it is treated as unknown too;
  - the mirror (east_left) is only asserted when a decisive rotation vote
    REPEATS INDEPENDENTLY: MIN_REPEATED_SIGN_VOTES recorded runs agree,
    none disagree, and the agreeing runs were measured over buffer windows
    that do not overlap. In the #10 log the one decisive vote in the
    window came from a contaminant and was wrong.

Why the mirror vote has its own memory: consecutive refine runs a few
minutes apart share most of one 60-frame rolling buffer, so two consecutive
recorded votes are one measurement counted twice — a contaminant persisting
four minutes used to satisfy the repeat rule, and its wrong mirror then
steered every bootstrap search into the mirrored half (east_left_hint),
which produced a mirrored candidate that agreed with the same vote. Two
windows are independent only when they do not overlap, i.e. a full buffer
span apart, and on a fast rig the POLE_HISTORY_LEN position history is
shorter than one buffer span (60 frames at 30 s = 30 min; 12 runs at the
2-min cooldown = 24 min), so no two windows inside it are ever disjoint.
Found estimates are therefore kept in a longer vote ledger
(VOTE_LEDGER_LEN); only votes within the link tolerance of the current
dominant position count, so a contaminant's or a pre-move vote at another
position never speaks for this one.

Resolution: an estimate carries the frame size it was measured on
(PoleEstimate.image_width/height). Positions are compared in one frame —
entries from a different resolution are rescaled when the aspect ratio
matches (a resize) and dropped when it does not (a crop) — so a
resize_percent change mid-session neither poisons the clusters nor needs
the history cleared. Unknown (0) resolutions are compared as-is.

Recording and reading are separate operations. The refine worker records
one entry per run (record). A reader with a measurement of its own — the
manual Calibrate Now / guided paths, which have the same buffer and must be
gated by it — uses evaluate(fresh), which judges the fresh estimate
alongside the history without recording it; a reader with none uses
current(). The first cut had a single resolve() that appended on every
call, so two reads of the same buffer manufactured a "repeated" vote from
one physical measurement (Calibrate Now clicked twice inside the cooldown
was enough). The window rule above now makes that impossible even if a
reading were recorded twice.

The link tolerance for "same cluster" is half the pole gate's own tolerance
(POLE_TOL_REF_PX / 2 = 70 px at reference scale, resolution-scaled). A
genuine Polaris estimate is the mean of its 0.65° orbit over the window, so
two windows hours apart differ by at most ~2 × 12 px ≈ 24 px at reference
scale: three times inside the link. Contaminant clusters in the #10 log were
35–1200 px apart; the sub-100 px ones merge, which changes nothing — the
history still has no dominant mode.

Thread-safe: record() runs on the refine worker thread, current() and
evaluate() on the GUI thread (manual calibration paths). All snapshot the
deques under the lock and evaluate the copies.
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

# Found estimates retained for the mirror vote (module doc: independent
# windows are a buffer span apart, further than the position history reaches).
VOTE_LEDGER_LEN = 64

# Two estimates closer than this (at reference resolution) are one mode.
MODE_LINK_REF_PX = 0.5 * POLE_TOL_REF_PX

# A pole must have been found in at least this fraction of retained runs.
MIN_FOUND_FRACTION = 0.5

# The largest cluster must hold at least this fraction of the found runs to
# be trusted. 3-of-4 survives one outlier; the #10 log peaks at ~1/3.
DOMINANT_MODE_FRACTION = 0.75

# Decisive sign votes needed (all agreeing, from non-overlapping windows)
# before east_left is asserted.
MIN_REPEATED_SIGN_VOTES = 2

# Frames whose aspect ratios differ by more than this are a crop, not a
# resize — no single scale factor relates their pixels (as validate_pole).
_ASPECT_TOL = 0.02


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


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def to_frame(e: PoleEstimate, ref_w: int, ref_h: int) -> Optional[PoleEstimate]:
    """`e` with x/y expressed in a (ref_w x ref_h) frame.

    Unchanged when either resolution is unknown or they match; rescaled for
    a resize; None for a crop (aspect mismatch) — the position cannot be
    related to the reference frame at all.
    """
    w, h = int(getattr(e, 'image_width', 0) or 0), int(getattr(e, 'image_height', 0) or 0)
    if not ref_w or not ref_h or w <= 0 or h <= 0 or (w == ref_w and h == ref_h):
        return e
    ar_e, ar_ref = w / h, ref_w / ref_h
    if abs(ar_e - ar_ref) / max(ar_e, ar_ref) > _ASPECT_TOL:
        return None
    s = ref_w / w
    return replace(e, x=e.x * s, y=e.y * s,
                   image_width=int(ref_w), image_height=int(ref_h))


def _in_frame(entries: Sequence[Optional[PoleEstimate]], ref_w: int,
              ref_h: int) -> List[Optional[PoleEstimate]]:
    """Entries in the reference frame; misses pass through, crops are dropped."""
    out: List[Optional[PoleEstimate]] = []
    for e in entries:
        if e is None:
            out.append(None)
            continue
        f = to_frame(e, ref_w, ref_h)
        if f is not None:
            out.append(f)
    return out


# ---------------------------------------------------------------------------
# Mirror vote
# ---------------------------------------------------------------------------

def independent_windows(estimates: Sequence[PoleEstimate]) -> int:
    """Size of the largest set of estimates with pairwise disjoint windows.

    Greedy earliest-end interval scheduling. An estimate with no window
    stamp cannot be shown to overlap anything and counts as its own window:
    in production only find_pole makes estimates, and it always stamps them.
    """
    stamped = []
    unstamped = 0
    for e in estimates:
        a, b = getattr(e, 'window_start', None), getattr(e, 'window_end', None)
        if a is None or b is None:
            unstamped += 1
        else:
            stamped.append((a, b))
    count, last_end = 0, None
    for start, end in sorted(stamped, key=lambda w: w[1]):
        if last_end is None or start >= last_end:
            count += 1
            last_end = end
    return count + unstamped


def consensus_east_left(estimates: Sequence[PoleEstimate]) -> Optional[bool]:
    """Mirror convention only when decisive votes agree, never conflict, and
    MIN_REPEATED_SIGN_VOTES of them come from windows that do not overlap."""
    decisive = [e for e in estimates if e.east_left is not None]
    if len(decisive) < MIN_REPEATED_SIGN_VOTES:
        return None
    if len({bool(e.east_left) for e in decisive}) != 1:
        return None
    if independent_windows(decisive) < MIN_REPEATED_SIGN_VOTES:
        return None
    return bool(decisive[0].east_left)


# ---------------------------------------------------------------------------
# Consensus
# ---------------------------------------------------------------------------

def consensus(
    runs: Sequence[Optional[PoleEstimate]],
    sky_r: Optional[float] = None,
    votes: Optional[Sequence[PoleEstimate]] = None,
    image_width: Optional[int] = None,
    image_height: Optional[int] = None,
) -> Optional[PoleEstimate]:
    """The estimate the gate may use given `runs` (misses as None), or None.

    The estimate under judgement is the most recent found run. Returns a
    copy of it whose east_left is the independent repeated-vote consensus
    (None until it repeats). `votes` is the longer ledger the mirror vote
    draws on (only entries within the link of the judged position count);
    None means the dominant-mode members of `runs` alone. `image_width/
    height` is the frame the comparison is made in; None means the judged
    estimate's own.
    """
    found = [e for e in runs if e is not None]
    if not found:
        return None
    ref_w = int(image_width or found[-1].image_width or 0)
    ref_h = int(image_height or found[-1].image_height or 0)
    runs = _in_frame(runs, ref_w, ref_h)
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
    latest = found[-1]
    pool: Sequence[PoleEstimate] = found
    if votes is not None:
        pool = [v for v in _in_frame(votes, ref_w, ref_h)
                if v is not None and v.east_left is not None
                and np.hypot(v.x - latest.x, v.y - latest.y) <= link]
    return replace(latest, east_left=consensus_east_left(pool))


class PoleHistory:
    """Rolling record of find_pole results with a trust decision per run."""

    def __init__(self, maxlen: int = POLE_HISTORY_LEN,
                 vote_ledger_len: int = VOTE_LEDGER_LEN):
        self._lock = threading.Lock()
        # None entries record runs where no pole was found (misses).
        self._runs: Deque[Optional[PoleEstimate]] = deque(maxlen=maxlen)
        # Every found estimate, for the mirror vote (module doc).
        self._found: Deque[PoleEstimate] = deque(maxlen=vote_ledger_len)
        self._runs_since_trusted = 0

    def record(self, estimate: Optional[PoleEstimate],
               sky_r: Optional[float] = None) -> Optional[PoleEstimate]:
        """Record this run's estimate and return the one the gate may use.

        One call per physical measurement (the refine worker, once per run).
        Returns None when there is nothing to trust: no dominant mode, this
        estimate outside it, or a pole found in fewer than half the recent
        runs. A miss this run does NOT by itself return None — an
        established consensus survives one withheld window (module doc).
        """
        with self._lock:
            self._runs.append(estimate)
            if estimate is not None:
                self._found.append(estimate)
            runs, votes = list(self._runs), list(self._found)
        # A miss is judged against the history like any other run rather
        # than returning None outright. On 2026-09-05 the pole had been found
        # at the same spot in 11 consecutive runs when one window was
        # withheld; that single None switched the gate off for exactly the
        # run in which a basin escape installed a wrong-basin model, and the
        # next run (pole back) rejected its refinement at 311 px. The found
        # fraction still retires a consensus once misses dominate.
        result = consensus(runs, sky_r, votes)
        with self._lock:
            self._runs_since_trusted = (
                0 if result is not None else self._runs_since_trusted + 1)
        return result

    def evaluate(self, fresh: Optional[PoleEstimate],
                 sky_r: Optional[float] = None,
                 image_width: Optional[int] = None,
                 image_height: Optional[int] = None) -> Optional[PoleEstimate]:
        """Judge `fresh` alongside the history without recording anything.

        For a reader that measured the same buffer the worker records from
        (manual calibration): the measurement is used, but never counted
        as a run. A miss (None) is judged as a run like any other — it
        lowers the found fraction but does not erase an established
        consensus, so a manual result is still held to what the field has
        shown. `image_width/height` is the frame the caller compares in
        (the buffer's); it defaults to the fresh estimate's own stamp.
        """
        with self._lock:
            runs = list(self._runs) + [fresh]
            votes = list(self._found) + ([fresh] if fresh is not None else [])
        return consensus(runs, sky_r, votes, image_width, image_height)

    def current(self, sky_r: Optional[float] = None,
                image_width: Optional[int] = None,
                image_height: Optional[int] = None) -> Optional[PoleEstimate]:
        """What the recorded history establishes, without recording anything.

        For readers that have no measurement of their own. The position is
        the most recent found run's (any member of the dominant mode is
        within the link tolerance of the others); the same trust rules as
        record() apply. None when nothing has been recorded or nothing is
        trusted.
        """
        with self._lock:
            runs, votes = list(self._runs), list(self._found)
        if not runs:
            return None
        return consensus(runs, sky_r, votes, image_width, image_height)

    @property
    def runs_since_trusted(self) -> int:
        """Consecutive recorded runs (including the latest) with no trusted
        pole. model_admission ages the pole-corroborated rung on it."""
        with self._lock:
            return self._runs_since_trusted

    def clear(self) -> None:
        with self._lock:
            self._runs.clear()
            self._found.clear()
            self._runs_since_trusted = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._runs)
