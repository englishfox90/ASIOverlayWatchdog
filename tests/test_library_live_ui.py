"""
Tests for the Library panel's live-update fixes:
  - Scrubber filmstrip pixmaps are pre-scaled at insertion (not on every paint).
  - LibraryPanel's live session-list refresh throttles (arms once) rather than
    debounces (restarts on every frame).
  - NightView buffers frame_archived payloads that arrive mid-load and replays
    them, deduped, once the load lands.
  - NightView clears the previous night's scrubber/event list when a session
    loads with zero frames.

Constructs real widgets against an offscreen QApplication, mirroring the
existing pattern in tests/test_overlay_panel.py and tests/test_library_controller.py
(no display needed; QT_QPA_PLATFORM=offscreen).
"""
import os
from datetime import datetime
from io import BytesIO

import pytest

pytest.importorskip("PySide6")
from PIL import Image  # noqa: E402

from services.library import sessions as S  # noqa: E402

# A fixed "night" to anchor frame/session fixtures — append_frame() matches
# a live record's night_key() against the session's stored key, so tests that
# exercise that path need frames whose captured_at actually falls in the
# session's declared night (arbitrary epochs like 1000/1010 land in 1970 and
# never match a "2026-07-03" session key).
_NIGHT_EPOCH = int(datetime(2026, 7, 3, 21, 0).timestamp())
_NIGHT_KEY = S.night_key(_NIGHT_EPOCH)


@pytest.fixture(scope="module")
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _jpeg_bytes(w=64, h=48, color=(10, 20, 30)):
    buf = BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="JPEG")
    return buf.getvalue()


def _frame(id_, offset_seconds=0, **kw):
    """A frame captured ``offset_seconds`` into the shared test night."""
    d = {"id": id_, "captured_at": _NIGHT_EPOCH + offset_seconds, "roof": "Open",
         "condition": "Clear", "clouds": 0}
    d.update(kw)
    return d


def _session(key=None, **kw):
    d = {"key": key or _NIGHT_KEY, "gaps": [], "max_gap_seconds": 0}
    d.update(kw)
    return d


# ---------------------------------------------------------------------------
# Fix 1: filmstrip pixmaps pre-scaled at insertion, not on every paint
# ---------------------------------------------------------------------------

class TestScrubberPreScale:
    def test_set_data_prescales_to_strip_height(self, qt_app):
        from ui.panels.library_scrubber import Scrubber, _STRIP_H
        scrubber = Scrubber()
        scrubber.set_data(
            [_frame(1, 1000), _frame(2, 1010)],
            [(0, _jpeg_bytes(200, 150)), (1, _jpeg_bytes(80, 80))],
            [],
        )
        assert len(scrubber._film) == 2
        for _idx, pix in scrubber._film:
            assert pix.height() == _STRIP_H
            # A full 200x150 (or 80x80) decode would be far larger — pixmap
            # is the pre-scaled on-screen size, not the source resolution.
            assert pix.width() <= 200

    def test_add_live_thumb_prescales_to_strip_height(self, qt_app):
        from ui.panels.library_scrubber import Scrubber, _STRIP_H
        scrubber = Scrubber()
        scrubber.add_live_thumb(0, _jpeg_bytes(300, 300))
        assert len(scrubber._film) == 1
        _idx, pix = scrubber._film[0]
        assert pix.height() == _STRIP_H

    def test_add_live_thumb_ignores_undecodable_bytes(self, qt_app):
        from ui.panels.library_scrubber import Scrubber
        scrubber = Scrubber()
        scrubber.add_live_thumb(0, b"not a jpeg")
        assert scrubber._film == []


# ---------------------------------------------------------------------------
# Fix 2: live session-list refresh throttles instead of debouncing
# ---------------------------------------------------------------------------

