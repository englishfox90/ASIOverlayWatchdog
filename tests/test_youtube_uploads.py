import json
import os
import sys
import types
from datetime import datetime

from services.timelapse_publishers import TimelapsePublishers, make_timelapse_metadata
from services.youtube_config import (
    normalize_youtube_config,
    parse_tags,
    render_template,
    validate_youtube_config,
)
from services.youtube_upload import YouTubeUploadResult, classify_google_error, sanitize_exception
from services.youtube_upload_state import YouTubeUploadStateStore


class DummyConfig:
    def __init__(self, youtube=None, discord=None, timelapse=None, weather=None):
        self._values = {
            "youtube": youtube or {},
            "discord": discord or {},
            "timelapse": timelapse or {},
            "weather": weather or {},
        }

    def get(self, key, default=None):
        return self._values.get(key, default)


class DummyAuth:
    def __init__(self, has_token=False):
        self._has_token = has_token

    def has_token(self):
        return self._has_token


class DummyUploader:
    def upload_video(self, config, metadata, *, resumable_uri="", progress_callback=None):
        if progress_callback:
            progress_callback({"resumable_uri": "https://upload.example/session"})
        return YouTubeUploadResult(
            True,
            "uploaded",
            "Uploaded",
            video_id="abc123",
            watch_url="https://www.youtube.com/watch?v=abc123",
        )


class DummyPublishers:
    def __init__(self):
        self.published = []

    def publish_finished(self, metadata):
        self.published.append(metadata)

    def shutdown(self, timeout=10.0):
        pass


def make_timelapse_controller(config):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QObject
    from PySide6.QtWidgets import QApplication
    from ui.controllers.timelapse_controller import TimelapseController

    app = QApplication.instance()
    if app is None or app.__class__.__name__ != "QApplication":
        QApplication([])

    class DummyMainWindow(QObject):
        def __init__(self, cfg):
            super().__init__()
            self.config = cfg

    controller = TimelapseController(DummyMainWindow(config))
    controller._status_timer.stop()
    controller._main_window.timelapse_controller = controller
    return controller


def make_youtube_card(tmp_path, *, enabled=False, client_json="", has_token=False):
    from PySide6.QtWidgets import QApplication
    from ui.panels.youtube_upload_card import YouTubeUploadCard

    app = QApplication.instance()
    if app is None or app.__class__.__name__ != "QApplication":
        QApplication([])
    youtube_cfg = {
        "enabled": enabled,
        "client_secrets_path": client_json,
        "privacy_status": "private",
        "title_template": "PFR Sentinel Timelapse {date}",
        "description_template": "All-sky timelapse recorded by PFR Sentinel.",
        "tags": "astronomy, allsky, timelapse",
        "category_id": "22",
    }
    config = DummyConfig(youtube=youtube_cfg, timelapse={}, weather={})
    controller = make_timelapse_controller(config)
    controller._publishers.youtube_auth.has_token = lambda: has_token

    class DummyPanel:
        def __init__(self, main_window):
            self.main_window = main_window

    panel = DummyPanel(controller._main_window)
    card = YouTubeUploadCard(panel)
    card.load_from_config(youtube_cfg)
    return card, controller


def test_youtube_config_normalizes_flat_values():
    cfg = normalize_youtube_config({
        "enabled": 1,
        "privacy_status": "PUBLIC",
        "tags": ["astronomy", "allsky", "astronomy"],
    })

    assert cfg["enabled"] is True
    assert cfg["privacy_status"] == "public"
    assert cfg["tags"] == "astronomy, allsky, astronomy"
    assert parse_tags(cfg["tags"]) == ["astronomy", "allsky"]


def test_youtube_config_validation_requires_client_file(tmp_path):
    missing = tmp_path / "missing.json"
    errors = validate_youtube_config({"enabled": True, "client_secrets_path": str(missing)})

    assert "OAuth client JSON was not found." in errors


