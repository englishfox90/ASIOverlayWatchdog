"""Tests for services/api_auth.py — control-API bearer auth (pure logic)."""
import pytest

from services import api_auth


class _FakeConfig:
    """Minimal stand-in for services.config with the same get/set/save surface."""

    def __init__(self, data=None):
        self.data = dict(data or {})
        self.saves = 0

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        self.saves += 1


# --- token generation -----------------------------------------------------

def test_generate_token_is_url_safe_and_unique():
    a = api_auth.generate_token()
    b = api_auth.generate_token()
    assert a != b
    assert len(a) >= 32
    assert all(c.isalnum() or c in "-_" for c in a)


# --- header parsing -------------------------------------------------------

@pytest.mark.parametrize("header,expected", [
    ("Bearer abc123", "abc123"),
    ("Bearer\tabc123", "abc123"),
    ("  Bearer abc123  ", "abc123"),
    ("bearer abc123", "abc123"),      # RFC 7235: the auth scheme is case-insensitive
    ("Basic abc123", None),
    ("abc123", None),
    ("Bearer", None),
    ("Bearer a b", None),
    ("", None),
    (None, None),
])
def test_parse_bearer(header, expected):
    assert api_auth.parse_bearer(header) == expected


# --- the auth matrix ------------------------------------------------------

def test_correct_token_is_accepted():
    assert api_auth.check_bearer("Bearer s3cret", "s3cret") == api_auth.AUTH_OK


def test_wrong_token_is_rejected():
    assert api_auth.check_bearer("Bearer nope", "s3cret") == api_auth.AUTH_INVALID


def test_missing_header_is_rejected():
    assert api_auth.check_bearer(None, "s3cret") == api_auth.AUTH_MISSING


def test_malformed_header_is_rejected():
    assert api_auth.check_bearer("Basic s3cret", "s3cret") == api_auth.AUTH_MALFORMED


@pytest.mark.parametrize("configured", ["", None])
def test_no_configured_token_fails_closed(configured):
    """A blank token must never mean 'open' — even with a valid-looking header."""
    assert api_auth.check_bearer("Bearer anything", configured) == api_auth.AUTH_NOT_CONFIGURED


def test_prefix_of_correct_token_is_rejected():
    assert api_auth.check_bearer("Bearer s3cr", "s3cret") == api_auth.AUTH_INVALID


def test_verdict_response_maps_statuses():
    assert api_auth.verdict_response(api_auth.AUTH_MISSING)[0] == 401
    assert api_auth.verdict_response(api_auth.AUTH_INVALID)[0] == 401
    assert api_auth.verdict_response(api_auth.AUTH_NOT_CONFIGURED)[0] == 503


def test_invalid_and_missing_share_a_message():
    """Responses must not let a caller probe whether a token is configured."""
    assert (api_auth.verdict_response(api_auth.AUTH_MISSING)[1]
            == api_auth.verdict_response(api_auth.AUTH_INVALID)[1])


def test_verdict_response_rejects_ok():
    with pytest.raises(ValueError):
        api_auth.verdict_response(api_auth.AUTH_OK)


# --- Host allow-list (DNS rebinding defence) ------------------------------

@pytest.mark.parametrize("host", [
    "localhost", "127.0.0.1", "localhost:8080", "127.0.0.1:8080",
    "LOCALHOST:8080", "[::1]", "[::1]:8080",
])
def test_loopback_hosts_allowed(host):
    assert api_auth.host_allowed(host) is True


@pytest.mark.parametrize("host", [
    "evil.example.com", "evil.example.com:8080", "192.168.1.50", "", None,
])
def test_foreign_hosts_rejected(host):
    assert api_auth.host_allowed(host) is False


def test_configured_host_allowed():
    assert api_auth.host_allowed("obs-pc:8080", configured_host="obs-pc") is True
    assert api_auth.host_allowed("other-pc:8080", configured_host="obs-pc") is False


# --- redaction ------------------------------------------------------------

def test_redact_strips_bearer_header():
    assert "s3cret" not in api_auth.redact("auth failed for Bearer s3cret on /capture/start")


def test_redact_strips_config_key():
    assert "s3cret" not in api_auth.redact('{"api_token": "s3cret"}')
    assert "s3cret" not in api_auth.redact("api_token=s3cret")


def test_redact_all_strips_bare_token():
    text = "connection refused while presenting s3cret-token-value"
    assert "s3cret-token-value" not in api_auth.redact_all(text, "s3cret-token-value")


def test_redact_all_ignores_short_values():
    """A short 'token' would redact half the message — leave it alone."""
    assert api_auth.redact_all("state is stopped", "ed") == "state is stopped"


def test_redact_leaves_unrelated_text_intact():
    assert api_auth.redact("capture started") == "capture started"


# --- config plumbing ------------------------------------------------------

def test_get_token_reads_nested_output_block():
    cfg = _FakeConfig({"output": {"api_token": "s3cret"}})
    assert api_auth.get_token(cfg) == "s3cret"


def test_get_token_missing_returns_empty():
    assert api_auth.get_token(_FakeConfig({})) == ""
    assert api_auth.get_token(_FakeConfig({"output": {}})) == ""


def test_ensure_token_mints_and_persists():
    cfg = _FakeConfig({"output": {"webserver_enabled": True}})
    token = api_auth.ensure_token(cfg)
    assert token
    assert cfg.data["output"]["api_token"] == token
    assert cfg.data["output"]["webserver_enabled"] is True  # siblings preserved
    assert cfg.saves == 1


def test_ensure_token_is_idempotent():
    cfg = _FakeConfig({"output": {"api_token": "existing"}})
    assert api_auth.ensure_token(cfg) == "existing"
    assert cfg.saves == 0


# --- non-ASCII credentials (review follow-up) -----------------------------

@pytest.mark.parametrize("header", [
    "Bearer éabc",        # accented text
    "Bearer \udcff",           # a raw latin-1 byte, as http.client decodes it
    "Bearer 中文",     # non-Latin script
])
def test_non_ascii_bearer_is_rejected_not_raised(header):
    """hmac.compare_digest raises TypeError on a non-ASCII str.

    Headers reach us latin-1-decoded, so without comparing bytes an
    unauthenticated client could crash the request thread with a single byte
    before ever being rejected.
    """
    assert api_auth.check_bearer(header, "s3cret") == api_auth.AUTH_INVALID


def test_non_ascii_token_still_authenticates():
    token = "s3cret-éè"
    assert api_auth.check_bearer(f"Bearer {token}", token) == api_auth.AUTH_OK


def test_scheme_is_case_insensitive():
    for scheme in ("Bearer", "bearer", "BEARER", "BeArEr"):
        assert api_auth.check_bearer(f"{scheme} s3cret", "s3cret") == api_auth.AUTH_OK


def test_redact_keeps_the_key_name():
    """A redacted log line should still read sensibly."""
    assert api_auth.redact("api_token=s3cret") == "api_token=<redacted-token>"
