# PostHog Integration Reference

Quick reference for adding PostHog analytics events to PFR Sentinel.

**SDK Version**: 7.9.12 | **Python**: 3.10+ | **Docs**: https://posthog.com/docs/libraries/python

---

## Setup

PostHog is initialized in [`services/posthog_service.py`](../../services/posthog_service.py).

### Preferred helpers (handles distinct_id + error swallowing)

```python
from services.posthog_service import capture_event, capture_error

# Track an event
capture_event('event_name', {'key': 'value'})

# Track a caught exception with stack trace
capture_error(e, context='camera_capture_loop')
```

### Low-level access (only needed for set/group/feature flags)

```python
from services.posthog_service import posthog, get_distinct_id
```

---

## Opt-Out

Users can disable all analytics via **Settings > System > "Send Anonymous Usage Data"**.
This sets `analytics_enabled: false` in config.json and immediately disables all tracking
including SDK exception autocapture.

The default is **opted in**. All helper functions (`capture_event`, `capture_error`) check
`is_enabled()` before sending. The SDK's `disabled` flag is also set to block autocapture.

## Distinct ID

Each installation gets a random anonymous UUID stored in `config.json` as `posthog_distinct_id`.
The helpers handle this automatically. For low-level calls, always use `get_distinct_id()`.

---

## Live Event Catalog

All events currently instrumented in the codebase:

### Lifecycle

| Event | Properties | Location |
|-------|-----------|----------|
| `install_started` | `version`, `install_type` (fresh/upgrade), `installer` | `installer/PFRSentinel.iss` |
| `app_installed` | `version`, `install_type` (fresh/upgrade), `installer` | `installer/PFRSentinel.iss` |
| `app_started` | `version`, `is_admin` | `main.py` |
| `app_shutdown` | — | `main.py` |
| `update_available` | `current_version`, `latest_version` | `ui/main_window.py` |

### Navigation

| Event | Properties | Location |
|-------|-----------|----------|
| `$pageview` | `$current_url` (e.g. `/app/monitoring`, `/app/capture`) | `ui/main_window.py` |

Pages: `monitoring`, `capture`, `output`, `processing`, `overlays`, `timelapse`, `logs`, `settings`

### Capture Sessions

| Event | Properties | Location |
|-------|-----------|----------|
| `capture_started` | `version`, `mode`, `camera_name`, `auto_exposure`, `output_format`, `output_file_enabled`, `output_web_enabled`, `output_discord_enabled`, `output_discord_interval_min`, `output_rtsp_enabled`, `weather_enabled`, `timelapse_enabled`, `ml_enabled`, `overlay_count`, `overlay_tokens`, `auto_stretch_enabled`, `scheduled_capture` | `ui/main_window.py` |
| `capture_stopped` | `mode`, `images_processed` | `ui/main_window.py` |

### Outputs

| Event | Properties | Location |
|-------|-----------|----------|
| `discord_post_sent` | `interval_minutes`, `include_image` | `ui/main_window.py` |
| `discord_image_sent` | `image_size_kb`, `image_width`, `image_height`, `was_resized`, `original_width`, `original_height`, `skipped_too_large` | `services/discord_alerts.py` |

### Features

| Event | Properties | Location |
|-------|-----------|----------|
| `weather_configured` | `units` | `ui/main_window.py` |
| `timelapse_recording_started` | `window_mode`, `playback_fps`, `output_resolution`, `video_quality`, `include_overlays`, `frame_width`, `frame_height` | `services/timelapse_writer.py` |
| `timelapse_session_finished` | `frame_count`, `duration_seconds`, `file_size_mb`, `discord_delivery`, `youtube_delivery` | `ui/controllers/timelapse_controller.py` |
| `youtube_timelapse_upload` | `success`, `status`, `retryable`, `file_size_mb` | `services/timelapse_publishers.py` |
| `calibration_completed` | `success`, `duration_seconds`, `attempts`, `final_exposure_ms`, `final_brightness`, `target_brightness`, `max_exposure_ms` | `services/zwo_camera.py` |

### Errors

