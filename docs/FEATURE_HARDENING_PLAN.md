# Feature Hardening Plan — Web App · ASCOM Roof Safety · Timelapse

**Created:** 2026-06-28
**Source:** Multi-agent deep review (8 dimension finders → adversarial verification of every finding → 3 test-gap agents; 34 subagents). Findings below are the *verified* set — the adversarial pass demoted several plausible-but-wrong claims to false positives (see appendix). Core P0 findings were additionally hand-checked against source.

**Scope:** Harden three features for 24/7 **unattended (headless) observatory** use: (1) the web monitoring server, (2) the ASCOM roof safety-monitor file driven by the roof ML model, (3) the timelapse video pipeline.

## Deployment context (affects priorities)
- The app **does run headless** for 24/7 operation → `services/headless_runner.py` is a primary path, not a side path. This makes **W1 high-impact**.
- The web API is **local-only by design** → **authentication is explicitly out of scope** (W2 dropped). CORS / path-leak / DoS items are correspondingly low priority.

## Legend
- **Priority:** `P0` defeats the feature's stated purpose or is safety-critical · `P1` robustness / graceful-failure / safety hardening · `P2` defense-in-depth / polish.
- **Size:** `S` ≈ <1h (local change + 1–2 tests) · `M` ≈ a few hours (logic change + several tests) · `L` ≈ a day+ (cross-cutting).
- **Status:** `todo` · `needs-decision` · `out-of-scope`.

---

## Orientation for implementers (read this first)

This backlog is meant to be actioned by an engineer/agent with **no prior context**. Follow the repo's existing conventions while implementing — they are enforced by hooks and a reviewer.

- **Run tests:** fast/default `pytest -m "not requires_camera and not requires_network and not requires_ml_models"`; full suite `pytest`. Markers are defined in `pytest.ini`. Test conventions: `.claude/rules/tests.md`.
- **Conventions are enforced — read the relevant rule file before editing:** `.claude/rules/services.md`, `ui-controllers.md`, `ui-panels.md`, `services-camera.md`, `ml.md`, `tests.md`. A PreToolUse hook **blocks** any edit that pushes a file past **750 lines**; `services/web_output.py` (~535), `services/timelapse_writer.py` (~606), and `ui/panels/timelapse_panel.py` (~748) are at/near the cap — **extract a helper module rather than growing them** (re-export moved symbols for back-compat).
- **Logging:** `from services.logger import app_logger`; never `print()` (a `print()` from a worker thread can deadlock the Qt event loop).
- **Config:** read/write only through `services.config` (`config.get/set/save`); keys are **nested**; never touch `config.json` directly. Resolve paths via `app_config.get_config_dir()`.
- **Threading:** worker threads must never touch Qt widgets — emit a signal/slot. Business logic + threads live in `ui/controllers/`; `ui/panels/` is layout-only.
- **Definition of done (per item):** the named test(s) pass under the default pytest command, no existing test regresses, and the change honours the rules above. Re-run the matching `tests/test_*.py`. For behaviour changes, also confirm the bug reproduces *before* the fix (the named test should fail first).
- **Blocked item:** **R1 is blocked** until the fail-safe policy is chosen (see *Open decision*). Every other item is independently actionable.

## Key code locations (shared by several items)

- **Roof ML → safety-file / Discord pipeline** — `ui/controllers/image_processor.py`:
  - ML inference block: `:307-337`. The **ASCOM safety write is at `:331-335`** (`write_ascom_safety_file(ml_results, ascom_config)`), fired on **every** frame, gated only by `ascom_safety_file.enabled` — i.e. on the *raw* per-frame result.
  - **2-consecutive-frame confirmation FSM:** `_check_roof_change()` at `:426-456`; state held in `self._confirmed_roof_open` / `_pending_roof_open` / `_pending_roof_count` (initialised `:53-55`); invoked at `:406`; fires `DiscordAlerts.send_roof_status_change()` (`services/discord_alerts.py:395`) **only on the 2nd consecutive change**.
  - **R1/R4 fix anchor:** route the safety-file write through this *confirmed* state (e.g. from inside `_check_roof_change` once confirmed), not the raw `ml_results`.
