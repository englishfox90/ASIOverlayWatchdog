"""
Self-documenting API: one OpenAPI spec, two ways to read it.

``build_openapi_spec()`` is the single source of truth for the HTTP API shape.
It is served verbatim at ``/openapi.json`` (machine-readable) and rendered to a
dependency-free HTML reference at ``/docs`` (human-readable, fully offline — no
CDN, no JS, suitable for an isolated observatory PC).

The ``capture`` response schema is generated from ``api_status.CAPTURE_FIELDS``,
the same catalog the live payload is built from, so the docs cannot drift from
what ``/status`` actually returns.
"""
from __future__ import annotations

import html as _html

from .api_status import CAPTURE_FIELDS

try:
    from version import __version__ as VERSION
except Exception:  # pragma: no cover - version module always present in app
    VERSION = "unknown"


def _capture_schema_properties() -> dict:
    """OpenAPI ``properties`` for the capture block, from the shared catalog."""
    props = {}
    for name, typ, desc in CAPTURE_FIELDS:
        props[name] = {"type": typ, "description": desc, "nullable": True}
    return props


def _library_paths(library_path: str) -> dict:
    """OpenAPI ``paths`` entries for the image library endpoints."""
    return {
        library_path: {
            "get": {
                "summary": "List archived library images (paginated, newest first)",
                "description": (
                    "Returns a paginated manifest of the rolling image library — "
                    "downscaled frames retained for a bounded window. Filter with "
                    "'since'/'until' (epoch seconds or ISO 8601) and page with "
                    "'limit'/'offset'."
                ),
                "parameters": [
                    {"name": "since", "in": "query", "required": False,
                     "schema": {"type": "string"},
                     "description": "Lower bound on capture time (epoch seconds or ISO 8601)."},
                    {"name": "until", "in": "query", "required": False,
                     "schema": {"type": "string"},
                     "description": "Upper bound on capture time (epoch seconds or ISO 8601)."},
                    {"name": "limit", "in": "query", "required": False,
                     "schema": {"type": "integer", "default": 100, "maximum": 500}},
                    {"name": "offset", "in": "query", "required": False,
                     "schema": {"type": "integer", "default": 0}},
                ],
                "responses": {
                    "200": {
                        "description": "Library manifest",
                        "content": {"application/json": {
                            "schema": {"$ref": "#/components/schemas/LibraryManifest"}}},
                    }
                },
            }
        },
        library_path + "/image": {
            "get": {
                "summary": "Fetch one archived library image by id",
                "description": (
                    "Returns the JPEG for a single library entry. Supports "
                    "ETag/If-None-Match; archived frames are immutable so the "
                    "response is long-cacheable."
                ),
                "parameters": [
                    {"name": "id", "in": "query", "required": True,
                     "schema": {"type": "integer"},
                     "description": "Library image id (from the manifest)."},
                ],
                "responses": {
                    "200": {"description": "Image bytes", "content": {"image/jpeg": {}}},
                    "304": {"description": "Not Modified (ETag matched)"},
                    "400": {"description": "Missing or invalid 'id'"},
                    "404": {"description": "No image with that id"},
                },
            }
        },
    }


def _library_schemas() -> dict:
    """OpenAPI component schemas for the library manifest payload."""
    return {
        "LibraryImage": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "captured_at": {"type": "integer", "description": "Capture time, epoch seconds (PC local)."},
                "url": {"type": "string", "description": "Relative URL to fetch this image."},
                "width": {"type": "integer", "nullable": True},
                "height": {"type": "integer", "nullable": True},
                "bytes": {"type": "integer"},
                "session": {"type": "string", "nullable": True},
                "exposure": {"type": "string", "nullable": True},
                "gain": {"type": "string", "nullable": True},
                "temp": {"type": "string", "nullable": True},
                "camera": {"type": "string", "nullable": True},
                "weather": {"type": "string", "nullable": True},
            },
        },
        "LibraryManifest": {
            "type": "object",
            "properties": {
                "total": {"type": "integer", "description": "Total matching entries (ignores paging)."},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
                "images": {"type": "array", "items": {"$ref": "#/components/schemas/LibraryImage"}},
            },
        },
    }



# --- Outbound Hermes webhook (client callback, not a route this server serves) --

