"""
Tests for the image library (services/image_resize + services/library/*).

Pure-Python: no camera, network, or ML models required.
"""
import os
import sys
import time
from datetime import datetime, timedelta

import pytest
from PIL import Image

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services.image_resize import downscale_to_jpeg
from services.library.store import LibraryStore
from services.library.index import LibraryIndex
from services.library import retention
from services.library import ImageLibrary


# --------------------------------------------------------------------------
# image_resize
# --------------------------------------------------------------------------

class TestDownscale:
    def test_caps_longest_edge_preserving_aspect(self):
        img = Image.new("RGB", (2000, 1000), (50, 60, 70))
        data, w, h = downscale_to_jpeg(img, max_edge=750, quality=85)
        assert max(w, h) == 750
        assert (w, h) == (750, 375)  # aspect ratio preserved
        assert data[:2] == b"\xff\xd8"  # JPEG SOI marker

    def test_never_upscales(self):
        img = Image.new("RGB", (300, 200), (10, 20, 30))
        _, w, h = downscale_to_jpeg(img, max_edge=750)
        assert (w, h) == (300, 200)

    def test_non_positive_cap_does_not_collapse(self):
        # A stray 0/negative max_dimension must not shrink the image to 1x1.
        img = Image.new("RGB", (800, 600), (1, 2, 3))
        for bad in (0, -100):
            _, w, h = downscale_to_jpeg(img, max_edge=bad)
            assert (w, h) == (800, 600)

    def test_flattens_non_rgb(self):
        img = Image.new("RGBA", (800, 600), (0, 0, 0, 128))
        data, w, h = downscale_to_jpeg(img, max_edge=400)
        assert (w, h) == (400, 300)
        # Decodes cleanly as a JPEG.
        from io import BytesIO
        assert Image.open(BytesIO(data)).mode == "RGB"

    def test_height_mode_caps_height(self):
        # Discord's bandwidth cap is on height, not the longest edge: a wide
        # frame keeps its width and only shrinks if its height exceeds the cap.
        img = Image.new("RGB", (2000, 1000), (50, 60, 70))
        _, w, h = downscale_to_jpeg(img, max_edge=750, mode="height")
        assert h == 750
        assert (w, h) == (1500, 750)  # aspect ratio preserved

    def test_height_mode_never_upscales(self):
        img = Image.new("RGB", (2000, 400), (10, 20, 30))
        _, w, h = downscale_to_jpeg(img, max_edge=750, mode="height")
        assert (w, h) == (2000, 400)


# --------------------------------------------------------------------------
# store
# --------------------------------------------------------------------------

class TestStore:
    def test_write_uses_dated_folder(self, temp_dir):
        store = LibraryStore(temp_dir)
        ts = datetime(2026, 6, 24, 22, 30, 15)
        rel, size = store.write(b"hello", ts)
        assert rel.startswith("2026-06-24" + os.sep)
        assert rel.endswith(".jpg")
        assert size == 5
        assert store.exists(rel)
        assert os.path.exists(store.abs_path(rel))

    def test_delete_removes_file_and_empty_folder(self, temp_dir):
        store = LibraryStore(temp_dir)
        rel, _ = store.write(b"data", datetime(2026, 6, 24, 1, 2, 3))
        folder = os.path.dirname(store.abs_path(rel))
        store.delete(rel)
        assert not store.exists(rel)
        assert not os.path.exists(folder)  # empty date folder pruned

    def test_delete_missing_is_noop(self, temp_dir):
        store = LibraryStore(temp_dir)
        store.delete(os.path.join("2026-06-24", "gone.jpg"))  # no raise


# --------------------------------------------------------------------------
# index
# --------------------------------------------------------------------------

def _rec(captured_at, size=1000, **extra):
    base = {
        "captured_at": int(captured_at),
        "path": f"p/{captured_at}.jpg",
        "width": 750, "height": 500, "bytes": size,
        "created_at": int(captured_at),
        "session": None, "exposure": None, "gain": None,
        "temp": None, "camera": None, "weather": None,
    }
    base.update(extra)
    return base


