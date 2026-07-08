"""Adapter: routes ``NotificationEvent`` objects to the existing
``DiscordAlerts`` methods with unchanged behaviour. This backend owns no new
business logic — see docs/dev/HERMES_NOTIFICATIONS_PLAN.md for the mapping.
"""
from ..discord_alerts import DiscordAlerts
from ..logger import app_logger
from .base import NotificationBackend
from .events import (
    CALIBRATION_DONE,
    ERROR,
    LIFECYCLE,
    PERIODIC_IMAGE,
    ROOF_CHANGED,
    TIMELAPSE_DONE,
)


class DiscordBackend(NotificationBackend):
    def __init__(self, config):
        super().__init__(config, "discord")

    def is_enabled(self) -> bool:
        return bool(self.config.get('discord', {}).get('enabled', False))

    def _deliver(self, event) -> None:
        alerts = DiscordAlerts(self.config)

        if event.type == ROOF_CHANGED:
            alerts.send_roof_status_change(
                event.data.get('roof_open'), event.data.get('confidence'), event.image_path
            )
        elif event.type == ERROR:
            alerts.send_error_message(event.body)
        elif event.type == LIFECYCLE:
            self._deliver_lifecycle(alerts, event)
        elif event.type == PERIODIC_IMAGE:
            self._deliver_periodic(alerts, event)
        elif event.type == TIMELAPSE_DONE:
            alerts.send_timelapse_completed(
                event.video_path, event.data.get('frame_count'), event.data.get('elapsed_seconds')
            )
        elif event.type == CALIBRATION_DONE:
            alerts.send_calibration_complete(event.data.get('model_info', {}))
        else:
            app_logger.warning(f"Discord backend: unknown event type '{event.type}'")

    def _deliver_lifecycle(self, alerts, event) -> None:
        phase = event.data.get('phase')
        if phase == 'startup':
            alerts.send_startup_message()
        elif phase == 'shutdown':
            alerts.send_shutdown_message()
        elif phase == 'capture_started':
            alerts.send_capture_started_message()
        else:
            app_logger.warning(f"Discord backend: unknown lifecycle phase '{phase}'")

    def _deliver_periodic(self, alerts, event) -> None:
        # Unlike the other events (whose DiscordAlerts methods self-gate on their
        # post_* flag), periodic routes through the generic send_discord_message,
        # which has no periodic gate — so check it here. Without this, enabling
        # Hermes periodic would also start Discord periodic posts.
        if not self.config.get('discord', {}).get('periodic_enabled', False):
            return
        success = alerts.send_discord_message(
            event.title, event.body, event.level, image_path=event.image_path
        )
        if success:
            from ..posthog_service import capture_event
            discord_config = self.config.get('discord', {})
            capture_event('discord_post_sent', {
                'interval_minutes': discord_config.get('periodic_interval_minutes', 60),
                'include_image': discord_config.get('include_latest_image', True),
            })

    def test(self, config_or_none=None):
        """Send a test embed via the existing Discord path. Returns (success, status)."""
        alerts = DiscordAlerts(config_or_none or self.config)
        success = alerts.send_discord_message(
            "Test Notification", "This is a test message from PFR Sentinel.", level="info"
        )
        return success, alerts.get_last_status()
