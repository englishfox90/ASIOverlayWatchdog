#!/usr/bin/env python3
"""
Sky/Celestial Classifier Training - Phase 2

Multi-task model trained on PIER CAMERA images to predict:
- sky_condition: 5-class (Clear, Mostly Clear, Partly Cloudy, Mostly Cloudy, Overcast)
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
import json
import random
from pathlib import Path
from datetime import datetime
from collections import Counter

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
from torch.amp import autocast, GradScaler

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Optional: astropy for FITS
try:
    from astropy.io import fits
    ASTROPY_AVAILABLE = True
except ImportError:
    ASTROPY_AVAILABLE = False
    print("Warning: astropy not available, FITS loading disabled")


# Sky condition class mapping
SKY_CONDITIONS = ['Clear', 'Mostly Clear', 'Partly Cloudy', 'Mostly Cloudy', 'Overcast']
SKY_TO_IDX = {cond: i for i, cond in enumerate(SKY_CONDITIONS)}
IDX_TO_SKY = {i: cond for i, cond in enumerate(SKY_CONDITIONS)}


class SkyDataset(Dataset):
    """Dataset for sky/celestial classification from pier camera images."""
    
    def __init__(self, samples: list, image_size: int = 256, augment: bool = False, preload: bool = True):
        """
        Args:
            samples: List of dicts with 'lum_path', 'sky_condition', 'stars_visible', 
                     'star_density', 'moon_visible', 'metadata'
            image_size: Target image size (larger than roof model)
            augment: Whether to apply data augmentation
            preload: Whether to preload all images into memory (faster training)
        """
        self.samples = samples
        self.image_size = image_size
        self.augment = augment
        self.preload = preload
        
        # Pre-compute all tensors for maximum speed
        self.images = []
        self.metadata = []
        self.labels = []
        
        if preload:
            print(f"  Preloading {len(samples)} images...")
            for i, sample in enumerate(samples):
                # Load and preprocess image (supports FITS and JPG)
                img = self.load_image(sample['image_path'])
                img = self.preprocess(img)
                # Store as tensor ready for GPU
                self.images.append(torch.from_numpy(img).unsqueeze(0).float())
                
                # Pre-compute metadata tensor
                meta = sample['metadata']
                meta_tensor = torch.tensor([
                    meta.get('corner_to_center_ratio', 1.0),
                    meta.get('median_lum', 0.0),
                    1.0 if meta.get('is_astronomical_night') else 0.0,
                    meta.get('hour', 12) / 24.0,
                    meta.get('moon_illumination', 0.0) / 100.0,
                    1.0 if meta.get('moon_is_up') else 0.0,
                ], dtype=torch.float32)
                self.metadata.append(meta_tensor)
                
                # Pre-compute labels
                sky_idx = SKY_TO_IDX.get(sample['sky_condition'], 0)
                stars_visible = 1.0 if sample['stars_visible'] else 0.0
                star_density = float(sample.get('star_density', 0.0))
                moon_visible = 1.0 if sample['moon_visible'] else 0.0
                self.labels.append({
                    'sky': torch.tensor(sky_idx, dtype=torch.long),
                    'stars': torch.tensor(stars_visible, dtype=torch.float32),
                    'density': torch.tensor(star_density, dtype=torch.float32),
                    'moon': torch.tensor(moon_visible, dtype=torch.float32),
                })
                
                if (i + 1) % 100 == 0:
                    print(f"    Loaded {i + 1}/{len(samples)}")
            print(f"  ✓ Preloaded {len(samples)} images")
    
    def __len__(self):
        return len(self.samples)
    
    def __getitem__(self, idx):
        if self.preload:
            image = self.images[idx].clone()
            
            # GPU-friendly augmentation (simple transforms)
            if self.augment:
                # Random flip (horizontal)
                if random.random() > 0.5:
                    image = torch.flip(image, [2])
                # Random flip (vertical)
                if random.random() > 0.5:
                    image = torch.flip(image, [1])
                # Random brightness
                image = image * random.uniform(0.9, 1.1)
                image = torch.clamp(image, 0, 1)
            
            return {
                'image': image,
                'metadata': self.metadata[idx],
                'sky_condition': self.labels[idx]['sky'],
                'stars_visible': self.labels[idx]['stars'],
                'star_density': self.labels[idx]['density'],
                'moon_visible': self.labels[idx]['moon'],
            }
        else:
            # Fallback to disk loading (slow)
            sample = self.samples[idx]
            image = self.load_image(sample['image_path'])
            image = self.preprocess(image)
            image_tensor = torch.from_numpy(image).unsqueeze(0).float()
            
            meta = sample['metadata']
            meta_tensor = torch.tensor([
                meta.get('corner_to_center_ratio', 1.0),
                meta.get('median_lum', 0.0),
                1.0 if meta.get('is_astronomical_night') else 0.0,
                meta.get('hour', 12) / 24.0,
                meta.get('moon_illumination', 0.0) / 100.0,
                1.0 if meta.get('moon_is_up') else 0.0,
            ], dtype=torch.float32)
            
            sky_idx = SKY_TO_IDX.get(sample['sky_condition'], 0)
            
            return {
                'image': image_tensor,
                'metadata': meta_tensor,
                'sky_condition': torch.tensor(sky_idx, dtype=torch.long),
                'stars_visible': torch.tensor(1.0 if sample['stars_visible'] else 0.0, dtype=torch.float32),
                'star_density': torch.tensor(float(sample.get('star_density', 0.0)), dtype=torch.float32),
                'moon_visible': torch.tensor(1.0 if sample['moon_visible'] else 0.0, dtype=torch.float32),
            }
    
    def load_fits(self, path: Path) -> np.ndarray:
        """Load FITS file as numpy array."""
        with fits.open(path) as hdul:
            data = hdul[0].data
        return data.astype(np.float32)
    
    def load_jpg(self, path: Path) -> np.ndarray:
        """Load JPG file as grayscale numpy array."""
        from PIL import Image
        img = Image.open(path).convert('L')  # Convert to grayscale
        return np.array(img, dtype=np.float32)
    
    def load_image(self, path: Path) -> np.ndarray:
        """Load image file (FITS or JPG)."""
        if str(path).lower().endswith('.fits'):
            return self.load_fits(path)
        else:
            return self.load_jpg(path)
    
    def preprocess(self, image: np.ndarray) -> np.ndarray:
        """Preprocess image: normalize, resize, stretch."""
        # Normalize to 0-1
        p1, p99 = np.percentile(image, [1, 99])
        if p99 > p1:
            image = (image - p1) / (p99 - p1)
        image = np.clip(image, 0, 1)
        
        # Arcsinh stretch for better star visibility
        stretch = 10.0
        image = np.arcsinh(image * stretch) / np.arcsinh(stretch)
        
        # Resize using block averaging
        image = self.resize_image(image, self.image_size)
        
        return image.astype(np.float32)
    
    def resize_image(self, img: np.ndarray, size: int) -> np.ndarray:
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
            
            # Must have sky_condition label
            sky_cond = labels.get('sky_condition')
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


def train_model(
    data_dir: Path,
    output_dir: Path,
    image_size: int = 256,
    batch_size: int = 64,  # Larger batch for GPU saturation
    epochs: int = 50,
    learning_rate: float = 0.001,
    val_split: float = 0.15,
):
    """
    Train the sky/celestial classifier with GPU optimization.
    
    Training strategy:
    - Train on: Pier camera (roof open) + All-sky camera (all labeled)
    - Validate on: Pier camera only (matches production)
    """
    
    print("=" * 60)
    print("Sky/Celestial Classifier Training - Phase 2")
    print("=" * 60)
    
    # Load dataset - separate pier and all-sky
    pier_samples, allsky_samples = load_dataset(data_dir)
    
    if len(pier_samples) < 20:
        print(f"Error: Need at least 20 pier samples for validation, got {len(pier_samples)}")
        return None
    
    # Split PIER samples into train/val (validation is pier-only)
    random.shuffle(pier_samples)
    val_size = max(int(len(pier_samples) * val_split), 10)  # At least 10 for validation
    val_samples = pier_samples[:val_size]
    pier_train_samples = pier_samples[val_size:]
    
    # Training = pier (roof open) + all-sky
    train_samples = pier_train_samples + allsky_samples
    random.shuffle(train_samples)
    
    # Calculate totals
    all_train = train_samples
    
    print(f"\n=== Dataset Split ===")
    print(f"Training:   {len(train_samples)} total")
    print(f"  - Pier camera (roof open): {len(pier_train_samples)}")
    print(f"  - All-sky camera:          {len(allsky_samples)}")
    print(f"Validation: {len(val_samples)} (pier camera only)")
    
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
    
    # With preloaded data, we don't need multiprocessing - data is already in RAM
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, 
                              num_workers=0, pin_memory=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, 
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
    
    # Loss functions
    criterion_sky = nn.CrossEntropyLoss()
    criterion_binary = nn.BCEWithLogitsLoss()
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
                loss_stars = criterion_binary(stars_logit.squeeze(), stars_labels)
                loss_density = criterion_density(density.squeeze(), density_labels)
                loss_moon = criterion_binary(moon_logit.squeeze(), moon_labels)
                
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
                    loss_stars = criterion_binary(stars_logit.squeeze(), stars_labels)
                    loss_density = criterion_density(density.squeeze(), density_labels)
                    loss_moon = criterion_binary(moon_logit.squeeze(), moon_labels)
                    loss = 1.0 * loss_sky + 0.5 * loss_stars + 0.3 * loss_density + 0.5 * loss_moon
                
                val_loss += loss.item()
                
                # Accuracy
                sky_pred = sky_logits.argmax(dim=1)
                sky_correct += (sky_pred == sky_labels).sum().item()
                
                stars_pred = (torch.sigmoid(stars_logit.squeeze()) > 0.5).float()
                stars_correct += (stars_pred == stars_labels).sum().item()
                
                moon_pred = (torch.sigmoid(moon_logit.squeeze()) > 0.5).float()
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
        
        # Save best model
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_model_state = model.state_dict().copy()
    
    # Load best model
    model.load_state_dict(best_model_state)
    
    # Save model
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / 'sky_classifier_v1.pth'
    
    torch.save({
        'model_state_dict': best_model_state,
        'image_size': image_size,
        'metadata_features': 6,
        'sky_conditions': SKY_CONDITIONS,
        'trained_at': datetime.now().isoformat(),
        'train_samples_total': len(train_samples),
        'train_samples_pier': len(pier_train_samples),
        'train_samples_allsky': len(allsky_samples),
        'val_samples': len(val_samples),
        'epochs': epochs,
    }, model_path)
    
    print(f"\n✓ Model saved to: {model_path}")
    
    # Final evaluation
    print("\n" + "=" * 60)
    print("Final Evaluation on Validation Set")
    print("=" * 60)
    
    model.eval()
    all_sky_true = []
    all_sky_pred = []
    all_stars_true = []
    all_stars_pred = []
    all_moon_true = []
    all_moon_pred = []
    
    with torch.no_grad():
        for batch in val_loader:
            images = batch['image'].to(device)
            metadata = batch['metadata'].to(device)
            
            sky_logits, stars_logit, density, moon_logit = model(images, metadata)
            
            all_sky_true.extend(batch['sky_condition'].numpy())
            all_sky_pred.extend(sky_logits.argmax(dim=1).cpu().numpy())
            
            all_stars_true.extend(batch['stars_visible'].numpy())
            all_stars_pred.extend((torch.sigmoid(stars_logit.squeeze()) > 0.5).cpu().numpy())
            
            all_moon_true.extend(batch['moon_visible'].numpy())
            all_moon_pred.extend((torch.sigmoid(moon_logit.squeeze()) > 0.5).cpu().numpy())
    
    # Sky condition confusion
    print("\nSky Condition Accuracy:")
    sky_correct = sum(1 for t, p in zip(all_sky_true, all_sky_pred) if t == p)
    print(f"  {sky_correct}/{len(all_sky_true)} ({sky_correct/len(all_sky_true)*100:.1f}%)")
    
    print("\nSky Condition per class:")
    for i, cond in enumerate(SKY_CONDITIONS):
        class_total = sum(1 for t in all_sky_true if t == i)
        class_correct = sum(1 for t, p in zip(all_sky_true, all_sky_pred) if t == i and p == i)
        if class_total > 0:
            print(f"  {cond}: {class_correct}/{class_total} ({class_correct/class_total*100:.1f}%)")
    
    print(f"\nStars Visible Accuracy:")
    stars_correct = sum(1 for t, p in zip(all_stars_true, all_stars_pred) if t == p)
    print(f"  {stars_correct}/{len(all_stars_true)} ({stars_correct/len(all_stars_true)*100:.1f}%)")
    
    print(f"\nMoon Visible Accuracy:")
    moon_correct = sum(1 for t, p in zip(all_moon_true, all_moon_pred) if t == p)
    print(f"  {moon_correct}/{len(all_moon_true)} ({moon_correct/len(all_moon_true)*100:.1f}%)")
    
    return model


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Train sky/celestial classifier")
    parser.add_argument("--data-dir", type=str, default=r"E:\Pier Camera ML Data",
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
