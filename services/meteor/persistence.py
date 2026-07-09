"""
Persistence filter — temporal plane/satellite discriminator.

Core logic (inverted from MeteorTracker):
  Meteor  → streak in exactly ONE frame, absent from neighbours.
  Plane   → collinear streak that continues (advanced along the same track)
             into the NEXT frame.

Each detection is held for one frame. If the next frame contains a collinear,
spatially-advanced streak along the same trajectory → plane: both are discarded
and a trajectory suppression is registered (so subsequent frames on the same
track are silently rejected for a configurable number of frames).

If no match is found in the next frame → meteor: the held detection is released.

One-frame holdback latency (10–20 s) is accepted — nothing downstream is
real-time and it eliminates the most common false-positive class entirely.
"""
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .detector import MeteorDetection


# ------------------------------------------------------------------ #
#  Internal data structures                                            #
# ------------------------------------------------------------------ #

@dataclass
class _HeldCandidate:
    detection: MeteorDetection
    frame_idx: int


@dataclass
class _TrajectorySuppress:
    """Hesse-normal-form line + tolerance — suppresses a known plane track."""
    angle_deg: float
    a: float           # normal vector components of the line (unit)
    b: float
    c: float           # offset: a*x + b*y + c = 0 passes through the track
    lateral_tol: float
    frames_remaining: int

    def matches(self, det: MeteorDetection, angle_tol_deg: float = 10.0) -> bool:
        d = abs(det.angle_deg - self.angle_deg) % 180
        angle_diff = min(d, 180 - d)
        if angle_diff > angle_tol_deg:
            return False
        mid_x = (det.x1 + det.x2) / 2.0
        mid_y = (det.y1 + det.y2) / 2.0
        return abs(self.a * mid_x + self.b * mid_y + self.c) <= self.lateral_tol


# ------------------------------------------------------------------ #
#  Geometry helpers                                                    #
# ------------------------------------------------------------------ #

def _hesse(det: MeteorDetection) -> Tuple[float, float, float]:
    """Hesse normal form (a, b, c) for the line through det's endpoints."""
    dx = det.x2 - det.x1
    dy = det.y2 - det.y1
    length = math.hypot(dx, dy) or 1.0
    a = dy / length
    b = -dx / length
    c = -(a * det.x1 + b * det.y1)
    return a, b, c


def _is_static_repeat(
    prev: MeteorDetection,
    new: MeteorDetection,
    angle_tol_deg: float,
    lateral_tol_px: float,
    advance_frac: float = 0.1,
) -> bool:
    """
    True when *new* is the same streak as *prev*, essentially unmoved —
    collinear, laterally close, and NOT advanced along the track.

    A meteor is a one-frame event: it is absent the frame before it appears.
    A streak still sitting in the same place a frame later (without advancing,
    which would make it a plane) is a static artifact — a star-drift residual
    or a fixed faint feature — not a meteor. A candidate matching a raw
    detection from the previous frame is therefore not "novel" and must not be
    held as a meteor. (A released meteor's OWN lingering residue is handled
    separately by residue suppression.)
    """
    d = abs(new.angle_deg - prev.angle_deg) % 180
    if min(d, 180 - d) > angle_tol_deg:
        return False
    a, b, c = _hesse(prev)
    mid_x = (new.x1 + new.x2) / 2.0
    mid_y = (new.y1 + new.y2) / 2.0
    if abs(a * mid_x + b * mid_y + c) > lateral_tol_px:
        return False
    prev_mid_x = (prev.x1 + prev.x2) / 2.0
    prev_mid_y = (prev.y1 + prev.y2) / 2.0
    advance = math.hypot(mid_x - prev_mid_x, mid_y - prev_mid_y)
    return advance <= max(prev.length, new.length) * advance_frac


def _is_collinear_and_advanced(
    held: MeteorDetection,
    new: MeteorDetection,
    angle_tol_deg: float,
    lateral_tol_px: float,
) -> bool:
    """
    True when *new* is collinear with *held* (same direction, nearby
    in the perpendicular direction) AND the midpoint has advanced along
    the track — the signature of a plane/satellite crossing from one
    frame to the next.
    """
    d = abs(new.angle_deg - held.angle_deg) % 180
    if min(d, 180 - d) > angle_tol_deg:
        return False

    a, b, c = _hesse(held)
    mid_x = (new.x1 + new.x2) / 2.0
    mid_y = (new.y1 + new.y2) / 2.0
    if abs(a * mid_x + b * mid_y + c) > lateral_tol_px:
        return False

    held_mid_x = (held.x1 + held.x2) / 2.0
    held_mid_y = (held.y1 + held.y2) / 2.0
    advance = math.hypot(mid_x - held_mid_x, mid_y - held_mid_y)
    # Require advance ≥ 10% of the longer streak — distinguishes a re-detection
    # of a static residual from genuine cross-frame motion.
    return advance > max(held.length, new.length) * 0.1


# ------------------------------------------------------------------ #
#  Public API                                                          #
# ------------------------------------------------------------------ #

