# Hermes Notifications — Design & Implementation Plan

Status: **implemented** (2026-07-08). Adds Hermes as a second outbound-notification
backend alongside Discord. Both are independent sinks — either, both, or neither.
Not yet live-tested against a real Hermes endpoint (needs a subscribed route + secret).

## Goal

Today every operator notification (roof change, error, lifecycle, timelapse done,
calibration done, periodic image) is sent by ad-hoc `DiscordAlerts(config)`
instances scattered across ~5 files. We add a second backend, **Hermes**
(HMAC-signed JSON webhook consumed by an LLM agent that composes + delivers the
alert), without regressing the Discord path.

The refactor introduces a small **notification dispatcher** so call sites emit one
semantic event and the dispatcher fans out to every enabled backend.

## Non-goals

- No change to `services/discord_alerts.py` internals — the Discord backend is a
  thin adapter over the existing class. Discord behaviour must stay byte-identical.
- No new image-serving code. Hermes references the Library image **id**; the
  existing web endpoint `GET /library/image?id=<id>` resolves it.

## Hermes webhook contract (from vendor docs)

- **Auth: Generic V2.** Header `X-Webhook-Signature-V2` = HMAC-SHA256 **hex**
  digest of the ASCII string `"<timestamp>.<body>"`; header `X-Webhook-Timestamp`
  = Unix seconds. Server validates timestamp within ±300 s.
- **Signed bytes = the exact POST body bytes.** The backend MUST send the same
  bytes it signed — serialize once, sign those bytes, POST those bytes
  (`requests.post(url, data=body_bytes)`, never `json=`, which re-serializes and
  breaks the HMAC → 401).
- `Content-Type: application/json`. Max body 1 MB (we send ~hundreds of bytes; no
  image bytes ever cross the webhook — only the id + a resolvable URL).
- Route + secret are provisioned on the Hermes side (`hermes webhook subscribe`);
  the URL and shared secret are runtime config the user enters in the UI.

## Package layout — `services/notifications/`

| File | Responsibility |
|---|---|
| `events.py` | `NotificationEvent` dataclass + event-type constants. Backend-agnostic. |
| `base.py` | `NotificationBackend` ABC. Owns a per-backend `queue.Queue` + single daemon worker so a slow backend can't block another. Subclass implements `_deliver(event)` and `is_enabled()`. |
| `webhook_http.py` | Shared `post_with_retry()` (exp backoff, rate-limit aware) + `redact_webhook_error()`. Extract the retry/redact logic currently private to `discord_alerts.py`; re-export from `discord_alerts` for its existing callers. |
| `hermes_signing.py` | `sign_v2(secret, body_bytes, timestamp) -> (sig, headers)`. Pure, unit-testable. |
| `discord_backend.py` | Adapter: maps each event type to the matching existing `DiscordAlerts` method. No behaviour change. |
| `hermes_backend.py` | Builds semantic JSON per event, signs V2, POSTs. Reads the `hermes` config block for its own per-event gating. |
| `dispatcher.py` | `NotificationDispatcher` — constructs enabled backends, `notify(event)` fans the event into each enabled backend's inbox, `on_frame_archived(record)` caches latest image id, `test(name)` for UI test buttons, `shutdown()`. |

Keep each file well under the 750-line cap (all are small).

## `NotificationEvent` (events.py)

```python
ROOF_CHANGED = "roof_changed"
ERROR = "error"
LIFECYCLE = "lifecycle"          # data.phase: startup | shutdown | capture_started
PERIODIC_IMAGE = "periodic_image"
TIMELAPSE_DONE = "timelapse_done"
CALIBRATION_DONE = "calibration_done"

@dataclass
class NotificationEvent:
    type: str
    title: str = ""
    body: str = ""                 # human-ready line; Discord uses it, Hermes passes it through
    level: str = "info"            # info | warning | error | success
    image_id: int | None = None    # filled by dispatcher from frame_archived cache if None
    image_path: str | None = None  # local path (Discord attaches bytes; Hermes ignores)
    video_path: str | None = None
    data: dict = field(default_factory=dict)  # event-specific structured fields
```

## Dispatcher (dispatcher.py)

- Constructed once, holds the live `config` object (so `.get()` reads current values).
- Instantiates `DiscordBackend(config)` and `HermesBackend(config)` (both always
  constructed; each no-ops when its own `enabled` flag is false).
