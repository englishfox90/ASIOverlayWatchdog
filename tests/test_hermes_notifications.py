"""Tests for services/notifications/ — Hermes webhook signing, HermesBackend
payload construction + gating, and NotificationDispatcher fan-out.

All network I/O is mocked: no real sockets, no real webhook POSTs. Follows
.claude/rules/tests.md — config is exercised as a plain dict, since the
notification code only ever calls ``config.get(...)``.
"""
import hashlib
import hmac
import json
import re
from unittest.mock import MagicMock, patch

import pytest

import services.notifications.dispatcher as dispatcher_module
from services.notifications.events import (
    CALIBRATION_DONE,
    ERROR,
    LIFECYCLE,
    NotificationEvent,
    PERIODIC_IMAGE,
    ROOF_CHANGED,
    TIMELAPSE_DONE,
)
from services.notifications.hermes_backend import HermesBackend
from services.notifications.hermes_signing import build_signed_request


# ---------------------------------------------------------------------------
# hermes_signing.build_signed_request
# ---------------------------------------------------------------------------

class TestBuildSignedRequest:
    def test_deterministic_for_fixed_inputs(self):
        payload = {"event": "roof_changed", "level": "warning", "n": 1}
        body1, headers1 = build_signed_request("shh", payload, timestamp=1700000000)
        body2, headers2 = build_signed_request("shh", payload, timestamp=1700000000)

        assert body1 == body2
        assert headers1 == headers2
        assert headers1["X-Webhook-Signature-V2"] == headers2["X-Webhook-Signature-V2"]

    def test_headers_present_and_named_correctly(self):
        payload = {"event": "error"}
        body, headers = build_signed_request("secret", payload, timestamp=1700000000)

        assert set(headers.keys()) == {
            "Content-Type",
            "X-Webhook-Signature-V2",
            "X-Webhook-Timestamp",
        }
        assert headers["Content-Type"] == "application/json"
        assert headers["X-Webhook-Timestamp"] == "1700000000"
        assert isinstance(headers["X-Webhook-Signature-V2"], str)
        assert len(headers["X-Webhook-Signature-V2"]) == 64  # hex sha256 digest

    def test_signature_matches_independent_hmac_computation(self):
        secret = "top-secret"
        payload = {"event": "calibration_done", "level": "success", "title": "Done"}
        timestamp = 1712345678

        body, headers = build_signed_request(secret, payload, timestamp=timestamp)

        expected_sig = hmac.new(
            secret.encode("utf-8"),
            f"{timestamp}.".encode("utf-8") + body,
            hashlib.sha256,
        ).hexdigest()

        assert headers["X-Webhook-Signature-V2"] == expected_sig

    def test_mutating_payload_changes_signature(self):
        timestamp = 1700000000
        body_a, headers_a = build_signed_request(
            "secret", {"event": "error", "body": "one"}, timestamp=timestamp
        )
        body_b, headers_b = build_signed_request(
            "secret", {"event": "error", "body": "two"}, timestamp=timestamp
        )

        assert body_a != body_b
        assert headers_a["X-Webhook-Signature-V2"] != headers_b["X-Webhook-Signature-V2"]

    def test_body_bytes_round_trip_to_payload(self):
        payload = {"event": "timelapse_done", "data": {"frame_count": 42, "ok": True}}
        body, _headers = build_signed_request("secret", payload, timestamp=1700000000)

        assert isinstance(body, bytes)
        assert json.loads(body) == payload
        assert body == json.dumps(payload, separators=(",", ":")).encode("utf-8")

    def test_defaults_to_current_time_when_timestamp_omitted(self):
        _body, headers = build_signed_request("secret", {"event": "error"})
        assert headers["X-Webhook-Timestamp"].isdigit()


# ---------------------------------------------------------------------------
# HermesBackend
# ---------------------------------------------------------------------------

def _hermes_config(**hermes_overrides):
    hermes = {
        "enabled": True,
        "url": "https://hermes.example.com/webhook",
        "secret": "shared-secret",
        "post_errors": True,
        "post_startup_shutdown": True,
        "post_roof_changes": True,
        "post_timelapse": True,
        "post_calibration": True,
        "periodic_enabled": True,
    }
    hermes.update(hermes_overrides)
    return {
        "hermes": hermes,
        "library": {"api_enabled": True},
        "output": {"webserver_host": "127.0.0.1", "webserver_port": 8080},
    }