- **Config defaults** — `services/config.py`:
  - Web server lives under **`output.*`**: `webserver_enabled=False`, `webserver_host="127.0.0.1"` (**loopback by default**), `webserver_port=8080` (`:53-55`). Note: `WebOutputServer.__init__`'s own default arg is `0.0.0.0`, so confirm which host the start path actually passes — under default config the bind is loopback, which further de-risks W4/W5/W6.
  - ASCOM safety lives under **`ml_models.ascom_safety_file.*`**: `enabled=False`, `file_path=<AppData>/RoofStatusFile.txt`, `preamble="Roof Status:"`, `open_trigger="OPEN"`, `closed_trigger="CLOSED"`, `min_confidence=0.7` (`:155-163`).
  - Timelapse lives under **`timelapse.*`**; sun-window coords are injected from `weather.latitude/longitude` by `TimelapseController._get_timelapse_config()` (`ui/controllers/timelapse_controller.py:192-200`).
- **Roof config UI** (toggles the keys above): `ui/panels/image_processing_ml.py`.
- **Secret-redaction helper (T5):** `services/youtube_upload.py::sanitize_exception` (`:55`) already strips secrets — reuse it.

---

## Summary table

| ID | Pri | Size | Feature | Finding | Pointer |
|----|-----|------|---------|---------|---------|
| **R1** | P0 | M | Roof | Uncertain prediction (N/A / low-conf) skips write → stale `OPEN`/safe file left on disk (fail-dangerous) | `services/ascom_safety.py:84-92` |
| **T1** | P0 | S | Timelapse | Sun-window times in UTC compared to naive **local** `now()` → window shifted by the host's UTC offset (e.g. UTC−6 ≈ 6h off) | `services/timelapse_writer.py:456-503` (`_sun_window`) |
| **W1** | P0 | S | Web | Headless gates web server on legacy `output.mode=='webserver'`; modern GUI writes `output.webserver_enabled` → web monitoring silently dead headless | `services/headless_runner.py:83,150` |
| **T2** | P0 | M | Timelapse | `BrokenPipeError` nulls process without `kill()/wait()` and bypasses crash-loop guard → leaked ffmpeg + partial regression of `d271cc8` | `services/timelapse_writer.py:146-148` |
| **R2** | P1 | S | Roof | Write/`os.replace` failure leaves stale `OPEN` on OPEN→CLOSED; caller discards `False` return (debug-only log) | `ascom_safety.py:113-117`, `image_processor.py:335` |
| **R3** | P1 | M | Roof | **No `test_ascom_safety.py`** for a safety-critical writer | (test gap) |
| **R4** | P1 | M | Roof | ASCOM write is **per-frame — no 2-frame confirmation** (Discord has it); `roof_confidence=None` bypasses `min_confidence` gate | `image_processor.py:331-335` |
| **T3** | P1 | M | Timelapse | Unlocked `self._process` start/exit mutation races `_stop_session()` → orphan ffmpeg / wrong session reported | `timelapse_writer.py:100-124` |
| **T4** | P1 | M | Timelapse | Finalization (`wait(60)` + file-stable poll) runs on the **frame-delivery thread** on resolution-change & `always` midnight rollover → stalls capture | `timelapse_writer.py:120-124` |
| **T5** | P1 | S | Timelapse | Discord webhook **token leaked into logs + forwarded to PostHog** on connection error | `discord_alerts.py:567-569,293-296` |
| **W7** | P1 | S | Web | Web-encode and Discord share one `try/except` in dispatch → a web failure skips the Discord post | `ui/main_window/output.py:530-594` |
| **T6** | P2 | M | Timelapse | Interrupted YouTube upload stranded `in_progress` forever — never retried/resumed | `services/youtube_upload_state.py:55-75` |
| **W3** | P2 | S | Web | Torn read of shared class-level image state → occasional truncated/garbled `/latest` frame (sub-ms window, self-heals) | `web_output.py:50-70,142-187` |
| **W8** | P2 | S | Web | Runtime toggle of `webserver_enabled` neither starts nor stops server; `_stop_web_server` is dead code | `ui/main_window/output.py:279-286,347-357` |
| **W9** | P2 | S | Web | `/latest` tagged with `self.preview_metadata` not the per-job metadata → `/status` vs `/latest` mismatch on bursts | `ui/main_window/output.py:512-517,549` |
| **W5** | P2 | S | Web | `/status` leaks absolute server path (Windows username + layout) | `web_output.py:208` |
| **R5** | P2 | S | Roof | `median_lum` 16-bit fix is correct but **unpinned by any test** (regression risk) | `ml_service.py:296-304` |
| **R6** | P2 | S | Roof | Module-global writer ignores `min_confidence`/trigger changes until restart | `ascom_safety.py:183-192` |
| **T7** | P2 | S | Timelapse | Orphan output file only deleted when *exactly* 0 frames written (1–4 frame stub survives) | `timelapse_writer.py:172-179` |
| **W4** | P2 | S | Web | Wildcard CORS + no Host validation (DNS-rebind vs loopback) | `web_output.py:133-140` |
| **W6** | P2 | M | Web | Unbounded thread-per-connection (flood DoS) | `web_output.py:353-355` |
| **W2** | — | — | Web | No API authentication | **out-of-scope** — local-only deployment (decided 2026-06-28); revisit only if the server is ever bound to a non-loopback host |

