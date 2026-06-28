"""
Tests for services/ascom_safety.py — the NINA GenericFile Safety Monitor writer.

This file is SAFETY-CRITICAL: a wrong "safe" can damage observatory equipment,
so the bias must be fail-safe (Policy A — "write UNSAFE on uncertainty").
"""
import os

import pytest

import services.ascom_safety as ascom_safety
from services.ascom_safety import ASCOMSafetyWriter, write_ascom_safety_file


@pytest.fixture(autouse=True)
def _reset_module_writer():
    """The convenience function caches a module-global writer; reset it so tests
    don't leak the cached instance into each other."""
    ascom_safety._writer_instance = None
    ascom_safety._writer_config = None
    yield
    ascom_safety._writer_instance = None
    ascom_safety._writer_config = None


def _config(path, **overrides):
    cfg = {
        'enabled': True,
        'file_path': str(path),
        'preamble': 'Roof Status:',
        'open_trigger': 'OPEN',
        'closed_trigger': 'CLOSED',
        'include_confidence': True,
        'include_sky_condition': True,
        'min_confidence': 0.7,
    }
    cfg.update(overrides)
    return cfg


# --- happy paths + preamble -------------------------------------------------

def test_open_happy_path_writes_open_trigger(tmp_path):
    target = tmp_path / "roof.txt"
    writer = ASCOMSafetyWriter(_config(target))
    assert writer.write_status({'roof_status': 'Open', 'roof_confidence': 0.95}) is True

    content = target.read_text(encoding='utf-8')
    assert content.startswith('Roof Status: OPEN')
    assert 'Confidence: 95%' in content


def test_closed_happy_path_writes_closed_trigger(tmp_path):
    target = tmp_path / "roof.txt"
    writer = ASCOMSafetyWriter(_config(target))
    assert writer.write_status({'roof_status': 'Closed', 'roof_confidence': 0.99}) is True

    content = target.read_text(encoding='utf-8')
    assert content.startswith('Roof Status: CLOSED')


def test_custom_preamble_and_triggers(tmp_path):
    target = tmp_path / "roof.txt"
    writer = ASCOMSafetyWriter(_config(
        target, preamble='Safe:', open_trigger='SAFE', closed_trigger='UNSAFE'))
    writer.write_status({'roof_status': 'Open', 'roof_confidence': 0.9})
    assert target.read_text(encoding='utf-8').startswith('Safe: SAFE')


def test_sky_condition_line_included(tmp_path):
    target = tmp_path / "roof.txt"
    writer = ASCOMSafetyWriter(_config(target))
    writer.write_status({
        'roof_status': 'Open', 'roof_confidence': 0.9,
        'sky_condition': 'Clear', 'sky_confidence': 0.8,
    })
    assert 'Sky Condition: Clear (80%)' in target.read_text(encoding='utf-8')


# --- atomic write -----------------------------------------------------------

def test_atomic_write_leaves_no_tmp_on_success(tmp_path):
    target = tmp_path / "roof.txt"
    writer = ASCOMSafetyWriter(_config(target))
    writer.write_status({'roof_status': 'Open', 'roof_confidence': 0.9})
    assert not os.path.exists(str(target) + '.tmp')


