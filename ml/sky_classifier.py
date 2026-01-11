#!/usr/bin/env python3
"""
Sky/Celestial Classifier - Inference Module

Loads trained model and provides prediction interface for PFR Sentinel.
Predicts sky condition, stars visibility, star density, and moon visibility.

IMPORTANT: This classifier is trained on PIER CAMERA images and can only
provide meaningful predictions when the ROOF IS OPEN. When the roof is closed,
the pier camera cannot see the sky, so predictions are invalid.

Production Usage:
    from ml.roof_classifier import RoofClassifier
    from ml.sky_classifier import SkyClassifier
    
    roof_clf = RoofClassifier.load("ml/models/roof_classifier_v1.pth")
    sky_clf = SkyClassifier.load("ml/models/sky_classifier_v1.pth")
    
    roof_result = roof_clf.predict(image)
    
    if roof_result.roof_open:
        # Only predict sky when roof is open
        sky_result = sky_clf.predict(image, metadata)
        print(f"Sky: {sky_result.sky_condition}")
    else:
        # Roof closed - can't see sky through pier camera
        print("Sky prediction N/A - roof closed")
"""
import sys
from pathlib import Path
from typing import Union, Optional
from dataclasses import dataclass

import numpy as np

# Check for ONNX runtime (lightweight inference - preferred for production)
try:
    import onnxruntime as ort
    ONNX_AVAILABLE = True
except ImportError:
    ONNX_AVAILABLE = False

# Fallback to PyTorch if ONNX not available
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


# Sky condition classes (must match training)
SKY_CONDITIONS = ['Clear', 'Mostly Clear', 'Partly Cloudy', 'Mostly Cloudy', 'Overcast']
IDX_TO_SKY = {i: cond for i, cond in enumerate(SKY_CONDITIONS)}


@dataclass
class SkyPrediction:
    """Sky/celestial prediction result."""
    sky_condition: str
    sky_confidence: float
    sky_probabilities: dict  # All class probabilities
    stars_visible: bool
    stars_confidence: float
    star_density: float
    moon_visible: bool
    moon_confidence: float
    
    def to_dict(self) -> dict:
        return {
            'sky_condition': self.sky_condition,
            'sky_confidence': round(self.sky_confidence, 4),
            'sky_probabilities': {k: round(v, 4) for k, v in self.sky_probabilities.items()},
            'stars_visible': self.stars_visible,
            'stars_confidence': round(self.stars_confidence, 4),
            'star_density': round(self.star_density, 4),
            'moon_visible': self.moon_visible,
            'moon_confidence': round(self.moon_confidence, 4),
        }


