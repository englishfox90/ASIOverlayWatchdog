"""
All-Sky Overlay Controller.

Manages:
  - Calibration trigger (runs in background QThread)
  - Background calibration accumulation service
  - Config save/load for allsky_overlay section
  - Signals to panel for status updates
"""
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

from PySide6.QtCore import QObject, Signal, QThread, QTimer

from services.logger import app_logger as log
from services.notifications import CALIBRATION_DONE, NotificationEvent

if TYPE_CHECKING:
    from ui.main_window import MainWindow

# Frames wider/taller than this ratio almost certainly crop the fisheye
# circle — the all-sky feature assumes the full sky circle is in frame
# (square-ish sensor + fisheye lens). Warn, don't block: a wide sensor whose
# lens image circle fits the short edge can still calibrate.
_MAX_SQUARE_ASPECT = 1.2


def _aspect_warning(image) -> Optional[str]:
    """Human-readable warning when a frame is far from square, else None."""
    w = int(getattr(image, 'width', 0) or 0)
    h = int(getattr(image, 'height', 0) or 0)
    if not w or not h:
        return None
    if max(w, h) / min(w, h) <= _MAX_SQUARE_ASPECT:
        return None
    return (
        f"frame is {w}x{h} — the all-sky feature is designed for a fisheye "
        "lens on a square (or near-square) sensor with the whole sky circle "
        "in frame. A wide sensor usually crops the circle, and calibration "
        "will not work correctly."
    )


def _short_cal_error(error_msg: str) -> str:
    """Summarise a calibration error into a one-line UI status.

    The raw CalibrationError messages embed diagnostic detail (per-star
    pixel misses, fallback chaining) that's useful in the log but too
    noisy for the small status label on the AllSky panel.
    """
    lower = error_msg.lower()
    if 'pole' in lower:
        return ("Calibration rejected — it disagrees with the measured "
                "celestial-pole position. Let capture run longer, then retry. "
                "(See logs)")
    if 'bright-anchor' in lower or 'bright anchors' in lower:
        return ("Calibration rejected — star alignment was off. "
                "Try again on a clearer night or check lat/lon. (See logs)")
    if 'triangle match' in lower and 'failed' in lower:
        return "Calibration failed — couldn't match star patterns. (See logs)"
    if 'need' in lower and 'star' in lower:
        return "Calibration failed — not enough stars detected. (See logs)"
    if 'scipy' in lower:
        return "Calibration failed — internal dependency error. (See logs)"
    # Generic fallback: first ~100 chars, trimmed at a sensible break
    short = error_msg.split('.')[0].split(';')[0].split('(')[0].strip()
    if len(short) > 120:
        short = short[:117] + '…'
    return f"Calibration failed — {short}. (See logs)"


class CalibrationWorker(QThread):
    """Background thread: detect stars, match, fit fisheye model."""

    progress = Signal(str)       # Status message
    finished = Signal(object)    # FisheyeModel on success
    failed   = Signal(str)       # Error message on failure

    def __init__(self, image, lat: float, lon: float, dt, parent=None):
        super().__init__(parent)
        self._image = image
        self._lat = lat
        self._lon = lon
        self._dt = dt

    def run(self):
        try:
            from services.allsky.calibration import calibrate, CalibrationError
            self.progress.emit("Detecting stars…")
            model = calibrate(
                self._image,
                lat_deg=self._lat,
                lon_deg=self._lon,
                dt=self._dt,
            )
            self.finished.emit(model)
        except Exception as e:
            self.failed.emit(str(e))