# One row per event type: (event name, event-block key, [(field, type, description), ...]).
# Mirrors services/notifications/hermes_backend.py `_event_block()` exactly —
# keep in lockstep with that function, not with the plan doc's prose.
WEBHOOK_EVENT_BLOCKS = [
    ("roof_changed", "roof", [
        ("open", "boolean", "New roof state."),
        ("confidence", "number", "Detector confidence, 0-1."),
    ]),
    ("error", "error", [
        ("text", "string", "Error message (same text as the envelope 'body')."),
    ]),
    ("lifecycle", "lifecycle", [
        ("phase", "string", "startup | shutdown | capture_started"),
        ("mode", "string", "Capture mode: watch | camera."),
        ("output_path", "string", "Configured output directory."),
    ]),
    ("periodic_image", "capture", [
        ("exposure", "string", "Exposure, as formatted for overlay tokens."),
        ("gain", "string", "Gain, as formatted for overlay tokens."),
        ("temp", "string", "Sensor temperature, as formatted for overlay tokens."),
        ("resolution", "string", "Frame resolution, e.g. '3856x2180'."),
    ]),
    ("timelapse_done", "timelapse", [
        ("frame_count", "integer", "Frames written to the completed timelapse."),
        ("elapsed_seconds", "integer", "Wall-clock duration of the timelapse run."),
        ("filename", "string", "Output video filename."),
    ]),
    ("calibration_done", "calibration", [
        ("rms_residual", "number", "All-sky calibration fit residual, pixels."),
        ("n_matches", "integer", "Star matches used in the fit."),
        ("calibrated_at", "string", "ISO-8601 timestamp of the calibration run."),
        ("a1", "number", "Lens model parameter: sky-circle scale."),
        ("cx", "number", "Lens model parameter: optical centre X."),
        ("cy", "number", "Lens model parameter: optical centre Y."),
    ]),
]

_WEBHOOK_ENVELOPE_FIELDS = [
    ("event", "string", "Event type — see the event table below."),
    ("level", "string", "info | warning | error | success"),
    ("title", "string", "Short human-readable title."),
    ("body", "string", "Human-readable message body."),
    ("source", "string", "App display name (identifies the sender to the agent)."),
    ("timestamp", "string", "ISO-8601 UTC, e.g. 2026-07-07T21:14:00Z."),
    ("image", "object", "Optional. { id, url } — present only when a Library image id "
                         "is available and the library API is enabled."),
]


def _webhook_schemas() -> dict:
    """OpenAPI component schemas documenting the outbound Hermes webhook payload.

    These are documentation-only — Hermes is a client callback PFR Sentinel POSTs
    to, not a route this server exposes, so they live under components/schemas
    rather than paths. See docs/dev/HERMES_NOTIFICATIONS_PLAN.md for the contract
    and services/notifications/hermes_backend.py for the code that builds them.
    """
    event_blocks = {}
    for event_name, block_key, fields in WEBHOOK_EVENT_BLOCKS:
        schema_name = "Webhook" + "".join(w.capitalize() for w in block_key.split("_"))
        event_blocks[schema_name] = {
            "type": "object",
            "description": f"Event-specific block for '{event_name}', keyed '{block_key}'.",
            "properties": {
                name: {"type": typ, "description": desc, "nullable": True}
                for name, typ, desc in fields
            },
        }

    schemas = {
        "WebhookNotification": {
            "type": "object",
            "description": (
                "Common envelope sent with every outbound webhook event. Event-specific "
                "fields (see WebhookEventBlocks) are merged in alongside these."
            ),
            "properties": {
                "event": {"type": "string", "description": _WEBHOOK_ENVELOPE_FIELDS[0][2]},
                "level": {"type": "string", "enum": ["info", "warning", "error", "success"],
                          "description": _WEBHOOK_ENVELOPE_FIELDS[1][2]},
                "title": {"type": "string", "description": _WEBHOOK_ENVELOPE_FIELDS[2][2]},
                "body": {"type": "string", "description": _WEBHOOK_ENVELOPE_FIELDS[3][2]},
                "source": {"type": "string", "description": _WEBHOOK_ENVELOPE_FIELDS[4][2]},
                "timestamp": {"type": "string", "format": "date-time",
                              "description": _WEBHOOK_ENVELOPE_FIELDS[5][2]},
                "image": {
                    "type": "object", "nullable": True,
                    "description": _WEBHOOK_ENVELOPE_FIELDS[6][2],
                    "properties": {
                        "id": {"type": "integer", "description": "Library image id."},
                        "url": {"type": "string", "description": "Resolvable /library/image URL."},
                    },
                },
            },
        },
    }
    schemas.update(event_blocks)
    return schemas


