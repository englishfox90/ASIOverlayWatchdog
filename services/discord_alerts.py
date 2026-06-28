"""
Discord webhook integration for alerts and notifications
"""
import os
import io
import re
import json
import time
import requests
from datetime import datetime, timezone
from PIL import Image
from .logger import app_logger
from .app_config import APP_DISPLAY_NAME

# Max height for images posted to Discord periodic updates (reduces bandwidth)
DISCORD_IMAGE_MAX_HEIGHT = 750

# Hard limit for Discord image uploads (1 MB)
DISCORD_IMAGE_MAX_BYTES = 1 * 1024 * 1024


# A live webhook secret. requests reports the failed request as a BARE PATH
# (".../url: /api/webhooks/<id>/<token> (Caused by ...)"), not a full http(s)://
# URL — so the shared URL redactor misses it. Strip the path itself first.
_WEBHOOK_PATH_RE = re.compile(r"/api/webhooks/\d+/[^\s/)]+", re.I)


def redact_discord_error(exc) -> str:
    """Return a log-safe ``"ExcType: message"`` string for a Discord webhook error.

    A ``requests`` exception (ConnectionError, etc.) embeds the webhook the
    request targeted — ``/api/webhooks/<id>/<token>`` — as a bare path, and the
    token is a live secret. Logs are forwarded to PostHog over OTLP (f3a5dd4),
    so a leak egresses. Strip the webhook path here, then run the shared
    URL/secret redactor for any full URLs / tokens. The exception type is
    included so callers don't re-prepend it (and re-invoke the redactor).
    """
    from .youtube_upload import sanitize_exception
    redacted = sanitize_exception(_WEBHOOK_PATH_RE.sub("/api/webhooks/[REDACTED]", str(exc)))
    return f"{type(exc).__name__}: {redacted}"


def format_exposure_time(exp_seconds):
    """Format exposure time dynamically as ms/s/m based on value
    
    Args:
        exp_seconds: Exposure time in seconds (float or int)
    
    Returns:
        str: Formatted exposure like "50ms", "2.5s", or "1.5m"
    """
    if not isinstance(exp_seconds, (int, float)):
        return str(exp_seconds)
    
    if exp_seconds >= 60:
        # Minutes
        minutes = exp_seconds / 60.0
        return f"{minutes:.2f}m"
    elif exp_seconds >= 1:
        # Seconds
        return f"{exp_seconds:.2f}s"
    else:
        # Milliseconds
        ms = exp_seconds * 1000.0
        return f"{ms:.2f}ms"


