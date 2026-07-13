# Meteor Detection Rework — Architecture Plan

> **Context recovery note:** This document captures the June 2026 review of the meteor
> tracking feature and the full rework plan. The feature is functionally complete
> (capture → detect → thumbnail → confirm/reject UI) but the detection logic is wrong
> for this app's operating regime and consistently flags planes and equipment edges
> instead of meteors. Read this before touching any `services/meteor/` code.

> **Status (2026-06-12): Phases 0–4 implemented and test-verified.** New modules:
> `frame_stack.py`, `noise.py`, `streak_profile.py`, `persistence.py`,
> `detection_scale.py`; `detector.py` reworked (binary threshold + MORPH_CLOSE,
> feathered sky mask, tight `maxLineGap=5`, collinear-segment NMS); controller
> rewritten; replay harness at `scripts/dev/meteor_replay.py`; new config keys in
> `DEFAULT_CONFIG`. Deviations from this plan, found during implementation/review:
> - `hot_mask()` has **no erosion** — 3×3 erosion deleted the 1–2 px equipment
>   lines that are its primary target. The "verify erosion keeps it to star
>   cores" risk note below is therefore moot.
> - `PersistenceFilter` additionally registers a **residue suppression**
>   (`residue_suppress_frames ≈ stack depth + 2`) on every released meteor:
>   the max−mean transient keeps a streak visible until its frame evicts, so
>   without this the same event re-reports once per run for ~stack-depth runs.
> - Released meteors are thumbnailed from the **held frame's image**
>   (`_held_full_res` in the controller) — the streak is absent from the
>   releasing frame by definition.
> - The detection frame is only computed/emitted when `meteor.enabled` AND dev
>   mode are on (per-frame LANCZOS cost otherwise).
> - Cooldown skips detection runs but **keeps pushing frames** so the stack
>   stays fresh and a reported streak evicts naturally.
> Remaining: Phase 5 (ONNX recheck — needs the bundling decision below),
> Phase 6 (cleanup/graduation), corpus collection. Watch file sizes:
> `meteor_controller.py` 594 / `image_processor.py` 597 vs the 600 target.

> **Update (2026-07-07): field fix after two silent weeks.** Zero detections
> in production traced to `hot_mask()` using an ABSOLUTE `pixel > 5` test:
> the linear detection frame's floor sits at the sensor offset + sky
> background (10–30 DN, auto-exposure mean ~100), so every pixel counted as
> "hot" and the transient map was zeroed before Hough ever ran. `hot_mask()`
> is now background-relative (pixel > per-frame median + threshold, still
> ANDed over the stack) — regression tests in `test_meteor_stack.py` use a
> realistic ~25 DN background, which the original synthetic tests (0 DN) did
> not. Two decisions changed with Paul's sign-off:
> - **The dev-mode gate is removed** (`meteor_controller.py`,
>   `image_processor.py`) — the feature ships under the Beta badge like
>   ML Models; `meteor.enabled` is the only gate. The Phase 6 exit criteria
>   now govern removing the Beta badge instead.
> - New `services/meteor/diagnostics.py` (`MeteorDiagnostics`) makes silent
>   nights diagnosable from the log: periodic INFO heartbeat with per-stage
>   candidate counts (raw → length → profile → released/planes), a one-shot
>   "frames stopped — none since HH:MM:SS" line, roof-gate suspend/resume
>   transitions, and a WARNING when hot-mask coverage exceeds 40% of the
>   frame. Sky-circle resolution failure is now a WARNING (was debug).

