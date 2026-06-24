# Image Library — Feature Design / Project Plan

> **Status (2026-06-24): Proposed — not yet implemented.** This document scopes a
> new "Image Library" feature: a rolling, on-disk store of downscaled (Discord-size)
> capture frames, retained for ~7 days, browsable in-app via a new Library panel and
> retrievable over the existing web/HTTP API. Read this before starting implementation.

---

## The Idea

Today PFR Sentinel can save **full-resolution** output images to a folder, but there
is no lightweight, queryable history inside the app. The live monitoring panel only
ever shows the *latest* frame, and the web server only exposes `/latest`. If you want
to look back over the last night's sky you have to dig through the output directory by
hand at full res.

This feature adds a **rolling image library**: every processed frame is also saved as a
small Discord-post-sized JPEG into a dedicated, indexed store. The store keeps roughly
the last 7 days (configurable), prunes itself automatically, and is exposed two ways:

1. **In-app** — a new "Library" navigation panel with a scrollable thumbnail gallery,
   date filtering, and click-to-enlarge.
2. **Web/HTTP API** — new endpoints alongside `/latest` and `/status` that list the
   library and fetch individual images, so external dashboards can build a timeline.

### Goals

- Cheap to store: one downscaled JPEG per frame (~50–100 KB), not full-res.
- Self-managing: automatic time- **and** size-bounded retention, no manual cleanup.
- Queryable: filter by time range, paginate, read per-frame metadata.
- Available both in the UI and over the API from the same backing store.

### Non-goals (this phase)

- Multiple thumbnail tiers (a single Discord-size tier serves both gallery and API).
- Full-resolution archival (that remains the job of the existing file output + cleanup).
- Editing, tagging, favouriting, or exporting timelapses from the library.
- Cloud sync / off-box upload.

---

## Decisions (locked)

These were settled during scoping and drive the design below:

| Decision | Choice | Rationale |
|---|---|---|
| **Image tier** | **Discord size only** — single downscaled JPEG per frame (max long-edge ~750 px, JPEG q85) | Reuse the proven Discord resize path; one image serves both gallery and API. |
| **Retention** | **Time + size cap** — keep N days (default 7) *and* a max library size (default 2 GB), whichever triggers first | Time gives the "last week" UX; size cap is the disk safety-net for high frame-rate nights. |
| **Access** | **In-app Library panel + Web/HTTP API** | Both surfaces read the same SQLite-backed store. |
| **Index/storage** | **SQLite index + JPEG files on disk** | Fast time-range queries, pagination, and metadata filtering without rewriting a manifest on every frame. `sqlite3` is stdlib. |

---

## Grounding: how the current pipeline works

(Verified in code, June 2026. Cited so the implementer knows exactly where to hook in.)

### Output dispatch — the hook point
The final processed PIL image is produced in `ui/controllers/image_processor.py`,
saved to disk (`output_img.save(...)` ~L399), then emitted via
`processing_complete`. `ui/main_window/output.py` `_on_image_processed()` (~L186)
routes it to the output sinks through **`_push_to_output_servers()` (~L417–481)**,
which already:

- re-encodes the image to bytes and calls `web_server.update_image(...)`, and
- periodically calls the Discord sender.

**The library "save" step hooks in here**, right alongside the web/Discord dispatch,
using the already-processed `output_image` PIL object. No new capture path is needed —
both watch mode and camera mode converge on this function.

### Discord resize — the logic to reuse
`services/discord_alerts.py` (L14–18, L188–204) already downscales for posting:

```python
DISCORD_IMAGE_MAX_HEIGHT = 750
# resize preserving aspect ratio with Image.LANCZOS, then
img_resized.save(buf, format="JPEG", quality=85)   # ~50–100 KB typical
```

This resize logic should be **extracted into a shared helper** so the library and
Discord use one definition (see "Shared resize util" below) rather than copy-pasting
the LANCZOS + JPEG dance a third time (the web server has its own variant too).

