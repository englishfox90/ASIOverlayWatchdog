"""
ML Prediction integration for Dev Mode

Provides roof state and sky condition predictions from trained ML models 
to include in calibration JSON files for validation and monitoring.

PRODUCTION BUILD: ML features disabled if DEV_MODE_AVAILABLE=False

Usage:
    from ui.controllers.ml_prediction import predict_roof_state, predict_sky_condition
    
    # Roof prediction (always run)
    roof_result = predict_roof_state(image_array, corner_analysis, time_context)
    
    # Sky prediction (only run when roof is open)
    if roof_result and roof_result['roof_open']:
        sky_result = predict_sky_condition(image_array, corner_analysis, time_context, moon_context)
"""
import os
from pathlib import Path
from typing import Optional
import numpy as np

from services.logger import app_logger
from services.dev_mode_config import is_dev_mode_available

# ============================================================================
# Roof Classifier
# ============================================================================

_roof_classifier = None
_roof_classifier_error = None
ROOF_ML_AVAILABLE = False

def _init_roof_classifier():
    """Initialize the roof classifier singleton on first use."""
    global ROOF_ML_AVAILABLE, _roof_classifier, _roof_classifier_error
    
    # PRODUCTION BUILD: Disable ML features if not in dev mode
    if not is_dev_mode_available():
        _roof_classifier_error = "ML features disabled in production build (DEV_MODE_AVAILABLE=False)"
        return False
    
    if _roof_classifier is not None:
        return True
    
    if _roof_classifier_error is not None:
        return False  # Already tried and failed
    
    try:
        from ml.roof_classifier import RoofClassifier
        
        # Look for model file
        model_paths = [
            Path(__file__).parent.parent.parent / "ml" / "models" / "roof_classifier_v1.pth",
            Path(__file__).parent.parent.parent / "ml" / "models" / "roof_classifier_v1.onnx",
        ]
        
        model_path = None
        for p in model_paths:
            if p.exists():
                model_path = p
                break
        
        if model_path is None:
            _roof_classifier_error = "No roof model file found"
            app_logger.warning(f"ML Prediction: {_roof_classifier_error}")
            return False
        
        _roof_classifier = RoofClassifier.load(str(model_path))
        ROOF_ML_AVAILABLE = True
        app_logger.info(f"ML Prediction: Loaded roof classifier from {model_path.name}")
        return True
        
    except ImportError as e:
        _roof_classifier_error = f"Import error: {e}"
        app_logger.warning(f"ML Prediction (roof): {_roof_classifier_error}")
        return False
    except Exception as e:
        _roof_classifier_error = f"Load error: {e}"
        app_logger.error(f"ML Prediction (roof): {_roof_classifier_error}")
        return False


# ============================================================================
# Sky Classifier
# ============================================================================

_sky_classifier = None
_sky_classifier_error = None
SKY_ML_AVAILABLE = False

def _init_sky_classifier():
    """Initialize the sky classifier singleton on first use."""
    global SKY_ML_AVAILABLE, _sky_classifier, _sky_classifier_error
    
    # PRODUCTION BUILD: Disable ML features if not in dev mode
    if not is_dev_mode_available():
        _sky_classifier_error = "ML features disabled in production build (DEV_MODE_AVAILABLE=False)"
        return False
    
    if _sky_classifier is not None:
        return True
    
    if _sky_classifier_error is not None:
        return False  # Already tried and failed
    
    try:
        from ml.sky_classifier import SkyClassifier
        
        model_path = Path(__file__).parent.parent.parent / "ml" / "models" / "sky_classifier_v1.pth"
        
        if not model_path.exists():
            _sky_classifier_error = "No sky model file found"
            app_logger.warning(f"ML Prediction: {_sky_classifier_error}")
            return False
        
        _sky_classifier = SkyClassifier.load(str(model_path))
        SKY_ML_AVAILABLE = True
        app_logger.info(f"ML Prediction: Loaded sky classifier from {model_path.name}")
        return True
        
    except ImportError as e:
        _sky_classifier_error = f"Import error: {e}"
        app_logger.warning(f"ML Prediction (sky): {_sky_classifier_error}")
        return False
    except Exception as e:
        _sky_classifier_error = f"Load error: {e}"
        app_logger.error(f"ML Prediction (sky): {_sky_classifier_error}")
        return False


# ============================================================================
# Prediction Functions
# ============================================================================