| Event | Properties | Location |
|-------|-----------|----------|
| `error_captured` | `error_type`, `error_message`, `stack_trace`, `context` | via `capture_error()` helper |
| `$exception` (auto) | full stack trace | SDK autocapture (unhandled exceptions) |

YouTube upload code must catch Google/OAuth exceptions at the module boundary
and convert them to sanitized typed results. Do not send tokens, auth codes,
client secrets, file paths, upload URLs, titles, descriptions, tags, channel
IDs, video IDs, or watch URLs in analytics.

**Error contexts** (the `context` property in `error_captured`):
- `camera_capture_loop` — ZWO capture thread exception
- `camera_start` — camera connection/init failure
- `image_processor_worker` — processing thread crash
- `image_processing` — overlay/stretch/save failure
- `file_watcher` — directory watch file processing failure

---

## Adding New Events

Use the helper functions — they handle distinct_id and silently swallow errors:

```python
from services.posthog_service import capture_event, capture_error

# Feature usage
capture_event('overlay_applied', {
    'overlay_count': 3,
    'has_weather': True,
})

# Caught exception with context
try:
    risky_operation()
except Exception as e:
    app_logger.error(f"Operation failed: {e}")
    capture_error(e, context='my_feature')
```

### Naming Conventions

- **snake_case** for event names: `capture_started`, not `CaptureStarted`
- **Past tense** for completed actions: `discord_post_sent`, `timelapse_session_finished`
- **Context prefix** where helpful: `camera_start`, `image_processing`

---

## SDK Reference

### Setting User/Device Properties

```python
posthog.set(
    distinct_id=get_distinct_id(),
    properties={
        'os': 'Windows 11',
        'app_version': '3.4.4',
        'camera_model': 'ASI676MC',
    }
)
```

### Group Analytics

```python
posthog.group_identify(
    group_type='observatory',
    group_key='obs_001',
    properties={'name': 'Home Observatory', 'location': 'UK'},
)

posthog.capture(
    distinct_id=get_distinct_id(),
    event='capture_started',
    groups={'observatory': 'obs_001'},
)
```

### Feature Flags

Requires `personal_api_key` in init.

```python
if posthog.feature_enabled('new-timelapse-ui', get_distinct_id()):
    enable_new_ui()

variant = posthog.get_feature_flag('stretch-algorithm', get_distinct_id())
payload = posthog.get_feature_flag_payload('stretch-algorithm', get_distinct_id())
all_flags = posthog.get_all_flags(get_distinct_id())
```

### Super Properties

Properties automatically appended to every `capture()` call:

```python
posthog = Posthog(
    project_api_key='phc_...',
    host='https://us.i.posthog.com',
    super_properties={'app_version': '3.4.4', 'os': 'win32'},
)
```

### Flush and Shutdown

```python
posthog.flush()     # send all queued events immediately
posthog.shutdown()  # flush + stop background threads (call on app exit)
```

`shutdown()` is called in `main.py` on app exit.

---

## Initialization Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `project_api_key` | required | Project API key from PostHog |
| `host` | `None` | PostHog instance URL |
| `debug` | `False` | Log debug info for troubleshooting |
| `send` | `True` | Set `False` to disable sending (dev/test) |
| `disabled` | `False` | Disable the client entirely |
| `sync_mode` | `False` | Send events synchronously (blocks) |
| `flush_at` | `100` | Queue size that triggers a flush |
| `flush_interval` | `0.5` | Seconds between automatic flushes |
| `max_queue_size` | `10000` | Max events to queue before dropping |
| `max_retries` | `3` | Retry count for failed sends |
| `timeout` | `15` | HTTP request timeout in seconds |
| `gzip` | `False` | Compress payloads |
| `on_error` | `None` | Callback `fn(error, batch)` for send failures |
| `disable_geoip` | `True` | Skip GeoIP enrichment |
| `personal_api_key` | `None` | Required for feature flag local evaluation |
| `super_properties` | `None` | Dict of properties added to every event |
| `historical_migration` | `False` | For backfilling old events |
| `enable_exception_autocapture` | `False` | Auto-capture unhandled exceptions |
| `privacy_mode` | `False` | Strip PII from captured data |
| `before_send` | `None` | Callback to modify/filter events before sending |
