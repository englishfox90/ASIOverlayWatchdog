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
        writer.flush()  # frames are processed on the pump's worker thread

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
        writer.flush()
    assert len(popen_calls) == 1

    # Advance the clock past the first backoff (base = 15s).
    _Clock._now = _Clock._now + timedelta(seconds=writer._RESTART_BACKOFF_BASE + 1)
    for _ in range(5):
        writer.add_frame(img)
        writer.flush()

    assert len(popen_calls) == 2  # one retry, then blocked again with longer backoff


def test_orphan_file_removed_on_failed_start(crash_writer):
    """A zero-frame crash must not leave timelapse_*.mp4 littering disk."""
    import os
    writer, popen_calls, _ = crash_writer
    img = _frame()

    writer.add_frame(img)           # starts ffmpeg, which writes its orphan header
    writer.flush()
    created = popen_calls[0]
    assert os.path.exists(created)  # the fake ffmpeg created it

    writer.add_frame(img)           # detects the crash → cleans up the orphan
    writer.flush()
    assert not os.path.exists(created)


def test_unexpected_exit_logs_ffmpeg_stderr(crash_writer, monkeypatch):
    """The real encoder error must reach the log, not just a numeric exit code."""
    writer, popen_calls, _ = crash_writer

    errors = []
    monkeypatch.setattr(tw_mod.app_logger, 'error', lambda msg: errors.append(msg))

    img = _frame()
    writer.add_frame(img)  # start (spawns stderr drain thread)
    writer.flush()

    # Give the daemon drain thread a moment to consume the fake stderr line.
    for _ in range(50):
        if writer._stderr_tail:
            break
        time.sleep(0.01)

    writer.add_frame(img)  # detect crash → should log the captured stderr
    writer.flush()

    assert any('height not divisible by 2' in m for m in errors), errors


# --------------------------------------------------------------------------- #
#  Shared wiring for the hardening tests (T1–T4, T7)                            #
# --------------------------------------------------------------------------- #

def _wire_writer(monkeypatch, temp_dir, popen_factory, start_dt, window_mode='always'):
    """Wire a TimelapseWriter to a fake Popen + fake clock + fast finalize.

    Returns (writer, popen_calls, procs). popen_factory(output_path) builds the
    fake process for each session start; procs collects every one created.
    """
    from datetime import datetime as real_dt

    monkeypatch.setattr(_Clock, '_now', start_dt, raising=False)

    class FakeDatetime(real_dt):
        pass
    monkeypatch.setattr(FakeDatetime, 'now', staticmethod(lambda tz=None: _Clock._now))
    monkeypatch.setattr(tw_mod, 'datetime', FakeDatetime)

    monkeypatch.setattr(tw_mod, 'is_ffmpeg_available', lambda: True)
    monkeypatch.setattr(tw_mod, 'get_ffmpeg_path', lambda: 'ffmpeg')
    import services.posthog_service as ph
    monkeypatch.setattr(ph, 'capture_event', lambda *a, **k: None)
    # The on-disk stable-file poll does real 1s sleeps — neutralise it so the
    # finalizer is fast in tests (we test its threading, not the disk wait).
    import services.timelapse_finalizer as tf
    monkeypatch.setattr(tf, 'wait_for_stable_file', lambda *a, **k: None)

    popen_calls = []
    procs = []

    def fake_popen(cmd, **kwargs):
        output_path = cmd[-1]
        popen_calls.append(output_path)
        proc = popen_factory(output_path)
        procs.append(proc)
        return proc
    monkeypatch.setattr(tw_mod.subprocess, 'Popen', fake_popen)

    writer = TimelapseWriter()
    writer.configure({'enabled': True, 'window_mode': window_mode, 'output_dir': temp_dir})
    return writer, popen_calls, procs


class _HealthyProcess:
    """A fake ffmpeg that stays alive and accepts every frame."""

    def __init__(self, output_path):
        self.stdin = _FakeStdin()
        self.stderr = iter([b''])
        self.killed = False
        with open(output_path, 'wb') as fh:
            fh.write(b'\x00')

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


# --------------------------------------------------------------------------- #
#  T1 — sun window uses local wall-clock, not UTC-with-tzinfo-stripped         #
# --------------------------------------------------------------------------- #

