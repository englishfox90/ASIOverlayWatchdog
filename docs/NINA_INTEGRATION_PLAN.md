# NINA Integration Plan — Capture Control API · Dockable Widget · Sequencer Instructions

**Created:** 2026-08-28
**Status:** Stage 0 complete and buildable end-to-end (P0, 0a–0d + UI + NINA scripts). 0e now only needs a real NINA + rig run — that run is the gate for Stages 1–3.
**Updated:** 2026-08-29
**Goal:** Surface the pier camera inside NINA's imaging dashboard (live frame + health), give the operator start/stop capture from NINA, and expose start/stop as Advanced Sequencer instructions so capture follows the observing session automatically.

---

## Decision record (why this shape)

| Decision | Choice | Rationale |
|---|---|---|
| Publish to `isbeorn/nina.plugin.manifests`? | **No** | The manifest repo only feeds NINA's plugin-manager discovery. Nothing in it is needed to *run* a plugin. Skipping it removes the manifest PR, plugin-manager review, and support burden for NINA versions/rigs we never test. |
| How is the plugin delivered? | **Bundled in the Sentinel installer + an "Install NINA Plugin" button** | A NINA plugin is just a DLL copied to a folder. Sentinel already ships a signed installer; the plugin rides along. |
| How is the plugin configured? | **Sentinel writes a sidecar JSON at install time** | This is the decisive advantage over publishing. Sentinel knows its own host/port and mints the auth token, so it can hand both to the plugin. Zero user configuration — no typing a URL or pasting a token. A published plugin structurally cannot do this. |
| Where does capture control live? | **Sentinel's HTTP API, not the plugin** | The plugin becomes a thin client. The same endpoints serve curl, Home Assistant, a phone bookmark, and NINA external-script sequence items. |

**Consequence worth stating plainly:** Stage 0 alone delivers the *automation* half with zero C#. NINA's Advanced Sequencer has an external-script instruction, so "start the pier camera when the roof opens, stop at dawn" works via `curl` the moment the control API exists. Stages 1–3 buy the *visual* half and a native drag-drop sequencer experience — real convenience, but not new capability. Sequence the work so that fact can be tested before committing to a C# codebase.

---

## Architecture

Four deliverables, each independently shippable:

```
Stage 0  services/api_control.py + control routes   (Python)   -> unlocks curl + NINA external-script
Stage 1  NINA plugin: dockable panel                (C#)       -> live frame + health in imaging tab
Stage 2  NINA plugin: sequencer instructions        (C#)       -> native Start/Stop sequence items
Stage 3  services/nina_plugin_install.py + button   (Python)   -> one-click install, zero-config pairing
```

### The load-bearing constraint: threading

**The HTTP server runs on a background thread. Capture start/stop touches Qt state.** A control endpoint must never call `start_capture()` directly — that violates `.claude/rules/services.md` and `ui-controllers.md`, and will race or crash.

The existing status path already solves the mirror-image problem, and the fix is to invert it:

- **Status (exists):** app *pushes* a snapshot into the server — `ui/main_window/output.py:388` → `WebOutputServer.update_capture_status()` (`services/web_output.py:530`). The server stays ignorant of capture; `services/api_status.py` turns the snapshot into the payload.
- **Control (new):** app *registers a command handler* with the server. The HTTP thread validates the request, hands the command to the handler, and the handler marshals to the owning thread.

This keeps `services/api_status.py`'s stated philosophy intact — *"The web server is deliberately ignorant of capture"* — and gives the two runtime hosts a clean seam:

| Host | Handler marshals via |
|---|---|
| `MainWindow` (GUI) | `QMetaObject.invokeMethod(..., Qt.QueuedConnection)` onto the GUI thread, then the existing `start_capture()` / `stop_capture()` |
| `HeadlessRunner` | direct call into its own capture lifecycle (no Qt loop) — see `services/headless_runner.py:367` for the existing symmetry |

Both register at the same point they already wire `update_capture_status`.

### Existing entry points the handler targets

| Path | Start | Stop |
|---|---|---|
| GUI | `ui/main_window/capture.py:487` | `ui/main_window/capture.py:527` |
| Controller | `ui/controllers/camera_controller.py:155` | `ui/controllers/camera_controller.py:347` |
| Precedent (non-panel trigger) | `ui/system_tray_qt.py:148` | `ui/system_tray_qt.py:162` |