def predict_roof_state(
    image_array: np.ndarray,
    corner_analysis: dict,
    time_context: dict,
) -> Optional[dict]:
    """
    Run ML model prediction on captured image for roof state.
    
    Args:
        image_array: Raw image array (grayscale or RGB)
        corner_analysis: Dict with corner_to_center_ratio, etc from image analysis
        time_context: Dict with is_astronomical_night, hour, etc
        
    Returns:
        Dict with prediction results, or None if ML not available:
        {
            'roof_open': bool,
            'confidence': float,
            'raw_logit': float,
            'model_version': str,
        }
    """
    if not _init_roof_classifier():
        return None
    
    try:
        # Build metadata dict for model
        metadata = {
            'corner_to_center_ratio': corner_analysis.get('corner_to_center_ratio', 1.0),
            'median_lum': corner_analysis.get('center_med', 0.0),  # Use center median as proxy
            'is_astronomical_night': time_context.get('is_astronomical_night', False),
            'hour': time_context.get('hour', 12),
        }
        
        # Run prediction
        result = _roof_classifier.predict(image_array, metadata)
        
        return {
            'roof_open': bool(result.roof_open),  # Ensure native bool for JSON
            'confidence': round(float(result.confidence), 4),
            'raw_logit': round(float(result.raw_logit), 4),
            'model_version': 'roof_classifier_v1',
        }
        
    except Exception as e:
        app_logger.error(f"ML Prediction (roof) failed: {e}")
        return None


def predict_sky_condition(
    image_array: np.ndarray,
    corner_analysis: dict,
    time_context: dict,
    moon_context: Optional[dict] = None,
) -> Optional[dict]:
    """
    Run ML model prediction on captured image for sky condition.
    
    IMPORTANT: Only call this when roof is OPEN. The sky classifier is trained
    on pier camera images which can only see the sky when the roof is open.
    
    Args:
        image_array: Raw image array (grayscale or RGB)
        corner_analysis: Dict with corner_to_center_ratio, median_lum, etc
        time_context: Dict with is_astronomical_night, hour, etc
        moon_context: Dict with moon_illumination, moon_is_up, etc (optional)
        
    Returns:
        Dict with prediction results, or None if ML not available:
        {
            'sky_condition': str,  # Clear, Mostly Clear, Partly Cloudy, etc
            'sky_confidence': float,
            'sky_probabilities': dict,
            'stars_visible': bool,
            'stars_confidence': float,
            'star_density': float,
            'moon_visible': bool,
            'moon_confidence': float,
            'model_version': str,
        }
    """
    if not _init_sky_classifier():
        return None
    
    try:
        # Build metadata dict for model (6 features)
        moon_context = moon_context or {}
        
        metadata = {
            'corner_to_center_ratio': corner_analysis.get('corner_to_center_ratio', 1.0),
            'median_lum': corner_analysis.get('center_med', 0.0),
            'is_astronomical_night': time_context.get('is_astronomical_night', False),
            'hour': time_context.get('hour', 12),
            'moon_illumination': moon_context.get('illumination_pct', 0.0),
            'moon_is_up': moon_context.get('moon_is_up', False),
        }
        
        # Run prediction
        result = _sky_classifier.predict(image_array, metadata)
        
        return {
            'sky_condition': result.sky_condition,
            'sky_confidence': round(float(result.sky_confidence), 4),
            'sky_probabilities': {k: round(v, 4) for k, v in result.sky_probabilities.items()},
            'stars_visible': bool(result.stars_visible),
            'stars_confidence': round(float(result.stars_confidence), 4),
            'star_density': round(float(result.star_density), 4),
            'moon_visible': bool(result.moon_visible),
            'moon_confidence': round(float(result.moon_confidence), 4),
            'model_version': 'sky_classifier_v1',
        }
        
    except Exception as e:
        app_logger.error(f"ML Prediction (sky) failed: {e}")
        return None


def get_ml_status() -> dict:
    """
    Get ML prediction system status.
    
    Returns:
        Dict with availability and error info for both models
    """
    _init_roof_classifier()  # Try to init if not done
    _init_sky_classifier()
    
    return {
        'roof_classifier': {
            'available': ROOF_ML_AVAILABLE,
            'error': _roof_classifier_error,
            'model_loaded': _roof_classifier is not None,
        },
        'sky_classifier': {
            'available': SKY_ML_AVAILABLE,
            'error': _sky_classifier_error,
            'model_loaded': _sky_classifier is not None,
        },
    }


# Legacy alias for backward compatibility
ML_AVAILABLE = property(lambda self: ROOF_ML_AVAILABLE)
