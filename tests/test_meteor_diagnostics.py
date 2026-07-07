"""Tests for services/meteor/diagnostics.py — heartbeat, silence detection,
roof-gate transitions, and the hot-mask coverage warning."""
import os
import sys

import pytest

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services.meteor.diagnostics import MeteorDiagnostics, HOT_MASK_WARN_FRACTION


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float):
        self.t += seconds


@pytest.fixture()
def clock():
    return FakeClock()


@pytest.fixture()
def diag(clock):
    return MeteorDiagnostics(heartbeat_minutes=15.0, now_fn=clock)


def _run(diag, **overrides):
    kwargs = dict(hot_coverage=0.02, sigma=1.4, threshold=6,
                  raw=0, after_length=0, after_profile=0,
                  released=0, planes=0)
    kwargs.update(overrides)
    return diag.detection_run(**kwargs)


class TestHeartbeat:
    def test_no_heartbeat_before_any_frame(self, diag):
        assert diag.maybe_heartbeat(enabled=True) is None

    def test_no_heartbeat_when_disabled(self, diag, clock):
        diag.frame_received()
        clock.advance(3600)
        assert diag.maybe_heartbeat(enabled=False) is None

    def test_no_heartbeat_before_interval(self, diag, clock):
        diag.frame_received()
        _run(diag)
        clock.advance(60)
        assert diag.maybe_heartbeat(enabled=True) is None

    def test_heartbeat_after_interval_summarises_stages(self, diag, clock):
        diag.frame_received()
        _run(diag, raw=4, after_length=3, after_profile=2, released=1, planes=1)
        clock.advance(15 * 60)
        diag.frame_received()   # keep the frame flow alive across the interval
        msg = diag.maybe_heartbeat(enabled=True)
        assert msg is not None
        assert "2 frames" in msg
        assert "4 raw -> 3 length-ok -> 2 profile-ok" in msg
        assert "1 meteor(s) released" in msg
        assert "1 plane track(s) suppressed" in msg

    def test_counters_reset_after_heartbeat(self, diag, clock):
        diag.frame_received()
        _run(diag, raw=4)
        clock.advance(15 * 60)
        diag.frame_received()
        diag.maybe_heartbeat(enabled=True)
        clock.advance(15 * 60)
        diag.frame_received()
        msg = diag.maybe_heartbeat(enabled=True)
        assert "0 raw" in msg, "Stage counters must reset between heartbeats"

    def test_skip_reasons_included(self, diag, clock):
        diag.frame_received()
        diag.detection_skipped("cooldown")
        diag.detection_skipped("cooldown")
        diag.detection_skipped("busy")
        clock.advance(15 * 60)
        diag.frame_received()
        msg = diag.maybe_heartbeat(enabled=True)
        assert "2 cooldown" in msg
        assert "1 busy" in msg


class TestSilenceDetection:
    def test_frames_stopped_logged_once_with_last_time(self, diag, clock):
        diag.frame_received()
        clock.advance(20 * 60)
        msg = diag.maybe_heartbeat(enabled=True)
        assert msg is not None and "frames stopped" in msg
        assert "20 min ago" in msg
        # Only once per silence period
        clock.advance(20 * 60)
        assert diag.maybe_heartbeat(enabled=True) is None

    def test_frames_resumed_after_silence(self, diag, clock):
        diag.frame_received()
        clock.advance(20 * 60)
        diag.maybe_heartbeat(enabled=True)
        msg = diag.frame_received()
        assert msg is not None and "frames resumed" in msg

    def test_no_resume_message_without_prior_silence(self, diag):
        assert diag.frame_received() is None
        assert diag.frame_received() is None


class TestRoofGate:
    def test_transitions_logged_once(self, diag):
        assert diag.roof_gate(False) is None          # open is the start state
        msg = diag.roof_gate(True)
        assert msg is not None and "suspended" in msg
        assert diag.roof_gate(True) is None           # no repeat while closed
        msg = diag.roof_gate(False)
        assert msg is not None and "resumed" in msg

    def test_roof_state_shown_in_heartbeat(self, diag, clock):
        diag.frame_received()
        diag.roof_gate(True)
        clock.advance(15 * 60)
        diag.frame_received()
        msg = diag.maybe_heartbeat(enabled=True)
        assert "roof gate ACTIVE" in msg


class TestHotMaskWarning:
    def test_warns_when_coverage_crosses_threshold(self, diag):
        msg = _run(diag, hot_coverage=HOT_MASK_WARN_FRACTION + 0.4)
        assert msg is not None and "hot mask covers 80%" in msg

    def test_warns_only_on_transition(self, diag):
        _run(diag, hot_coverage=0.9)
        assert _run(diag, hot_coverage=0.9) is None

    def test_recovery_logged(self, diag):
        _run(diag, hot_coverage=0.9)
        msg = _run(diag, hot_coverage=0.05)
        assert msg is not None and "unblocked" in msg

    def test_no_warning_at_normal_coverage(self, diag):
        assert _run(diag, hot_coverage=0.05) is None


class TestFlushAndReset:
    def test_flush_emits_final_summary(self, diag):
        diag.frame_received()
        _run(diag, raw=1)
        msg = diag.flush("capture stopped")
        assert msg is not None and "[capture stopped]" in msg

    def test_flush_silent_when_nothing_counted(self, diag):
        assert diag.flush("capture stopped") is None

    def test_reset_clears_silence_and_roof_state(self, diag, clock):
        diag.frame_received()
        diag.roof_gate(True)
        clock.advance(20 * 60)
        diag.maybe_heartbeat(enabled=True)
        diag.reset()
        assert diag.maybe_heartbeat(enabled=True) is None  # no frame yet
        assert diag.roof_gate(True) is not None            # transitions re-arm
