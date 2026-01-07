"""
ML Prediction integration for Dev Mode

Provides roof state predictions from the trained ML model to include
in calibration JSON files for validation and monitoring.
"""
import os
from pathlib import Path
from typing import Optional
import numpy as np

from services.logger import app_logger

# Try to import the roof classifier
ML_AVAILABLE = False
_classifier = None
_classifier_error = None

def _init_classifier():
    """Initialize the classifier singleton on first use."""
    global ML_AVAILABLE, _classifier, _classifier_error
    
    if _classifier is not None:
        return True
    
    if _classifier_error is not None:
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
            _classifier_error = "No model file found"
            app_logger.warning(f"ML Prediction: {_classifier_error}")
            return False
        
        _classifier = RoofClassifier.load(str(model_path))
        ML_AVAILABLE = True
        app_logger.info(f"ML Prediction: Loaded roof classifier from {model_path.name}")
        return True
        
    except ImportError as e:
        _classifier_error = f"Import error: {e}"
        app_logger.warning(f"ML Prediction: {_classifier_error}")
        return False
    except Exception as e:
        _classifier_error = f"Load error: {e}"
        app_logger.error(f"ML Prediction: {_classifier_error}")
        return False


def predict_roof_state(
    image_array: np.ndarray,
    corner_analysis: dict,
    time_context: dict,
) -> Optional[dict]:
    """
    Run ML model prediction on captured image.
    
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
    if not _init_classifier():
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
        result = _classifier.predict(image_array, metadata)
        
        return {
            'roof_open': bool(result.roof_open),  # Ensure native bool for JSON
            'confidence': round(float(result.confidence), 4),
            'raw_logit': round(float(result.raw_logit), 4),
            'model_version': 'roof_classifier_v1',
        }
        
    except Exception as e:
        app_logger.error(f"ML Prediction failed: {e}")
        return None


def get_ml_status() -> dict:
    """
    Get ML prediction system status.
    
    Returns:
        Dict with availability and error info
    """
    _init_classifier()  # Try to init if not done
    
    return {
        'available': ML_AVAILABLE,
        'error': _classifier_error,
        'model_loaded': _classifier is not None,
    }
