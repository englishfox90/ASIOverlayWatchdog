"""
Meteor Controller
Receives detection frames from ImageProcessor, runs the Phase 2+ detection
pipeline in a daemon thread, saves thumbnails, persists events, and handles
user confirmation/rejection.

Detection pipeline (Phase 2–4):
  1. Pre-stretch grayscale detection frame (linear, downscaled) pushed to FrameStack.
  2. FrameStack.transient_map() = max−mean: static scene cancels automatically.
  3. FrameStack.hot_mask(): pixels bright in ALL frames masked (equipment edges).
  4. DiffNoiseEMA → noise_to_threshold(): proper diff-noise adaptive threshold.
  5. detect_meteors() with feathered sky-circle mask and tight Hough maxLineGap.
  6. Streak profile scoring (dash periodicity + peak-fade shape).
  7. PersistenceFilter: single-frame candidate held one frame; if collinear+advanced
     streak appears next frame → plane (reject); else → meteor (report).
"""
import math
import os
import threading
import time
import traceback
from datetime import datetime
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image
from PySide6.QtCore import QObject, Signal, QTimer

from services.logger import app_logger
from services.meteor.detection_scale import DetectionScale, make_scale
from services.meteor.diagnostics import MeteorDiagnostics
from services.meteor.frame_stack import FrameStack
from services.meteor.noise import DiffNoiseEMA, noise_to_threshold
from services.meteor.detector import detect_meteors, MeteorDetection, annotate_image
from services.meteor.streak_profile import sample_profile, dash_score, peak_fade_score
from services.meteor.persistence import PersistenceFilter
from services.meteor.storage import (
    log_detections, log_event, save_thumbnail, resolve_log_path
)
from services.meteor.mask import (
    zone_from_detection, zones_from_config, zones_to_config, ExclusionZone,
)


_MAX_RECENT_EVENTS = 20


