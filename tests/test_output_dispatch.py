"""Tests for the output dispatch fan-out in ui/main_window/output.py.

Covers the independence of the web and Discord sinks (W7) and that /latest is
tagged with the per-job metadata rather than the stale preview metadata (W9).

The real mixin methods are bound onto a lightweight MagicMock host so we
exercise genuine control flow without constructing a Qt MainWindow.
"""
import io
import types

from unittest.mock import MagicMock

from PIL import Image

from ui.main_window.output import _MainWindowOutputMixin


def _bind(win, name):
    setattr(win, name, types.MethodType(getattr(_MainWindowOutputMixin, name), win))


def _frame(width=32, height=24):
    """A real (tiny) frame — the encoder inspects size/mode, so a mock won't do."""
    return Image.new('RGB', (width, height), (10, 20, 30))


def test_web_encode_failure_does_not_block_discord():
    """W7: a failing web encode/push must not suppress the Discord post."""
    win = MagicMock()
    win.config = {
        "output_format": "PNG",
        "output": {},
        "discord": {"enabled": True, "periodic_enabled": True},
    }
    win.web_server = MagicMock()
    win.web_server.running = True
    win.preview_metadata = {}
    # First-image path → should_post is True without any timing dependency.
    win.first_image_posted_to_discord = False
    _bind(win, "_push_to_output_servers")

    img = MagicMock()
    img.size = (32, 24)
    img.save.side_effect = RuntimeError("encode boom")

    win._push_to_output_servers("/out/frame.png", img)

    # Web path raised, but the Discord post was still scheduled.
    win._send_discord_periodic_update.assert_called_once_with("/out/frame.png")


def test_web_push_uses_job_metadata():
    """W9: /latest is tagged with the job's metadata, not preview_metadata."""
    win = MagicMock()
    win.config = {
        "output_format": "jpg",
        "jpg_quality": 85,
        "output": {},
        "discord": {"enabled": False},
    }
    win.web_server = MagicMock()
    win.web_server.running = True
    win.preview_metadata = {"src": "preview"}
    _bind(win, "_push_to_output_servers")

    job_meta = {"src": "job", "FILENAME": "f42.jpg"}

    win._push_to_output_servers("/out/f42.jpg", _frame(), metadata=job_meta)

    _, kwargs = win.web_server.update_image.call_args
    assert kwargs["metadata"] == job_meta
    assert kwargs["metadata"]["src"] == "job"


def test_web_push_falls_back_to_preview_metadata_when_omitted():
    """W9 back-compat: callers that omit metadata still get the old behaviour."""
    win = MagicMock()
    win.config = {
        "output_format": "jpg",
        "jpg_quality": 85,
        "output": {},
        "discord": {"enabled": False},
    }
    win.web_server = MagicMock()
    win.web_server.running = True
    win.preview_metadata = {"src": "preview"}
    _bind(win, "_push_to_output_servers")

    win._push_to_output_servers("/out/f.jpg", _frame())

    _, kwargs = win.web_server.update_image.call_args
    assert kwargs["metadata"] == {"src": "preview"}


def _push_with(config, frame=None):
    """Run one web push against ``config``.

    Returns (image_bytes, content_type) as handed to update_image().
    """
    win = MagicMock()
    win.config = dict(config)
    win.config.setdefault("output", {})
    win.config.setdefault("discord", {"enabled": False})
    win.web_server = MagicMock()
    win.web_server.running = True
    win.preview_metadata = {}
    _bind(win, "_push_to_output_servers")

    win._push_to_output_servers("/out/f.jpg", frame or _frame())
    args, kwargs = win.web_server.update_image.call_args
    return args[1], kwargs["content_type"]


def test_web_push_reads_top_level_output_format():
    """output_format is a TOP-LEVEL key — reading it from the nested 'output'
    section always missed, which forced every frame down the PNG branch."""
    _, content_type = _push_with({"output_format": "jpg", "jpg_quality": 85})
    assert content_type == "image/jpeg"


def test_web_push_honours_top_level_png_choice():
    _, content_type = _push_with({"output_format": "png"})
    assert content_type == "image/png"


def test_web_push_ignores_a_stray_nested_output_format():
    """A leftover nested key must not override the real top-level setting."""
    _, content_type = _push_with({
        "output_format": "jpg",
        "output": {"output_format": "PNG"},
    })
    assert content_type == "image/jpeg"


def test_web_push_resizes_a_large_frame_instead_of_serving_full_res():
    from services.web_image_encode import WEB_IMAGE_MAX_DIM

    data, content_type = _push_with(
        {"output_format": "png"}, frame=_frame(WEB_IMAGE_MAX_DIM + 500, 400)
    )
    # Downgraded to JPEG and clamped — never a full-res optimized PNG.
    assert content_type == "image/jpeg"
    assert max(Image.open(io.BytesIO(data)).size) <= WEB_IMAGE_MAX_DIM