### Web server — how to add endpoints
`services/web_output.py` is a stdlib `http.server.HTTPServer` +
`BaseHTTPRequestHandler`. Endpoints are dispatched in `do_GET()` (~L87+):
`/latest`, `/status`, `/docs`, `/openapi.json`. The handler stores the latest image
in **class-level variables** updated via `ImageHTTPHandler.update_image()` (cross-thread
safe). New library endpoints are added by extending `do_GET()` and registering them in
the OpenAPI spec in `services/api_docs.py`.

> ⚠️ **Threading note:** the web server runs on a background thread. The library's
> SQLite connection used by the web endpoints must be opened per-handler-thread (or
> with `check_same_thread=False` + a lock). Do **not** share one connection across the
> processor thread and the HTTP thread. See "Concurrency" below.

### Config & cleanup — patterns to follow
- `services/config.py` `DEFAULT_CONFIG` is merged against on load, so new nested keys
  land safely on existing user configs. Output keys live under `output.*` and top-level
  (`output_directory`, `output_format`, `jpg_quality`). Add a new **`library.*`** block.
- `app_config.get_app_data_dir()` → `%LOCALAPPDATA%\PFRSentinel`. The library lives in a
  sibling of the existing `Images` output subfolder.
- `services/cleanup.py` is **size-based only** today (delete oldest files/sessions to get
  under a GB cap). It has no time-based logic. The library brings its **own** retention
  (time + size) rather than overloading `cleanup.py`, because the library's pruning must
  also delete the matching SQLite rows — it is not a pure filesystem sweep.

### UI — how a panel is registered
Panels are layout-only (`ui/panels/`); business logic lives in controllers
(`ui/controllers/`); they talk via Qt signals/slots. Registration touches:
1. `ui/components/nav_rail.py` (~L193) — add a nav button + section key.
2. `ui/main_window/window.py` (~L220) — instantiate the panel, `addWidget` to
   `inspector_stack` (next free index, currently 9).
3. `_on_nav_changed()` (~L441) — add the section→index mapping.

There is **no existing gallery/thumbnail viewer** — this would be the first persistent
gallery in the app.

---

## Proposed architecture

### New module layout

Following the project's module-discipline rule (new responsibility → new file; name it
after what it *does*; keep files under the ~600-line cap), the core lives in a small
`services/library/` package:

```
services/
├── image_resize.py            # NEW — shared "downscale to max edge + JPEG" helper
│                              #       (reused by Discord, library, and ideally web)
└── library/
    ├── __init__.py            # NEW — public facade: ImageLibrary (add/query/prune)
    ├── store.py               # NEW — file storage: dated folder layout, write/read JPEG
    ├── index.py               # NEW — SQLite schema + CRUD + time-range/paginated queries
    └── retention.py           # NEW — time + size pruning policy (DB rows + files together)

ui/
├── panels/
│   └── library_panel.py       # NEW — layout only: gallery grid, date filter, viewer dialog
└── controllers/
    └── library_controller.py  # NEW — query the library, lazy-load thumbnails, signals
```

Touched (not new):
- `services/discord_alerts.py` — call the shared resize helper instead of its inline copy.
- `ui/main_window/output.py` — add the library-save call in `_push_to_output_servers()`.
- `services/web_output.py` + `services/api_docs.py` — new endpoints + OpenAPI entries.
- `services/config.py` — new `library.*` config block.
- `ui/components/nav_rail.py`, `ui/main_window/window.py` — register the Library panel.

### Storage layout on disk

```
%LOCALAPPDATA%\PFRSentinel\Library\
├── library.db                 # SQLite index
└── 2026-06-24\                # one folder per local capture date (keeps dirs small)
    ├── 20260624_223015_a1b2.jpg
    ├── 20260624_223115_c3d4.jpg
    └── ...
```

