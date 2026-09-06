"""
Regression tests for the all-sky calibration reliability fixes.

Covers:
  - Refinement guard: worse-RMS rank upgrade rejected; bounded regression accepted
  - FisheyeModel resolution scaling: half-size model projects to half the pixels
"""
import copy
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.allsky.fisheye import FisheyeModel
from services.allsky.calibration_service import CalibrationQuality, model_quality


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _model(rms: float, n_matches: int, n_images: int = 5,
           span_minutes: float = 30.0) -> FisheyeModel:
    return FisheyeModel(
        cx=960.0, cy=540.0, a1=600.0,
        rms_residual=rms, n_matches=n_matches,
        n_images=n_images, span_minutes=span_minutes,
        calibrated_at="2026-01-01T00:00:00+00:00",
    )


def _would_improve(current: FisheyeModel, new: FisheyeModel,
                   current_quality: str) -> bool:
    """The _on_refine_done accept/reject decision (model_replacement)."""
    from services.allsky.model_replacement import should_replace
    new_q = model_quality(new, new.n_images, new.span_minutes)
    return should_replace(current, current_quality, new, new_q)[0]


# ---------------------------------------------------------------------------
# Refinement RMS guard (F3 + Phase 2.2)
# ---------------------------------------------------------------------------

class TestRefineGuard:

    def test_pure_rms_improvement_accepted(self):
        """Lower RMS, same rank → accept."""
        current = _model(rms=8.0, n_matches=80)
        new = _model(rms=6.0, n_matches=85)
        q = model_quality(current, current.n_images, current.span_minutes)
        assert _would_improve(current, new, q)

    def test_rank_upgrade_within_rms_bound_accepted(self):
        """Quality rank goes up, RMS within 15% → accept."""
        # current: 3 images, 30 min → acceptable (rank 2)
        current = _model(rms=10.0, n_matches=50, n_images=3, span_minutes=30.0)
        # new: 12 images, 40 min → good (rank 3)
        new = _model(rms=11.0, n_matches=110, n_images=12, span_minutes=40.0)
        q = model_quality(current, current.n_images, current.span_minutes)
        assert CalibrationQuality.rank(q) == CalibrationQuality.rank('acceptable')
        new_q = model_quality(new, new.n_images, new.span_minutes)
        assert CalibrationQuality.rank(new_q) == CalibrationQuality.rank('good')
        # 11.0 <= 10.0 * 1.15 = 11.5 → rms_ok; rank upgrade → accept
        assert _would_improve(current, new, q)

    def test_rank_upgrade_but_rms_exceeds_bound_rejected(self):
        """Rank goes up but RMS is >15% worse → reject.

        This is the core regression from F3: a 15-20px model was overwriting
        a 3px model on disk just by accumulating more frames.
        """
        current = _model(rms=3.0, n_matches=100, n_images=3, span_minutes=30.0)
        # rms 4.0 > 3.0 * 1.15 = 3.45 → rms_ok=False even if rank goes up
        new = _model(rms=4.0, n_matches=120, n_images=12, span_minutes=40.0)
        q = model_quality(current, current.n_images, current.span_minutes)
        assert not _would_improve(current, new, q)

    def test_rms_exactly_at_15_percent_boundary_accepted(self):
        """RMS at exactly current * 1.15 (boundary) → accept."""
        current = _model(rms=10.0, n_matches=80)
        new = _model(rms=11.5, n_matches=120, n_images=12, span_minutes=40.0)
        q = model_quality(current, current.n_images, current.span_minutes)
        assert _would_improve(current, new, q)

    def test_rms_just_above_15_percent_boundary_rejected(self):
        """RMS fractionally above current * 1.15 → reject."""
        current = _model(rms=10.0, n_matches=80)
        new = _model(rms=11.6, n_matches=120, n_images=12, span_minutes=40.0)
        q = model_quality(current, current.n_images, current.span_minutes)
        assert not _would_improve(current, new, q)

    def test_worse_rms_fewer_matches_rejected(self):
        """Both metrics worse → always reject."""
        current = _model(rms=5.0, n_matches=100)
        new = _model(rms=7.0, n_matches=60)
        q = model_quality(current, current.n_images, current.span_minutes)
        assert not _would_improve(current, new, q)