class TestLiveSessionRefreshThrottle:
    def test_burst_of_frames_arms_the_timer_once(self, qt_app, monkeypatch):
        from PySide6.QtCore import QTimer
        from ui.panels.library_panel import LibraryPanel

        starts = []
        orig_start = QTimer.start

        def counting_start(self, *a, **kw):
            starts.append(self)
            return orig_start(self, *a, **kw)

        monkeypatch.setattr(QTimer, "start", counting_start)

        panel = LibraryPanel()
        panel.on_frame_archived({"id": 1, "captured_at": 1000})
        panel.on_frame_archived({"id": 2, "captured_at": 1001})
        panel.on_frame_archived({"id": 3, "captured_at": 1002})

        # A debounce (restart-on-every-call) would call start() 3 times; the
        # throttle only arms once for the whole burst.
        assert len(starts) == 1
        assert panel._live_timer.isActive()

    def test_new_burst_after_timer_fires_arms_again(self, qt_app, monkeypatch):
        from PySide6.QtCore import QTimer
        from ui.panels.library_panel import LibraryPanel

        panel = LibraryPanel()
        panel.on_frame_archived({"id": 1, "captured_at": 1000})
        assert panel._live_timer.isActive()

        # Force the timer to have already fired (simulates the 2s window
        # elapsing) without waiting in real time.
        panel._live_timer.stop()
        assert not panel._live_timer.isActive()

        starts = []
        orig_start = QTimer.start

        def counting_start(self, *a, **kw):
            starts.append(self)
            return orig_start(self, *a, **kw)

        monkeypatch.setattr(QTimer, "start", counting_start)
        panel.on_frame_archived({"id": 2, "captured_at": 2000})
        assert len(starts) == 1
        assert panel._live_timer.isActive()


# ---------------------------------------------------------------------------
# Fix 4: frames archived mid-load are buffered and replayed (deduped)
# ---------------------------------------------------------------------------

class TestNightViewMidLoadBuffering:
    def test_frame_archived_during_load_is_not_dropped(self, qt_app):
        from ui.panels.library_night_view import NightView

        view = NightView()
        session = _session()
        view.begin_load(session)
        assert view._loading is True

        # A frame arrives (via the live callback) while the disk load is
        # still in flight — before this fix, the empty-_frames guard in
        # append_frame silently dropped it.
        live_record = _frame(5, 1050)
        view.append_frame(live_record)
        assert view._frames == []          # not appended yet — buffered
        assert 5 in view._pending_live

        # The load lands: two frames from disk, not including id 5.
        view.set_frames({
            "session": session,
            "frames": [_frame(1, 1000), _frame(2, 1010)],
            "filmstrip": [],
            "meteors": [],
        })

        assert view._loading is False
        assert 5 in view._id_index
        assert len(view._frames) == 3
        assert view._pending_live == {}

    def test_replay_dedupes_against_frames_the_load_already_picked_up(self, qt_app):
        from ui.panels.library_night_view import NightView

        view = NightView()
        session = _session()
        view.begin_load(session)

        # This frame lands on disk before the query runs, so the load result
        # already includes it — the buffered copy must not be double-appended.
        view.append_frame(_frame(2, 1010))
        # This one truly is new relative to the load result.
        view.append_frame(_frame(6, 1060))

        view.set_frames({
            "session": session,
            "frames": [_frame(1, 1000), _frame(2, 1010)],
            "filmstrip": [],
            "meteors": [],
        })

        assert len(view._frames) == 3  # not 4 — id 2 wasn't duplicated
        ids = [f["id"] for f in view._frames]
        assert ids.count(2) == 1
        assert 6 in ids

    def test_frame_for_a_different_night_is_dropped_not_buffered(self, qt_app):
        from ui.panels.library_night_view import NightView

        view = NightView()
        session = _session()
        view.begin_load(session)

        # 30 days earlier — unambiguously a different night than the session.
        other_night_record = _frame(9, -30 * 24 * 3600)
        view.append_frame(other_night_record)
        assert view._pending_live == {}


# ---------------------------------------------------------------------------
# Fix 3: opening a night with zero frames clears the previous night's UI
# ---------------------------------------------------------------------------

class TestNightViewEmptyNightClearing:
    def test_empty_load_clears_scrubber_and_event_list(self, qt_app):
        from ui.panels.library_night_view import NightView

        view = NightView()
        first = _session(key="2026-07-01")
        view.begin_load(first)
        view.set_frames({
            "session": first,
            "frames": [_frame(1, 1000, roof="Closed", condition=None, clouds=None)],
            "filmstrip": [],
            "meteors": [],
        })
        assert view.scrubber.frame_count() == 1
        assert view.events_box.count() >= 1

        # Pruned between listing and clicking: the second night loads empty.
        second = _session(key="2026-07-02")
        view.begin_load(second)
        view.set_frames({"session": second, "frames": [], "filmstrip": [], "meteors": []})

        assert view.scrubber.frame_count() == 0
        assert view.events_box.count() == 1
        placeholder = view.events_box.itemAt(0).widget()
        assert placeholder.text() == "No events tonight"
