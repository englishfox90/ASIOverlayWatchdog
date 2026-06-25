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
from . import sessions

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

# Bounded queue, drop-oldest on overflow so capture never blocks. Items hold a
# full-resolution PIL copy (downscaling happens in the worker), so the cap also
# bounds worst-case memory — keep it small. At <=1 fps with a fast worker the
# queue normally holds 0-1 items; this is burst headroom, not a backlog buffer.
_QUEUE_MAXSIZE = 16
_STOP = object()      # worker shutdown sentinel


def _first_word(text):
    """Leading word of a status string ('Open (95%)' -> 'Open'), or None."""
    if text is None:
        return None
    parts = str(text).strip().split()
    return parts[0] if parts and parts[0].upper() != "N/A" else None


def _strip_pct(text):
    """Drop a trailing '(NN%)' confidence suffix ('Clear (87%)' -> 'Clear')."""
    if text is None:
        return None
    base = str(text).split("(")[0].strip()
    if not base or base.upper() == "N/A":
        return None
    return base


def _parse_pct(text):
    """Integer percent from a value like '45%' or 45, or None."""
    if text is None:
        return None
    digits = "".join(c for c in str(text) if c.isdigit())
    return int(digits) if digits else None


def _clean_na(text):
    """Trimmed string, or None for empty / 'N/A' placeholders."""
    if text is None:
        return None
    s = str(text).strip()
    return None if not s or s.upper() == "N/A" else s


def _parse_int(text):
    """Integer from a value like '1234' or '0', or None ('N/A' -> None)."""
    s = _clean_na(text)
    if s is None:
        return None
    digits = "".join(c for c in s if c.isdigit())
    return int(digits) if digits else None