**Suggested first slice (P0):** R1, T1, W1, T2 + their regression tests. T1 and W1 are each ~S and high-value (each currently breaks the feature for headless/non-UTC users).

---

## Detailed findings

### Web app (camera monitoring)

#### W1 — Headless web server silently dead `[P0 · S]`
- **Where:** `services/headless_runner.py:83` and `_webserver_mode_enabled()` at `:150` gate on `config.output.mode == 'webserver'`. The modern GUI writes `output.webserver_enabled` (see `ui/main_window/output.py`), never `output.mode`.
- **Impact:** In the headless 24/7 deployment, a user who enables the web server in the GUI gets nothing served — the only live monitoring surface is dead and there's no error.
- **Fix:** Change both the `start()` gate and `_webserver_mode_enabled()` to `config.get('output', {}).get('webserver_enabled', False)`, OR-ing with the legacy `mode == 'webserver'` for old configs. Optionally add a config migration `webserver_enabled = (mode == 'webserver')`.
- **Test:** `tests/test_web_server_retry.py::test_headless_starts_webserver_from_webserver_enabled_flag` — build `HeadlessRunner` with `{'output': {'webserver_enabled': True, 'webserver_host': '127.0.0.1', 'webserver_port': 8080}}` (mode absent), patch `WebOutputServer`, assert the server is started.

#### W7 — Web-encode failure suppresses the Discord post `[P1 · S]`
- **Where:** `ui/main_window/output.py:530-594` — web encode+push and Discord scheduling share one `try/except`.
- **Fix:** Split into two independent `try/except` blocks so neither sink can suppress the other.
- **Test:** `test_web_encode_failure_does_not_block_discord` — stub `web_server` whose `processed_img.save` raises; assert the Discord method is still invoked.

#### W3 — Torn read of shared image state `[P2 · S]`
- **Where:** `services/web_output.py:50-70` (writer) vs `:142-187` (reader) — 6 class attributes mutated unlocked while request threads read `latest_image_data` independently for the 404 guard, Content-Length, and body.
- **Impact:** A poll coinciding with a frame push can yield Content-Length ≠ body (truncated/garbled frame), occasionally locked in under the new ETag until the next update. Verifier downgraded to **low** (sub-ms window, HTTP/1.0 closes per response, self-heals next frame).
- **Fix:** Build an immutable snapshot tuple `(data, content_type, etag, update_time)` and assign in one statement; readers bind it to a local once.
- **Test:** `tests/test_webserver.py` concurrency test — alternate two JPEGs of very different sizes while 8 threads GET `/latest`; assert every 200 has `len(content) == Content-Length` and decodes.

#### W8 — Runtime toggle doesn't start/stop server `[P2 · S]`
- **Where:** `ui/main_window/output.py:279-286,347-357`. Flipping `webserver_enabled` at runtime does nothing; `_stop_web_server` is dead code.
- **Fix:** Drive lifecycle from the settings-changed path (start when enabled, call `_stop_web_server()` when disabled).
- **Test:** `test_runtime_toggle_starts_and_stops_web_server`.

