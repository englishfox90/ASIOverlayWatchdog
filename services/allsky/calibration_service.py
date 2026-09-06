"""
Background calibration accumulation service.

Receives frames from the image processing pipeline, detects stars,
accumulates detection data, and progressively refines the fisheye lens
model through multi-image joint calibration.

Lifecycle:
  1. Created by AllSkyController on startup.
  2. Loads existing model from %LOCALAPPDATA%/PFRSentinel/allsky_calibration.json.
  3. Fed by ImageProcessorWorker via feed_frame() on each captured frame.
  4. Detects stars inline (~50 ms), stores detection data (not raw images).
  5. When enough frames span enough time, launches a background _RefineWorker.
  6. On success, saves improved model and emits quality_upgraded signal.

Thread safety:
  - feed_frame() is called from the image-processor worker thread.
  - _maybe_refine() runs on the main thread (via queued signal).
  - _RefineWorker runs in its own QThread.

Worker ownership:
  Workers are created UNPARENTED and retired via QThread.finished (see
  _retire_worker). Parenting them to this long-lived service made Shiboken
  keep every past QThread alive, each pinning its payload — measured at
  477 MB after ten refinements, ~2.2 GB over a night on the reference rig.
"""
import functools
import os
import shutil
import threading
import time
from datetime import datetime, timezone
from typing import List, Optional

from PySide6.QtCore import QObject, Signal

from services.logger import app_logger as log

from .star_centroid import detect_stars, measure_sky_circle
from .fisheye import FisheyeModel
from .catalogs import get_bright_stars
from .coords import radec_to_altaz
from .calibration_quality import CalibrationQuality, model_quality  # re-exported for existing callers
from .calibration_validate import median_frame_resolution
from .calibration_workers import (  # re-exported for existing callers
    MAX_RESIDUAL_PX, _InitialCalWorker, _RefineWorker)
from .incumbent_evidence import incumbent_anchor_health
from .model_admission import admit_manual
from .model_replacement import should_replace
from .multi_calibrate import median_sky_r
from .pole_consensus import PoleHistory
from .pole_finder import find_pole

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_BUFFER = 60             # rolling buffer capacity (frame dicts)
MIN_FRAMES = 3              # minimum frames before attempting refinement
MIN_SPAN_MINUTES = 5.0      # minimum time span to refine an existing model

# Cold-start (no prior model) needs a much longer baseline. A near-zenith
# fisheye is rotationally degenerate over short spans: many (roll, azimuth)
# orientations produce near-identical star patterns, so only enough sky
# *rotation over time* can disambiguate the true pose. Attempting orientation
# from a few minutes converges to a wrong basin (observed: Polaris placed on
# the wrong side from a ~7-min span). The reference long-baseline fit that
# historically worked spanned ~78 min; require a substantial window before the
# first cold-start attempt.
MIN_SPAN_BOOTSTRAP_MINUTES = 35.0
MIN_FRAMES_BOOTSTRAP = 15

REFINE_COOLDOWN_S = 120     # seconds between refinement attempts
INITIAL_COOLDOWN_S = 180    # seconds between initial single-image cal attempts

# Failure back-off. The cooldown is measured from when a run *completes*, not
# when it is triggered: a run takes 40 s to several minutes, so the flat
# trigger-relative 120 s left refinement occupying roughly half of every night.
# On top of that, a seed that cannot be refined fails identically every time
# (33 consecutive rejections in one production log), so each consecutive
# failure doubles the wait up to a half-hour ceiling. Reset by any run that
# completes, and by a user reset.
REFINE_BACKOFF_MAX_DOUBLINGS = 4
REFINE_COOLDOWN_MAX_S = 1800

# Basin escape: a wrong-basin model on disk seeds every refinement into its
# own basin, whose polished result the sanity gates then reject — a permanent
# loop (observed in production, 2026-06-24). After this many consecutive
# rejections the seed itself is suspect: run one cold-start bootstrap instead
# and let a gate-passing result replace the model outright.
BASIN_ESCAPE_FAILURES = 3
ESCAPE_COOLDOWN_S = 600     # bootstrap fits are expensive; don't spam them


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------

