"""
Discord webhook integration for alerts and notifications
"""
import os
import json
import requests
from datetime import datetime
from .logger import app_logger
from app_config import APP_DISPLAY_NAME


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
                "timestamp": datetime.utcnow().isoformat()
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
            
            if valid_image_path:
                # Send with image attachment
                app_logger.debug(f"Attaching image to Discord: {image_path}")
                files = {
                    "file": (os.path.basename(image_path), open(image_path, "rb"), "image/jpeg")
                }
                
                # Add image reference to embed
                embed["image"] = {"url": f"attachment://{os.path.basename(image_path)}"}
                
                response = requests.post(
                    webhook_url,
                    data={"payload_json": json.dumps(payload)},
                    files=files,
                    timeout=10
                )
                
                files["file"][1].close()  # Close file handle
            else:
                # Send text-only message
                if image_path:
                    if not isinstance(image_path, (str, bytes, os.PathLike)):
                        app_logger.warning(f"Discord image_path is not a valid path type: {type(image_path).__name__}")
                    elif not os.path.exists(image_path):
                        app_logger.warning(f"Discord image path doesn't exist: {image_path}")
                app_logger.debug("Sending text-only Discord message")
                response = requests.post(
                    webhook_url,
                    json=payload,
                    timeout=10
                )
            
            # Check response
            if response.status_code in [200, 204]:
                self.last_send_time = datetime.now()
                self.last_send_status = f"Success (HTTP {response.status_code})"
                app_logger.info(f"Discord alert sent: {title}")
                return True
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_detail = response.json()
                    error_msg += f" - {error_detail}"
                except:
                    error_msg += f" - {response.text[:100]}"
                
                self.last_send_status = f"Failed: {error_msg}"
                app_logger.error(f"Discord webhook failed: {error_msg}")
                return False
                
        except requests.exceptions.Timeout:
            self.last_send_status = "Failed: Request timeout"
            app_logger.error("Discord webhook timeout")
            return False
            
        except requests.exceptions.ConnectionError as e:
            self.last_send_status = f"Failed: Connection error"
            app_logger.error(f"Discord webhook connection error: {e}")
            return False
            
        except Exception as e:
            self.last_send_status = f"Failed: {str(e)[:50]}"
            app_logger.error(f"Discord webhook error: {e}")
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
    
    def get_last_status(self):
        """Get formatted last send status"""
        if self.last_send_time:
            time_str = self.last_send_time.strftime('%H:%M:%S')
            return f"Last message: {time_str} – {self.last_send_status}"
        else:
            return "No messages sent yet"