class TestIndex:
    def test_insert_and_get(self, temp_dir):
        idx = LibraryIndex(os.path.join(temp_dir, "lib.db"))
        rid = idx.insert(_rec(1000, camera="ASI294"))
        row = idx.get(rid)
        assert row["camera"] == "ASI294"
        assert row["bytes"] == 1000
        idx.close()

    def test_query_newest_first_and_pagination(self, temp_dir):
        idx = LibraryIndex(os.path.join(temp_dir, "lib.db"))
        for t in (100, 200, 300, 400):
            idx.insert(_rec(t))
        rows = idx.query(limit=2, offset=0)
        assert [r["captured_at"] for r in rows] == [400, 300]
        rows = idx.query(limit=2, offset=2)
        assert [r["captured_at"] for r in rows] == [200, 100]
        idx.close()

    def test_query_time_range(self, temp_dir):
        idx = LibraryIndex(os.path.join(temp_dir, "lib.db"))
        for t in (100, 200, 300, 400):
            idx.insert(_rec(t))
        rows = idx.query(since=200, until=300)
        assert sorted(r["captured_at"] for r in rows) == [200, 300]
        assert idx.count(since=200, until=300) == 2
        assert idx.count() == 4
        idx.close()

    def test_total_bytes(self, temp_dir):
        idx = LibraryIndex(os.path.join(temp_dir, "lib.db"))
        idx.insert(_rec(100, size=500))
        idx.insert(_rec(200, size=1500))
        assert idx.total_bytes() == 2000
        idx.close()


# --------------------------------------------------------------------------
# retention
# --------------------------------------------------------------------------

class TestRetention:
    def _setup(self, temp_dir, count, base_epoch, size=1000, step=3600):
        store = LibraryStore(temp_dir)
        idx = LibraryIndex(store.db_path)
        for i in range(count):
            ts = datetime.fromtimestamp(base_epoch + i * step)
            rel, sz = store.write(b"x" * size, ts)
            idx.insert(_rec(int(ts.timestamp()), size=sz, path=rel))
        return store, idx

    def test_age_prune_drops_old_only(self, temp_dir):
        now = time.time()
        # 5 frames, one per day going back; keep 2 days.
        store, idx = self._setup(temp_dir, 5, now - 4 * 86400, step=86400)
        res = retention.prune(idx, store, retention_days=2, max_size_gb=0, now_epoch=now)
        remaining = idx.query(limit=100)
        # Only frames at/after the cutoff survive (same int cutoff the pruner uses).
        cutoff = int(now - 2 * 86400)
        assert all(r["captured_at"] >= cutoff for r in remaining)
        assert res["removed"] >= 1
        idx.close()

    def test_size_prune_drops_oldest_until_under_cap(self, temp_dir):
        now = time.time()
        # 10 frames * 1000 bytes = ~10 KB; cap at 5 KB worth.
        store, idx = self._setup(temp_dir, 10, now - 100000, size=1000, step=100)
        cap_gb = 5000 / (1024 ** 3)
        retention.prune(idx, store, retention_days=0, max_size_gb=cap_gb, now_epoch=now)
        assert idx.total_bytes() <= 5000
        # The survivors are the newest ones.
        remaining = [r["captured_at"] for r in idx.query(limit=100)]
        assert remaining == sorted(remaining, reverse=True)
        idx.close()

    def test_reconcile_orphans(self, temp_dir):
        store, idx = self._setup(temp_dir, 3, time.time() - 1000, step=100)
        # Delete one file out from under the index.
        rows = idx.all_rows()
        store.delete(rows[0][1])  # rows are (id, path)
        dropped = retention.reconcile_orphans(idx, store)
        assert dropped == 1
        assert idx.count() == 2
        idx.close()


# --------------------------------------------------------------------------
# ImageLibrary end-to-end
# --------------------------------------------------------------------------

