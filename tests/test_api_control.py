"""Tests for services/api_control.py — capture-control command logic (pure)."""
import pytest

from services import api_control as ac
from services import api_status


def snap(**kwargs):
    """A capture snapshot in the exact shape api_status produces."""
    return api_status.build_capture_snapshot(**kwargs)


RUNNING = snap(mode="camera", enabled=True, running=True, state="capturing")
WAITING = snap(mode="camera", enabled=True, running=True, state="waiting")
GATED = snap(mode="camera", enabled=True, running=False, state="outside_window")
STOPPED = snap()
ERRORED = snap(mode="camera", enabled=True, running=False, state="error",
               last_error="camera unplugged")


# --- idempotency ----------------------------------------------------------

@pytest.mark.parametrize("snapshot", [RUNNING, WAITING, GATED])
def test_start_is_a_noop_when_already_on(snapshot):
    assert ac.is_at_target(snapshot, ac.COMMAND_START) is True


def test_start_is_not_satisfied_when_stopped():
    assert ac.is_at_target(STOPPED, ac.COMMAND_START) is False


def test_stop_is_a_noop_when_already_stopped():
    assert ac.is_at_target(STOPPED, ac.COMMAND_STOP) is True


def test_stop_is_not_satisfied_while_running():
    assert ac.is_at_target(RUNNING, ac.COMMAND_STOP) is False


def test_empty_snapshot_reads_as_stopped():
    assert ac.snapshot_state({}) == "stopped"
    assert ac.is_at_target(None, ac.COMMAND_STOP) is True
    assert ac.is_at_target(None, ac.COMMAND_START) is False


def test_unknown_command_is_never_at_target():
    assert ac.is_at_target(RUNNING, "restart") is False


def test_scheduled_window_counts_as_started():
    """An enabled run waiting for dusk HAS started — don't block the sequence."""
    assert ac.is_at_target(GATED, ac.COMMAND_START) is True


# --- failure detection ----------------------------------------------------

def test_error_state_is_a_start_failure():
    assert ac.is_failed(ERRORED, ac.COMMAND_START) is True


def test_unrecoverable_recovery_is_a_start_failure():
    s = snap(enabled=True, state="recovering",
             recovery={"in_progress": False, "attempts": 5, "unrecoverable": True})
    assert ac.is_failed(s, ac.COMMAND_START) is True


def test_error_state_does_not_block_a_stop():
    assert ac.is_failed(ERRORED, ac.COMMAND_STOP) is False


# --- body validation ------------------------------------------------------

@pytest.mark.parametrize("body", [None, b"", "", "   ", b"{}", "{}"])
def test_empty_body_yields_defaults(body):
    params, error = ac.parse_request(body)
    assert error is None
    assert params == {"wait": True, "timeout": ac.TIMEOUT_DEFAULT}


def test_explicit_params_are_honoured():
    params, error = ac.parse_request(b'{"wait": false, "timeout": 5}')
    assert error is None
    assert params["wait"] is False
    assert params["timeout"] == 5.0


def test_malformed_json_is_rejected():
    params, error = ac.parse_request(b"{not json")
    assert params is None
    assert error[0] == 400


def test_non_object_body_is_rejected():
    assert ac.parse_request(b"[1, 2, 3]")[1][0] == 400
    assert ac.parse_request(b'"start"')[1][0] == 400


def test_non_utf8_body_is_rejected():
    assert ac.parse_request(b"\xff\xfe\x00")[1][0] == 400


def test_oversized_body_is_rejected():
    assert ac.parse_request(b"x" * (ac.MAX_BODY_BYTES + 1))[1][0] == 413


@pytest.mark.parametrize("body", [b'{"wait": "yes"}', b'{"wait": 1}'])
def test_non_boolean_wait_is_rejected(body):
    assert ac.parse_request(body)[1][0] == 400


@pytest.mark.parametrize("body", [
    b'{"timeout": 0}', b'{"timeout": -5}', b'{"timeout": 9999}',
    b'{"timeout": "30"}', b'{"timeout": true}',
])
def test_out_of_range_or_wrong_type_timeout_is_rejected(body):
    assert ac.parse_request(body)[1][0] == 400


# --- wait semantics -------------------------------------------------------