def test_sun_window_converts_utc_to_local_naive(monkeypatch):
    """astral returns tz-aware UTC; the window must be naive LOCAL wall-clock,
    not UTC with tzinfo merely stripped (which shifted the window by the host's
    UTC offset)."""
    from datetime import datetime, date, timezone, timedelta
    import astral.sun as astral_sun

    plus5 = timezone(timedelta(hours=5))
    fake_sunset = datetime(2026, 1, 1, 18, 0, tzinfo=plus5)   # 13:00 UTC
    fake_sunrise = datetime(2026, 1, 2, 6, 0, tzinfo=plus5)   # 01:00 UTC

    def fake_sun(observer, date=None):
        # s_today supplies 'sunset'; s_tomorrow supplies 'sunrise'.
        return {'sunset': fake_sunset, 'sunrise': fake_sunrise}
    monkeypatch.setattr(astral_sun, 'sun', fake_sun)

    writer = TimelapseWriter()
    writer.configure({
        'enabled': True, 'window_mode': 'sun', 'sun_mode': 'sunset_sunrise',
        'sun_latitude': 51.5, 'sun_longitude': 0.0,
    })

    ws, we = writer._sun_window(date(2026, 1, 1))

    assert ws == fake_sunset.astimezone().replace(tzinfo=None)
    assert we == fake_sunrise.astimezone().replace(tzinfo=None)
    # On any host whose local offset isn't +5h, the buggy .replace(tzinfo=None)
    # (→ 18:00 naive) differs from the correct local instant.
    if datetime.now().astimezone().utcoffset() != timedelta(hours=5):
        assert ws != fake_sunset.replace(tzinfo=None)


# --------------------------------------------------------------------------- #
#  T2 — BrokenPipe reaps ffmpeg + runs the crash-loop guard                     #
# --------------------------------------------------------------------------- #

class _BrokenPipeStdin:
    def write(self, data):
        raise BrokenPipeError("pipe closed")

    def flush(self):
        pass

    def close(self):
        pass


class _BrokenPipeProcess:
    """Appears alive (poll None) but every stdin.write breaks the pipe."""

    def __init__(self, output_path):
        self.stdin = _BrokenPipeStdin()
        self.stderr = iter([b'broken\n'])
        self.killed = False
        with open(output_path, 'wb') as fh:
            fh.write(b'\x00')

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


def test_broken_pipe_reaps_and_applies_backoff(monkeypatch, temp_dir):
    """A persistent broken pipe must reap ffmpeg and back off — not leak a
    process and mint one broken video per frame (the d271cc8 regression)."""
    from datetime import datetime
    writer, popen_calls, procs = _wire_writer(
        monkeypatch, temp_dir, _BrokenPipeProcess, datetime(2026, 1, 1, 22, 0, 0))
    img = _frame()

    for _ in range(20):
        writer.add_frame(img)
        writer.flush()

    assert len(popen_calls) == 1            # exactly one start, then backoff
    # The reap now runs off the lock on a background thread — poll for it.
    for _ in range(100):
        if procs[0].killed:
            break
        time.sleep(0.01)
    assert procs[0].killed is True          # the leaked process was reaped
    assert writer._restart_failures >= 1
    assert writer._restart_blocked_until is not None
    assert writer._process is None


# --------------------------------------------------------------------------- #
#  T3 — stop() races add_frame safely                                          #
# --------------------------------------------------------------------------- #

def test_stop_races_add_frame(monkeypatch, temp_dir):
    """stop() concurrent with add_frame must not corrupt state: no crash, a
    self-consistent final process, and a bounded Popen count (no per-frame
    storm). Reusability after stop is covered separately."""
    import threading
    from datetime import datetime
    writer, popen_calls, procs = _wire_writer(
        monkeypatch, temp_dir, _HealthyProcess, datetime(2026, 1, 1, 22, 0, 0))
    img = _frame()

    errors = []
    stop_evt = threading.Event()

    def feeder():
        while not stop_evt.is_set():
            try:
                writer.add_frame(img)
            except Exception as e:  # pragma: no cover
                errors.append(e)

    t = threading.Thread(target=feeder)
    t.start()
    time.sleep(0.05)
    writer.stop()
    stop_evt.set()
    t.join(timeout=2)
    # Quiesce the pump: frames fed after stop() returned (the flag is scoped)
    # are still being processed asynchronously and could start a session while
    # the temp_dir fixture is tearing down.
    writer.flush()

    assert not errors, errors
    # The scoped shutdown flag means the writer is reusable, so a final live
    # session is allowed — but it must be self-consistent, never a torn handle.
    if writer._process is not None:
        assert writer._process.poll() is None
    assert len(popen_calls) <= 3            # no per-frame Popen storm


