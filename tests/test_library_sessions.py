"""
Tests for image-library session grouping + condition status
(services/library/sessions.py) and the roof/condition/clouds persistence path.

Pure-Python: no camera, network, ML models, or Qt required.
"""
import os
import sys
from datetime import datetime, timedelta

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services.library import sessions as S
from services.library.index import LibraryIndex
from services.library import ImageLibrary


def _epoch(y, mo, d, h, mi=0):
    return int(datetime(y, mo, d, h, mi).timestamp())


# --------------------------------------------------------------------------
# night_key — noon cutoff keeps an evening-to-morning run on one date
# --------------------------------------------------------------------------

class TestNightKey:
    def test_evening_belongs_to_same_date(self):
        assert S.night_key(_epoch(2026, 6, 24, 21, 0)) == "2026-06-24"

    def test_after_midnight_belongs_to_previous_date(self):
        assert S.night_key(_epoch(2026, 6, 25, 3, 0)) == "2026-06-24"

    def test_afternoon_starts_a_new_night(self):
        assert S.night_key(_epoch(2026, 6, 25, 13, 0)) == "2026-06-25"


# --------------------------------------------------------------------------
# frame_status — green / amber / red rule
# --------------------------------------------------------------------------

class TestFrameStatus:
    def test_clear_and_roof_open_is_clear(self):
        assert S.frame_status("Open", "Clear", 0) == S.STATUS_CLEAR

    def test_roof_open_not_clear_is_cloudy(self):
        assert S.frame_status("Open", "Partly Cloudy", 80) == S.STATUS_CLOUDY

    def test_roof_closed_is_closed_regardless_of_sky(self):
        assert S.frame_status("Closed", "Clear", 0) == S.STATUS_CLOSED

    def test_weather_clouds_fallback_when_sky_unknown(self):
        assert S.frame_status("Open", None, 10) == S.STATUS_CLEAR
        assert S.frame_status("Open", None, 90) == S.STATUS_CLOUDY

    def test_no_signal_is_unknown(self):
        assert S.frame_status(None, None, None) == S.STATUS_UNKNOWN


# --------------------------------------------------------------------------
# gaps + band segments
# --------------------------------------------------------------------------

class TestGapsAndSegments:
    def _rows(self):
        base = _epoch(2026, 6, 24, 21, 0)
        return [
            {"id": 1, "captured_at": base, "roof": "Open", "condition": "Clear", "clouds": 0},
            {"id": 2, "captured_at": base + 10, "roof": "Open", "condition": "Clear", "clouds": 0},
            # 30-minute capture gap here
            {"id": 3, "captured_at": base + 1810, "roof": "Closed", "condition": None, "clouds": None},
        ]

    def test_detect_gaps_finds_the_break(self):
        gaps = S.detect_gaps(self._rows())
        assert len(gaps) == 1
        assert gaps[0]["before_id"] == 2 and gaps[0]["after_id"] == 3
        assert gaps[0]["seconds"] == 1800

    def test_status_segments_cover_full_span_and_mark_gap(self):
        rows = self._rows()
        segs = S.status_segments(rows, rows[0]["captured_at"], rows[-1]["captured_at"])
        assert segs[0][0] == 0.0 and segs[-1][1] == 1.0  # span fully covered
        assert any(s[2] == S.STATUS_GAP for s in segs)
        assert any(s[2] == S.STATUS_CLOSED for s in segs)


# --------------------------------------------------------------------------
# summarize_sessions over a fake index
# --------------------------------------------------------------------------

class _FakeIndex:
    def __init__(self, rows):
        self._rows = rows

    def brief_rows(self, since=None):
        rows = self._rows
        if since is not None:
            rows = [r for r in rows if r["captured_at"] >= since]
        return sorted(rows, key=lambda r: r["captured_at"])


class TestSummarize:
    def _index(self):
        n1 = _epoch(2026, 6, 23, 21, 0)
        n2 = _epoch(2026, 6, 24, 22, 0)
        rows = [
            {"id": 1, "captured_at": n1, "temp": "12.0°C", "roof": "Open", "condition": "Clear", "clouds": 0},
            {"id": 2, "captured_at": n1 + 60, "temp": "11.0°C", "roof": "Open", "condition": "Clear", "clouds": 0},
            {"id": 3, "captured_at": n2, "temp": "14.0°C", "roof": "Open", "condition": "Overcast", "clouds": 95},
            {"id": 4, "captured_at": n2 + 60, "temp": "14.5°C", "roof": "Closed", "condition": None, "clouds": None},
        ]
        return _FakeIndex(rows)

    def test_groups_by_night_newest_first(self):
        result = S.summarize_sessions(self._index())
        assert [s["key"] for s in result] == ["2026-06-24", "2026-06-23"]

    def test_summary_fields(self):
        result = S.summarize_sessions(self._index())
        latest = result[0]
        assert latest["frame_count"] == 2
        assert latest["roof_closed"] is True
        assert latest["min_temp_c"] == 14.0
        assert latest["band"]  # has condition segments
        first = result[1]
        assert first["clear_pct"] == 100


# --------------------------------------------------------------------------
# index migration + metadata extraction
# --------------------------------------------------------------------------

class TestPersistence:
    def test_migration_adds_columns_to_old_db(self, tmp_path):
        db = str(tmp_path / "library.db")
        # Create a DB with the pre-condition schema (no roof/condition/clouds).
        import sqlite3
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE images (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "captured_at INTEGER NOT NULL, path TEXT NOT NULL, bytes INTEGER NOT NULL, "
            "created_at INTEGER NOT NULL)"
        )
        conn.commit()
        conn.close()

        idx = LibraryIndex(db)  # opening should ALTER the new columns in
        cols = {r["name"] for r in idx._conn.execute("PRAGMA table_info(images)").fetchall()}
        assert {"roof", "condition", "clouds"} <= cols
        idx.close()

    def test_extract_meta_pulls_roof_condition_clouds(self):
        meta = {
            "_ML_RESULTS": {"roof_status": "Open", "sky_condition": "Partly Cloudy"},
            "ROOF_STATUS": "Open (95%)",
            "SKY_CONDITION": "Partly Cloudy (72%)",
            "WEATHER_CLOUDS": "45%",
        }
        out = ImageLibrary._extract_meta(meta)
        assert out["roof"] == "Open"
        assert out["condition"] == "Partly Cloudy"
        assert out["clouds"] == 45

    def test_extract_meta_handles_na_and_absence(self):
        out = ImageLibrary._extract_meta({"ROOF_STATUS": "N/A", "SKY_CONDITION": "N/A"})
        assert out["roof"] is None
        assert out["condition"] is None
        assert out["clouds"] is None
