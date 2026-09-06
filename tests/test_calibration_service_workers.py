"""
Worker lifetime and refinement pacing in CalibrationService.

Two production faults are pinned here:

* Workers used to be created with ``parent=self``. Shiboken then kept every
  past QThread alive as a child of the long-lived service, and each one pinned
  its payload — a deep copy of the 60-frame detection buffer (each frame
  carrying the whole above-horizon catalogue) or a full-resolution image copy.
  Ten refinements retained 477 MB; a night of them reached ~2.2 GB.
* The refinement cooldown was measured from the *trigger*, so with runs
  lasting 40 s to several minutes refinement occupied about half of every
  night, and a seed that could not be refined failed identically 33 times in
  a row with no back-off.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from services.allsky import calibration_service as cs
from services.allsky import calibration_workers as cw
from services.allsky.fisheye import FisheyeModel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _model(rms: float = 5.0, n_matches: int = 500, n_images: int = 20,
           span_minutes: float = 40.0) -> FisheyeModel:
    return FisheyeModel(
        cx=960.0, cy=540.0, a1=600.0,
        rms_residual=rms, n_matches=n_matches,
        n_images=n_images, span_minutes=span_minutes,
        calibrated_at="2026-01-01T00:00:00+00:00",
    )


def _frames(n=6, span_minutes=30.0):
    """Buffer frames shaped like _detect_frame output, span > MIN_SPAN."""
    t0 = datetime(2026, 1, 16, 22, 0, tzinfo=timezone.utc)
    step = timedelta(minutes=span_minutes / max(n - 1, 1))
    return [{
        'dt': t0 + i * step,
        'detected': [(10.0 + i, 20.0, 100.0)],
        'above_horizon': [({'name': 'Vega', 'vmag': 0.03,
                            'ra_deg': 279.2, 'dec_deg': 38.8}, 60.0, 90.0)],
        'sky_cx': 960.0, 'sky_cy': 540.0, 'sky_r': 500.0,
        'image_width': 1920, 'image_height': 1080,
    } for i in range(n)]


@pytest.fixture
def fast_refine(monkeypatch):
    """Make _RefineWorker.run() return immediately with an admitted model.

    Everything the worker calls out to is stubbed at module level, so the real
    QThread subclass — the thing whose lifetime is under test — still runs.
    Records the frames list each run was handed.
    """
    seen = []

    def fake_refine(frames, seed, **kw):
        seen.append(frames)
        return _model()

    monkeypatch.setattr(cw, 'refine_from_detections', fake_refine)
    monkeypatch.setattr(cw, 'find_pole', lambda frames, lat, *a, **k: None)
    monkeypatch.setattr(cw, 'median_sky_r', lambda frames: 500.0)
    monkeypatch.setattr(cw, 'median_frame_resolution', lambda frames: (1920, 1080))
    monkeypatch.setattr(cw, 'east_left_hint', lambda *a, **k: None)
    monkeypatch.setattr(cw, 'admit_candidate', lambda *a, **k: (True, 'ok'))
    monkeypatch.setattr(cw, 'admission_evidence', lambda *a, **k: False)
    return seen


def _service(frames=None, model=None):
    svc = cs.CalibrationService()
    svc._save_model = lambda m, **kw: None   # never touch the real cal file
    svc._model = model if model is not None else _model()
    svc._quality = cs.model_quality(svc._model, 20, 40.0)
    svc._frames.extend(frames if frames is not None else _frames())
    return svc


def _run_one_refinement(svc):
    """Trigger a refinement and pump the loop until the worker is retired."""
    svc._maybe_refine()
    worker = svc._refine_worker
    assert worker is not None, "refinement did not start"
    worker.wait(5000)
    for _ in range(200):
        QCoreApplication.processEvents()
        if svc._refine_worker is None:
            break
    return worker


# ---------------------------------------------------------------------------
# Bug 1 — leaked workers
# ---------------------------------------------------------------------------

class TestWorkerLifetime:

    def test_repeated_refinements_leave_no_worker_children(self, qapp, fast_refine):
        svc = _service()
        baseline = len(svc.children())
        for _ in range(5):
            svc._last_refine_time = 0.0     # bypass the cooldown
            _run_one_refinement(svc)
            assert svc._refine_worker is None, "worker was not retired"
            assert len(svc.children()) == baseline
        assert baseline == 0, "workers must not be parented to the service"

    def test_retired_worker_is_released_and_deleted(self, qapp, fast_refine):
        import shiboken6
        svc = _service()
        worker = _run_one_refinement(svc)
        assert worker._frames is None, "payload still pinned after retirement"
        # processEvents() alone does not deliver DeferredDelete.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not shiboken6.isValid(worker), "QThread was never destroyed"

    def test_initial_worker_releases_its_image_copy(self, qapp, monkeypatch):
        monkeypatch.setattr(cw, 'calibrate', lambda *a, **k: _model())
        svc = cs.CalibrationService()
        svc._save_model = lambda m: None
        svc.validate_against_pole = lambda m: (True, 'ok')
        image = object()
        svc._pending_initial = (image, datetime.now(timezone.utc), 51.0, -1.0)
        svc._start_initial_cal()
        worker = svc._initial_worker
        assert worker is not None
        worker.wait(5000)
        for _ in range(200):
            QCoreApplication.processEvents()
            if svc._initial_worker is None:
                break
        assert svc._initial_worker is None
        assert worker._image is None
        assert len(svc.children()) == 0


# ---------------------------------------------------------------------------
# Bug 1 — the buffer is handed over by reference, not deep-copied
# ---------------------------------------------------------------------------

class TestBufferIsNotDeepCopied:

    def test_worker_receives_the_same_frame_dicts(self, qapp, fast_refine):
        frames = _frames()
        svc = _service(frames=frames)
        _run_one_refinement(svc)
        assert len(fast_refine) == 1
        handed = fast_refine[0]
        assert handed is not svc._frames, "must be a snapshot list, not the buffer"
        for original, passed in zip(frames, handed):
            assert passed is original
            assert passed['detected'] is original['detected']
            assert passed['above_horizon'] is original['above_horizon']

    def test_snapshot_is_unaffected_by_later_buffer_churn(self, qapp, fast_refine):
        svc = _service()
        svc._maybe_refine()
        worker = svc._refine_worker
        handed = worker._frames
        n = len(handed)
        with svc._lock:
            svc._frames.pop(0)
        assert len(handed) == n
        worker.wait(5000)
        for _ in range(200):
            QCoreApplication.processEvents()
            if svc._refine_worker is None:
                break


# ---------------------------------------------------------------------------
# Bug 2 — cooldown from completion, plus exponential failure back-off
# ---------------------------------------------------------------------------

class TestRefineBackoff:

    def test_cooldown_restarts_when_the_run_completes(self, qapp, fast_refine):
        svc = _service()
        svc._maybe_refine()
        triggered_at = svc._last_refine_time
        worker = svc._refine_worker
        worker.wait(5000)
        for _ in range(200):
            QCoreApplication.processEvents()
            if svc._refine_worker is None:
                break
        assert svc._last_refine_time > triggered_at

    def test_cooldown_doubles_per_consecutive_failure(self):
        svc = cs.CalibrationService()
        assert svc._refine_cooldown() == cs.REFINE_COOLDOWN_S
        for k in range(1, cs.REFINE_BACKOFF_MAX_DOUBLINGS + 1):
            svc._refine_backoff_failures = k
            assert svc._refine_cooldown() == min(
                cs.REFINE_COOLDOWN_S * 2 ** k, cs.REFINE_COOLDOWN_MAX_S)

    def test_cooldown_is_capped(self):
        svc = cs.CalibrationService()
        svc._refine_backoff_failures = 50
        assert svc._refine_cooldown() == cs.REFINE_COOLDOWN_MAX_S

    def test_failures_extend_the_cooldown_before_the_next_trigger(self, qapp,
                                                                  fast_refine):
        svc = _service()
        svc._refine_gen = svc._model_generation
        for _ in range(2):
            svc._on_refine_failed("admission check failed: …")
        assert svc._refine_backoff_failures == 2

        # 2 failures -> 4x REFINE_COOLDOWN_S. One plain cooldown is not enough.
        svc._last_refine_time -= cs.REFINE_COOLDOWN_S + 1
        svc._maybe_refine()
        assert svc._refine_worker is None, "back-off did not hold the trigger"

        svc._last_refine_time -= svc._refine_cooldown()
        _run_one_refinement(svc)

    def test_success_resets_the_back_off(self, qapp, fast_refine):
        svc = _service()
        svc._refine_backoff_failures = 4
        assert svc._refine_cooldown() > cs.REFINE_COOLDOWN_S

        svc._last_refine_time -= svc._refine_cooldown()
        _run_one_refinement(svc)
        assert svc._refine_backoff_failures == 0
        assert svc._refine_cooldown() == cs.REFINE_COOLDOWN_S

    def test_user_reset_clears_the_back_off(self):
        svc = cs.CalibrationService()
        svc._save_model = lambda m: None
        svc._model = _model()
        svc._refine_backoff_failures = 4
        svc.clear_model()
        assert svc._refine_backoff_failures == 0

    def test_basin_escape_still_fires_after_the_threshold(self, qapp, fast_refine):
        """Back-off delays escapes; it must not disable them."""
        svc = _service(frames=_frames(n=16, span_minutes=40.0))
        svc._consecutive_refine_failures = cs.BASIN_ESCAPE_FAILURES
        svc._refine_backoff_failures = cs.BASIN_ESCAPE_FAILURES
        svc._last_refine_time = -svc._refine_cooldown()
        svc._last_escape_time = -cs.ESCAPE_COOLDOWN_S
        svc._maybe_refine()
        worker = svc._refine_worker
        assert worker is not None
        assert worker._seed is None, "escape must run seedless"
        worker.wait(5000)
        for _ in range(200):
            QCoreApplication.processEvents()
            if svc._refine_worker is None:
                break

    def test_a_live_worker_blocks_a_second_trigger(self, qapp, fast_refine):
        svc = _service()
        svc._maybe_refine()
        first = svc._refine_worker
        svc._last_refine_time = 0.0
        svc._maybe_refine()
        assert svc._refine_worker is first, "started a second concurrent refinement"
        first.wait(5000)
        for _ in range(200):
            QCoreApplication.processEvents()
            if svc._refine_worker is None:
                break


# ---------------------------------------------------------------------------
# 2026-09-05 — the incumbent is judged too (incumbent_evidence)
# ---------------------------------------------------------------------------

def _pump(svc, worker):
    worker.wait(5000)
    for _ in range(200):
        QCoreApplication.processEvents()
        if svc._refine_worker is None:
            break


def _arm_escape(svc):
    svc._consecutive_refine_failures = cs.BASIN_ESCAPE_FAILURES
    svc._last_refine_time = -svc._refine_cooldown()
    svc._last_escape_time = -cs.ESCAPE_COOLDOWN_S


class TestEscapeNeedsAnUnhealthySeed:

    def test_healthy_incumbent_turns_the_escape_into_a_refinement(
            self, qapp, fast_refine, monkeypatch):
        monkeypatch.setattr(cs, 'incumbent_anchor_health', lambda m, f: True)
        svc = _service(frames=_frames(n=16, span_minutes=40.0))
        _arm_escape(svc)
        svc._maybe_refine()
        worker = svc._refine_worker
        assert worker is not None
        assert worker._seed is svc._model, "must refine from the healthy seed"
        assert svc._escape_attempt is False
        _pump(svc, worker)

    def test_unhealthy_incumbent_escapes_seedless(self, qapp, fast_refine, monkeypatch):
        monkeypatch.setattr(cs, 'incumbent_anchor_health', lambda m, f: False)
        svc = _service(frames=_frames(n=16, span_minutes=40.0))
        _arm_escape(svc)
        svc._maybe_refine()
        worker = svc._refine_worker
        assert worker._seed is None and svc._escape_attempt is True
        _pump(svc, worker)

    def test_unknown_health_does_not_block_the_escape(self, qapp, fast_refine, monkeypatch):
        monkeypatch.setattr(cs, 'incumbent_anchor_health', lambda m, f: None)
        svc = _service(frames=_frames(n=16, span_minutes=40.0))
        _arm_escape(svc)
        svc._maybe_refine()
        assert svc._refine_worker._seed is None
        _pump(svc, svc._refine_worker)

    def test_a_skipped_escape_waits_a_full_escape_cooldown(
            self, qapp, fast_refine, monkeypatch):
        monkeypatch.setattr(cs, 'incumbent_anchor_health', lambda m, f: True)
        svc = _service(frames=_frames(n=16, span_minutes=40.0))
        _arm_escape(svc)
        svc._maybe_refine()
        import time
        assert time.monotonic() - svc._last_escape_time < 5.0
        _pump(svc, svc._refine_worker)


class TestIncumbentCorroboration:

    def _corroborating_pole(self, monkeypatch, incumbent):
        from services.allsky.model_admission import projected_pole
        from services.allsky.pole_finder import PoleEstimate
        x, y = projected_pole(incumbent, 39.0)
        est = PoleEstimate(x=x, y=y, east_left=True, sign=-1, n_frames=12,
                           span_minutes=47.0, drift_px=2.4, flux=3600.0,
                           sign_votes=(300, 1000), image_width=1920,
                           image_height=1080)
        monkeypatch.setattr(cw, 'find_pole', lambda frames, lat, *a, **k: est)

    def test_trusted_pole_stamps_and_persists_the_incumbent(
            self, qapp, fast_refine, monkeypatch):
        svc = _service()
        svc._lat = 39.0
        saved = []
        svc._save_model = lambda m, **kw: saved.append((m, kw))
        self._corroborating_pole(monkeypatch, svc._model)
        before = svc._model.calibrated_at
        _run_one_refinement(svc)
        assert svc._model.provenance == 'pole'
        assert any(m is svc._model and kw.get('stamp_time') is False
                   for m, kw in saved)
        assert svc._model.calibrated_at == before

    def test_second_run_does_not_restamp(self, qapp, fast_refine, monkeypatch):
        svc = _service()
        svc._lat = 39.0
        saved = []
        svc._save_model = lambda m, **kw: saved.append(kw)
        self._corroborating_pole(monkeypatch, svc._model)
        _run_one_refinement(svc)
        svc._last_refine_time = 0.0
        _run_one_refinement(svc)
        assert sum(1 for kw in saved if kw.get('stamp_time') is False) == 1

    def test_stale_generation_is_ignored(self, qapp):
        svc = _service()
        saved = []
        svc._save_model = lambda m, **kw: saved.append(m)
        svc._refine_gen = svc._model_generation
        svc._model_generation += 1          # Calibrate Now swapped the model
        svc._on_incumbent_corroborated("late")
        assert saved == []


class TestSaveBackup:

    def _paths(self, monkeypatch, tmp_path):
        import services.app_config as ac
        cal = str(tmp_path / 'allsky_calibration.json')
        bak = str(tmp_path / 'allsky_calibration.previous.json')
        monkeypatch.setattr(ac, 'get_calibration_path', lambda: cal)
        monkeypatch.setattr(ac, 'get_calibration_backup_path', lambda: bak)
        return cal, bak

    def test_previous_file_is_kept_when_a_model_replaces_it(self, qapp, monkeypatch, tmp_path):
        cal, bak = self._paths(monkeypatch, tmp_path)
        svc = cs.CalibrationService()
        good = _model(rms=8.04, n_matches=767)
        svc._save_model(good)
        assert not os.path.exists(bak)
        svc._save_model(_model(rms=8.03, n_matches=828))
        assert FisheyeModel.load(bak).n_matches == 767
        assert FisheyeModel.load(cal).n_matches == 828

    def test_provenance_stamp_keeps_the_timestamp_and_makes_no_backup(
            self, qapp, monkeypatch, tmp_path):
        cal, bak = self._paths(monkeypatch, tmp_path)
        svc = cs.CalibrationService()
        m = _model()
        svc._save_model(m)
        stamped_at = m.calibrated_at
        m.provenance = 'pole'
        svc._save_model(m, stamp_time=False)
        assert not os.path.exists(bak)
        reloaded = FisheyeModel.load(cal)
        assert reloaded.provenance == 'pole' and reloaded.calibrated_at == stamped_at
