"""
Bearer-token authentication for the HTTP control API.

The read-only endpoints (``/latest``, ``/status``, ``/library``) are
unauthenticated by design — they are loopback-only and expose nothing that
isn't already on the operator's screen.  The *control* endpoints mutate capture
state, so they carry a bearer token and a ``Host`` allow-list on top of the
loopback bind.

Everything here is pure (plain values in, verdicts out; no Qt, no sockets, no
config object) so the full matrix — missing token, malformed header, wrong
token, no token configured — is cheap to unit-test.  Config plumbing lives in
:func:`ensure_token`, the one function that touches a config object, and even
that only calls ``get``/``set``/``save``.

**Fail closed:** when no token is configured, every control request is denied.
A blank token never means "open".
"""
from __future__ import annotations

import hmac
import re
import secrets

# Verdicts returned by check_bearer(). Only AUTH_OK admits a request.
AUTH_OK = "ok"
AUTH_NOT_CONFIGURED = "not_configured"  # no token in config — fail closed
AUTH_MISSING = "missing"                # no Authorization header at all
AUTH_MALFORMED = "malformed"            # header present but not `Bearer <token>`
AUTH_INVALID = "invalid"                # well-formed but wrong token

# HTTP status + client-facing message per verdict.
#
# The three genuine auth failures share one 401 message, so a caller cannot tell
# a wrong token from a malformed header. AUTH_NOT_CONFIGURED is deliberately
# distinct (503): a client that cannot authenticate because the feature is
# switched off needs to know that, and the NINA helper maps it to its own
# "enable the control API" exit code. That reveals only a setting the operator
# already controls — never anything about the token.
# The `code` is machine-readable and deliberately coarser than the verdict:
# all three genuine auth failures collapse to one code as well as one message,
# so a client still cannot distinguish them.
_VERDICT_RESPONSE = {
    AUTH_NOT_CONFIGURED: (503, "control_disabled",
                          "Control API is not configured on this server."),
    AUTH_MISSING: (401, "unauthorized", "Authorization required."),
    AUTH_MALFORMED: (401, "unauthorized", "Authorization required."),
    AUTH_INVALID: (401, "unauthorized", "Authorization required."),
}

# Config key holding the control-API bearer token, inside the nested `output`
# block (see services/config.py DEFAULT_CONFIG).
CONFIG_SECTION = "output"
TOKEN_KEY = "api_token"
ENABLED_KEY = "webserver_control_enabled"
ALLOWED_HOSTS_KEY = "webserver_control_allowed_hosts"

# Hosts always accepted on control routes. The server binds loopback by
# default; the configured host is added at request time by callers.
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]")

# RFC 7235 makes the auth scheme case-insensitive.
_BEARER_RE = re.compile(r"^Bearer[ \t]+(\S+)$", re.IGNORECASE)

_REDACTED = "<redacted-token>"

# Anything that looks like a token in free text. Applied to log lines and error
# payloads so a token can never reach the log file (mirrors
# services/youtube_upload.py::sanitize_exception).
_TOKEN_PATTERNS = (
    # Whole match goes — the scheme word carries no information.
    (re.compile(r"(?i)\bBearer[ \t]+\S+"), _REDACTED),
    # Keep the key name so a redacted log line still reads sensibly.
    (re.compile(r'(?i)("?api_token"?\s*[:=]\s*)"?[^"\s,}]+"?'), r"\1" + _REDACTED),
)


def generate_token() -> str:
    """Mint a new control-API token.

    32 bytes of ``secrets`` entropy, URL-safe so it survives being pasted into
    a sidecar JSON, a curl command line, or a plugin settings field.
    """
    return secrets.token_urlsafe(32)


def redact(text) -> str:
    """Strip anything token-shaped out of a string bound for a log or a client.

    Never log or return a control-API error without passing it through here.
    """
    out = str(text)
    for pattern, replacement in _TOKEN_PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def redact_all(text, *tokens) -> str:
    """:func:`redact`, plus literal removal of the known token values.

    Used where the token could appear bare (not as ``Bearer <t>`` or a config
    key), e.g. inside an exception message from a client library.
    """
    out = redact(text)
    for token in tokens:
        if token and len(str(token)) >= 8:
            out = out.replace(str(token), _REDACTED)
    return out


def parse_bearer(header_value):
    """Extract the token from an ``Authorization`` header value.

    Returns the token string, or ``None`` when the header is absent or is not a
    well-formed ``Bearer <token>``.
    """
    if not header_value:
        return None
    match = _BEARER_RE.match(str(header_value).strip())
    return match.group(1) if match else None


