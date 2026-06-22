"""
Shared icon helpers.

Panels should use ``mdi()`` for Material Design Icon 6 glyphs instead of
reaching for ``qtawesome`` directly, so the color/theming stays consistent
with the nav rail.
"""
import os
import qtawesome as qta
from PySide6.QtGui import QIcon

from .tokens import Colors

_WINDOWS_FONT_DIR_READY = False


def _ensure_windows_font_dir():
    global _WINDOWS_FONT_DIR_READY
    if _WINDOWS_FONT_DIR_READY or os.name != "nt":
        return
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return
    try:
        os.makedirs(os.path.join(local_app_data, "Microsoft", "Windows", "Fonts"), exist_ok=True)
    except OSError:
        return
    _WINDOWS_FONT_DIR_READY = True


def mdi(name: str, color: str = None):
    """Material Design Icon 6 icon. Defaults to the muted-secondary app color."""
    try:
        _ensure_windows_font_dir()
        return qta.icon(f'mdi6.{name}', color=color or Colors.text_secondary)
    except Exception:
        return QIcon()