The system tray is the existing proof that capture can be driven from outside the capture panel. Follow that pattern — but note the tray runs *on* the GUI thread and can call directly; the HTTP thread cannot.

---

## Blockers and size constraints (verified 2026-08-28)

The 750-line hook cap (`.claude/hooks/check_file_size.py`) materially shapes where code can go:

| File | Lines | Headroom | Implication |
|---|---|---|---|
| `ui/main_window/capture.py` | **760** | **BLOCKED** | **Already over the 750 cap and *not* in the hook's `EXCEPTIONS` list. Any edit is refused today.** Must be split before Stage 0 can wire control into the GUI capture path. |
| `services/web_output.py` | 610 | 140 | POST routing + auth + control dispatch will not fit. Extract, don't grow. |
| `ui/main_window/output.py` | 664 | 86 | Handler registration is small, but tight. Prefer a new module. |
| `services/api_status.py` | 180 | 570 | Fine — but control logic belongs in a sibling, not here (SRP). |

**Pre-work item (P0, blocks Stage 0):** split `ui/main_window/capture.py`. Use `/refactor-oversized`. This is a pre-existing debt the plan surfaces, not new work the plan creates — but it is genuinely blocking.

---

## Stage 0 — Capture control API (Python)

### New modules

- **`services/api_control.py`** — pure command validation and result shaping. Plain values in, dicts out; no Qt, no I/O; `now` injected. Mirrors `api_status.py` so it is cheap to unit-test across the full state matrix. Defines the command catalog reused by `api_docs.py` so OpenAPI cannot drift.
- **`services/api_auth.py`** — bearer-token compare (`hmac.compare_digest`), token generation, config plumbing.
- **`services/web_control.py`** — the `do_POST` route handlers, delegated from `web_output.py` exactly as `web_library.py` already is (`services/web_output.py:168-171`). Keeps `web_output.py` under cap.

### Endpoints

| Method | Route | Body | Behaviour |
|---|---|---|---|
| `POST` | `/capture/start` | `{"wait": bool, "timeout": int}` | Idempotent. Already running → `200` no-op. |
| `POST` | `/capture/stop` | `{"wait": bool, "timeout": int}` | Idempotent. Already stopped → `200` no-op. |
| `GET` | `/capture` | — | Current control state (alias of the `/status` `capture` block; convenience for clients). |

**Idempotency is a hard requirement**, not polish — a sequence that re-runs "Start" must not error, and a NINA sequence may legitimately fire Stop twice on abort.

**`wait` semantics:** when true, the call blocks until `state` reaches `capturing` / `stopped` or the timeout elapses, then returns the reached state. This is what makes sequencer instructions deterministic — the sequence should not advance until capture is genuinely running. Default `wait: true`, `timeout: 30`.

### Security model

Adding mutating routes invalidates three `ACCEPTED RISK` comments in `services/web_output.py` (W4 wildcard CORS + no Host validation at `:178-183`, W6 unbounded threads at `:423-428`). Each was accepted *explicitly because the API was read-only*. Required changes:

1. **Bearer token on every control route**, even on loopback. Generated on first enable, stored as `output.api_token` in config, never logged (reuse `services/youtube_upload.py::sanitize_exception:55`).
2. **Control routes must not send `Access-Control-Allow-Origin: *`.** This is the actual defence against DNS-rebinding and CSRF: without a permissive ACAO, a browser cannot read the response, and a custom `Authorization` header forces a preflight that will fail. Do **not** add `POST` to the existing `do_OPTIONS` allow-list at `:188`.
3. **`Host` header allow-list** (`localhost`, `127.0.0.1`, configured host) on control routes only — closes rebinding directly rather than relying on the CORS side effect.
4. **Bind stays `127.0.0.1`** (`services/config.py:54`) unless D1 says otherwise.
5. **Reject control requests when no token is configured** — fail closed, never "no token means open".

### Tests (`tests/test_api_control.py`, `tests/test_api_auth.py`)

Pure-logic modules make this cheap and marker-free (no `requires_network`):
- command validation: unknown command, malformed body, missing token, wrong token, correct token
- idempotency: start-when-running, stop-when-stopped
- `wait` reaching target state / timing out
- handler-not-registered → `503`
- token never appears in log output or error payloads
- ACAO header **absent** on control routes, **present** on `/status` (regression guard)

---

## Stage 1 — Dockable panel (C#)