class DiscordAlerts:
    """Handles Discord webhook notifications"""
    
    def __init__(self, config):
        self.config = config
        self.last_send_status = ""
        self.last_send_time = None
    
    # Retry configuration
    MAX_RETRIES = 3
    BACKOFF_DELAYS = [1, 4, 16]  # seconds between attempts

    def _post_with_retry(self, *args, **kwargs):
        """POST with exponential backoff and rate-limit handling.

        Returns the response on success, or raises the last exception
        after all retries are exhausted.
        """
        last_exception = None
        for attempt in range(self.MAX_RETRIES):
            try:
                response = requests.post(*args, **kwargs)

                # Handle Discord rate limiting
                if response.status_code == 429:
                    retry_after = None
                    try:
                        retry_after = response.json().get('retry_after', None)
                    except Exception:
                        pass
                    wait = float(retry_after) if retry_after else self.BACKOFF_DELAYS[attempt]
                    app_logger.warning(
                        f"Discord rate limited (429), retrying in {wait:.1f}s "
                        f"(attempt {attempt + 1}/{self.MAX_RETRIES})"
                    )
                    time.sleep(wait)
                    continue

                return response

            except (requests.exceptions.Timeout,
                    requests.exceptions.ConnectionError) as e:
                last_exception = e
                if attempt < self.MAX_RETRIES - 1:
                    wait = self.BACKOFF_DELAYS[attempt]
                    app_logger.warning(
                        f"Discord request failed ({type(e).__name__}), "
                        f"retrying in {wait}s (attempt {attempt + 1}/{self.MAX_RETRIES})"
                    )
                    time.sleep(wait)

        # All retries exhausted
        if last_exception:
            raise last_exception
        # Rate-limited on all attempts — return last response
        return response

    def is_enabled(self):
        """Check if Discord alerts are enabled"""
        discord_config = self.config.get('discord', {})
        return discord_config.get('enabled', False) and discord_config.get('webhook_url', '')
    
    def get_color_int(self):
        """Convert hex color to Discord integer format"""
        discord_config = self.config.get('discord', {})
        hex_color = discord_config.get('embed_color_hex', '#0EA5E9')
        
        try:
            # Remove # if present and convert to int
            return int(hex_color.lstrip('#'), 16)
        except (ValueError, AttributeError):
            app_logger.warning(f"Invalid Discord embed color: {hex_color}, using default")
            return int('0EA5E9', 16)  # Default color
    
    def send_discord_message(self, title, description, level="info", image_path=None):
        """
        Send a message to Discord webhook
        
        Args:
            title: Embed title
            description: Embed description/content
            level: Message level (info, warning, error)
            image_path: Optional path to image file to attach
        """
        if not self.is_enabled():
            return False
        
        discord_config = self.config.get('discord', {})
        webhook_url = discord_config.get('webhook_url', '')
        
        if not webhook_url:
            app_logger.error("Discord webhook URL not set")
            self.last_send_status = "Failed: No webhook URL"
            return False
        
        try:
            # Prepare username and avatar
            username = discord_config.get('username_override', '') or APP_DISPLAY_NAME
            avatar_url = discord_config.get('avatar_url', '')
            
            # Build embed
            embed = {
                "title": title,
                "description": description,
                "color": self.get_color_int(),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            
            # Add footer based on level
            level_emoji = {
                'info': 'ℹ️',
                'warning': '⚠️',
                'error': '❌',
                'success': '✅'
            }
            embed["footer"] = {
                "text": f"{level_emoji.get(level, 'ℹ️')} {level.upper()}"
            }
            
            payload = {
                "username": username,
                "embeds": [embed]
            }
            
            if avatar_url:
                payload["avatar_url"] = avatar_url
            
            # Check if we should attach an image
            include_image = discord_config.get('include_latest_image', True)
            
            # Validate image_path is a string path, not a PIL Image or other object
            valid_image_path = (
                image_path and 
                include_image and 
                isinstance(image_path, (str, bytes, os.PathLike)) and 
                os.path.exists(image_path)
            )
            
            # Track image stats for analytics
            _discord_image_stats = None

            if valid_image_path:
                # Resize image to limit bandwidth — keep aspect ratio, cap height.
                # Shared helper (mode="height") so the library/Discord/web paths
                # share one resize implementation, not three copies.
                from .image_resize import downscale_to_jpeg
                img_buf = io.BytesIO()
                _was_resized = False
                _original_w, _original_h = 0, 0
                try:
                    with Image.open(image_path) as img:
                        _original_w, _original_h = img.width, img.height
                        jpeg_bytes, _sent_w, _sent_h = downscale_to_jpeg(
                            img, DISCORD_IMAGE_MAX_HEIGHT, 85, mode="height"
                        )
                        img_buf = io.BytesIO(jpeg_bytes)
                        _was_resized = _original_h > DISCORD_IMAGE_MAX_HEIGHT
                except Exception as resize_err:
                    app_logger.warning(f"Discord image resize failed, sending original: {resize_err}")
                    img_buf = open(image_path, "rb")
                    _sent_w, _sent_h = _original_w, _original_h

                try:
                    img_buf.seek(0)
                    size_bytes = img_buf.getbuffer().nbytes if isinstance(img_buf, io.BytesIO) else os.path.getsize(image_path)
                    size_kb = size_bytes / 1024
                    app_logger.info(f"Discord image: {size_kb:.0f} KB ({os.path.basename(image_path)})")

                    # Only track stats if image was actually opened successfully
                    if _original_w > 0 and _original_h > 0:
                        _discord_image_stats = {
                            'image_size_kb': round(size_kb, 1),
                            'image_width': _sent_w,
                            'image_height': _sent_h,
                            'was_resized': _was_resized,
                            'original_width': _original_w,
                            'original_height': _original_h,
                        }

                    if size_bytes > DISCORD_IMAGE_MAX_BYTES:
                        size_mb = size_bytes / (1024 * 1024)
                        msg = f"Discord image too large ({size_mb:.1f} MB > 1 MB limit), skipping upload"
                        app_logger.warning(msg)
                        self.last_send_status = f"Skipped: Image too large ({size_mb:.1f} MB)"
                        from .posthog_service import capture_event
                        if _discord_image_stats:
                            _discord_image_stats['skipped_too_large'] = True
                            capture_event('discord_image_sent', _discord_image_stats)
                        return False  # finally block handles img_buf.close()

                    filename = os.path.splitext(os.path.basename(image_path))[0] + ".jpg"
                    files = {
                        "file": (filename, img_buf, "image/jpeg")
                    }

                    # Add image reference to embed
                    embed["image"] = {"url": f"attachment://{filename}"}

                    response = self._post_with_retry(
                        webhook_url,
                        data={"payload_json": json.dumps(payload)},
                        files=files,
                        timeout=10
                    )
                finally:
                    img_buf.close()
            else:
                # Send text-only message
                if image_path:
                    if not isinstance(image_path, (str, bytes, os.PathLike)):
                        app_logger.warning(f"Discord image_path is not a valid path type: {type(image_path).__name__}")
                    elif not os.path.exists(image_path):
                        app_logger.warning(f"Discord image path doesn't exist: {image_path}")
                app_logger.debug("Sending text-only Discord message")
                response = self._post_with_retry(
                    webhook_url,
                    json=payload,
                    timeout=10
                )
            
            # Check response
            if response.status_code in [200, 204]:
                self.last_send_time = datetime.now()
                self.last_send_status = f"Success (HTTP {response.status_code})"
                app_logger.info(f"Discord alert sent: {title}")
                if _discord_image_stats:
                    from .posthog_service import capture_event
                    _discord_image_stats['skipped_too_large'] = False
                    capture_event('discord_image_sent', _discord_image_stats)
                return True
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_detail = response.json()
                    error_msg += f" - {error_detail}"
                except Exception:
                    error_msg += f" - {response.text[:100]}"
                
                self.last_send_status = f"Failed: {error_msg}"
                app_logger.error(f"Discord webhook failed: {error_msg}")
                return False
                
        except requests.exceptions.Timeout:
            self.last_send_status = "Failed: Request timeout"
            app_logger.error("Discord webhook timeout")
            return False
            
        except requests.exceptions.ConnectionError as e:
            self.last_send_status = "Failed: Connection error"
            app_logger.error(f"Discord webhook connection error: {redact_discord_error(e)}")
            return False

        except Exception as e:
            err = redact_discord_error(e)
            self.last_send_status = f"Failed: {err}"
            app_logger.error(f"Discord webhook error: {err}")
            return False

    def send_startup_message(self):
        """Send application startup notification"""
        discord_config = self.config.get('discord', {})
        
        if not discord_config.get('post_startup_shutdown', False):
            return False
        
        # Get current mode
        mode = self.config.get('capture_mode', 'watch')
        mode_text = "Directory Watch" if mode == 'watch' else "ZWO Camera Capture"
        
        # Get output path
        output_path = self.config.get('output_directory', 'Not configured')
        
        description = f"""**Mode:** {mode_text}
**Started:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Output Path:** {output_path}

Ready to process images."""
        
        return self.send_discord_message(
            f"🚀 {APP_DISPLAY_NAME} Started",
            description,
            level="success"
        )
    
    def send_shutdown_message(self):
        """Send application shutdown notification"""
        discord_config = self.config.get('discord', {})
        
        if not discord_config.get('post_startup_shutdown', False):
            return False
        
        description = f"""**Stopped:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Application has been closed."""
        
        return self.send_discord_message(
            f"🛑 {APP_DISPLAY_NAME} Stopped",
            description,
            level="info"
        )
    
    def send_capture_started_message(self):
        """Send capture started notification"""
        discord_config = self.config.get('discord', {})
        
        if not discord_config.get('post_startup_shutdown', False):
            return False
        
        # Get current mode
        mode = self.config.get('capture_mode', 'watch')
        mode_text = "Directory Watch" if mode == 'watch' else "ZWO Camera Capture"
        
        # Get output path
        output_path = self.config.get('output_directory', 'Not configured')
        
        description = f"""**Mode:** {mode_text}
**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Output Path:** {output_path}

Ready to process images."""
        
        return self.send_discord_message(
            f"🚀 Capture Started",
            description,
            level="info"
        )
    
    def send_error_message(self, error_text):
        """Send error notification"""
        discord_config = self.config.get('discord', {})
        
        if not discord_config.get('post_errors', False):
            return False
        
        # Truncate very long error messages
        if len(error_text) > 1000:
            error_text = error_text[:1000] + "..."
        
        description = f"""**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

```
{error_text}
```"""
        
        return self.send_discord_message(
            "❌ Error Detected",
            description,
            level="error"
        )
    
    def send_roof_status_change(self, roof_open: bool, confidence: float, image_path=None):
        """Send notification when ML confirms a roof status change (2 consecutive frames)."""
        discord_config = self.config.get('discord', {})
        if not discord_config.get('post_roof_changes', False):
            return False

        status = "Open" if roof_open else "Closed"
        emoji = "🔓" if roof_open else "🔒"
        description = (
            f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"Roof is now **{status}** (confidence: {confidence:.0%})"
        )
        img = image_path if image_path and os.path.exists(image_path) else None
        return self.send_discord_message(
            f"{emoji} Roof {status}",
            description,
            level="warning" if not roof_open else "info",
            image_path=img,
        )

    def send_periodic_update(self, latest_image_path=None):
        """Send periodic image update"""
        discord_config = self.config.get('discord', {})
        
        if not discord_config.get('periodic_enabled', False):
            return False
        
        # Get stats
        description = f"""**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Latest sky capture from {APP_DISPLAY_NAME}."""
        
        # Determine image path
        image_to_send = None
        if discord_config.get('include_latest_image', True) and latest_image_path:
            if os.path.exists(latest_image_path):
                image_to_send = latest_image_path
            else:
                app_logger.warning(f"Latest image not found: {latest_image_path}")
        
        return self.send_discord_message(
            "📸 Periodic AllSky Update",
            description,
            level="info",
            image_path=image_to_send
        )
    
    def send_timelapse_completed(self, video_path: str, frame_count: int, elapsed_seconds: int):
        """
        Post a timelapse-completed notification.

        Attaches the MP4 file if it exists and is ≤ 8 MB (Discord free-tier
        limit).  If the file is too large, posts a text-only message with the
        file size noted so the user knows where to find it.
        """
        if not self.is_enabled():
            return False
        if not self.config.get('discord', {}).get('post_timelapse', False):
            return False

        h, rem = divmod(elapsed_seconds, 3600)
        m, s = divmod(rem, 60)
        filename = os.path.basename(video_path) if video_path else 'timelapse.mp4'

        description = (
            f"**{frame_count}** frames · {h:02d}:{m:02d}:{s:02d} session\n"
            f"`{filename}`"
        )

        # Try to attach the video if it fits within Discord's free-tier limit
        attach_path = None
        DISCORD_MAX_BYTES = 8 * 1024 * 1024  # 8 MB
        if video_path and os.path.isfile(video_path):
            size = os.path.getsize(video_path)
            if size <= DISCORD_MAX_BYTES:
                attach_path = video_path
            else:
                size_mb = size / (1024 * 1024)
                description += f"\n\n*Video too large to attach ({size_mb:.1f} MB > 8 MB limit)*"

        return self._send_with_video(
            "🎬 Timelapse Complete", description, attach_path
        )

    def send_calibration_complete(self, model_info: dict):
        """
        Post an all-sky calibration-complete notification.

        model_info keys: rms_residual, n_matches, calibrated_at, a1, cx, cy.
        """
        if not self.is_enabled():
            return False
        if not self.config.get('discord', {}).get('post_calibration', False):
            return False

        rms = model_info.get('rms_residual', 0)
        n = model_info.get('n_matches', 0)
        ts = (model_info.get('calibrated_at', '') or '')[:10]
        description = (
            f"All-sky lens calibrated successfully.\n"
            f"**Stars matched:** {n}\n"
            f"**RMS residual:** {rms:.2f} px\n"
            f"**Date:** {ts}"
        )
        return self.send_discord_message(
            "All-Sky Calibration Complete", description, level="info"
        )

    def _send_with_video(self, title: str, description: str, video_path=None):
        """
        Internal helper: send an embed, optionally attaching an MP4 file.

        Unlike send_discord_message() which embeds images inline, video files
        are sent as plain multipart attachments — Discord renders them as an
        inline player automatically.
        """
        if not self.is_enabled():
            return False

        discord_config = self.config.get('discord', {})
        webhook_url = discord_config.get('webhook_url', '')
        if not webhook_url:
            return False

        try:
            username = discord_config.get('username_override', '') or APP_DISPLAY_NAME
            avatar_url = discord_config.get('avatar_url', '')

            embed = {
                "title": title,
                "description": description,
                "color": self.get_color_int(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "footer": {"text": "✅ SUCCESS"},
            }

            payload = {"username": username, "embeds": [embed]}
            if avatar_url:
                payload["avatar_url"] = avatar_url

            if video_path and os.path.isfile(video_path):
                app_logger.debug(f"Attaching video to Discord: {video_path}")
                with open(video_path, "rb") as fh:
                    files = {"file": (os.path.basename(video_path), fh, "video/mp4")}
                    response = self._post_with_retry(
                        webhook_url,
                        data={"payload_json": json.dumps(payload)},
                        files=files,
                        timeout=120,  # Video upload needs generous timeout
                    )
            else:
                response = self._post_with_retry(webhook_url, json=payload, timeout=10)

            if response.status_code in [200, 204]:
                self.last_send_time = datetime.now()
                self.last_send_status = f"Success (HTTP {response.status_code})"
                app_logger.info(f"Discord alert sent: {title}")
                return True
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_msg += f" - {response.json()}"
                except Exception:
                    error_msg += f" - {response.text[:100]}"
                self.last_send_status = f"Failed: {error_msg}"
                app_logger.error(f"Discord webhook failed: {error_msg}")
                return False

        except requests.exceptions.Timeout:
            self.last_send_status = "Failed: Request timeout"
            app_logger.error("Discord webhook timeout (video upload)")
            return False
        except Exception as e:
            err = redact_discord_error(e)
            self.last_send_status = f"Failed: {err}"
            app_logger.error(f"Discord webhook error: {err}")
            return False

    def get_last_status(self):
        """Get formatted last send status"""
        if self.last_send_time:
            time_str = self.last_send_time.strftime('%H:%M:%S')
            return f"Last message: {time_str} – {self.last_send_status}"
        else:
            return "No messages sent yet"
