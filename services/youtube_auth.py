"""
OAuth helpers for YouTube uploads.

Authentication is only started from explicit UI actions. Automatic upload paths
load or refresh existing credentials but never open a browser.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from typing import Any

from .utils_paths import get_app_data_dir
from .youtube_config import UPLOAD_SCOPE
from .youtube_upload import YouTubeUploadResult, sanitize_exception


TOKEN_FILENAME = "youtube_token.json"


@dataclass(frozen=True)
class CredentialsResult:
    success: bool
    status: str
    user_message: str
    technical_message: str = ""
    credentials: Any = None


def get_token_path(storage_dir: str | None = None) -> str:
    return os.path.join(storage_dir or get_app_data_dir(), TOKEN_FILENAME)


def _atomic_write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=os.path.basename(path) + ".",
        suffix=".tmp",
        dir=os.path.dirname(path),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


class YouTubeAuthManager:
    """Loads, refreshes, and creates YouTube OAuth credentials."""

    def __init__(self, storage_dir: str | None = None):
        self.storage_dir = storage_dir
        self.token_path = get_token_path(storage_dir)

    def has_token(self) -> bool:
        return os.path.isfile(self.token_path)

    def load_credentials(self) -> CredentialsResult:
        if not os.path.isfile(self.token_path):
            return CredentialsResult(
                False,
                "auth_required",
                "Authenticate YouTube before uploading.",
            )

        try:
            from google.auth.transport.requests import Request
            from google.auth.exceptions import RefreshError
            from google.oauth2.credentials import Credentials

            creds = Credentials.from_authorized_user_file(self.token_path, [UPLOAD_SCOPE])
            if creds and creds.valid:
                return CredentialsResult(True, "authenticated", "YouTube is authenticated.", credentials=creds)
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except RefreshError as exc:
                    return CredentialsResult(
                        False,
                        "auth_expired",
                        "YouTube authorization expired. Re-authenticate from the YouTube card.",
                        sanitize_exception(exc),
                    )
                self.save_credentials(creds)
                return CredentialsResult(True, "authenticated", "YouTube is authenticated.", credentials=creds)
            return CredentialsResult(
                False,
                "auth_expired",
                "YouTube authorization expired. Re-authenticate from the YouTube card.",
            )
        except Exception as exc:
            return CredentialsResult(
                False,
                "auth_failed",
                "Could not load YouTube authorization. Re-authenticate from the YouTube card.",
                sanitize_exception(exc),
            )

    def authenticate(self, client_secrets_path: str) -> YouTubeUploadResult:
        """Run the browser-based installed app flow from a UI-triggered action."""
        if not client_secrets_path or not os.path.isfile(client_secrets_path):
            return YouTubeUploadResult(False, "validation_failed", "OAuth client JSON was not found.")

        try:
            from google_auth_oauthlib.flow import InstalledAppFlow

            flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, [UPLOAD_SCOPE])
            creds = flow.run_local_server(port=0, prompt="consent")
            self.save_credentials(creds)
            return YouTubeUploadResult(True, "authenticated", "YouTube authentication complete.")
        except Exception as exc:
            return YouTubeUploadResult(
                False,
                "auth_failed",
                "YouTube authentication failed.",
                sanitize_exception(exc),
            )

    def save_credentials(self, creds) -> None:
        payload = creds.to_json() if hasattr(creds, "to_json") else json.dumps(creds)
        _atomic_write_text(self.token_path, payload)