class TestHermesBackendIsEnabled:
    def test_false_when_hermes_disabled(self):
        config = _hermes_config(enabled=False)
        assert HermesBackend(config).is_enabled() is False

    def test_false_when_url_empty(self):
        config = _hermes_config(url="")
        assert HermesBackend(config).is_enabled() is False

    def test_true_when_enabled_and_url_set(self):
        config = _hermes_config()
        assert HermesBackend(config).is_enabled() is True


class TestHermesBackendBuildPayload:
    def test_envelope_keys(self):
        config = _hermes_config()
        backend = HermesBackend(config)
        event = NotificationEvent(
            type=ERROR, title="Something broke", body="Disk full", level="error"
        )

        payload = backend._build_payload(event)

        assert payload["event"] == ERROR
        # event_type mirrors event so Hermes' native subscription filter matches us.
        assert payload["event_type"] == ERROR
        assert payload["level"] == "error"
        assert payload["title"] == "Something broke"
        assert payload["body"] == "Disk full"
        assert payload["source"] == "PFR Sentinel"
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", payload["timestamp"])

    def test_roof_changed_block(self):
        backend = HermesBackend(_hermes_config())
        event = NotificationEvent(
            type=ROOF_CHANGED, data={"roof_open": False, "confidence": 0.94}
        )
        payload = backend._build_payload(event)
        assert payload["roof"] == {"open": False, "confidence": 0.94}

    def test_error_block(self):
        backend = HermesBackend(_hermes_config())
        event = NotificationEvent(type=ERROR, body="Camera disconnected")
        payload = backend._build_payload(event)
        assert payload["error"] == {"text": "Camera disconnected"}

    def test_lifecycle_block(self):
        backend = HermesBackend(_hermes_config())
        event = NotificationEvent(
            type=LIFECYCLE,
            data={"phase": "startup", "mode": "camera", "output_path": "D:/out"},
        )
        payload = backend._build_payload(event)
        assert payload["lifecycle"] == {
            "phase": "startup",
            "mode": "camera",
            "output_path": "D:/out",
        }

    def test_capture_block_for_periodic_image(self):
        backend = HermesBackend(_hermes_config())
        event = NotificationEvent(
            type=PERIODIC_IMAGE,
            data={"exposure": "5.0s", "gain": 200, "temp": "-10.5C", "resolution": "4144x2822"},
        )
        payload = backend._build_payload(event)
        assert payload["capture"] == {
            "exposure": "5.0s",
            "gain": 200,
            "temp": "-10.5C",
            "resolution": "4144x2822",
        }

    def test_timelapse_block(self):
        backend = HermesBackend(_hermes_config())
        event = NotificationEvent(
            type=TIMELAPSE_DONE,
            data={"frame_count": 300, "elapsed_seconds": 15, "filename": "night.mp4"},
        )
        payload = backend._build_payload(event)
        assert payload["timelapse"] == {
            "frame_count": 300,
            "elapsed_seconds": 15,
            "filename": "night.mp4",
        }

    def test_calibration_block(self):
        backend = HermesBackend(_hermes_config())
        event = NotificationEvent(
            type=CALIBRATION_DONE,
            data={
                "model_info": {
                    "rms_residual": 1.23,
                    "n_matches": 42,
                    "calibrated_at": "2026-07-07T00:00:00Z",
                    "a1": 0.5,
                    "cx": 960.0,
                    "cy": 540.0,
                }
            },
        )
        payload = backend._build_payload(event)
        assert payload["calibration"] == {
            "rms_residual": 1.23,
            "n_matches": 42,
            "calibrated_at": "2026-07-07T00:00:00Z",
            "a1": 0.5,
            "cx": 960.0,
            "cy": 540.0,
        }

    def test_image_present_when_id_set_and_library_enabled(self):
        backend = HermesBackend(_hermes_config())
        event = NotificationEvent(type=ERROR, body="x", image_id=1234)
        payload = backend._build_payload(event)
        assert payload["image"] == {
            "id": 1234,
            "url": "http://127.0.0.1:8080/library/image?id=1234",
        }

    def test_image_url_substitutes_localhost_for_wildcard_host(self):
        config = _hermes_config()
        config["output"] = {"webserver_host": "0.0.0.0", "webserver_port": 9090}
        backend = HermesBackend(config)
        event = NotificationEvent(type=ERROR, body="x", image_id=42)
        payload = backend._build_payload(event)
        assert payload["image"]["url"] == "http://127.0.0.1:9090/library/image?id=42"

    def test_image_absent_when_image_id_none(self):
        backend = HermesBackend(_hermes_config())
        event = NotificationEvent(type=ERROR, body="x", image_id=None)
        payload = backend._build_payload(event)
        assert "image" not in payload

    def test_image_absent_when_library_api_disabled(self):
        config = _hermes_config()
        config["library"] = {"api_enabled": False}
        backend = HermesBackend(config)
        event = NotificationEvent(type=ERROR, body="x", image_id=1234)
        payload = backend._build_payload(event)
        assert "image" not in payload