def build_openapi_spec(*, image_path: str = "/latest", status_path: str = "/status",
                       docs_path: str = "/docs", openapi_path: str = "/openapi.json",
                       library_path: str | None = None) -> dict:
    """Build the OpenAPI 3.0 spec describing the live server's actual routes.

    ``library_path`` is included only when the image library API is enabled;
    pass None to omit those routes so the docs never describe a 404.
    """
    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": "PFR Sentinel HTTP API",
            "version": VERSION,
            "description": (
                "Read-only HTTP API for PFR Sentinel. Serves the latest processed "
                "all-sky / observatory frame and a rich status report covering capture "
                "state, schedule, and health."
            ),
        },
        "paths": {
            image_path: {
                "get": {
                    "summary": "Latest processed image",
                    "description": (
                        "Returns the most recently processed frame (JPEG or PNG). "
                        "Supports ETag/If-None-Match conditional requests. Response "
                        "headers X-PFR-Image-Age-Seconds and X-PFR-Image-Stale signal "
                        "freshness without parsing /status."
                    ),
                    "responses": {
                        "200": {"description": "Image bytes",
                                "content": {"image/jpeg": {}, "image/png": {}}},
                        "304": {"description": "Not Modified (ETag matched)"},
                        "404": {"description": "No image available yet"},
                    },
                }
            },
            status_path: {
                "get": {
                    "summary": "Server, capture, and health status",
                    "description": (
                        "JSON status. Top-level keys (status, uptime_seconds, "
                        "images_served, image_age_seconds, image_stale, metadata) are "
                        "the HTTP-server view kept for backward compatibility. The "
                        "'capture' block reports mode/schedule/next-frame, and 'health' "
                        "summarises whether capture is actually working."
                    ),
                    "responses": {
                        "200": {
                            "description": "Status report",
                            "content": {"application/json": {
                                "schema": {"$ref": "#/components/schemas/Status"}}},
                        }
                    },
                }
            },
            openapi_path: {
                "get": {"summary": "This OpenAPI spec (JSON)",
                        "responses": {"200": {"description": "OpenAPI 3.0 document"}}}
            },
            docs_path: {
                "get": {"summary": "Human-readable API docs (HTML)",
                        "responses": {"200": {"description": "HTML reference page"}}}
            },
        },
        "components": {
            "schemas": {
                "Status": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string",
                                   "description": "HTTP server liveness ('running'). Not capture health."},
                        "uptime_seconds": {"type": "integer"},
                        "images_served": {"type": "integer"},
                        "latest_image": {"type": "string", "nullable": True},
                        "image_age_seconds": {"type": "integer", "nullable": True},
                        "image_stale": {"type": "boolean"},
                        "stale_threshold_seconds": {"type": "integer"},
                        "metadata": {"type": "object"},
                        "timestamp": {"type": "string", "format": "date-time"},
                        "capture": {"type": "object", "properties": _capture_schema_properties()},
                        "health": {
                            "type": "object",
                            "properties": {
                                "status": {"type": "string",
                                           "enum": ["ok", "idle", "degraded", "recovering", "error"]},
                                "reasons": {"type": "array", "items": {"type": "string"}},
                            },
                        },
                    },
                }
            }
        },
    }

    if library_path:
        spec["paths"].update(_library_paths(library_path))
        spec["components"]["schemas"].update(_library_schemas())

    # Documentation-only: Hermes is an outbound client callback, never a route
    # this server serves, so it's unconditional (not gated like the library).
    spec["components"]["schemas"].update(_webhook_schemas())

    return spec


# --- HTML rendering -------------------------------------------------------

_DOCS_CSS = """
:root { color-scheme: dark light; }
body { font-family: 'Segoe UI', system-ui, sans-serif; max-width: 920px; margin: 0 auto;
       padding: 2rem 1.5rem 4rem; line-height: 1.55; background: #0f1115; color: #e6e8eb; }
h1 { font-size: 1.6rem; margin-bottom: .25rem; }
h2 { font-size: 1.15rem; margin-top: 2rem; border-bottom: 1px solid #2a2f3a; padding-bottom: .35rem; }
.sub { color: #9aa3b2; margin-top: 0; }
.endpoint { background: #161a22; border: 1px solid #242a36; border-radius: 8px;
            padding: 1rem 1.1rem; margin: 1rem 0; }
.method { display: inline-block; font-weight: 700; font-size: .75rem; letter-spacing: .05em;
          background: #1f6feb; color: #fff; border-radius: 4px; padding: .15rem .5rem; margin-right: .6rem; }
code, .path { font-family: 'Cascadia Code', Consolas, monospace; }
.path { font-weight: 600; }
table { border-collapse: collapse; width: 100%; margin-top: .6rem; font-size: .9rem; }
th, td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #242a36; vertical-align: top; }
th { color: #9aa3b2; font-weight: 600; }
td.type { color: #79c0ff; white-space: nowrap; font-family: 'Cascadia Code', Consolas, monospace; }
pre { background: #0b0d12; border: 1px solid #242a36; border-radius: 8px; padding: 1rem;
      overflow-x: auto; font-size: .85rem; }
a { color: #79c0ff; }
.tag { font-size: .7rem; color: #9aa3b2; }
"""