def test_writer_is_reusable_after_stop(monkeypatch, temp_dir):
    """#1 regression — the controller calls stop() on EVERY capture stop, and
    configure() runs every frame. stop() must scope _shutting_down to its own
    duration, or the writer stays permanently dead after the first stop."""
    from datetime import datetime
    writer, popen_calls, procs = _wire_writer(
        monkeypatch, temp_dir, _HealthyProcess, datetime(2026, 1, 1, 22, 0, 0))
    img = _frame()

    assert writer.add_frame(img) is True       # session 1 accepted for processing
    writer.flush()
    assert len(popen_calls) == 1

    writer.stop()
    assert writer._shutting_down is False      # flag cleared, writer reusable

    # Fresh capture session — must record again, not be silently dead.
    writer.configure({'enabled': True, 'window_mode': 'always', 'output_dir': temp_dir})
    assert writer.add_frame(img) is True
    writer.flush()
    assert len(popen_calls) == 2


def test_out_of_window_skips_rgb_conversion(monkeypatch, temp_dir):
    """#2 efficiency — an out-of-window (daytime) frame must NOT pay for the
    multi-MB RGB convert+serialize it would only discard."""
    from datetime import datetime
    writer, popen_calls, procs = _wire_writer(
        monkeypatch, temp_dir, _HealthyProcess, datetime(2026, 1, 1, 12, 0, 0),
        window_mode='roof')   # roof_open defaults False → never in window

    converted = []

    class _SpyImage:
        width = 640
        height = 480

        def convert(self, mode):
            converted.append(mode)
            raise AssertionError("convert must not run out-of-window")

    assert writer.add_frame(_SpyImage()) is False
    assert converted == []                     # conversion skipped entirely
    assert popen_calls == []                    # no session started


def test_add_frame_does_not_block_on_a_held_lock(monkeypatch, temp_dir):
    """GUI-thread safety: if the pump worker is wedged inside self._lock (a
    blocking write to a hung ffmpeg), add_frame must drop the frame after a
    bounded wait instead of parking the caller on lock acquisition —
    otherwise the original event-loop hang comes back one step removed."""
    from datetime import datetime
    writer, popen_calls, procs = _wire_writer(
        monkeypatch, temp_dir, _HealthyProcess, datetime(2026, 1, 1, 22, 0, 0))
    img = _frame()

    writer._lock.acquire()   # simulate the worker wedged inside the lock
    try:
        t0 = time.perf_counter()
        result = writer.add_frame(img)
        elapsed = time.perf_counter() - t0
    finally:
        writer._lock.release()

    assert result is False
    assert elapsed < 1.0, elapsed
    assert popen_calls == []                   # frame dropped, nothing enqueued


def test_backoff_window_skips_rgb_conversion(crash_writer):
    """Mirrors test_out_of_window_skips_rgb_conversion for the OTHER cheap
    gate: during crash-loop backoff, add_frame must reject BEFORE the image
    ever reaches the pump — not just before the worker converts it."""
    writer, popen_calls, _ = crash_writer

    writer.add_frame(_frame())   # starts ffmpeg, which crashes immediately
    writer.flush()
    writer.add_frame(_frame())   # next frame detects the crash → enters backoff
    writer.flush()
    assert writer._restart_blocked_until is not None   # now in backoff

    converted = []

    class _SpyImage:
        width = 640
        height = 480

        def convert(self, mode):
            converted.append(mode)
            raise AssertionError("convert must not run during backoff")

    assert writer.add_frame(_SpyImage()) is False
    writer.flush()
    assert converted == []                # conversion skipped entirely
    assert len(popen_calls) == 1          # no new start attempted during backoff