# ---------------------------------------------------------------------------
# Basin escape (ALLSKY_POLE_ANCHOR_PLAN P3): a repeatedly-rejected seed model
# triggers a seedless re-calibration whose result bypasses the RMS guard.
# ---------------------------------------------------------------------------

class TestBasinEscape:

    def _service(self):
        from services.allsky.calibration_service import CalibrationService
        svc = CalibrationService()
        svc._save_model = lambda m: None   # never touch the real cal file
        return svc

    def test_consecutive_failures_counted_and_reset_on_success(self):
        svc = self._service()
        svc._model = _model(rms=4.0, n_matches=11)
        svc._quality = 'preliminary'
        svc._refine_gen = svc._model_generation   # refinement of current model
        svc._on_refine_failed("Refinement failed sanity check: …")
        svc._on_refine_failed("Refinement failed sanity check: …")
        assert svc._consecutive_refine_failures == 2

        # A failure from a refinement seeded by a superseded model must NOT
        # count against the current one.
        svc._refine_gen = svc._model_generation - 1
        svc._on_refine_failed("stale seed failure")
        assert svc._consecutive_refine_failures == 2
        svc._refine_gen = svc._model_generation

        # A completed (gate-passing) refinement resets the counter even when
        # it does not replace the model.
        svc._refine_gen = svc._model_generation
        svc._on_refine_done(_model(rms=9.0, n_matches=5), 5, 30.0)
        assert svc._consecutive_refine_failures == 0

    def test_failures_without_model_do_not_count(self):
        """Cold-start attempts that fail are expected — no escape needed."""
        svc = self._service()
        svc._on_refine_failed("Cold-start bootstrap failed: …")
        assert svc._consecutive_refine_failures == 0

    def test_escape_result_on_evidence_bypasses_rms_guard(self):
        """The wrong-basin incident model carried a flattering RMS (4.2px,
        11 matches). An honest escape result (9px, 200 matches) admitted on
        evidence (a trusted pole, or continuity with an authoritative
        incumbent) must replace it even though the normal guard would
        reject the RMS regression."""
        svc = self._service()
        bad = _model(rms=4.0, n_matches=11, n_images=1, span_minutes=0.0)
        svc._model = bad
        svc._quality = 'preliminary'
        svc._escape_attempt = True
        svc._refine_gen = svc._model_generation
        honest = _model(rms=9.0, n_matches=200, n_images=20, span_minutes=60.0)
        svc._on_refine_done(honest, 20, 60.0, evidence=True)
        assert svc._model is honest
        assert svc._consecutive_refine_failures == 0
        assert svc._escape_attempt is False

    def test_escape_without_evidence_cannot_overwrite_legacy_model(self, tmp_path):
        """Review blocker: every pre-provenance installation loads its
        calibration uncorroborated, and with no trusted pole admit_candidate
        checks nothing — so an escape result used to be installed and saved
        unconditionally. A wrong-scale bootstrap over a hazy buffer (the #10
        a1≈1030 family: fewer matches, plausible RMS) must be held to the
        normal comparison and lose."""
        import json
        from services.allsky.model_admission import incumbent_authority
        good = _model(rms=7.7, n_matches=4561, n_images=40, span_minutes=80.0)
        good.provenance = 'pole'                 # stamped by a newer build...
        p = tmp_path / "allsky_calibration.json"
        good.save(str(p))
        legacy = json.loads(p.read_text())
        del legacy['provenance']                 # ...but this file predates it
        p.write_text(json.dumps(legacy))

        svc = self._service()
        saved = []
        svc._save_model = lambda m: saved.append(m)
        svc.load_model(str(p))
        assert svc.current_model.provenance == ''
        assert incumbent_authority(svc.current_model) is None
        svc._escape_attempt = True
        svc._refine_gen = svc._model_generation
        wrong = _model(rms=6.0, n_matches=900, n_images=20, span_minutes=60.0)
        wrong.a1 = 600.0 * 0.8
        svc._on_refine_done(wrong, 20, 60.0, evidence=False)
        assert svc.current_model is not wrong
        assert svc.current_model.n_matches == 4561
        assert saved == []
        assert svc._escape_attempt is False

    def test_escape_without_evidence_still_wins_when_genuinely_better(self):
        """The previous blocker's fix must survive: a wrong cold-start model
        (uncorroborated, no pole) is not a permanent lock — a candidate that
        beats it on the numbers replaces it."""
        svc = self._service()
        svc._model = _model(rms=9.0, n_matches=300, n_images=20, span_minutes=60.0)
        svc._quality = model_quality(svc._model, 20, 60.0)
        svc._escape_attempt = True
        svc._refine_gen = svc._model_generation
        better = _model(rms=7.0, n_matches=1200, n_images=25, span_minutes=70.0)
        svc._on_refine_done(better, 25, 70.0, evidence=False)
        assert svc._model is better

    def test_worker_signal_carries_evidence(self):
        from services.allsky.calibration_service import _RefineWorker
        w = _RefineWorker([], None, 5, 30.0)
        # (model, n_images, span_min, evidence)
        received = []
        w.finished.connect(lambda *a: received.append(a))
        m = _model(rms=5.0, n_matches=50)
        w.finished.emit(m, 5, 30.0, True)
        assert received == [(m, 5, 30.0, True)]

    def test_non_escape_regression_still_rejected(self):
        """Without the escape flag, the 15% RMS guard still protects."""
        svc = self._service()
        good = _model(rms=4.0, n_matches=100)
        svc._model = good
        svc._quality = model_quality(good, good.n_images, good.span_minutes)
        svc._refine_gen = svc._model_generation
        worse = _model(rms=9.0, n_matches=200, n_images=20, span_minutes=60.0)
        svc._on_refine_done(worse, 20, 60.0)
        assert svc._model is good

    def test_set_model_resets_escape_state(self):
        svc = self._service()
        svc._consecutive_refine_failures = 5
        svc._escape_attempt = True
        svc.set_model(_model(rms=5.0, n_matches=50))
        assert svc._consecutive_refine_failures == 0
        assert svc._escape_attempt is False

    def test_validate_against_pole_empty_buffer_is_ok(self):
        svc = self._service()
        ok, msg = svc.validate_against_pole(_model(rms=5.0, n_matches=50))
        assert ok

    def test_guided_model_passes_manual_gate_regardless_of_pole(self):
        """Issue #10: user anchors outrank a pole measured from a field of
        pier/mount lights — a guided result is never vetoed by the pole."""
        from services.allsky.pole_finder import PoleEstimate
        svc = self._service()
        contaminant = PoleEstimate(x=1822.0, y=2765.0, east_left=False, sign=1,
                                   n_frames=12, span_minutes=60.0, drift_px=3.0,
                                   flux=9000.0, sign_votes=(500, 300))
        svc._pole_history.record(contaminant, 1563.0)
        guided = _model(rms=2.4, n_matches=7, n_images=1, span_minutes=0.0)
        guided.provenance = 'guided'
        ok, msg = svc.validate_against_pole(guided)
        assert ok and 'guided' in msg


