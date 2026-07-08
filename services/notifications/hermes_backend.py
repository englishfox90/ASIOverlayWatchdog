"""Builds and signs the Hermes webhook payload for each notification event,
then POSTs it with retry. Hermes is an LLM agent that composes and delivers
the human-facing alert from this structured JSON — see
docs/dev/HERMES_NOTIFICATIONS_PLAN.md for the wire contract.
"""
from datetime import datetime, timezone

from ..app_config import APP_DISPLAY_NAME
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
from .hermes_signing import build_signed_request
from .webhook_http import post_with_retry, redact_webhook_error

# Mirrors the Discord post_* flag names — one flag gates every phase of LIFECYCLE.
_EVENT_GATE_KEY = {
    ROOF_CHANGED: 'post_roof_changes',
    ERROR: 'post_errors',
    LIFECYCLE: 'post_startup_shutdown',
    PERIODIC_IMAGE: 'periodic_enabled',
    TIMELAPSE_DONE: 'post_timelapse',
    CALIBRATION_DONE: 'post_calibration',
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class HermesBackend(NotificationBackend):
    def __init__(self, config):
        super().__init__(config, "hermes")

    def is_enabled(self) -> bool:
        hermes = self.config.get('hermes', {})
        if not hermes.get('enabled', False):
            return False
        if (hermes.get('url') or '').strip():
            return True
        # No base URL, but per-event routing may still target some events.
        if hermes.get('route_by_event', False):
            return any((u or '').strip() for u in (hermes.get('event_urls') or {}).values())
        return False

    def _resolve_url(self, hermes, event_type) -> str:
        """Destination for this event: the per-event override when routing is on
        and set, otherwise the base URL."""
        base = (hermes.get('url') or '').strip()
        if hermes.get('route_by_event', False):
            override = ((hermes.get('event_urls') or {}).get(event_type) or '').strip()
            return override or base
        return base

    def _deliver(self, event) -> None:
        hermes = self.config.get('hermes', {})
        gate_key = _EVENT_GATE_KEY.get(event.type)
        if gate_key is None:
            app_logger.warning(f"Hermes backend: unknown event type '{event.type}'")
            return
        if not hermes.get(gate_key, False):
            return

        url = self._resolve_url(hermes, event.type)
        if not url:
            app_logger.warning(
                f"Hermes: no URL for event '{event.type}' (base and per-event "
                f"override both empty); skipping"
            )
            return

        payload = self._build_payload(event)
        body, headers = build_signed_request(hermes.get('secret', ''), payload)
        self._post(url, body, headers, event.type)

    def _post(self, url, body, headers, event_type) -> None:
        try:
            response = post_with_retry(url, data=body, headers=headers, timeout=10)
        except Exception as e:
            app_logger.error(f"Hermes webhook failed ({event_type}): {redact_webhook_error(e)}")
            return

        if 200 <= response.status_code < 300:
            app_logger.info(f"Hermes notification sent ({event_type})")
            from ..posthog_service import capture_event
            capture_event('hermes_post_sent', {'event_type': event_type})
        else:
            detail = response.text[:200] if hasattr(response, 'text') else ''
            app_logger.error(
                f"Hermes webhook failed ({event_type}): HTTP {response.status_code} - {detail}"
            )

    def _build_payload(self, event) -> dict:
        payload = {
            "event": event.type,
            # Hermes' native subscription filter matches on event_type; keep it in
            # sync with event so filtered subscriptions don't drop us as "unknown".
            "event_type": event.type,
            "level": event.level,
            "title": event.title,
            "body": event.body,
            "source": APP_DISPLAY_NAME,
            "timestamp": _utc_now_iso(),
        }
        image = self._build_image_ref(event)
        if image is not None:
            payload["image"] = image
        payload.update(self._event_block(event))
        return payload

    def _build_image_ref(self, event):
        if event.image_id is None:
            return None
        library = self.config.get('library', {})
        if not library.get('api_enabled', True):
            return None
        output = self.config.get('output', {})
        host = output.get('webserver_host', '127.0.0.1')
        if host == '0.0.0.0':
            host = '127.0.0.1'
        port = output.get('webserver_port', 8080)
        return {
            "id": event.image_id,
            "url": f"http://{host}:{port}/library/image?id={event.image_id}",
        }

    def _event_block(self, event) -> dict:
        data = event.data or {}
        if event.type == ROOF_CHANGED:
            return {"roof": {"open": data.get('roof_open'), "confidence": data.get('confidence')}}
        if event.type == ERROR:
            return {"error": {"text": event.body}}
        if event.type == LIFECYCLE:
            return {
                "lifecycle": {
                    "phase": data.get('phase'),
                    "mode": data.get('mode'),
                    "output_path": data.get('output_path'),
                }
            }
        if event.type == PERIODIC_IMAGE:
            return {
                "capture": {
                    "exposure": data.get('exposure'),
                    "gain": data.get('gain'),
                    "temp": data.get('temp'),
                    "resolution": data.get('resolution'),
                }
            }
        if event.type == TIMELAPSE_DONE:
            return {
                "timelapse": {
                    "frame_count": data.get('frame_count'),
                    "elapsed_seconds": data.get('elapsed_seconds'),
                    "filename": data.get('filename'),
                }
            }
        if event.type == CALIBRATION_DONE:
            model_info = data.get('model_info', {})
            return {
                "calibration": {
                    "rms_residual": model_info.get('rms_residual'),
                    "n_matches": model_info.get('n_matches'),
                    "calibrated_at": model_info.get('calibrated_at'),
                    "a1": model_info.get('a1'),
                    "cx": model_info.get('cx'),
                    "cy": model_info.get('cy'),
                }
            }
        return {}

    def test(self, config_or_none=None):
        """POST a minimal test payload. Returns (success, status)."""
        cfg = config_or_none or self.config
        hermes = cfg.get('hermes', {})
        url = hermes.get('url', '')
        secret = hermes.get('secret', '')
        if not url or not secret:
            return False, "Hermes URL or secret not configured"

        payload = {
            "event": "test",
            "event_type": "test",
            "level": "info",
            "title": "Test Notification",
            "body": f"Test message from {APP_DISPLAY_NAME}.",
            "source": APP_DISPLAY_NAME,
            "timestamp": _utc_now_iso(),
        }
        body, headers = build_signed_request(secret, payload)
        try:
            response = post_with_retry(url, data=body, headers=headers, timeout=10)
        except Exception as e:
            return False, redact_webhook_error(e)

        if 200 <= response.status_code < 300:
            return True, f"Success (HTTP {response.status_code})"
        return False, f"Failed: HTTP {response.status_code}"