- Dated subfolders keep any single directory from growing unbounded and make manual
  inspection / whole-day deletion trivial.
- Filenames are timestamp + short random/hash suffix to avoid collisions; the canonical
  record is the DB row, not the filename.

### SQLite schema (draft)

```sql
CREATE TABLE images (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at  INTEGER NOT NULL,   -- unix epoch (UTC), the frame's capture time
    path         TEXT    NOT NULL,   -- relative to Library root
    width        INTEGER,
    height       INTEGER,
    bytes        INTEGER NOT NULL,   -- file size, for the size-cap accounting
    -- denormalised metadata for filtering / display without opening the JPEG:
    session      TEXT,
    exposure     TEXT,
    gain         TEXT,
    temp         TEXT,
    camera       TEXT,
    weather      TEXT,               -- short summary string if available
    created_at   INTEGER NOT NULL    -- when the row was inserted
);
CREATE INDEX idx_images_captured_at ON images(captured_at);
```

Pulling metadata from the same `metadata` dict the overlay/Discord paths already
receive means no new extraction work. `bytes` is summed for the size-cap policy so
retention never has to stat the whole tree.

### Data flow

```
processor produces output_img + metadata
        │
        ▼
_push_to_output_servers()  (ui/main_window/output.py)
        ├── (existing) web_server.update_image(...)
        ├── (existing) Discord periodic post
        └── (NEW, if library.enabled)
              ImageLibrary.add(output_img, metadata)
                   ├── image_resize.to_max_edge(img, 750, q=85) → jpeg bytes
                   ├── store.write(date_folder, filename, bytes)
                   ├── index.insert(row)
                   └── retention.maybe_prune()   # cheap check, throttled
```

`maybe_prune()` runs opportunistically (e.g. at most once every N minutes, tracked by a
timestamp) so we are not scanning on every single frame. Pruning deletes oldest rows +
their files until **both** constraints hold: `captured_at >= now − retention_days` and
`SUM(bytes) <= max_size_gb`.

### Config block (draft)

```python
"library": {
    "enabled": True,
    "retention_days": 7,
    "max_size_gb": 2.0,
    "max_dimension": 750,     # long-edge px; matches Discord default
    "jpeg_quality": 85,
    "api_enabled": True,      # expose the /library endpoints
    "prune_interval_minutes": 15,
}
```

`library.max_dimension` / `jpeg_quality` default to the Discord values so the single
stored tier *is* "Discord size" out of the box, but remain tunable.

---

## Web/HTTP API

New endpoints (gated behind `library.enabled && library.api_enabled`):

| Method | Path | Returns |
|---|---|---|
| `GET` | `/library` | JSON manifest: paginated list of entries with metadata. Query params: `since`, `until` (epoch or ISO), `limit` (default 100, capped), `offset`. Includes a `total` count. |
| `GET` | `/library/image?id=<id>` | The JPEG bytes for one entry (with ETag, same caching pattern as `/latest`). |

Example `/library` response:

```json
{
  "total": 4213,
  "limit": 100,
  "offset": 0,
  "images": [
    {
      "id": 4213,
      "captured_at": 1750800615,
      "url": "/library/image?id=4213",
      "width": 1000, "height": 750, "bytes": 78213,
      "exposure": "15s", "gain": "120", "temp": "-10C",
      "camera": "ASI2600MC", "weather": "Clear, 12C"
    }
  ]
}
```

- Reuse the existing ETag/`If-None-Match` machinery from `/latest` for `/library/image`.
- Register both in `services/api_docs.py` so `/docs` and `/openapi.json` stay accurate.

---

## In-app Library panel

- **Nav:** new "Library" section in `nav_rail.py` (e.g. a gallery/photo icon),
  registered in `window.py` and `_on_nav_changed()` at the next stack index.
- **`ui/panels/library_panel.py`** (layout only): a scrollable thumbnail **grid**, a
  **date filter** (day picker / range), a small detail strip, and a **click-to-enlarge**
  viewer dialog showing the Discord-size image plus its metadata.
