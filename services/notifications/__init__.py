"""Notification dispatcher package — Discord + Hermes webhook backends.

See docs/dev/HERMES_NOTIFICATIONS_PLAN.md for the design.
"""
from .dispatcher import NotificationDispatcher
from .events import (
    CALIBRATION_DONE,
    ERROR,
    LIFECYCLE,
    NotificationEvent,
    PERIODIC_IMAGE,
    ROOF_CHANGED,
    TIMELAPSE_DONE,
)

__all__ = [
    "NotificationDispatcher",
    "NotificationEvent",
    "ROOF_CHANGED",
    "ERROR",
    "LIFECYCLE",
    "PERIODIC_IMAGE",
    "TIMELAPSE_DONE",
    "CALIBRATION_DONE",
]