class _FakeClock:
    """Injected monotonic + sleep so timeouts are tested without elapsed time."""

    def __init__(self):
        self.t = 0.0

    def monotonic(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def test_wait_returns_immediately_when_already_at_target():
    clock = _FakeClock()
    snapshot, outcome = ac.wait_for_target(
        ac.COMMAND_START, lambda: RUNNING,
        timeout=30, monotonic=clock.monotonic, sleep=clock.sleep,
    )
    assert outcome == "reached"
    assert clock.t == 0.0  # never slept


def test_wait_reaches_target_after_a_few_polls():
    clock = _FakeClock()
    reads = [STOPPED, STOPPED, RUNNING]

    def read():
        return reads.pop(0) if reads else RUNNING

    snapshot, outcome = ac.wait_for_target(
        ac.COMMAND_START, read,
        timeout=30, monotonic=clock.monotonic, sleep=clock.sleep,
    )
    assert outcome == "reached"
    assert snapshot is RUNNING


def test_wait_times_out_when_state_never_changes():
    clock = _FakeClock()
    snapshot, outcome = ac.wait_for_target(
        ac.COMMAND_START, lambda: STOPPED,
        timeout=2, monotonic=clock.monotonic, sleep=clock.sleep,
    )
    assert outcome == "timeout"
    assert clock.t >= 2


def test_wait_aborts_early_on_capture_failure():
    clock = _FakeClock()
    snapshot, outcome = ac.wait_for_target(
        ac.COMMAND_START, lambda: ERRORED,
        timeout=300, monotonic=clock.monotonic, sleep=clock.sleep,
    )
    assert outcome == "failed"
    assert clock.t == 0.0  # did not burn the full timeout


def test_wait_for_stop_reaches_target():
    clock = _FakeClock()
    reads = [RUNNING, STOPPED]

    def read():
        return reads.pop(0) if reads else STOPPED

    _, outcome = ac.wait_for_target(
        ac.COMMAND_STOP, read,
        timeout=30, monotonic=clock.monotonic, sleep=clock.sleep,
    )
    assert outcome == "reached"


# --- result shaping -------------------------------------------------------

def test_result_for_outcome_maps_per_command():
    assert ac.result_for_outcome(ac.COMMAND_START, "reached") == ac.RESULT_STARTED
    assert ac.result_for_outcome(ac.COMMAND_STOP, "reached") == ac.RESULT_STOPPED
    assert ac.result_for_outcome(ac.COMMAND_START, "timeout") == ac.RESULT_TIMEOUT
    assert ac.result_for_outcome(ac.COMMAND_START, "failed") == ac.RESULT_FAILED


def test_build_result_shape_matches_documented_fields():
    body = ac.build_result(ac.COMMAND_START, RUNNING,
                           result=ac.RESULT_STARTED, issued=True,
                           waited=True, wait_seconds=1.234)
    documented = {name for name, _type, _desc in ac.CONTROL_RESULT_FIELDS}
    assert set(body) == documented
    assert body["state"] == "capturing"
    assert body["running"] is True
    assert body["wait_seconds"] == 1.23


def test_noop_results_carry_changed_false():
    body = ac.build_result(ac.COMMAND_START, RUNNING,
                           result=ac.RESULT_ALREADY_RUNNING, issued=False)
    assert body["changed"] is False
    assert "already running" in body["message"].lower()


@pytest.mark.parametrize("result,status", [
    (ac.RESULT_STARTED, 200),
    (ac.RESULT_STOPPED, 200),
    (ac.RESULT_ALREADY_RUNNING, 200),
    (ac.RESULT_ALREADY_STOPPED, 200),
    (ac.RESULT_PENDING, 200),
    (ac.RESULT_TIMEOUT, 504),
    (ac.RESULT_FAILED, 500),
])
def test_idempotent_outcomes_are_200(result, status):
    assert ac.http_status_for_result(result) == status


# --- catalog integrity (docs cannot drift) --------------------------------

def test_control_routes_cover_both_commands():
    commands = {r["command"] for r in ac.CONTROL_ROUTES if r["command"]}
    assert commands == set(ac.COMMANDS)


def test_control_routes_are_well_formed():
    for route in ac.CONTROL_ROUTES:
        assert route["path"].startswith("/capture")
        assert route["method"] in ("get", "post")
        assert route["summary"] and route["description"]


# --- OpenAPI integration (0d) ---------------------------------------------

def test_openapi_omits_control_routes_when_disabled():
    from services import api_docs
    spec = api_docs.build_openapi_spec()
    assert not [p for p in spec["paths"] if p.startswith("/capture")]
    assert "bearerAuth" not in spec["components"].get("securitySchemes", {})


def test_openapi_documents_every_control_route_when_enabled():
    from services import api_docs
    spec = api_docs.build_openapi_spec(control_path="/capture")
    for route in ac.CONTROL_ROUTES:
        assert route["path"] in spec["paths"], route["path"]
        assert route["method"] in spec["paths"][route["path"]]
    assert "bearerAuth" in spec["components"]["securitySchemes"]


def test_openapi_control_result_schema_matches_build_result():
    from services import api_docs
    spec = api_docs.build_openapi_spec(control_path="/capture")
    documented = set(spec["components"]["schemas"]["ControlResult"]["properties"])
    actual = set(ac.build_result(ac.COMMAND_START, RUNNING,
                                 result=ac.RESULT_STARTED, issued=True))
    assert documented == actual


def test_openapi_control_routes_all_require_the_token():
    from services import api_docs
    spec = api_docs.build_openapi_spec(control_path="/capture")
    for route in ac.CONTROL_ROUTES:
        op = spec["paths"][route["path"]][route["method"]]
        assert op["security"] == [{"bearerAuth": []}]


def test_docs_html_renders_with_control_routes():
    from services import api_docs
    spec = api_docs.build_openapi_spec(control_path="/capture")
    html = api_docs.render_docs_page(spec) if hasattr(api_docs, "render_docs_page") \
        else api_docs.render_docs_html(spec)
    assert "/capture/start" in html


# --- review follow-ups ----------------------------------------------------

@pytest.mark.parametrize("result,changed", [
    (ac.RESULT_STARTED, True),
    (ac.RESULT_STOPPED, True),
    (ac.RESULT_ALREADY_RUNNING, False),
    (ac.RESULT_ALREADY_STOPPED, False),
    (ac.RESULT_PENDING, False),
    (ac.RESULT_TIMEOUT, False),
    (ac.RESULT_FAILED, False),
])
def test_changed_is_true_only_when_state_actually_moved(result, changed):
    """A timeout or a failure changed nothing — saying otherwise misleads a client."""
    body = ac.build_result(ac.COMMAND_START, RUNNING, result=result, issued=True)
    assert body["changed"] is changed


def test_issued_distinguishes_a_noop_from_a_real_command():
    noop = ac.build_result(ac.COMMAND_START, RUNNING,
                           result=ac.RESULT_ALREADY_RUNNING, issued=False)
    pending = ac.build_result(ac.COMMAND_START, STOPPED,
                              result=ac.RESULT_PENDING, issued=True)
    assert noop["issued"] is False and noop["changed"] is False
    assert pending["issued"] is True and pending["changed"] is False


def test_stale_error_does_not_fail_a_fresh_start():
    """A fault from an earlier session must not fail a start before it is processed."""
    stale = snap(enabled=False, running=False, state="stopped",
                 last_error="camera unplugged an hour ago", last_error_epoch=1000.0)
    assert ac.is_failed(stale, ac.COMMAND_START, baseline_error_epoch=1000.0) is False


def test_new_error_during_start_is_a_failure():
    """The GUI start path can fail without ever reaching state='error'."""
    after = snap(enabled=False, running=False, state="stopped",
                 last_error="could not open camera", last_error_epoch=2000.0)
    assert ac.is_failed(after, ac.COMMAND_START, baseline_error_epoch=None) is True


def test_the_same_fault_reported_again_is_still_a_failure():
    """The bug this rework exists for.

    Retrying a disconnected camera produces a byte-identical message, so the
    old text comparison read the repeat as stale and burned the full timeout
    before returning 504 instead of failing immediately.
    """
    ERR = "No ZWO cameras detected. Check USB connections."
    before = 1000.0
    after = snap(enabled=False, running=False, state="stopped",
                 last_error=ERR, last_error_epoch=1500.0)
    assert ac.is_failed(after, ac.COMMAND_START, baseline_error_epoch=before) is True


def test_an_unstamped_error_is_not_treated_as_new():
    """Missing stamp — stay conservative and let the timeout decide."""
    s = snap(enabled=False, running=False, state="stopped", last_error="boom")
    assert ac.is_failed(s, ac.COMMAND_START, baseline_error_epoch=None) is False


def test_wait_returns_failed_on_a_new_error_rather_than_burning_the_timeout():
    clock = _FakeClock()
    failed = snap(enabled=False, running=False, state="stopped",
                  last_error="could not open camera", last_error_epoch=2000.0)
    _, outcome = ac.wait_for_target(
        ac.COMMAND_START, lambda: failed,
        timeout=300, monotonic=clock.monotonic, sleep=clock.sleep,
        baseline_error_epoch=None,
    )
    assert outcome == "failed"
    assert clock.t == 0.0


def test_wait_still_times_out_when_only_a_stale_error_is_present():
    clock = _FakeClock()
    stale = snap(enabled=False, running=False, state="stopped",
                 last_error="old fault", last_error_epoch=1000.0)
    _, outcome = ac.wait_for_target(
        ac.COMMAND_START, lambda: stale,
        timeout=2, monotonic=clock.monotonic, sleep=clock.sleep,
        baseline_error_epoch=1000.0,
    )
    assert outcome == "timeout"