def check_bearer(header_value, expected_token) -> str:
    """Authenticate one control request. Returns an ``AUTH_*`` verdict.

    ``expected_token`` is whatever is configured (possibly empty/None). The
    comparison is constant-time so a wrong token cannot be recovered by timing
    the response.
    """
    if not expected_token:
        return AUTH_NOT_CONFIGURED
    if not header_value:
        return AUTH_MISSING

    presented = parse_bearer(header_value)
    if presented is None:
        return AUTH_MALFORMED

    # Compare bytes, not str. compare_digest raises TypeError on a non-ASCII
    # str, and headers arrive latin-1-decoded, so an unauthenticated client
    # could put one non-ASCII byte in the header and crash the request thread
    # before ever being rejected.
    if hmac.compare_digest(presented.encode("utf-8", "surrogateescape"),
                           str(expected_token).encode("utf-8", "surrogateescape")):
        return AUTH_OK
    return AUTH_INVALID


def verdict_response(verdict: str):
    """Map an ``AUTH_*`` verdict to ``(http_status, code, client_message)``.

    ``AUTH_OK`` has no response of its own — asking for one is a caller bug.
    """
    if verdict == AUTH_OK:
        raise ValueError("verdict_response() called on AUTH_OK")
    return _VERDICT_RESPONSE.get(verdict, (401, "unauthorized", "Authorization required."))


def normalize_host(host_header) -> str:
    """Reduce a ``Host`` header to a bare comparable hostname.

    Strips the port and lower-cases; IPv6 literals keep their brackets so they
    match the :data:`LOOPBACK_HOSTS` entries.
    """
    if not host_header:
        return ""
    host = str(host_header).strip().lower()
    if host.startswith("["):
        # IPv6 literal: [::1]:8080 -> [::1]
        end = host.find("]")
        return host[: end + 1] if end != -1 else host
    return host.rsplit(":", 1)[0] if ":" in host else host


# Bind addresses that name no reachable host, so they can never be a valid
# Host header — a request to a 0.0.0.0 bind arrives as the LAN IP or a name.
_WILDCARD_BINDS = ("0.0.0.0", "::", "[::]", "")


def host_allowed(host_header, configured_host=None, allowed_hosts=None) -> bool:
    """Whether a request's ``Host`` header may reach a control route.

    This is the direct defence against DNS rebinding: a rebound page resolves
    an attacker-controlled name to 127.0.0.1, so the socket is loopback but the
    ``Host`` header is not.  Rejecting unknown hosts closes that without
    relying on CORS side effects.

    An absent ``Host`` header is rejected — HTTP/1.1 requires one.

    ``allowed_hosts`` is the operator's escape hatch. A wildcard bind
    (``0.0.0.0``) names no host, so every real Host header — the LAN IP, a
    Tailscale MagicDNS name — would otherwise be rejected with no way to permit
    it. Adding a name here is an explicit decision to widen the control surface
    beyond loopback.
    """
    host = normalize_host(host_header)
    if not host:
        return False
    if host in LOOPBACK_HOSTS:
        return True

    configured = normalize_host(configured_host)
    if configured and configured not in _WILDCARD_BINDS and host == configured:
        return True

    for allowed in allowed_hosts or ():
        if host == normalize_host(allowed):
            return True
    return False


def allowed_control_hosts(config):
    """Extra Host values accepted on control routes (empty by default)."""
    section = config.get(CONFIG_SECTION, {}) or {}
    hosts = section.get(ALLOWED_HOSTS_KEY) or []
    return [str(h) for h in hosts if str(h).strip()]


def get_token(config) -> str:
    """Read the configured control-API token, or ``""`` when unset."""
    section = config.get(CONFIG_SECTION, {}) or {}
    return str(section.get(TOKEN_KEY, "") or "")


def ensure_token(config) -> str:
    """Return the control-API token, minting and persisting one if absent.

    Called when the control API is first enabled.  The token is written into
    the nested ``output`` block via ``config.set`` + ``config.save`` — never by
    touching ``config.json`` directly.
    """
    existing = get_token(config)
    if existing:
        return existing

    token = generate_token()
    section = dict(config.get(CONFIG_SECTION, {}) or {})
    section[TOKEN_KEY] = token
    config.set(CONFIG_SECTION, section)
    config.save()
    return token


def control_enabled(config) -> bool:
    """Whether the mutating control routes are switched on for this install.

    Opt-in: these are the only routes that change capture state, so a config
    that predates them must not silently gain them.
    """
    section = config.get(CONFIG_SECTION, {}) or {}
    return bool(section.get(ENABLED_KEY, False))


def resolve_control_token(config) -> str:
    """The token to hand the web server at start, or ``""`` to keep control off.

    Minting happens here — on first enable — rather than at install time, so a
    user who never turns control on never has a credential sitting in config.
    """
    if not control_enabled(config):
        return ""
    return ensure_token(config)
