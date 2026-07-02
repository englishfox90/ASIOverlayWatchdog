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
    """Replicate the _on_refine_done accept/reject logic as a pure function."""
    new_q = model_quality(new, new.n_images, new.span_minutes)
    rms_ok = new.rms_residual <= current.rms_residual * 1.15
    return rms_ok and (
        CalibrationQuality.rank(new_q) > CalibrationQuality.rank(current_quality)
        or (
            new.rms_residual < current.rms_residual
            and new.n_matches >= current.n_matches
        )
    )


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

    def test_escape_result_bypasses_rms_guard(self):
        """The wrong-basin incident model carried a flattering RMS (4.2px,
        11 matches). An honest escape result (9px, 200 matches) must replace
        it even though the normal guard would reject the RMS regression."""
        svc = self._service()
        bad = _model(rms=4.0, n_matches=11, n_images=1, span_minutes=0.0)
        svc._model = bad
        svc._quality = 'preliminary'
        svc._escape_attempt = True
        svc._refine_gen = svc._model_generation
        honest = _model(rms=9.0, n_matches=200, n_images=20, span_minutes=60.0)
        svc._on_refine_done(honest, 20, 60.0)
        assert svc._model is honest
        assert svc._consecutive_refine_failures == 0
        assert svc._escape_attempt is False

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