_EXAMPLE_STATUS = """{
  "status": "running",
  "uptime_seconds": 3725,
  "images_served": 442,
  "image_age_seconds": 7,
  "image_stale": false,
  "metadata": { "EXPOSURE": "2.0s", "GAIN": "300" },
  "capture": {
    "mode": "camera",
    "enabled": true,
    "running": true,
    "state": "waiting",
    "interval_seconds": 5.0,
    "effective_interval_seconds": 5.0,
    "schedule": { "mode": "gated", "start_time": "17:00", "end_time": "09:00", "in_window": true },
    "last_capture_age_seconds": 7,
    "next_capture_in_seconds": 3,
    "recovery": { "in_progress": false, "attempts": 0, "unrecoverable": false },
    "last_error": null
  },
  "health": { "status": "ok", "reasons": [] }
}"""

_EXAMPLE_WEBHOOK = """{
  "event": "roof_changed",
  "level": "warning",
  "title": "Roof Closed",
  "body": "Roof is now Closed (confidence 94%)",
  "source": "PFR Sentinel",
  "timestamp": "2026-07-07T21:14:00Z",
  "image": { "id": 1234, "url": "http://127.0.0.1:8080/library/image?id=1234" },
  "roof": { "open": false, "confidence": 0.94 }
}"""


def _esc(text: str) -> str:
    return _html.escape(str(text))


def _html_table(headers: list, rows: list, label: str = None) -> str:
    """Wrap pre-built <tr> ``rows`` in a table with the given column ``headers``.

    An optional ``label`` renders a small caption tag above the table.
    """
    tag = f"<div class='tag'>{_esc(label)}</div>" if label else ""
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    return f"{tag}<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _render_params(op: dict) -> str:
    """Render an operation's query/path parameters as a small table, if any."""
    params = op.get("parameters") or []
    if not params:
        return ""
    rows = []
    for p in params:
        schema = p.get("schema", {})
        default = schema.get("default")
        extra = f" (default {_esc(default)})" if default is not None else ""
        req = "yes" if p.get("required") else "no"
        rows.append(
            f"<tr><td class='path'>{_esc(p.get('name', ''))}</td>"
            f"<td class='type'>{_esc(schema.get('type', ''))}{extra}</td>"
            f"<td>{_esc(p.get('in', ''))}</td>"
            f"<td>{_esc(req)}</td>"
            f"<td>{_esc(p.get('description', ''))}</td></tr>"
        )
    return _html_table(["Name", "Type", "In", "Required", "Description"], rows,
                       label="Query parameters")


def _render_responses(op: dict) -> str:
    """Render an operation's response status codes + descriptions, if any."""
    responses = op.get("responses") or {}
    if not responses:
        return ""
    rows = [
        f"<tr><td class='path'>{_esc(code)}</td>"
        f"<td>{_esc(meta.get('description', ''))}</td></tr>"
        for code, meta in responses.items()
    ]
    return _html_table(["Status", "Description"], rows, label="Responses")


