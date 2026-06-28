"""Tests for the output dispatch fan-out in ui/main_window/output.py.

Covers the independence of the web and Discord sinks (W7) and that /latest is
tagged with the per-job metadata rather than the stale preview metadata (W9).

The real mixin methods are bound onto a lightweight MagicMock host so we
exercise genuine control flow without constructing a Qt MainWindow.
"""
import types

from unittest.mock import MagicMock

from ui.main_window.output import _MainWindowOutputMixin


def _bind(win, name):
    setattr(win, name, types.MethodType(getattr(_MainWindowOutputMixin, name), win))


def test_web_encode_failure_does_not_block_discord():
    """W7: a failing web encode/push must not suppress the Discord post."""
    win = MagicMock()
    win.config = {
        "output": {"output_format": "PNG"},
        "discord": {"enabled": True, "periodic_enabled": True},
    }
    win.web_server = MagicMock()
    win.web_server.running = True
    win.preview_metadata = {}
    # First-image path → should_post is True without any timing dependency.
    win.first_image_posted_to_discord = False
    _bind(win, "_push_to_output_servers")

    img = MagicMock()
    img.save.side_effect = RuntimeError("encode boom")

    win._push_to_output_servers("/out/frame.png", img)

    # Web path raised, but the Discord post was still scheduled.
    win._send_discord_periodic_update.assert_called_once_with("/out/frame.png")


def test_web_push_uses_job_metadata():
    """W9: /latest is tagged with the job's metadata, not preview_metadata."""
    win = MagicMock()
    win.config = {
        "output": {"output_format": "JPEG", "jpg_quality": 85},
        "discord": {"enabled": False},
    }
    win.web_server = MagicMock()
    win.web_server.running = True
    win.preview_metadata = {"src": "preview"}
    _bind(win, "_push_to_output_servers")

    img = MagicMock()  # save() is a no-op; getvalue() returns b""
    job_meta = {"src": "job", "FILENAME": "f42.jpg"}

    win._push_to_output_servers("/out/f42.jpg", img, metadata=job_meta)

    _, kwargs = win.web_server.update_image.call_args
    assert kwargs["metadata"] == job_meta
    assert kwargs["metadata"]["src"] == "job"


def test_web_push_falls_back_to_preview_metadata_when_omitted():
    """W9 back-compat: callers that omit metadata still get the old behaviour."""
    win = MagicMock()
    win.config = {
        "output": {"output_format": "JPEG", "jpg_quality": 85},
        "discord": {"enabled": False},
    }
    win.web_server = MagicMock()
    win.web_server.running = True
    win.preview_metadata = {"src": "preview"}
    _bind(win, "_push_to_output_servers")

    win._push_to_output_servers("/out/f.jpg", MagicMock())

    _, kwargs = win.web_server.update_image.call_args
    assert kwargs["metadata"] == {"src": "preview"}
