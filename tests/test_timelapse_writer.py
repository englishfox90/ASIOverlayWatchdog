"""
Tests for services.timelapse_writer.TimelapseWriter.

Covers:
- _build_ffmpeg_cmd even-dimension handling (libx264 + yuv420p require even
  width AND height — odd dims used to crash ffmpeg on every frame).
- The crash-loop guard: a persistent ffmpeg failure must NOT mint a new video
  file on every captured frame; restarts back off and orphan files are removed.
- The real ffmpeg error is surfaced at error level on an unexpected exit.
"""
import time

import pytest

import services.timelapse_writer as tw_mod
from services.timelapse_writer import TimelapseWriter


# --------------------------------------------------------------------------- #
#  _build_ffmpeg_cmd — even-dimension handling                                 #
# --------------------------------------------------------------------------- #

def _vf(writer, frame_size, max_dim):
    writer._config = {'output_max_dim': max_dim}
    cmd = writer._build_ffmpeg_cmd(frame_size, 'out.mp4')
    return cmd[cmd.index('-vf') + 1] if '-vf' in cmd else None


def test_even_native_no_filter():
    """Already-even frames need no -vf — avoid pointless scaling overhead."""
    assert _vf(TimelapseWriter(), (1920, 1080), 0) is None


def test_odd_native_is_cropped_even():
    """Odd source dims must be forced even or x264/yuv420p aborts."""
    vf = _vf(TimelapseWriter(), (1937, 1097), 0)
    assert vf == 'crop=trunc(iw/2)*2:trunc(ih/2)*2'


def test_downscale_also_forces_even():
    """The aspect-preserving downscale can land on odd dims, so crop follows it."""
    vf = _vf(TimelapseWriter(), (4144, 2822), 1920)
    assert vf == (
        'scale=1920:1920:force_original_aspect_ratio=decrease,'
        'crop=trunc(iw/2)*2:trunc(ih/2)*2'
    )


def test_downscale_skipped_when_smaller_than_max():
    """No downscale and even source → no filter chain at all."""
    assert _vf(TimelapseWriter(), (1280, 720), 1920) is None


# --------------------------------------------------------------------------- #
#  Crash-loop guard fixtures                                                   #
# --------------------------------------------------------------------------- #

class _FakeStdin:
    def write(self, data):
        pass

    def flush(self):
        pass

    def close(self):
        pass


class _FakeProcess:
    """Simulates an ffmpeg that crashes immediately (poll() always returns code)."""

    def __init__(self, output_path, exit_code, stderr_line):
        self._exit_code = exit_code
        self.stdin = _FakeStdin()
        self.stderr = iter([stderr_line.encode()])
        # ffmpeg's +empty_moov writes a header straight away — simulate the
        # orphan file so the orphan-cleanup path can be exercised.
        with open(output_path, 'wb') as fh:
            fh.write(b'\x00')

    def poll(self):
        return self._exit_code

    def wait(self, timeout=None):
        return self._exit_code

    def kill(self):
        pass


class _Clock:
    """Drop-in for datetime that returns a fixed, advanceable 'now'."""
    _now = None

    @classmethod
    def now(cls, tz=None):
        return cls._now


@pytest.fixture
def crash_writer(monkeypatch, temp_dir):
    """A writer wired to an immediately-crashing fake ffmpeg, with a fake clock."""
    from datetime import datetime as real_dt

    # Controllable clock anchored inside an 'always' window.
    class FakeDatetime(real_dt):
        pass

    start = real_dt(2026, 1, 1, 22, 0, 0)
    monkeypatch.setattr(_Clock, '_now', start, raising=False)

    def fake_now(tz=None):
        return _Clock._now
    monkeypatch.setattr(FakeDatetime, 'now', staticmethod(fake_now))
    monkeypatch.setattr(tw_mod, 'datetime', FakeDatetime)

    # Stub ffmpeg discovery + analytics so no real process / network is touched.
    monkeypatch.setattr(tw_mod, 'is_ffmpeg_available', lambda: True)
    monkeypatch.setattr(tw_mod, 'get_ffmpeg_path', lambda: 'ffmpeg')
    import services.posthog_service as ph
    monkeypatch.setattr(ph, 'capture_event', lambda *a, **k: None)

    popen_calls = []

    def fake_popen(cmd, **kwargs):
        output_path = cmd[-1]
        popen_calls.append(output_path)
        return _FakeProcess(output_path, exit_code=3752568763,
                            stderr_line='x264 [error]: height not divisible by 2\n')
    monkeypatch.setattr(tw_mod.subprocess, 'Popen', fake_popen)

    writer = TimelapseWriter()
    writer.configure({'enabled': True, 'window_mode': 'always', 'output_dir': temp_dir})

    return writer, popen_calls, FakeDatetime


def _frame():
    from PIL import Image
    return Image.new('RGB', (640, 480), (10, 10, 10))


# --------------------------------------------------------------------------- #
#  Crash-loop guard behaviour                                                  #
# --------------------------------------------------------------------------- #

def test_persistent_crash_does_not_spawn_video_per_frame(crash_writer):
    """The reported bug: ffmpeg crashing must not mint a file on every frame."""
    writer, popen_calls, _ = crash_writer
    img = _frame()

    for _ in range(20):
        writer.add_frame(img)

    # One start attempt; every subsequent frame is blocked by the backoff.
    assert len(popen_calls) == 1
    assert writer._restart_failures >= 1
    assert writer._restart_blocked_until is not None


def test_backoff_expiry_allows_one_retry(crash_writer):
    """After the backoff window elapses, exactly one new attempt is allowed."""
    from datetime import timedelta
    writer, popen_calls, _ = crash_writer
    img = _frame()

    for _ in range(5):
        writer.add_frame(img)
    assert len(popen_calls) == 1

    # Advance the clock past the first backoff (base = 15s).
    _Clock._now = _Clock._now + timedelta(seconds=writer._RESTART_BACKOFF_BASE + 1)
    for _ in range(5):
        writer.add_frame(img)

    assert len(popen_calls) == 2  # one retry, then blocked again with longer backoff


def test_orphan_file_removed_on_failed_start(crash_writer):
    """A zero-frame crash must not leave timelapse_*.mp4 littering disk."""
    import os
    writer, popen_calls, _ = crash_writer
    img = _frame()

    writer.add_frame(img)           # starts ffmpeg, which writes its orphan header
    created = popen_calls[0]
    assert os.path.exists(created)  # the fake ffmpeg created it

    writer.add_frame(img)           # detects the crash → cleans up the orphan
    assert not os.path.exists(created)


def test_unexpected_exit_logs_ffmpeg_stderr(crash_writer, monkeypatch):
    """The real encoder error must reach the log, not just a numeric exit code."""
    writer, popen_calls, _ = crash_writer

    errors = []
    monkeypatch.setattr(tw_mod.app_logger, 'error', lambda msg: errors.append(msg))

    img = _frame()
    writer.add_frame(img)  # start (spawns stderr drain thread)

    # Give the daemon drain thread a moment to consume the fake stderr line.
    for _ in range(50):
        if writer._stderr_tail:
            break
        time.sleep(0.01)

    writer.add_frame(img)  # detect crash → should log the captured stderr

    assert any('height not divisible by 2' in m for m in errors), errors
