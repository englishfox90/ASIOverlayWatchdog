"""Force-exit watchdog tests.

The watchdog exists to guarantee the process actually dies when shutdown wedges
(a hung teardown step leaves a locked exe that fails the next in-place upgrade).
The kill path is verified in a subprocess so it can't take the test runner down;
idempotency is checked in-process with a harmless long timeout.
"""
import subprocess
import sys
import textwrap
import time

import pytest

import services.shutdown_watchdog as wd


@pytest.fixture(autouse=True)
def _reset_armed():
    """Each test starts with the module disarmed (it's a process-global flag)."""
    wd._armed = False
    yield
    wd._armed = False


def test_arm_is_idempotent():
    """Arming twice must not start a second timer or raise."""
    wd.arm_force_exit(1000.0)  # long timeout — never fires during the test
    assert wd._armed is True
    wd.arm_force_exit(1000.0)  # no-op
    assert wd._armed is True


@pytest.mark.skipif(sys.platform != "win32", reason="force-kill path is Windows-specific")
def test_watchdog_kills_hung_process():
    """A process that wedges after arming is force-terminated by the deadline."""
    script = textwrap.dedent(
        """
        import time
        from services.shutdown_watchdog import arm_force_exit
        arm_force_exit(2.0)
        time.sleep(60)          # simulate a wedged teardown
        print("NOT KILLED")     # must never run
        """
    )
    start = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    elapsed = time.monotonic() - start
    assert "NOT KILLED" not in proc.stdout
    # Killed near the 2s deadline, well before the 60s sleep would end.
    assert elapsed < 20
