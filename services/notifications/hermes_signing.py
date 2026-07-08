"""Generic V2 HMAC-SHA256 request signing for the Hermes webhook contract.

Pure and deterministic given a fixed timestamp — no I/O, no config reads.
See docs/dev/HERMES_NOTIFICATIONS_PLAN.md for the wire contract.
"""
import hashlib
import hmac
import json
import time


def build_signed_request(secret: str, payload: dict, timestamp: int | None = None):
    """Serialize, sign, and header-wrap a Hermes webhook payload.

    Returns ``(body_bytes, headers)``. Callers MUST POST these exact body
    bytes (``data=body``, never ``json=``) — re-serializing the payload would
    produce different bytes than the ones the signature was computed over,
    and Hermes would reject the request with 401.
    """
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ts = str(timestamp if timestamp is not None else int(time.time()))
    sig = hmac.new(
        secret.encode("utf-8"), f"{ts}.".encode("utf-8") + body, hashlib.sha256
    ).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature-V2": sig,
        "X-Webhook-Timestamp": ts,
    }
    return body, headers
