"""
Atomic upload-state persistence for YouTube timelapse uploads.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from typing import Any

from .utils_paths import get_app_data_dir


STATE_FILENAME = "youtube_upload_state.json"


def get_state_path(storage_dir: str | None = None) -> str:
    return os.path.join(storage_dir or get_app_data_dir(), STATE_FILENAME)


class YouTubeUploadStateStore:
    """Thread-safe JSON-backed upload state store."""

    def __init__(self, storage_dir: str | None = None):
        self.path = get_state_path(storage_dir)
        self._lock = threading.RLock()

    def make_identity(self, video_path: str) -> dict[str, Any]:
        abs_path = os.path.normcase(os.path.abspath(video_path))
        st = os.stat(video_path)
        return {
            "path": abs_path,
            "size": int(st.st_size),
            "mtime_ns": int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))),
        }

    def make_key(self, video_path: str) -> str:
        identity = self.make_identity(video_path)
        raw = f"{identity['path']}|{identity['size']}|{identity['mtime_ns']}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            return self._load().get("uploads", {}).get(key)

    def claim(self, video_path: str, *, manual: bool = False) -> tuple[bool, str, dict[str, Any]]:
        """Mark a video as in_progress before upload starts.

        Returns (claimed, key, entry). claimed=False means an uploaded or active
        in-progress entry already exists.
        """
        with self._lock:
            data = self._load()
            uploads = data.setdefault("uploads", {})
            key = self.make_key(video_path)
            existing = uploads.get(key)
            if existing and existing.get("status") in {"uploaded", "in_progress"}:
                return False, key, existing

            identity = self.make_identity(video_path)
            entry = {
                **identity,
                "status": "in_progress",
                "manual": bool(manual),
                "claimed_at": _now(),
                "updated_at": _now(),
                "attempts": int((existing or {}).get("attempts", 0)) + 1,
                "resumable_uri": (existing or {}).get("resumable_uri", ""),
            }
            uploads[key] = entry
            self._save(data)
            return True, key, entry

    def update_progress(self, key: str, fields: dict[str, Any]) -> None:
        with self._lock:
            data = self._load()
            entry = data.setdefault("uploads", {}).setdefault(key, {})
            entry.update(fields)
            entry["updated_at"] = _now()
            self._save(data)

    def mark_uploaded(self, key: str, *, video_id: str = "", watch_url: str = "") -> None:
        self.update_progress(key, {
            "status": "uploaded",
            "video_id": video_id,
            "watch_url": watch_url,
            "uploaded_at": _now(),
            "last_error": "",
        })

    def mark_failed(self, key: str, *, status: str, error: str = "") -> None:
        self.update_progress(key, {
            "status": "failed",
            "error_status": status,
            "last_error": error[:500],
            "failed_at": _now(),
        })

    def _load(self) -> dict[str, Any]:
        if not os.path.isfile(self.path):
            return {"version": 1, "uploads": {}}
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("state is not an object")
            if not isinstance(data.get("uploads"), dict):
                data["uploads"] = {}
            data["version"] = 1
            return data
        except Exception:
            return {"version": 1, "uploads": {}}

    def _save(self, data: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=os.path.basename(self.path) + ".",
            suffix=".tmp",
            dir=os.path.dirname(self.path),
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, self.path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
