"""Generic webhook HTTP POST helper — retry/backoff + error redaction.

This is for backends other than Discord (currently Hermes). It intentionally
does not touch ``discord_alerts.py`` — that module keeps its own private
``_post_with_retry`` / ``redact_discord_error`` so its behaviour stays
byte-identical.
"""
import re
import time

import requests

from ..logger import app_logger

BACKOFF_DELAYS = [1, 4, 16]  # seconds between attempts

# A live webhook secret can appear two ways in a requests exception message:
# as a bare path (".../url: /api/webhooks/<id>/<token> (Caused by ...)", the
# scheme-less form `requests` uses for connection errors) or as a query-string
# token/secret param. Strip both before running the generic URL redactor.
_WEBHOOK_PATH_RE = re.compile(r"/api/webhooks/\d+/[^\s/)]+", re.I)
_TOKEN_PARAM_RE = re.compile(r"(token|secret|signature|key)=([^&\s)]+)", re.I)


def redact_webhook_error(exc) -> str:
    """Return a log-safe ``"ExcType: message"`` string for a webhook POST error."""
    from ..youtube_upload import sanitize_exception
    text = _WEBHOOK_PATH_RE.sub("/api/webhooks/[REDACTED]", str(exc))
    text = _TOKEN_PARAM_RE.sub(r"\1=[REDACTED]", text)
    redacted = sanitize_exception(text)
    return f"{type(exc).__name__}: {redacted}"


def post_with_retry(url, *, data, headers, timeout=10, max_retries=3):
    """POST with exponential backoff and 429 rate-limit handling.

    Returns the ``requests.Response`` on success or a non-retryable error
    status, or raises the last exception after all retries are exhausted on
    connection/timeout failures.
    """
    last_exception = None
    response = None
    for attempt in range(max_retries):
        try:
            response = requests.post(url, data=data, headers=headers, timeout=timeout)

            if response.status_code == 429:
                retry_after = None
                try:
                    retry_after = response.json().get('retry_after', None)
                except Exception:
                    pass
                wait = float(retry_after) if retry_after else BACKOFF_DELAYS[min(attempt, len(BACKOFF_DELAYS) - 1)]
                app_logger.warning(
                    f"Webhook rate limited (429), retrying in {wait:.1f}s "
                    f"(attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(wait)
                continue

            return response

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exception = e
            if attempt < max_retries - 1:
                wait = BACKOFF_DELAYS[min(attempt, len(BACKOFF_DELAYS) - 1)]
                app_logger.warning(
                    f"Webhook request failed ({type(e).__name__}), "
                    f"retrying in {wait}s (attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(wait)

    if last_exception:
        raise last_exception
    return response
