"""
Library controller — loads archived frames off the UI thread.

Backs the three-screen Library flow (session list → night scrubber → single
image). Reading JPEGs off disk must not block the UI, so every load runs on a
background thread and hands results back via Qt signals (mirrors the
timelapse/meteor controllers).

Three load paths, each on its own worker:
  • ``load_sessions``        — night summaries + a cover thumbnail per night.
  • ``load_session_frames``  — one night's frame timeline + a sampled filmstrip.
  • ``request_frame``        — the single frame under the scrubber playhead,
                               coalesced so a fast drag only loads the latest.
"""
import threading
import time

from PySide6.QtCore import QObject, Signal

from services.logger import app_logger

# Newest-first cap on how many frames the legacy flat page loads. Each item
# carries the (Discord-size) JPEG bytes, so this also bounds transient memory.
GALLERY_LIMIT = 120

# Thumbnails sampled across a night for the scrubber filmstrip. Evenly spaced,
# so the strip previews the whole session without loading every frame.
FILMSTRIP_SAMPLES = 14


class LibraryController(QObject):
    """Background loader for the Library panel."""

    # Legacy flat gallery (kept for the web/test surface): (items, total).
    page_ready = Signal(list, int)
    load_failed = Signal(str)

    # Three-screen flow.
    sessions_ready = Signal(list)     # list of night summaries (+ 'cover_data')
    frames_ready = Signal(object)     # {'session', 'frames', 'filmstrip'}
    frame_ready = Signal(int, object)  # (image_id, jpeg bytes) for the playhead

    def __init__(self, main_window):
        super().__init__(main_window)
        self._main_window = main_window
        self._loader = None

        # Coalescing single-frame loader (scrubber). One persistent worker reads
        # whichever frame was most recently requested and drops the rest.
        self._frame_lock = threading.Lock()
        self._frame_event = threading.Event()
        self._pending_frame_id = None
        self._frame_worker = None
        self._frame_stop = False

    @property
    def _library(self):
        return getattr(self._main_window, 'image_library', None)

    # -- legacy flat page (unused by the new UI, kept for tests/back-compat) --

    def refresh(self, since_seconds=None):
        """Load the most recent flat page for the given window, on a worker."""
        if self._loader and self._loader.is_alive():
            return
        self._loader = threading.Thread(
            target=self._load, args=(since_seconds,),
            name="LibraryLoader", daemon=True,
        )
        self._loader.start()

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

    # -- shared read helper -------------------------------------------------

    def read_full(self, image_id):
        """Return the JPEG bytes for one frame, or None. Used by the viewer."""
        lib = self._library
        if not lib:
            return None
        result = lib.read_image(image_id)
        return result[0] if result else None

    # -- session list -------------------------------------------------------

    def load_sessions(self, since_seconds=None):
        """Load night summaries (+ a cover thumbnail each) on a worker thread."""
        if self._loader and self._loader.is_alive():
            return
        self._loader = threading.Thread(
            target=self._load_sessions, args=(since_seconds,),
            name="LibrarySessionLoader", daemon=True,
        )
        self._loader.start()

    def _load_sessions(self, since_seconds):
        lib = self._library
        if not lib:
            self.sessions_ready.emit([])
            return
        try:
            since = int(time.time() - since_seconds) if since_seconds else None
            sessions = lib.list_sessions(since=since)
            for s in sessions:
                result = lib.read_image(s.get("cover_id"))
                s["cover_data"] = result[0] if result else None
            self.sessions_ready.emit(sessions)
        except Exception as e:
            app_logger.error(f"Library session load failed: {e}")
            self.load_failed.emit(str(e))

    # -- one night's timeline ----------------------------------------------

    def load_session_frames(self, session):
        """Load a night's frame rows + a sampled filmstrip on a worker thread."""
        loader = threading.Thread(
            target=self._load_session_frames, args=(session,),
            name="LibraryNightLoader", daemon=True,
        )
        loader.start()

    def _load_session_frames(self, session):
        lib = self._library
        if not lib:
            self.frames_ready.emit({"session": session, "frames": [], "filmstrip": []})
            return
        try:
            frames = lib.list_session_frames(session["start_epoch"], session["end_epoch"])
            filmstrip = []
            for idx in _sample_indices(len(frames), FILMSTRIP_SAMPLES):
                result = lib.read_image(frames[idx]["id"])
                if result is not None:
                    filmstrip.append((idx, result[0]))
            self.frames_ready.emit(
                {"session": session, "frames": frames, "filmstrip": filmstrip}
            )
        except Exception as e:
            app_logger.error(f"Library night load failed: {e}")
            self.load_failed.emit(str(e))

    # -- scrubber playhead (coalesced) -------------------------------------

    def request_frame(self, image_id):
        """Request the frame under the playhead. Coalesces to the latest id."""
        with self._frame_lock:
            self._pending_frame_id = image_id
            if self._frame_worker is None or not self._frame_worker.is_alive():
                self._frame_stop = False
                self._frame_worker = threading.Thread(
                    target=self._frame_loop, name="LibraryFrameLoader", daemon=True,
                )
                self._frame_worker.start()
        self._frame_event.set()

    def _frame_loop(self):
        while not self._frame_stop:
            self._frame_event.wait(timeout=1.0)
            self._frame_event.clear()
            while not self._frame_stop:
                with self._frame_lock:
                    fid = self._pending_frame_id
                    self._pending_frame_id = None
                if fid is None:
                    break
                data = self.read_full(fid)
                if data is not None:
                    self.frame_ready.emit(fid, data)

    # -- lifecycle ----------------------------------------------------------

    def shutdown(self):
        self._frame_stop = True
        self._frame_event.set()
        loader = self._loader
        if loader and loader.is_alive():
            loader.join(timeout=5.0)
        worker = self._frame_worker
        if worker and worker.is_alive():
            worker.join(timeout=2.0)


def _sample_indices(count, samples):
    """Up to ``samples`` evenly-spaced indices over ``range(count)``."""
    if count <= 0:
        return []
    if count <= samples:
        return list(range(count))
    step = (count - 1) / (samples - 1)
    return sorted({round(i * step) for i in range(samples)})
