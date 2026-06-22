"""
YouTube Data API upload service for completed timelapse videos.

Google client libraries are imported lazily inside methods so the rest of the
app and tests can run without those optional dependencies available.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .logger import app_logger
from .youtube_config import (
    TimelapseUploadMetadata,
    normalize_youtube_config,
    parse_tags,
    render_template,
)


REDACTION_PATTERNS = [
    (re.compile(r"(access_token|refresh_token|client_secret|code)=([^&\s]+)", re.I), r"\1=[REDACTED]"),
    (re.compile(r'"(access_token|refresh_token|client_secret)"\s*:\s*"[^"]+"', re.I), r'"\1":"[REDACTED]"'),
    (re.compile(r"https?://[^\s)]+", re.I), "[REDACTED_URL]"),
    (re.compile(r"[A-Za-z]:\\[^\s:]+(?:\\[^\s:]+)+"), "[REDACTED_PATH]"),
]


@dataclass(frozen=True)
class YouTubeUploadResult:
    success: bool
    status: str
    user_message: str
    technical_message: str = ""
    video_id: str = ""
    watch_url: str = ""
    retryable: bool = False
    resumable_uri: str = ""

    def to_status(self) -> dict:
        return {
            "provider": "youtube",
            "success": self.success,
            "status": self.status,
            "message": self.user_message,
            "video_id": self.video_id,
            "watch_url": self.watch_url,
            "retryable": self.retryable,
        }


def sanitize_exception(exc: BaseException | str) -> str:
    """Return a log-safe message for Google/OAuth errors."""
    text = str(exc)
    for pattern, replacement in REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    return text[:500]


def classify_google_error(exc: BaseException) -> YouTubeUploadResult:
    """Convert Google/OAuth exceptions into sanitized typed results."""
    name = type(exc).__name__
    detail = sanitize_exception(exc)
    lowered = detail.lower()

    if "invalid_grant" in lowered or "token has been expired or revoked" in lowered:
        return YouTubeUploadResult(
            False,
            "auth_expired",
            "YouTube authorization expired. Re-authenticate from the YouTube card.",
            detail,
            retryable=False,
        )

    status_code = getattr(getattr(exc, "resp", None), "status", None)
    if status_code in (401, 403):
        return YouTubeUploadResult(
            False,
            "auth_expired" if status_code == 401 else "quota_or_permission",
            "YouTube rejected the upload. Check authorization, quota, and channel permissions.",
            detail,
            retryable=False,
        )
    if status_code in (429, 500, 502, 503, 504):
        return YouTubeUploadResult(
            False,
            "retryable",
            "YouTube upload hit a temporary service or quota limit.",
            detail,
            retryable=True,
        )

    return YouTubeUploadResult(
        False,
        "failed",
        "YouTube upload failed. Check logs for the sanitized error category.",
        f"{name}: {detail}",
        retryable=False,
    )


class YouTubeUploadService:
    """Synchronous resumable upload client."""

    def __init__(self, auth_manager=None, sleep_fn: Callable[[float], None] | None = None):
        from .youtube_auth import YouTubeAuthManager

        self.auth_manager = auth_manager or YouTubeAuthManager()
        self.sleep_fn = sleep_fn or time.sleep

    def upload_video(
        self,
        config: dict,
        metadata: TimelapseUploadMetadata,
        *,
        resumable_uri: str = "",
        progress_callback: Optional[Callable[[dict], None]] = None,
    ) -> YouTubeUploadResult:
        """Upload one completed MP4 to YouTube."""
        cfg = normalize_youtube_config(config)
        if not os.path.isfile(metadata.path):
            return YouTubeUploadResult(False, "validation_failed", "Video file was not found.")

        try:
            creds_result = self.auth_manager.load_credentials()
            if not creds_result.success:
                return YouTubeUploadResult(
                    False,
                    creds_result.status,
                    creds_result.user_message,
                    creds_result.technical_message,
                    retryable=False,
                )

            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload

            youtube = build("youtube", "v3", credentials=creds_result.credentials)
            title = render_template(cfg["title_template"], metadata).strip()
            description = render_template(cfg["description_template"], metadata).strip()

            body = {
                "snippet": {
                    "title": title,
                    "description": description,
                    "tags": parse_tags(cfg["tags"]),
                    "categoryId": str(cfg["category_id"]),
                },
                "status": {
                    "privacyStatus": cfg["privacy_status"],
                },
            }

            media = MediaFileUpload(metadata.path, chunksize=8 * 1024 * 1024, resumable=True)
            request = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )
            if resumable_uri:
                try:
                    request.resumable_uri = resumable_uri
                except Exception:
                    pass

            response = None
            last_uri = resumable_uri or ""
            while response is None:
                status, response = request.next_chunk(num_retries=2)
                current_uri = getattr(request, "resumable_uri", "") or last_uri
                if current_uri and current_uri != last_uri:
                    last_uri = current_uri
                    if progress_callback:
                        progress_callback({"resumable_uri": last_uri})
                if status and progress_callback:
                    progress_callback({"progress": float(status.progress())})

            video_id = response.get("id", "") if isinstance(response, dict) else ""
            watch_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else ""
            return YouTubeUploadResult(
                True,
                "uploaded",
                "YouTube upload complete.",
                video_id=video_id,
                watch_url=watch_url,
                resumable_uri=last_uri,
            )
        except Exception as exc:
            result = classify_google_error(exc)
            detail = result.technical_message or result.user_message
            app_logger.warning(f"YouTube upload failed [{result.status}]: {detail}")
            return result