#### W9 — `/latest` uses preview_metadata not job metadata `[P2 · S]`
- **Where:** `ui/main_window/output.py:512-517,549` — served image tagged with `self.preview_metadata` instead of the job's metadata → `/status` can describe a different frame than `/latest` on bursts.
- **Fix:** Thread the job metadata through `_push_to_output_servers` into `update_image`.
- **Test:** `test_web_push_uses_job_metadata`.

#### W5 — `/status` leaks absolute filesystem path `[P2 · S]`
- **Where:** `web_output.py:208` returns the absolute image path (drive + username + layout).
- **Fix:** Return `os.path.basename(...)` or an opaque label; scrub `latest_metadata` for path/location tokens.
- **Test:** `test_status_does_not_leak_absolute_paths`.

#### W4 / W6 — CORS rebinding / unbounded threads `[P2]`
Low priority given local-only deployment. W4: drop blanket `ACAO:*` on `/status`/`/library`, validate Host. W6: cap concurrency via a bounded pool / active-connection 503. Document rather than fix unless exposure changes.

---

### ASCOM roof safety file (roof ML)

> The safety file tells NINA's GenericFile Safety Monitor whether it is safe to keep the roof/dome and gear operating. A wrong "safe" can damage equipment, so the bias must be fail-safe.

#### R1 — Uncertain prediction leaves a stale "safe" file `[P0 · M · needs-decision]`
- **Where:** `services/ascom_safety.py:84-92` — `roof_status == 'N/A'` or `roof_confidence < min_confidence` returns `False` **without writing**, leaving the previous file (possibly `OPEN`) on disk.
- **Impact:** Model goes blind/uncertain (cloud, dawn wash, inference hiccup) and NINA keeps reading the last `OPEN` → "safe". Fail-dangerous unless the operator has configured NINA's "maximum file age".
- **DECISION NEEDED — pick the fail-safe policy:**
  - **(A) Write UNSAFE on uncertainty** *(recommended)* — any state that isn't a confident, confirmed `Open` writes the closed/unsafe trigger; gate transitions behind the 2-frame confirmation (R4) so one noisy frame can't slam the dome.
  - **(B) Keep last state + freshness** — always re-stamp the current confirmed state with a timestamp; rely on NINA max-age for staleness.
  - **(C) Tests + docs only** — pin current behavior, document the NINA max-age requirement, no semantic change.
- **Tests:** `test_na_after_open_writes_unsafe` (under A), `test_na_status_leaves_previous_open_file_unchanged` (pins current behavior under C).

#### R2 — Write failure silently retains "safe" `[P1 · S]`
- **Where:** `ascom_safety.py:113-117` returns `False` on exception; caller `image_processor.py:335` discards it (debug log only).
- **Fix:** Escalate a failed safety write to an operator-visible channel (Discord/tray alert + `capture_error` PostHog event); have the caller act on `False`.
- **Test:** `test_write_failure_does_not_retain_safe` (monkeypatch `os.replace` to raise on an OPEN→CLOSED write; assert `False` + escalation invoked).

#### R3 — No `test_ascom_safety.py` `[P1 · M]`
Create the suite (≈14 cases): open/closed happy paths + preamble; `_atomic_write` leaves no `.tmp` on success and cleans temp + preserves original on error; `min_confidence` gating + boundary; **`None`-confidence bypass (flag)**; **`N/A` leaves stale file (flag)**; disabled-config no-op; unexpected-status→`CLOSED`; missing-parent-dir creation + creation-failure; global-instance config-change-ignored (flag, pins R6); `get_last_status/time` bookkeeping.