# Only define PyTorch model class when torch is available (not needed for ONNX inference)
if TORCH_AVAILABLE:
    class SkyClassifierCNN(nn.Module):
        """CNN architecture - must match training."""
        
        def __init__(self, image_size: int = 256, metadata_features: int = 6):
            super().__init__()
            
            self.image_size = image_size
            
            self.conv1 = nn.Conv2d(1, 32, 3, padding=1)
            self.bn1 = nn.BatchNorm2d(32)
            self.conv2 = nn.Conv2d(32, 64, 3, padding=1)
            self.bn2 = nn.BatchNorm2d(64)
            self.conv3 = nn.Conv2d(64, 128, 3, padding=1)
            self.bn3 = nn.BatchNorm2d(128)
            self.conv4 = nn.Conv2d(128, 256, 3, padding=1)
            self.bn4 = nn.BatchNorm2d(256)
            self.conv5 = nn.Conv2d(256, 256, 3, padding=1)
            self.bn5 = nn.BatchNorm2d(256)
            
            self.pool = nn.MaxPool2d(2, 2)
            self.dropout = nn.Dropout(0.3)
            
            conv_output_size = (image_size // 32) ** 2 * 256
            
            self.fc_image = nn.Linear(conv_output_size, 256)
            self.fc_meta = nn.Linear(metadata_features, 32)
            self.fc_fusion = nn.Linear(256 + 32, 128)
            
            self.head_sky = nn.Linear(128, len(SKY_CONDITIONS))
            self.head_stars = nn.Linear(128, 1)
            self.head_density = nn.Linear(128, 1)
            self.head_moon = nn.Linear(128, 1)
        
        def forward(self, image, metadata):
            x = self.pool(F.relu(self.bn1(self.conv1(image))))
            x = self.pool(F.relu(self.bn2(self.conv2(x))))
            x = self.pool(F.relu(self.bn3(self.conv3(x))))
            x = self.pool(F.relu(self.bn4(self.conv4(x))))
            x = self.pool(F.relu(self.bn5(self.conv5(x))))
            
            x = x.view(x.size(0), -1)
            x = self.dropout(F.relu(self.fc_image(x)))
            
            m = F.relu(self.fc_meta(metadata))
            
            combined = torch.cat([x, m], dim=1)
            features = self.dropout(F.relu(self.fc_fusion(combined)))
            
            sky_logits = self.head_sky(features)
            stars_logit = self.head_stars(features)
            density = torch.sigmoid(self.head_density(features))
            moon_logit = self.head_moon(features)
            
            return sky_logits, stars_logit, density, moon_logit


class SkyClassifier:
    """
    Sky/celestial classifier for PFR Sentinel.
    
    Predicts sky condition, stars, and moon from pier camera images.
    Supports both ONNX (preferred for production) and PyTorch models.
    """
    
    def __init__(self, model_path: Union[str, Path], image_size: int = 256):
        """
        Initialize classifier with model.
        
        Args:
            model_path: Path to model file (.onnx or .pth)
            image_size: Expected image size (must match training)
        """
        self.model_path = Path(model_path)
        self.image_size = image_size
        self.model = None
        self.model_type = None
        self.device = None
        
        self._load_model()
    
    def _load_model(self):
        """Load model based on file extension."""
        if not self.model_path.exists():
            raise FileNotFoundError(f"Model not found: {self.model_path}")
        
        suffix = self.model_path.suffix.lower()
        
        if suffix == '.onnx':
            if not ONNX_AVAILABLE:
                raise ImportError("ONNX Runtime not installed. Run: pip install onnxruntime")
            
            self.model = ort.InferenceSession(str(self.model_path))
            self.model_type = 'onnx'
            # ONNX models use default image_size=256, metadata_features=6
            print(f"Loaded ONNX sky classifier from: {self.model_path}")
            
        elif suffix == '.pth':
            if not TORCH_AVAILABLE:
                raise ImportError("PyTorch not installed. Run: pip install torch")
            
            self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
            checkpoint = torch.load(self.model_path, map_location=self.device, weights_only=False)
            
            # Get model parameters
            self.image_size = checkpoint.get('image_size', 256)
            metadata_features = checkpoint.get('metadata_features', 6)
            
            # Create and load model
            self.model = SkyClassifierCNN(
                image_size=self.image_size,
                metadata_features=metadata_features
            )
            self.model.load_state_dict(checkpoint['model_state_dict'])
            self.model.to(self.device)
            self.model.eval()
            self.model_type = 'pytorch'
            print(f"Loaded PyTorch sky classifier from: {self.model_path}")
        
        print(f"Loaded sky classifier from: {self.model_path}")
    
    @classmethod
    def load(cls, model_path: Union[str, Path], image_size: int = 256) -> 'SkyClassifier':
        """Load classifier from model file."""
        return cls(model_path, image_size)
    
    def preprocess_image(self, image: np.ndarray) -> np.ndarray:
        """Preprocess image for model input."""
        # Handle RGB by converting to grayscale
        if len(image.shape) == 3:
            if image.shape[2] == 3:
                image = 0.299 * image[:,:,0] + 0.587 * image[:,:,1] + 0.114 * image[:,:,2]
            else:
                image = image[:,:,0]
        
        image = image.astype(np.float32)
        
        # Normalize
        p1, p99 = np.percentile(image, [1, 99])
        if p99 > p1:
            image = (image - p1) / (p99 - p1)
        image = np.clip(image, 0, 1)
        
        # Arcsinh stretch
        stretch = 10.0
        image = np.arcsinh(image * stretch) / np.arcsinh(stretch)
        
        # Resize
        image = self._resize_image(image, self.image_size)
        
        # Add batch and channel dimensions
        image = image[np.newaxis, np.newaxis, :, :]
        
        return image
    
    def _resize_image(self, img: np.ndarray, size: int) -> np.ndarray:
        """Resize image using block averaging."""
        h, w = img.shape
        block_h = h // size
        block_w = w // size
        
        if block_h == 0 or block_w == 0:
            result = np.zeros((size, size), dtype=np.float32)
            copy_h = min(h, size)
            copy_w = min(w, size)
            result[:copy_h, :copy_w] = img[:copy_h, :copy_w]
            return result
        
        trimmed = img[:block_h * size, :block_w * size]
        result = trimmed.reshape(size, block_h, size, block_w).mean(axis=(1, 3))
        return result
    
    def predict(self, image: np.ndarray, metadata: Optional[dict] = None) -> SkyPrediction:
        """
        Predict sky condition and celestial objects.
        
        Args:
            image: Raw image array
            metadata: Optional metadata dict with:
                - corner_to_center_ratio
                - median_lum
                - is_astronomical_night
                - hour
                - moon_illumination
                - moon_is_up
                
        Returns:
            SkyPrediction with all predictions
        """
        # Preprocess image
        image_input = self.preprocess_image(image)
        
        # Build metadata array
        if metadata is not None:
            meta_input = np.array([[
                metadata.get('corner_to_center_ratio', 1.0),
                metadata.get('median_lum', 0.0),
                1.0 if metadata.get('is_astronomical_night') else 0.0,
                metadata.get('hour', 12) / 24.0,
                metadata.get('moon_illumination', 0.0) / 100.0,
                1.0 if metadata.get('moon_is_up') else 0.0,
            ]], dtype=np.float32)
        else:
            meta_input = np.array([[1.0, 0.0, 0.0, 0.5, 0.0, 0.0]], dtype=np.float32)
        
        # Run inference based on model type
        if self.model_type == 'onnx':
            outputs = self.model.run(None, {
                'image': image_input.astype(np.float32),
                'metadata': meta_input.astype(np.float32)
            })
            sky_logits = outputs[0]
            stars_logit = outputs[1]
            density = outputs[2]
            moon_logit = outputs[3]
            
            # Sky condition (softmax)
            sky_exp = np.exp(sky_logits - np.max(sky_logits, axis=1, keepdims=True))
            sky_probs = (sky_exp / sky_exp.sum(axis=1, keepdims=True))[0]
            sky_idx = int(np.argmax(sky_probs))
            sky_condition = IDX_TO_SKY[sky_idx]
            sky_confidence = float(sky_probs[sky_idx])
            sky_probabilities = {IDX_TO_SKY[i]: float(p) for i, p in enumerate(sky_probs)}
            
            # Stars (sigmoid)
            stars_prob = float(1 / (1 + np.exp(-stars_logit[0, 0])))
            stars_visible = stars_prob > 0.5
            stars_confidence = stars_prob if stars_visible else (1 - stars_prob)
            
            # Star density (already sigmoid in model)
            star_density = float(density[0, 0])
            
            # Moon (sigmoid)
            moon_prob = float(1 / (1 + np.exp(-moon_logit[0, 0])))
            moon_visible = moon_prob > 0.5
            moon_confidence = moon_prob if moon_visible else (1 - moon_prob)
            
        elif self.model_type == 'pytorch':
            with torch.no_grad():
                image_tensor = torch.from_numpy(image_input).float().to(self.device)
                meta_tensor = torch.from_numpy(meta_input).float().to(self.device)
                
                sky_logits, stars_logit, density, moon_logit = self.model(image_tensor, meta_tensor)
                
                # Sky condition
                sky_probs = F.softmax(sky_logits, dim=1).cpu().numpy()[0]
                sky_idx = int(np.argmax(sky_probs))
                sky_condition = IDX_TO_SKY[sky_idx]
                sky_confidence = float(sky_probs[sky_idx])
                sky_probabilities = {IDX_TO_SKY[i]: float(p) for i, p in enumerate(sky_probs)}
                
                # Stars
                stars_prob = float(torch.sigmoid(stars_logit).cpu().numpy()[0, 0])
                stars_visible = stars_prob > 0.5
                stars_confidence = stars_prob if stars_visible else (1 - stars_prob)
                
                # Star density
                star_density = float(density.cpu().numpy()[0, 0])
                
                # Moon
                moon_prob = float(torch.sigmoid(moon_logit).cpu().numpy()[0, 0])
                moon_visible = moon_prob > 0.5
                moon_confidence = moon_prob if moon_visible else (1 - moon_prob)
        
        return SkyPrediction(
            sky_condition=sky_condition,
            sky_confidence=sky_confidence,
            sky_probabilities=sky_probabilities,
            stars_visible=stars_visible,
            stars_confidence=stars_confidence,
            star_density=star_density if stars_visible else 0.0,
            moon_visible=moon_visible,
            moon_confidence=moon_confidence,
        )
    
    def predict_from_fits(self, fits_path: Union[str, Path],
                          metadata: Optional[dict] = None) -> SkyPrediction:
        """Predict from FITS file."""
        try:
            from astropy.io import fits as astropy_fits
        except ImportError:
            raise ImportError("Astropy required for FITS files")
        
        with astropy_fits.open(fits_path) as hdul:
            image = hdul[0].data
        
        if image is None:
            raise ValueError(f"No image data in FITS file: {fits_path}")
        
        return self.predict(image, metadata)


def main():
    """CLI for testing predictions."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test sky classifier predictions")
    parser.add_argument("image", help="Path to image file (FITS)")
    parser.add_argument("--model", default="ml/models/sky_classifier_v1.pth",
                        help="Path to model file")
    args = parser.parse_args()
    
    classifier = SkyClassifier.load(args.model)
    result = classifier.predict_from_fits(args.image)
    
    print(f"\nPrediction for: {args.image}")
    print(f"  Sky Condition:  {result.sky_condition} ({result.sky_confidence:.1%})")
    print(f"  Stars Visible:  {result.stars_visible} ({result.stars_confidence:.1%})")
    print(f"  Star Density:   {result.star_density:.2f}")
    print(f"  Moon Visible:   {result.moon_visible} ({result.moon_confidence:.1%})")


if __name__ == "__main__":
    main()
