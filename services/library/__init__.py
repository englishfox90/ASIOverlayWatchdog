"""
Image library — a rolling, on-disk store of downscaled capture frames.

Every processed frame can be archived as a small (Discord-size) JPEG into a
date-partitioned folder, indexed in SQLite, and retained for a bounded window
(N days AND a max size). The store is the shared backing for the in-app Library
panel and the web/HTTP ``/library`` endpoints.

The public surface is :class:`ImageLibrary`. Saves go through a bounded
background queue so the capture pipeline never blocks: callers ``enqueue()`` and
return immediately while a worker thread does the resize / write / insert /
prune off the hot path (mirrors the ``app_logger`` queue pattern). Cadence
varies from 5-15 s long exposures at night to ~1 fps daytime auto-exposure; the
queue absorbs the bursts and drops oldest-queued frames rather than stall.
"""
import queue
import threading
import time
from datetime import datetime

from ..logger import app_logger
from ..image_resize import downscale_to_jpeg
from .store import LibraryStore, get_library_root
from .index import LibraryIndex
from . import retention

# Defaults mirror the ``library`` config block (and the Discord image size).
DEFAULTS = {
    "enabled": True,
    "retention_days": 7,
    "max_size_gb": 2.0,
    "max_dimension": 750,
    "jpeg_quality": 85,
    "api_enabled": True,
    "prune_interval_minutes": 15,
}

_QUEUE_MAXSIZE = 200  # bounded; drop-oldest on overflow so capture never blocks
_STOP = object()      # worker shutdown sentinel


class ImageLibrary:
    """Owns the library store, index, and the background save worker.

    Args:
        config_provider: Zero-arg callable returning the full config dict. Read
            on every save so toggles (enable, retention, size) take effect live.
    """

    def __init__(self, config_provider):
        self._config_provider = config_provider
        self._queue = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        self._worker = None
        self._running = False
        self._last_prune = 0.0
        self.store = None
        self.index = None

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        """Open the store/index and start the worker thread (idempotent)."""
        if self._running:
            return
        try:
            self.store = LibraryStore(get_library_root())
            self.index = LibraryIndex(self.store.db_path)
            dropped = retention.reconcile_orphans(self.index, self.store)
            if dropped:
                app_logger.info(f"Image library: dropped {dropped} orphaned row(s) at startup")
        except Exception as e:
            app_logger.error(f"Image library failed to start: {e}")
            self.store = None
            self.index = None
            return

        self._running = True
        self._worker = threading.Thread(
            target=self._run, name="ImageLibraryWorker", daemon=True
        )
        self._worker.start()
        app_logger.info(f"Image library started ({self.store.root})")

    def stop(self):
        """Stop the worker (drains nothing) and close the index."""
        if not self._running:
            return
        self._running = False
        try:
            self._queue.put_nowait(_STOP)
        except queue.Full:
            # Make room for the sentinel so the worker wakes promptly.
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(_STOP)
            except queue.Full:
                pass
        if self._worker:
            self._worker.join(timeout=5.0)
        if self.index:
            self.index.close()
        app_logger.debug("Image library stopped")

    # -- public API --------------------------------------------------------

    def is_enabled(self):
        return bool(self._cfg().get("enabled", True))

    def enqueue(self, pil_image, metadata=None):
        """Queue a frame for archiving. Non-blocking; returns immediately.

        The image is copied so the worker is decoupled from any later mutation
        by the caller. If the queue is full the oldest pending frame is dropped.
        """
        if not self._running or not self.is_enabled():
            return
        try:
            item = (pil_image.copy(), dict(metadata or {}), datetime.now())
        except Exception as e:
            app_logger.debug(f"Image library enqueue skipped (copy failed): {e}")
            return
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            try:
                self._queue.get_nowait()  # drop oldest
                self._queue.put_nowait(item)
                app_logger.debug("Image library queue full — dropped oldest frame")
            except (queue.Empty, queue.Full):
                pass

    # -- worker ------------------------------------------------------------

    def _run(self):
        while True:
            item = self._queue.get()
            if item is _STOP:
                break
            try:
                self._save(*item)
            except Exception as e:
                app_logger.error(f"Image library save failed: {e}")

    def _save(self, image, metadata, captured_at):
        cfg = self._cfg()
        max_dim = int(cfg.get("max_dimension", 750))
        quality = int(cfg.get("jpeg_quality", 85))

        jpeg_bytes, width, height = downscale_to_jpeg(image, max_dim, quality)
        rel_path, size = self.store.write(jpeg_bytes, captured_at)

        record = {
            "captured_at": int(captured_at.timestamp()),
            "path": rel_path,
            "width": width,
            "height": height,
            "bytes": size,
            "created_at": int(time.time()),
            **self._extract_meta(metadata),
        }
        self.index.insert(record)
        self._maybe_prune(cfg)

    def _maybe_prune(self, cfg):
        interval = max(1, int(cfg.get("prune_interval_minutes", 15))) * 60
        now = time.time()
        if now - self._last_prune < interval:
            return
        self._last_prune = now
        try:
            result = retention.prune(
                self.index,
                self.store,
                retention_days=cfg.get("retention_days", 7),
                max_size_gb=cfg.get("max_size_gb", 2.0),
                now_epoch=now,
            )
            if result["removed"]:
                freed_mb = result["freed_bytes"] / (1024 * 1024)
                app_logger.info(
                    f"Image library pruned {result['removed']} frame(s), "
                    f"freed {freed_mb:.1f} MB"
                )
        except Exception as e:
            app_logger.error(f"Image library prune failed: {e}")

    # -- helpers -----------------------------------------------------------

    def _cfg(self):
        try:
            full = self._config_provider() or {}
        except Exception:
            full = {}
        cfg = dict(DEFAULTS)
        cfg.update(full.get("library", {}) or {})
        return cfg

    @staticmethod
    def _extract_meta(metadata):
        """Pull a known set of display fields, tolerant of casing/absence."""
        m = metadata or {}

        def pick(*keys):
            for k in keys:
                v = m.get(k)
                if v is not None:
                    return str(v)
            return None

        return {
            "session": pick("session", "SESSION"),
            "exposure": pick("exposure", "EXPOSURE"),
            "gain": pick("gain", "GAIN"),
            "temp": pick("temp", "TEMP", "temperature"),
            "camera": pick("camera", "CAMERA"),
            "weather": pick("weather", "WEATHER"),
        }