class TestImageLibraryEndToEnd:
    def _provider(self, root, **over):
        cfg = {
            "enabled": True, "retention_days": 7, "max_size_gb": 2.0,
            "max_dimension": 400, "jpeg_quality": 80, "api_enabled": True,
            "prune_interval_minutes": 15,
        }
        cfg.update(over)
        return lambda: {"library": cfg}

    def _wait_for_rows(self, lib, n, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if lib.index and lib.index.count() >= n:
                return True
            time.sleep(0.02)
        return False

    @staticmethod
    def _point_root_at(temp_dir, monkeypatch):
        """Redirect get_library_root (imported into two modules) to temp_dir."""
        import services.library.store as store_mod
        import services.library as lib_mod
        monkeypatch.setattr(store_mod, "get_library_root", lambda: temp_dir)
        monkeypatch.setattr(lib_mod, "get_library_root", lambda: temp_dir)

    def test_enqueue_writes_file_and_row(self, temp_dir, monkeypatch):
        self._point_root_at(temp_dir, monkeypatch)
        lib = ImageLibrary(self._provider(temp_dir))
        lib.start()
        try:
            img = Image.new("RGB", (1600, 1200), (90, 90, 90))
            lib.enqueue(img, {"camera": "ASI294", "exposure": "5.0s"})
            assert self._wait_for_rows(lib, 1), "frame was not archived in time"

            row = lib.index.query(limit=1)[0]
            assert row["camera"] == "ASI294"
            assert max(row["width"], row["height"]) == 400  # downscaled
            assert lib.store.exists(row["path"])
        finally:
            lib.stop()

    def test_disabled_does_not_archive(self, temp_dir, monkeypatch):
        self._point_root_at(temp_dir, monkeypatch)
        lib = ImageLibrary(self._provider(temp_dir, enabled=False))
        lib.start()
        try:
            lib.enqueue(Image.new("RGB", (100, 100)), {})
            time.sleep(0.2)
            assert lib.index.count() == 0
        finally:
            lib.stop()

    def test_frame_saved_callback_fires_with_id(self, temp_dir, monkeypatch):
        # The live-update path: the worker invokes the callback after insert,
        # handing over the record with its assigned id and display metadata.
        self._point_root_at(temp_dir, monkeypatch)
        seen = []
        lib = ImageLibrary(self._provider(temp_dir), on_frame_saved=seen.append)
        lib.start()
        try:
            lib.enqueue(Image.new("RGB", (300, 200)), {"camera": "ASI676"})
            assert self._wait_for_rows(lib, 1)
            deadline = time.time() + 2
            while time.time() < deadline and not seen:
                time.sleep(0.02)
            assert seen, "on_frame_saved was not invoked"
            record = seen[0]
            assert isinstance(record.get("id"), int)
            assert record["camera"] == "ASI676"
            assert record["id"] == lib.index.query(limit=1)[0]["id"]
        finally:
            lib.stop()

    def test_frame_saved_callback_errors_are_swallowed(self, temp_dir, monkeypatch):
        # A throwing callback must never break the worker / lose the frame.
        self._point_root_at(temp_dir, monkeypatch)

        def boom(_record):
            raise RuntimeError("callback blew up")

        lib = ImageLibrary(self._provider(temp_dir), on_frame_saved=boom)
        lib.start()
        try:
            lib.enqueue(Image.new("RGB", (120, 120)), {})
            assert self._wait_for_rows(lib, 1), "frame should still be archived"
        finally:
            lib.stop()


# --------------------------------------------------------------------------
# Read API (list_images / read_image / api_enabled)
# --------------------------------------------------------------------------

class TestLibraryReadAPI(TestImageLibraryEndToEnd):
    def _seeded(self, temp_dir, monkeypatch, n=3, **over):
        """Start a library and archive ``n`` frames; return the library."""
        self._point_root_at(temp_dir, monkeypatch)
        lib = ImageLibrary(self._provider(temp_dir, **over))
        lib.start()
        for i in range(n):
            lib.enqueue(Image.new("RGB", (200, 150), (i, i, i)), {"camera": f"c{i}"})
        assert self._wait_for_rows(lib, n), "frames were not archived in time"
        return lib

    def test_list_images_pagination_and_total(self, temp_dir, monkeypatch):
        lib = self._seeded(temp_dir, monkeypatch, n=3)
        try:
            total, rows = lib.list_images(limit=2, offset=0)
            assert total == 3
            assert len(rows) == 2
            # Newest first: captured_at descending.
            assert rows[0]["captured_at"] >= rows[1]["captured_at"]
        finally:
            lib.stop()

    def test_list_images_clamps_limit(self, temp_dir, monkeypatch):
        lib = self._seeded(temp_dir, monkeypatch, n=1)
        try:
            total, rows = lib.list_images(limit=10000)
            assert total == 1 and len(rows) == 1
        finally:
            lib.stop()

    def test_read_image_roundtrip(self, temp_dir, monkeypatch):
        lib = self._seeded(temp_dir, monkeypatch, n=1)
        try:
            _, rows = lib.list_images(limit=1)
            image_id = rows[0]["id"]
            result = lib.read_image(image_id)
            assert result is not None
            data, etag = result
            assert data[:2] == b"\xff\xd8"  # JPEG
            assert etag and etag.startswith('"')
            # Unknown id -> None
            assert lib.read_image(999999) is None
        finally:
            lib.stop()

    def test_image_etag_comes_from_index_without_file(self, temp_dir, monkeypatch):
        lib = self._seeded(temp_dir, monkeypatch, n=1)
        try:
            _, rows = lib.list_images(limit=1)
            row = rows[0]
            etag = lib.image_etag(row["id"])
            assert etag and etag == f'"{row["id"]}-{row["bytes"]}"'
            # ETag is still answerable after the file is gone (index-only) — this
            # is what lets a 304 skip the disk read.
            os.remove(lib.store.abs_path(row["path"]))
            assert lib.image_etag(row["id"]) == etag
            assert lib.image_etag(999999) is None
        finally:
            lib.stop()

    def test_read_image_missing_file_returns_none(self, temp_dir, monkeypatch):
        lib = self._seeded(temp_dir, monkeypatch, n=1)
        try:
            _, rows = lib.list_images(limit=1)
            row = rows[0]
            os.remove(lib.store.abs_path(row["path"]))  # file gone, row remains
            assert lib.read_image(row["id"]) is None
        finally:
            lib.stop()

    def test_api_enabled_reflects_config(self, temp_dir, monkeypatch):
        self._point_root_at(temp_dir, monkeypatch)
        on = ImageLibrary(self._provider(temp_dir))
        off = ImageLibrary(self._provider(temp_dir, api_enabled=False))
        disabled = ImageLibrary(self._provider(temp_dir, enabled=False))
        assert on.api_enabled() is True
        assert off.api_enabled() is False
        assert disabled.api_enabled() is False  # library off => API off


# --------------------------------------------------------------------------
# Query-param parsing
# --------------------------------------------------------------------------

class TestParseTimeParam:
    def test_epoch_iso_and_garbage(self):
        from services.web_library import parse_time_param
        assert parse_time_param(None) is None
        assert parse_time_param(["1700000000"]) == 1700000000
        assert parse_time_param(["1700000000.5"]) == 1700000000
        assert parse_time_param(["2023-11-14T22:13:20"]) == \
            int(datetime(2023, 11, 14, 22, 13, 20).timestamp())
        assert parse_time_param(["not-a-time"]) is None

    def test_non_finite_does_not_raise(self):
        # 'inf'/'-inf' parse as float but int() overflows — must be swallowed.
        from services.web_library import parse_time_param
        assert parse_time_param(["inf"]) is None
        assert parse_time_param(["-inf"]) is None
        assert parse_time_param(["nan"]) is None


# --------------------------------------------------------------------------
# OpenAPI spec includes library routes only when enabled
# --------------------------------------------------------------------------

class TestOpenAPILibraryRoutes:
    def test_library_routes_present_when_path_given(self):
        from services.api_docs import build_openapi_spec
        spec = build_openapi_spec(library_path="/library")
        assert "/library" in spec["paths"]
        assert "/library/image" in spec["paths"]
        assert "LibraryManifest" in spec["components"]["schemas"]

    def test_docs_html_details_endpoint_params_and_responses(self):
        from services.api_docs import build_openapi_spec, render_docs_html
        html = render_docs_html(build_openapi_spec(library_path="/library"))
        # The library endpoints are now detailed (not just the URL): query
        # params and response codes render in the HTML reference.
        assert "Query parameters" in html
        assert "since" in html and "limit" in html and "offset" in html
        assert "Responses" in html and "304" in html

    def test_library_routes_absent_when_path_none(self):
        from services.api_docs import build_openapi_spec
        spec = build_openapi_spec(library_path=None)
        assert "/library" not in spec["paths"]
        assert "LibraryManifest" not in spec["components"]["schemas"]