class TestManualPathMeasuresThePole:
    """Review warning 1: the history is populated only by refine runs (35-min,
    15-frame span), so on a fresh install the first Calibrate Now / guided
    solve — saved to disk, seed of every later refinement — ran against an
    empty history and was admitted ungated while a measurement sat in the
    same buffer. validate_against_pole now measures the buffer and judges
    the fresh estimate alongside the history without recording it."""

    LAT = 38.9717

    def _service(self, monkeypatch, fresh):
        from datetime import datetime, timezone
        from services.allsky import calibration_service as cs
        svc = cs.CalibrationService()
        svc._save_model = lambda m: None
        svc._lat = self.LAT
        svc._frames.append({
            'dt': datetime(2026, 1, 16, 8, 0, tzinfo=timezone.utc),
            'detected': [(1.0, 1.0, 100.0)], 'sky_cx': 960.0, 'sky_cy': 540.0,
            'sky_r': 500.0, 'image_width': 1920, 'image_height': 1080,
        })
        calls = []

        def fake_find_pole(frames, lat, *a, **k):
            calls.append(len(frames))
            return fresh
        monkeypatch.setattr(cs, 'find_pole', fake_find_pole)
        return svc, calls

    @staticmethod
    def _estimate(x, y, east_left):
        from services.allsky.pole_finder import PoleEstimate
        return PoleEstimate(x=x, y=y, east_left=east_left, sign=-1, n_frames=12,
                            span_minutes=60.0, drift_px=1.0, flux=3000.0,
                            sign_votes=(30, 300), image_width=1920,
                            image_height=1080)

    def test_first_manual_result_is_gated_by_the_fresh_measurement(self, monkeypatch):
        from services.allsky.model_admission import projected_pole
        model = _model(rms=5.0, n_matches=50)
        model.image_width, model.image_height = 1920, 1080
        px, py = projected_pole(model, self.LAT)
        svc, calls = self._service(monkeypatch, self._estimate(px + 900.0, py, True))
        assert len(svc._pole_history) == 0
        ok, msg = svc.validate_against_pole(model)
        assert not ok and 'measured position' in msg
        assert calls == [1]
        assert len(svc._pole_history) == 0        # measured, never recorded

    def test_matching_manual_result_passes_and_is_corroborated(self, monkeypatch):
        from services.allsky.model_admission import projected_pole
        model = _model(rms=5.0, n_matches=50)
        model.image_width, model.image_height = 1920, 1080
        px, py = projected_pole(model, self.LAT)
        svc, _ = self._service(monkeypatch, self._estimate(px, py, True))
        ok, msg = svc.validate_against_pole(model)
        assert ok, msg
        assert model.provenance == 'pole'

    def test_one_physical_reading_never_asserts_the_mirror(self, monkeypatch):
        """Review blocker 3 (kept): however many times the same buffer is
        judged, a single reading's decisive vote must not become the
        'repeated' vote that asserts east_left — here the reading votes
        the OPPOSITE mirror to the model, so any assertion would veto."""
        from services.allsky.model_admission import projected_pole
        model = _model(rms=5.0, n_matches=50)
        model.image_width, model.image_height = 1920, 1080
        model.east_left = True
        px, py = projected_pole(model, self.LAT)
        svc, calls = self._service(monkeypatch, self._estimate(px, py, False))
        for _ in range(3):
            ok, msg = svc.validate_against_pole(model)
            assert ok, msg
        assert calls == [1, 1, 1]
        assert len(svc._pole_history) == 0

    def test_no_measurement_and_empty_history_is_ungated(self, monkeypatch):
        svc, _ = self._service(monkeypatch, None)
        ok, msg = svc.validate_against_pole(_model(rms=5.0, n_matches=50))
        assert ok and 'skipped' in msg


