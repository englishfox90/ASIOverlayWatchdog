"""Default configuration values.

`DEFAULT_CONFIG` is the template every loaded config.json is merged against
(see services/config.py `Config.load`), so a key added here lands on existing
installs automatically. `DEFAULT_CAMERA_PROFILE` seeds camera_profiles entries.
Pure data — behaviour lives in services/config.py.
"""
import os
from .utils_paths import resource_path, get_app_data_dir
from .app_config import DEFAULT_OUTPUT_SUBFOLDER

DEFAULT_CAMERA_PROFILE = {
    "exposure_ms": 100.0,
    "gain": 100,
    "max_exposure_ms": 30000.0,
    "target_brightness": 100,
    "wb_r": 75,
    "wb_b": 99,
    "offset": 20,
    "flip": 0,
    "bayer_pattern": "BGGR",
}

DEFAULT_CONFIG = {
    # UI appearance
    "ui_accent": "iris",   # accent theme: iris | nebula | aurora | solar | nova | forest
    "ui_log_level": "Info+",

    # Window settings
    "window_geometry": "1280x1700",
    "splitter_sizes": [400, 500],  # Live panel and inspector panel widths
    "inspector_visible": True,  # Whether inspector panel is visible
    
    # Mode selection
    "capture_mode": "camera",  # "watch" or "camera"
    
    # Directory watch settings
    "watch_directory": "",
    "watch_recursive": True,
    
    # Output settings
    "output_directory": os.path.join(get_app_data_dir(), DEFAULT_OUTPUT_SUBFOLDER),
    "filename_pattern": "latestImage",
    "output_format": "jpg",
    "jpg_quality": 100,
    "resize_percent": 74,
    "timestamp_corner": False,
    
    # Output mode settings
    "output": {
        "mode": "file",  # "file" | "webserver"

        # Webserver settings
        "webserver_enabled": False,
        "webserver_host": "127.0.0.1",
        "webserver_port": 8080,
        "webserver_path": "/latest",
        "webserver_status_path": "/status",
        "webserver_docs_path": "/docs",
        "webserver_library_path": "/library",

        # Capture-control API (POST /capture/start | /capture/stop). Off by
        # default: these are the only mutating routes on the server, so they
        # are opt-in and fail closed without a token. See services/api_auth.py.
        "webserver_control_enabled": False,
        "webserver_control_path": "/capture",
        # Extra Host values for control routes; see services/api_auth.py.
        "webserver_control_allowed_hosts": [],
        "api_token": ""
    },
    
    # ZWO Camera settings
    "zwo_sdk_path": resource_path("ASICamera2.dll"),
    "zwo_camera_index": 0,
    "zwo_camera_name": "",  # Last selected camera name
    "zwo_selected_camera": 0,  # Last selected camera index (transient — shifts on hot-plug)
    # Stable hardware serial (ASIGetSerialNumber, 16-hex). The authoritative
    # identity: index and model name are non-unique/unstable. Learned on the
    # first clean connect for configs that predate this key.
    "zwo_selected_camera_serial": "",
    
    # Per-camera profiles (NEW: stores settings per camera to prevent cross-contamination)
    # NOTE: auto_exposure is NOT stored here - it's a global algorithm setting, not camera-specific
    # NOTE: auto_wb/WB mode is NOT stored here - stored in global white_balance config
    "camera_profiles": {
        # "ZWO ASI676MC": {  # Example camera profile
        #     "exposure_ms": 100.0,
        #     "gain": 100,
        #     "max_exposure_ms": 30000.0,
        #     "target_brightness": 100,
        #     "wb_r": 75,  # Manual WB red channel (when mode=manual)
        #     "wb_b": 99,  # Manual WB blue channel (when mode=manual)
        #     "offset": 20,
        #     "flip": 0,
        #     "bayer_pattern": "BGGR"
        # }
    },
    
    # Global camera settings (NOT per-camera — apply to the whole capture loop)
    "zwo_interval": 300.0,        # seconds between captures
    "zwo_auto_exposure": True,    # auto-exposure algorithm enabled (global toggle)
    
    # Scheduled capture settings
    # mode:
    #   "always"   — capture 24/7 using zwo_interval (default)
    #   "gated"    — only capture inside the time window; disconnect camera outside
    #   "variable" — always capture, but use scheduled_window_interval inside the
    #                window and zwo_interval outside (e.g. fast at night, slow by day)
    "scheduled_capture_mode": "variable",
    "scheduled_capture_enabled": True,      # legacy flag — kept in sync with mode for back-compat
    "scheduled_start_time": "16:00",        # 4:00 PM — window start (24hr)
    "scheduled_end_time": "09:00",          # 9:00 AM — window end (next day for overnight)
    "scheduled_window_interval": 30.0,      # seconds between captures when inside the window (variable mode only)
    
    # White Balance configuration
    "white_balance": {
        "mode": "gray_world",  # "asi_auto" | "manual" | "gray_world"
        "manual_red_gain": 1.0,
        "manual_blue_gain": 1.0,
        "gray_world_low_pct": 5,
        "gray_world_high_pct": 100
    },
    # Analytics (PostHog)
    "analytics_enabled": True,  # Send anonymous usage data (opt-out via Settings > System)

    # Startup behaviour (Windows scheduled task — see services/autostart.py)
    "run_on_startup": False,      # UI reflection; the scheduled task is the source of truth
    "autostart_capture": True,    # Include --auto-start in the registered startup command

    "auto_brightness": False,  # Automatically adjust brightness
    "brightness_factor": 1.0,  # Brightness multiplier (0.5 to 2.0, 1.0 = neutral)
    "saturation_factor": 0.98,  # Saturation multiplier (0.0 to 2.0, 1.0 = neutral)
    # Auto Stretch settings (MTF - Midtone Transfer Function)
    "auto_stretch": {
        "enabled": True,
        "target_median": 0.15,  # Target median value (0.0-1.0, default 0.25 = quarter brightness)
        "linked_stretch": False,  # Apply same stretch to all RGB channels (False = per-channel MAD clipping)
        "preserve_blacks": True,  # Keep true blacks dark instead of lifting to grey
        "black_point": 0.0,  # Manual black point (0.0-0.1) - pixels below this stay black
        "shadow_aggressiveness": 1.8,  # MAD multiplier for shadow clipping (1.5=aggressive, 2.8=standard, 4.0=gentle)
        "saturation_boost": 1.5,  # Post-stretch saturation boost (1.0=none, 1.5=moderate, 2.0=strong)
        "normalize_channels": True,  # Equalize R/G/B medians before stretch (fixes color cast in dark scenes)
        "dark_scene_threshold": 0.12,  # Median below this triggers dark scene mode (0.0-0.2)
        "scnr_amount": 0.46  # Subtractive chromatic noise reduction strength (0.0=off, 1.0=max green removal)
    },

    # Star sharpening — cosmetic unsharp mask applied before overlay rendering
    "sharpening": {
        "enabled": True,   # Disabled by default; user opts in
        "radius": 1.5,      # Gaussian blur radius in pixels (keep <= 2 for stars)
        "amount": 80,       # Strength on Pillow 0-500 scale (80 = subtle)
        "threshold": 3,     # Min pixel diff to sharpen; suppresses noise in dark sky
    },

    # ML Models (Beta) - Observatory condition classification
    # These models analyze images to detect roof state and sky conditions
    "ml_models": {
        "enabled": False,  # Enable ML-based image analysis (Beta)
        "roof_classifier": True,  # Predict roof open/closed state
        "sky_classifier": True,   # Predict sky condition (Clear/Cloudy/etc) when roof is open
        "show_in_preview": True,  # Display predictions in live monitoring metadata
        "roof_gates_sky_features": True,  # Roof "Closed" suppresses star detection/all-sky overlay (turn off for roofless rigs)
        # ASCOM Safety Monitor file output (for NINA integration)
        "ascom_safety_file": {
            "enabled": False,  # Write roof status to file for NINA GenericFile safety monitor
            "file_path": os.path.join(get_app_data_dir(), 'RoofStatusFile.txt'),  # Default to AppData
            "preamble": "Roof Status:",  # Text before the status value
            "open_trigger": "OPEN",  # Value when roof is open (Safe in NINA)
            "closed_trigger": "CLOSED",  # Value when roof is closed (Unsafe in NINA)
            "include_confidence": True,  # Include confidence % in file
            "include_sky_condition": True,  # Include sky condition on separate line
            "min_confidence": 0.7,  # Only write if confidence >= this threshold
        },
    },
    
    # Developer Mode settings - for troubleshooting raw image data
    "dev_mode": {
        "enabled": False,  # Save raw images before any processing
        "raw_folder": "raw_debug",  # Subfolder name for raw images (relative to output_directory)
        "save_histogram_stats": True,  # Log detailed per-channel statistics
        "use_raw16": False,  # Use RAW16 mode for full bit depth (requires camera support)
        "ml_predictions": {
            "enabled": True,  # Run ML model predictions on each capture (for dev JSON)
            "roof_classifier": True,  # Predict roof open/closed state
            "sky_classifier": True,   # Predict sky condition (only when roof open)
        }
    },
    
    # Overlay settings
    "overlays": [
        {
            "text": "Camera: {CAMERA}\nExposure: {EXPOSURE}\nGain: {GAIN}\nTemp: {TEMP}",
            "anchor": "Bottom-Left",
            "offset_x": 10,
            "offset_y": 10,
            "font_size": 24,
            "font_style": "normal",
            "color": "white"
        }
    ],
    
    # Cleanup settings
    "cleanup_enabled": False,
    "cleanup_max_size_gb": 10.0,
    "cleanup_strategy": "oldest",

    # Image library — rolling store of downscaled (Discord-size) frames,
    # retained by age AND size, browsable in-app and over the web API.
    "library": {
        "enabled": True,
        "retention_days": 7,
        "max_size_gb": 2.0,
        "max_dimension": 750,   # longest-edge px; matches the Discord image size
        "jpeg_quality": 85,
        "api_enabled": True,    # expose the /library web endpoints
        "prune_interval_minutes": 15,
    },

    # Weather settings (OpenWeatherMap)
    "weather": {
        "enabled": False,  # Set to True when API key and location configured
        "api_key": "",
        "location": "",  # City name fallback, e.g., "London" or "London,GB"
        "latitude": "",  # Preferred: direct coordinates (e.g., "51.5074")
        "longitude": "",  # Preferred: direct coordinates (e.g., "-0.1278")
        "units": "metric",  # "metric", "imperial", or "standard"
        "cache_duration": 600,  # Cache weather data for 10 minutes
        "elevation": "",       # Observer elevation in metres (for refraction)
    },
    
    # Discord alerts
    "discord": {
        "enabled": False,
        "webhook_url": "",
        "embed_color_hex": "#0EA5E9",
        "post_errors": False,
        "post_startup_shutdown": False,
        "periodic_enabled": False,
        "periodic_interval_minutes": 60,
        "include_latest_image": True,
        "username_override": "",
        "avatar_url": "",
        "post_timelapse": False,      # Post timelapse video when session completes
        "post_calibration": False,    # Post notification when all-sky calibration completes
        "post_roof_changes": False,   # Post notification when ML confirms a roof status change
    },

    # Hermes webhook — HMAC-signed JSON notifications for an LLM agent to compose/deliver
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
        # Optional per-event URL routing: when route_by_event is True, each event
        # type posts to its own URL below (blank falls back to the base 'url'),
        # so Hermes can run focused per-event subscriptions. Same secret for all.
        "route_by_event": False,
        "event_urls": {
            "error": "",
            "roof_changed": "",
            "periodic_image": "",
            "lifecycle": "",
            "timelapse_done": "",
            "calibration_done": "",
        },
    },

    # YouTube timelapse uploads
    "youtube": {
        "enabled": False,
        "client_secrets_path": "",
        "privacy_status": "private",  # "private" | "unlisted" | "public"
        "title_template": "PFR Sentinel Timelapse {date}",
        "description_template": "All-sky timelapse recorded by PFR Sentinel.",
        "tags": "astronomy, allsky, timelapse",
        "category_id": "22",
    },
    
    # All-sky camera settings (for ML training visual reference)
    "allsky": {
        "enabled": True,
        "url": "https://zyssufjepmbhqznfuwcw.supabase.co/storage/v1/object/public/status-assets-public/building-0009/allsky/images/image.jpg",
        "timeout_seconds": 10
    },
    
    # ML Data Contribution - helps improve models for all users
    # Opt-in anonymous data sharing with downscaled images (256x256)
    "ml_contribution": {
        "enabled": False,  # Opt-in data sharing
        "min_interval_minutes": 30,  # Don't collect more often than this
        "max_samples": 500,  # Auto-pause when reached (~50MB)
    },

    # Timelapse - daily video recording from camera capture mode
    "timelapse": {
        "enabled": False,
        "window_mode": "sun",          # "sun" | "fixed" | "always"
        "sun_mode": "astronomical",    # "astronomical" | "nautical" | "civil" | "sunset_sunrise"
        # Sun-window location is sourced live from weather.latitude/longitude by
        # timelapse_controller — there is no separate timelapse coordinate UI.
        "fixed_start": "18:00",        # HH:MM local time (used when window_mode="fixed")
        "fixed_end": "06:00",          # HH:MM local time (crossing midnight is supported)
        "playback_fps": 24,            # Output video playback frame rate
        "video_crf": 23,               # H.264 CRF quality (0-51, lower=better, 23=default)
        "video_preset": "fast",        # ffmpeg preset (ultrafast/fast/medium/slow)
        # Longest output side in px; 0 = native. Encoding a 2628x2628 sensor at
        # native resolution makes every piped frame ~20MB and puts libx264
        # seconds behind the capture — 1920 is the panel's default option too.
        "output_max_dim": 1920,        # 0 (native) | 1920 | 1440 | 1280 | 720
        "include_overlays": False,     # False = clean frame, True = frame with overlays
        "output_dir": "",              # "" = AppData/PFRSentinel/timelapse/
        "max_videos_to_keep": 30,      # Auto-delete oldest beyond this many days
    },

    # Meteor Tracker — temporal-stack trail detection (see docs/METEOR_DETECTION_PLAN.md)
    "meteor": {
        "enabled": False,
        "min_length": 100,              # Minimum trail length in pixels (full-res)
        "detection_cooldown": 30,       # Seconds between detection events (0 = disabled)
        "save_detections": True,        # Append events to a JSONL log
        "log_file": "",                 # "" = %LOCALAPPDATA%\PFRSentinel\meteor_detections.jsonl
        "save_annotated": False,        # Save annotated full-frame copies with detections
        "annotated_dir": "",            # "" = disabled
        "exclusion_zones": [],          # [{x,y,w,h,note}] — user-rejected regions
        # --- Temporal stack detector (Phase 2+) ---
        "stack_frames": 6,              # FrameStack ring-buffer depth
        # Structure mask — suppress the Moon-drift crescent and mount slew
        # envelope (a superset of the static hot-pixel mask). The dominant
        # false-positive class on obstructed pier cameras. See frame_stack.py.
        "structure_mask": True,         # False → fall back to static hot_mask only
        "structure_mask_fraction": 0.5, # Bright in ≥ this fraction of stack frames → suppress
        "structure_mask_dilate_px": 3,  # Dilate the mask to bridge slew gaps / crescent lips
        "detection_long_side": 1280,    # Detection working resolution (long side, px)
        "noise_sensitivity": "normal",  # low | normal | high → diff-noise threshold mapping
        "min_brightness": 10,           # Min mean transient value along trail (0 = off)
        "max_nonline_prob": 0.30,       # Reject blobs fatter than this width/length ratio
        "max_length_frac": 0.5,         # Reject streaks longer than this fraction of frame width
        "track_suppress_minutes": 10,   # Plane-trajectory suppression TTL
        # --- Deprecated (pre-rework, read-but-ignored; remove in Phase 6) ---
        "diff_threshold": 25,
        "adaptive_threshold": True,
    },

    # All-sky overlay — astronomical annotations on each frame
    "allsky_overlay": {
        "enabled": False,
        "calibration_file": "",
        # Show only the N brightest objects across all catalogs. 0 = unlimited.
        "top_n": 15,
        # UTC offset of timestamps in image metadata/filenames — NINA and most
        # capture software write LOCAL time, so constellations misalign at 0.
        "utc_offset_hours": 0,
        "constellations": {
            "enabled": True, "lines": True, "labels": True,
            "color": "#4488FF", "line_width": 2, "label_size": 12, "opacity": 180,
            "edge_fade_px": 250,
        },
        "bright_stars": {
            "enabled": False, "max_magnitude": 3, "bayer_fallback": False,
            "color": "#FFDD44", "label_size": 11, "opacity": 220,
        },
        "messier": {
            "enabled": True, "color": "#FF8844",
            "marker_size": 8, "label_size": 10, "opacity": 200,
        },
        "ngc": {
            "enabled": False, "min_magnitude": 8.0, "color": "#88FF44",
            "marker_size": 6, "label_size": 9, "opacity": 150,
        },
        "planets": {
            "enabled": True, "color": "#FFFFCC",
            "label_size": 14, "marker_size": 10, "opacity": 255,
            "colors": {
                "Mercury": "#B0B0B0", "Venus": "#FFFFCC", "Mars": "#FF6644",
                "Jupiter": "#FFCC88", "Saturn": "#FFDDAA",
                "Uranus": "#88DDFF", "Neptune": "#4466FF", "Moon": "#FFFFEE",
            },
        },
        # Off by default: the settings panel writes these all-False, so a
        # True default only ever applied to fresh installs that had not yet
        # saved the all-sky panel — which drew a full alt/az grid unasked.
        "grid": {
            "enabled": False, "horizon": False, "altitude_rings": False,
            "altitude_step": 30, "azimuth_lines": False, "cardinal_labels": False,
            "color": "#336633", "line_width": 1, "label_size": 14, "opacity": 120,
        },
        # Per-destination burn-in; overlay stays preview-only unless opted in.
        "burn_into_output": {"saved_file": False, "web": False, "timelapse": False},
    },
}
