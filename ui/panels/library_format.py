"""
Display formatting shared by the Library views (presentation only).

All epochs are the PC's local time — the library stores local time end to end,
so these never convert time zones.
"""
from datetime import datetime


def _dt(epoch):
    return datetime.fromtimestamp(int(epoch))


def fmt_full(epoch):
    """'YYYY-MM-DD HH:MM:SS' for a capture epoch, or '—'."""
    try:
        return _dt(epoch).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return "—"


def fmt_clock(epoch):
    """'HH:MM' for a capture epoch, or '—'."""
    try:
        return _dt(epoch).strftime("%H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return "—"


def fmt_time_seconds(epoch):
    """'HH:MM:SS' for a capture epoch, or '—'."""
    try:
        return _dt(epoch).strftime("%H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return "—"


def fmt_temp_c(value):
    """'14.2°C' from a Celsius float, or None."""
    if value is None:
        return None
    try:
        return f"{float(value):.1f}°C"
    except (TypeError, ValueError):
        return None


def fmt_gap(seconds):
    """Human gap length: '28-min gap' or '1h 12m gap'."""
    seconds = int(seconds or 0)
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}-min gap"
    return f"{minutes // 60}h {minutes % 60:02d}m gap"


def fmt_exposure(value):
    """Exposure in seconds rounded to 2 dp: '0.46 s' from '0.456198…' or '0.46s'."""
    if value is None:
        return "—"
    raw = str(value).strip().lower().rstrip("s").strip()
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return str(value)
    return f"{seconds:.2f} s"


def fmt_clouds(value):
    """'45%' from a cloud-cover int/str, or '—'."""
    if value is None:
        return "—"
    try:
        return f"{int(value)}%"
    except (TypeError, ValueError):
        return str(value)


def fmt_duration(seconds):
    """Compact span like '10h 0m'."""
    seconds = int(seconds or 0)
    minutes = seconds // 60
    return f"{minutes // 60}h {minutes % 60:02d}m"
