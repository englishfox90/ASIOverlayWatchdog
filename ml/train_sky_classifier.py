#!/usr/bin/env python3
"""
Sky/Celestial Classifier Training - Phase 2

Multi-task model trained on PIER CAMERA images to predict:
- sky_condition: 3-class (Clear, Partly Cloudy, Overcast)
- stars_visible: binary
- star_density: regression (0-1)
- moon_visible: binary

Note: All-sky camera is used only as labeling reference, NOT as model input.
Production uses pier camera only.

Uses larger image size (256x256) than roof model for better star/cloud detection.

GPU Optimizations:
- Large batch size (64-128) to saturate GPU
- Mixed precision (FP16) for 2x speedup
- Data preloaded to GPU memory
- torch.compile() for optimized kernels
"""
import sys
import warnings
import json
import copy
import random
from pathlib import Path
from datetime import datetime

# Suppress TorchScript ONNX legacy exporter deprecation notice
warnings.filterwarnings('ignore', category=DeprecationWarning, module='torch.onnx')
from collections import Counter

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torch.amp import autocast, GradScaler

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ml.sky_dataset import (
    SkyDataset, SKY_CONDITIONS, SKY_TO_IDX, IDX_TO_SKY, SKY_CONDITION_COLLAPSE,
)

try:
    from sklearn.model_selection import train_test_split
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

# Reproducible split so a separate eval can reconstruct the exact test set.
SEED = 42


