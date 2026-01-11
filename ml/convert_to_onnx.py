#!/usr/bin/env python3
"""
Convert PyTorch ML models to ONNX format for production deployment.

ONNX models are preferred for production because:
1. Lighter weight runtime (onnxruntime vs full PyTorch)
2. Better PyInstaller compatibility
3. Faster cold-start inference
4. No CUDA/GPU dependency issues

Usage:
    python ml/convert_to_onnx.py
    
    # Or convert specific model:
    python ml/convert_to_onnx.py --model roof
    python ml/convert_to_onnx.py --model sky
"""
import argparse
from pathlib import Path

import numpy as np

# PyTorch required for conversion
try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
except ImportError:
    print("ERROR: PyTorch required for conversion. Run: pip install torch")
    exit(1)


# ============================================================================
# Model Architectures (must match training)
# ============================================================================

class RoofClassifierCNN(nn.Module):
    """CNN for roof state classification with metadata fusion."""
    
    def __init__(self, image_size: int = 128, num_meta_features: int = 4):
        super().__init__()
        
        self.conv_layers = nn.Sequential(
            nn.Conv2d(1, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.MaxPool2d(2),
            
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.MaxPool2d(2),
            
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(),
            nn.MaxPool2d(2),
            
            nn.Conv2d(128, 256, kernel_size=3, padding=1),
            nn.BatchNorm2d(256),
            nn.ReLU(),
            nn.MaxPool2d(2),
            
            nn.Conv2d(256, 256, kernel_size=3, padding=1),
            nn.BatchNorm2d(256),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d(4),
        )
        
        self.cnn_output_size = 256 * 4 * 4
        
        self.meta_layers = nn.Sequential(
            nn.Linear(num_meta_features, 32),
            nn.ReLU(),
            nn.Linear(32, 64),
            nn.ReLU(),
        )
        
        self.classifier = nn.Sequential(
            nn.Linear(self.cnn_output_size + 64, 256),
            nn.ReLU(),
            nn.Dropout(0.5),
            nn.Linear(256, 64),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(64, 1),
        )
    
    def forward(self, image, metadata):
        x = self.conv_layers(image)
        x = x.view(x.size(0), -1)
        m = self.meta_layers(metadata)
        combined = torch.cat([x, m], dim=1)
        output = self.classifier(combined)
        return output


class SkyClassifierCNN(nn.Module):
    """CNN architecture for sky classification."""
    
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
        
        self.head_sky = nn.Linear(128, 5)  # 5 sky conditions
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


def convert_roof_classifier(input_path: Path, output_path: Path, image_size: int = 128):
    """Convert roof classifier to ONNX."""
    print(f"\n=== Converting Roof Classifier ===")
    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")
    
    # Load PyTorch model
    checkpoint = torch.load(input_path, map_location='cpu', weights_only=False)
    model = RoofClassifierCNN(image_size=image_size)
    model.load_state_dict(checkpoint['model_state_dict'])
    model.eval()
    
    # Create dummy inputs
    dummy_image = torch.randn(1, 1, image_size, image_size)
    dummy_metadata = torch.randn(1, 4)
    
    # Export to ONNX
    torch.onnx.export(
        model,
        (dummy_image, dummy_metadata),
        str(output_path),
        input_names=['image', 'metadata'],
        output_names=['output'],
        dynamic_axes={
            'image': {0: 'batch'},
            'metadata': {0: 'batch'},
            'output': {0: 'batch'}
        },
        opset_version=14,
        do_constant_folding=True,
    )
    
    print(f"✓ Exported roof classifier to ONNX")
    
    # Verify
    verify_onnx_model(output_path)
    
    # Compare outputs
    compare_outputs(
        model, output_path, dummy_image, dummy_metadata,
        output_names=['output']
    )


def convert_sky_classifier(input_path: Path, output_path: Path, image_size: int = 256):
    """Convert sky classifier to ONNX."""
    print(f"\n=== Converting Sky Classifier ===")
    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")
    
    # Load PyTorch model
    checkpoint = torch.load(input_path, map_location='cpu', weights_only=False)
    saved_image_size = checkpoint.get('image_size', image_size)
    metadata_features = checkpoint.get('metadata_features', 6)
    
    model = SkyClassifierCNN(image_size=saved_image_size, metadata_features=metadata_features)
    model.load_state_dict(checkpoint['model_state_dict'])
    model.eval()
    
    # Create dummy inputs
    dummy_image = torch.randn(1, 1, saved_image_size, saved_image_size)
    dummy_metadata = torch.randn(1, metadata_features)
    
    # Export to ONNX
    torch.onnx.export(
        model,
        (dummy_image, dummy_metadata),
        str(output_path),
        input_names=['image', 'metadata'],
        output_names=['sky_logits', 'stars_logit', 'density', 'moon_logit'],
        dynamic_axes={
            'image': {0: 'batch'},
            'metadata': {0: 'batch'},
            'sky_logits': {0: 'batch'},
            'stars_logit': {0: 'batch'},
            'density': {0: 'batch'},
            'moon_logit': {0: 'batch'},
        },
        opset_version=14,
        do_constant_folding=True,
    )
    
    print(f"✓ Exported sky classifier to ONNX")
    
    # Verify
    verify_onnx_model(output_path)
    
    # Compare outputs
    with torch.no_grad():
        pytorch_outputs = model(dummy_image, dummy_metadata)
    
    import onnxruntime as ort
    session = ort.InferenceSession(str(output_path))
    onnx_outputs = session.run(None, {
        'image': dummy_image.numpy(),
        'metadata': dummy_metadata.numpy()
    })
    
    print("\nOutput comparison (PyTorch vs ONNX):")
    output_names = ['sky_logits', 'stars_logit', 'density', 'moon_logit']
    for i, name in enumerate(output_names):
        pt_out = pytorch_outputs[i].numpy()
        onnx_out = onnx_outputs[i]
        max_diff = np.abs(pt_out - onnx_out).max()
        print(f"  {name}: max_diff = {max_diff:.2e}")
        if max_diff > 1e-5:
            print(f"    WARNING: Large difference detected!")


def verify_onnx_model(model_path: Path):
    """Verify ONNX model is valid."""
    try:
        import onnx
        model = onnx.load(str(model_path))
        onnx.checker.check_model(model)
        print(f"✓ ONNX model is valid")
    except ImportError:
        print("  (Skipping ONNX validation - onnx package not installed)")
    except Exception as e:
        print(f"  WARNING: ONNX validation failed: {e}")


def compare_outputs(pytorch_model, onnx_path: Path, image, metadata, output_names):
    """Compare PyTorch and ONNX outputs."""
    try:
        import onnxruntime as ort
    except ImportError:
        print("  (Skipping output comparison - onnxruntime not installed)")
        return
    
    # PyTorch inference
    with torch.no_grad():
        pytorch_output = pytorch_model(image, metadata)
    
    # ONNX inference
    session = ort.InferenceSession(str(onnx_path))
    onnx_output = session.run(None, {
        'image': image.numpy(),
        'metadata': metadata.numpy()
    })
    
    print("\nOutput comparison (PyTorch vs ONNX):")
    for i, name in enumerate(output_names):
        pt_out = pytorch_output.numpy() if hasattr(pytorch_output, 'numpy') else pytorch_output
        onnx_out = onnx_output[i]
        max_diff = np.abs(pt_out - onnx_out).max()
        print(f"  {name}: max_diff = {max_diff:.2e}")
        if max_diff > 1e-5:
            print(f"    WARNING: Large difference detected!")


def main():
    parser = argparse.ArgumentParser(description="Convert ML models to ONNX")
    parser.add_argument("--model", choices=['roof', 'sky', 'all'], default='all',
                        help="Which model to convert")
    parser.add_argument("--models-dir", default="ml/models",
                        help="Directory containing model files")
    args = parser.parse_args()
    
    models_dir = Path(args.models_dir)
    
    if args.model in ['roof', 'all']:
        roof_pth = models_dir / "roof_classifier_v1.pth"
        roof_onnx = models_dir / "roof_classifier_v1.onnx"
        
        if roof_pth.exists():
            convert_roof_classifier(roof_pth, roof_onnx)
        else:
            print(f"ERROR: Roof model not found: {roof_pth}")
    
    if args.model in ['sky', 'all']:
        sky_pth = models_dir / "sky_classifier_v1.pth"
        sky_onnx = models_dir / "sky_classifier_v1.onnx"
        
        if sky_pth.exists():
            convert_sky_classifier(sky_pth, sky_onnx)
        else:
            print(f"ERROR: Sky model not found: {sky_pth}")
    
    print("\n=== Conversion Complete ===")
    print("\nONNX models can now be used in production builds.")
    print("The ml_service.py will automatically prefer ONNX over PyTorch.")


if __name__ == "__main__":
    main()