class ImageLibrary:
    """Owns the library store, index, and the background save worker.

    Args:
        config_provider: Zero-arg callable returning the full config dict. Read
            on every save so toggles (enable, retention, size) take effect live.
    """

    def __init__(self, config_provider, on_frame_saved=None):
        self._config_provider = config_provider
        self._on_frame_saved = on_frame_saved
        self._queue = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        self._worker = None
        self._running = False
        self._last_prune = 0.0
        self.store = None
        self.index = None

    def set_frame_saved_callback(self, callback):
        """Register a callback fired (on the worker thread) after each frame is
        archived. Receives the inserted record dict, including its new ``id``.

        Used by the UI to live-update the Library without a manual refresh. The
        callback must not block — marshal to the GUI thread via a Qt signal.
        """
        self._on_frame_saved = callback

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        """Open the store/index and start the worker thread (idempotent)."""
        if self._running:
            return
        try:
            self.store = LibraryStore(get_library_root())
            self.index = LibraryIndex(self.store.db_path)
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
        self._offer(_STOP)  # wake the worker promptly, dropping a frame if needed
        if self._worker:
            self._worker.join(timeout=5.0)
        if self.index:
            self.index.close()
        app_logger.debug("Image library stopped")

    # -- public API --------------------------------------------------------

    def is_enabled(self):
        return bool(self._cfg().get("enabled", True))

    def api_enabled(self):
        """True when the library AND its HTTP API are both enabled."""
        cfg = self._cfg()
        return bool(cfg.get("enabled", True)) and bool(cfg.get("api_enabled", True))

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
        if not self._offer(item):
            app_logger.debug("Image library queue full — dropped oldest frame")

    def _offer(self, item):
        """Put ``item`` on the queue, dropping the oldest entry if it is full.

        Returns True if the item was queued without a drop, False otherwise.
        """
        try:
            self._queue.put_nowait(item)
            return True
        except queue.Full:
            try:
                self._queue.get_nowait()  # drop oldest
                self._queue.put_nowait(item)
            except (queue.Empty, queue.Full):
                pass
            return False

    # -- read API (used by the web endpoints and, later, the UI panel) -----

    # Hard ceiling on a single page so a remote caller can't ask for everything.
    MAX_PAGE = 500

    def list_images(self, since=None, until=None, limit=100, offset=0):
        """Return ``(total, rows)`` for archived frames, newest first.

        ``rows`` are plain dicts straight from the index (id + metadata). The
        caller is responsible for any HTTP-shaping (URLs, envelope). Returns
        ``(0, [])`` if the library isn't started.
        """
        if not self.index:
            return 0, []
        limit = max(1, min(int(limit), self.MAX_PAGE))
        offset = max(0, int(offset))
        total = self.index.count(since=since, until=until)
        rows = self.index.query(since=since, until=until, limit=limit, offset=offset)
        return total, rows

    def list_sessions(self, since=None):
        """Archived frames grouped into night sessions, newest night first.

        ``since`` is an epoch lower bound (None = all time). Returns ``[]`` when
        the library isn't started. See ``sessions.summarize_sessions``.
        """
        if not self.index:
            return []
        return sessions.summarize_sessions(self.index, since=since)

    def list_session_frames(self, start_epoch, end_epoch):
        """Full-field rows for one night, oldest first (the scrubber timeline)."""
        if not self.index:
            return []
        return self.index.range_rows(since=start_epoch, until=end_epoch)

    def image_etag(self, image_id):
        """Return an archived frame's ETag from the index, or None if unknown.

        Does no file I/O — lets a conditional request answer 304 without
        reading the JPEG off disk.
        """
        if not self.index:
            return None
        row = self.index.get(image_id)
        return self._etag(row) if row else None

    def read_image(self, image_id):
        """Return ``(jpeg_bytes, etag)`` for one archived frame, or None.

        None means the id is unknown or its backing file has gone missing.
        """
        if not self.index or not self.store:
            return None
        row = self.index.get(image_id)
        if not row:
            return None
        try:
            with open(self.store.abs_path(row["path"]), "rb") as f:
                data = f.read()
        except OSError:
            return None
        return data, self._etag(row)

    @staticmethod
    def _etag(row):
        # id + size identifies an immutable archived frame — cheap and stable.
        return f'"{row["id"]}-{row["bytes"]}"'

    # -- worker ------------------------------------------------------------

    def _run(self):
        # Reconcile orphaned rows here (not in start()) so a large library does
        # not stat every file on the main thread during app startup.
        try:
            dropped = retention.reconcile_orphans(self.index, self.store)
            if dropped:
                app_logger.info(f"Image library: dropped {dropped} orphaned row(s) at startup")
        except Exception as e:
            app_logger.error(f"Image library orphan reconcile failed: {e}")

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
        record["id"] = self.index.insert(record)
        self._notify_saved(record)
        self._maybe_prune(cfg)

    def _notify_saved(self, record):
        cb = self._on_frame_saved
        if cb is None:
            return
        try:
            cb(record)
        except Exception as e:
            app_logger.debug(f"Image library frame-saved callback failed: {e}")

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
        cfg.update(full.get("library") or {})
        return cfg

    @staticmethod
    def _extract_meta(metadata):
        """Pull a known set of display fields, tolerant of casing/absence."""
        m = metadata or {}
        ml = m.get("_ML_RESULTS") or {}

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
            # Condition signal for the timeline band. _ML_RESULTS holds the clean
            # 'Open'/'Closed' and 'Clear'/'Partly Cloudy' values; the ROOF_STATUS /
            # SKY_CONDITION tokens ("Open (95%)") are the overlay-formatted fallback.
            "roof": _first_word(ml.get("roof_status")) or _first_word(m.get("ROOF_STATUS")),
            "condition": ml.get("sky_condition") or _strip_pct(m.get("SKY_CONDITION")),
            "clouds": _parse_pct(m.get("WEATHER_CLOUDS") or m.get("clouds")),
            # Star-detection tokens (present when the observing-window gate ran it).
            "star_count": _parse_int(m.get("STAR_COUNT")),
            "seeing": _clean_na(m.get("SEEING")),
            "fwhm": _clean_na(m.get("FWHM")),
        }