class GuidedCalibrationWorker(QThread):
    """Background thread: solve a fisheye model from user-identified anchors."""

    finished = Signal(object)    # FisheyeModel on success
    failed   = Signal(str)       # Error message on failure

    def __init__(self, anchors, lat, lon, dt, sky_cx, sky_cy, sky_r,
                 img_w, img_h, parent=None):
        super().__init__(parent)
        self._anchors = anchors
        self._lat, self._lon, self._dt = lat, lon, dt
        self._sky_cx, self._sky_cy, self._sky_r = sky_cx, sky_cy, sky_r
        self._img_w, self._img_h = img_w, img_h

    def run(self):
        try:
            from services.allsky.guided_calibration import calibrate_from_anchors
            model = calibrate_from_anchors(
                self._anchors, self._lat, self._lon, self._dt,
                self._sky_cx, self._sky_cy, self._sky_r,
                image_width=self._img_w, image_height=self._img_h,
            )
            self.finished.emit(model)
        except Exception as e:
            self.failed.emit(str(e))


class AllSkyController(QObject):
    """
    Business logic for the All-Sky Settings panel.

    Signals:
        status_changed(str): Human-readable calibration status message.
        calibration_done(dict): Emitted with model_info after successful calibration.
        settings_changed(): Emitted when any setting is changed (triggers config save).
    """

    status_changed   = Signal(str)
    quality_changed  = Signal(str)   # CalibrationQuality level string
    calibration_done = Signal(dict)
    settings_changed = Signal()

    def __init__(self, main_window: 'MainWindow', parent=None):
        super().__init__(parent)
        self._mw = main_window
        self._worker: Optional[CalibrationWorker] = None
        self._model = None
        self._aspect_note: Optional[str] = None  # non-square-frame warning

        # Background calibration accumulation service
        from services.allsky.calibration_service import CalibrationService
        self._cal_service = CalibrationService(parent=self)
        self._cal_service.quality_upgraded.connect(self._on_quality_upgraded)
        self._cal_service.status_changed.connect(self.status_changed)

        # Load existing model into both controller and service
        self._update_status()

    # ------------------------------------------------------------------
    # Public API (called by panel)
    # ------------------------------------------------------------------

    def load_from_config(self) -> None:
        """Refresh panel state from current config."""
        self._update_status()

    def start_calibration(self, image=None) -> None:
        """
        Begin background calibration.

        If image is None, uses the most recent raw frame cached by
        MainWindow (set for both Watch mode and Camera mode).
        """
        log.info("Calibrate Now clicked")
        if self._worker and self._worker.isRunning():
            log.warning("Calibrate Now ignored — calibration already in progress")
            self.status_changed.emit("Calibration already in progress…")
            return

        if image is None:
            image, source = self._get_latest_frame()
            if image is not None:
                log.info(f"Calibrate Now using image from {source}")

        if image is None:
            log.warning(
                "Calibrate Now: no image available. Start capture (Camera mode) "
                "or wait for the watcher to process a frame (Watch mode)."
            )
            self.status_changed.emit("No image available — start capture first.")
            return

        # No pre-resize: calibrate() resolution-binds the model to whatever
        # frame it is given (model.image_width/height), and the renderer scales
        # the model to the actual render resolution (overlay_renderer.py). A
        # manual resize here would just double-resize the watch-mode frame,
        # which is already at output resolution.

        self._aspect_note = _aspect_warning(image)
        if self._aspect_note:
            log.warning(f"Calibrate Now: {self._aspect_note}")

        lat = float(self._mw.config.get('weather', {}).get('latitude', 0) or 0)
        lon = float(self._mw.config.get('weather', {}).get('longitude', 0) or 0)
        dt = self._frame_capture_time()

        if lat == 0.0 and lon == 0.0:
            log.warning("Calibrate Now: lat/lon not configured (both zero)")
            self.status_changed.emit(
                "Warning: lat/lon not configured. Set in Output > Weather Settings."
            )

        log.info(f"Calibrate Now starting worker (lat={lat}, lon={lon}, dt={dt.isoformat()})")
        self.status_changed.emit("Calibrating… detecting stars")
        self._worker = CalibrationWorker(image, lat, lon, dt, parent=self)
        self._worker.progress.connect(self.status_changed)
        self._worker.finished.connect(self._on_calibration_done)
        self._worker.failed.connect(self._on_calibration_failed)
        self._worker.start()

    def prepare_guided_calibration(self) -> Optional[dict]:
        """Gather everything the guided-calibration dialog needs.

        Returns a dict with the latest clean frame, its detected star centroids
        (so clicks snap to real stars), the sky circle, the capture time, and the
        list of bright catalog stars currently above the horizon (name + RA/Dec
        for the user to pick from). Returns None if no frame is available.
        """
        image, source = self._get_latest_frame()
        if image is None:
            self.status_changed.emit("No image available — start capture first.")
            return None

        self._aspect_note = _aspect_warning(image)
        if self._aspect_note:
            log.warning(f"Guided calibration: {self._aspect_note}")

        lat = float(self._mw.config.get('weather', {}).get('latitude', 0) or 0)
        lon = float(self._mw.config.get('weather', {}).get('longitude', 0) or 0)
        if lat == 0.0 and lon == 0.0:
            self.status_changed.emit(
                "Set latitude/longitude in Output > Weather Settings first.")
            return None

        dt = self._frame_capture_time()
        from services.allsky.star_centroid import (
            detect_stars, estimate_sky_circle, stretch_for_display)
        from services.allsky.catalogs import get_bright_stars
        from services.allsky.coords import radec_to_altaz
        from services.allsky.render_stars import star_display_name

        sky_cx, sky_cy, sky_r = estimate_sky_circle(image)
        detections = detect_stars(image, max_stars=300,
                                  sky_cx=sky_cx, sky_cy=sky_cy, sky_radius=sky_r)
        candidates = []
        for s in get_bright_stars(max_mag=3.5):
            alt, az = radec_to_altaz(s['ra_deg'], s['dec_deg'], lat, lon, dt)
            if float(alt) > 15.0:
                # Many bright stars have no proper name; fall back to the Bayer
                # designation, then the HR catalogue number, so the picker never
                # shows a blank entry.
                name = (star_display_name(s, True)
                        or (f"HR {s['hr']}" if s.get('hr') else 'Unknown star'))
                candidates.append({
                    'name': name, 'ra_deg': s['ra_deg'],
                    'dec_deg': s['dec_deg'], 'alt': float(alt), 'az': float(az),
                    'vmag': float(s.get('vmag', 0.0)),
                })
        candidates.sort(key=lambda c: c['vmag'])
        # A failed stretch must not cost the user the dialog itself — guided
        # calibration is often the only path that solves on a given rig, so
        # degrade to the (dark, but usable) linear frame rather than raising.
        try:
            display_image = stretch_for_display(image)
        except Exception as e:
            log.warning(f"Guided calibration: display stretch failed, "
                        f"showing the linear frame instead: {e}")
            display_image = image

        log.info(f"Guided calibration prep: {len(detections)} detections, "
                 f"{len(candidates)} bright stars above horizon ({source})")
        return {
            'image': image, 'display_image': display_image,
            'detections': detections,
            'sky_cx': sky_cx, 'sky_cy': sky_cy, 'sky_r': sky_r,
            'lat': lat, 'lon': lon, 'dt': dt, 'candidates': candidates,
            'image_width': getattr(image, 'width', 0),
            'image_height': getattr(image, 'height', 0),
        }

    def start_guided_calibration(self, anchors, prep: dict) -> None:
        """Solve from user anchors in the background, then save like Calibrate Now.

        anchors: list of (pixel_x, pixel_y, ra_deg, dec_deg).
        prep:    the dict returned by prepare_guided_calibration().
        """
        if self._worker and self._worker.isRunning():
            self.status_changed.emit("Calibration already in progress…")
            return
        log.info(f"Guided calibration starting with {len(anchors)} anchors")
        self.status_changed.emit("Solving from identified stars…")
        self._worker = GuidedCalibrationWorker(
            anchors, prep['lat'], prep['lon'], prep['dt'],
            prep['sky_cx'], prep['sky_cy'], prep['sky_r'],
            prep.get('image_width', 0), prep.get('image_height', 0),
            parent=self)
        self._worker.finished.connect(self._on_calibration_done)
        self._worker.failed.connect(self._on_calibration_failed)
        self._worker.start()

    def reset_calibration(self) -> None:
        """Delete the saved calibration and forget the in-memory model.

        The remedy for a poisoned (wrong-basin) model: without it the
        background service returns to a clean cold-start bootstrap instead
        of refining a bad seed forever. The service keeps its frame buffer
        so auto-calibration can restart immediately; any in-flight worker
        result is invalidated by the service's generation counter.
        """
        if self._worker and self._worker.isRunning():
            self.status_changed.emit(
                "Cannot reset while a calibration is running — wait for it "
                "to finish.")
            return

        import os
        from services.app_config import get_calibration_path
        cal_path = get_calibration_path()
        try:
            if os.path.isfile(cal_path):
                os.remove(cal_path)
        except OSError as e:
            log.error(f"Calibration reset: could not delete {cal_path}: {e}")
            self.status_changed.emit(
                f"Reset failed — could not delete the calibration file: {e}")
            return

        self._model = None
        self._cal_service.clear_model()

        # Clear the config pointer so the overlay renderer stops immediately;
        # the next successful calibration re-sets it.
        allsky_cfg = dict(self._mw.config.get('allsky_overlay', {}))
        allsky_cfg['calibration_file'] = ''
        self._mw.config.set('allsky_overlay', allsky_cfg)
        self._mw.config.save()

        log.info(f"All-sky calibration reset by user (deleted {cal_path})")
        self.status_changed.emit(
            "Calibration reset — auto-calibration will start over as frames "
            "accumulate, or use Guided Calibration.")
        self.quality_changed.emit('none')
        self.settings_changed.emit()

    @property
    def calibration_service(self):
        """The background calibration accumulation service."""
        return self._cal_service

    def get_calibration_info(self) -> Optional[dict]:
        """Return a summary dict of the current calibration model."""
        if self._model is None:
            return None
        return {
            'rms_residual': self._model.rms_residual,
            'n_matches': self._model.n_matches,
            'calibrated_at': self._model.calibrated_at,
            'a1': self._model.a1,
            'cx': self._model.cx,
            'cy': self._model.cy,
        }

    def shutdown(self) -> None:
        """Stop any running calibration threads and background service."""
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(3000)
        self._cal_service.shutdown()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_calibration_done(self, model) -> None:
        from services.app_config import get_calibration_path

        # Pole check: the background service measures the celestial pole from
        # accumulated frames; a manual result that contradicts it is a
        # wrong-basin fit and must not reach disk (a saved wrong-basin model
        # poisons every subsequent refinement).
        pole_ok, pole_msg = self._cal_service.validate_against_pole(model)
        if not pole_ok:
            self._on_calibration_failed(f"pole check failed: {pole_msg}")
            return

        self._model = model
        info = self.get_calibration_info()

        # Persist model JSON
        cal_path = get_calibration_path()
        try:
            model.save(cal_path)
            # Update config with new calibration path
            allsky_cfg = dict(self._mw.config.get('allsky_overlay', {}))
            allsky_cfg['calibration_file'] = cal_path
            self._mw.config.set('allsky_overlay', allsky_cfg)
            self._mw.config.save()
        except Exception as e:
            log.error(f"Failed to save calibration: {e}")

        # Notify the background service so it uses this model as its seed
        # and resets its frame buffer for fresh accumulation.
        self._cal_service.set_model(model)

        from services.allsky.calibration_service import model_quality
        quality = model_quality(model, model.n_images, model.span_minutes)

        msg = (f"Calibrated: {model.n_matches} stars, "
               f"RMS={model.rms_residual:.2f}px ({quality})")
        # Guided-solve rescue note (excluded/reassigned anchors) — the user
        # must see which of their identifications didn't fit.
        note = getattr(model, 'guided_note', None)
        if note:
            msg += f" — {note}"
        self.status_changed.emit(msg)
        self.quality_changed.emit(quality)
        self.calibration_done.emit(info)
        self.settings_changed.emit()

        self._notify_calibration_done(info)

    def _on_calibration_failed(self, error_msg: str) -> None:
        log.warning(f"All-sky calibration failed: {error_msg}")
        msg = _short_cal_error(error_msg)
        if self._aspect_note:
            msg += " Note: " + self._aspect_note
        self.status_changed.emit(msg)

    def _update_status(self) -> None:
        """Load existing model and emit current status."""
        cal_path = self._mw.config.get('allsky_overlay', {}).get('calibration_file', '')
        if cal_path:
            from services.allsky.fisheye import FisheyeModel
            model = FisheyeModel.try_load(cal_path)
            if model and model.is_valid():
                self._model = model
                # Seed the background service with the existing model
                self._cal_service.load_model(cal_path)
                from services.allsky.calibration_service import model_quality
                quality = model_quality(
                    model, model.n_images, model.span_minutes,
                )
                ts = model.calibrated_at[:10] if model.calibrated_at else 'unknown date'
                self.status_changed.emit(
                    f"Calibrated ({ts}): {model.n_matches} stars, "
                    f"RMS={model.rms_residual:.2f}px ({quality})"
                )
                self.quality_changed.emit(quality)
                return
        self.status_changed.emit("Not calibrated — click 'Calibrate Now'")
        self.quality_changed.emit('none')

    def _on_quality_upgraded(self, quality: str, model) -> None:
        """Handle quality upgrade from the background service."""
        self._model = model
        info = self.get_calibration_info()
        # Update config path (service already saved the file)
        from services.app_config import get_calibration_path
        cal_path = get_calibration_path()
        allsky_cfg = dict(self._mw.config.get('allsky_overlay', {}))
        allsky_cfg['calibration_file'] = cal_path
        self._mw.config.set('allsky_overlay', allsky_cfg)
        self._mw.config.save()

        self.quality_changed.emit(quality)
        self.calibration_done.emit(info)
        self.settings_changed.emit()

    def _get_latest_frame(self):
        """Return (image, source_description) for the most recent clean frame.

        Tries, in order:
          MainWindow.cached_raw_frame() — Camera mode rebuilds the RAW
          pre-overlay frame from the Bayer bytes cached in on_image_captured;
          Watch mode returns the clean (no all-sky) output frame cached in
          _on_image_processed.

        The old "load the last saved output image from disk" fallback was
        removed: that file is overlay-contaminated and already resized, so
        calibrating on it produced misaligned models. If no clean in-memory
        frame exists we fail with a clear status message instead.

        Returns (None, '') if nothing is available.
        """
        accessor = getattr(self._mw, 'cached_raw_frame', None)
        if accessor is not None:
            # Camera mode rebuilds the frame from cached Bayer bytes (~0.9 s
            # at 3552^2) — acceptable on an explicit Calibrate Now click.
            image, _meta = accessor()
            if image is not None:
                return image, "cached raw frame"
            return None, ""

        cached = getattr(self._mw, '_cached_raw_image', None)
        if cached is not None:
            return cached, "cached raw frame"

        return None, ""

    def _frame_capture_time(self) -> datetime:
        """UTC capture time of the cached frame (falls back to now).

        The sky rotates ~0.25°/min, so solving against a stale frame with a
        'now' timestamp shifts every star; the mismatch previously inflated
        guided-calibration residuals past the acceptance limit.
        """
        cached = getattr(self._mw, '_cached_raw_time', None)
        return cached or datetime.now(timezone.utc)

    def _notify_calibration_done(self, info: dict) -> None:
        try:
            rms = info.get('rms_residual', 0) or 0
            n = info.get('n_matches', 0) or 0
            self._mw.notifier.notify(NotificationEvent(
                type=CALIBRATION_DONE,
                title='All-Sky Calibration Complete',
                body=f"All-sky lens calibrated successfully. {n} stars matched, RMS {rms:.2f}px.",
                data={'model_info': info},
            ))
        except Exception as e:
            log.debug(f"Calibration notification failed: {e}")
