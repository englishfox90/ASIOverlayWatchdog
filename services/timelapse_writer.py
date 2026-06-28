"""
Timelapse video writer for camera capture mode.
Pipes processed frames directly into a long-running ffmpeg subprocess,
producing a standard MP4 with correct duration metadata.
"""
import os
import sys
import subprocess
import threading
from collections import deque
from datetime import datetime, date, timedelta
from typing import Optional, Tuple

from PIL import Image
import numpy as np

from .logger import app_logger
from .ffmpeg_utils import is_ffmpeg_available, get_ffmpeg_path
from .timelapse_finalizer import finalize_session, finalize_in_background, reap_in_background


def _to_local_naive(dt: datetime) -> datetime:
    """Convert a tz-aware datetime to naive local time.

    astral returns tz-aware UTC; the rest of the writer compares against
    datetime.now(), which is naive LOCAL. Stripping tzinfo without converting
    (the old bug) shifted the window by the host's UTC offset — hours wrong off
    the prime meridian. astimezone() with no argument converts to the system's
    local zone first, so the naive result lines up with datetime.now().
    """
    return dt.astimezone().replace(tzinfo=None)


class TimelapseWriter:
    """
    Manages an ongoing daily timelapse session.

    Every frame passed to add_frame() is written — timing is entirely
    driven by the camera capture interval in Capture Settings.
    Frames are piped as raw RGB24 bytes into ffmpeg, which encodes to
    a fragmented MP4 in real-time.
    Session boundaries (day rollover, window open/close) are managed
    internally — callers just call add_frame() on every capture.
    """

    # A session that dies before writing this many frames is treated as a
    # failed *start* (e.g. ffmpeg rejecting the stream) rather than a healthy
    # session interrupted late (USB drop). Failed starts trigger backoff.
    _HEALTHY_FRAME_THRESHOLD = 5
    # Exponential backoff between restart attempts after consecutive failed
    # starts, so a persistent ffmpeg crash can no longer mint one video file
    # per captured frame. Frames received during the cooldown are dropped.
    _RESTART_BACKOFF_BASE = 15      # seconds before the first retry
    _RESTART_BACKOFF_CAP = 300      # seconds (5 min) ceiling

    def __init__(self):
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._shutting_down: bool = False
        self._session_date: Optional[date] = None
        self._session_start: Optional[datetime] = None
        self._frame_size: Optional[Tuple[int, int]] = None  # (width, height)
        self._frame_count: int = 0
        self._session_path: Optional[str] = None
        self._config: dict = {}
        self._last_in_window: Optional[bool] = None   # for transition logging
        self._last_enabled: bool = False               # for configure change logging
        self._stderr_thread: Optional[threading.Thread] = None
        # Last few ffmpeg stderr lines, so an unexpected exit can report the
        # actual encoder error instead of just a numeric exit code.
        self._stderr_tail: deque = deque(maxlen=12)
        # Crash-loop guard state.
        self._restart_failures: int = 0
        self._restart_blocked_until: Optional[datetime] = None
        # Optional callback(path, frame_count, elapsed_seconds) called after
        # each session finalizes. Set by TimelapseController for Discord posts.
        self.on_session_finished = None

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def configure(self, config: dict):
        """Update config dict (call whenever settings change)."""
        enabled = config.get('enabled', False)
        if enabled != self._last_enabled:
            self._last_enabled = enabled
            app_logger.info(f"Timelapse: {'enabled' if enabled else 'disabled'}")
        self._config = config

    def add_frame(self, image: Image.Image) -> bool:
        """
        Attempt to add a frame to the current timelapse session.

        Handles window detection, day rollover, ffmpeg startup and
        resolution changes internally. Returns True if a frame was
        actually written.

        All session-state mutation happens under ``self._lock``; any session
        that needs finalizing (window close, resolution change, midnight
        rollover) is detached under the lock and handed to a background
        finalizer once the lock is released, so the long ffmpeg drain never
        stalls the frame-delivery thread and never races ``stop()``.
        """
        if not self._config.get('enabled', False):
            return False

        now = datetime.now()

        # Cheap gate first: the window check reads only _config, so run it BEFORE
        # the multi-MB RGB convert + serialize. For all of daytime — and during
        # backoff or shutdown — a captured frame must not pay for a conversion it
        # would discard one line later. Detach a running session if the window
        # has just closed.
        pending_finalize = None
        try:
            with self._lock:
                if self._shutting_down:
                    return False
                if not self._is_in_window(now):
                    pending_finalize = self._detach_session_locked()
                    return False
        finally:
            self._finalize_async(pending_finalize)

        # In-window: now pay for the conversion — OFF the lock, it's the heavy bit.
        try:
            frame_size = (image.width, image.height)
            frame_bytes = np.array(image.convert('RGB'), dtype=np.uint8).tobytes()
        except Exception as e:
            app_logger.error(f"Timelapse: frame convert error: {e}")
            return False

        pending_finalize = None
        wrote = False
        try:
            with self._lock:
                # State may have changed while the lock was released for the
                # conversion (e.g. a concurrent stop()).
                if self._shutting_down:
                    return False

                # Detect unexpected ffmpeg exit and decide whether to restart.
                if self._process is not None and self._process.poll() is not None:
                    self._handle_unexpected_exit(now)

                # 'always' mode rolls over at midnight (one video per calendar day).
                # All other modes are window-driven: only start when not already
                # recording — midnight does NOT split an overnight session.
                mode = self._config.get('window_mode', 'sun')
                needs_new_session = (
                    self._process is None or
                    (mode == 'always' and self._session_date != now.date())
                )
                if needs_new_session:
                    # Crash-loop guard: if recent starts failed immediately, wait
                    # out the backoff before trying again instead of minting one
                    # broken video file per captured frame.
                    if self._restart_blocked_until and now < self._restart_blocked_until:
                        return False
                    pending_finalize = self._detach_session_locked()
                    self._start_session(frame_size, now)
                elif frame_size != self._frame_size:
                    app_logger.info(
                        f"Timelapse: resolution changed {self._frame_size} → "
                        f"{frame_size}, restarting session"
                    )
                    pending_finalize = self._detach_session_locked()
                    self._start_session(frame_size, now)

                if self._process is not None and self._process.poll() is None:
                    try:
                        self._process.stdin.write(frame_bytes)
                        self._process.stdin.flush()
                        self._frame_count += 1
                        # Session is proving healthy — clear crash-loop state.
                        if self._restart_failures and self._frame_count >= self._HEALTHY_FRAME_THRESHOLD:
                            self._restart_failures = 0
                            self._restart_blocked_until = None
                        if self._frame_count % 100 == 0:
                            app_logger.debug(f"Timelapse: {self._frame_count} frames recorded")
                        wrote = True
                    except BrokenPipeError:
                        # The pipe broke mid-write. The old code nulled the
                        # process without kill()/wait() and skipped the backoff,
                        # leaking ffmpeg and reopening the one-video-per-frame
                        # crash loop (the d271cc8 regression). Run the SAME guard.
                        app_logger.error("Timelapse: ffmpeg pipe broke during write")
                        self._handle_broken_pipe(now)
        except Exception as e:
            app_logger.error(f"Timelapse: add_frame error: {e}")
        finally:
            self._finalize_async(pending_finalize)

        return wrote

    def _finalize_async(self, spec: Optional[dict]):
        """Hand a detached session to the background finalizer (no-op if None)."""
        if spec is not None:
            finalize_in_background(
                spec['proc'], path=spec['path'], frames=spec['frames'],
                elapsed=spec['elapsed'], on_finished=self.on_session_finished,
            )

    def _detach_session_locked(self) -> Optional[dict]:
        """Detach the live ffmpeg session under the lock for off-thread finalize.

        Must be called with ``self._lock`` held. Clears the process/session
        fields and returns a finalize spec (or None when nothing is recording),
        so the caller can finalize outside the lock without racing ``stop()``.
        """
        proc = self._process
        if proc is None:
            return None
        spec = {
            'proc': proc,
            'path': self._session_path,
            'frames': self._frame_count,
            'elapsed': (
                int((datetime.now() - self._session_start).total_seconds())
                if self._session_start else 0
            ),
        }
        self._process = None
        self._session_date = None
        self._session_start = None
        return spec

    def _handle_unexpected_exit(self, now: datetime):
        """ffmpeg died while we still expected it to be recording.

        Caller holds ``self._lock``. Surfaces the encoder's real error and runs
        the shared crash-loop guard.
        """
        exit_code = self._process.poll()
        self._process = None
        self._apply_exit_guard(now, exit_code=exit_code)

    def _handle_broken_pipe(self, now: datetime):
        """ffmpeg's stdin pipe broke mid-write.

        Caller holds ``self._lock``. Detach the (possibly zombie) process — the
        old path leaked it — and run the cheap crash-loop guard under the lock,
        but hand the blocking kill()/wait() to a background reaper: doing it
        under the lock would stall get_status() (the UI's 5s status poll) for up
        to the reap timeout.
        """
        proc = self._process
        self._process = None
        if proc is not None:
            reap_in_background(proc)
        self._apply_exit_guard(now, exit_code='broken-pipe')

    def _apply_exit_guard(self, now: datetime, *, exit_code):
        """Shared crash-loop guard for a detected exit OR a broken pipe.

        Surfaces the stderr tail, removes an unhealthy orphan output file, and
        applies exponential backoff so a persistent failure can't mint a new
        video on every frame. A late death after a healthy run restarts
        promptly; only immediate failures escalate the backoff. Caller holds
        ``self._lock``.
        """
        died_frames = self._frame_count
        died_path = self._session_path
        stderr_tail = " | ".join(self._stderr_tail)
        detail = f" — ffmpeg said: {stderr_tail}" if stderr_tail else ""
        failed_start = died_frames < self._HEALTHY_FRAME_THRESHOLD

        if failed_start:
            # Remove the orphaned (empty / near-empty) output so a crash loop
            # doesn't leave timelapse_YYYYMMDD_2.mp4, _3, _4 … littering disk.
            # Covers 1–4 frame stubs too, not just the exactly-zero case.
            if died_path and os.path.isfile(died_path):
                try:
                    os.remove(died_path)
                except OSError:
                    pass
            self._restart_failures += 1
            backoff = min(
                self._RESTART_BACKOFF_CAP,
                self._RESTART_BACKOFF_BASE * (2 ** (self._restart_failures - 1)),
            )
            self._restart_blocked_until = now + timedelta(seconds=backoff)
            app_logger.error(
                f"Timelapse: ffmpeg exited on startup (code {exit_code}, "
                f"{died_frames} frames){detail} — retrying in {backoff}s "
                f"(failure #{self._restart_failures})"
            )
        else:
            self._restart_failures = 0
            self._restart_blocked_until = None
            app_logger.error(
                f"Timelapse: ffmpeg exited unexpectedly (code {exit_code}, "
                f"{died_frames} frames){detail} — restarting session"
            )

    def stop(self):
        """Stop any active session gracefully (capture stop OR app shutdown).

        Sets the shutdown flag and detaches the session under the lock, then
        finalizes synchronously — a stop wants to block until ffmpeg has
        flushed the final video. The flag is scoped to the duration of this
        call: the writer is long-lived and reused across capture sessions
        (the controller calls stop() on every capture stop), so it must clear
        the flag before returning or add_frame() would early-return forever and
        no further timelapse would ever record until the app restarts.
        """
        with self._lock:
            self._shutting_down = True
            spec = self._detach_session_locked()
        try:
            if spec is not None:
                finalize_session(
                    spec['proc'], path=spec['path'], frames=spec['frames'],
                    elapsed=spec['elapsed'], on_finished=self.on_session_finished,
                )
        finally:
            with self._lock:
                self._shutting_down = False

    def get_status(self) -> dict:
        """Return current timelapse status for UI display."""
        with self._lock:
            proc = self._process
            recording = proc is not None and proc.poll() is None
            elapsed = 0
            if self._session_start and recording:
                elapsed = int((datetime.now() - self._session_start).total_seconds())
            return {
                'recording': recording,
                'frame_count': self._frame_count,
                'session_path': self._session_path,
                'elapsed_seconds': elapsed,
            }

    # ------------------------------------------------------------------ #
    #  Session management                                                  #
    # ------------------------------------------------------------------ #

    def _start_session(self, frame_size: Tuple[int, int], now: datetime):
        """Start a new ffmpeg session for today.

        Caller holds ``self._lock`` and has already detached any prior session
        via ``_detach_session_locked`` — so ``self._process`` is None here.
        """
        if not is_ffmpeg_available():
            app_logger.warning("Timelapse: ffmpeg not found — cannot start session")
            return

        output_path = self._build_output_path(now)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        cmd = self._build_ffmpeg_cmd(frame_size, output_path)
        crf = self._config.get('video_crf', 23)
        fps = self._config.get('playback_fps', 24)
        preset = self._config.get('video_preset', 'fast')
        app_logger.info(f"Timelapse: starting session → {os.path.basename(output_path)}")
        app_logger.debug(
            f"Timelapse: {frame_size[0]}x{frame_size[1]} @ {fps}fps  CRF={crf}  preset={preset}"
        )

        try:
            # Hide the ffmpeg console window on Windows
            kwargs = {}
            if sys.platform == 'win32':
                kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                **kwargs,
            )
            self._frame_size = frame_size
            self._session_date = now.date()
            self._session_start = now
            self._session_path = output_path
            self._frame_count = 0

            from .posthog_service import capture_event
            _res_labels = {0: 'native', 1920: '1920p', 1440: '1440p', 1280: '1280p', 720: '720p'}
            _quality_labels = {28: 'low', 23: 'medium', 18: 'high', 12: 'maximum'}
            capture_event('timelapse_recording_started', {
                'window_mode': self._config.get('window_mode', 'sun'),
                'playback_fps': fps,
                'output_resolution': _res_labels.get(self._config.get('output_max_dim', 0), 'native'),
                'video_quality': _quality_labels.get(crf, 'medium'),
                'include_overlays': self._config.get('include_overlays', False),
                'frame_width': frame_size[0],
                'frame_height': frame_size[1],
            })

            # Fresh stderr ring buffer for this session — captures the encoder's
            # last words so an unexpected exit can report the real cause.
            self._stderr_tail.clear()
            tail = self._stderr_tail

            # Drain stderr in a background thread so it never blocks ffmpeg.
            # Filter out per-frame progress lines (frame=...) which ffmpeg emits
            # every ~0.5s — over an 11-hour session that's ~80k lines of log bloat.
            proc = self._process
            def _drain_stderr(p):
                try:
                    for line in p.stderr:
                        text = line.decode(errors='replace').rstrip()
                        if text and not text.lstrip('\r ').startswith('frame='):
                            tail.append(text)
                            app_logger.debug(f"Timelapse [ffmpeg]: {text}")
                except Exception:
                    pass
            self._stderr_thread = threading.Thread(target=_drain_stderr, args=(proc,), daemon=True)
            self._stderr_thread.start()

        except FileNotFoundError:
            app_logger.error("Timelapse: ffmpeg executable not found")
            self._process = None
        except Exception as e:
            app_logger.error(f"Timelapse: failed to start ffmpeg: {e}")
            self._process = None

    # ------------------------------------------------------------------ #
    #  Window detection                                                    #
    # ------------------------------------------------------------------ #

    def _is_in_window(self, now: datetime) -> bool:
        """Return True if now falls within the configured recording window."""
        mode = self._config.get('window_mode', 'sun')

        if mode == 'always':
            # No time gate — start capturing from the very next frame received.
            return True

        if mode == 'roof':
            # [Beta] Record only while the ML roof model reports the roof is open.
            # roof_open is injected by TimelapseController on every frame.
            # Defaults to False if ML is disabled or no frame has been processed yet.
            is_open = bool(self._config.get('roof_open', False))
            if is_open != getattr(self, '_last_roof_open', None):
                self._last_roof_open = is_open
                app_logger.info(
                    f"Timelapse [roof mode]: roof {'open — recording' if is_open else 'closed — pausing'}"
                )
            return is_open

        try:
            # Check today's window first
            window_start, window_end = self._get_window_for_day(now.date())
            in_window = window_start <= now <= window_end

            # For overnight windows that cross midnight, also check yesterday's window
            # (e.g. at 02:00 on Mar 12, the Mar 11 window 18:00→06:00 still applies)
            if not in_window:
                yesterday = now.date() - timedelta(days=1)
                window_start, window_end = self._get_window_for_day(yesterday)
                in_window = window_start <= now <= window_end

            if in_window != self._last_in_window:
                self._last_in_window = in_window
                w_str = (f"{window_start.strftime('%H:%M')} → "
                         f"{window_end.strftime('%H:%M')}")
                if in_window:
                    app_logger.info(f"Timelapse [{mode}]: entered recording window ({w_str})")
                else:
                    app_logger.info(f"Timelapse [{mode}]: outside recording window ({w_str})")
            return in_window
        except Exception as e:
            app_logger.debug(f"Timelapse: window check error ({e}), defaulting to False")
            return False

    def _get_window_for_day(self, day: date) -> Tuple[datetime, datetime]:
        """
        Return (window_start, window_end) for the given day.

        For overnight windows (e.g. 18:00 → 06:00) the window_end
        is on the following day.  The current time is tested against
        windows anchored on both today and yesterday so sessions
        started yesterday are still considered active.
        """
        mode = self._config.get('window_mode', 'sun')

        if mode == 'always':
            # Full day: midnight to next midnight
            start = datetime.combine(day, datetime.min.time())
            end = datetime.combine(day + timedelta(days=1), datetime.min.time())
            return start, end

        if mode == 'fixed':
            return self._fixed_window(day)

        # Default: sun-based
        return self._sun_window(day)

    def _fixed_window(self, day: date) -> Tuple[datetime, datetime]:
        """Parse fixed HH:MM start/end into datetimes, handling midnight crossing."""
        def parse_time(s: str, fallback: str) -> datetime:
            try:
                h, m = map(int, s.split(':'))
            except Exception:
                h, m = map(int, fallback.split(':'))
            return datetime.combine(day, datetime.strptime(f"{h}:{m}", "%H:%M").time())

        start = parse_time(self._config.get('fixed_start', '18:00'), '18:00')
        end = parse_time(self._config.get('fixed_end', '06:00'), '06:00')

        # If end is earlier than start, it crosses midnight → add a day
        if end <= start:
            end = end + timedelta(days=1)

        return start, end

    def _sun_window(self, day: date) -> Tuple[datetime, datetime]:
        """Calculate sunset→sunrise window using the astral library."""
        try:
            from astral import LocationInfo
            from astral.sun import sun, time_at_elevation, SunDirection

            lat = self._config.get('sun_latitude')
            lon = self._config.get('sun_longitude')
            if lat is None or lon is None:
                raise ValueError("No coordinates configured for sun mode")

            loc = LocationInfo(latitude=float(lat), longitude=float(lon))
            sun_mode = self._config.get('sun_mode', 'astronomical')
            tomorrow = day + timedelta(days=1)

            if sun_mode == 'sunset_sunrise':
                s_today = sun(loc.observer, date=day)
                s_tomorrow = sun(loc.observer, date=tomorrow)
                window_start = _to_local_naive(s_today['sunset'])
                window_end = _to_local_naive(s_tomorrow['sunrise'])

            elif sun_mode == 'civil':
                s_today = sun(loc.observer, date=day)
                s_tomorrow = sun(loc.observer, date=tomorrow)
                window_start = _to_local_naive(s_today['dusk'])
                window_end = _to_local_naive(s_tomorrow['dawn'])

            elif sun_mode == 'nautical':
                window_start = _to_local_naive(time_at_elevation(
                    loc.observer, -12, date=day,
                    direction=SunDirection.SETTING
                ))
                window_end = _to_local_naive(time_at_elevation(
                    loc.observer, -12, date=tomorrow,
                    direction=SunDirection.RISING
                ))

            else:  # astronomical
                window_start = _to_local_naive(time_at_elevation(
                    loc.observer, -18, date=day,
                    direction=SunDirection.SETTING
                ))
                window_end = _to_local_naive(time_at_elevation(
                    loc.observer, -18, date=tomorrow,
                    direction=SunDirection.RISING
                ))

            return window_start, window_end

        except ImportError:
            app_logger.warning("Timelapse: astral not available, falling back to fixed window")
            return self._fixed_window(day)
        except Exception as e:
            app_logger.warning(f"Timelapse: sun window error ({e}), falling back to fixed window")
            return self._fixed_window(day)

    # ------------------------------------------------------------------ #
    #  ffmpeg helpers                                                      #
    # ------------------------------------------------------------------ #

    def _build_output_path(self, now: datetime) -> str:
        """
        Build output path: {output_dir}/timelapse_YYYYMMDD.mp4

        If a file for that date already exists (e.g. roof closed and reopened),
        appends _2, _3, … to avoid overwriting the previous session's video.
        """
        output_dir = self._config.get('output_dir', '')
        if not output_dir:
            from services.app_config import APP_DATA_FOLDER
            output_dir = os.path.join(
                os.getenv('LOCALAPPDATA', ''), APP_DATA_FOLDER, 'timelapse'
            )
        date_str = now.strftime('%Y%m%d')
        base = os.path.join(output_dir, f'timelapse_{date_str}.mp4')
        if not os.path.exists(base):
            return base
        n = 2
        while True:
            path = os.path.join(output_dir, f'timelapse_{date_str}_{n}.mp4')
            if not os.path.exists(path):
                return path
            n += 1

    def _build_ffmpeg_cmd(self, frame_size: Tuple[int, int], output_path: str) -> list:
        """Build the ffmpeg subprocess command."""
        width, height = frame_size
        crf = self._config.get('video_crf', 23)
        preset = self._config.get('video_preset', 'fast')
        fps = self._config.get('playback_fps', 24)
        max_dim = int(self._config.get('output_max_dim', 0))

        # Force a keyframe every playback-second. Each fragment is closed on a
        # keyframe, so this bounds a fragment to ~1s of video and caps how much
        # trailing footage a hard kill (USB drop, power loss) can lose.
        gop = max(1, int(fps))

        cmd = [
            get_ffmpeg_path(),
            '-f', 'rawvideo',
            '-pixel_format', 'rgb24',
            '-video_size', f'{width}x{height}',
            '-framerate', str(fps),      # each piped frame = 1/fps seconds → correct playback speed
            '-i', 'pipe:0',
            '-c:v', 'libx264',
            '-crf', str(crf),
            '-preset', str(preset),
            '-r', str(fps),
            '-g', str(gop),
            '-pix_fmt', 'yuv420p',
        ]

        vf_filters = []
        # Optional downscale — scale longest side to max_dim, keep aspect ratio
        if max_dim > 0 and (width > max_dim or height > max_dim):
            vf_filters.append(f'scale={max_dim}:{max_dim}:force_original_aspect_ratio=decrease')

        # libx264 + yuv420p require BOTH width and height to be even. A raw source
        # frame can be odd (watch mode), and the aspect-preserving downscale above
        # can also land on an odd dimension. Either makes x264 abort on the first
        # frame — which, combined with per-frame restart, used to spawn a broken
        # video on every captured image. Crop at most 1px per axis to force even.
        if vf_filters or width % 2 or height % 2:
            vf_filters.append('crop=trunc(iw/2)*2:trunc(ih/2)*2')

        if vf_filters:
            cmd += ['-vf', ','.join(vf_filters)]

        cmd += [
            # Fragmented MP4: the header (moov) is written up front (+empty_moov)
            # and the stream is recorded as self-contained fragments flushed at
            # each keyframe (+frag_keyframe). This keeps the file playable even
            # when the session ends abnormally — a camera USB sleep, crash, or
            # power loss leaves a valid video up to the last flushed fragment
            # instead of an unplayable file missing its trailing moov atom.
            # +faststart is intentionally NOT used: it requires a clean end-of-
            # stream rewrite (the exact step that never runs on an abnormal exit),
            # and the moov is already at the front here so progressive playback
            # still works. +default_base_moof improves player compatibility.
            '-movflags', '+frag_keyframe+empty_moov+default_base_moof',
            # Flush each fragment to disk immediately instead of waiting for the
            # ~256KB I/O buffer to fill. Matters most for a dark, well-compressing
            # night sky, where the buffer would otherwise hold minutes of frames
            # that a hard kill (USB sleep, power loss) would lose. Cheap at
            # timelapse frame rates.
            '-flush_packets', '1',
            '-y',
            output_path,
        ]
        return cmd