class TestGuidedIncumbentRefinement:
    """Once a guided model is the incumbent, same-basin multi-image
    refinements (admitted by model_admission continuity) must be able to
    replace it: anchor RMS over 7 clicks and joint RMS over thousands of
    matches are not comparable, and the multi-image fit is the better
    whole-sky model (ALLSKY_CALIBRATION_PLAN)."""

    def _service(self):
        from services.allsky.calibration_service import CalibrationService
        svc = CalibrationService()
        svc._save_model = lambda m: None
        return svc

    def _guided_incumbent(self, svc):
        guided = _model(rms=2.4, n_matches=7, n_images=1, span_minutes=0.0)
        guided.provenance = 'guided'
        svc._model = guided
        svc._quality = model_quality(guided, 1, 0.0)   # preliminary
        svc._refine_gen = svc._model_generation
        return guided

    def test_multi_image_refinement_replaces_guided_solve(self):
        svc = self._service()
        self._guided_incumbent(svc)
        refined = _model(rms=7.7, n_matches=4561, n_images=40, span_minutes=80.0)
        refined.provenance = 'guided'        # inherited by the worker on admission
        svc._on_refine_done(refined, 40, 80.0)
        assert svc.current_model is refined
        assert svc.current_quality == CalibrationQuality.EXCELLENT
        assert svc.current_model.provenance == 'guided'

    def test_after_replacement_normal_rms_guard_applies(self):
        svc = self._service()
        self._guided_incumbent(svc)
        refined = _model(rms=7.7, n_matches=4561, n_images=40, span_minutes=80.0)
        refined.provenance = 'guided'
        svc._on_refine_done(refined, 40, 80.0)
        worse = _model(rms=12.0, n_matches=5000, n_images=45, span_minutes=90.0)
        worse.provenance = 'guided'
        svc._refine_gen = svc._model_generation
        svc._on_refine_done(worse, 45, 90.0)
        assert svc.current_model is refined

    def test_single_image_result_does_not_replace_guided(self):
        svc = self._service()
        guided = self._guided_incumbent(svc)
        single = _model(rms=6.0, n_matches=40, n_images=1, span_minutes=0.0)
        svc._on_refine_done(single, 1, 0.0)
        assert svc.current_model is guided

    def test_refine_worker_accepts_incumbent_and_history(self):
        from services.allsky.calibration_service import _RefineWorker
        from services.allsky.pole_consensus import PoleHistory
        inc = _model(rms=5.0, n_matches=50)
        w = _RefineWorker([], inc, 5, 30.0, lat=39.0, incumbent=inc,
                          pole_history=PoleHistory())
        assert w._incumbent is inc
        w2 = _RefineWorker([], None, 5, 30.0)
        assert w2._incumbent is None and w2._pole_history is not None