class SkyClassifierCNN(nn.Module):
    """
    Multi-task CNN for sky condition and celestial detection.
    
    Larger architecture than roof model for better detail detection.
    """
    
    def __init__(self, image_size: int = 256, metadata_features: int = 6):
        super().__init__()
        
        self.image_size = image_size
        
        # Deeper CNN backbone for larger images
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
        
        # Calculate flattened size after conv layers
        # 256 -> 128 -> 64 -> 32 -> 16 -> 8 (5 pooling layers)
        conv_output_size = (image_size // 32) ** 2 * 256
        
        # Image feature extraction
        self.fc_image = nn.Linear(conv_output_size, 256)
        
        # Metadata branch
        self.fc_meta = nn.Linear(metadata_features, 32)
        
        # Fusion layer
        self.fc_fusion = nn.Linear(256 + 32, 128)
        
        # Task-specific heads
        self.head_sky = nn.Linear(128, len(SKY_CONDITIONS))  # 5-class
        self.head_stars = nn.Linear(128, 1)  # Binary
        self.head_density = nn.Linear(128, 1)  # Regression
        self.head_moon = nn.Linear(128, 1)  # Binary
    
    def forward(self, image, metadata):
        # CNN backbone
        x = self.pool(F.relu(self.bn1(self.conv1(image))))
        x = self.pool(F.relu(self.bn2(self.conv2(x))))
        x = self.pool(F.relu(self.bn3(self.conv3(x))))
        x = self.pool(F.relu(self.bn4(self.conv4(x))))
        x = self.pool(F.relu(self.bn5(self.conv5(x))))
        
        # Flatten
        x = x.view(x.size(0), -1)
        x = self.dropout(F.relu(self.fc_image(x)))
        
        # Metadata branch
        m = F.relu(self.fc_meta(metadata))
        
        # Fusion
        combined = torch.cat([x, m], dim=1)
        features = self.dropout(F.relu(self.fc_fusion(combined)))
        
        # Task outputs
        sky_logits = self.head_sky(features)
        stars_logit = self.head_stars(features)
        density = torch.sigmoid(self.head_density(features))  # 0-1 range
        moon_logit = self.head_moon(features)
        
        return sky_logits, stars_logit, density, moon_logit


def load_dataset(data_dir: Path) -> tuple:
    """
    Load all labeled samples with required fields.
    
    Returns:
        (pier_samples, allsky_samples) - Pier camera for validation, all-sky for extra training
        
    Pier camera (lum_*.fits): Only roof_open=True samples
    All-sky (allsky_*.jpg): All labeled samples (can see sky regardless of pier roof)
    """
    pier_samples = []
    allsky_samples = []
    skipped = {
        'no_labels': 0, 
        'no_sky_label': 0, 
        'no_lum': 0, 
        'no_allsky': 0,
        'roof_closed': 0,
    }
    
    for cal_file in data_dir.rglob('calibration_*.json'):
        try:
            with open(cal_file, 'r') as f:
                cal = json.load(f)
            
            labels = cal.get('labels', {})
            if not labels.get('labeled_at'):
                skipped['no_labels'] += 1
                continue
            
            # Must have sky_condition label. Fold any legacy 5-class label into
            # the 3-class scheme so an un-migrated file is bucketed, not dropped.
            sky_cond = labels.get('sky_condition')
            sky_cond = SKY_CONDITION_COLLAPSE.get(sky_cond, sky_cond)
            if not sky_cond or sky_cond not in SKY_CONDITIONS:
                skipped['no_sky_label'] += 1
                continue
            
            # Extract timestamp and paths
            timestamp = cal_file.stem.replace('calibration_', '')
            lum_path = cal_file.parent / f'lum_{timestamp}.fits'
            allsky_path = cal_file.parent / f'allsky_{timestamp}.jpg'
            
            # Extract metadata (shared for both image types)
            tc = cal.get('time_context', {})
            ca = cal.get('corner_analysis', {})
            mc = cal.get('moon_context', {})
            st = cal.get('stretch', {})
            
            metadata = {
                'corner_to_center_ratio': ca.get('corner_to_center_ratio', 1.0),
                'median_lum': st.get('median_lum', 0.0),
                'is_astronomical_night': tc.get('is_astronomical_night', False),
                'hour': tc.get('hour', 12),
                'moon_illumination': mc.get('illumination_pct', 0.0),
                'moon_is_up': mc.get('moon_is_up', False),
            }
            
            # Common sample data
            sample_base = {
                'sky_condition': sky_cond,
                'stars_visible': labels.get('stars_visible', False),
                'star_density': labels.get('star_density', 0.0),
                'moon_visible': labels.get('moon_visible', False),
                'metadata': metadata,
                'timestamp': timestamp,
            }
            
            # PIER CAMERA (lum_*.fits) - Only if roof is OPEN
            if lum_path.exists():
                roof_open = labels.get('roof_open', False)
                if roof_open:
                    pier_samples.append({
                        **sample_base,
                        'image_path': lum_path,
                        'source': 'pier',
                    })
                else:
                    skipped['roof_closed'] += 1
            else:
                skipped['no_lum'] += 1
            
            # ALL-SKY CAMERA (allsky_*.jpg) - All labeled samples
            if allsky_path.exists():
                allsky_samples.append({
                    **sample_base,
                    'image_path': allsky_path,
                    'source': 'allsky',
                })
            else:
                skipped['no_allsky'] += 1
            
        except Exception as e:
            print(f"Error loading {cal_file}: {e}")
    
    print(f"Loaded: {len(pier_samples)} pier (roof open), {len(allsky_samples)} all-sky")
    print(f"Skipped: {skipped}")

    return pier_samples, allsky_samples


def _split_samples(samples: list, val_split: float):
    """Reproducible train/val/test split, stratified on sky_condition.

    Test is held out at 15%; val is `val_split` of the remainder. Falls back to a
    seeded random split if sklearn is missing or a class is too rare to stratify.
    """
    strata = [s['sky_condition'] for s in samples]
    try:
        if not SKLEARN_AVAILABLE:
            raise RuntimeError("sklearn unavailable")
        trainval, test = train_test_split(
            samples, test_size=0.15, random_state=SEED, stratify=strata)
        train, val = train_test_split(
            trainval, test_size=val_split, random_state=SEED,
            stratify=[s['sky_condition'] for s in trainval])
        return train, val, test
    except (ValueError, RuntimeError) as e:
        # ValueError: a class has too few members to stratify.
        print(f"  Stratified split unavailable ({e}); using seeded random split.")
        shuffled = list(samples)
        random.Random(SEED).shuffle(shuffled)
        n_test = max(int(len(shuffled) * 0.15), 1)
        n_val = max(int(len(shuffled) * val_split), 1)
        test = shuffled[:n_test]
        val = shuffled[n_test:n_test + n_val]
        train = shuffled[n_test + n_val:]
        return train, val, test


def train_model(
    data_dir: Path,
    output_dir: Path,
    image_size: int = 256,
    batch_size: int = 64,  # Larger batch for GPU saturation
    epochs: int = 50,
    learning_rate: float = 0.001,
    val_split: float = 0.15,
    model_name: str = 'sky_classifier_v1',
):
    """
    Train the sky/celestial classifier with GPU optimization.
    
    Training strategy:
    - Train on: Pier camera (roof open) ONLY
    - Validate on: Pier camera only (matches production)
    - All-sky camera data is NOT used for training
    """
    
    print("=" * 60)
    print("Sky/Celestial Classifier Training - Phase 2")
    print("=" * 60)
    
    # Load dataset - separate pier and all-sky
    pier_samples, allsky_samples = load_dataset(data_dir)
    
    if len(pier_samples) < 20:
        print(f"Error: Need at least 20 pier samples for validation, got {len(pier_samples)}")
        return None
    
    # Seed everything so the split is reproducible — a separate eval reconstructs
    # the exact same test set, and runs are comparable across retrains.
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    # Stratified train/val/TEST split on sky_condition (pier camera only). The
    # held-out test set is never used for selection or the LR scheduler, so the
    # final numbers are honest rather than measured on the tuning set.
    train_samples, val_samples, test_samples = _split_samples(pier_samples, val_split)
    all_train = train_samples

    print(f"\n=== Dataset Split (PIER CAMERA ONLY) ===")
    print(f"Training:   {len(train_samples)} (roof open)")
    print(f"Validation: {len(val_samples)} (selection + scheduler)")
    print(f"Test:       {len(test_samples)} (held out, final metrics only)")
    print(f"\nNote: All-sky samples ({len(allsky_samples)}) are SKIPPED in this training run")
    
    # Print class distribution (training set)
    print("\n=== Training Label Distribution ===")
    sky_dist = Counter(s['sky_condition'] for s in all_train)
    for cond in SKY_CONDITIONS:
        print(f"  {cond}: {sky_dist.get(cond, 0)}")
    
    stars_dist = Counter(s['stars_visible'] for s in all_train)
    print(f"\n  Stars visible: {stars_dist.get(True, 0)}")
    print(f"  Stars not visible: {stars_dist.get(False, 0)}")
    
    moon_dist = Counter(s['moon_visible'] for s in all_train)
    print(f"\n  Moon visible: {moon_dist.get(True, 0)}")
    print(f"  Moon not visible: {moon_dist.get(False, 0)}")
    
    # Create datasets with preloading for fast GPU training
    print("\nPreloading training data...")
    train_dataset = SkyDataset(train_samples, image_size=image_size, augment=True, preload=True)
    print("\nPreloading validation data (pier camera only)...")
    val_dataset = SkyDataset(val_samples, image_size=image_size, augment=False, preload=True)
    print("\nPreloading test data (pier camera only)...")
    test_dataset = SkyDataset(test_samples, image_size=image_size, augment=False, preload=True)

    # With preloaded data, we don't need multiprocessing - data is already in RAM
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True,
                              num_workers=0, pin_memory=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False,
                            num_workers=0, pin_memory=True)
    test_loader = DataLoader(test_dataset, batch_size=batch_size, shuffle=False,
                             num_workers=0, pin_memory=True)
    
    # Create model
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"\nUsing device: {device}")
    if device.type == 'cuda':
        print(f"GPU: {torch.cuda.get_device_name(0)}")
        print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
    
    model = SkyClassifierCNN(image_size=image_size, metadata_features=6)
    model = model.to(device)
    
    # Note: torch.compile() requires Triton which is not available on Windows
    # Skipping compilation - still get good speedup from mixed precision and large batches
    print("Note: Using eager mode (torch.compile requires Triton/Linux)")
    
    # Class-weight ONLY the sky head — it's the imbalanced multiclass task (Clear
    # dominates the open-roof set because you only image on clear nights). The
    # binary heads use plain BCE on purpose: stars-visible is actually the
    # MAJORITY label, so balancing it would trade away accuracy, and the moon head
    # already learns its rare positive well without weighting.
    # sqrt-softened inverse-frequency weights, normalized to mean 1. Full inverse
    # frequency over-corrected (Clear fell to 82%); sqrt keeps the rare classes
    # learnable without tanking Clear, and mean-1 normalization keeps the sky loss
    # scale comparable to the other (unweighted) task heads.
    sky_counts = Counter(SKY_TO_IDX[s['sky_condition']] for s in train_samples)
    n_classes = len(SKY_CONDITIONS)
    raw_w = [(len(train_samples) / (n_classes * max(sky_counts.get(i, 0), 1))) ** 0.5
             for i in range(n_classes)]
    mean_w = sum(raw_w) / n_classes
    sky_w = torch.tensor([w / mean_w for w in raw_w], dtype=torch.float32, device=device)
    criterion_sky = nn.CrossEntropyLoss(weight=sky_w)
    criterion_stars = nn.BCEWithLogitsLoss()
    criterion_moon = nn.BCEWithLogitsLoss()
    criterion_density = nn.MSELoss()
    
    # Optimizer with weight decay
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=0.01)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=5, factor=0.5)
    
    # Mixed precision scaler for 2x speedup on RTX cards
    scaler = GradScaler('cuda')
    use_amp = device.type == 'cuda'
    if use_amp:
        print("✓ Mixed precision (FP16) enabled")
    
    # Training loop
    best_val_loss = float('inf')
    best_model_state = None
    
    print("\n" + "=" * 60)
    print(f"Training with batch_size={batch_size}, AMP={use_amp}")
    print("=" * 60)
    
    for epoch in range(epochs):
        # Training
        model.train()
        train_loss = 0.0
        
        for batch in train_loader:
            # Non-blocking GPU transfer
            images = batch['image'].to(device, non_blocking=True)
            metadata = batch['metadata'].to(device, non_blocking=True)
            sky_labels = batch['sky_condition'].to(device, non_blocking=True)
            stars_labels = batch['stars_visible'].to(device, non_blocking=True)
            density_labels = batch['star_density'].to(device, non_blocking=True)
            moon_labels = batch['moon_visible'].to(device, non_blocking=True)
            
            optimizer.zero_grad(set_to_none=True)  # Faster than zero_grad()
            
            # Mixed precision forward pass
            with autocast('cuda', enabled=use_amp):
                sky_logits, stars_logit, density, moon_logit = model(images, metadata)
                
                # Multi-task loss (weighted)
                loss_sky = criterion_sky(sky_logits, sky_labels)
                loss_stars = criterion_stars(stars_logit.squeeze(-1), stars_labels)
                loss_density = criterion_density(density.squeeze(-1), density_labels)
                loss_moon = criterion_moon(moon_logit.squeeze(-1), moon_labels)
                
                # Combined loss with weights
                loss = 1.0 * loss_sky + 0.5 * loss_stars + 0.3 * loss_density + 0.5 * loss_moon
            
            # Scaled backward pass
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            
            train_loss += loss.item()
        
        train_loss /= len(train_loader)
        
        # Validation
        model.eval()
        val_loss = 0.0
        sky_correct = 0
        stars_correct = 0
        moon_correct = 0
        total = 0
        
        with torch.no_grad():
            for batch in val_loader:
                images = batch['image'].to(device, non_blocking=True)
                metadata = batch['metadata'].to(device, non_blocking=True)
                sky_labels = batch['sky_condition'].to(device, non_blocking=True)
                stars_labels = batch['stars_visible'].to(device, non_blocking=True)
                density_labels = batch['star_density'].to(device, non_blocking=True)
                moon_labels = batch['moon_visible'].to(device, non_blocking=True)
                
                with autocast('cuda', enabled=use_amp):
                    sky_logits, stars_logit, density, moon_logit = model(images, metadata)
                    
                    # Loss
                    loss_sky = criterion_sky(sky_logits, sky_labels)
                    loss_stars = criterion_stars(stars_logit.squeeze(-1), stars_labels)
                    loss_density = criterion_density(density.squeeze(-1), density_labels)
                    loss_moon = criterion_moon(moon_logit.squeeze(-1), moon_labels)
                    loss = 1.0 * loss_sky + 0.5 * loss_stars + 0.3 * loss_density + 0.5 * loss_moon
                
                val_loss += loss.item()
                
                # Accuracy
                sky_pred = sky_logits.argmax(dim=1)
                sky_correct += (sky_pred == sky_labels).sum().item()
                
                stars_pred = (torch.sigmoid(stars_logit.squeeze(-1)) > 0.5).float()
                stars_correct += (stars_pred == stars_labels).sum().item()
                
                moon_pred = (torch.sigmoid(moon_logit.squeeze(-1)) > 0.5).float()
                moon_correct += (moon_pred == moon_labels).sum().item()
                
                total += sky_labels.size(0)
        
        val_loss /= len(val_loader)
        sky_acc = sky_correct / total * 100
        stars_acc = stars_correct / total * 100
        moon_acc = moon_correct / total * 100
        
        scheduler.step(val_loss)
        
        # Print progress
        if (epoch + 1) % 5 == 0 or epoch == 0:
            print(f"Epoch {epoch+1:3d}/{epochs}: "
                  f"Train Loss={train_loss:.4f}, Val Loss={val_loss:.4f}, "
                  f"Sky={sky_acc:.1f}%, Stars={stars_acc:.1f}%, Moon={moon_acc:.1f}%")
        
        # Save best model. deepcopy is required: state_dict() returns live tensor
        # references, so a shallow .copy() would be overwritten in place by later
        # epochs — silently saving the last epoch instead of the best.
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_model_state = copy.deepcopy(model.state_dict())
    
    # Load best model
    model.load_state_dict(best_model_state)
    
    # Save model
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / f'{model_name}.pth'
    
    torch.save({
        'model_state_dict': best_model_state,
        'image_size': image_size,
        'metadata_features': 6,
        'sky_conditions': SKY_CONDITIONS,
        'trained_at': datetime.now().isoformat(),
        'train_samples_total': len(train_samples),
        'train_samples_allsky': len(allsky_samples),
        'val_samples': len(val_samples),
        'test_samples': len(test_samples),
        'epochs': epochs,
    }, model_path)
    
    print(f"\n✓ Model saved to: {model_path}")
    
    # Final evaluation on the HELD-OUT test set (never seen during selection).
    print("\n" + "=" * 60)
    print("Final Evaluation on Held-Out Test Set")
    print("=" * 60)

    model.eval()
    all_sky_true = []
    all_sky_pred = []
    all_stars_true = []
    all_stars_pred = []
    all_moon_true = []
    all_moon_pred = []

    with torch.no_grad():
        for batch in test_loader:
            images = batch['image'].to(device)
            metadata = batch['metadata'].to(device)
            
            sky_logits, stars_logit, density, moon_logit = model(images, metadata)
            
            all_sky_true.extend(batch['sky_condition'].numpy())
            all_sky_pred.extend(sky_logits.argmax(dim=1).cpu().numpy())
            
            all_stars_true.extend(batch['stars_visible'].numpy())
            all_stars_pred.extend((torch.sigmoid(stars_logit.squeeze(-1)) > 0.5).cpu().numpy())
            
            all_moon_true.extend(batch['moon_visible'].numpy())
            all_moon_pred.extend((torch.sigmoid(moon_logit.squeeze(-1)) > 0.5).cpu().numpy())
    
    # Sky condition confusion
    print("\nSky Condition Accuracy:")
    sky_correct = sum(1 for t, p in zip(all_sky_true, all_sky_pred) if t == p)
    print(f"  {sky_correct}/{len(all_sky_true)} ({sky_correct/len(all_sky_true)*100:.1f}%)")
    
    print("\nSky Condition per class:")
    sky_per_class = {}
    for i, cond in enumerate(SKY_CONDITIONS):
        class_total = sum(1 for t in all_sky_true if t == i)
        class_correct = sum(1 for t, p in zip(all_sky_true, all_sky_pred) if t == i and p == i)
        sky_per_class[cond] = (class_correct, class_total)
        if class_total > 0:
            print(f"  {cond}: {class_correct}/{class_total} ({class_correct/class_total*100:.1f}%)")
    
    print(f"\nStars Visible Accuracy:")
    stars_correct = sum(1 for t, p in zip(all_stars_true, all_stars_pred) if t == p)
    print(f"  {stars_correct}/{len(all_stars_true)} ({stars_correct/len(all_stars_true)*100:.1f}%)")
    
    print(f"\nMoon Visible Accuracy:")
    moon_correct = sum(1 for t, p in zip(all_moon_true, all_moon_pred) if t == p)
    print(f"  {moon_correct}/{len(all_moon_true)} ({moon_correct/len(all_moon_true)*100:.1f}%)")

    # Export to ONNX for production inference
    onnx_path = Path(model_path).with_suffix('.onnx')
    print(f"\nExporting to ONNX: {onnx_path}")
    try:
        model.eval()
        dummy_image = torch.randn(1, 1, image_size, image_size).to(device)
        dummy_meta = torch.randn(1, 6).to(device)
        dynamic_axes = {
            'image': {0: 'batch'},
            'metadata': {0: 'batch'},
            'sky_condition': {0: 'batch'},
            'stars_visible': {0: 'batch'},
            'star_density': {0: 'batch'},
            'moon_visible': {0: 'batch'},
        }
        torch.onnx.export(
            model,
            (dummy_image, dummy_meta),
            str(onnx_path),
            input_names=['image', 'metadata'],
            output_names=['sky_condition', 'stars_visible', 'star_density', 'moon_visible'],
            dynamic_axes=dynamic_axes,
            opset_version=18,
            dynamo=False,
        )
        print(f"ONNX model saved to: {onnx_path}")
    except Exception as e:
        print(f"ONNX export failed: {e}")
        print("You can still use the .pth model with PyTorch")

    return {
        'image_size': image_size,
        'sky_overall': (sky_correct, len(all_sky_true)),
        'sky_per_class': sky_per_class,
        'stars_acc': (stars_correct, len(all_stars_true)),
        'moon_acc': (moon_correct, len(all_moon_true)),
        'train_n': len(train_samples),
        'test_n': len(test_samples),
        'params': sum(p.numel() for p in model.parameters()),
        'model_path': str(model_path),
    }


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Train sky/celestial classifier")
    parser.add_argument("--data-dir", type=str, default=r"D:\Pier Camera ML Data",
                        help="Directory containing calibration files")
    parser.add_argument("--output-dir", type=str, default="ml/models",
                        help="Output directory for model")
    parser.add_argument("--image-size", type=int, default=256,
                        help="Image size (default: 256)")
    parser.add_argument("--batch-size", type=int, default=64,
                        help="Batch size (default: 64 for GPU)")
    parser.add_argument("--epochs", type=int, default=50,
                        help="Number of epochs")
    parser.add_argument("--lr", type=float, default=0.001,
                        help="Learning rate")
    
    args = parser.parse_args()
    
    train_model(
        data_dir=Path(args.data_dir),
        output_dir=Path(args.output_dir),
        image_size=args.image_size,
        batch_size=args.batch_size,
        epochs=args.epochs,
        learning_rate=args.lr,
    )


if __name__ == "__main__":
    main()