def test_atomic_write_cleans_temp_and_preserves_original_on_error(tmp_path, monkeypatch):
    target = tmp_path / "roof.txt"
    target.write_text('ORIGINAL CONTENT\n', encoding='utf-8')

    writer = ASCOMSafetyWriter(_config(target))

    def boom(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(ascom_safety.os, 'replace', boom)

    assert writer.write_status({'roof_status': 'Open', 'roof_confidence': 0.9}) is False
    # Original file untouched, temp cleaned up.
    assert target.read_text(encoding='utf-8') == 'ORIGINAL CONTENT\n'
    assert not os.path.exists(str(target) + '.tmp')


# --- min_confidence gating + boundary --------------------------------------

def test_low_confidence_writes_unsafe(tmp_path):
    target = tmp_path / "roof.txt"
    writer = ASCOMSafetyWriter(_config(target, min_confidence=0.7))
    # Open but under-confident -> Policy A writes CLOSED, not skipped.
    assert writer.write_status({'roof_status': 'Open', 'roof_confidence': 0.5}) is True
    assert target.read_text(encoding='utf-8').startswith('Roof Status: CLOSED')


def test_confidence_at_threshold_writes_open(tmp_path):
    target = tmp_path / "roof.txt"
    writer = ASCOMSafetyWriter(_config(target, min_confidence=0.7))
    # Boundary: confidence == min_confidence is "confident".
    assert writer.write_status({'roof_status': 'Open', 'roof_confidence': 0.7}) is True
    assert target.read_text(encoding='utf-8').startswith('Roof Status: OPEN')


def test_none_confidence_treated_as_below_threshold(tmp_path):
    target = tmp_path / "roof.txt"
    writer = ASCOMSafetyWriter(_config(target))
    # roof_confidence is None -> not confident -> UNSAFE (Policy A).
    assert writer.write_status({'roof_status': 'Open', 'roof_confidence': None}) is True
    assert target.read_text(encoding='utf-8').startswith('Roof Status: CLOSED')


# --- N/A under Policy A -----------------------------------------------------

def test_na_status_writes_unsafe_not_stale_open(tmp_path):
    target = tmp_path / "roof.txt"
    # Pre-existing OPEN file on disk (the dangerous stale-safe scenario).
    target.write_text('Roof Status: OPEN\n', encoding='utf-8')

    writer = ASCOMSafetyWriter(_config(target))
    result = writer.write_status({'roof_status': 'N/A', 'roof_confidence': None})

    assert result is True
    content = target.read_text(encoding='utf-8')
    assert content.startswith('Roof Status: CLOSED')
    assert 'OPEN' not in content.split('\n')[0]


def test_unexpected_status_writes_closed(tmp_path):
    target = tmp_path / "roof.txt"
    writer = ASCOMSafetyWriter(_config(target))
    writer.write_status({'roof_status': 'Partially', 'roof_confidence': 0.99})
    assert target.read_text(encoding='utf-8').startswith('Roof Status: CLOSED')


# --- disabled / unconfigured no-op -----------------------------------------

def test_disabled_config_is_noop(tmp_path):
    target = tmp_path / "roof.txt"
    cfg = _config(target, enabled=False)
    assert write_ascom_safety_file({'roof_status': 'Open', 'roof_confidence': 0.9}, cfg) is False
    assert not target.exists()


def test_unconfigured_path_returns_false(tmp_path):
    writer = ASCOMSafetyWriter(_config(tmp_path / "x", file_path=''))
    assert writer.write_status({'roof_status': 'Open', 'roof_confidence': 0.9}) is False


# --- missing parent dir -----------------------------------------------------

def test_missing_parent_dir_is_created(tmp_path):
    target = tmp_path / "nested" / "deeper" / "roof.txt"
    writer = ASCOMSafetyWriter(_config(target))
    assert writer.write_status({'roof_status': 'Open', 'roof_confidence': 0.9}) is True
    assert target.exists()


def test_parent_dir_creation_failure_returns_false(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "roof.txt"
    writer = ASCOMSafetyWriter(_config(target))

    def boom(*args, **kwargs):
        raise OSError("cannot makedirs")

    monkeypatch.setattr(ascom_safety.os, 'makedirs', boom)
    assert writer.write_status({'roof_status': 'Open', 'roof_confidence': 0.9}) is False


# --- bookkeeping ------------------------------------------------------------

def test_get_last_status_and_time(tmp_path):
    target = tmp_path / "roof.txt"
    writer = ASCOMSafetyWriter(_config(target))
    assert writer.get_last_status() is None
    assert writer.get_last_write_time() is None

    writer.write_status({'roof_status': 'Open', 'roof_confidence': 0.9})
    assert writer.get_last_status() == 'Roof Status: OPEN'
    assert writer.get_last_write_time() is not None


# --- R6: global writer rebuilds when relevant config changes ----------------

def test_global_writer_rebuilds_on_min_confidence_change(tmp_path):
    target = tmp_path / "roof.txt"
    results = {'roof_status': 'Open', 'roof_confidence': 0.6}

    # min_confidence 0.5 -> confident Open -> OPEN
    write_ascom_safety_file(results, _config(target, min_confidence=0.5))
    assert target.read_text(encoding='utf-8').startswith('Roof Status: OPEN')

    # Tighten min_confidence to 0.7 (same file_path). Must rebuild, not reuse
    # the stale instance -> now under-confident -> CLOSED.
    write_ascom_safety_file(results, _config(target, min_confidence=0.7))
    assert target.read_text(encoding='utf-8').startswith('Roof Status: CLOSED')


def test_global_writer_rebuilds_on_trigger_change(tmp_path):
    target = tmp_path / "roof.txt"
    results = {'roof_status': 'Open', 'roof_confidence': 0.9}

    write_ascom_safety_file(results, _config(target))
    assert target.read_text(encoding='utf-8').startswith('Roof Status: OPEN')

    write_ascom_safety_file(results, _config(target, open_trigger='SAFE'))
    assert target.read_text(encoding='utf-8').startswith('Roof Status: SAFE')


# ===========================================================================
# RoofSafetyFSM — the confirmation state machine (Policy A) that gates *when*
# the file is written. Pure-python, no Qt; uses an injected fake writer.
# ===========================================================================

from services.ascom_safety_fsm import RoofSafetyFSM, UNSAFE_RESULT  # noqa: E402

FSM_CFG = {'enabled': True, 'file_path': 'X', 'min_confidence': 0.7,
           'heartbeat_seconds': 0}


class _FakeWriter:
    """Records each write and returns a scripted (or always-True) success."""

    def __init__(self, returns=None):
        self.calls = []
        self._returns = list(returns) if returns is not None else None

    def __call__(self, ml_results, ascom_config):
        self.calls.append(dict(ml_results))
        if self._returns is None:
            return True
        return self._returns.pop(0) if self._returns else True


def _is_safe_write(rec, min_conf=0.7):
    conf = rec.get('roof_confidence')
    return rec.get('roof_status') == 'Open' and conf is not None and conf >= min_conf


_OPEN = {'roof_status': 'Open', 'roof_confidence': 0.95}
_CLOSED = {'roof_status': 'Closed', 'roof_confidence': 0.95}


def _fsm(writer=None, on_failure=None, clock=None):
    return RoofSafetyFSM(writer=writer or _FakeWriter(),
                         on_failure=on_failure,
                         clock=clock or (lambda: 0.0))


# --- Item 1: SAFE is never certified without confirmation -------------------

def test_first_open_frame_does_not_certify_safe():
    w = _FakeWriter()
    fsm = _fsm(w)
    fsm.update(_OPEN, FSM_CFG)
    # Exactly one write — the UNSAFE baseline — and NOT a SAFE/OPEN one.
    assert len(w.calls) == 1
    assert not _is_safe_write(w.calls[0])
    assert fsm._confirmed_safe is False


def test_two_consecutive_opens_certify_safe():
    w = _FakeWriter()
    fsm = _fsm(w)
    fsm.update(_OPEN, FSM_CFG)   # baseline UNSAFE
    fsm.update(_OPEN, FSM_CFG)   # 2nd consecutive confident Open -> SAFE
    assert len(w.calls) == 2
    assert _is_safe_write(w.calls[1])
    assert fsm._confirmed_safe is True


def test_single_open_then_closed_never_writes_safe():
    w = _FakeWriter()
    fsm = _fsm(w)
    fsm.update(_OPEN, FSM_CFG)     # baseline UNSAFE, pending toward safe
    fsm.update(_CLOSED, FSM_CFG)   # noise breaks the run
    assert all(not _is_safe_write(c) for c in w.calls)
    assert fsm._confirmed_safe is False


def test_unsafe_baseline_writes_immediately():
    w = _FakeWriter()
    fsm = _fsm(w)
    fsm.update(_CLOSED, FSM_CFG)
    assert len(w.calls) == 1
    assert not _is_safe_write(w.calls[0])
    assert fsm._confirmed_safe is False


# --- transitions both ways require two consecutive --------------------------

def test_transition_to_unsafe_requires_two_consecutive():
    w = _FakeWriter()
    fsm = _fsm(w)
    fsm.update(_OPEN, FSM_CFG)     # baseline
    fsm.update(_OPEN, FSM_CFG)     # SAFE confirmed (write #2)
    assert fsm._confirmed_safe is True
    fsm.update(_CLOSED, FSM_CFG)   # pending unsafe, no write
    assert len(w.calls) == 2
    fsm.update(_CLOSED, FSM_CFG)   # confirmed unsafe (write #3)
    assert len(w.calls) == 3
    assert fsm._confirmed_safe is False


def test_none_confidence_confirms_unsafe_from_safe():
    w = _FakeWriter()
    fsm = _fsm(w)
    fsm.update(_OPEN, FSM_CFG)
    fsm.update(_OPEN, FSM_CFG)     # SAFE
    fsm.update({'roof_status': 'Open', 'roof_confidence': None}, FSM_CFG)
    fsm.update({'roof_status': 'Open', 'roof_confidence': None}, FSM_CFG)
    assert fsm._confirmed_safe is False


# --- failed write retries until durable -------------------------------------

def test_failed_write_retries_until_durably_written():
    # baseline ok, SAFE-confirm ok, transition-to-unsafe FAILS then succeeds.
    w = _FakeWriter(returns=[True, True, False, True])
    fsm = _fsm(w)
    fsm.update(_OPEN, FSM_CFG)     # baseline UNSAFE ok
    fsm.update(_OPEN, FSM_CFG)     # SAFE ok -> confirmed True
    assert fsm._confirmed_safe is True
    fsm.update(_CLOSED, FSM_CFG)   # pending, no write
    fsm.update(_CLOSED, FSM_CFG)   # confirm -> write attempted, FAILS
    assert len(w.calls) == 3
    assert fsm._confirmed_safe is True            # NOT committed on failure
    fsm.update(_CLOSED, FSM_CFG)   # RE-ATTEMPT -> succeeds
    assert len(w.calls) == 4
    assert fsm._confirmed_safe is False           # committed only after success


# --- Item 3: benign skip must not escalate ----------------------------------

def test_not_configured_does_not_escalate():
    # Real writer + enabled but EMPTY file_path -> write_status returns False for
    # a benign reason. Must NOT fire the "write FAILED" escalation.
    ascom_safety._writer_instance = None
    ascom_safety._writer_config = None
    failures = []
    cfg = {'enabled': True, 'file_path': '', 'min_confidence': 0.7,
           'heartbeat_seconds': 0}
    fsm = RoofSafetyFSM(writer=write_ascom_safety_file,
                        on_failure=lambda: failures.append(1))
    fsm.update(_CLOSED, cfg)
    assert failures == []


def test_genuine_failure_escalates_once():
    failures = []
    w = _FakeWriter(returns=[False, False, False])
    fsm = _fsm(w, on_failure=lambda: failures.append(1))
    fsm.update(_CLOSED, FSM_CFG)   # fails -> escalate
    fsm.update(_CLOSED, FSM_CFG)   # still un-baselined, fails -> deduped
    assert len(failures) == 1


# --- Item 4: heartbeat re-stamps a steady session ---------------------------

def test_heartbeat_restamps_steady_state():
    clock = {'t': 0.0}
    w = _FakeWriter()
    fsm = RoofSafetyFSM(writer=w, clock=lambda: clock['t'])
    cfg = {'enabled': True, 'file_path': 'X', 'min_confidence': 0.7,
           'heartbeat_seconds': 300}

    fsm.update(_OPEN, cfg)         # baseline (t=0)
    fsm.update(_OPEN, cfg)         # SAFE confirmed (t=0)
    n_after_confirm = len(w.calls)

    clock['t'] = 100.0
    fsm.update(_OPEN, cfg)         # steady, under heartbeat -> no extra write
    assert len(w.calls) == n_after_confirm

    clock['t'] = 500.0
    fsm.update(_OPEN, cfg)         # past heartbeat -> re-stamp
    assert len(w.calls) == n_after_confirm + 1
    assert _is_safe_write(w.calls[-1])  # re-stamped the confirmed SAFE state
