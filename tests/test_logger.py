"""
Tests for services/logger.py

Covers _safe_console_write() (the encoding-safety fix for a latent crash:
console output previously used a bare print(), which raised
UnicodeEncodeError on a cp1252-redirected stdout for the arrows/warning
signs/emoji used throughout log messages, and would also raise
AttributeError when sys.stdout is None, as it is in a PyInstaller
windowed build) and AppLogger.log()'s use of it.
"""
import io
import logging
import queue
import sys

import pytest

from services.logger import AppLogger, _safe_console_write

NON_ASCII_MESSAGE = "warning ⚠ threshold exceeded → check camera"


def _make_isolated_logger(tmp_path, logger_name, request):
    """Build an AppLogger wired to a private stdlib logger + temp file.

    AppLogger.__init__ binds to the process-wide, name-cached APP_NAME
    logger and the real %APPDATA% log directory. Bypassing it (and giving
    each test its own logger name) keeps these tests from stepping on the
    real application logger or on each other.
    """
    inst = AppLogger.__new__(AppLogger)
    inst.message_queue = queue.Queue()
    inst.log_callbacks = []
    inst.error_callback = None
    inst.log_dir = tmp_path

    file_logger = logging.getLogger(logger_name)
    file_logger.setLevel(logging.DEBUG)
    file_logger.propagate = False
    for h in list(file_logger.handlers):
        file_logger.removeHandler(h)
        h.close()

    log_path = tmp_path / "test.log"
    handler = logging.FileHandler(log_path, encoding='utf-8')
    handler.setFormatter(logging.Formatter(
        '[%(asctime)s] %(levelname)-8s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    file_logger.addHandler(handler)

    def _cleanup():
        handler.close()
        file_logger.removeHandler(handler)
    request.addfinalizer(_cleanup)

    inst.file_logger = file_logger
    inst.file_handler = handler
    return inst, log_path


class TestSafeConsoleWrite:
    """Unit tests for the standalone console-write helper."""

    def test_ascii_message_written_unchanged(self, monkeypatch):
        buf = io.StringIO()
        monkeypatch.setattr(sys, 'stdout', buf)

        _safe_console_write("plain ascii message")

        assert buf.getvalue() == "plain ascii message\n"

    def test_nonascii_on_cp1252_stream_does_not_raise(self, monkeypatch):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding='cp1252')
        monkeypatch.setattr(sys, 'stdout', stream)

        _safe_console_write(NON_ASCII_MESSAGE)  # must not raise
        stream.flush()

        written = raw.getvalue()
        assert written != b''
        assert b'threshold exceeded' in written

    def test_stdout_none_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(sys, 'stdout', None)

        _safe_console_write(NON_ASCII_MESSAGE)  # must not raise, must not touch anything

    def test_stdout_closed_does_not_raise(self, monkeypatch):
        stream = io.StringIO()
        stream.close()
        monkeypatch.setattr(sys, 'stdout', stream)

        _safe_console_write("hello")  # must not raise (ValueError: I/O on closed file)

    def test_stream_missing_encoding_attribute_does_not_raise(self, monkeypatch):
        class NoEncodingStream:
            def write(self, text):
                raise UnicodeEncodeError('ascii', text, 0, 1, 'boom')

            def flush(self):
                pass

        monkeypatch.setattr(sys, 'stdout', NoEncodingStream())

        _safe_console_write(NON_ASCII_MESSAGE)  # must not raise even on repeated failure


class TestAppLoggerLog:
    """Behavioural tests for AppLogger.log()'s console/queue/file fan-out."""

    def test_ascii_message_unchanged_in_console_queue_and_file(self, tmp_path, request):
        inst, log_path = _make_isolated_logger(tmp_path, "TestLoggerAscii", request)
        console = io.StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, 'stdout', console)
            inst.log("hello world", "INFO")

        assert "INFO: hello world" in console.getvalue()

        messages = inst.get_messages()
        assert len(messages) == 1
        assert "hello world" in messages[0]

        assert "hello world" in log_path.read_text(encoding='utf-8')

    def test_nonascii_message_on_cp1252_console_does_not_raise(self, tmp_path, request):
        inst, log_path = _make_isolated_logger(tmp_path, "TestLoggerCp1252", request)
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding='cp1252')

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, 'stdout', stream)
            inst.log(NON_ASCII_MESSAGE, "WARN")  # must not raise
            stream.flush()

        assert raw.getvalue() != b''

        # The file handler (UTF-8) must keep the original characters —
        # only the console degrades.
        file_contents = log_path.read_text(encoding='utf-8')
        assert NON_ASCII_MESSAGE in file_contents

        # The GUI queue also keeps the untouched unicode text; Qt widgets
        # render it natively, so it must not be pre-degraded here either.
        messages = inst.get_messages()
        assert len(messages) == 1
        assert NON_ASCII_MESSAGE in messages[0]

    def test_stdout_none_during_log_does_not_raise(self, tmp_path, request):
        inst, log_path = _make_isolated_logger(tmp_path, "TestLoggerNone", request)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, 'stdout', None)
            inst.log("still works", "ERROR")  # must not raise

        assert "still works" in log_path.read_text(encoding='utf-8')

    def test_stdout_closed_during_log_does_not_raise(self, tmp_path, request):
        inst, log_path = _make_isolated_logger(tmp_path, "TestLoggerClosedStream", request)
        stream = io.StringIO()
        stream.close()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, 'stdout', stream)
            inst.log(NON_ASCII_MESSAGE, "DEBUG")  # must not raise

        assert NON_ASCII_MESSAGE in log_path.read_text(encoding='utf-8')
