"""
Library controller — loads archived thumbnails off the UI thread.

The in-app Library panel shows a gallery of the rolling image library
(``services/library``). Reading JPEGs off disk must not block the UI, so this
controller does the disk work on a background thread and hands finished pages
back to the panel via Qt signals (mirrors the timelapse/meteor controllers).
"""
import threading
import time

from PySide6.QtCore import QObject, Signal

from services.logger import app_logger

# Newest-first cap on how many frames a single gallery page loads. Each item
# carries the (Discord-size) JPEG bytes, so this also bounds transient memory.
GALLERY_LIMIT = 120

# Range filter options shown in the panel, mapped to a "since" window in seconds
# (None = no lower bound). Order is preserved in the dropdown.
RANGE_OPTIONS = [
    ("Last 24 hours", 24 * 3600),
    ("Last 3 days", 3 * 24 * 3600),
    ("Last 7 days", 7 * 24 * 3600),
    ("All", None),
]


class LibraryController(QObject):
    """Background loader for the Library panel."""

    # (items, total) — items are dicts: index row fields plus 'data' (jpeg bytes).
    page_ready = Signal(list, int)
    load_failed = Signal(str)

    def __init__(self, main_window):
        super().__init__(main_window)
        self._main_window = main_window
        self._loader = None

    @property
    def _library(self):
        return getattr(self._main_window, 'image_library', None)

    def refresh(self, since_seconds=None):
        """Load the most recent page for the given window, on a worker thread.

        ``since_seconds`` is a lookback window (None = all time). A load already
        in flight is left to finish rather than stacking another.
        """
        if self._loader and self._loader.is_alive():
            return
        self._loader = threading.Thread(
            target=self._load, args=(since_seconds,),
            name="LibraryLoader", daemon=True,
        )
        self._loader.start()

    def read_full(self, image_id):
        """Return the JPEG bytes for one frame, or None. Used by the viewer."""
        lib = self._library
        if not lib:
            return None
        result = lib.read_image(image_id)
        return result[0] if result else None

    def _load(self, since_seconds):
        lib = self._library
        if not lib:
            self.page_ready.emit([], 0)
            return
        try:
            since = int(time.time() - since_seconds) if since_seconds else None
            total, rows = lib.list_images(since=since, limit=GALLERY_LIMIT)
            items = []
            for row in rows:
                result = lib.read_image(row["id"])
                if result is None:
                    continue  # file vanished since the index row was written
                items.append({**row, "data": result[0]})
            self.page_ready.emit(items, total)
        except Exception as e:
            app_logger.error(f"Library load failed: {e}")
            self.load_failed.emit(str(e))

    def shutdown(self):
        loader = self._loader
        if loader and loader.is_alive():
            loader.join(timeout=5.0)