- `notify(event)`: if `event.image_id is None`, fill from `self._latest_image_id`.
  Then for each backend where `is_enabled()`, `backend.submit(event)` (enqueue).
  Fire-and-forget; never blocks the caller.
- `on_frame_archived(record)`: `self._latest_image_id = record.get("id")`. Wired to
  `library_controller.frame_archived` in `window.py`.
- `test(name) -> (bool, str)`: synchronously send a test message via that backend,
  return success + status for the UI.
- `shutdown()`: signal each backend worker to drain and stop (best-effort, daemonized).

Threading: each backend owns one daemon worker draining its own queue → per-backend
ordering, mutual isolation, bounded threads. Callers never spawn threads anymore.

## DiscordBackend event → method map (preserve exact behaviour)

| Event | Call |
|---|---|
| `ROOF_CHANGED` | `send_roof_status_change(data["roof_open"], data["confidence"], image_path)` |
| `ERROR` | `send_error_message(body)` |
| `LIFECYCLE` startup | `send_startup_message()` · shutdown → `send_shutdown_message()` · capture_started → `send_capture_started_message()` |
| `PERIODIC_IMAGE` | `send_discord_message(title, body, level, image_path=image_path)` (body is the token-formatted description built by the caller, matching today) |
| `TIMELAPSE_DONE` | `send_timelapse_completed(video_path, data["frame_count"], data["elapsed_seconds"])` |
| `CALIBRATION_DONE` | `send_calibration_complete(data["model_info"])` |

Per-event gating already lives inside those `DiscordAlerts` methods (they check
`discord.post_*`), so the backend just delegates. Move the `discord_post_sent`
analytics capture (currently in `output.py`) into the periodic branch here.

## HermesBackend

Config block `hermes` (see config additions). `is_enabled()` = `hermes.enabled and hermes.url`.
`_deliver(event)`: check the per-event flag; if off, return. Build payload, sign, POST
via `webhook_http.post_with_retry`. Log success/failure with redaction. Capture a
`hermes_post_sent` analytics event (past-tense, snake_case) mirroring Discord.

Per-event flags (mirror Discord names): `post_errors`, `post_startup_shutdown`,
`post_roof_changes`, `post_timelapse`, `post_calibration`, `periodic_enabled`.

### Payload schema (JSON, dot-notation-templatable)

Common envelope every event carries:

```json
{
  "event": "roof_changed",
  "level": "warning",
  "title": "Roof Closed",
  "body": "Roof is now Closed (confidence 94%)",
  "source": "PFR Sentinel",
  "timestamp": "2026-07-07T21:14:00Z",
  "image": { "id": 1234, "url": "http://127.0.0.1:8080/library/image?id=1234" }
}
```

`image` is included only when `image_id` is present AND the library API is enabled;
otherwise omit the key entirely. URL host: use `output.webserver_host`, but substitute
`127.0.0.1` when it is `0.0.0.0`; port `output.webserver_port`; path `/library/image`.

Event-specific keys (added alongside the envelope):

- `roof_changed`: `"roof": {"open": bool, "confidence": float}`
- `error`: `"error": {"text": "..."}`
- `lifecycle`: `"lifecycle": {"phase": "...", "mode": "watch|camera", "output_path": "..."}`
- `periodic_image`: `"capture": {"exposure": "...", "gain": N, "temp": "...", "resolution": "..."}`
- `timelapse_done`: `"timelapse": {"frame_count": N, "elapsed_seconds": N, "filename": "..."}`
- `calibration_done`: `"calibration": {"rms_residual": F, "n_matches": N, "calibrated_at": "...", "a1": F, "cx": F, "cy": F}`

### V2 signing (hermes_signing.py)

```python
import hmac, hashlib, time, json

def build_signed_request(secret: str, payload: dict):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode("utf-8"), f"{ts}.".encode("utf-8") + body,
                   hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Signature-V2": sig,
        "X-Webhook-Timestamp": ts,
    }
    return body, headers   # POST with data=body, headers=headers
```

## Config additions (services/config.py)

Add a top-level `hermes` block next to `discord`. Leave `discord` untouched
(old configs merge safely via the existing deep-merge).

```python
"hermes": {
    "enabled": False,
    "url": "",
    "secret": "",
    "post_errors": False,
    "post_startup_shutdown": False,
    "post_roof_changes": False,
    "post_timelapse": False,
    "post_calibration": False,
    "periodic_enabled": False,
},
```