> **Update (2026-07-12): streak library removed, restrictions loosened.** The
> feature was still missing real streaks while flagging equipment, so the two
> "streak" pieces added during the rework were pulled out with Paul's sign-off:
> - **Deleted** `services/meteor/contour_streaks.py` (the ASTRiDE-inspired
>   contour candidate finder) and `services/meteor/streak_profile.py`
>   (dash/peak-fade/dash-count photometry). The Detection Method dropdown and
>   the `detection_method`, `dash_reject_score`, `dash_count_reject`,
>   `peak_fade_min` config keys are gone; `_apply_profile_filters` and the
>   diagnostics `profile-ok` stage are removed.
> - The detector is now **Hough-only**. Remaining pipeline: FrameStack transient
>   map + background-relative `hot_mask` → adaptive threshold → `detect_meteors`
>   (feathered sky mask) → `PersistenceFilter` (plane reject + residue/novelty
>   suppression) → exclusion zones. Equipment rejection leans on the masking +
>   persistence + manual "Not a Meteor" zones, not on streak classification.
> - Restrictions loosened (gentle): `min_brightness` 20→10, `max_nonline_prob`
>   0.15→0.30, Hough `maxLineGap` 5→15. Sections below describing the contour
>   detector and streak-profile scoring are **historical** — kept for design
>   context but no longer implemented.

---

## The Problem

