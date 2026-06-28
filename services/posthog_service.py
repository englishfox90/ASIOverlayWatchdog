"""
PostHog analytics service for PFR Sentinel.
Provides observability and usage tracking.

Each installation gets a random anonymous UUID stored in config.
No personal data is collected — just a stable ID to correlate events.
Users can opt out via Settings > System > "Send anonymous usage data".
"""
import uuid
import traceback
from posthog import Posthog
from .config import Config
from .logger import app_logger

# Shared across analytics events and log forwarding (see posthog_logs.py).
PROJECT_API_KEY = 'phc_yZQPicEvLtuwo4ws6uMCX2RuLc23fsJVbrh7PdSBggyt'
POSTHOG_HOST = 'https://us.i.posthog.com'

posthog = Posthog(
    project_api_key=PROJECT_API_KEY,
    host=POSTHOG_HOST,
    enable_exception_autocapture=True,
)

# Patch exception autocapture to use our stored distinct_id instead of random UUIDs.
# The SDK generates a new uuid4() for each autocaptured exception when no distinct_id
# is set, which creates orphan persons in PostHog.
_original_capture_exception = posthog.capture_exception

def _patched_capture_exception(exception, **kwargs):
    if 'distinct_id' not in kwargs or kwargs['distinct_id'] is None:
        kwargs['distinct_id'] = get_distinct_id()
    return _original_capture_exception(exception, **kwargs)

posthog.capture_exception = _patched_capture_exception

_distinct_id = None
_opted_out = None

# Respect opt-out at import time (disables autocapture too)
def _init_opt_out():
    config = Config()
    config.load()
    if not config.get('analytics_enabled', True):
        posthog.disabled = True

_init_opt_out()


def is_enabled():
    """Check if analytics is enabled (user has not opted out)."""
    global _opted_out
    if _opted_out is None:
        config = Config()
        config.load()
        _opted_out = not config.get('analytics_enabled', True)
    return not _opted_out


def set_enabled(enabled: bool):
    """Update the opt-out state. Called when the user toggles the setting."""
    global _opted_out
    _opted_out = not enabled
    posthog.disabled = not enabled


def get_distinct_id():
    """Return a stable anonymous ID for this installation, creating one if needed."""
    global _distinct_id
    if _distinct_id:
        return _distinct_id
    config = Config()
    config.load()
    _distinct_id = config.get('posthog_distinct_id')
    if not _distinct_id:
        _distinct_id = str(uuid.uuid4())
        config.set('posthog_distinct_id', _distinct_id)
        config.save()
    return _distinct_id


def capture_event(event: str, properties: dict = None):
    """Send an analytics event. Silently swallows errors to never affect the app."""
    if not is_enabled():
        return
    try:
        posthog.capture(
            distinct_id=get_distinct_id(),
            event=event,
            properties=properties or {},
        )
    except Exception:
        app_logger.debug(f"PostHog event '{event}' failed (non-critical)")


def capture_error(exception: Exception, context: str = None):
    """Capture a caught exception with stack trace and optional context."""
    if not is_enabled():
        return
    try:
        props = {
            'error_type': type(exception).__name__,
            'error_message': str(exception),
            'stack_trace': traceback.format_exc(),
        }
        if context:
            props['context'] = context
        capture_event('error_captured', props)
    except Exception:
        pass
