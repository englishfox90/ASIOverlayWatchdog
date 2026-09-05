"""
Shared gate for sky-observation-dependent features.

Used by star detection and the all-sky overlay: both only make sense when
the sun is below civil twilight and (if ML roof detection is running) the
roof is actually open.
"""
from datetime import datetime, timezone

from .logger import app_logger

_CACHE_KEY = '_observing_window'


def is_observing_window(config, metadata, feature="feature"):
    """Return True when it is safe to run sky-dependent image analysis.

    Primary gate: sun must be below civil twilight (-6°). Requires
    weather.latitude and weather.longitude to be configured.

    Secondary gate: if ML is enabled, roof is predicted Closed, and
    ml_models.roof_gates_sky_features is True (default), skip. Rigs with no
    roof at all (e.g. open-air all-sky cameras) can set that flag False to
    keep sky-condition ML while dropping the roof-based suppression.

    Falls through (returns True) if location is not configured or astral
    is unavailable, so features degrade gracefully.

    Result is cached on ``metadata`` so multiple callers in a single frame
    (e.g. star detection + all-sky overlay) share one astral computation.

    Args:
        config: Application config dict.
        metadata: Frame metadata dict. May contain 'ROOF_STATUS' populated
            by the ML service ("Open (95%)" / "Closed (98%)" / "N/A").
        feature: Short label used in debug log messages.
    """
    cached = metadata.get(_CACHE_KEY)
    if cached is not None:
        return cached

    result = _evaluate(config, metadata, feature)
    metadata[_CACHE_KEY] = result
    return result


def _evaluate(config, metadata, feature):
    weather_cfg = config.get('weather', {})
    lat = weather_cfg.get('latitude', '')
    lon = weather_cfg.get('longitude', '')

    if lat and lon:
        try:
            from astral import LocationInfo
            from astral.sun import elevation

            loc = LocationInfo(latitude=float(lat), longitude=float(lon))
            sun_alt = elevation(loc.observer, dateandtime=datetime.now(tz=timezone.utc))
            if sun_alt > -6.0:
                app_logger.debug(
                    f"{feature} suppressed: sun elevation {sun_alt:.1f}° "
                    f"(above civil twilight -6°)"
                )
                return False
        except Exception as e:
            app_logger.debug(f"Sun elevation check failed, allowing {feature}: {e}")

    ml_config = config.get('ml_models', {})
    if ml_config.get('enabled', False) and ml_config.get('roof_gates_sky_features', True):
        roof_status = metadata.get('ROOF_STATUS', 'N/A')
        if roof_status.startswith('Closed'):
            app_logger.debug(f"{feature} suppressed: ML roof status '{roof_status}'")
            return False

    return True
