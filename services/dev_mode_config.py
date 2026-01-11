"""
Development Mode Configuration

Controls access to dev/debugging features that should be disabled in production builds.
"""
import os

# === DEVELOPMENT MODE FLAG ===
# Set to False for production builds to disable:
# - Raw debug file saving (FITS/TIFF files)
# - Calibration JSON exports
# - ML prediction integration
# - Other experimental features
#
# RAW16 camera mode remains available regardless of this flag (user-facing feature).
DEV_MODE_AVAILABLE = False  # Set to False before building release

# Environment variable override for easy testing
# PFRSENTINEL_DEV_MODE=1 to force enable, =0 to force disable
env_override = os.getenv('PFRSENTINEL_DEV_MODE')
if env_override == '0':
    DEV_MODE_AVAILABLE = False
elif env_override == '1':
    DEV_MODE_AVAILABLE = True


def is_dev_mode_available() -> bool:
    """Check if development mode features are available in this build."""
    return DEV_MODE_AVAILABLE


def get_dev_mode_status_message() -> str:
    """Get human-readable status message for dev mode availability."""
    if DEV_MODE_AVAILABLE:
        return "Development features enabled (not a production build)"
    return "Development features disabled (production build)"