- **`ui/controllers/library_controller.py`** (logic + threading): queries the index,
  loads JPEGs lazily off the UI thread (e.g. a `QThreadPool`/worker that emits ready
  pixmaps), and exposes signals the panel binds to. All widget updates marshalled back
  to the UI thread per the project's threading rule.
- Because the stored image is already small, the grid can display the stored JPEG
  directly (optionally letting Qt scale it for the grid cell) — no separate thumbnail
  tier is generated, consistent with the "Discord size only" decision.

---

## Concurrency & safety

- **SQLite across threads:** the processor thread writes; the web thread reads. Use a
  dedicated connection per thread (open in the handler) or a single
  `check_same_thread=False` connection guarded by a `threading.Lock`. Enable WAL mode
  (`PRAGMA journal_mode=WAL`) for concurrent read/write without blocking the capture path.
- **Never block the capture pipeline:** `add()` does a small resize + file write + one
  insert. Pruning is throttled and can run on the same call but must be bounded (delete
  in batches). If profiling shows it stalls capture on busy nights, move `add()` onto a
  small background queue (mirrors the logger's queue pattern).
- **Crash/partial-write resilience:** write the JPEG first, then insert the row, so a
  crash leaves at most an orphan file (cleaned on next prune sweep), never a row pointing
  at a missing file. A lightweight startup reconciliation can drop rows whose files are
  gone.
- **Disk safety:** the size cap is the backstop; the retention sweep must also handle the
  case where the user shrinks `max_size_gb` below current usage (prune down on next run).

---

## Testing

New `tests/test_image_library.py` (pytest, no hardware/network markers needed):

- `image_resize`: aspect ratio preserved, long-edge respected, output is valid JPEG,
  size in the expected ballpark.
- `index`: insert + time-range query + pagination correctness; `total` count.
- `retention`: time-based prune drops only old rows/files; size-based prune drops oldest
  first until under cap; both constraints enforced together; size shrink prunes down.
- `store`: dated-folder pathing; orphan-file reconciliation.
- `add()` end-to-end with a temp dir + in-memory/temp SQLite, asserting file + row land.

Web endpoint tests extend `tests/test_webserver.py` (`requires_network`): `/library`
returns paginated JSON; `/library/image` returns bytes with correct content-type + ETag;
endpoints 404/disabled cleanly when `api_enabled` is false.

Watch file sizes against the ~600-line cap; the package split exists to stay under it.

---

## Phasing

1. **Phase 1 — core store.** `image_resize.py`, `services/library/` (store + index +
   retention), config block, hook in `_push_to_output_servers()`. Unit tests. No UI/API
   yet — verify the DB + files populate and prune correctly.
2. **Phase 2 — web API.** `/library` + `/library/image`, OpenAPI registration, tests.
3. **Phase 3 — in-app panel.** Library panel + controller, nav registration, lazy grid,
   viewer dialog.
4. **Phase 4 (optional, later).** Refactor Discord (and possibly the web `/latest`
   downscaler) to call the shared `image_resize` helper, removing the duplicate resize
   implementations.

Phases 1–3 are independently shippable; the API and UI both read the same store, so
either can land first after Phase 1.

---

## Open questions / risks

- **Frame rate vs. retention:** at fast cadence, 7 days could be tens of thousands of
  frames. The size cap protects disk, but the gallery and `/library` must paginate (they
  do). Consider an optional "store at most 1 frame per N seconds into the library"
  throttle if nights get dense — flag for a later phase, not v1.
- **Time zone:** store `captured_at` in UTC; the date-folder and UI date filter should
  use the observatory's local day. Pick one convention and document it.
- **Interaction with full-res cleanup:** the library is fully independent of
  `output_directory` and `services/cleanup.py`; deleting full-res output never touches the
  library and vice-versa. Worth stating in user docs to avoid confusion.
