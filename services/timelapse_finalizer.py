"""Finalize a completed ffmpeg timelapse session.

Closing the encoder, waiting for it to flush, killing it if it hangs, and then
waiting for the output file to settle on disk can take up to ~70s. This is
pulled out of ``TimelapseWriter`` so it can run on a background thread — a
resolution change or an ``always``-mode midnight rollover must not stall the
frame-delivery loop while ffmpeg drains. Shutdown still runs it synchronously.
"""
import os
import subprocess
import threading
import time

from .logger import app_logger


def finalize_session(proc, *, path, frames, elapsed, on_finished):
    """Close ffmpeg's stdin, let it flush, and notify the listener.

    Blocking: run on a background thread for in-flow finalization, or inline on
    shutdown. A finalizer must never raise into its caller, so every step is
    guarded — the worst case is a killed encoder, never a propagated exception.
    """
    if proc is None:
        return
    try:
        proc.stdin.close()
    except Exception:
        pass

    clean_exit = True
    try:
        # Fragmented MP4 needs no end-of-stream rewrite, so ffmpeg exits soon
        # after stdin closes — it only has to flush the final buffered frames.
        # The generous timeout just absorbs a slow disk on a large session.
        proc.wait(timeout=60)
        mins, secs = divmod(elapsed, 60)
        app_logger.info(
            f"Timelapse: session finalized — {frames} frames  "
            f"{mins}m{secs:02d}s → {os.path.basename(path or '')}"
        )
    except subprocess.TimeoutExpired:
        clean_exit = False
        try:
            proc.kill()
            proc.wait()
        except Exception:
            pass
        app_logger.warning("Timelapse: ffmpeg did not exit cleanly, killed")

    # Wait for the OS to finish flushing the file to disk — on Windows the file
    # may not report a stable size immediately after proc.wait() returns, and the
    # Discord poster reads it right after.
    if clean_exit and path:
        wait_for_stable_file(path)

    if clean_exit and path and frames > 0 and on_finished:
        try:
            on_finished(path, frames, elapsed)
        except Exception as e:
            app_logger.error(f"Timelapse: on_session_finished callback error: {e}")


def wait_for_stable_file(path, *, settle=1.0, attempts=10):
    """Block until ``path``'s size stops changing (or attempts are exhausted)."""
    time.sleep(settle)
    for _ in range(attempts):
        try:
            size = os.path.getsize(path)
            time.sleep(settle)
            if os.path.getsize(path) == size:
                break
        except OSError:
            time.sleep(settle)


def finalize_in_background(proc, *, path, frames, elapsed, on_finished):
    """Run :func:`finalize_session` on a daemon thread so the caller returns
    promptly. Returns the started thread (handy for tests)."""
    thread = threading.Thread(
        target=finalize_session,
        kwargs=dict(proc=proc, path=path, frames=frames, elapsed=elapsed,
                    on_finished=on_finished),
        daemon=True,
        name="timelapse-finalizer",
    )
    thread.start()
    return thread


def reap_process(proc):
    """Kill a dead/zombie ffmpeg and wait briefly for it to be reaped."""
    if proc is None:
        return
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def reap_in_background(proc):
    """Reap a process off-thread so a broken-pipe kill()/wait() never blocks the
    caller's lock (get_status contends on it). Returns the started thread."""
    thread = threading.Thread(
        target=reap_process, args=(proc,), daemon=True, name="timelapse-reaper",
    )
    thread.start()
    return thread