class MeteorController(QObject):
    """
    Responsibilities:
    - Receive detection_frame_ready signal from ImageProcessor
    - Maintain an N-frame FrameStack; run detection when stack is full
    - Apply streak profile scoring and persistence filter to classify candidates
    - Save thumbnails, persist to JSONL, handle user confirm/reject
    - Emit status_updated for MeteorPanel
    """

    status_updated = Signal(dict)

    def __init__(self, main_window):
        super().__init__(main_window)
        self._main_window = main_window
        self._lock = threading.Lock()
        self._detection_semaphore = threading.Semaphore(1)

        self._session_frames: int = 0
        self._session_detections: int = 0
        self._last_detection_time: Optional[str] = None
        self._recent_events: List[dict] = []

        # Detection pipeline state
        self._stack: Optional[FrameStack] = None
        self._noise_ema: Optional[DiffNoiseEMA] = None
        self._filter: Optional[PersistenceFilter] = None
        self._detection_scale: Optional[DetectionScale] = None
        self._sky_circle: Optional[Tuple[float, float, float]] = None  # detection coords
        self._frame_idx: int = 0
        self._last_detection_ts: float = 0.0
        # Full-res image of the frame whose candidates the PersistenceFilter is
        # currently holding. Released meteors come from the PREVIOUS frame, so
        # thumbnails must be cropped from that frame — the streak is absent
        # from the current one by definition. Detection-thread access only.
        self._held_full_res: Optional[Image.Image] = None

        self._diag = MeteorDiagnostics()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(5000)
        self._status_timer.timeout.connect(self._emit_status)
        self._status_timer.timeout.connect(self._on_diag_tick)
        self._status_timer.start()

    # ------------------------------------------------------------------ #
    #  Frame handling                                                      #
    # ------------------------------------------------------------------ #

    def on_frame_ready(self, detection_gray: Image.Image, full_res_clean: Image.Image):
        """
        Called per frame via image_processor.detection_frame_ready.

        *detection_gray*: grayscale PIL Image at detection scale, pre-stretch.
        *full_res_clean*: full-resolution stretched clean PIL Image for thumbnails.
        """
        cfg = self._get_config()
        if not cfg.get("enabled", False):
            return
        self._diag.frame_received()

        # Roof gate — invalidate the whole pipeline when confirmed closed, so a
        # stale pre-closure candidate can't be released after reopening.
        ml_results = getattr(self._main_window, 'last_ml_results', None) or {}
        roof_closed = ml_results.get('roof_status') == 'Closed'
        self._diag.roof_gate(roof_closed)
        if roof_closed:
            if self._stack and self._detection_semaphore.acquire(blocking=False):
                try:
                    self._stack.clear()
                    if self._filter:
                        self._filter.reset()
                    if self._noise_ema:
                        self._noise_ema.reset()
                    self._held_full_res = None
                finally:
                    self._detection_semaphore.release()
            return

        with self._lock:
            self._session_frames += 1

        # Lazy-init detection objects
        n_frames = int(cfg.get("stack_frames", 6))
        if self._stack is None or self._stack.maxlen != n_frames:
            self._reset_stack(n_frames)

        if self._filter is None:
            suppress_sec = float(cfg.get("track_suppress_minutes", 10)) * 60
            exposure = self._get_exposure_sec()
            frame_interval = max(1.0, exposure if exposure > 0 else 15.0)
            suppress_frames = max(5, int(suppress_sec / frame_interval))
            self._filter = PersistenceFilter(
                suppress_frames=suppress_frames,
                residue_suppress_frames=n_frames + 2,
            )

        # Derive or reset detection scale from frame dimensions
        gray_arr = np.array(detection_gray if detection_gray.mode == 'L'
                            else detection_gray.convert('L'))
        if self._detection_scale is None and full_res_clean is not None:
            self._detection_scale = make_scale(
                gray_arr.shape[1], full_res_clean.width)
        elif (self._detection_scale is not None and full_res_clean is not None
              and abs(self._detection_scale.factor -
                      gray_arr.shape[1] / max(full_res_clean.width, 1)) > 0.05):
            # Resolution changed — everything downstream holds coordinates or
            # statistics from the old scale; reset the full pipeline.
            self._detection_scale = make_scale(gray_arr.shape[1], full_res_clean.width)
            self._sky_circle = None
            self._held_full_res = None
            self._reset_stack(n_frames)

        # Resolve sky circle (in detection coords) once
        if self._sky_circle is None:
            self._resolve_sky_circle(detection_gray)

        self._stack.push(gray_arr)
        self._frame_idx += 1

        if not self._stack.full:
            self._diag.detection_skipped("warming")
            app_logger.debug(
                f"Meteor: stack warming ({self._stack.count}/{self._stack.maxlen})")
            return

        # Cooldown gate — keep pushing frames (so the stack stays fresh and a
        # reported streak evicts naturally) but skip detection runs.
        cooldown = float(cfg.get("detection_cooldown", 30))
        if cooldown > 0 and (time.monotonic() - self._last_detection_ts) < cooldown:
            self._diag.detection_skipped("cooldown")
            return

        # Non-blocking: drop frame if a detection thread is already running
        if not self._detection_semaphore.acquire(blocking=False):
            self._diag.detection_skipped("busy")
            return

        transient = self._stack.transient_map()
        hot = self._stack.hot_mask()
        frame_idx_snap = self._frame_idx

        threading.Thread(
            target=self._run_detection,
            args=(transient, hot, full_res_clean, cfg, frame_idx_snap),
            daemon=True,
        ).start()

    def _reset_stack(self, n_frames: int) -> None:
        """Rebuild the frame stack and the per-stack statistics that depend on
        it. The persistence filter is reset too (lazily rebuilt below) since its
        suppression windows are sized against the stack length."""
        self._stack = FrameStack(maxlen=n_frames)
        self._noise_ema = DiffNoiseEMA()
        self._filter = None

    # ------------------------------------------------------------------ #
    #  Detection thread                                                    #
    # ------------------------------------------------------------------ #

    def _run_detection(self, transient: np.ndarray, hot_mask: np.ndarray,
                       full_res: Image.Image, cfg: dict, frame_idx: int):
        try:
            sensitivity = cfg.get("noise_sensitivity", "normal")
            sigma = self._noise_ema.update(transient) if self._noise_ema else 15.0
            threshold = noise_to_threshold(sigma, sensitivity)

            # Suppress hot pixels (static equipment edges)
            masked = transient.copy()
            if hot_mask is not None:
                masked[hot_mask > 0] = 0

            # Scale exclusion zones to detection coordinates
            scale = self._detection_scale
            zones = zones_from_config(cfg)
            det_zones: Optional[List[ExclusionZone]] = None
            if zones and scale and scale.factor < 1.0:
                det_zones = [ExclusionZone(
                    x=int(z.x * scale.factor), y=int(z.y * scale.factor),
                    w=max(1, int(z.w * scale.factor)),
                    h=max(1, int(z.h * scale.factor)),
                    note=z.note,
                ) for z in zones]
            elif zones:
                det_zones = zones

            min_length_full = int(cfg.get("min_length", 100))
            min_length_det = (scale.scale_length(min_length_full)
                              if scale else min_length_full)

            detections = detect_meteors(
                Image.fromarray(masked),
                min_length=min_length_det,
                exclusion_zones=det_zones or None,
                sky_circle=self._sky_circle,
                threshold=threshold,
                max_nonline_prob=float(cfg.get("max_nonline_prob", 0.15)),
                min_brightness=int(cfg.get("min_brightness", 20)),
            )
            raw_count = len(detections)

            # Absolute length ceiling: a streak spanning most of the sky in one
            # exposure is a satellite/plane/ISS pass, not a verifiable meteor.
            max_len_det = float(cfg.get("max_length_frac", 0.5)) * transient.shape[1]
            detections = [d for d in detections if d.length <= max_len_det]
            after_length_count = len(detections)

            # Scale detections back to full-res coords for thumbnails and zones
            if detections and scale and scale.factor < 1.0:
                inv = 1.0 / scale.factor
                detections = [MeteorDetection(
                    x1=int(d.x1 * inv), y1=int(d.y1 * inv),
                    x2=int(d.x2 * inv), y2=int(d.y2 * inv),
                    length=d.length * inv,
                    angle_deg=d.angle_deg,
                    nonline_prob=d.nonline_prob,
                ) for d in detections]

            if detections:
                detections = self._apply_profile_filters(detections, full_res, cfg)
            after_profile_count = len(detections)

            # Persistence filter: hold one frame, report as meteor if absent
            # next frame. Must run EVERY frame — an empty frame is what releases
            # the previous frame's held candidate as a meteor.
            released_count = 0
            plane_count = 0
            if self._filter:
                prev_held_img = self._held_full_res
                released, planes = self._filter.update(detections, frame_idx)
                self._held_full_res = full_res if detections else None
                plane_count = planes
                if planes:
                    app_logger.debug(f"Meteor: {planes} plane track(s) suppressed")
                if released:
                    released_count = len(released)
                    self._report_detections(
                        released, prev_held_img or full_res, cfg)
            elif detections:
                released_count = len(detections)
                self._report_detections(detections, full_res, cfg)

            hot_coverage = (float((hot_mask > 0).mean())
                            if hot_mask is not None and hot_mask.size else 0.0)
            self._diag.detection_run(
                hot_coverage=hot_coverage, sigma=sigma, threshold=threshold,
                raw=raw_count, after_length=after_length_count,
                after_profile=after_profile_count,
                released=released_count, planes=plane_count)

        except Exception as exc:
            app_logger.error(f"Meteor detection error: {exc}")
            app_logger.error(traceback.format_exc())
        finally:
            self._detection_semaphore.release()

    def _apply_profile_filters(
        self,
        detections: List[MeteorDetection],
        full_res: Image.Image,
        cfg: dict,
    ) -> List[MeteorDetection]:
        """Score and filter detections by streak photometry."""
        dash_reject = float(cfg.get("dash_reject_score", 0.6))
        # peak_fade_min: reject streaks flatter than a meteor's ablation
        # profile (uniform satellites/equipment edges score ~0). Default 0
        # disables the gate — it only *rejects*, so raise it deliberately
        # against logged scores once recall is confirmed, never blind.
        peak_fade_min = float(cfg.get("peak_fade_min", 0.0))
        gray = np.array(full_res.convert('L'))
        kept = []
        for det in detections:
            profile = sample_profile(gray, det)
            ds = dash_score(profile)
            pf = peak_fade_score(profile)
            scores = (f"dash={ds:.2f}, peak_fade={pf:.2f} "
                      f"({det.length:.0f}px @{det.angle_deg:.0f}°)")
            if ds > dash_reject:
                app_logger.debug(f"Meteor: rejected by dash periodicity ({scores})")
                continue
            if peak_fade_min > 0 and pf < peak_fade_min:
                app_logger.debug(f"Meteor: rejected by flat profile ({scores})")
                continue
            app_logger.debug(f"Meteor: profile scores {scores}")
            kept.append(det)
        return kept

    # ------------------------------------------------------------------ #
    #  Reporting                                                           #
    # ------------------------------------------------------------------ #

    def _report_detections(self, detections: List[MeteorDetection],
                           full_res: Image.Image, cfg: dict):
        self._last_detection_ts = time.monotonic()
        timestamp = datetime.now().isoformat(timespec="seconds")
        best = max(detections, key=lambda d: d.length)

        thumb_info = save_thumbnail(
            full_res, best,
            thumb_dir=self._resolve_thumb_dir(),
            timestamp=timestamp,
        )

        annotated_path = ""
        if cfg.get("save_annotated", False):
            annotated_path = self._save_annotated(full_res, detections, cfg, timestamp)

        event = {
            "timestamp":      timestamp,
            "count":          len(detections),
            "max_length":     round(best.length, 1),
            "thumbnail_path": thumb_info.get("path", ""),
            "annotated_path": annotated_path,
            "confirmed":      False,
            "thumb_left":     thumb_info.get("thumb_left", 0),
            "thumb_top":      thumb_info.get("thumb_top", 0),
            "thumb_size":     thumb_info.get("thumb_size", 300),
            "line_x1":        thumb_info.get("line_x1", 0),
            "line_y1":        thumb_info.get("line_y1", 0),
            "line_x2":        thumb_info.get("line_x2", 0),
            "line_y2":        thumb_info.get("line_y2", 0),
            "length_px":      thumb_info.get("length_px", int(round(best.length))),
            "best_x1": best.x1, "best_y1": best.y1,
            "best_x2": best.x2, "best_y2": best.y2,
            "img_w": full_res.width, "img_h": full_res.height,
        }

        if cfg.get("save_detections", True):
            log_detections(self._resolve_log_path(cfg), detections)

        with self._lock:
            self._session_detections += len(detections)
            self._last_detection_time = timestamp
            new_list = ([event] + self._recent_events)[:_MAX_RECENT_EVENTS]
            evicted = self._recent_events[_MAX_RECENT_EVENTS - 1:]
            self._recent_events = new_list

        for old in evicted:
            self._evict_event_files(old)

        app_logger.info(
            f"Meteor: {len(detections)} detection(s), "
            f"longest={event['max_length']}px, "
            f"nonline_prob={best.nonline_prob:.2f}")

    def _save_annotated(self, image, detections, cfg, timestamp) -> str:
        annotated_dir = cfg.get("annotated_dir", "").strip()
        if not annotated_dir:
            return ""
        try:
            os.makedirs(annotated_dir, exist_ok=True)
            annotated = annotate_image(image, detections)
            fname = f"meteor_{timestamp.replace(':', '-')}.jpg"
            path = os.path.join(annotated_dir, fname)
            annotated.save(path, "JPEG", quality=90)
            return path
        except Exception as exc:
            app_logger.error(f"Meteor: could not save annotated image: {exc}")
            return ""

    # ------------------------------------------------------------------ #
    #  Rejection / Confirmation                                            #
    # ------------------------------------------------------------------ #

    def on_detection_rejected(self, timestamp: str):
        with self._lock:
            event = next((e for e in self._recent_events
                          if e.get("timestamp") == timestamp), None)
        if not event:
            return

        zone = zone_from_detection(
            x1=event["best_x1"], y1=event["best_y1"],
            x2=event["best_x2"], y2=event["best_y2"],
            image_width=event.get("img_w", 9999),
            image_height=event.get("img_h", 9999),
            padding=80,
        )
        zone.note = f"Rejected {timestamp}"

        cfg = self._get_config()
        existing = zones_from_config(cfg)
        existing.append(zone)
        updated = dict(cfg)
        updated["exclusion_zones"] = zones_to_config(existing)
        self._main_window.config.set("meteor", updated)
        self._main_window.config.save()

        self._evict_event_files(event)
        with self._lock:
            self._recent_events = [e for e in self._recent_events
                                   if e.get("timestamp") != timestamp]

        app_logger.info(f"Meteor: rejection saved — zone at "
                        f"({zone.x},{zone.y}) {zone.w}×{zone.h}px")
        self._emit_status()

    def on_detection_confirmed(self, timestamp: str):
        with self._lock:
            event = next((e for e in self._recent_events
                          if e.get("timestamp") == timestamp), None)
        if not event or event.get("confirmed"):
            return

        new_thumb = self._move_to_confirmed(event.get("thumbnail_path", ""))
        new_annotated = self._move_to_confirmed(event.get("annotated_path", ""))

        with self._lock:
            for e in self._recent_events:
                if e.get("timestamp") == timestamp:
                    e["confirmed"] = True
                    if new_thumb:
                        e["thumbnail_path"] = new_thumb
                    if new_annotated:
                        e["annotated_path"] = new_annotated
                    break

        cfg = self._get_config()
        if cfg.get("save_detections", True):
            log_event(self._resolve_log_path(cfg), {
                "event": "confirmed",
                "timestamp": timestamp,
                "thumbnail": new_thumb or event.get("thumbnail_path", ""),
                "annotated": new_annotated or event.get("annotated_path", ""),
            })

        app_logger.info(f"Meteor: confirmed detection at {timestamp}")
        self._emit_status()

    @staticmethod
    def _move_to_confirmed(path: str) -> str:
        if not path or not os.path.isfile(path):
            return ""
        try:
            confirmed_dir = os.path.join(os.path.dirname(path), "confirmed")
            os.makedirs(confirmed_dir, exist_ok=True)
            new_path = os.path.join(confirmed_dir, os.path.basename(path))
            os.replace(path, new_path)
            return new_path
        except OSError:
            return ""

    # ------------------------------------------------------------------ #
    #  Lifecycle                                                           #
    # ------------------------------------------------------------------ #

    def on_capture_stopped(self):
        self._diag.flush("capture stopped")
        self._diag.reset()
        # Wait for an in-flight detection thread before tearing down — it
        # reads _filter/_noise_ema/_held_full_res and reports into
        # _recent_events; tearing down underneath it races.
        acquired = self._detection_semaphore.acquire(timeout=5.0)
        try:
            if self._filter:
                # Flush held candidates — no next frame will come to refute them
                held = self._filter.flush()
                if held:
                    app_logger.info(
                        f"Meteor: capture ended, {len(held)} held candidate(s) "
                        "unverified (no next frame)")
            self._filter = None
            self._stack = None
            self._noise_ema = None
            self._detection_scale = None
            self._sky_circle = None
            self._held_full_res = None
            self._frame_idx = 0
            self._last_detection_ts = 0.0
        finally:
            if acquired:
                self._detection_semaphore.release()

        with self._lock:
            old_events = list(self._recent_events)
            self._session_frames = 0
            self._session_detections = 0
            self._last_detection_time = None
            self._recent_events = []

        for ev in old_events:
            self._evict_event_files(ev)

        self._emit_status()

    def shutdown(self):
        acquired = self._detection_semaphore.acquire(timeout=3.0)
        try:
            if self._filter:
                self._filter.reset()
            self._filter = None
            self._stack = None
            self._noise_ema = None
            self._sky_circle = None
            self._held_full_res = None
        finally:
            if acquired:
                self._detection_semaphore.release()
        app_logger.debug("Meteor controller shutdown")

    # ------------------------------------------------------------------ #
    #  Status                                                              #
    # ------------------------------------------------------------------ #

    def get_status(self) -> dict:
        with self._lock:
            return {
                "session_frames":      self._session_frames,
                "session_detections":  self._session_detections,
                "last_detection_time": self._last_detection_time,
                "recent_events":       list(self._recent_events),
            }

    def _emit_status(self):
        self.status_updated.emit(self.get_status())

    def _on_diag_tick(self):
        """Periodic diagnostics heartbeat — GUI status-timer thread."""
        if self._main_window is None:
            return
        try:
            enabled = bool(self._get_config().get("enabled", False))
        except AttributeError:
            return
        self._diag.maybe_heartbeat(enabled)

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _resolve_sky_circle(self, detection_gray: Image.Image):
        """Compute and cache sky circle in detection-scale pixel coordinates."""
        scale = self._detection_scale.factor if self._detection_scale else 1.0
        try:
            ctrl = getattr(self._main_window, 'allsky_controller', None)
            model = getattr(ctrl, '_model', None) if ctrl else None
            if model and hasattr(model, 'cx') and hasattr(model, 'a1'):
                r = model.a1 * (math.pi / 2)
                self._sky_circle = (
                    model.cx * scale, model.cy * scale, r * scale)
                app_logger.info(
                    f"Meteor: sky circle from calibration — "
                    f"cx={self._sky_circle[0]:.0f}, "
                    f"cy={self._sky_circle[1]:.0f}, "
                    f"r={self._sky_circle[2]:.0f} (det coords)")
                return
        except Exception:
            pass
        try:
            from services.allsky.star_centroid import estimate_sky_circle
            cx, cy, r = estimate_sky_circle(detection_gray)
            self._sky_circle = (cx, cy, r)
            app_logger.info(
                f"Meteor: sky circle auto-detected — "
                f"cx={cx:.0f}, cy={cy:.0f}, r={r:.0f}")
        except Exception as exc:
            app_logger.warning(
                "Meteor: no sky circle (all-sky calibration absent, "
                f"auto-detect failed: {exc}) — detection runs unmasked "
                "over the full frame")

    def _get_exposure_sec(self) -> float:
        try:
            from services.camera.camera_utils import get_selected_camera_name
            cfg = self._main_window.config
            cam_name = get_selected_camera_name(cfg)
            serial = cfg.get('zwo_selected_camera_serial', '')
            profile = cfg.get_camera_profile(cam_name, serial) if cam_name else {}
            return float(profile.get("exposure_ms", 0)) / 1000.0
        except (TypeError, ValueError, AttributeError):
            return 0.0

    def _get_config(self) -> dict:
        return self._main_window.config.get("meteor", {})

    def _resolve_log_path(self, cfg: dict) -> str:
        return resolve_log_path(cfg)

    def _resolve_thumb_dir(self) -> str:
        return os.path.join(self._appdata_dir(), "meteor_thumbnails")

    def _appdata_dir(self) -> str:
        from services.app_config import APP_DATA_FOLDER
        return os.path.join(os.getenv("LOCALAPPDATA", ""), APP_DATA_FOLDER)

    @staticmethod
    def _delete_file(path: str):
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass

    def _evict_event_files(self, event: dict):
        if event.get("confirmed"):
            return
        self._delete_file(event.get("thumbnail_path", ""))
        self._delete_file(event.get("annotated_path", ""))
