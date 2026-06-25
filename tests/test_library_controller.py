"""
Tests for the Library panel's controller (ui/controllers/library_controller.py).

Only the controller is exercised (no qfluentwidgets / widgets needed) — it drives
the page-load data shaping off the library. Skipped where PySide6 is absent.
"""
import os
import sys
import time

import pytest
from PIL import Image

pytest.importorskip("PySide6")
from PySide6.QtCore import QObject  # noqa: E402

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services.library import ImageLibrary  # noqa: E402
from ui.controllers.library_controller import LibraryController, GALLERY_LIMIT  # noqa: E402


class _FakeMainWindow(QObject):
    """Minimal QObject 'main window' exposing an image_library attribute."""
    def __init__(self, library):
        super().__init__()
        self.image_library = library


def _seed_library(temp_dir, monkeypatch, n=3):
    import services.library.store as store_mod
    import services.library as lib_mod
    monkeypatch.setattr(store_mod, "get_library_root", lambda: temp_dir)
    monkeypatch.setattr(lib_mod, "get_library_root", lambda: temp_dir)

    cfg = {"enabled": True, "api_enabled": True, "max_dimension": 200,
           "jpeg_quality": 80, "retention_days": 7, "max_size_gb": 2.0,
           "prune_interval_minutes": 15}
    lib = ImageLibrary(lambda: {"library": cfg})
    lib.start()
    for i in range(n):
        lib.enqueue(Image.new("RGB", (300, 200), (i, i, i)), {"camera": f"c{i}"})
    deadline = time.time() + 5
    while time.time() < deadline and lib.index.count() < n:
        time.sleep(0.02)
    assert lib.index.count() == n
    return lib


def test_load_emits_shaped_items(temp_dir, monkeypatch):
    lib = _seed_library(temp_dir, monkeypatch, n=3)
    controller = LibraryController(_FakeMainWindow(lib))
    try:
        captured = []
        controller.page_ready.connect(lambda items, total: captured.append((items, total)))
        controller._load(since_seconds=None)  # synchronous; direct signal delivery

        assert captured, "page_ready was not emitted"
        items, total = captured[0]
        assert total == 3 and len(items) == 3
        # Newest first, each carrying decodable JPEG bytes + its metadata.
        assert items[0]["captured_at"] >= items[-1]["captured_at"]
        for it in items:
            assert it["data"][:2] == b"\xff\xd8"
            assert "camera" in it
    finally:
        lib.stop()


def test_load_respects_since_window(temp_dir, monkeypatch):
    lib = _seed_library(temp_dir, monkeypatch, n=2)
    controller = LibraryController(_FakeMainWindow(lib))
    try:
        captured = []
        controller.page_ready.connect(lambda items, total: captured.append((items, total)))
        # A future lower bound (negative lookback) excludes everything.
        controller._load(since_seconds=-3600)
        assert captured and captured[0][1] == 0 and captured[0][0] == []
    finally:
        lib.stop()


def test_read_full_roundtrip_and_missing(temp_dir, monkeypatch):
    lib = _seed_library(temp_dir, monkeypatch, n=1)
    controller = LibraryController(_FakeMainWindow(lib))
    try:
        total, rows = lib.list_images(limit=1)
        data = controller.read_full(rows[0]["id"])
        assert data and data[:2] == b"\xff\xd8"
        assert controller.read_full(999999) is None
    finally:
        lib.stop()


def test_gallery_limit_caps_page(temp_dir, monkeypatch):
    assert GALLERY_LIMIT >= 1
    lib = _seed_library(temp_dir, monkeypatch, n=3)
    controller = LibraryController(_FakeMainWindow(lib))
    try:
        captured = []
        controller.page_ready.connect(lambda items, total: captured.append((items, total)))
        controller._load(since_seconds=None)
        items, total = captured[0]
        assert len(items) <= GALLERY_LIMIT
    finally:
        lib.stop()
