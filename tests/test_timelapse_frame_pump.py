"""
Tests for services.timelapse_frame_pump.FramePump.

Covers the queue mechanics TimelapseWriter.add_frame relies on to stay
non-blocking on its caller's thread (the GUI thread, via the Qt signal
chain): bounded queue with drop-oldest-on-full, flush()/drain() semantics,
and consumer-error isolation.
"""
import threading
import time

from services.timelapse_frame_pump import FramePump


def test_submit_never_blocks_when_queue_is_full():
    """A slow/stuck consumer must not make submit() block the producer."""
    release = threading.Event()
    started = threading.Event()

    def slow_consume(item):
        started.set()
        release.wait(timeout=2)

    pump = FramePump(slow_consume, maxsize=2)
    pump.submit('first')
    assert started.wait(timeout=1)  # worker is now blocked on the first item

    # Queue holds 2 more; a 4th submit must drop the oldest, not block.
    t0 = time.perf_counter()
    for i in range(4):
        pump.submit(i)
    elapsed = time.perf_counter() - t0

    assert elapsed < 0.5, elapsed
    release.set()
    assert pump.flush(timeout=2)


def test_full_queue_drops_oldest_not_newest():
    """When the queue is full, the OLDEST queued item is dropped so the most
    recent frame always wins — losing an old frame is invisible; losing the
    newest one would make the timelapse look stalled."""
    release = threading.Event()
    started = threading.Event()
    processed = []

    def consume(item):
        if item == 'first':
            started.set()
            release.wait(timeout=2)
        processed.append(item)

    pump = FramePump(consume, maxsize=2)
    pump.submit('first')
    assert started.wait(timeout=1)  # worker is now stuck processing 'first'

    pump.submit('a')
    pump.submit('b')
    pump.submit('c')  # queue was full (a, b) → 'a' must be dropped, 'c' kept

    release.set()
    assert pump.flush(timeout=2)

    assert processed == ['first', 'b', 'c']


def test_flush_waits_for_in_flight_item():
    """flush() must not report done while the worker is still mid-consume."""
    order = []

    def consume(item):
        time.sleep(0.05)
        order.append(item)

    pump = FramePump(consume, maxsize=2)
    pump.submit('x')
    assert pump.flush(timeout=2)
    assert order == ['x']


def test_flush_times_out_on_a_stuck_consumer():
    """flush() must return False (not hang forever) if the worker never
    finishes within the timeout — this is what bounds TimelapseWriter.stop()."""
    stuck = threading.Event()

    def consume(item):
        stuck.wait()  # never set — simulates a wedged ffmpeg write

    pump = FramePump(consume, maxsize=2)
    pump.submit('x')

    t0 = time.perf_counter()
    result = pump.flush(timeout=0.2)
    elapsed = time.perf_counter() - t0

    assert result is False
    assert elapsed < 1.0
    stuck.set()  # let the worker thread exit cleanly


def test_drain_discards_unstarted_items_after_timeout():
    """drain() must give up on QUEUED (not yet started) items once the
    consumer proves too slow, so shutdown is bounded even with a backlog."""
    release = threading.Event()
    started = threading.Event()
    processed = []

    def consume(item):
        if item == 'first':
            started.set()
            release.wait(timeout=2)
        processed.append(item)

    pump = FramePump(consume, maxsize=2)
    pump.submit('first')
    assert started.wait(timeout=1)
    pump.submit('queued')

    pump.drain(timeout=0.2)  # 'first' still running; 'queued' gets discarded
    assert 'queued' not in processed

    release.set()
    assert pump.flush(timeout=2)  # lets the in-flight 'first' finish cleanly


def test_consumer_exception_does_not_kill_the_worker():
    """One bad frame must not stop later frames from being processed."""
    processed = []

    def consume(item):
        if item == 'boom':
            raise ValueError("bad frame")
        processed.append(item)

    pump = FramePump(consume, maxsize=2)
    pump.submit('boom')
    pump.submit('ok')

    assert pump.flush(timeout=2)
    assert processed == ['ok']
