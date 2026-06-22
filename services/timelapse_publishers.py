"""
Delivery coordinator for completed timelapse videos.

Discord remains best-effort on a daemon thread. YouTube uses a tracked queue
because uploads are long-running, resumable, quota-sensitive, and deduplicated.
"""
from __future__ import annotations

import os
import queue
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from .logger import app_logger
from .youtube_auth import YouTubeAuthManager
from .youtube_config import (
    TimelapseUploadMetadata,
    normalize_youtube_config,
    validate_youtube_config,
)
from .youtube_upload import YouTubeUploadResult, YouTubeUploadService, sanitize_exception
from .youtube_upload_state import YouTubeUploadStateStore


class TimelapsePublishers:
    """Coordinates all post-finalization publishing for timelapse videos."""

    def __init__(
        self,
        config,
        *,
        youtube_status_callback: Optional[Callable[[dict], None]] = None,
        youtube_state_store: Optional[YouTubeUploadStateStore] = None,
        youtube_uploader: Optional[YouTubeUploadService] = None,
        youtube_auth_manager: Optional[YouTubeAuthManager] = None,
        max_queue_size: int = 5,
    ):
        self.config = config
        self.youtube_status_callback = youtube_status_callback
        self.youtube_state = youtube_state_store or YouTubeUploadStateStore()
        self.youtube_auth = youtube_auth_manager or YouTubeAuthManager()
        self.youtube_uploader = youtube_uploader or YouTubeUploadService(auth_manager=self.youtube_auth)
        self._queue: queue.Queue = queue.Queue(maxsize=max_queue_size)
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._worker_lock = threading.Lock()

    def publish_finished(self, metadata: TimelapseUploadMetadata):
        self._post_discord_if_enabled(metadata)
        self.enqueue_youtube_upload(metadata, manual=False)

    def authenticate_youtube(self):
        cfg = normalize_youtube_config(self.config.get("youtube", {}))
        self._emit_youtube_status({"status": "authenticating", "message": "Opening browser for YouTube authentication..."})

        def _auth():
            try:
                result = self.youtube_auth.authenticate(cfg.get("client_secrets_path", ""))
            except Exception as exc:
                result = YouTubeUploadResult(
                    False,
                    "auth_failed",
                    "YouTube authentication failed.",
                    sanitize_exception(exc),
                )
            if result.success:
                app_logger.info("YouTube authentication completed")
            else:
                detail = result.technical_message or result.user_message
                app_logger.warning(f"YouTube authentication failed [{result.status}]: {detail}")
            self._emit_youtube_status(result.to_status())

        threading.Thread(target=_auth, name="YouTubeAuth", daemon=False).start()

    def enqueue_youtube_upload(self, metadata: TimelapseUploadMetadata, *, manual: bool) -> YouTubeUploadResult:
        cfg = normalize_youtube_config(self.config.get("youtube", {}))
        if not cfg.get("enabled", False):
            if manual:
                result = YouTubeUploadResult(False, "disabled", "Enable YouTube uploads first.")
                self._emit_youtube_status(result.to_status())
                return result
            return YouTubeUploadResult(False, "disabled", "YouTube uploads are disabled.")

        errors = validate_youtube_config(cfg, require_client_file=True)
        if errors:
            result = YouTubeUploadResult(False, "validation_failed", " ".join(errors))
            self._emit_youtube_status(result.to_status())
            return result

        if not self.youtube_auth.has_token():
            result = YouTubeUploadResult(False, "auth_required", "Authenticate YouTube before uploading.")
            self._emit_youtube_status(result.to_status())
            return result

        try:
            claimed, key, entry = self.youtube_state.claim(metadata.path, manual=manual)
        except OSError:
            result = YouTubeUploadResult(False, "validation_failed", "Video file was not found.")
            self._emit_youtube_status(result.to_status())
            return result

        if not claimed:
            status = entry.get("status", "duplicate")
            msg = "This timelapse is already uploaded." if status == "uploaded" else "This timelapse upload is already in progress."
            result = YouTubeUploadResult(status == "uploaded", status, msg, video_id=entry.get("video_id", ""), watch_url=entry.get("watch_url", ""))
            self._emit_youtube_status(result.to_status())
            return result

        job = {
            "key": key,
            "config": cfg,
            "metadata": metadata,
            "resumable_uri": entry.get("resumable_uri", ""),
        }
        try:
            self._ensure_worker()
            self._queue.put_nowait(job)
        except queue.Full:
            self.youtube_state.mark_failed(key, status="queue_full", error="Upload queue is full.")
            result = YouTubeUploadResult(False, "queue_full", "YouTube upload queue is full.")
            self._emit_youtube_status(result.to_status())
            return result

        result = YouTubeUploadResult(True, "queued", "YouTube upload queued.")
        self._emit_youtube_status(result.to_status())
        return result

    def shutdown(self, timeout: float = 10.0):
        self._stop_event.set()
        worker = self._worker
        if worker and worker.is_alive():
            worker.join(timeout=timeout)
            if worker.is_alive():
                app_logger.warning("YouTube upload still running; app will wait until the current upload exits")

    def _ensure_worker(self):
        with self._worker_lock:
            if self._worker and self._worker.is_alive():
                return
            self._stop_event.clear()
            self._worker = threading.Thread(target=self._worker_loop, name="YouTubeUploadQueue", daemon=False)
            self._worker.start()

    def _worker_loop(self):
        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                job = self._queue.get(timeout=0.5)
            except queue.Empty:
                if self._stop_event.is_set():
                    return
                continue

            key = job["key"]
            metadata = job["metadata"]
            self._emit_youtube_status({"provider": "youtube", "status": "uploading", "message": f"Uploading {metadata.filename} to YouTube..."})

            def _progress(fields: dict):
                if "resumable_uri" in fields:
                    self.youtube_state.update_progress(key, {"resumable_uri": fields["resumable_uri"]})

            try:
                result = self.youtube_uploader.upload_video(
                    job["config"],
                    metadata,
                    resumable_uri=job.get("resumable_uri", ""),
                    progress_callback=_progress,
                )
            except Exception as exc:
                result = YouTubeUploadResult(
                    False,
                    "failed",
                    "YouTube upload failed.",
                    sanitize_exception(exc),
                )
            if result.success:
                self.youtube_state.mark_uploaded(key, video_id=result.video_id, watch_url=result.watch_url)
            else:
                self.youtube_state.mark_failed(key, status=result.status, error=result.technical_message)
            self._capture_youtube_event(result, metadata)
            self._emit_youtube_status(result.to_status())
            self._queue.task_done()

    def _post_discord_if_enabled(self, metadata: TimelapseUploadMetadata):
        discord_cfg = self.config.get("discord", {})
        discord_delivery = discord_cfg.get("enabled", False) and discord_cfg.get("post_timelapse", False)
        if not discord_delivery:
            return

        app_logger.info("Timelapse: posting completed video to Discord")

        def _post():
            try:
                from services.discord_alerts import DiscordAlerts

                alerts = DiscordAlerts(self.config)
                max_retries = 3
                for attempt in range(1, max_retries + 1):
                    success = alerts.send_timelapse_completed(
                        metadata.path,
                        metadata.frame_count,
                        metadata.elapsed_seconds,
                    )
                    if success:
                        app_logger.info("Timelapse: Discord post sent")
                        return
                    if attempt < max_retries:
                        wait = attempt * 10
                        app_logger.warning(
                            f"Timelapse: Discord post failed (attempt {attempt}/{max_retries}), "
                            f"retrying in {wait}s"
                        )
                        time.sleep(wait)
                app_logger.error("Timelapse: Discord post failed after all retries")
            except Exception as e:
                app_logger.error(f"Timelapse: Discord post failed: {e}")

        threading.Thread(target=_post, daemon=True).start()

    def _capture_youtube_event(self, result: YouTubeUploadResult, metadata: TimelapseUploadMetadata):
        try:
            from .posthog_service import capture_event

            capture_event("youtube_timelapse_upload", {
                "success": result.success,
                "status": result.status,
                "retryable": result.retryable,
                "file_size_mb": round(metadata.file_size_bytes / (1024 * 1024), 1),
            })
        except Exception:
            pass

    def _emit_youtube_status(self, status: dict):
        if self.youtube_status_callback:
            self.youtube_status_callback(status)


def make_timelapse_metadata(path: str, frame_count: int, elapsed_seconds: int) -> TimelapseUploadMetadata:
    try:
        file_size = os.path.getsize(path)
    except OSError:
        file_size = 0
    return TimelapseUploadMetadata(
        path=path,
        frame_count=frame_count,
        elapsed_seconds=elapsed_seconds,
        file_size_bytes=file_size,
        queued_at=datetime.now(),
    )