class TestHermesBackendDeliverGating:
    def test_deliver_does_not_post_when_event_flag_disabled(self):
        with patch("services.notifications.hermes_backend.post_with_retry") as post_mock:
            config = _hermes_config(post_errors=False)
            backend = HermesBackend(config)
            event = NotificationEvent(type=ERROR, body="oops")

            backend._deliver(event)

            post_mock.assert_not_called()

    def test_deliver_posts_signed_body_when_event_flag_enabled(self):
        response = MagicMock(status_code=200)
        with patch(
            "services.notifications.hermes_backend.post_with_retry", return_value=response
        ) as post_mock, patch("services.posthog_service.capture_event"):
            config = _hermes_config(post_errors=True, secret="s3cr3t")
            backend = HermesBackend(config)
            event = NotificationEvent(type=ERROR, body="oops", title="Error", level="error")

            backend._deliver(event)

        post_mock.assert_called_once()
        args, kwargs = post_mock.call_args
        assert args[0] == config["hermes"]["url"]
        body = kwargs["data"]
        headers = kwargs["headers"]
        assert json.loads(body)["event"] == ERROR
        assert "X-Webhook-Signature-V2" in headers

        expected_sig = hmac.new(
            b"s3cr3t",
            f"{headers['X-Webhook-Timestamp']}.".encode("utf-8") + body,
            hashlib.sha256,
        ).hexdigest()
        assert headers["X-Webhook-Signature-V2"] == expected_sig

    @pytest.mark.parametrize(
        "event_type, gate_key",
        [
            (ROOF_CHANGED, "post_roof_changes"),
            (ERROR, "post_errors"),
            (LIFECYCLE, "post_startup_shutdown"),
            (PERIODIC_IMAGE, "periodic_enabled"),
            (TIMELAPSE_DONE, "post_timelapse"),
            (CALIBRATION_DONE, "post_calibration"),
        ],
    )
    def test_each_event_type_gated_by_its_own_flag(self, event_type, gate_key):
        with patch("services.notifications.hermes_backend.post_with_retry") as post_mock:
            config = _hermes_config(**{gate_key: False})
            backend = HermesBackend(config)
            event = NotificationEvent(type=event_type, body="x")

            backend._deliver(event)

            post_mock.assert_not_called()

    def test_deliver_logs_and_does_not_raise_on_post_failure(self):
        with patch(
            "services.notifications.hermes_backend.post_with_retry",
            side_effect=ConnectionError("no route to host"),
        ):
            config = _hermes_config()
            backend = HermesBackend(config)
            event = NotificationEvent(type=ERROR, body="oops")

            backend._deliver(event)  # must not raise


# ---------------------------------------------------------------------------
# Per-event URL routing (route_by_event + event_urls)
# ---------------------------------------------------------------------------