def test_missing_ffmpeg_does_not_reprobe_within_cooldown(monkeypatch, temp_dir):
    """#3 efficiency — with ffmpeg absent, every in-window frame used to
    re-probe (shutil.which + a winget glob + a subprocess spawn) and log a
    WARNING every single frame. The cooldown must collapse both to one probe
    and one warning per window, then allow exactly one more once it elapses."""
    from datetime import datetime, timedelta

    monkeypatch.setattr(_Clock, '_now', datetime(2026, 1, 1, 22, 0, 0), raising=False)

    class FakeDatetime(datetime):
        pass
    monkeypatch.setattr(FakeDatetime, 'now', staticmethod(lambda tz=None: _Clock._now))
    monkeypatch.setattr(tw_mod, 'datetime', FakeDatetime)

    probe_calls = []

    def fake_probe():
        probe_calls.append(1)
        return False
    monkeypatch.setattr(tw_mod, 'is_ffmpeg_available', fake_probe)

    warnings = []
    monkeypatch.setattr(tw_mod.app_logger, 'warning', lambda msg: warnings.append(msg))

    writer = TimelapseWriter()
    writer.configure({'enabled': True, 'window_mode': 'always', 'output_dir': temp_dir})
    img = _frame()

    for _ in range(5):
        writer.add_frame(img)
        writer.flush()

    assert len(probe_calls) == 1
    assert len(warnings) == 1

    # Advance past the cooldown — exactly one more probe/warning is allowed.
    _Clock._now = _Clock._now + timedelta(seconds=writer._FFMPEG_PROBE_COOLDOWN + 1)
    writer.add_frame(img)
    writer.flush()

    assert len(probe_calls) == 2
    assert len(warnings) == 2


# --------------------------------------------------------------------------- #
#  T4 — finalization runs off the frame-delivery thread                        #
# --------------------------------------------------------------------------- #

class _SlowWaitProcess:
    """Alive process whose wait() sleeps — to prove finalize runs off-thread."""

    def __init__(self, output_path):
        self.stdin = _FakeStdin()
        self.stderr = iter([b''])
        self.wait_thread = None
        with open(output_path, 'wb') as fh:
            fh.write(b'\x00')

    def poll(self):
        return None

    def wait(self, timeout=None):
        import threading
        self.wait_thread = threading.get_ident()
        time.sleep(0.5)
        return 0

    def kill(self):
        pass


def test_resolution_change_finalizes_off_thread(monkeypatch, temp_dir):
    """A resolution change must not block the frame thread on ffmpeg's drain."""
    import threading
    from datetime import datetime
    from PIL import Image
    writer, popen_calls, procs = _wire_writer(
        monkeypatch, temp_dir, _SlowWaitProcess, datetime(2026, 1, 1, 22, 0, 0))

    small = Image.new('RGB', (640, 480), (10, 10, 10))
    big = Image.new('RGB', (800, 600), (10, 10, 10))

    writer.add_frame(small)                 # start session #1
    writer.flush()
    assert len(procs) == 1

    t0 = time.perf_counter()
    writer.add_frame(big)                    # resolution change → finalize #1 off-thread
    writer.flush()                           # wait for the pump worker's detach+restart
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.3, elapsed            # pump worker did NOT block on the 0.5s wait
    assert len(procs) == 2                   # new session started promptly

    time.sleep(0.7)                          # let the background finalizer run
    assert procs[0].wait_thread is not None
    assert procs[0].wait_thread != threading.get_ident()


# --------------------------------------------------------------------------- #
#  T7 — orphan output removed for a 1–4 frame stub, not just exactly-0          #
# --------------------------------------------------------------------------- #

class _CountingStdin:
    def __init__(self, proc):
        self.proc = proc

    def write(self, data):
        self.proc._writes += 1

    def flush(self):
        pass

    def close(self):
        pass


class _DiesAfterNProcess:
    """Writes n frames then reports exit — an early-death stub, not 0 frames."""

    def __init__(self, output_path, n=3):
        self._writes = 0
        self._n = n
        self.stdin = _CountingStdin(self)
        self.stderr = iter([b'x264 [error]: boom\n'])
        with open(output_path, 'wb') as fh:
            fh.write(b'\x00')

    def poll(self):
        return None if self._writes < self._n else 1

    def wait(self, timeout=None):
        return 1

    def kill(self):
        pass


def test_orphan_removed_for_short_stub(monkeypatch, temp_dir):
    """A 3-frame stub (below the healthy threshold) must be cleaned up and
    counted as a failed start."""
    import os
    from datetime import datetime
    writer, popen_calls, procs = _wire_writer(
        monkeypatch, temp_dir, lambda p: _DiesAfterNProcess(p, n=3),
        datetime(2026, 1, 1, 22, 0, 0))
    img = _frame()

    for _ in range(3):
        writer.add_frame(img)               # 3 frames written
        writer.flush()
    created = popen_calls[0]
    assert os.path.exists(created)

    writer.add_frame(img)                    # poll() now reports exit → cleanup
    writer.flush()
    assert not os.path.exists(created)
    assert writer._restart_failures == 1