# ---------------------------------------------------------------------------
# Calibration reset (user-initiated) — service + controller
# ---------------------------------------------------------------------------

class _FakeConfig:
    def __init__(self):
        self._data = {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def save(self):
        pass


class _FakeMainWindow:
    def __init__(self):
        self.config = _FakeConfig()


class TestCalibrationReset:

    def _service(self):
        from services.allsky.calibration_service import CalibrationService
        svc = CalibrationService()
        svc._save_model = lambda m: None
        return svc

    def test_clear_model_keeps_buffer_and_bumps_generation(self):
        svc = self._service()
        svc._model = _model(rms=5.0, n_matches=50)
        svc._quality = 'good'
        svc._consecutive_refine_failures = 4
        svc._frames.append({'dt': None, 'detected': []})
        gen = svc._model_generation
        svc.clear_model()
        assert svc.current_model is None
        assert svc.current_quality == 'none'
        assert svc._model_generation == gen + 1
        assert svc._consecutive_refine_failures == 0
        assert svc.frame_count == 1   # buffer kept for immediate bootstrap

    def test_initial_result_accepted_after_reset(self):
        """A reset must not permanently disable the fast single-image path —
        the old `generation > 0` check discarded every post-reset result."""
        svc = self._service()
        svc._model = _model(rms=5.0, n_matches=50)
        svc.set_model(svc._model)          # generation > 0 now
        svc.clear_model()
        svc._initial_gen = svc._model_generation   # worker launched post-reset
        fresh = _model(rms=6.0, n_matches=40)
        svc._on_initial_done(fresh)
        assert svc.current_model is fresh

    def test_initial_result_discarded_if_model_changed_mid_flight(self):
        svc = self._service()
        svc._initial_gen = svc._model_generation   # worker launched
        manual = _model(rms=3.0, n_matches=80)
        svc.set_model(manual)                       # user calibrated meanwhile
        late = _model(rms=6.0, n_matches=40)
        svc._on_initial_done(late)
        assert svc.current_model is manual

    def test_controller_reset_deletes_file_and_clears_state(self, tmp_path, monkeypatch):
        import services.app_config as app_config
        cal = tmp_path / "allsky_calibration.json"
        cal.write_text("{}")
        monkeypatch.setattr(app_config, 'get_calibration_path',
                            lambda: str(cal))

        from ui.controllers.allsky_controller import AllSkyController
        mw = _FakeMainWindow()
        mw.config.set('allsky_overlay', {'calibration_file': str(cal)})
        ctrl = AllSkyController(mw)
        ctrl._model = _model(rms=4.0, n_matches=11)
        ctrl._cal_service._save_model = lambda m: None
        ctrl._cal_service._model = _model(rms=4.0, n_matches=11)

        ctrl.reset_calibration()

        assert not cal.exists()
        assert ctrl._model is None
        assert ctrl._cal_service.current_model is None
        assert mw.config.get('allsky_overlay')['calibration_file'] == ''

    def test_controller_reset_with_no_file_still_clears_state(self, tmp_path, monkeypatch):
        import services.app_config as app_config
        cal = tmp_path / "missing.json"
        monkeypatch.setattr(app_config, 'get_calibration_path',
                            lambda: str(cal))

        from ui.controllers.allsky_controller import AllSkyController
        ctrl = AllSkyController(_FakeMainWindow())
        ctrl._model = _model(rms=4.0, n_matches=11)
        ctrl.reset_calibration()
        assert ctrl._model is None


# ---------------------------------------------------------------------------
# Non-square-sensor warning (all-sky assumes fisheye circle fully in frame)
# ---------------------------------------------------------------------------

class _FakeImage:
    def __init__(self, w, h):
        self.width, self.height = w, h


class TestAspectWarning:
    def test_square_sensor_no_warning(self):
        from ui.controllers.allsky_controller import _aspect_warning
        assert _aspect_warning(_FakeImage(3552, 3552)) is None

    def test_mild_rectangle_no_warning(self):
        from ui.controllers.allsky_controller import _aspect_warning
        assert _aspect_warning(_FakeImage(3552, 3079)) is None  # 1.15

    def test_wide_sensor_warns(self):
        from ui.controllers.allsky_controller import _aspect_warning
        msg = _aspect_warning(_FakeImage(1920, 1080))
        assert msg is not None
        assert '1920x1080' in msg
        assert 'square' in msg

    def test_unknown_size_no_warning(self):
        from ui.controllers.allsky_controller import _aspect_warning
        assert _aspect_warning(object()) is None


# ---------------------------------------------------------------------------
# FisheyeModel resolution scaling (F5 + Phase 3.1)
# ---------------------------------------------------------------------------

class TestFisheyeModelScaling:

    def _full_model(self) -> FisheyeModel:
        return FisheyeModel(
            cx=960.0, cy=540.0, a1=600.0, a3=-20.0, a5=0.0,
            roll=0.0, axis_alt=90.0, axis_az=0.0,
            image_width=1920, image_height=1080,
            rms_residual=1.0, n_matches=50,
        )

    def _scale(self, model: FisheyeModel, s: float) -> FisheyeModel:
        m = copy.copy(model)
        m.cx *= s
        m.cy *= s
        m.a1 *= s
        m.a3 *= s
        m.a5 *= s
        m.image_width = int(model.image_width * s)
        m.image_height = int(model.image_height * s)
        return m

    def test_half_scale_projects_to_half_pixels(self):
        """Projecting any star through a 50%-scaled copy of a model yields
        exactly half the pixel coordinates of the full-resolution projection."""
        model = self._full_model()
        half = self._scale(model, 0.5)

        for alt, az in [(45.0, 0.0), (70.0, 90.0), (30.0, 180.0), (60.0, 270.0)]:
            px1 = model.altaz_to_pixel(alt, az)
            px2 = half.altaz_to_pixel(alt, az)
            assert px1 is not None, f"Full model failed to project ({alt}, {az})"
            assert px2 is not None, f"Half model failed to project ({alt}, {az})"
            assert abs(px2[0] - px1[0] * 0.5) < 0.5, (
                f"x mismatch at ({alt}°, {az}°): "
                f"full={px1[0]:.1f}, half={px2[0]:.1f} (expected {px1[0]*0.5:.1f})"
            )
            assert abs(px2[1] - px1[1] * 0.5) < 0.5, (
                f"y mismatch at ({alt}°, {az}°): "
                f"full={px1[1]:.1f}, half={px2[1]:.1f} (expected {px1[1]*0.5:.1f})"
            )

    def test_quarter_scale_projects_to_quarter_pixels(self):
        """Same as above but at 25% scale."""
        model = self._full_model()
        quarter = self._scale(model, 0.25)

        alt, az = 55.0, 135.0
        px1 = model.altaz_to_pixel(alt, az)
        px2 = quarter.altaz_to_pixel(alt, az)
        assert px1 is not None and px2 is not None
        assert abs(px2[0] - px1[0] * 0.25) < 0.5
        assert abs(px2[1] - px1[1] * 0.25) < 0.5

    def test_identity_scale_unchanged(self):
        """Scaling by 1.0 leaves projections identical."""
        model = self._full_model()
        same = self._scale(model, 1.0)

        alt, az = 50.0, 45.0
        px1 = model.altaz_to_pixel(alt, az)
        px2 = same.altaz_to_pixel(alt, az)
        assert px1 is not None and px2 is not None
        assert abs(px2[0] - px1[0]) < 1e-9
        assert abs(px2[1] - px1[1]) < 1e-9

    def test_image_width_height_recorded(self):
        """FisheyeModel stores calibration image size."""
        m = FisheyeModel(image_width=1920, image_height=1080)
        assert m.image_width == 1920
        assert m.image_height == 1080

    def test_zero_dimensions_are_unknown(self):
        """Default (0, 0) means 'unknown' — old JSONs don't break on load."""
        m = FisheyeModel()
        assert m.image_width == 0
        assert m.image_height == 0