class TestHermesBackendUrlRouting:
    def _post_url(self, config, event_type=ERROR):
        """Return the URL _deliver() actually POSTs to, or None if it skipped."""
        response = MagicMock(status_code=200)
        with patch(
            "services.notifications.hermes_backend.post_with_retry", return_value=response
        ) as post_mock, patch("services.posthog_service.capture_event"):
            HermesBackend(config)._deliver(NotificationEvent(type=event_type, body="x"))
        return post_mock.call_args[0][0] if post_mock.called else None

    def test_routing_off_always_uses_base_url_even_when_overrides_set(self):
        config = _hermes_config(
            route_by_event=False,
            event_urls={"error": "https://h/webhooks/sentinel-error"},
        )
        assert self._post_url(config) == config["hermes"]["url"]

    def test_routing_on_uses_per_event_override(self):
        override = "https://h/webhooks/sentinel-error"
        config = _hermes_config(route_by_event=True, event_urls={"error": override})
        assert self._post_url(config) == override

    def test_routing_on_falls_back_to_base_when_override_blank(self):
        config = _hermes_config(route_by_event=True, event_urls={"error": ""})
        assert self._post_url(config) == config["hermes"]["url"]

    def test_routes_distinct_event_types_to_distinct_urls(self):
        config = _hermes_config(route_by_event=True, event_urls={
            "error": "https://h/webhooks/sentinel-error",
            "roof_changed": "https://h/webhooks/sentinel-roof",
        })
        assert self._post_url(config, ERROR) == "https://h/webhooks/sentinel-error"
        assert self._post_url(config, ROOF_CHANGED) == "https://h/webhooks/sentinel-roof"

    def test_skips_when_no_base_and_no_override(self):
        config = _hermes_config(url="", route_by_event=True, event_urls={"error": ""})
        assert self._post_url(config) is None

    def test_is_enabled_true_with_only_event_urls_and_no_base(self):
        config = _hermes_config(url="", route_by_event=True,
                                event_urls={"error": "https://h/webhooks/sentinel-error"})
        assert HermesBackend(config).is_enabled() is True

    def test_is_enabled_false_when_no_base_and_routing_off(self):
        config = _hermes_config(url="", route_by_event=False,
                                event_urls={"error": "https://h/webhooks/sentinel-error"})
        assert HermesBackend(config).is_enabled() is False


# ---------------------------------------------------------------------------
# NotificationDispatcher
# ---------------------------------------------------------------------------

def _make_backend_mock(enabled: bool):
    backend = MagicMock()
    backend.is_enabled.return_value = enabled
    return backend


