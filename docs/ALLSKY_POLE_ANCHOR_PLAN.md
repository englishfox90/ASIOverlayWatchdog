# All-Sky Pole Anchor & Model Trust Plan

> **Context:** Produced 2026-07-01 after diagnosing a user rig (same physical camera as
> `sample_images/`) whose saved `calibration.json` was a degenerate wrong-basin fit that
> then poisoned every background refinement. Companion docs:
> [`ALLSKY_RELIABILITY_PLAN.md`](ALLSKY_RELIABILITY_PLAN.md) (F1–F14 hardening, done),
> [`ALLSKY_CALIBRATION_PLAN.md`](ALLSKY_CALIBRATION_PLAN.md) (architecture),
> [`dev/allsky_single_image_failure_2026-06-13.md`](dev/allsky_single_image_failure_2026-06-13.md)
> (grid-search wrong-basin root cause).

## The incident this fixes

A model saved on 2026-06-23 (`n_matches=11`, `n_images=1`, RMS 4.2px — *looks* great)
was verified against the 9 hand-confirmed anchors of `lum_20260116_021511.fits`:
**median error 761px**. Telltales visible in the JSON alone:

| Parameter | Saved model | Rig truth | Invariant? |
|---|---|---|---|
| `a3` | `19.9999…` (pinned at A3_MAX) | −47.6 | bound-pinning is always a red flag |
| `east_left` | `false` | `true` | mirror never changes on a rig |
| `a1` (scaled to 3552px) | ~650 | 1277 | lens scale never changes |

Consequences observed in the 2026-06-24 user log:

1. `CalibrationService` seeds `_RefineWorker` with the current (bad) model; matching at
   tol 32→11px stays in the wrong basin; refinement converges (RMS ~8px, ~595
   coincidental matches) and `validate_bright_anchors` **correctly** rejects it — every
   cycle, forever. The gate worked; admission failed.
2. Guided calibration rejected the user's (probably correct) star identifications at
   RMS 13.7px vs a 13px limit — click precision on a 760px no-zoom preview of a ~3190px
   frame is ~4px/display-px, the optical centre is frozen from `estimate_sky_circle`,
   and `dt` is dialog-open time rather than frame capture time.

## The pole anchor (validated 2026-07-01 on sample_images)

The celestial pole is a model-free ground truth extractable from the frame buffer:

- **Polaris** is the brightest near-stationary detection. Found at (1719.4, 650.6) on a
  61-min window — 4.8px from its catalog-confirmed position. Its measured drift (3.3px)
  matched the predicted sidereal arc (3.3px) exactly.
- **Rotation sign** of the star field around the pole determines `east_left` outright
  (measured −1 / clockwise in array coords on this rig, `east_left=True`, northern
  hemisphere). Sign was correct in every window tested, even where the pole position
  estimate was poor.
- **Contaminant rejection is mandatory**: equipment LEDs are stationary AND bright.
  Filters that survived testing: (a) reject candidates within ~80px of the sky-circle
  edge (the LED at (3051, 948) sat at r=1520/1563); (b) drift band — accept only
  candidates whose drift over the window is 0.35–2.5× the predicted Polaris arc
  (static lights drift ~0.2×, lights on the moving OTA drifted 5–10×).