Add a validate() warning mirroring Discord: enabled but url/secret empty.

## Call-site migration

Construct the dispatcher once in `window.py` (`self.notifier =
NotificationDispatcher(self.config)`), wire `library_controller.frame_archived
.connect(self.notifier.on_frame_archived)`, and call `self.notifier.shutdown()` in
the existing shutdown path. Then replace each Discord call site with a
`self.notifier.notify(NotificationEvent(...))`:

| File | Old | New event |
|---|---|---|
| `ui/main_window/output.py` | `_send_discord_startup/error/shutdown`, `_send_discord_periodic_update` | `LIFECYCLE` / `ERROR` / `PERIODIC_IMAGE` |
| `ui/controllers/image_processor.py` | `_send_roof_alert`, ASCOM safety `send_error_message` | `ROOF_CHANGED`, `ERROR` |
| `services/timelapse_publishers.py` | `_post_discord_if_enabled` (+ its retry loop) | `TIMELAPSE_DONE` (retry now lives in the backend) |
| `ui/controllers/allsky_controller.py` | `send_calibration_complete` call | `CALIBRATION_DONE` |

**Periodic gate:** the existing throttle/jitter logic in `output.py` (first-post,
interval, jitter) stays and continues to decide *when* to fire. Broaden its gate
from `discord_enabled and periodic_enabled` to "**any** backend has periodic
enabled", and at fire time call `self.notifier.notify(PERIODIC_IMAGE event)` — the
caller builds `body` (token-formatted description) and `image_path`; the dispatcher
fills `image_id`. Both backends post at that shared cadence (documented
simplification: one interval drives both; interval source = whichever backend has
periodic on, Discord winning ties).

Backends read live config, so callers no longer wrap sends in their own threads —
delete the ad-hoc `threading.Thread(...)` wrappers where they only guarded a send.

## UI (ui/panels/output_settings.py)

Add a **"Hermes Webhook"** `CollapsibleCard` mirroring the Discord card:

- `hermes_enabled_switch`, `hermes_url_input` (password echo + Show button),
  `hermes_secret_input` (password), per-event switches (`hermes_post_errors_switch`,
  `hermes_post_lifecycle_switch`, `hermes_post_roof_changes_switch`,
  `hermes_post_timelapse_switch`, `hermes_periodic_switch`,
  `hermes_post_calibration_switch`), `test_hermes_btn`, `hermes_status_label`.
- New signal `test_hermes_requested = Signal()`; method `set_hermes_test_result(ok, msg)`.
- `_on_hermes_settings_changed()` collects into `config['hermes']` + emits
  `settings_changed` (mirror `_on_discord_settings_changed`, respect
  `_loading_config`).
- Extend `load_from_config()` to populate the Hermes widgets.

If adding the card pushes the file toward the 750 cap, extract the Discord + Hermes
cards into a small helper (e.g. `_build_integrations_cards`) or a mixin module —
do **not** exceed the cap.

Wire in `window.py`: `output_panel.test_hermes_requested.connect(self._on_test_hermes)`.
Add `_on_test_hermes` in `output.py` (mirror `_on_test_discord`) → calls
`self.notifier.test("hermes")` and routes the result to
`output_panel.set_hermes_test_result(...)`.

## Tests (tests/test_hermes_notifications.py)

- `hermes_signing`: signature is deterministic for fixed (secret, ts, body); header
  names correct; body-mutation changes the signature.
- `HermesBackend`: builds the right payload per event type; omits `image` when no id
  / library disabled; includes resolvable URL when id present; per-event gating
  respects config flags; `enabled=False` → no POST (mock `requests`).
- `NotificationDispatcher`: `notify` fans to both backends; a disabled backend is
  skipped; `image_id` auto-fill from `on_frame_archived`; a raising backend doesn't
  break the other (isolation).
- Mock all network (`requests`). No real sockets. Follow `.claude/rules/tests.md`.

## Risks / decisions

- **Image reachability:** the id-URL is only resolvable if the web server is enabled
  and reachable from the Hermes host. Hermes is co-located (localhost), so this holds;
  when the library API is off we omit `image` rather than send a dead URL.
- **Clock skew:** V2 has a ±300 s window; co-located clock makes this a non-issue.
- **Do not break Discord:** all Discord behaviour is delegated to unchanged
  `DiscordAlerts` methods.