class TestNotificationDispatcher:
    def test_notify_submits_only_to_enabled_backends(self, monkeypatch):
        discord_mock = _make_backend_mock(enabled=True)
        hermes_mock = _make_backend_mock(enabled=False)
        monkeypatch.setattr(dispatcher_module, "DiscordBackend", lambda config: discord_mock)
        monkeypatch.setattr(dispatcher_module, "HermesBackend", lambda config: hermes_mock)

        dispatcher = dispatcher_module.NotificationDispatcher({})
        event = NotificationEvent(type=ERROR, body="x")
        dispatcher.notify(event)

        discord_mock.submit.assert_called_once_with(event)
        hermes_mock.submit.assert_not_called()

    def test_image_id_autofilled_from_frame_archived_cache(self, monkeypatch):
        discord_mock = _make_backend_mock(enabled=True)
        hermes_mock = _make_backend_mock(enabled=True)
        monkeypatch.setattr(dispatcher_module, "DiscordBackend", lambda config: discord_mock)
        monkeypatch.setattr(dispatcher_module, "HermesBackend", lambda config: hermes_mock)

        dispatcher = dispatcher_module.NotificationDispatcher({})
        dispatcher.on_frame_archived({"id": 1234})

        event = NotificationEvent(type=PERIODIC_IMAGE, body="x", image_id=None)
        dispatcher.notify(event)

        assert event.image_id == 1234
        discord_mock.submit.assert_called_once_with(event)
        hermes_mock.submit.assert_called_once_with(event)

    def test_image_id_left_untouched_when_already_set(self, monkeypatch):
        discord_mock = _make_backend_mock(enabled=True)
        hermes_mock = _make_backend_mock(enabled=True)
        monkeypatch.setattr(dispatcher_module, "DiscordBackend", lambda config: discord_mock)
        monkeypatch.setattr(dispatcher_module, "HermesBackend", lambda config: hermes_mock)

        dispatcher = dispatcher_module.NotificationDispatcher({})
        dispatcher.on_frame_archived({"id": 999})

        event = NotificationEvent(type=PERIODIC_IMAGE, body="x", image_id=42)
        dispatcher.notify(event)

        assert event.image_id == 42

    def test_frame_archived_with_none_record_clears_cache(self, monkeypatch):
        discord_mock = _make_backend_mock(enabled=True)
        hermes_mock = _make_backend_mock(enabled=False)
        monkeypatch.setattr(dispatcher_module, "DiscordBackend", lambda config: discord_mock)
        monkeypatch.setattr(dispatcher_module, "HermesBackend", lambda config: hermes_mock)

        dispatcher = dispatcher_module.NotificationDispatcher({})
        dispatcher.on_frame_archived({"id": 1234})
        dispatcher.on_frame_archived(None)

        event = NotificationEvent(type=ERROR, body="x", image_id=None)
        dispatcher.notify(event)

        assert event.image_id is None

    def test_backend_isolation_raising_backend_does_not_block_the_other(self, monkeypatch):
        discord_mock = _make_backend_mock(enabled=True)
        discord_mock.submit.side_effect = RuntimeError("discord blew up")
        hermes_mock = _make_backend_mock(enabled=True)
        monkeypatch.setattr(dispatcher_module, "DiscordBackend", lambda config: discord_mock)
        monkeypatch.setattr(dispatcher_module, "HermesBackend", lambda config: hermes_mock)

        dispatcher = dispatcher_module.NotificationDispatcher({})
        event = NotificationEvent(type=ERROR, body="x")

        dispatcher.notify(event)  # must not raise despite discord_mock.submit raising

        discord_mock.submit.assert_called_once_with(event)
        hermes_mock.submit.assert_called_once_with(event)

    def test_test_dispatches_to_named_backend(self, monkeypatch):
        discord_mock = MagicMock()
        discord_mock.test.return_value = (True, "Success (HTTP 200)")
        hermes_mock = MagicMock()
        monkeypatch.setattr(dispatcher_module, "DiscordBackend", lambda config: discord_mock)
        monkeypatch.setattr(dispatcher_module, "HermesBackend", lambda config: hermes_mock)

        dispatcher = dispatcher_module.NotificationDispatcher({})
        ok, status = dispatcher.test("discord")

        assert ok is True
        assert status == "Success (HTTP 200)"
        hermes_mock.test.assert_not_called()

    def test_test_returns_false_for_unknown_backend_name(self, monkeypatch):
        monkeypatch.setattr(dispatcher_module, "DiscordBackend", lambda config: MagicMock())
        monkeypatch.setattr(dispatcher_module, "HermesBackend", lambda config: MagicMock())

        dispatcher = dispatcher_module.NotificationDispatcher({})
        ok, status = dispatcher.test("carrier_pigeon")

        assert ok is False
        assert "carrier_pigeon" in status


# ---------------------------------------------------------------------------
# DiscordBackend periodic gating — regression guard.
#
# Every other Discord event self-gates inside its DiscordAlerts method, but
# PERIODIC_IMAGE routes through the generic send_discord_message (no gate), so
# the backend must check discord.periodic_enabled itself. Without it, turning on
# Hermes periodic would also start Discord periodic posts (the dispatcher fans
# every event to every enabled backend).
# ---------------------------------------------------------------------------

class TestDiscordBackendPeriodicGating:
    def _run(self, periodic_enabled):
        from services.notifications.discord_backend import DiscordBackend
        config = {"discord": {"enabled": True, "webhook_url": "http://x",
                              "periodic_enabled": periodic_enabled}}
        with patch("services.notifications.discord_backend.DiscordAlerts") as alerts_cls:
            alerts_cls.return_value.send_discord_message.return_value = False
            backend = DiscordBackend(config)
            backend._deliver(NotificationEvent(type=PERIODIC_IMAGE, title="t", body="b"))
            return alerts_cls.return_value.send_discord_message

    def test_periodic_suppressed_when_flag_off(self):
        self._run(periodic_enabled=False).assert_not_called()

    def test_periodic_sent_when_flag_on(self):
        self._run(periodic_enabled=True).assert_called_once()