def _render_webhook_section(spec: dict) -> str:
    """Render the outbound Hermes webhook reference from WEBHOOK_EVENT_BLOCKS +
    the WebhookNotification schema, so this stays in sync with what
    hermes_backend._build_payload() actually sends rather than drifting prose.
    """
    envelope_rows = [
        f"<tr><td class='path'>{_esc(name)}</td>"
        f"<td class='type'>{_esc(typ)}</td>"
        f"<td>{_esc(desc)}</td></tr>"
        for name, typ, desc in _WEBHOOK_ENVELOPE_FIELDS
    ]
    envelope_table = _html_table(["Field", "Type", "Description"], envelope_rows,
                                 label="Common envelope (every event)")

    event_rows = []
    for event_name, block_key, fields in WEBHOOK_EVENT_BLOCKS:
        field_list = ", ".join(f"{name} ({typ})" for name, typ, _ in fields)
        event_rows.append(
            f"<tr><td class='path'>{_esc(event_name)}</td>"
            f"<td class='type'>{_esc(block_key)}</td>"
            f"<td>{_esc(field_list)}</td></tr>"
        )
    event_table = _html_table(["event", "Block key", "Fields"], event_rows,
                              label="Event types → event-specific block")

    return f"""
<h2>Outbound Webhook Notifications</h2>
<p class="sub">PFR Sentinel can <strong>POST</strong> HMAC-signed JSON to a configured
webhook (e.g. a Hermes agent) for six event types: roof_changed, error, lifecycle,
periodic_image, timelapse_done, calibration_done. This is a client callback the app
makes outbound &mdash; it is not a route this server serves, so it will not appear
under <code>/openapi.json</code> "paths"; the payload shape is documented via the
<code>WebhookNotification</code> and per-event component schemas instead.</p>

<div class="endpoint">
<span class="method">POST</span>
<span class="path">&lt;configured webhook URL&gt;</span>
<div><strong>Generic V2 HMAC signing</strong></div>
<p class="sub"><code>Content-Type: application/json</code>. Signed bytes are the
exact POST body bytes (never re-serialized). Header
<code>X-Webhook-Signature-V2</code> is the hex HMAC-SHA256 digest of the ASCII
string <code>"&lt;timestamp&gt;.&lt;body&gt;"</code>; header
<code>X-Webhook-Timestamp</code> is the Unix seconds used in that string. The
receiving server should reject requests where the timestamp is more than &plusmn;300s
from its own clock.</p>
{envelope_table}
{event_table}
</div>

<h3>Example <code>roof_changed</code> payload</h3>
<pre>{_esc(_EXAMPLE_WEBHOOK)}</pre>
"""


def render_docs_html(spec: dict) -> str:
    """Render the OpenAPI spec to a self-contained HTML reference page."""
    info = spec.get("info", {})
    title = _esc(info.get("title", "API"))
    version = _esc(info.get("version", ""))
    description = _esc(info.get("description", ""))

    endpoints_html = []
    for path, methods in spec.get("paths", {}).items():
        for method, op in methods.items():
            summary = _esc(op.get("summary", ""))
            desc = _esc(op.get("description", ""))
            desc_html = f'<p class="sub">{desc}</p>' if desc else ""
            endpoints_html.append(
                f'<div class="endpoint">'
                f'<span class="method">{_esc(method.upper())}</span>'
                f'<span class="path">{_esc(path)}</span>'
                f'<div><strong>{summary}</strong></div>{desc_html}'
                f'{_render_params(op)}{_render_responses(op)}</div>'
            )

    # Bespoke table for the nested /status `capture` schema fields — this
    # introspects a response schema's sub-object, not endpoint params/responses,
    # so it stays separate from the generic _render_* helpers.
    capture_props = (
        spec.get("components", {}).get("schemas", {})
        .get("Status", {}).get("properties", {})
        .get("capture", {}).get("properties", {})
    )
    rows = [
        f"<tr><td class='path'>{_esc(name)}</td>"
        f"<td class='type'>{_esc(meta.get('type', ''))}</td>"
        f"<td>{_esc(meta.get('description', ''))}</td></tr>"
        for name, meta in capture_props.items()
    ]
    capture_table = _html_table(["Field", "Type", "Description"], rows)

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>{_DOCS_CSS}</style></head>
<body>
<h1>{title} <span class="tag">v{version}</span></h1>
<p class="sub">{description}</p>
<p class="tag">Machine-readable spec: <a href="/openapi.json">/openapi.json</a></p>

<h2>Endpoints</h2>
{''.join(endpoints_html)}

<h2><code>/status</code> &rarr; <code>capture</code> fields</h2>
{capture_table}

<h2><code>health.status</code> values</h2>
<table><thead><tr><th>Value</th><th>Meaning</th></tr></thead><tbody>
<tr><td class="path">ok</td><td>Capture is running and producing fresh frames.</td></tr>
<tr><td class="path">idle</td><td>Capture is off or intentionally paused (e.g. outside the scheduled window).</td></tr>
<tr><td class="path">degraded</td><td>Capture is running but frames have stalled past the expected cadence.</td></tr>
<tr><td class="path">recovering</td><td>Auto-recovery is in progress after a camera fault.</td></tr>
<tr><td class="path">error</td><td>Capture has failed; may need manual intervention.</td></tr>
</tbody></table>

<h2>Example <code>/status</code> response</h2>
<pre>{_esc(_EXAMPLE_STATUS)}</pre>

{_render_webhook_section(spec)}
</body></html>"""
