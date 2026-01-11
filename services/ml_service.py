"""
ML Service - Observatory Condition Classification

Provides ML-based image analysis for:
1. Roof State Classification - Detects if observatory roof is open/closed
2. Sky Condition Classification - Detects sky conditions when roof is open

This service is available independent of Dev Mode and can be enabled via
the "ML Models (Beta)" setting in Image Processing settings.

Usage:
    from services.ml_service import MLService
    
    ml = MLService()
    ml.initialize()
    
    # Get predictions for an image
    results = ml.analyze_image(image_array, metadata)
    
    # Results include:
    # - roof_status: "Open" | "Closed" | "N/A"
    # - roof_confidence: 0.0-1.0
    # - sky_condition: "Clear" | "Mostly Clear" | "Partly Cloudy" | etc | "N/A"
    # - sky_confidence: 0.0-1.0
    # - stars_visible: True | False | None
    # - star_density: 0.0-1.0 | None
"""
import os
from pathlib import Path
from typing import Optional, Dict, Any
import numpy as np

from services.logger import app_logger


class MLService:
    """
    Singleton service for ML-based image analysis.
    
    Provides roof state and sky condition predictions for use in:
    - Overlay tokens ({ROOF_STATUS}, {SKY_CONDITION}, etc.)
    - Live monitoring display
    - Discord notifications
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._roof_classifier = None
        self._sky_classifier = None
        self._roof_error = None
        self._sky_error = None
        self._initialized = True
        self._models_loaded = False
        
        # Cache last prediction results for quick access
        self._last_results = {}
    
    def initialize(self) -> bool:
        """
        Initialize ML models.
        
        Returns:
            True if at least one model loaded successfully
        """
        roof_ok = self._init_roof_classifier()
        sky_ok = self._init_sky_classifier()
        
        self._models_loaded = roof_ok or sky_ok
        return self._models_loaded
    
    def _init_roof_classifier(self) -> bool:
        """Initialize roof classifier model."""
        if self._roof_classifier is not None:
            return True
        
        if self._roof_error is not None:
            return False
        
        try:
            from ml.roof_classifier import RoofClassifier
            
            # Look for model file
            model_paths = [
                Path(__file__).parent.parent / "ml" / "models" / "roof_classifier_v1.pth",
                Path(__file__).parent.parent / "ml" / "models" / "roof_classifier_v1.onnx",
            ]
            
            model_path = None
            for p in model_paths:
                if p.exists():
                    model_path = p
                    break
            
            if model_path is None:
                self._roof_error = "Roof model file not found"
                app_logger.warning(f"ML Service: {self._roof_error}")
                return False
            
            self._roof_classifier = RoofClassifier.load(str(model_path))
            app_logger.info(f"ML Service: Loaded roof classifier from {model_path.name}")
            return True
            
        except ImportError as e:
            self._roof_error = f"Import error: {e}"
            app_logger.warning(f"ML Service (roof): {self._roof_error}")
            return False
        except Exception as e:
            self._roof_error = f"Load error: {e}"
            app_logger.error(f"ML Service (roof): {self._roof_error}")
            return False
    
    def _init_sky_classifier(self) -> bool:
        """Initialize sky classifier model."""
        if self._sky_classifier is not None:
            return True
        
        if self._sky_error is not None:
            return False
        
        try:
            from ml.sky_classifier import SkyClassifier
            
            model_path = Path(__file__).parent.parent / "ml" / "models" / "sky_classifier_v1.pth"
            
            if not model_path.exists():
                self._sky_error = "Sky model file not found"
                app_logger.warning(f"ML Service: {self._sky_error}")
                return False
            
            self._sky_classifier = SkyClassifier.load(str(model_path))
            app_logger.info(f"ML Service: Loaded sky classifier from {model_path.name}")
            return True
            
        except ImportError as e:
            self._sky_error = f"Import error: {e}"
            app_logger.warning(f"ML Service (sky): {self._sky_error}")
            return False
        except Exception as e:
            self._sky_error = f"Load error: {e}"
            app_logger.error(f"ML Service (sky): {self._sky_error}")
            return False
    
    def is_available(self) -> bool:
        """Check if ML service has any models available."""
        return self._roof_classifier is not None or self._sky_classifier is not None
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get ML service status information.
        
        Returns:
            Dict with model availability and error info
        """
        return {
            'available': self.is_available(),
            'models_loaded': self._models_loaded,
            'roof_classifier': {
                'available': self._roof_classifier is not None,
                'error': self._roof_error,
            },
            'sky_classifier': {
                'available': self._sky_classifier is not None,
                'error': self._sky_error,
            },
        }
    
    def analyze_image(
        self,
        image_array: np.ndarray,
        metadata: Optional[Dict] = None,
        config: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Analyze image for observatory conditions.
        
        Args:
            image_array: Image as numpy array (grayscale or RGB)
            metadata: Optional image metadata (exposure, gain, etc.)
            config: ML models config dict with 'roof_classifier', 'sky_classifier' flags
        
        Returns:
            Dict with predictions:
            {
                'roof_status': str,  # "Open", "Closed", or "N/A"
                'roof_confidence': float,  # 0.0-1.0 or None
                'sky_condition': str,  # "Clear", "Mostly Clear", etc. or "N/A"
                'sky_confidence': float,  # 0.0-1.0 or None
                'stars_visible': bool or None,
                'star_density': float or None,  # 0.0-1.0
                'moon_visible': bool or None,
            }
        """
        config = config or {}
        metadata = metadata or {}
        
        results = {
            'roof_status': 'N/A',
            'roof_confidence': None,
            'sky_condition': 'N/A',
            'sky_confidence': None,
            'stars_visible': None,
            'star_density': None,
            'moon_visible': None,
        }
        
        # Build analysis context from image
        corner_analysis = self._compute_corner_analysis(image_array)
        time_context = self._compute_time_context()
        
        # Roof prediction
        roof_enabled = config.get('roof_classifier', True)
        if roof_enabled and self._roof_classifier is not None:
            try:
                roof_meta = {
                    'corner_to_center_ratio': corner_analysis.get('corner_to_center_ratio', 1.0),
                    'median_lum': corner_analysis.get('center_med', 0.0),
                    'is_astronomical_night': time_context.get('is_astronomical_night', False),
                    'hour': time_context.get('hour', 12),
                }
                
                roof_result = self._roof_classifier.predict(image_array, roof_meta)
                results['roof_status'] = 'Open' if roof_result.roof_open else 'Closed'
                results['roof_confidence'] = round(float(roof_result.confidence), 3)
                
            except Exception as e:
                app_logger.debug(f"ML Service: Roof prediction failed: {e}")
        
        # Sky prediction (only when roof is open)
        sky_enabled = config.get('sky_classifier', True)
        roof_is_open = results['roof_status'] == 'Open'
        
        if sky_enabled and roof_is_open and self._sky_classifier is not None:
            try:
                sky_meta = {
                    'corner_to_center_ratio': corner_analysis.get('corner_to_center_ratio', 1.0),
                    'median_lum': corner_analysis.get('center_med', 0.0),
                    'is_astronomical_night': time_context.get('is_astronomical_night', False),
                    'hour': time_context.get('hour', 12),
                    'moon_illumination': 0.0,  # Could fetch from moon service
                    'moon_is_up': False,
                }
                
                sky_result = self._sky_classifier.predict(image_array, sky_meta)
                results['sky_condition'] = sky_result.sky_condition
                results['sky_confidence'] = round(float(sky_result.sky_confidence), 3)
                results['stars_visible'] = sky_result.stars_visible
                results['star_density'] = round(float(sky_result.star_density), 3)
                results['moon_visible'] = sky_result.moon_visible
                
            except Exception as e:
                app_logger.debug(f"ML Service: Sky prediction failed: {e}")
        
        # Cache results
        self._last_results = results
        
        return results
    
    def get_last_results(self) -> Dict[str, Any]:
        """Get cached results from last analysis."""
        return self._last_results.copy()
    
    def _compute_corner_analysis(self, image_array: np.ndarray) -> Dict[str, float]:
        """Compute corner-to-center analysis for ML features."""
        try:
            # Convert to grayscale if needed
            if len(image_array.shape) == 3:
                # RGB to grayscale
                gray = np.mean(image_array, axis=2)
            else:
                gray = image_array.astype(np.float32)
            
            # Normalize to 0-1
            if gray.max() > 1.0:
                gray = gray / 255.0
            
            h, w = gray.shape
            
            # Define regions (corners and center)
            corner_size = min(h, w) // 8
            
            # Corners
            corners = [
                gray[:corner_size, :corner_size],  # Top-left
                gray[:corner_size, -corner_size:],  # Top-right
                gray[-corner_size:, :corner_size],  # Bottom-left
                gray[-corner_size:, -corner_size:],  # Bottom-right
            ]
            
            # Center region
            ch, cw = h // 4, w // 4
            center = gray[ch:h-ch, cw:w-cw]
            
            corner_med = np.median([np.median(c) for c in corners])
            center_med = np.median(center)
            
            ratio = corner_med / max(center_med, 0.001)
            
            return {
                'corner_med': float(corner_med),
                'center_med': float(center_med),
                'corner_to_center_ratio': float(ratio),
            }
            
        except Exception as e:
            app_logger.debug(f"ML Service: Corner analysis failed: {e}")
            return {'corner_med': 0.0, 'center_med': 0.0, 'corner_to_center_ratio': 1.0}
    
    def _compute_time_context(self) -> Dict[str, Any]:
        """Compute time context for ML features."""
        from datetime import datetime
        
        try:
            now = datetime.now()
            hour = now.hour
            
            # Simple night detection (could be improved with astropy)
            is_night = hour < 6 or hour >= 20
            
            return {
                'hour': hour,
                'is_astronomical_night': is_night,
            }
            
        except Exception:
            return {'hour': 12, 'is_astronomical_night': False}


# Global singleton instance
_ml_service = None


def get_ml_service() -> MLService:
    """Get the global ML service instance."""
    global _ml_service
    if _ml_service is None:
        _ml_service = MLService()
    return _ml_service


def analyze_image_for_tokens(
    image_array: np.ndarray,
    config: Optional[Dict] = None
) -> Dict[str, str]:
    """
    Convenience function to get ML predictions formatted for overlay tokens.
    
    Args:
        image_array: Image as numpy array
        config: ML models config dict
    
    Returns:
        Dict with token values ready for overlay replacement:
        {
            'ROOF_STATUS': "Open (95%)" or "Closed (98%)" or "N/A",
            'SKY_CONDITION': "Clear (87%)" or "N/A",
            'STARS_VISIBLE': "Yes" or "No" or "N/A",
            'STAR_DENSITY': "High (0.85)" or "Low (0.12)" or "N/A",
        }
    """
    ml = get_ml_service()
    
    if not ml.is_available():
        return {
            'ROOF_STATUS': 'N/A',
            'SKY_CONDITION': 'N/A',
            'STARS_VISIBLE': 'N/A',
            'STAR_DENSITY': 'N/A',
        }
    
    results = ml.analyze_image(image_array, config=config)
    
    # Format for overlay display
    tokens = {}
    
    # Roof status
    if results['roof_confidence'] is not None:
        pct = int(results['roof_confidence'] * 100)
        tokens['ROOF_STATUS'] = f"{results['roof_status']} ({pct}%)"
    else:
        tokens['ROOF_STATUS'] = results['roof_status']
    
    # Sky condition
    if results['sky_confidence'] is not None:
        pct = int(results['sky_confidence'] * 100)
        tokens['SKY_CONDITION'] = f"{results['sky_condition']} ({pct}%)"
    else:
        tokens['SKY_CONDITION'] = results['sky_condition']
    
    # Stars visible
    if results['stars_visible'] is not None:
        tokens['STARS_VISIBLE'] = 'Yes' if results['stars_visible'] else 'No'
    else:
        tokens['STARS_VISIBLE'] = 'N/A'
    
    # Star density
    if results['star_density'] is not None:
        density = results['star_density']
        if density > 0.6:
            label = 'High'
        elif density > 0.3:
            label = 'Medium'
        else:
            label = 'Low'
        tokens['STAR_DENSITY'] = f"{label} ({density:.2f})"
    else:
        tokens['STAR_DENSITY'] = 'N/A'
    
    return tokens