class PersistenceFilter:
    """
    One-frame holdback filter that discriminates meteors from planes.

    Args:
        angle_tol_deg:   Max angle difference (degrees) for collinearity.
        lateral_tol_px:  Max perpendicular distance (pixels, full-res) for match.
        suppress_frames: How many frames to suppress a confirmed plane trajectory.
        residue_suppress_frames: How many frames to suppress a RELEASED meteor's
            own line. The max−mean transient map keeps a streak visible until
            its frame evicts from the stack, so the same event is re-detected
            for ~stack-depth runs; without this it would be re-reported each time.
    """

    def __init__(
        self,
        angle_tol_deg: float = 10.0,
        lateral_tol_px: float = 50.0,
        suppress_frames: int = 30,
        residue_suppress_frames: int = 8,
    ):
        self._angle_tol = angle_tol_deg
        self._lateral_tol = lateral_tol_px
        self._suppress_frames = suppress_frames
        self._residue_suppress_frames = residue_suppress_frames
        self._held: List[_HeldCandidate] = []
        self._suppressions: List[_TrajectorySuppress] = []
        # Raw candidates from the previous frame — the novelty memory. A streak
        # already present here is not a fresh one-frame event, so it is not held.
        self._prev_candidates: List[MeteorDetection] = []

    def update(
        self,
        candidates: List[MeteorDetection],
        frame_idx: int,
    ) -> Tuple[List[MeteorDetection], int]:
        """
        Feed current-frame candidates.

        Returns:
            (released_meteors, plane_tracks_confirmed)

        *released_meteors*: candidates from the PREVIOUS frame that found no
          match this frame — these are released as meteor detections.
        *plane_tracks_confirmed*: count of new plane tracks registered.
        """
        # Tick down active suppressions
        self._suppressions = [
            _TrajectorySuppress(s.angle_deg, s.a, s.b, s.c,
                                s.lateral_tol, s.frames_remaining - 1)
            for s in self._suppressions if s.frames_remaining > 1
        ]

        # Filter current candidates against active suppressions
        active = [
            d for d in candidates
            if not any(s.matches(d, self._angle_tol) for s in self._suppressions)
        ]

        # Match each held candidate against this frame's active candidates
        matched_held: set = set()
        plane_active: set = set()

        for hi, held in enumerate(self._held):
            for ai, det in enumerate(active):
                if ai in plane_active:
                    continue
                if _is_collinear_and_advanced(
                    held.detection, det, self._angle_tol, self._lateral_tol
                ):
                    matched_held.add(hi)
                    plane_active.add(ai)
                    a, b, c = _hesse(held.detection)
                    self._suppressions.append(_TrajectorySuppress(
                        angle_deg=held.detection.angle_deg,
                        a=a, b=b, c=c,
                        lateral_tol=self._lateral_tol,
                        frames_remaining=self._suppress_frames,
                    ))
                    break

        # Unmatched held candidates → released as meteors, EXCEPT any that lie
        # on a suppressed trajectory (including ones registered this update):
        # leftover duplicate segments of a just-confirmed plane track must not
        # escape as meteors.
        released = [
            self._held[hi].detection
            for hi in range(len(self._held))
            if hi not in matched_held
            and not any(s.matches(self._held[hi].detection, self._angle_tol)
                        for s in self._suppressions)
        ]

        # Suppress each released meteor's own line for ~stack-depth frames:
        # the transient map re-detects the streak until its frame evicts, and
        # those residue re-detections must not become fresh candidates.
        for det in released:
            a, b, c = _hesse(det)
            self._suppressions.append(_TrajectorySuppress(
                angle_deg=det.angle_deg,
                a=a, b=b, c=c,
                lateral_tol=self._lateral_tol,
                frames_remaining=self._residue_suppress_frames,
            ))

        # Current candidates that are NOT plane extensions, NOT residue of a
        # just-released meteor, and NOT already present last frame (novelty
        # gate — a persistent static streak is an artifact, not a meteor) →
        # hold for next frame.
        self._held = [
            _HeldCandidate(det, frame_idx)
            for ai, det in enumerate(active)
            if ai not in plane_active
            and not any(s.matches(det, self._angle_tol)
                        for s in self._suppressions)
            and not any(_is_static_repeat(prev, det, self._angle_tol,
                                          self._lateral_tol)
                        for prev in self._prev_candidates)
        ]

        # Remember this frame's raw candidates (pre-suppression) so a streak
        # that keeps re-appearing never looks "novel" again, even after residue
        # suppression on its line has expired.
        self._prev_candidates = list(candidates)

        return released, len(plane_active)

    def flush(self) -> List[MeteorDetection]:
        """
        Release all held candidates immediately (e.g. on capture stop).

        These arrive as "unverified" since there is no next frame to
        confirm or deny them.
        """
        released = [h.detection for h in self._held]
        self._held.clear()
        return released

    def reset(self) -> None:
        """Discard all state (stack clear, session change)."""
        self._held.clear()
        self._suppressions.clear()
        self._prev_candidates.clear()

    @property
    def active_suppressions(self) -> int:
        return len(self._suppressions)
