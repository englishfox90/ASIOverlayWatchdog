"""Fans a single semantic ``NotificationEvent`` out to every enabled backend.

Construct once per app instance; both backends are always built so toggling
config at runtime (via the Settings UI) takes effect without a restart.
"""
from ..logger import app_logger
from .discord_backend import DiscordBackend
from .hermes_backend import HermesBackend


class NotificationDispatcher:
    def __init__(self, config):
        self.config = config
        self._latest_image_id = None
        self._backends = {
            "discord": DiscordBackend(config),
            "hermes": HermesBackend(config),
        }

    def notify(self, event) -> None:
        """Fan ``event`` out to every enabled backend. Never blocks."""
        if event.image_id is None:
            event.image_id = self._latest_image_id
        for backend in self._backends.values():
            try:
                if backend.is_enabled():
                    backend.submit(event)
            except Exception as e:
                app_logger.error(f"Notification dispatch to {backend.name} failed: {e}")

    def on_frame_archived(self, record) -> None:
        self._latest_image_id = record.get("id") if record else None

    def test(self, name):
        """Synchronously run a backend's test send. Returns (success, status)."""
        backend = self._backends.get(name)
        if backend is None:
            return False, f"Unknown notification backend '{name}'"
        try:
            return backend.test(self.config)
        except Exception as e:
            app_logger.error(f"Notification test for {name} failed: {e}")
            return False, str(e)

    def shutdown(self) -> None:
        for backend in self._backends.values():
            try:
                backend.shutdown()
            except Exception as e:
                app_logger.error(f"Notification backend {backend.name} shutdown failed: {e}")