class CalibrationService(QObject):
    """
    Background service that accumulates star detections from incoming
    frames and progressively refines the fisheye lens model.

    Signals:
        quality_upgraded(str, object): quality level name + FisheyeModel.
        status_changed(str): human-readable status for the UI.
    """

    quality_upgraded = Signal(str, object)
    status_changed = Signal(str)

    # Internal signal: queued to main thread for safe QThread creation.
    _check_refine = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frames: List[dict] = []
        self._lock = threading.Lock()
        self._model: Optional[FisheyeModel] = None
        self._quality = 'none'
        self._model_generation = 0  # incremented by set_model() to detect stale refinements
        self._last_refine_time = 0.0
        self._last_initial_attempt_time = 0.0
        self._refine_worker: Optional[_RefineWorker] = None
        self._initial_worker: Optional[_InitialCalWorker] = None
        self._pending_initial = None   # (image, dt, lat, lon) awaiting cal
        self._refine_gen = -1          # generation when last refine was launched
        self._initial_gen = -1         # generation when last initial cal launched
        # F9: per-frame skips stay at DEBUG (log spam on cloudy nights); a
        # WARNING summary is emitted at most once per cooldown so the user can
        # see "calibration is running but skipping frames" without the noise.
        self._skipped_frames = 0
        self._last_skip_summary_t = 0.0
        # Basin escape (see BASIN_ESCAPE_FAILURES). _escape_attempt marks the
        # in-flight refinement as a seedless bootstrap whose result may
        # replace the current model without the RMS-regression guard — but
        # only when it was admitted on evidence (model_replacement).
        self._consecutive_refine_failures = 0
        self._last_escape_time = 0.0
        self._escape_attempt = False
        # Back-off counter, separate from _consecutive_refine_failures: that
        # one drives basin escape and deliberately ignores cold-start and
        # stale-seed failures. Back-off must count every fruitless run.
        self._refine_backoff_failures = 0
        # Cross-run pole consensus (pole_consensus.py). Survives set_model /
        # clear_model: it describes the field, not the model.
        self._pole_history = PoleHistory()
        self._lat = 0.0
        self._lon = 0.0
        self._check_refine.connect(self._maybe_refine)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_model(self, path: str) -> None:
        """Load an existing calibration model from disk."""
        model = FisheyeModel.try_load(path)
        if model and model.is_valid():
            self._model = model
            self._quality = model_quality(
                model, model.n_images, model.span_minutes,
            )
            log.info(f"CalibrationService loaded model: {model}, "
                     f"quality={self._quality}")

    def clear_model(self) -> None:
        """Forget the current model (user-initiated reset).

        In-flight worker results are invalidated via the generation counter.
        The frame buffer is kept: the accumulated detections are still valid
        sky data, so a cold-start bootstrap can begin immediately instead of
        waiting another 35 minutes.
        """
        self._model = None
        self._model_generation += 1
        self._consecutive_refine_failures = 0
        self._refine_backoff_failures = 0
        self._escape_attempt = False
        if self._quality != CalibrationQuality.NONE:
            self._quality = CalibrationQuality.NONE
        log.info("CalibrationService: model cleared (user reset); "
                 f"{self.frame_count} buffered frame(s) kept")

    def set_model(self, model: FisheyeModel) -> None:
        """
        Inject a model directly (e.g. after the user clicks Calibrate Now).
        Resets the frame buffer so accumulation starts fresh.
        """
        self._model = model
        self._model_generation += 1
        self._consecutive_refine_failures = 0
        self._refine_backoff_failures = 0
        self._escape_attempt = False
        new_q = model_quality(model, model.n_images, model.span_minutes)
        with self._lock:
            self._frames.clear()
        if new_q != self._quality:
            self._quality = new_q
            self.quality_upgraded.emit(self._quality, model)

    def feed_frame(
        self,
        image,
        dt: datetime,
        lat: float,
        lon: float,
    ) -> None:
        """
        Accept a new frame for calibration accumulation.

        Thread-safe.  Called from the image-processor worker thread.
        Detects stars inline (~50 ms), stores only detection data.
        """
        if lat == 0.0 and lon == 0.0:
            return
        with self._lock:
            self._lat, self._lon = lat, lon

        # ------ Always detect + accumulate detections -----------------
        # Both paths need the buffer: refinement (when a model exists) and the
        # cold-start multi-image bootstrap (when one doesn't). A single frame on
        # an obstructed sky can't calibrate alone, but accumulating detections
        # across the rotating sky gives the joint fit enough cross-sky coverage.
        frame = self._detect_frame(image, dt, lat, lon)
        if frame is None:
            self._skipped_frames += 1
            now = time.monotonic()
            if self._last_skip_summary_t == 0.0:
                # Start the summary window on the first skip (stay quiet for now).
                self._last_skip_summary_t = now
            elif now - self._last_skip_summary_t >= REFINE_COOLDOWN_S:
                log.warning(
                    f"Calibration skipped {self._skipped_frames} frame(s) in the "
                    "last cycle (too few stars / detection failed) — sky may be "
                    "cloudy or the lens obstructed."
                )
                self._skipped_frames = 0
                self._last_skip_summary_t = now
            return

        with self._lock:
            self._frames.append(frame)
            if len(self._frames) > MAX_BUFFER:
                self._frames.pop(0)

        # ------ Fast path: instant single-image fix on easy skies ------
        # While no model exists, also try a single-image calibration so clear,
        # unobstructed installs get an overlay on the first frame. Failures are
        # expected on obstructed scenes and are harmless — the accumulated buffer
        # drives the bootstrap. Cooldown-guarded (the attempt is ~30s).
        if self._model is None:
            now = time.monotonic()
            if (now - self._last_initial_attempt_time >= INITIAL_COOLDOWN_S
                    and self._pending_initial is None
                    and self._initial_worker is None):
                self._pending_initial = (image.copy(), dt, lat, lon)

        self._check_refine.emit()

    def shutdown(self) -> None:
        """Stop any running workers cleanly."""
        for w in (self._refine_worker, self._initial_worker):
            if w and w.isRunning():
                w.quit()
                w.wait(3000)

    def validate_against_pole(self, model: FisheyeModel) -> tuple:
        """Check a candidate model against the consensus celestial pole.

        For manual paths (Calibrate Now, guided) whose results bypass the
        refine worker. Returns (ok, message); ok=True when no pole estimate
        is available — the pole is an optional constraint, never a gate on
        its own absence.

        Measures the pole from the buffer NOW and judges it alongside what
        the refine worker has recorded (PoleHistory.evaluate) without
        recording it. The history alone is empty on a fresh install — it is
        populated only by refine runs, which need a 35-min, 15-frame span —
        so the first Calibrate Now / guided solve, whose result is saved to
        disk and seeds every later refinement, would otherwise run ungated
        while a measurement was sitting in the same buffer. Not recording
        it is what keeps one physical window from counting as a "repeated"
        rotation vote (the mirror also needs non-overlapping windows now).
        find_pole is ~35 ms on a full 60-frame buffer of 200 detections:
        fine on the GUI thread for a user-initiated action.

        The buffer frames are fed post-resize (image_processor feeds the
        preview-resolution frame, see ImageProcessorWorker), while manual and
        guided calibration fit `model` against the pre-resize raw cached
        frame — a different resolution whenever resize_percent < 100. The
        buffer's median resolution is passed through so validate_pole can
        rescale the model into the pole's frame before comparing pixels
        (docs/ALLSKY_POLE_ANCHOR_PLAN.md P1); omitting it here silently
        re-introduces the cross-resolution comparison bug.
        """
        with self._lock:
            # Frame dicts are never mutated after append; a shallow copy
            # is enough for find_pole to read them off the lock.
            frames = list(self._frames)
            sky_r = median_sky_r(frames)
            pole_w, pole_h = median_frame_resolution(frames)
        try:
            fresh = find_pole(frames, self._lat) if frames else None
            pole = self._pole_history.evaluate(fresh, sky_r, pole_w, pole_h)
        except Exception as e:
            log.debug(f"Pole consensus failed (non-fatal): {e}")
            return True, "pole estimation unavailable"
        return admit_manual(model, self._lat, pole, sky_r,
                            pole_image_width=pole_w, pole_image_height=pole_h)

    @property
    def current_quality(self) -> str:
        return self._quality

    @property
    def current_model(self) -> Optional[FisheyeModel]:
        return self._model

    @property
    def frame_count(self) -> int:
        with self._lock:
            return len(self._frames)

    # ------------------------------------------------------------------
    # Frame detection (runs on caller's thread — image-processor worker)
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_frame(image, dt, lat, lon) -> Optional[dict]:
        """Detect stars and compute catalog AltAz for one frame."""
        try:
            circle = measure_sky_circle(image)
            if circle is None:
                log.debug("CalibrationService: no measurable sky circle "
                          "(no illuminated disc) — skipping frame")
                return None
            sky_cx, sky_cy, sky_r = circle
            detected = detect_stars(
                image, max_stars=200,
                sky_cx=sky_cx, sky_cy=sky_cy, sky_radius=sky_r,
            )
            if len(detected) < 5:
                log.debug(f"CalibrationService: {len(detected)} stars — "
                          "too few, skipping frame")
                return None

            catalog = get_bright_stars(max_mag=6.5)
            above_horizon = []
            for s in catalog:
                alt, az = radec_to_altaz(
                    s['ra_deg'], s['dec_deg'], lat, lon, dt,
                )
                if float(alt) > 3.0:
                    above_horizon.append((s, float(alt), float(az)))
            above_horizon.sort(key=lambda x: x[0]['vmag'])

            img_w = image.width if hasattr(image, 'width') else 0
            img_h = image.height if hasattr(image, 'height') else 0
            return {
                'dt': dt,
                'detected': detected,
                'above_horizon': above_horizon,
                'sky_cx': sky_cx,
                'sky_cy': sky_cy,
                'sky_r': sky_r,
                'image_width': img_w,
                'image_height': img_h,
            }
        except Exception as e:
            log.warning(f"CalibrationService frame detection failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Refinement triggering (runs on main thread via _check_refine)
    # ------------------------------------------------------------------

    def _maybe_refine(self) -> None:
        """Check thresholds and start the appropriate worker."""
        # --- Guard: a worker is still live ---
        # `is not None` rather than isRunning(): the slot is None only once
        # _retire_worker has run, so a worker is never dropped (and possibly
        # garbage-collected) between finishing and being retired.
        if self._refine_worker is not None:
            return
        if self._initial_worker is not None:
            return

        # --- Fast path: single-image initial cal when queued ---
        if self._model is None and self._pending_initial is not None:
            self._start_initial_cal()
            return

        # --- Cooldown (shared by refinement and cold-start bootstrap) ---
        now = time.monotonic()
        if now - self._last_refine_time < self._refine_cooldown():
            return

        # --- Threshold checks ---
        # Cold start (no model) demands a long baseline to break the near-zenith
        # rotational degeneracy; refining an existing model only needs a few min.
        # Basin escape reuses the cold-start path: after repeated rejections the
        # on-disk model is suspect and must not seed the fit.
        escape = (self._model is not None
                  and self._consecutive_refine_failures >= BASIN_ESCAPE_FAILURES
                  and now - self._last_escape_time >= ESCAPE_COOLDOWN_S)
        cold_start = self._model is None or escape
        min_frames = MIN_FRAMES_BOOTSTRAP if cold_start else MIN_FRAMES
        min_span = MIN_SPAN_BOOTSTRAP_MINUTES if cold_start else MIN_SPAN_MINUTES
        with self._lock:
            n = len(self._frames)
            if n < min_frames:
                return

            dts = [f['dt'] for f in self._frames]
            span_s = (max(dts) - min(dts)).total_seconds()
            span_min = span_s / 60.0
            if span_min < min_span:
                return

            # Shallow: frame dicts and their 'detected'/'above_horizon' lists
            # are never mutated after append, and every consumer
            # (refine_from_detections, find_pole, model_admission) reads them
            # only. Deep-copying cost ~43 MB per refinement (measured, 60
            # frames x 8.4k catalogue entries) because it duplicated the shared
            # catalogue star dicts once per frame; a snapshot list costs ~0.
            frames_copy = list(self._frames)

        # An escape presumes the seed is the problem. Hold the incumbent to
        # the same bright-anchor test its refinements keep failing: if it
        # passes on the recent frames, the refinements are what is broken
        # (2026-09-05: 26 rejections while the incumbent drew a correct
        # overlay; the escape installed a wrong-basin model). Refine as
        # usual instead and re-ask after the escape cooldown.
        if escape:
            self._last_escape_time = now
            health = incumbent_anchor_health(self._model, frames_copy)
            if health is True:
                log.warning(
                    f"CalibrationService: {self._consecutive_refine_failures} "
                    "consecutive refinement rejections, but the current model "
                    "passes the bright-anchor check on the recent frames — the "
                    "seed is healthy and the refinements are what is failing. "
                    "Not escaping; keeping the current model.")
                escape = False
                cold_start = False
        self._escape_attempt = escape

        # seed=None -> _RefineWorker bootstraps a coarse orientation seed
        # (cold start / basin escape). Otherwise it refines the existing model.
        if escape:
            log.warning(
                f"CalibrationService: {self._consecutive_refine_failures} "
                "consecutive refinement rejections \u2014 the current model may be "
                "a wrong-basin fit poisoning the seed. Attempting a seedless "
                "re-calibration (basin escape)."
            )
        mode = ("basin escape" if escape
                else "cold-start bootstrap" if cold_start else "refinement")
        log.info(f"CalibrationService: triggering {mode} "
                 f"({n} frames, {span_min:.1f} min span)")
        self.status_changed.emit(
            f"{'Calibrating' if cold_start else 'Refining'} ({n} frames)\u2026")
        self._last_refine_time = now
        self._refine_gen = self._model_generation  # snapshot for stale-result detection

        self._refine_worker = _RefineWorker(
            frames_copy, None if cold_start else self._model, n, span_min,
            lat=self._lat, incumbent=self._model,
            pole_history=self._pole_history,
        )
        self._refine_worker.result_ready.connect(self._on_refine_done)
        self._refine_worker.failed.connect(self._on_refine_failed)
        self._refine_worker.incumbent_corroborated.connect(
            self._on_incumbent_corroborated)
        self._refine_worker.finished.connect(
            functools.partial(self._retire_worker, self._refine_worker))
        self._refine_worker.start()

    def _on_incumbent_corroborated(self, why: str) -> None:
        """Persist the 'pole' stamp incumbent_evidence put on the current
        model (the worker mutates the shared instance; only this thread
        writes the file). A model swapped in meanwhile carries its own
        provenance and is left alone."""
        if self._refine_gen != self._model_generation or self._model is None:
            return
        log.info(f"CalibrationService: {why} — model now locks mirror/scale/"
                 "basin against automatic replacements")
        self._save_model(self._model, stamp_time=False)

    def _refine_cooldown(self) -> float:
        """Seconds to wait after the last refinement before trying again."""
        n = min(self._refine_backoff_failures, REFINE_BACKOFF_MAX_DOUBLINGS)
        return min(float(REFINE_COOLDOWN_S * (2 ** n)),
                   float(REFINE_COOLDOWN_MAX_S))

    def _retire_worker(self, worker) -> None:
        """Free a finished worker and everything it pinned.

        Connected to QThread.finished, so it runs on this object's thread
        after run() has returned - safe to delete the QThread. The worker is
        bound at connect time rather than read from sender(): a None sender
        would leave the slot occupied forever and silently stop all further
        refinement on a 24/7 process.
        """
        release = getattr(worker, 'release', None)
        if release is not None:
            release()
        if self._refine_worker is worker:
            self._refine_worker = None
        if self._initial_worker is worker:
            self._initial_worker = None
        worker.deleteLater()

    # ------------------------------------------------------------------
    # Initial single-image calibration
    # ------------------------------------------------------------------

    def _start_initial_cal(self) -> None:
        if self._initial_worker is not None:
            return

        image, dt, lat, lon = self._pending_initial
        self._last_initial_attempt_time = time.monotonic()
        self._initial_gen = self._model_generation  # stale-result snapshot
        log.info("CalibrationService: starting initial single-image calibration")
        self.status_changed.emit("Auto-calibrating\u2026")

        self._initial_worker = _InitialCalWorker(image, lat, lon, dt)
        self._initial_worker.result_ready.connect(self._on_initial_done)
        self._initial_worker.failed.connect(self._on_initial_failed)
        self._initial_worker.finished.connect(
            functools.partial(self._retire_worker, self._initial_worker))
        self._initial_worker.start()

    def _on_initial_done(self, model: FisheyeModel) -> None:
        self._pending_initial = None
        # Discard if the model changed while the worker was running (manual
        # Calibrate Now, guided result, or a reset). Snapshot comparison, not
        # `generation > 0`: the latter would also discard every legitimate
        # auto-calibration attempted after a user reset.
        if self._initial_gen != self._model_generation:
            log.info("Discarding initial auto-calibration — model was replaced while calibrating")
            return
        pole_ok, pole_msg = self.validate_against_pole(model)
        if not pole_ok:
            log.warning(f"Initial auto-calibration rejected: {pole_msg}")
            self.status_changed.emit(
                "Auto-calibration rejected by the pole check — accumulating "
                "more frames.")
            return
        self._model = model
        model.n_images = 1
        model.span_minutes = 0.0

        self._quality = model_quality(model, 1, 0.0)
        self._save_model(model)

        log.info(f"Initial calibration succeeded: {model}, "
                 f"quality={self._quality}")
        self.status_changed.emit(
            f"Calibrated: {model.n_matches} stars, "
            f"RMS={model.rms_residual:.1f}px ({self._quality})"
        )
        self.quality_upgraded.emit(self._quality, model)

    def _on_initial_failed(self, error: str) -> None:
        self._pending_initial = None
        log.warning(
            f"Initial auto-calibration failed: {error}. "
            f"Next attempt allowed in {INITIAL_COOLDOWN_S}s."
        )
        # Short message for the panel — full detail stays in the log.
        self.status_changed.emit(
            f"Auto-calibration failed — will retry in {INITIAL_COOLDOWN_S // 60} min. (See logs)"
        )

    # ------------------------------------------------------------------
    # Multi-image refinement results
    # ------------------------------------------------------------------

    def _on_refine_done(self, model: FisheyeModel, n_images: int, span_min: float,
                        evidence: bool = False) -> None:
        # Restart the cooldown from completion, not from the trigger: a run
        # lasts 40 s to several minutes (see REFINE_BACKOFF_MAX_DOUBLINGS).
        self._last_refine_time = time.monotonic()
        self._refine_backoff_failures = 0
        # Discard if Calibrate Now replaced the model while the worker was running.
        if self._refine_gen != self._model_generation:
            log.info("Discarding stale refinement — model was replaced during calibration")
            return

        model.n_images = n_images
        model.span_minutes = round(span_min, 1)

        new_q = model_quality(model, n_images, span_min)
        improved, why = should_replace(
            self._model, self._quality, model, new_q,
            escape=self._escape_attempt, evidence=evidence)
        if self._escape_attempt:
            (log.warning if improved else log.info)(f"Basin escape result: {why}")

        self._escape_attempt = False
        if improved:
            self._consecutive_refine_failures = 0
            self._model = model
            self._quality = new_q
            self._save_model(model)

            log.info(f"Calibration refined: {model}, quality={new_q}")
            self.status_changed.emit(
                f"Refined: {model.n_matches} stars, "
                f"RMS={model.rms_residual:.1f}px ({new_q})"
            )
            self.quality_upgraded.emit(new_q, model)
        else:
            # A completed, gate-passing refinement means the seed basin is
            # healthy even if this particular fit wasn't better.
            self._consecutive_refine_failures = 0
            log.info(
                f"Refinement did not improve model "
                f"(RMS={model.rms_residual:.2f}px vs "
                f"{self._model.rms_residual:.2f}px)"
            )
            self.status_changed.emit(
                f"Calibrated: {self._model.n_matches} stars, "
                f"RMS={self._model.rms_residual:.1f}px ({self._quality})"
            )

    def _on_refine_failed(self, error: str) -> None:
        self._escape_attempt = False
        self._last_refine_time = time.monotonic()
        self._refine_backoff_failures += 1
        if self._model:
            # Only count failures of refinements seeded by the CURRENT model —
            # a late failure from a superseded seed says nothing about it.
            if self._refine_gen == self._model_generation:
                self._consecutive_refine_failures += 1
            log.warning(
                f"Calibration refinement failed "
                f"({self._consecutive_refine_failures} consecutive): {error}. "
                f"Next attempt in {self._refine_cooldown() / 60.0:.0f} min.")
            # Restore previous status text
            self.status_changed.emit(
                f"Calibrated: {self._model.n_matches} stars, "
                f"RMS={self._model.rms_residual:.1f}px ({self._quality})"
            )
        else:
            # Cold-start bootstrap not yet successful — keep accumulating.
            log.info(f"Cold-start calibration not yet successful: {error}")
            self.status_changed.emit("Calibrating… (accumulating frames)")

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_model(self, model: FisheyeModel, stamp_time: bool = True) -> None:
        """Save model to the production calibration file.

        The file being overwritten is copied to the backup path first: an
        automatic replacement is the one write the user did not ask for, and
        on 2026-09-05 it destroyed the only copy of a correct model.
        `stamp_time=False` re-saves the same model (a provenance stamp)
        without moving its calibration timestamp.
        """
        try:
            from services.app_config import (
                get_calibration_backup_path, get_calibration_path)
            cal_path = get_calibration_path()
            if stamp_time and os.path.isfile(cal_path):
                try:
                    shutil.copyfile(cal_path, get_calibration_backup_path())
                except OSError as e:
                    log.warning(f"Could not back up the previous calibration: {e}")
            if stamp_time:
                model.calibrated_at = datetime.now(timezone.utc).isoformat()
            model.save(cal_path)
            log.info(f"Calibration saved to {cal_path}")
        except Exception as e:
            log.error(f"Failed to save calibration: {e}")
            self.status_changed.emit(f"Calibration save failed: {e}")
