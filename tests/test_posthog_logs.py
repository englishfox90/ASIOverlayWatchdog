"""
Tests for services/posthog_logs.py.

Log forwarding to PostHog is best-effort by design (see the module docstring):
it must never raise, and it must honour the same analytics opt-out as event
tracking. These two invariants are what we pin here. All network is mocked —
nothing may reach the real OTLP endpoint, and the "opentelemetry missing"
path is forced via sys.modules so the test doesn't depend on whatever happens
to be installed in this venv (pip may be installing opentelemetry packages
concurrently with this test run).
"""
import logging
import sys
from unittest.mock import patch

import pytest

from services import posthog_logs


# sys.modules[name] = None makes `import name` (or `from name import x`) raise
# ImportError immediately without touching the real package, if any is
# installed. Same technique test_frame_buffers.py uses for optional cv2.
_OTEL_MODULES_TO_BLOCK = {
    "opentelemetry": None,
    "opentelemetry.sdk": None,
    "opentelemetry.sdk._logs": None,
    "opentelemetry.sdk._logs.export": None,
    "opentelemetry.sdk.resources": None,
    "opentelemetry.exporter": None,
    "opentelemetry.exporter.otlp": None,
    "opentelemetry.exporter.otlp.proto": None,
    "opentelemetry.exporter.otlp.proto.http": None,
    "opentelemetry.exporter.otlp.proto.http._log_exporter": None,
}


@pytest.fixture(autouse=True)
def _reset_module_state():
    """The attach/shutdown pair is guarded by module-level singletons
    (_attached, _logger_provider). Reset them around every test so tests
    don't leak state into each other, and strip any handler that a test
    might (accidentally) attach to the real app logger."""
    app_logger_obj = logging.getLogger(
        __import__("services.app_config", fromlist=["APP_NAME"]).APP_NAME
    )
    handlers_before = list(app_logger_obj.handlers)
    posthog_logs._attached = False
    posthog_logs._logger_provider = None
    yield
    posthog_logs._attached = False
    posthog_logs._logger_provider = None
    for h in list(app_logger_obj.handlers):
        if h not in handlers_before:
            app_logger_obj.removeHandler(h)


class TestAttachIsNoOpWhenOpentelemetryMissing:
    def test_returns_none_without_raising(self):
        with patch("services.posthog_service.is_enabled", return_value=True), \
                patch.dict(sys.modules, _OTEL_MODULES_TO_BLOCK):
            result = posthog_logs.attach_posthog_log_handler()
        assert result is None

    def test_does_not_mark_attached(self):
        with patch("services.posthog_service.is_enabled", return_value=True), \
                patch.dict(sys.modules, _OTEL_MODULES_TO_BLOCK):
            posthog_logs.attach_posthog_log_handler()
        assert posthog_logs._attached is False
        assert posthog_logs._logger_provider is None

    def test_no_handler_attached_to_app_logger(self):
        app_logger_obj = logging.getLogger(
            __import__("services.app_config", fromlist=["APP_NAME"]).APP_NAME
        )
        before = len(app_logger_obj.handlers)
        with patch("services.posthog_service.is_enabled", return_value=True), \
                patch.dict(sys.modules, _OTEL_MODULES_TO_BLOCK):
            posthog_logs.attach_posthog_log_handler()
        assert len(app_logger_obj.handlers) == before

    def test_swallows_import_error_even_if_otel_is_actually_installed(self):
        """Guards against pip mid-installing opentelemetry during this test
        run: even if the real package importable, forcing the failure via
        sys.modules must still be honoured by the import machinery."""
        with patch("services.posthog_service.is_enabled", return_value=True), \
                patch.dict(sys.modules, _OTEL_MODULES_TO_BLOCK):
            # Must not raise regardless of what's on disk.
            posthog_logs.attach_posthog_log_handler()


class TestAttachHonoursOptOut:
    def test_returns_early_when_disabled(self):
        with patch("services.posthog_service.is_enabled", return_value=False):
            result = posthog_logs.attach_posthog_log_handler()
        assert result is None
        assert posthog_logs._attached is False
        assert posthog_logs._logger_provider is None

    def test_does_not_attempt_otel_import_when_disabled(self):
        """If opt-out short-circuits before the try/import block, importing
        the (blocked) opentelemetry modules should never even be attempted,
        so forcing ImportError here should have no observable difference."""
        with patch("services.posthog_service.is_enabled", return_value=False), \
                patch.dict(sys.modules, _OTEL_MODULES_TO_BLOCK):
            posthog_logs.attach_posthog_log_handler()
        assert posthog_logs._attached is False

    def test_idempotent_when_already_attached(self):
        """If a previous call already attached, a second call must be a
        pure no-op regardless of the current opt-out state."""
        posthog_logs._attached = True
        with patch("services.posthog_service.is_enabled") as mock_enabled:
            result = posthog_logs.attach_posthog_log_handler()
            mock_enabled.assert_not_called()
        assert result is None


class TestOptOutFilter:
    def test_allows_records_when_enabled(self):
        f = posthog_logs._OptOutFilter()
        record = logging.LogRecord(
            "test", logging.WARNING, __file__, 1, "msg", None, None
        )
        with patch("services.posthog_service.is_enabled", return_value=True):
            assert f.filter(record) is True

    def test_drops_records_when_disabled(self):
        f = posthog_logs._OptOutFilter()
        record = logging.LogRecord(
            "test", logging.WARNING, __file__, 1, "msg", None, None
        )
        with patch("services.posthog_service.is_enabled", return_value=False):
            assert f.filter(record) is False

    def test_reflects_runtime_toggle(self):
        """The filter re-checks is_enabled() per record, so a user flipping
        the setting mid-session takes effect on the very next log line
        without re-wiring the handler."""
        f = posthog_logs._OptOutFilter()
        record = logging.LogRecord(
            "test", logging.WARNING, __file__, 1, "msg", None, None
        )
        with patch("services.posthog_service.is_enabled", return_value=True):
            assert f.filter(record) is True
        with patch("services.posthog_service.is_enabled", return_value=False):
            assert f.filter(record) is False
        with patch("services.posthog_service.is_enabled", return_value=True):
            assert f.filter(record) is True


class TestShutdownIsSafe:
    def test_shutdown_without_attach_is_a_noop(self):
        posthog_logs._logger_provider = None
        posthog_logs._attached = False
        posthog_logs.shutdown_posthog_logs()  # must not raise
        assert posthog_logs._logger_provider is None
        assert posthog_logs._attached is False

    def test_shutdown_swallows_provider_errors(self):
        from unittest.mock import MagicMock
        provider = MagicMock()
        provider.shutdown.side_effect = Exception("network unreachable")
        posthog_logs._logger_provider = provider
        posthog_logs._attached = True
        posthog_logs.shutdown_posthog_logs()  # must not raise
        provider.shutdown.assert_called_once()
        assert posthog_logs._logger_provider is None
        assert posthog_logs._attached is False