#### R4 — Per-frame safety write, no confirmation `[P1 · M]`
- **Where:** `ui/controllers/image_processor.py:331-335` — `write_ascom_safety_file(ml_results, ascom_config)` fires on **every** frame whenever `ascom_safety_file.enabled`, with no 2-consecutive-frame confirmation (the Discord roof-change path *does* confirm). Also `roof_confidence=None` slips past the `min_confidence` gate in `ascom_safety.py:90`.
- **Fix:** Drive the safety write from the **same confirmed roof-state FSM that gates the Discord alert** — `_check_roof_change()` at `image_processor.py:426-456` (state `_confirmed_roof_open`/`_pending_roof_open`/`_pending_roof_count`, see *Key code locations*). Move the safety write to fire on a *confirmed* transition rather than the raw per-frame `ml_results`, and treat `None` confidence as below threshold. (Note R4 and R1 share this anchor — implement together.)
- **Tests:** `test_safety_file_written_every_frame_without_confirmation` (pins current), then `test_roof_change_requires_two_consecutive` for the FSM.

#### R5 — `median_lum` 16-bit fix unpinned `[P2 · S]`
`ml_service.py:296-304` normalizes by dtype bit-depth and feeds `frame_med` — the old "Closed on open roof" bug is fixed but has no test. Add `test_frame_med_normalized_by_bit_depth` (uint16 30000 → ≈0.4578; uint8 117 → ≈0.459).

#### R6 — Global writer ignores config changes `[P2 · S]`
`ascom_safety.py:183-192` only rebuilds `_writer_instance` when `file_path` changes; a tightened `min_confidence`/trigger is ignored until restart. Rebuild when any relevant field changes (or compare the whole config). Pinned by an R3 test.

---

### Timelapse video

#### T1 — Sun-window UTC vs naive local time `[P0 · S]`
- **Where:** `services/timelapse_writer.py:456-503` (`_sun_window`) — astral returns tz-aware **UTC**; code does `.replace(tzinfo=None)` then compares to `datetime.now()` (naive **local**).
- **Impact:** Recording window is shifted by the local UTC offset. In MDT (UTC−6) a sun/astronomical window is ~6h wrong; recording starts/stops at the wrong time. (Falls back to fixed-window correctly only if lat/lon are unset.)
- **Fix:** Convert to local naive (`dt.astimezone().replace(tzinfo=None)`) or compare tz-aware throughout (`datetime.now().astimezone()`).
- **Test:** monkeypatch astral to a known UTC time, pin `now()` to a non-UTC local zone, assert the window matches local wall-clock.

#### T2 — BrokenPipe leaks ffmpeg + bypasses crash-loop guard `[P0 · M]`
- **Where:** `services/timelapse_writer.py:146-148` — `except BrokenPipeError:` sets `self._process = None` without `kill()/wait()` and without the backoff/orphan-cleanup in `_handle_unexpected_exit`.
- **Impact:** Leaked ffmpeg process + handle; the next frame immediately starts a new session with no backoff — the one-broken-video-per-frame failure mode `d271cc8` was meant to kill, partially reintroduced.
- **Fix:** Extract the `_handle_unexpected_exit` body into a shared helper `(died_frames, died_path)`; on `BrokenPipeError`, capture the proc, `kill()/wait()` it, then run the same backoff + orphan cleanup.
- **Test:** fake Popen whose `poll()` returns None but `stdin.write` raises `BrokenPipeError`; feed 20 frames with an advanceable clock; assert exactly one Popen created, `_restart_failures >= 1`, `_restart_blocked_until` set.

#### T3 — Unlocked `_process` mutation races stop `[P1 · M]`
- **Where:** `timelapse_writer.py:100-124` — `poll()`, `_handle_unexpected_exit()`, and `_start_session()` mutate `self._process` outside `self._lock` while `_stop_session()` mutates under it.
- **Fix:** Add a `_stopped`/`_shutting_down` flag set under the lock in `stop()`; perform all `self._process`/session-field reads+writes under the lock (snapshot to locals before the long finalize); have `add_frame` early-return when stopping.
- **Test:** one thread `stop()` while another calls `add_frame()` repeatedly; assert no live process remains and ≤1 extra Popen ever created. Plus `stop()` then `add_frame()` is a no-op.

