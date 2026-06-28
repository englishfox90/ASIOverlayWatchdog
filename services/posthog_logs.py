"""
Forward PFR Sentinel application logs to PostHog.

PostHog ingests logs over the OpenTelemetry (OTLP/HTTP) protocol. We attach an
OpenTelemetry ``LoggingHandler`` to the app's dedicated logger (``APP_NAME``),
so every ``app_logger`` message is mirrored to PostHog in addition to the
rotating file log. See https://posthog.com/docs/logs/installation/python.

Design goals (all best-effort — log forwarding must never affect the app):
  - Optional: if the ``opentelemetry-*`` packages aren't installed, this is a
    silent no-op. The file log keeps working regardless.
  - Opt-out aware: respects the same ``analytics_enabled`` switch as events.
    A logging filter re-checks ``is_enabled()`` on every record, so toggling
    the setting at runtime takes effect immediately.
  - Crash-safe: setup and shutdown swallow all exceptions.
"""
import logging

from .app_config import APP_NAME
from .logger import app_logger
from . import posthog_service

# PostHog's OTLP logs endpoint lives under the same ingestion host as events.
_LOGS_ENDPOINT = f"{posthog_service.POSTHOG_HOST}/i/v1/logs"

_logger_provider = None
_attached = False


class _OptOutFilter(logging.Filter):
    """Drop records when the user has opted out of analytics.

    The OTLP handler is wired straight onto the logger, bypassing the PostHog
    SDK's ``disabled`` flag, so we gate it here instead. Checked per-record so a
    runtime opt-out toggle stops log forwarding without re-plumbing the handler.
    """

    def filter(self, record):
        return posthog_service.is_enabled()


def attach_posthog_log_handler():
    """Attach the OTLP log handler to the app logger. Idempotent and best-effort."""
    global _logger_provider, _attached
    if _attached:
        return
    if not posthog_service.is_enabled():
        # Opted out at startup — don't even build the pipeline. A later opt-in
        # takes effect on next launch, matching how event tracking behaves.
        return

    try:
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.otlp.proto.http._log_exporter import (
            OTLPLogExporter,
        )
    except ImportError:
        app_logger.debug(
            "PostHog log forwarding disabled (opentelemetry not installed)"
        )
        return

    try:
        from version import __version__
    except Exception:
        __version__ = "unknown"

    try:
        resource = Resource.create({
            "service.name": APP_NAME,
            "service.version": __version__,
            # Correlate logs with the same anonymous install that emits events.
            "distinct_id": posthog_service.get_distinct_id(),
        })
        provider = LoggerProvider(resource=resource)
        exporter = OTLPLogExporter(
            endpoint=_LOGS_ENDPOINT,
            headers={"Authorization": f"Bearer {posthog_service.PROJECT_API_KEY}"},
        )
        provider.add_log_record_processor(BatchLogRecordProcessor(exporter))

        handler = LoggingHandler(level=logging.INFO, logger_provider=provider)
        handler.addFilter(_OptOutFilter())

        # APP_NAME is the dedicated logger that AppLogger routes every message
        # through, so attaching here captures all app logs and nothing else
        # (third-party loggers are silenced/non-propagating in logger.py).
        logging.getLogger(APP_NAME).addHandler(handler)

        _logger_provider = provider
        _attached = True
        app_logger.debug("PostHog log forwarding enabled")
    except Exception:
        app_logger.debug("PostHog log forwarding setup failed (non-critical)")


def shutdown_posthog_logs():
    """Flush and stop the log pipeline. Safe to call when never attached."""
    global _logger_provider, _attached
    provider = _logger_provider
    if provider is None:
        return
    try:
        provider.shutdown()  # flushes any queued records before stopping
    except Exception:
        pass
    finally:
        _logger_provider = None
        _attached = False