def test_template_rendering_leaves_unknown_placeholders(tmp_path):
    video = tmp_path / "timelapse_20260619.mp4"
    video.write_bytes(b"fake")
    metadata = make_timelapse_metadata(str(video), frame_count=42, elapsed_seconds=65)
    metadata = metadata.__class__(
        path=metadata.path,
        frame_count=metadata.frame_count,
        elapsed_seconds=metadata.elapsed_seconds,
        file_size_bytes=metadata.file_size_bytes,
        queued_at=datetime(2026, 6, 19, 21, 30, 0),
    )

    rendered = render_template("{date} {filename} {frame_count} {duration} {missing}", metadata)

    assert rendered == "2026-06-19 timelapse_20260619.mp4 42 00:01:05 {missing}"


def test_upload_state_claims_and_prevents_duplicate(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake video")
    store = YouTubeUploadStateStore(storage_dir=str(tmp_path))

    claimed, key, entry = store.claim(str(video))
    duplicate, _, duplicate_entry = store.claim(str(video))

    assert claimed is True
    assert entry["status"] == "in_progress"
    assert duplicate is False
    assert duplicate_entry["status"] == "in_progress"

    store.mark_uploaded(key, video_id="abc123", watch_url="https://youtu.be/abc123")
    uploaded = store.get(key)
    assert uploaded["status"] == "uploaded"
    assert uploaded["video_id"] == "abc123"


def test_upload_state_recovers_from_corrupt_file(tmp_path):
    state_path = tmp_path / "youtube_upload_state.json"
    state_path.write_text("{not json", encoding="utf-8")
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")

    store = YouTubeUploadStateStore(storage_dir=str(tmp_path))
    claimed, _, _ = store.claim(str(video))

    assert claimed is True
    assert json.loads(state_path.read_text(encoding="utf-8"))["version"] == 1


def test_sanitize_exception_redacts_sensitive_values():
    text = sanitize_exception(
        "access_token=secret refresh_token=secret2 https://accounts.google.com/o/oauth2 C:\\Users\\Alice\\client.json"
    )

    assert "secret" not in text
    assert "accounts.google.com" not in text
    assert "Alice" not in text


def test_invalid_grant_maps_to_auth_expired():
    result = classify_google_error(Exception("invalid_grant: Token has been expired or revoked"))

    assert result.status == "auth_expired"
    assert result.retryable is False


def test_publisher_manual_upload_requires_auth(tmp_path):
    client_json = tmp_path / "client.json"
    client_json.write_text("{}", encoding="utf-8")
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")
    statuses = []
    publisher = TimelapsePublishers(
        DummyConfig(youtube={
            "enabled": True,
            "client_secrets_path": str(client_json),
            "privacy_status": "private",
        }),
        youtube_status_callback=statuses.append,
        youtube_auth_manager=DummyAuth(has_token=False),
    )

    result = publisher.enqueue_youtube_upload(make_timelapse_metadata(str(video), 0, 0), manual=True)

    assert result.status == "auth_required"
    assert statuses[-1]["status"] == "auth_required"


def test_publisher_disabled_does_not_start_upload(tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")
    statuses = []
    publisher = TimelapsePublishers(
        DummyConfig(youtube={"enabled": False}),
        youtube_status_callback=statuses.append,
        youtube_auth_manager=DummyAuth(has_token=True),
    )

    result = publisher.enqueue_youtube_upload(make_timelapse_metadata(str(video), 0, 0), manual=True)

    assert result.status == "disabled"
    assert statuses[-1]["status"] == "disabled"


def test_publisher_queue_marks_upload_success(tmp_path):
    client_json = tmp_path / "client.json"
    client_json.write_text("{}", encoding="utf-8")
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")
    statuses = []
    store = YouTubeUploadStateStore(storage_dir=str(tmp_path))
    publisher = TimelapsePublishers(
        DummyConfig(youtube={
            "enabled": True,
            "client_secrets_path": str(client_json),
            "privacy_status": "private",
        }),
        youtube_status_callback=statuses.append,
        youtube_auth_manager=DummyAuth(has_token=True),
        youtube_uploader=DummyUploader(),
        youtube_state_store=store,
    )

    result = publisher.enqueue_youtube_upload(make_timelapse_metadata(str(video), 3, 10), manual=True)
    publisher._queue.join()
    publisher.shutdown(timeout=1)
    entry = store.get(store.make_key(str(video)))

    assert result.status == "queued"
    assert entry["status"] == "uploaded"
    assert entry["video_id"] == "abc123"
    assert statuses[-1]["status"] == "uploaded"


def test_controller_latest_completed_video_excludes_active_recording(tmp_path):
    older = tmp_path / "timelapse_20260618.mp4"
    active = tmp_path / "timelapse_20260619.mp4"
    older.write_bytes(b"older")
    active.write_bytes(b"active")
    os.utime(older, (1000, 1000))
    os.utime(active, (2000, 2000))

    controller = make_timelapse_controller(
        DummyConfig(timelapse={"output_dir": str(tmp_path)}, weather={})
    )
    controller.get_status = lambda: {
        "recording": True,
        "session_path": str(active),
    }

    try:
        assert controller._find_latest_completed_video() == str(older)
    finally:
        controller.shutdown()


def test_controller_session_finished_hands_metadata_to_publishers(tmp_path, monkeypatch):
    video = tmp_path / "timelapse_20260619.mp4"
    video.write_bytes(b"fake video")
    captured = []
    fake_posthog = types.SimpleNamespace(
        capture_event=lambda name, props: captured.append((name, props))
    )
    monkeypatch.setitem(sys.modules, "services.posthog_service", fake_posthog)

    controller = make_timelapse_controller(
        DummyConfig(
            youtube={"enabled": True},
            discord={"enabled": True, "post_timelapse": True},
            timelapse={"output_dir": str(tmp_path)},
            weather={},
        )
    )
    publishers = DummyPublishers()
    controller._publishers = publishers

    try:
        controller._on_session_finished(str(video), frame_count=42, elapsed_seconds=65)
    finally:
        controller.shutdown()

    assert len(publishers.published) == 1
    metadata = publishers.published[0]
    assert metadata.path == str(video)
    assert metadata.frame_count == 42
    assert metadata.elapsed_seconds == 65
    assert captured[0][0] == "timelapse_session_finished"
    assert captured[0][1]["youtube_delivery"] is True
    assert captured[0][1]["discord_delivery"] is True


def test_youtube_card_guides_setup_steps(tmp_path):
    card, controller = make_youtube_card(tmp_path, enabled=False, client_json="", has_token=False)

    try:
        assert "Turn on uploads" in card._step_label.text()
        assert card.auth_btn.isEnabled() is False
        assert card.upload_latest_btn.isEnabled() is False
        assert card._advanced_widget.isVisible() is False
    finally:
        controller.shutdown()


def test_youtube_card_unlocks_auth_then_upload(tmp_path):
    client_json = tmp_path / "client.json"
    client_json.write_text("{}", encoding="utf-8")
    card, controller = make_youtube_card(
        tmp_path,
        enabled=True,
        client_json=str(client_json),
        has_token=True,
    )

    try:
        assert "private test video" in card._step_label.text().lower()
        assert card.auth_btn.text() == "Re-authenticate"
        assert card.auth_btn.isEnabled() is True
        assert card.upload_latest_btn.isEnabled() is True
    finally:
        controller.shutdown()


def test_youtube_setup_dialog_can_open(tmp_path):
    from ui.panels.youtube_upload_card import YouTubeSetupGuideDialog
    from PySide6.QtWidgets import QTextBrowser

    card, controller = make_youtube_card(
        tmp_path,
        enabled=True,
        client_json="",
        has_token=False,
    )

    try:
        dialog = YouTubeSetupGuideDialog(card)
        assert dialog.windowTitle() == "YouTube setup"
        browser = dialog.findChildren(QTextBrowser)[0]
        assert "Choose the Google file" in browser.toPlainText()
    finally:
        controller.shutdown()