**First task is a spike, not the panel:** build the unmodified [`isbeorn/nina.plugin.template`](https://github.com/isbeorn/nina.plugin.template) against the [`NINA.Plugin` NuGet package](https://www.nuget.org/packages/NINA.Plugin/) (3.2.0.9001 at time of writing), copy the DLL in by hand, confirm it loads. This validates the toolchain, the plugin API surface, and the install path *before* any Sentinel-specific code exists. Everything below assumes that spike passed; API details (`PluginBase` / `IPluginManifest`, `DockableVM` / `IDockableVM`, MEF `[Export]` wiring, the DataTemplate resource convention) should be taken from the template as built, not from this document.

**Panel contents:**
- Live frame from `GET /latest`, polled every 3–5s using `If-None-Match`. The endpoint already returns `304` on unchanged frames (`services/web_output.py:212-219`), so idle polling is nearly free.
- Staleness indicator driven by the `X-PFR-Image-Age-Seconds` / `X-PFR-Image-Stale` headers (`:236-239`) — grey the frame rather than showing an hours-old image as current.
- Health line from `GET /status` → `health.status` + `health.reasons` (`services/api_status.py`). The `reasons` array is already human-readable; render it verbatim.
- Start/Stop buttons → the Stage 0 endpoints, disabled while a command is in flight.

**Config:** read the Sentinel-written sidecar JSON (`{baseUrl, token}`) on load; expose an override in plugin settings for the case where Sentinel and NINA are on different machines.

---

## Stage 2 — Sequencer instructions (C#)

Two `ISequenceItem` exports: **Start Sentinel Capture**, **Stop Sentinel Capture**.

- `Execute()` calls the Stage 0 endpoint with `wait: true` so the sequence blocks until capture actually reaches the target state.
- Implement `Validate()` to check reachability + token, surfacing "Sentinel not reachable" as a sequence validation issue *before* the user starts a night — this is the difference between a good and a frustrating integration.
- Honour the `CancellationToken`; a cancelled sequence must not leave a half-issued command.
- `Clone()` per the template.

Optional follow-on (not scoped here): a *condition* or *trigger* item. Deliberately excluded — Sentinel already consumes roof state from NINA, so a Sentinel-side roof condition would be circular.

---

## Stage 3 — Install button (Python)

### New module: `services/nina_plugin_install.py`

Per `.claude/rules/python-general.md` module discipline, this is a distinct responsibility and gets its own file. Panel = button + status label only; controller threads it; service does the work.

**Responsibilities:**
1. **Resolve NINA's version** — read `NINA.exe` FileVersion from the uninstall registry key, falling back to the default Program Files path. Secondary fallback: scan existing `%LOCALAPPDATA%\NINA\Plugins\*` version folders and take the highest (empty on a fresh NINA with no plugins — hence the registry as primary).
2. **Compute target** — `%LOCALAPPDATA%\NINA\Plugins\<Major>.<Minor>.<Hotfix>\PFRSentinel\`.
3. **Copy** the bundled DLL + dependencies.
4. **Write the sidecar** `{baseUrl, token}` — the zero-config pairing step.
5. **Compare versions** — bundled DLL vs installed DLL, to drive an "Update available" state.
6. **Remove** — the counterpart button.

### The recurring gotcha: NINA upgrades orphan the plugin

The plugin folder is keyed to NINA's `Major.Minor.Hotfix`. When the user upgrades NINA 3.2 → 3.3, NINA reads from a `3.3.x` folder and the plugin silently vanishes. **Design for this, don't just handle first install:**
- The button is re-runnable (idempotent copy).
- On Sentinel startup, if the plugin is installed under a *different* NINA version folder than the current one, surface a non-modal "Reinstall NINA plugin" nudge.

### Packaging
- Add the DLL to PyInstaller `datas` and the Inno Setup payload.
- Resolve the bundled path through a frozen-aware helper (`sys._MEIPASS` vs source tree).
- Sentinel's uninstaller should offer to remove the plugin (per-user `LOCALAPPDATA`, so it needs explicit handling).

---

## Effort model

Traditional engineer-days are the wrong unit here — code volume is not the constraint. What actually costs:

- **Design** — decisions only the human can make. `D0` none · `D1` one call · `D2` several.
- **Build** — Claude working sessions. `S` one focused session · `M` two or three · `L` several with iteration.
- **Verify** — how it is *proven*, which is the real long pole. `unit` pytest, fast, no hardware · `rig` needs the observatory camera · `nina` needs NINA running · `field` needs a real night.

| # | Item | Design | Build | Verify | Notes |
|---|---|---|---|---|---|
| ~~**P0**~~ | ~~Split `ui/main_window/capture.py`~~ | D0 | S | unit | **DONE** — split into `capture.py` (365), `camera_detect.py` (324), `capture_watchdog.py` (99). `_MainWindowCaptureMixin` now composes both new mixins, so the surface is unchanged. |
| ~~**0a**~~ | ~~`services/api_control.py` + `api_auth.py`~~ | D1 | S | unit | **DONE** — 90 unit tests. Token minted on first enable via `resolve_control_token()`. |
| ~~**0b**~~ | ~~`services/web_control.py` routes + security~~ | D1 | M | unit | **DONE** — D1 answered: loopback only. 33 route tests incl. ACAO regression guard. |
| **0c** | Handler registration (MainWindow + HeadlessRunner) | D0 | M | rig | **BUILT, NOT RIG-VERIFIED.** `CaptureCommandBridge` (QueuedConnection) + headless pause Event. 11 tests pin the threading. Still needs a real-rig run. |
| ~~**0d**~~ | ~~OpenAPI/docs + tests~~ | D0 | S | unit | **DONE** — `/openapi.json` + `/docs` generated from `CONTROL_ROUTES`; routes hidden when control is off. |
| **0e** | **Prove value: NINA external-script sequence item** | D0 | S | nina | **SCRIPTS BUILT & TESTED against a live server; awaiting a real NINA+rig run.** `scripts/nina/` — see below. **Still the gate for Stages 1–3.** |
| **1a** | Spike: build + load template plugin | D0 | S | nina | De-risks all C#. **Needs the .NET 8 SDK — this machine has none.** See spike findings. |
| **1b** | Dockable panel | D2 | M | nina | D2 = layout/UX calls. |
| **2** | Sequencer instructions | D1 | S | nina | Small once 1a lands. |
| **3a** | `nina_plugin_install.py` | D1 | M | nina | Version detection is the fiddly bit. |
| **3b** | Panel/controller wiring + upgrade nudge | D0 | S | nina | |
| **3c** | PyInstaller + Inno packaging | D0 | M | field | Only provable via a real installer run. |

**Where the time actually goes:** items marked `nina` and `field` cannot be accelerated by generating code faster — they need NINA running, an installer built, and in a couple of cases a real night. Budget attention there. The Python-only, `unit`-verified items (P0, 0a, 0b, 0d) are where progress is cheapest and should be front-loaded.

**The C# bootstrap is a one-time cost, then a recurring tax.** Setting up the build loop is item 1a. The recurring part is rebuilding when NINA's plugin API moves between versions — pin the `NINA.Plugin` NuGet version and treat a NINA major/minor bump as a scheduled maintenance item, not a surprise.

---

## Spike findings (2026-08-29) — corrections to Stages 1–3

Researched before writing any C#. **Verified on this machine** unless marked inferred.

### The plugin install path in Stage 3a is wrong

The plan says the target is `%LOCALAPPDATA%\NINA\Plugins\<NINA Major>.<Minor>.<Hotfix>\`.
It is not. From NINA's `NINA.Plugin/Constants.cs`, the folder is keyed to
**`PluginMinimumApplicationVersion`** — the compatibility baseline stamped on
`NINA.Plugin.dll` — not to NINA's own version.

Verified here: **NINA is 3.2.0.9001, and its plugins live in `Plugins\3.0.0\`.**
Reading `NINA.exe`'s FileVersion, as Stage 3a step 1 instructs, would install the
DLL to `3.2.0\` where NINA never looks — a silent no-op.

Two consequences, both good:
- **Stage 3a gets simpler.** Enumerate `%LOCALAPPDATA%\NINA\Plugins\*`, take the
  highest parseable version, default `3.0.0`. No registry probe, no version parse.
- **"NINA upgrades orphan the plugin" is a much smaller risk than stated.** The
  folder only moves when the compat baseline moves (i.e. NINA 4.x), not on every
  3.2 → 3.3 bump. Keep the startup nudge; drop the "recurring tax" framing.

### Stage 3's sidecar JSON is not needed for pairing

A C# plugin can read `%LOCALAPPDATA%\PFRSentinel\config.json` directly in ~10 lines,
exactly as `scripts/nina/Invoke-SentinelCapture.ps1` already does. The sidecar only
earns its place if Sentinel and NINA run as different Windows users or on different
machines — excluded by D1. Stage 3 shrinks to "copy the DLL + offer an override".

### Toolchain

Needs the **.NET 8 SDK** and nothing else (`winget install Microsoft.DotNet.SDK.8`).
This machine has the .NET 8 *runtime* and MSBuild Build Tools but **no SDK**, so
nothing can build today. Visual Studio is not required — `dotnet build` suffices;
VS would only add the template's token-substitution wizard.

The template pins `NINA.Plugin` **3.0.0.2017-beta**; bump to **3.2.0.9001** to match
the installed NINA. Note .NET 8 reaches end-of-support **10 Nov 2026**, so a TFM
migration is near-term, not distant.

### Resequence: do Stage 2 before Stage 1

The plugin's value is concentrated in the *sequencer* half, and that half is also
the cheaper one:

| | Value over the existing scripts |
|---|---|
| Stage 2 `Validate()` | **Genuinely new capability.** NINA validates a sequence *before* the night starts. An External Script instruction cannot be validated — it fails at 22:15 when it runs. "Sentinel not reachable / control API disabled" at sequence-build time is what the scripts structurally cannot do. |
| Stage 2 native items | Cosmetic. The `.bat` already works. |
| Stage 1 panel | Real but ~90% replicated by a browser window on `http://127.0.0.1:8080`. The delta is not alt-tabbing. |

Stage 1 is also the expensive one: XAML, the `<FQTypeName>_Dockable` DataTemplate key
convention, a `ResourceDictionary` pack URI that fails *silently* through MEF if it
mismatches, and a polling lifecycle to gate on `IsVisible`.

**New order: 1a (spike) → 0e (real night) → 2 → decide again → 1b.**

### Open question to close during the spike

`IValidatable` is **not implemented in the template** — only referenced in a comment.
Its exact namespace and members (likely `Issues` + `Validate()`) could not be verified
from source. Resolve it by inspecting the restored `NINA.Sequencer.dll` during 1a
rather than designing around a guess.

### Done as a result of this spike: machine-readable error codes

Control error responses now carry a `code` field. `503` had two entirely different
causes — control API switched off vs. no capture handler registered — needing opposite
operator advice, distinguishable only by free-text prose. `Validate()` is only as good
as its ability to say *which* failure it hit. Codes: `bad_request`, `body_too_large`,
`unauthorized`, `host_not_allowed`, `control_disabled`, `control_unavailable`,
`internal_error`. The three auth failures deliberately share one code and one message.

---

## Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| Control endpoint called from HTTP thread touches Qt state | **High** — crashes or races | Handler-registration seam + `QueuedConnection`; never call capture directly from the request thread. Explicit test that the handler is invoked off the request thread. |
| Mutating API inherits read-only security assumptions | **High** | Token + no-wildcard-ACAO + Host allow-list on control routes; fail closed with no token. Security review before merge. |
| NINA upgrade orphans the plugin | **Low** (revised) — the folder tracks the plugin compat baseline, not NINA's version, so it moves only at NINA 4.x. Keep the re-runnable install + startup nudge. |
| NINA plugin API churn | Medium | Pin NuGet version; spike (1a) validates surface; private distribution means no third-party rigs to support. |
| `capture.py` over cap blocks work | Medium — already true | P0 split first. |
| Token leaks into logs / PostHog | Medium | Reuse `sanitize_exception`; explicit test. |
| Scope creep into a general remote-control API | Low | Endpoint surface is fixed at start/stop. Anything else is a new plan. |

---

## Open decisions

- ~~**D1 — Does NINA run on the same machine as Sentinel?**~~ **ANSWERED 2026-08-29: same machine, loopback only.** `webserver_host` stays `127.0.0.1`; control routes enforce a `Host` allow-list of loopback + the configured host. If NINA ever moves to a separate observatory PC, revisit 0b (LAN bind, TLS or SSH tunnel, and W6 thread exhaustion).
- **D2 — Panel scope.** Frame + health + two buttons, or also interval/exposure controls? Recommend shipping the minimal version first; more controls mean more endpoints and a wider mutating surface.
- **D3 — Does Sentinel's uninstaller remove the plugin?** Per-user `LOCALAPPDATA` path makes this non-automatic.

---

## What Stage 0 actually shipped (2026-08-29)

| Module | Lines | Role |
|---|---|---|
| `services/api_auth.py` | 218 | Bearer compare (`hmac.compare_digest`), Host allow-list, token minting, redaction |
| `services/api_control.py` | 286 | Command validation, idempotency, `wait` loop (injected clock), result shaping, `CONTROL_ROUTES` catalog |
| `services/web_control.py` | 218 | `do_POST` route handlers, delegated from `web_output.py` like `web_library.py` |
| `ui/controllers/capture_command_bridge.py` | 70 | `QueuedConnection` marshalling onto the GUI thread |

Wiring: `WebOutputServer.register_capture_command_handler()` / `set_control_token()`;
`ui/main_window/output.py` registers `CaptureCommandBridge`, `services/headless_runner.py`
registers `_handle_capture_command`.

Config (all under `output`, off by default): `webserver_control_enabled`,
`webserver_control_path`, `api_token`.

Tests: `test_api_auth.py` (43), `test_api_control.py` (51), `test_web_control.py` (33),
`test_capture_command_bridge.py` (11) — 138 new, all in the default pytest run,
no `requires_network` marker. Full suite: 1077 passed.

Verified live over a real loopback socket: 401 without/with a wrong token, `started`
then `already_running`, `stopped` then `already_stopped`, no `Access-Control-Allow-Origin`
on control responses, `/status` unchanged, control routes present in `/openapi.json`,
token absent from all log output.

**Headless semantics note:** `stop` *pauses* the capture loop rather than shutting the
runner down. Killing the process on "Stop" would leave nothing alive to receive the
matching "Start" at dusk, which would break the sequencer story the whole plan is for.

### UI (closes the gap that blocked 0e)

`ui/panels/output_settings.py` — inside the existing **Web Server** card:
an "Enable Capture Control API" `SwitchRow`, plus an API Token row
(read-only, password-masked `LineEdit` + Show / Copy / Regenerate).
Enabling it while the web server is off warns rather than silently doing nothing.

Token lifecycle lives on the window (`ui/main_window/settings.py`:
`ensure_control_token()`, `regenerate_control_token()`, `_apply_control_token()`),
not the panel — panels stay layout-only and never import `api_auth` or `secrets`.

**The non-obvious part:** `_ensure_output_servers_started()` reconciles only the
*enabled* flag, so a token change on a running server would otherwise not take
effect until the next restart. `_apply_control_token()` pushes it through
`WebOutputServer.set_control_token()`. `tests/test_control_token_ui.py` (13) pins this.

### NINA External Script helpers (item 0e)

`scripts/nina/Invoke-SentinelCapture.ps1` + `sentinel-capture-{start,stop}.bat` + `README.md`.

The script reads host/port/token from Sentinel's own `config.json`, so there is
**nothing to paste into NINA** — the same zero-config pairing the Stage 3 sidecar
was designed to give the C# plugin, achieved for the script path for free.
Waits for the target state, never prints the token, and exits non-zero so a failed
step fails the sequence instead of continuing silently.

Verified against a live loopback server — every documented exit code reproduced:
start→0, start again→0 (`already running`), stop→0, stop again→0, bad token→5,
unreachable→4, missing config→2.

Added to `PFRSentinel.spec` `datas` so they ship in an installed copy (NINA needs
the `.bat` on disk by path).

**Remaining for 0e:** point a NINA External Script instruction at the `.bat` on the
real rig and run a night. That is the decision point for Stages 1–3.

---

## Definition of done

- **Stage 0:** control endpoints authenticated and idempotent; `tests/test_api_control.py` + `test_api_auth.py` pass under the default pytest run; no ACAO on control routes (regression test); OpenAPI/`/docs` describe the new routes; start/stop verified against the real rig from both GUI and headless hosts.
- **Stage 0e (gate):** a NINA external-script sequence item starts and stops capture on the real rig. **Decide here whether Stages 1–3 are worth it.**
- **Stages 1–3:** plugin loads in NINA; panel shows a live frame that greys when stale; buttons drive capture; sequencer items validate-then-execute and block until state is reached; install button works from a built installer on a machine that has never had the plugin.

---

## References

- [nina.plugin.manifests](https://github.com/isbeorn/nina.plugin.manifests) — manifest schema (not used; documented for completeness)
- [nina.plugin.template](https://github.com/isbeorn/nina.plugin.template) — plugin boilerplate, the basis for item 1a
- [NINA.Plugin NuGet](https://www.nuget.org/packages/NINA.Plugin/) — plugin SDK
- Manual install path: `%LOCALAPPDATA%\NINA\Plugins\<Major>.<Minor>.<Hotfix>\<PluginName>\`