- **What does NOT work**: fitting the pole as the fixed point of a rigid rotation using
  *all* stars — fisheye distortion biases the aggregate fit by 100+px (each distant
  star's arc has its own curvature centre). Southern hemisphere (no bright pole star)
  would need a near-pole-restricted flow fit; out of scope for now — `find_pole`
  returns None below ~|lat| where Polaris logic doesn't apply.
- Even the known-good model projects the NCP ~50–70px from the measured pole (real
  regional model error) — so the pole gate tolerance must be generous (~0.09·sky_r
  ≈ 140px at reference resolution). Wrong basins miss by 400–1400px; the gate still
  kills them with an order of magnitude of margin.

## Work items

### P1 — `services/allsky/pole_finder.py` (new)
Pure function over the CalibrationService buffer format (`{'dt', 'detected', ...}`):
stationary-track clustering (seeded from every frame, ≥70% presence), edge-margin +
drift-band filters, brightest survivor = Polaris ≈ pole; rigid-match vote for rotation
sign → `east_left` (northern: `east_left = (sign<0)`; southern mirrored). Returns a
`PoleEstimate` or None. Requires ≥6 frames spanning ≥30 min.

### P2 — Admission gates (`calibration_validate.py`)
- `validate_a1_scale(model, sky_r)`: a1 must be within [0.7, 1.5]× of
  `a1_from_sky_radius(sky_r)`. Kills the a1≈half-truth basin (measured ratios: bad
  model 0.57, known-good 1.09).
- `validate_lens_polynomial`: additionally reject a3 within 0.5 of A3_MIN/A3_MAX —
  a pinned coefficient means the optimiser fought the bound (wrong orientation).
- `validate_pole(model, lat, pole, sky_r)`: model must project the visible celestial
  pole within 140px·tol_scale of the measured pole, and `model.east_left` must agree
  with the pole estimate's sign when confident.
- Wire a1-scale + pinned-a3 into every accept path: `calibrate()` step 6,
  `triangle_calibrate`, `_fit_and_validate` (multi), `calibrate_from_anchors` (guided).

### P3 — CalibrationService integration
- Compute `PoleEstimate` from the buffer when refinement triggers; run
  `validate_pole` on any candidate model (initial, refined, bootstrap) before saving.
- Pass `east_left` from the pole estimate into the cold-start bootstrap so
  `_coarse_orientation_candidates` skips the wrong mirror half of the grid.
- **Basin escape:** count consecutive refinement rejections; after 3, discard the
  (possibly poisoned) seed for one cycle and run the cold-start bootstrap path with
  the pole constraint, replacing the model if the result passes all gates.

### P4 — Guided calibration fixes

> Addendum 2026-07-01: the guided coarse orientation search now refines the
> **top-5** grid cells and keeps the best final RMS (was: single best cell).
> The grid is near-degenerate at axis_alt=90 (az/roll collapse into one
> rotation), so near-ties could drop the refine into a wrong basin — observed
> as a bistable solve (0.6px vs 12.2px on identical inputs). Same pattern the
> cold-start bootstrap already used.
- `dt` = capture time of the displayed frame (cache the timestamp with the frame),
  not dialog-open time.
- Free cx/cy within ±5% of sky radius when ≥6 anchors (4–5 anchors keep them fixed).
- Error message reports per-anchor residuals so one bad identification is identifiable
  instead of "you're wrong, try again".
- Dialog: larger snap radius, per-anchor snapped/unsnapped indicator, hint to prefer
  snapped anchors.

### P6 — Anchor-gate altitude floor — **resolved 2026-07-01**

`validate_bright_anchors` used to reject the known-good `multi_calibration.json` on the
confirmed frame (3/12 hits) because the brightest winter stars sit at low altitude,
where even a correct fisheye model extrapolates 46–406px. Per-anchor measurement across
3 real frames × 4 models (known-good, incident, mirrored, 180°-rolled) showed clean
separation above ~40° altitude: the good model hits 7–35px, wrong basins miss 40–360px.
Fix: `min_alt_deg` default raised 15° → **40°** (pool stays top-12, min_hits 5). A
parameter sweep (min_alt 35/40/45 × min_hits 4/5/6) passed the acceptance criterion at
every combination — good passes, all three wrong variants fail, on all 3 frames — so 40/5
was chosen mid-range. Permanent regression: `tests/test_allsky_anchor_gate_real.py`
(the June-13 acceptance criterion, run against the real frame). Whole-sky correctness
below 40° is covered by the a1-scale, lens-polynomial and pole gates.

### P5 — Validation protocol — **run 2026-07-01, results**
- ✅ Incident model rejected by **all four** gates on the confirmed frame
  (a3 out-of-range/pinned; a1 scale 0.55×; anchors 4/12; pole gate: mirrored).
- ✅ `multi_calibration.json` passes poly, a1-scale and pole gates (pole projected
  87px from measured, tol 140px). ⚠️ It still fails the legacy bright-anchor gate
  (3/12) — the pre-existing gap documented above, unchanged by this work.
- ✅ `pole_finder` on three real windows: pole error 4.8 / 0.5 / 2.2px vs Polaris
  truth (1718, 646); sign −1 and `east_left=True` everywhere; the window containing
  the bright OTA light still picks Polaris (drift band rejects the contaminant).
- ✅ End-to-end cold-start bootstrap (15 frames / 60 min, pole `east_left` hint):
  5 wrong-orientation candidates rejected by the gates; the survivor is the true
  basin (a1=1268 vs truth 1277, east_left=True, 1294 matches) and its projected NCP
  is **15px** from the measured pole.
- ✅ Test suite green (773 passed; 2 pre-existing `test_camera.py` failures are a
  missing local `ASICamera2.dll`, unrelated).

## Invariants (unchanged from the reliability plan)
- `fisheye.py:altaz_to_pixel()` stays untouched.
- The 50→10px tightening schedule shape stays.
- Layered-confidence design stays; this plan adds admission gates and one anchor, it
  does not restructure.
- File caps: `multi_calibrate.py` is at ~700/750 — additions there must be minimal;
  new logic goes in `pole_finder.py` / `calibration_validate.py`.

## User-facing remediation (immediate, no code)
Delete `%LOCALAPPDATA%\PFRSentinel\allsky_calibration.json` on the affected rig — a
missing model is strictly better than the poisoned one; guided or bootstrap will
re-create it once the fixes land.

## Field test 2026-07-02 (first clear sky after the fixes) — findings & follow-ups

The user reset calibration and attempted auto + guided calibration on the real rig.
No model was admitted (good: the gates held), but three defects surfaced and were
fixed the same night:

1. **Triangle fallback crash (auto-cal).** The grid search converged to a wrong
   basin and the new pinned-a3 gate correctly rejected it; the triangle fallback
   then found the correct basin (east_left=True, 40 matches, prob 1.0) but
   `_iterative_fit` died at iteration 0 — scipy's "Initial guess is outside of
   provided bounds". Root cause: `triangle_match._extract_orientation` admits
   axis_alt ≥ 45 while the fit bounds start at 60, and roll/axis_az come back
   unwrapped. Fix: wrap the angles and clamp the seed into the fit bounds each
   iteration (`calibration.py::_iterative_fit`). Regression:
   `TestFitSeedFeasibility`.
2. **Camera had physically moved since the April reference model** (roll +21°,
   axis tilt ~16°, centre ~0.15·sky_r away). The guided free-centre leash
   (±5% sky_r) pinned at its corner — correct anchors could not fit better than
   14.5px. Fix: progressive leash 5% → 10% → 15%, wider stages only while the
   fit still fails the limit (`_CENTRE_RANGE_FRACTIONS`). The same anchors then
   solved at 1.8px. Implication: `sample_images/multi_calibration.json` is no
   longer ground truth for the *current* physical rig — it remains valid for the
   archived sample frames only.
3. **Guided anchors are user data and fail like it.** One mis-identification
   ("Alkaid" clicked on Mizar — 9px from Mizar through the consensus model) and
   one sloppy unsnapped click (Polaris, ~58px off) took an otherwise-perfect
   7-anchor set to RMS 54.7px, and the per-star residual report smears the error
   across all anchors (worst residual ≠ the bad anchor when the fit compromises).
   Fixes in `guided_calibration.py`:
   - full anchor input (name, pixel, RA/Dec, dt, sky circle) logged at INFO —
     failures are now replayable from the log alone;
   - outlier rescue: worst-first single (then pair) exclusions; a passing subset
     is the consensus model, excluded clicks are audited against the bright-star
     catalog through it and reinstated under the corrected identity when they sit
     on a different star (≤0.05·sky_r). Outcome reported via `guided_note`,
     surfaced in the controller status message. The field anchor set now solves
     at 7.0px, all 7 anchors, note "'Alkaid' is actually Mizar".
   Regressions: `test_bad_anchor_excluded_and_named`,
   `test_misidentified_anchor_reassigned`.

Open observations (not yet acted on):
- `estimate_sky_circle` returned r=1250 on the field frame vs the ~1563 reference
  trimmed radius at the same resolution (~20% under; centre was within 4px). That
  tightens every tol_scale-derived limit and under-seeds a1. Suspected cause: the
  horizon circle extends past the frame edge on this rig plus heavy obstruction.
  Worth a dedicated look if calibrations keep landing near the RMS limit.
- The grid search's a1 candidates cap at 0.99·min_half/(π/2) ≈ 963px on this rig
  while the true a1 ≈ 1250+ — the single-image grid can never reach the true
  basin here (known June-13 finding; triangle/guided/multi are the viable paths).
