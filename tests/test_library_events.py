"""
Tests for the library night-events timeline (services/library/events.py):
roof transitions, meteor matching, and the merged timeline.

Pure-Python: no camera, network, ML models, or Qt required.
"""
import json
import os
import sys
from datetime import datetime

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services.library import events as E


def _epoch(y, mo, d, h, mi=0, s=0):
    return int(datetime(y, mo, d, h, mi, s).timestamp())


class TestRoofTransitions:
    def _rows(self):
        base = _epoch(2026, 6, 24, 20, 0)
        return [
            {"id": 1, "captured_at": base, "roof": "Closed"},
            {"id": 2, "captured_at": base + 600, "roof": "Open"},
            {"id": 3, "captured_at": base + 1200, "roof": "Open"},
            {"id": 4, "captured_at": base + 1800, "roof": "Closed"},
        ]

    def test_emits_one_event_per_state_change(self):
        evts = E.roof_transitions(self._rows())
        assert [e["type"] for e in evts] == [E.EVENT_ROOF_OPEN, E.EVENT_ROOF_CLOSED]
        assert [e["image_id"] for e in evts] == [2, 4]

    def test_no_events_when_roof_steady(self):
        rows = [{"id": i, "captured_at": i, "roof": "Open"} for i in range(3)]
        assert E.roof_transitions(rows) == []

    def test_skips_frames_with_no_roof_signal(self):
        base = _epoch(2026, 6, 24, 20, 0)
        rows = [
            {"id": 1, "captured_at": base, "roof": "Open"},
            {"id": 2, "captured_at": base + 60, "roof": None},
            {"id": 3, "captured_at": base + 120, "roof": "Closed"},
        ]
        evts = E.roof_transitions(rows)
        assert len(evts) == 1
        assert evts[0]["type"] == E.EVENT_ROOF_CLOSED and evts[0]["image_id"] == 3


class TestMeteorHits:
    def _rows(self):
        base = _epoch(2026, 6, 24, 23, 0)
        return [
            {"id": 10, "captured_at": base},
            {"id": 11, "captured_at": base + 600},
            {"id": 12, "captured_at": base + 1200},
        ]

    def _write_log(self, path, entries):
        with open(path, "w", encoding="utf-8") as fh:
            for e in entries:
                fh.write(json.dumps(e) + "\n")

    def test_matches_meteor_to_nearest_frame(self, tmp_path):
        rows = self._rows()
        hit_time = rows[1]["captured_at"] + 5  # just after frame 11
        log = str(tmp_path / "meteors.jsonl")
        self._write_log(log, [
            {"timestamp": _iso_from_epoch(hit_time), "count": 1, "detections": [{}]},
        ])
        evts = E.meteor_hits(rows, log)
        assert len(evts) == 1
        assert evts[0]["type"] == E.EVENT_METEOR
        assert evts[0]["image_id"] == 11
        assert evts[0]["count"] == 1

    def test_drops_zero_count_entries(self, tmp_path):
        rows = self._rows()
        log = str(tmp_path / "meteors.jsonl")
        self._write_log(log, [
            {"timestamp": _iso_from_epoch(rows[0]["captured_at"]), "count": 0,
             "detections": []},
            {"event": "confirmation", "id": "abc"},  # free-form, no detections
        ])
        assert E.meteor_hits(rows, log) == []

    def test_drops_hits_outside_the_night(self, tmp_path):
        rows = self._rows()
        far = rows[-1]["captured_at"] + 10_000
        log = str(tmp_path / "meteors.jsonl")
        self._write_log(log, [
            {"timestamp": _iso_from_epoch(far), "count": 1, "detections": [{}]},
        ])
        assert E.meteor_hits(rows, log) == []

    def test_missing_log_is_empty(self, tmp_path):
        rows = self._rows()
        assert E.meteor_hits(rows, str(tmp_path / "nope.jsonl")) == []


class TestBuildTimeline:
    def test_merges_and_sorts_by_time(self):
        base = _epoch(2026, 6, 24, 21, 0)
        rows = [
            {"id": 1, "captured_at": base, "roof": "Closed"},
            {"id": 2, "captured_at": base + 600, "roof": "Open"},
        ]
        gaps = [{"at": base + 300, "seconds": 4200, "after_id": 2}]
        meteors = [{"type": E.EVENT_METEOR, "at": base + 900, "image_id": 2, "count": 2}]
        timeline = E.build_timeline(rows, gaps, meteors)
        assert [e["type"] for e in timeline] == [
            E.EVENT_GAP, E.EVENT_ROOF_OPEN, E.EVENT_METEOR,
        ]
        assert [e["at"] for e in timeline] == sorted(e["at"] for e in timeline)


def _iso_from_epoch(epoch):
    return datetime.fromtimestamp(epoch).isoformat(timespec="seconds")
