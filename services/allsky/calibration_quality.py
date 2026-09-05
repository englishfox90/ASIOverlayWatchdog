"""
Calibration quality levels and the metric → level mapping.

Extracted from calibration_service.py (which re-exports both names for its
existing callers). Pure: no Qt, no I/O.
"""
from typing import Optional

from .fisheye import FisheyeModel


class CalibrationQuality:
    """
    Calibration quality levels with display metadata.

    Each level has a value string, numeric rank (for comparison), a
    user-facing description, and background/text colour pair for the UI
    badge (dark-theme palette).
    """

    # (value, rank, description, badge_bg, badge_text)
    _LEVELS = {
        'none':        (0, 'Not calibrated',
                        '#1E1E1E', '#706F6A'),
        'preliminary': (1, 'Single image — rough overlay',
                        '#2D2305', '#FFD166'),
        'acceptable':  (2, 'Multi-image — improving',
                        '#2D1A05', '#FF9F43'),
        'good':        (3, 'Multi-image — accurate',
                        '#132D21', '#3DD68C'),
        'excellent':   (4, 'Long baseline — best accuracy',
                        '#0D2D1A', '#4ADE80'),
    }

    NONE        = 'none'
    PRELIMINARY = 'preliminary'
    ACCEPTABLE  = 'acceptable'
    GOOD        = 'good'
    EXCELLENT   = 'excellent'

    ALL = (NONE, PRELIMINARY, ACCEPTABLE, GOOD, EXCELLENT)

    @classmethod
    def rank(cls, value: str) -> int:
        return cls._LEVELS.get(value, cls._LEVELS['none'])[0]

    @classmethod
    def description(cls, value: str) -> str:
        return cls._LEVELS.get(value, cls._LEVELS['none'])[1]

    @classmethod
    def badge_colors(cls, value: str) -> tuple:
        """Return (background_hex, text_hex) for the UI badge."""
        entry = cls._LEVELS.get(value, cls._LEVELS['none'])
        return entry[2], entry[3]


def model_quality(
    model: Optional[FisheyeModel],
    n_images: int = 1,
    span_minutes: float = 0.0,
) -> str:
    """
    Assess calibration quality from model metrics.

    Returns one of the CalibrationQuality level strings:
    'none', 'preliminary', 'acceptable', 'good', 'excellent'.
    """
    if model is None or not model.is_valid():
        return CalibrationQuality.NONE
    rms = model.rms_residual
    n = model.n_matches
    if n_images >= 20 and span_minutes >= 60 and rms <= 8.0:
        return CalibrationQuality.EXCELLENT
    if n_images >= 10 and n >= 100 and rms <= 12.0:
        return CalibrationQuality.GOOD
    if n_images >= 3 and n >= 30 and rms <= 15.0:
        return CalibrationQuality.ACCEPTABLE
    return CalibrationQuality.PRELIMINARY
