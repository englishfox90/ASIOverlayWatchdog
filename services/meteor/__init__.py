# services/meteor — meteor trail detection package
from .detector import MeteorDetection, detect_meteors, annotate_image
from .frame_stack import FrameStack
from .noise import DiffNoiseEMA, estimate_diff_noise, noise_to_threshold
from .persistence import PersistenceFilter
from .streak_profile import sample_profile, dash_score, dash_count, peak_fade_score
from .detection_scale import DetectionScale, make_scale
from .mask import ExclusionZone, apply_exclusion_zones, zone_from_detection, zones_from_config, zones_to_config
from .storage import log_detections, log_event, save_thumbnail

__all__ = [
    "MeteorDetection", "detect_meteors", "annotate_image",
    "FrameStack",
    "DiffNoiseEMA", "estimate_diff_noise", "noise_to_threshold",
    "PersistenceFilter",
    "sample_profile", "dash_score", "dash_count", "peak_fade_score",
    "DetectionScale", "make_scale",
    "ExclusionZone", "apply_exclusion_zones", "zone_from_detection",
    "zones_from_config", "zones_to_config",
    "log_detections", "log_event", "save_thumbnail",
]
