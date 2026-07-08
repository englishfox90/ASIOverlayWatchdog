"""Notification event types shared by every outbound backend (Discord, Hermes).

A call site builds one ``NotificationEvent`` and hands it to
``NotificationDispatcher.notify()`` — it never talks to a specific backend.
"""
from dataclasses import dataclass, field

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
