"""Tests for services/meteor/persistence.py — inverted temporal plane filter."""
import os
import sys

import pytest

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services.meteor.detector import MeteorDetection
from services.meteor.persistence import PersistenceFilter


def _det(x1, y1, x2, y2, angle=None) -> MeteorDetection:
    import math
    if angle is None:
        angle = float(math.degrees(math.atan2(y2 - y1, x2 - x1)))
    length = float(math.hypot(x2 - x1, y2 - y1))
    return MeteorDetection(x1=x1, y1=y1, x2=x2, y2=y2, length=length, angle_deg=angle)


# Diagonal streak at ~45°
_DIAG = _det(100, 100, 300, 300)

# Same direction, midpoint advanced ~200px along the track
_DIAG_NEXT = _det(250, 250, 450, 450)

# Crossing streak (different angle)
_CROSS = _det(100, 300, 300, 100)


class TestPersistenceFilter:
    def test_single_frame_candidate_released_next_frame(self):
        pf = PersistenceFilter()
        pf.update([_DIAG], frame_idx=0)
        # Next frame: no match → DIAG released as meteor
        released, _ = pf.update([], frame_idx=1)
        assert len(released) == 1
        assert released[0] is _DIAG

    def test_collinear_advanced_streak_rejected_as_plane(self):
        pf = PersistenceFilter()
        pf.update([_DIAG], frame_idx=0)
        released, plane_count = pf.update([_DIAG_NEXT], frame_idx=1)
        assert released == [], "Collinear+advanced streak should be a plane, not released"
        assert plane_count == 1

    def test_suppression_registered_after_plane_detection(self):
        pf = PersistenceFilter()
        pf.update([_DIAG], frame_idx=0)
        pf.update([_DIAG_NEXT], frame_idx=1)
        assert pf.active_suppressions == 1

    def test_suppressed_trajectory_blocks_future_detections(self):
        pf = PersistenceFilter()
        pf.update([_DIAG], 0)
        pf.update([_DIAG_NEXT], 1)
        # Further detections on the same track should be silently filtered
        released, _ = pf.update([_DIAG_NEXT], 2)
        assert released == [], "Subsequent on-track detection should be suppressed"

    def test_crossing_meteor_not_suppressed(self):
        pf = PersistenceFilter()
        pf.update([_DIAG], 0)
        pf.update([_DIAG_NEXT], 1)
        # Frame 2: crossing streak (different angle) should NOT be suppressed
        pf.update([_CROSS], 2)
        released, _ = pf.update([], 3)
        assert len(released) == 1, "Crossing streak should survive as meteor candidate"

    def test_flush_releases_held_candidates(self):
        pf = PersistenceFilter()
        pf.update([_DIAG], 0)
        released = pf.flush()
        assert len(released) == 1

    def test_flush_after_plane_detection_is_empty(self):
        pf = PersistenceFilter()
        pf.update([_DIAG], 0)
        pf.update([_DIAG_NEXT], 1)
        assert pf.flush() == []

    def test_reset_clears_all_state(self):
        pf = PersistenceFilter()
        pf.update([_DIAG], 0)
        pf.reset()
        assert pf.flush() == []
        assert pf.active_suppressions == 0

    def test_empty_input_releases_held(self):
        pf = PersistenceFilter()
        pf.update([_DIAG], 0)
        released, _ = pf.update([], 1)
        assert len(released) == 1

    def test_multiple_meteors_same_frame(self):
        pf = PersistenceFilter()
        m1 = _det(50, 200, 250, 200)   # horizontal
        m2 = _det(300, 50, 300, 250)   # vertical
        pf.update([m1, m2], 0)
        released, _ = pf.update([], 1)
        assert len(released) == 2, "Both single-frame streaks should be released"


class TestResidueSuppression:
    """A released meteor's streak stays in the max-mean transient map until its
    frame evicts from the stack, so the detector re-finds it every run. Those
    residue re-detections must be swallowed, not re-reported."""

    def test_residue_redetection_not_rereleased(self):
        pf = PersistenceFilter(residue_suppress_frames=6)
        pf.update([_DIAG], frame_idx=0)
        # Frame 1: residue at the SAME position (not advanced) -> meteor released once
        released, planes = pf.update([_DIAG], frame_idx=1)
        assert len(released) == 1
        assert planes == 0
        # Frames 2-5: residue keeps re-detecting -> never released again
        for idx in range(2, 6):
            released, _ = pf.update([_DIAG], frame_idx=idx)
            assert released == [], f"Residue re-released at frame {idx}"

    def test_release_registers_residue_suppression(self):
        pf = PersistenceFilter(residue_suppress_frames=6)
        pf.update([_DIAG], frame_idx=0)
        pf.update([], frame_idx=1)
        assert pf.active_suppressions == 1

    def test_residue_suppression_expires(self):
        pf = PersistenceFilter(residue_suppress_frames=3)
        pf.update([_DIAG], frame_idx=0)
        pf.update([], frame_idx=1)   # released; residue suppression registered
        pf.update([], frame_idx=2)
        pf.update([], frame_idx=3)
        # A NEW meteor on the same line after expiry is detected normally
        # (the TTL-3 suppression is pruned at the start of update 4)
        pf.update([_DIAG], frame_idx=4)
        assert pf.active_suppressions == 0
        released, _ = pf.update([], frame_idx=5)
        assert len(released) == 1

    def test_crossing_meteor_during_residue_suppression_released(self):
        pf = PersistenceFilter(residue_suppress_frames=6)
        pf.update([_DIAG], frame_idx=0)
        pf.update([_DIAG], frame_idx=1)          # release + residue suppression
        pf.update([_CROSS], frame_idx=2)          # different angle -> held
        released, _ = pf.update([], frame_idx=3)
        assert len(released) == 1
        assert released[0] is _CROSS


class TestNoveltyGate:
    """A meteor is a one-frame event. A streak that keeps re-appearing in the
    same place is a static artifact (star-drift residual, fixed feature) and
    must not be reported repeatedly, even after residue suppression expires."""

    def test_persistent_streak_not_rereleased_after_suppression_expiry(self):
        pf = PersistenceFilter(residue_suppress_frames=3)
        pf.update([_DIAG], frame_idx=0)
        released, _ = pf.update([_DIAG], frame_idx=1)   # first (unavoidable) report
        assert len(released) == 1
        # Same streak keeps sitting there, past the 3-frame suppression TTL.
        reports = 0
        for idx in range(2, 8):
            r, _ = pf.update([_DIAG], frame_idx=idx)
            reports += len(r)
        assert reports == 0, "Persistent static streak re-reported as a meteor"

    def test_genuinely_new_streak_after_quiet_line_is_released(self):
        # The novelty memory self-heals: once the line goes quiet, a fresh
        # streak on it is a meteor again.
        pf = PersistenceFilter(residue_suppress_frames=2)
        pf.update([_DIAG], frame_idx=0)
        pf.update([_DIAG], frame_idx=1)   # first report
        pf.update([], frame_idx=2)         # line goes quiet
        pf.update([], frame_idx=3)
        pf.update([_DIAG], frame_idx=4)    # genuinely new appearance -> held
        released, _ = pf.update([], frame_idx=5)
        assert len(released) == 1