#### T4 — Finalization blocks the frame-delivery thread `[P1 · M]`
- **Where:** `timelapse_writer.py:120-124` — resolution-change and `always`-mode midnight rollover call `_stop_session()` (with `wait(60)` + 1–10s file-stable poll) inline on the capture thread.
- **Fix:** Hand the old process to a background finalizer (same pattern the controller uses for capture-stop), so `add_frame` returns promptly.
- **Test:** fake process whose `wait()` sleeps; trigger a resolution change between two `add_frame()` calls; assert the triggering call returns within a small bound and the wait runs off-thread.

#### T5 — Discord webhook token leaked to logs + PostHog `[P1 · S]`
- **Where:** `services/discord_alerts.py:567-569` (also `293-296`) logs the raw exception, which can contain `/api/webhooks/<id>/<token>`; also stored in `last_send_status` and forwarded to analytics.
- **Fix:** Route all Discord error text through a redaction helper (reuse `services.youtube_upload.sanitize_exception` or add a Discord-specific one); log only `type(e).__name__` + redacted message; never store `str(e)`.
- **Test:** `tests/test_discord.py` — monkeypatch `requests.post` to raise a `ConnectionError` whose message contains a sentinel token; assert the token does not appear in logs or `last_send_status`.

#### T6 — Interrupted YouTube upload stranded forever `[P2 · M]`
- **Where:** `services/youtube_upload_state.py:55-75` — an `in_progress` entry is never reclaimable after a crash, so the upload never resumes/retries.
- **Fix:** In `claim()`, treat a stale `in_progress` entry (old `claimed_at`, or no worker running) as reclaimable, preserving `resumable_uri`; or re-enqueue stale entries on startup.
- **Test:** seed a stale `in_progress` entry with a `resumable_uri`; assert `claim()` reclaims it and keeps the URI.

#### T7 — Orphan file kept for 1–4 frame stubs `[P2 · S]`
- **Where:** `timelapse_writer.py:172-179` — orphan removed only when `died_frames == 0`.
- **Fix:** Gate on `died_frames < _HEALTHY_FRAME_THRESHOLD and died_path`.
- **Test:** fake ffmpeg writes 3 frames then exits; assert the orphan file is removed and `_restart_failures` incremented.

---

## Test plan (≈52 cases ready to implement)

The review produced concrete, named test specs with assertions and mocks. New files needed:
- **`tests/test_ascom_safety.py`** (new) — ~14 cases (R3).
- **`tests/test_ml_service.py`** (new) — `median_lum` bit-depth regression + sky-gated-on-roof (R5).
- **`tests/test_image_processor.py`** (new) — 2-frame confirmation FSM + per-frame-safety-write pin (R4).
- **`tests/test_output_dispatch.py`** (new) — web-failure-doesn't-block-Discord (W7).
- **Extend** `tests/test_webserver.py` (downsize-over-cap, failed-downsize-keeps-previous, concurrent consistency, CORS, path-leak), `tests/test_image_library.py` (traversal-id rejection — currently safe, pins it; file-vanished 404), `tests/test_timelapse_writer.py` (every window mode incl. overnight + astral-missing; crash-loop backoff **and reset-after-healthy**; BrokenPipe; ffmpeg-missing; finalize-only-on-clean-exit-with-frames; kill-on-timeout; resolution-change restart; **midnight-split-only-in-`always`**; output-path dedup), `tests/test_youtube_uploads.py` (**overlay-leak regression: include_overlays=False ⇒ clean frame**; roof_open injection; finalize lifecycle; sanitize; queue-full), `tests/test_discord.py` (token redaction).

Markers: use `requires_network` for cases that bind a real socket; the rest run in default CI.

---

## Appendix — ruled out by the adversarial pass (do not chase)
- ASCOM `.tmp` fixed-name collision race — single producer thread; not reachable.
- Per-session stderr-drain thread "leak" — daemon thread, bounded `deque(maxlen=12)`; benign.
- `/status` body-after-headers truncation — dormant; every metadata producer stringifies today.
- `/library/image` path traversal via `id` — **not present**; served by integer id → index lookup in `library.read_image()`, not a user path. (A regression test still recommended to keep it that way.)
- Cached-writer "config ignored" (R6) — real but low (correctness nit, not a hazard); demoted from medium.

## Open decision
- **R1 fail-safe policy (A / B / C above)** — blocks the R1 implementation. Everything else can proceed without it.