PFR Sentinel captures **long exposures (10–20 s per frame, ~0.05–0.1 fps)**. The
current detector was assembled from pieces of [MetDetPy](https://github.com/LilacMeteorObservatory/MetDetPy),
a pipeline designed for **video at real frame rates** (10+ fps, effective exposure
≤ 0.5 s). The regime change inverts the meaning of the borrowed logic:

| Signal | At video rates (MetDetPy) | At 10–20 s exposures (us) |
|--------|---------------------------|---------------------------|
| Meteor | Moves across many frames; speed/duration measurable | **Complete streak in exactly ONE frame**, absent from neighbours |
| Plane/satellite | Slow, persists for minutes → rejected by speed gate | Long streak **in every frame** along a continuing track, often dashed (nav strobes) |
| Equipment/horizon | Static → cancelled by temporal background subtraction | Static — but our diff input isn't photometrically stable, so it *doesn't* cancel |

Observed symptoms (reported June 2026): detections are almost exclusively
(a) straight edges on the pier/mount/horizon and (b) plane trails. Real meteors
are missed.

### Root causes (verified in code review, June 2026)

1. **Diff input is per-frame auto-stretched.** `timelapse_ready` emits
   `stretched_for_preview` (`ui/controllers/image_processor.py:379`) — the MTF
   auto-stretched frame. The stretch curve is recomputed from each frame's own
   statistics, and auto-exposure changes the raw signal underneath. Two frames of
   an identical static scene therefore differ everywhere, with the strongest
   residuals on high-contrast static edges. The premise of
   `compute_frame_difference()` ("subtract previous frame to isolate transients",
   `services/meteor/detector.py:6`) only holds on photometrically stable input.

2. **Adaptive threshold measures the wrong statistic.**
   `estimate_adaptive_threshold()` (`detector.py:33`) applies MetDetPy's
   `1.2·σ² + 3.6` mapping to the **spatial std of a central crop of the current
   frame** (real scene structure: stars, Milky Way, on stretched data).
   MetDetPy applies it to the **noise std of the difference signal**, EMA-smoothed.
   Any stretched night sky has crop σ > 9, and σ = 9 already exceeds the clamp —
   the threshold sits **pinned at 100** essentially always. Faint meteors are zeroed
   out of the diff; only the brightest changes survive (plane lights, stretch
   flicker on equipment edges).

3. **Speed-plausibility filter is inverted for long exposures.**
   `check_speed_plausibility()` (`detector.py:125`) computes
   `speed = length / width / exposure_sec`, range 2–50 %/s. A meteor's streak
   length is set by its *flight duration* (~0.5–1 s), not the exposure: a 400 px
   meteor streak in a 15 s exposure on a 3500 px frame scores 0.75 %/s →
   **rejected**. Anything moving continuously through the whole exposure (planes,
   satellites) accumulates the longest streaks and the best scores. The 2–50 %/s
   range is MetDetPy's `speed_range`, which they compute from *inter-frame motion*;
   dividing single-frame streak length by exposure changes its meaning entirely.
   (Side effect: `_get_exposure_sec()` reads `exposure_ms` from the camera profile —
   absent in NINA watch mode, stale under auto-exposure — so the filter silently
   self-disables in some configs, which is the only reason anything is detected.)

4. **No plane discriminator exists.** The reliable signal at this frame rate is
   temporal: a plane's streak **continues across consecutive frames, collinear and
   advanced along the track**; a meteor appears in exactly one frame. Nothing
   checks this. Worse, `MeteorTracker` (`services/meteor/tracker.py`) confirms
   series that *persist* across frames — its own docstring (lines 14–17) warns this
   is only valid under ~2 s exposures. With `multi_frame_confirm` on it is
   functionally a plane detector. Dashed plane trails are also actively *hidden*:
   `HoughLinesP(maxLineGap=20)` bridges nav-light dashes into one clean line.

5. **Sky-circle mask manufactures lines.** `apply_sky_circle_mask()`
   (`detector.py:81`) hard-zeros outside the circle. When the diff is globally
   nonzero (per cause 1, usually), the mask boundary is a crisp circular edge.
   At r ≈ 1000+ px a 100 px arc deviates from straight by ~1 px (sagitta = L²/8R),
   inside HoughLinesP's `rho=3` tolerance → the mask itself Houghs into chords at
   the horizon, exactly where equipment silhouettes sit. Equipment *inside* the
   circle (OTA, mast) isn't masked at all, and a slewing scope is a genuine
   transient that produces strong straight diff edges.

6. **Exclusion zones are the wrong tool for moving objects.** Rejecting a plane
   adds a permanent 80 px-padded rectangle over a patch of *sky*
   (`ui/controllers/meteor_controller.py:303`). The next plane flies elsewhere;
   the zone just blinds that patch forever. Zones are right for equipment only.

### What is already good (keep)

- Module split (`detector` / `tracker` / `mask` / `storage` / controller) and the
  panel/controller separation.
- Threading model: daemon detection thread, semaphore frame-dropping, lock around
  shared counters, no Qt calls from the worker.
- Confirm/reject UI, thumbnail crops, `confirmed/` archival, JSONL event log —
  this is also a **labelled-training-data generator** for Phase 5.
- Roof gate, cooldown gate, dev-mode gate (`meteor_controller.py:81` — keep until
  exit criteria below are met).

---

## MetDetPy Reference (researched June 2026, v2.4.0, MPL-2.0)

Pipeline: loader (resize to 960 long side, grayscale, merge raw frames into
logical frames) → **M3Detector** (sliding window `max − mean` background
subtraction, ~1 s window) → adaptive binary threshold from *diff-noise* std
(EMA-smoothed, `sensitivity` maps σ → threshold: normal = `1.2σ²+3.6`, floor 5) →
`medianBlur` → `MORPH_CLOSE` → **dynamic mask** (pixel that fired in *every*
frame of a 5 s window is masked — kills stars/hot pixels/fixed edges) →
`HoughLinesP(rho=1, threshold=10, minLen=10, maxGap=adaptive)` → line-NMS with a
`nonline_prob` width/length fatness score → **kinematic collector**
(`MeteorSeries`: multiplicative score of duration ∈ [0,8] s, speed ∈ [2,21] %/s,
direction-std ≤ 0.6 rad, soft trapezoid gates) → **YOLOv5s ONNX recheck**
(`weights/yolov5s_v2.onnx`) on max-stacked crops, 10 classes incl.
`PLANE_SATELLITE` and `BUGS`; only `METEOR`/`RED_SPRITE` export as positives.
`MetDetPhoto.py` is their long-exposure still mode: pure YOLO per image with a
2×2 multiscale pyramid and `--exclude-noise`.

**Transfers to our regime:** max−mean N-frame stack (reinterpret window as frame
count), dynamic mask, diff-noise adaptive threshold, Hough + line-shape NMS,
direction-std linearity, the `MeteorSeries` *association machinery* (with the
verdict inverted), and — best of all — the recheck model: max-stacked video crops
visually resemble long exposures, and `PLANE_SATELLITE` was trained on exactly
the dashed-streak appearance we're fighting.

**Does NOT transfer:** the whole kinematic scoring layer (speed/duration units
collapse when the event lives inside one frame), `exp_time` estimation,
ClassicDetector's 4-frame mask trick.

---

## Target Pipeline

```
capture (10–20 s exposure)
  │
  ▼
linear / pre-stretch grayscale frame, downscaled to ~960–1280 px long side   [Phase 1]
  │
  ▼
N-frame ring buffer (N ≈ 5–8 frames ≈ 1–3 min of sky)                        [Phase 2]
  ├── diff = max(stack) − mean(stack)          ← static scene vanishes
  ├── threshold = f(σ of diff, EMA-smoothed)   ← MetDetPy mapping, right input
  ├── dynamic mask: pixel hot in ALL N frames → masked (auto exclusion zones)
  └── soft sky-circle mask (feathered edge, no hard chord artifacts)
  │
  ▼
HoughLinesP → line NMS → linearity (nonline_prob) + min length               [Phase 2]
  │
  ▼
single-frame streak analysis                                                  [Phase 3]
  ├── intensity profile along streak: meteors peak-and-fade; planes uniform
  └── dash periodicity (autocorrelation along streak) → plane strobes
  │
  ▼
cross-frame persistence filter (one-frame holdback)                           [Phase 4]
  ├── candidate streak reappears next frame, collinear + advanced → PLANE, reject
  ├── + add temporary trajectory suppression (TTL ~10 min) along that track
  └── absent from next frame → METEOR candidate, report
  │
  ▼
optional ONNX recheck on candidate crop (yolov5s_v2 classes)                  [Phase 5]
  │
  ▼
report → thumbnail → confirm/reject UI (existing)
```

Detection latency becomes one frame (10–20 s) because of the holdback. That is
acceptable — nothing downstream is real-time.

---

## Phases

Each phase is independently shippable and testable; later phases only tighten
precision. Dependencies: 0 → 1 → 2 → {3, 4 in either order or parallel} → 5 → 6.
Phase 1+2 alone should eliminate the equipment false positives, Phase 3+4 the
planes.

### Phase 0 — Replay harness + baseline corpus

**Goal:** make detection iterable offline. You cannot develop a meteor detector
by waiting for meteors at night; every later phase is tuned and validated against
recorded frames replayed through the pipeline.

- New script `scripts/dev/meteor_replay.py` (dev-only, follows the pattern of the
  other `scripts/dev/` tools): takes a folder of frames (FITS/PNG/JPEG, sorted by
  timestamp), feeds them through the detection pipeline exactly as the controller
  would (same stack, masks, filters — import the `services/meteor/` modules, do
  NOT reimplement), and writes per-frame annotated output + a JSONL of
  detections/rejections with the reason each candidate was kept or dropped.
  A `--stage` flag to dump intermediate images (transient map, hot mask, binary
  mask) is what makes Phase 2/3 tuning tractable.
- **Collect the corpus before changing any detection code:**
  - Several nights of raw frame sequences (pre-stretch — once Phase 1 lands, save
    the actual detection frames; until then, save what the camera produces).
    Must include: clear night with star field, night with passing planes
    (multiple), clouds, a scope slew, moonlight, and — when luck cooperates — a
    real meteor. Satellites (Starlink trains) are a bonus.
  - Save the **current detector's false positives** (the existing thumbnails +
    JSONL log under `%LOCALAPPDATA%\PFRSentinel\`) as the regression set: the
    rework is successful when replaying those nights produces none of them.
  - Suggested location: a `meteor_corpus/` folder outside the repo (multi-GB),
    path documented in this file once chosen. <!-- corpus path: TBD -->
- Acceptance: replaying a recorded night reproduces the live detector's current
  (bad) detections — proving the harness matches production behaviour before any
  fix is made.

### Phase 1 — Photometrically stable input

**Goal:** the detector sees linear-ish, consistently scaled frames, not per-frame
MTF stretches.

- In `ImageProcessorWorker` (`ui/controllers/image_processor.py`), capture a
  **detection frame** before auto-stretch: grayscale, downscaled to a configurable
  long side (default 1280; MetDetPy uses 960). Downscale BEFORE grayscale copy to
  keep the extra memory negligible (~1–2 MB vs the 76 MB raw array).
- Emit it on a new signal `detection_frame_ready = Signal(object, object)`
  (detection grayscale PIL image, full-res clean image for thumbnails) and connect
  it to `MeteorController.on_frame_ready` in `ui/main_window/window.py` (replacing
  the current `timelapse_ready` connection for the meteor controller only —
  timelapse keeps `timelapse_ready`).
- If 16-bit raw data is available (`RAW_RGB_16BIT`), derive the detection frame
  from it with a *fixed* linear scale (e.g. >>8), not a per-frame stretch.
- Scale `min_length` and all pixel-space config between detection resolution and
  full resolution in exactly one place (a `DetectionScale` helper holding the
  factor) — thumbnails and exclusion zones live in full-res coordinates, detection
  in downscaled coordinates. **This boundary is where past bugs will breed; keep
  the conversion in one module.**

**Files:** `ui/controllers/image_processor.py`, `ui/main_window/window.py`,
`ui/controllers/meteor_controller.py`, new `services/meteor/detection_scale.py`.

**Tests:** unit test that detection frame is invariant when the same scene is
stretched two different ways; coordinate round-trip tests for `DetectionScale`.

### Phase 2 — Temporal stack detector (max − mean + dynamic mask)

**Goal:** static structure cancels by construction; threshold adapts to actual
noise.

- New module `services/meteor/frame_stack.py`:
  - `FrameStack(maxlen)` — ring buffer of grayscale `np.ndarray` with O(1)-ish
    running mean (running sum) and recomputed max (N ≤ 8, recompute is cheap at
    1280 px).
  - `transient_map() = clip(max − mean)` — the new diff image.
  - `hot_mask()` — per-frame binary responses ANDed over the window: pixel above
    threshold in **every** frame of the window → masked (then eroded 3×3, dilated
    5×5). This replaces manual exclusion zones for static equipment.
- New module `services/meteor/noise.py`:
  - `estimate_diff_noise(diff, sample_area=0.1)` — σ via MAD on a sampled
    subregion of the *transient map*, EMA-smoothed across frames
    (`σ_t = 0.9·σ_{t-1} + 0.1·σ`).
  - `noise_to_threshold(σ)` — keep MetDetPy's `1.2σ²+3.6` with floor 5, cap 100.
- Rework `detect_meteors()` (`services/meteor/detector.py`) to take the transient
  map + masks. Drop Canny entirely (MetDetPy doesn't use it; binary threshold +
  `MORPH_CLOSE` feeds Hough better for streaks). Tune Hough toward MetDetPy:
  `rho=1`, lower vote threshold, `minLineLength` from scaled config,
  `maxLineGap` **small** (≤ 5 at detection scale — large gaps are what welded
  plane dashes into clean lines).
- Port MetDetPy's `lineset_nms` idea: merge collinear segments, compute
  `nonline_prob` (bounding-blob width / length fatness score), reject fat blobs.
- Sky-circle mask: feather the edge (linear ramp over ~20 px) or erode the
  circle by the dilation kernel radius before masking, so the boundary can't
  produce Hough chords. Applied to the transient map, not the source frame.
- Remove `estimate_adaptive_threshold()` and `compute_frame_difference()` usage
  from the controller; keep the functions temporarily as deprecated re-exports if
  tests reference them, delete in Phase 6.
- Controller: stack lives on `MeteorController`, invalidated on roof-closed,
  capture-stop, and resolution change. First N−1 frames warm the stack (no
  detection) — log this state so "why no detections yet" is answerable.

**Config (new keys under `meteor`, merge-safe):**
```
"stack_frames": 6,            # ring buffer length
"detection_long_side": 1280,  # detection working resolution
"noise_sensitivity": "normal" # low | normal | high → MetDetPy mapping choice
```
`diff_threshold` / `adaptive_threshold` become unused (read-but-ignored until
Phase 6 cleanup).

**Tests:** synthetic sequences (small PIL/numpy frames):
- static bright edge across N frames → transient map ≈ 0 there (the equipment case);
- same scene with global brightness ramp (simulated auto-exposure drift) → no lines;
- single-frame synthetic streak → detected;
- hot pixel in all frames → removed by `hot_mask`;
- mask boundary with global offset → no detections along the circle.

### Phase 3 — Single-frame streak analysis

**Goal:** use the streak's own photometry to separate meteors from planes within
one frame.

- New module `services/meteor/streak_profile.py`:
  - `sample_profile(gray, det, width=3)` — mean intensity along the line
    (perpendicular-averaged, Bresenham sampling like the existing
    `_validate_trail_brightness`).
  - `dash_periodicity(profile)` — autocorrelation of the mean-subtracted profile;
    a strong secondary peak (regular on/off) → plane strobes. Return a score, not
    a bool — feeds the combined verdict.
  - `peak_fade_score(profile)` — meteors brighten to a peak and fade
    (smooth unimodal envelope); planes are flat or periodic. Score = how unimodal
    the smoothed profile is.
- **Delete `check_speed_plausibility()`** and its call site. Replace with an
  absolute length ceiling (`max_length_frac` of detection width, default ~0.5) —
  a streak spanning most of the sky in one exposure is a plane/satellite or the
  ISS, not a meteor we can verify.
- Replace `strict_validation`'s axis-aligned rejection (`_is_axis_aligned`) with
  nothing — it was a hack for stretch-flicker on equipment edges, which Phase 2
  removes at the source; it costs real meteors that happen to be horizontal.

**Config:** `"max_length_frac": 0.5`, `"dash_reject_score": 0.6` (tunable).

**Tests:** synthetic streaks with (a) gaussian peak-fade envelope → accepted,
(b) uniform brightness → low peak-fade score, (c) dashed pattern → high dash
score, rejected.

### Phase 4 — Persistence filter (the inverted tracker)

**Goal:** anything that continues across frames along the same track is not a
meteor.

- New module `services/meteor/persistence.py` (replaces
  `services/meteor/tracker.py`):
  - `PersistenceFilter(hold_frames=1, collinear_tol_deg=10, lateral_tol_px=...)`.
  - `update(candidates, frame_idx) -> (released_meteors, rejected_tracks)`:
    candidates from frame T are **held** until frame T+1 is analysed. If frame
    T+1 (or T+2, planes can dim) contains a streak whose infinite line matches
    the held streak's line (angle within tolerance, lateral offset within
    tolerance) and whose position has advanced along it → both are a
    plane/satellite track: drop the held candidate, and register a
    **trajectory suppression** (the matched line, widened ~30 px, TTL
    ~10 minutes) so the rest of that pass doesn't re-trigger per frame.
  - Suppressions are in-memory only (planes don't repeat paths — persisting them
    would recreate the exclusion-zone mistake).
- Delete `MeteorTracker` and the `multi_frame_confirm` / `min_confirm_frames`
  config path — confirm-by-persistence is the exact opposite of correct here.
  (`tracker.py` carries its own docstring warning to this effect.)
- Controller flush semantics: on capture stop, `flush()` releases held
  candidates *as meteors* (no next frame will ever come to refute them) — log
  them as "unverified (capture ended)".

**Config:** `"persistence_hold_frames": 1`, `"track_suppress_minutes": 10`.

**Tests:** scripted detection sequences:
- streak frame T only → released as meteor after T+1;
- collinear advancing streaks T, T+1, T+2 → all rejected, one suppression entry;
- same line but NOT advanced (re-detection of static residue) → rejected;
- crossing meteor during an active plane suppression, different angle → released;
- flush on capture stop releases held candidate.

### Phase 5 — ONNX recheck (optional but high value)

**Goal:** a learned second opinion on each candidate crop, MetDetPy-style.

- Evaluate MetDetPy's `weights/yolov5s_v2.onnx` (MPL-2.0 — redistribution OK with
  attribution + license file) on saved candidate crops from Phases 2–4 field
  testing **before** integrating. If precision is poor on our fisheye crops, skip
  to the fine-tune path.
- If adopted: new module `services/meteor/recheck.py` — preprocess candidate crop
  (max-stack crop over the event's frame ± context, letterbox to model input),
  run via `onnxruntime`, map classes; reject `PLANE_SATELLITE` / `BUGS`, require
  `METEOR` above threshold. Inference goes through the existing ONNX conventions
  (`.claude/rules/ml.md`): model file under `app_config.get_config_dir()/models`,
  production calls routed via `ui/controllers/ml_prediction.py`.
- **Training-data flywheel:** the confirm/reject UI already labels crops. Extend
  `storage.py` to retain rejected crops (currently deleted) in a
  `rejected/` folder when `"keep_rejected_for_training": true`. After a season of
  data, fine-tuning a small classifier (meteor / plane / other) on our own sky is
  a weekend job and almost certainly beats the stock model on this camera.

**Tests:** `requires_ml_models`-marked smoke test (load + infer on a fixture
crop); class-mapping unit test (no model needed).

### Phase 6 — Cleanup and graduation

- Delete deprecated re-exports (`compute_frame_difference`,
  `estimate_adaptive_threshold`, `check_speed_plausibility`, `tracker.py`).
- Config migration: drop `diff_threshold`, `adaptive_threshold`,
  `multi_frame_confirm`, `min_confirm_frames` from `DEFAULT_CONFIG`; stale keys
  in user configs are harmless (merge pattern ignores them).
- Repurpose exclusion zones as **equipment-only**: keep the manual rectangle
  feature in the panel (some gear isn't fully static — flapping cables), but the
  reject button should no longer auto-create zones — with the persistence filter
  and dynamic mask, rejection is just label feedback (and training data).
- Update `tests/test_meteor.py` end-state: tests mirror the new modules
  (`test_frame_stack`, `test_streak_profile`, `test_persistence`, …) per
  `.claude/rules/tests.md` naming.
- Update the meteor panel settings to the new config keys (stack size,
  sensitivity, dash threshold) — panel stays layout-only, controller owns logic.
- **Exit criteria for removing the dev-mode gate** (`meteor_controller.py:81`):
  ≥ 2 weeks of unattended field running with (a) zero equipment-line detections,
  (b) plane rejection ≥ 90% (count via rejected-track log vs confirmed planes in
  review), (c) no detection-thread crash in logs, (d) CPU cost per frame < 1 s at
  detection resolution.

---

## Execution notes (read before starting)

### Running the feature
- It is gated behind dev mode: set env var **`PFRSENTINEL_DEV_MODE=1`**
  (`services/dev_mode_config.py`) — the build-time constant is `False`, so
  without the env var `on_frame_ready` returns immediately and nothing you
  change will appear to work.
- Then enable `meteor.enabled` in config (Meteor panel toggle or
  `%APPDATA%\PFRSentinel\config.json` via the app — never hand-edit while the
  app runs) and start a camera or watch session. Frames only flow while capture
  is running; most iteration should use the Phase 0 replay harness instead.

### Size-cap landmines
- **`tests/test_meteor.py` is 748 lines — the hard cap is 750.** The
  `check_file_size.py` hook will block the first meaningful edit. Split it
  FIRST (mechanical move, no behaviour change): one test file per module under
  test (`test_meteor_detector.py`, `test_meteor_tracker.py`, …), then let each
  phase add/replace tests in its module's file (`test_meteor_stack.py`,
  `test_meteor_persistence.py`, …). Do this as part of Phase 0.
- `ui/panels/meteor_panel.py` is 534 lines; Phase 6 adds settings rows. If it
  approaches 600, split the settings card group from the events/history view.
- `ui/controllers/meteor_controller.py` is 516 lines; see budget table below.

### Workflow conventions
- One branch per phase (`meteor/phase-N-<slug>`), merged in order. Run
  `/pre-commit-check` before each commit; run the `pfr-reviewer` subagent after
  each phase's changes (it knows the threading model and config nesting).
- Per-phase done-definition: unit tests green AND a replay of the Phase 0 corpus
  shows the expected delta (Phase 2: zero equipment/static-edge detections;
  Phase 3/4: plane sequences rejected with the right reason codes in the replay
  JSONL; no real-meteor frame, if the corpus has one, lost at any phase).
- Quantitative target for the Phase 6 exit criteria is measured with the replay
  JSONL reason codes, not by eyeballing thumbnails.

### Interface contracts to hold steady
- `MeteorDetection` stays the cross-module currency. Phases 2–4 may ADD fields
  (e.g. `nonline_prob`, `dash_score`, `peak_fade_score`) but must not rename or
  repurpose the existing ones — `storage.py`, the panel, and the JSONL log all
  consume them, and old JSONL logs must keep parsing.
- New signal: `detection_frame_ready = Signal(object, object)` —
  (detection grayscale PIL Image at detection scale, full-res clean PIL Image).
  Thumbnails/zones stay in full-res coordinates; everything else in detection
  coordinates; `detection_scale.py` is the only place that converts.
- The reject/confirm UI contract (`on_detection_rejected` /
  `on_detection_confirmed` keyed by timestamp) must keep working in every phase
  — it is the labelled-data flywheel for Phase 5.

### Decisions already made (don't re-litigate)
- One-frame detection holdback (10–20 s latency) is accepted — nothing
  downstream is real-time.
- Trajectory suppressions are in-memory only, never persisted.
- The dev-mode gate stays until the Phase 6 exit criteria are met.

### Open decisions — need Paul's call, don't guess
- Whether to **bundle** MetDetPy's `yolov5s_v2.onnx` in the installer (MPL-2.0
  attribution + license text required) vs. download-on-enable vs. skip straight
  to a self-trained model (Phase 5).
- Default for `keep_rejected_for_training` (disk usage on a 24/7 box; rejected
  crops accumulate).
- Corpus storage location (multi-GB, outside repo) — record it in Phase 0's
  placeholder above once chosen.

## File-size budget (rule: target ≤ 600, cap 750)

| File | Now | After |
|------|-----|-------|
| `services/meteor/detector.py` | 258 | ~250 (loses diff/threshold/speed, gains NMS) |
| `services/meteor/frame_stack.py` | — | ~150 |
| `services/meteor/noise.py` | — | ~80 |
| `services/meteor/streak_profile.py` | — | ~150 |
| `services/meteor/persistence.py` | — | ~200 |
| `services/meteor/recheck.py` | — | ~150 (Phase 5) |
| `services/meteor/detection_scale.py` | — | ~60 |
| `services/meteor/tracker.py` | 181 | deleted (Phase 4) |
| `ui/controllers/meteor_controller.py` | 516 | watch this one — if Phase 2 state pushes it past ~600, extract the frame-ingest path into `services/meteor/ingest.py` |

---

## Risks / open questions

- **Star drift residue:** stars move ~1 px between 15 s frames near the equator —
  negligible in max−mean over 6 frames, but the *dynamic mask* may slowly eat
  bright stars (they're hot in every frame). That is fine (we don't detect
  meteors *through* a star) but verify the mask erosion keeps it to star cores.
- **Clouds:** moving clouds light up large areas of the transient map. The
  existing large-contour cloud mask logic in `detect_meteors()` carries over;
  MetDetPy additionally shrinks Hough `maxLineGap` when foreground area is high —
  port that if field testing shows cloud-edge lines.
- **Slewing scope:** a moving OTA edge is a genuine transient and will pass the
  stack. The persistence filter catches repeated slews; a single slew during one
  frame may still produce a candidate. Acceptable — it lands in the review UI and
  the streak-profile scores (no peak-fade) argue against it.
- **Memory:** 6 × (1280² grayscale float32) ≈ 39 MB if stored as float; store
  uint8 frames + uint32 running sum → ~12 MB. Fine.
- **Watch mode (NINA):** frames may arrive already stretched by the capture
  program. Phase 1's stability guarantee only holds for camera mode; document
  that watch-mode detection quality depends on upstream consistency.
- **MetDetPy model licensing:** MPL-2.0 — bundling `yolov5s_v2.onnx` requires
  shipping the license text and attribution in the installer. Check before
  Phase 5 release.

---

## References

- [MetDetPy](https://github.com/LilacMeteorObservatory/MetDetPy) v2.4.0 —
  `MetLib/Detector.py` (M3Detector), `MetLib/collector.py`
  (MeteorSeries/recheck), `config/m3det_normal.json`, `docs/config-doc.md`,
  `MetDetPhoto.py` (still-image mode).
- Code review findings: this document, "Root causes" section (June 2026 session).
- Existing feature docs: `services/meteor/` module docstrings;
  `tests/test_meteor.py` documents current (pre-rework) behaviour.
