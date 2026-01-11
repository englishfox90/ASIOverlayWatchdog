#!/usr/bin/env python3
"""
Phase 1: Roof State Classifier Training

Trains a CNN model to detect if the observatory roof is open or closed
from pier camera images.

Usage:
    python ml/train_roof_classifier.py "E:\Pier Camera ML Data"
    python ml/train_roof_classifier.py --epochs 50 --batch-size 16
"""
import sys
import json
import argparse
import random
from pathlib import Path
from datetime import datetime

import numpy as np

# Check for required packages
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    print("PyTorch not installed. Run: pip install torch torchvision")
    sys.exit(1)

try:
    from astropy.io import fits
    ASTROPY_AVAILABLE = True
except ImportError:
    ASTROPY_AVAILABLE = False
    print("Astropy not installed. Run: pip install astropy")
    sys.exit(1)

try:
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import classification_report, confusion_matrix
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    print("Scikit-learn not installed. Run: pip install scikit-learn")
    sys.exit(1)


# ============================================================================
# Dataset
# ============================================================================

class RoofDataset(Dataset):
    """Dataset for roof state classification."""
    
    def __init__(self, samples: list, image_size: int = 128, augment: bool = False):
        """
        Args:
            samples: List of dicts with 'fits_path', 'label', 'metadata'
            image_size: Resize images to this size (square)
            augment: Apply data augmentation
        """
        self.samples = samples
        self.image_size = image_size
        self.augment = augment
    
    def __len__(self):
        return len(self.samples)
    
    def __getitem__(self, idx):
        sample = self.samples[idx]
        
        # Load FITS image
        image = self.load_fits(sample['fits_path'])
        
        # Apply augmentation if training
        if self.augment:
            image = self.apply_augmentation(image)
        
        # Normalize to [0, 1]
        image = self.normalize(image)
        
        # Convert to tensor (C, H, W)
        image_tensor = torch.from_numpy(image).float().unsqueeze(0)
        
        # Get label
        label = torch.tensor(1.0 if sample['label'] else 0.0).float()
        
        # Get metadata features
        metadata = sample.get('metadata', {})
        meta_features = torch.tensor([
            metadata.get('corner_to_center_ratio', 1.0),
            metadata.get('median_lum', 0.0),
            metadata.get('is_astronomical_night', 0),
            metadata.get('hour', 12) / 24.0,
        ]).float()
        
        return image_tensor, meta_features, label
    
    def load_fits(self, fits_path: Path) -> np.ndarray:
        """Load and resize FITS image."""
        try:
            with fits.open(fits_path) as hdul:
                data = hdul[0].data
            
            if data is None:
                return np.zeros((self.image_size, self.image_size), dtype=np.float32)
            
            # Resize using simple averaging
            data = data.astype(np.float32)
            data = self.resize_image(data, self.image_size)
            
            return data
        except Exception as e:
            print(f"Warning: Failed to load {fits_path}: {e}")
            return np.zeros((self.image_size, self.image_size), dtype=np.float32)
    
    def resize_image(self, img: np.ndarray, size: int) -> np.ndarray:
        """Simple resize using block averaging."""
        h, w = img.shape
        
        # Calculate block size
        block_h = h // size
        block_w = w // size
        
        if block_h == 0 or block_w == 0:
            # Image smaller than target, just pad/crop
            result = np.zeros((size, size), dtype=np.float32)
            copy_h = min(h, size)
            copy_w = min(w, size)
            result[:copy_h, :copy_w] = img[:copy_h, :copy_w]
            return result
        
        # Trim to exact multiple
        trimmed = img[:block_h * size, :block_w * size]
        
        # Reshape and average
        result = trimmed.reshape(size, block_h, size, block_w).mean(axis=(1, 3))
        
        return result
    
    def normalize(self, image: np.ndarray) -> np.ndarray:
        """Normalize image to [0, 1] with percentile clipping."""
        p1, p99 = np.percentile(image, [1, 99])
        if p99 > p1:
            image = (image - p1) / (p99 - p1)
        image = np.clip(image, 0, 1)
        return image
    
    def apply_augmentation(self, image: np.ndarray) -> np.ndarray:
        """Apply random augmentations."""
        # Random horizontal flip
        if random.random() > 0.5:
            image = np.fliplr(image).copy()
        
        # Random vertical flip
        if random.random() > 0.5:
            image = np.flipud(image).copy()
        
        # Random rotation (90 degree increments)
        k = random.randint(0, 3)
        if k > 0:
            image = np.rot90(image, k).copy()
        
        # Random brightness adjustment
        if random.random() > 0.5:
            factor = random.uniform(0.8, 1.2)
            image = image * factor
        
        return image


# ============================================================================
# Model
# ============================================================================

class RoofClassifierCNN(nn.Module):
    """CNN for roof state classification with metadata fusion."""
    
    def __init__(self, image_size: int = 128, num_meta_features: int = 4):
        super().__init__()
        
        # CNN backbone for image
        self.conv_layers = nn.Sequential(
            # Block 1: 128 -> 64
            nn.Conv2d(1, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.MaxPool2d(2),
            
            # Block 2: 64 -> 32
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.MaxPool2d(2),
            
            # Block 3: 32 -> 16
            nn.Conv2d(64, 128, kernel_size=3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(),
            nn.MaxPool2d(2),
            
            # Block 4: 16 -> 8
            nn.Conv2d(128, 256, kernel_size=3, padding=1),
            nn.BatchNorm2d(256),
            nn.ReLU(),
            nn.MaxPool2d(2),
            
            # Block 5: 8 -> 4
            nn.Conv2d(256, 256, kernel_size=3, padding=1),
            nn.BatchNorm2d(256),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d(4),
        )
        
        # Calculate flattened size
        self.cnn_output_size = 256 * 4 * 4  # 4096
        
        # Metadata branch
        self.meta_layers = nn.Sequential(
            nn.Linear(num_meta_features, 32),
            nn.ReLU(),
            nn.Linear(32, 64),
            nn.ReLU(),
        )
        
        # Fusion and classification
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
        # CNN branch
        x = self.conv_layers(image)
        x = x.view(x.size(0), -1)  # Flatten
        
        # Metadata branch
        m = self.meta_layers(metadata)
        
        # Fusion
        combined = torch.cat([x, m], dim=1)
        
        # Classification
        output = self.classifier(combined)
        
        return output


# ============================================================================
# Training
# ============================================================================

def load_dataset(data_dir: Path) -> list:
    """Load all labeled samples from data directory."""
    samples = []
    
    # Find all calibration files
    for cal_file in data_dir.rglob("calibration_*.json"):
        try:
            with open(cal_file, 'r') as f:
                cal_data = json.load(f)
            
            # Check if labeled
            labels = cal_data.get('labels', {})
            if not labels.get('labeled_at'):
                continue
            
            # Get corresponding FITS file
            timestamp = cal_file.stem.replace('calibration_', '')
            fits_path = cal_file.parent / f"lum_{timestamp}.fits"
            
            if not fits_path.exists():
                continue
            
            # Extract metadata
            tc = cal_data.get('time_context', {})
            ca = cal_data.get('corner_analysis', {})
            st = cal_data.get('stretch', {})
            
            sample = {
                'fits_path': fits_path,
                'cal_path': cal_file,
                'label': labels.get('roof_open', False),
                'metadata': {
                    'corner_to_center_ratio': ca.get('corner_to_center_ratio', 1.0),
                    'median_lum': st.get('median_lum', 0.0),
                    'is_astronomical_night': 1 if tc.get('is_astronomical_night') else 0,
                    'hour': tc.get('hour', 12),
                }
            }
            samples.append(sample)
            
        except Exception as e:
            print(f"Warning: Failed to load {cal_file}: {e}")
    
    return samples


def train_epoch(model, loader, criterion, optimizer, device):
    """Train for one epoch."""
    model.train()
    total_loss = 0
    correct = 0
    total = 0
    
    for images, metadata, labels in loader:
        images = images.to(device)
        metadata = metadata.to(device)
        labels = labels.to(device)
        
        optimizer.zero_grad()
        outputs = model(images, metadata).squeeze()
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()
        
        total_loss += loss.item()
        predictions = (torch.sigmoid(outputs) > 0.5).float()
        correct += (predictions == labels).sum().item()
        total += labels.size(0)
    
    return total_loss / len(loader), correct / total


def evaluate(model, loader, criterion, device):
    """Evaluate model on a dataset."""
    model.eval()
    total_loss = 0
    all_preds = []
    all_labels = []
    
    with torch.no_grad():
        for images, metadata, labels in loader:
            images = images.to(device)
            metadata = metadata.to(device)
            labels = labels.to(device)
            
            outputs = model(images, metadata).squeeze()
            loss = criterion(outputs, labels)
            
            total_loss += loss.item()
            predictions = (torch.sigmoid(outputs) > 0.5).float()
            
            all_preds.extend(predictions.cpu().numpy())
            all_labels.extend(labels.cpu().numpy())
    
    all_preds = np.array(all_preds)
    all_labels = np.array(all_labels)
    
    accuracy = (all_preds == all_labels).mean()
    
    return total_loss / len(loader), accuracy, all_preds, all_labels


def main():
    parser = argparse.ArgumentParser(description="Train roof state classifier")
    parser.add_argument("data_dir", nargs="?", default=r"E:\Pier Camera ML Data",
                        help="Directory containing labeled calibration files")
    parser.add_argument("--epochs", type=int, default=30, help="Number of training epochs")
    parser.add_argument("--batch-size", type=int, default=16, help="Batch size")
    parser.add_argument("--lr", type=float, default=0.001, help="Learning rate")
    parser.add_argument("--image-size", type=int, default=128, help="Image size for model")
    parser.add_argument("--output", type=str, default="ml/models/roof_classifier_v1.pth",
                        help="Output model path")
    args = parser.parse_args()
    
    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Error: Directory not found: {data_dir}")
        sys.exit(1)
    
    # Set device
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")
    
    # Load dataset
    print(f"\nLoading labeled samples from: {data_dir}")
    samples = load_dataset(data_dir)
    
    if len(samples) < 10:
        print(f"Error: Not enough labeled samples ({len(samples)}). Need at least 10.")
        sys.exit(1)
    
    # Count classes
    n_open = sum(1 for s in samples if s['label'])
    n_closed = sum(1 for s in samples if not s['label'])
    print(f"Found {len(samples)} labeled samples: {n_open} open, {n_closed} closed")
    
    # Split into train/val/test
    train_samples, test_samples = train_test_split(
        samples, test_size=0.2, random_state=42,
        stratify=[s['label'] for s in samples]
    )
    train_samples, val_samples = train_test_split(
        train_samples, test_size=0.15, random_state=42,
        stratify=[s['label'] for s in train_samples]
    )
    
    print(f"Split: {len(train_samples)} train, {len(val_samples)} val, {len(test_samples)} test")
    
    # Create datasets
    train_dataset = RoofDataset(train_samples, image_size=args.image_size, augment=True)
    val_dataset = RoofDataset(val_samples, image_size=args.image_size, augment=False)
    test_dataset = RoofDataset(test_samples, image_size=args.image_size, augment=False)
    
    # Handle class imbalance with weighted sampler
    train_labels = [s['label'] for s in train_samples]
    class_counts = [train_labels.count(False), train_labels.count(True)]
    class_weights = [1.0 / c if c > 0 else 0 for c in class_counts]
    sample_weights = [class_weights[1 if label else 0] for label in train_labels]
    sampler = WeightedRandomSampler(sample_weights, len(sample_weights))
    
    # Create data loaders
    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, sampler=sampler)
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size, shuffle=False)
    test_loader = DataLoader(test_dataset, batch_size=args.batch_size, shuffle=False)
    
    # Create model
    model = RoofClassifierCNN(image_size=args.image_size).to(device)
    print(f"\nModel created with {sum(p.numel() for p in model.parameters()):,} parameters")
    
    # Loss and optimizer
    # Use class weights in loss for additional balancing
    pos_weight = torch.tensor([n_closed / n_open if n_open > 0 else 1.0]).to(device)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = optim.Adam(model.parameters(), lr=args.lr)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', patience=5, factor=0.5)
    
    # Training loop
    print(f"\n{'='*60}")
    print("Starting training...")
    print(f"{'='*60}")
    
    best_val_acc = 0
    best_epoch = 0
    
    for epoch in range(args.epochs):
        train_loss, train_acc = train_epoch(model, train_loader, criterion, optimizer, device)
        val_loss, val_acc, _, _ = evaluate(model, val_loader, criterion, device)
        
        scheduler.step(val_loss)
        
        # Save best model
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_epoch = epoch + 1
            
            # Save checkpoint
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            torch.save({
                'epoch': epoch,
                'model_state_dict': model.state_dict(),
                'optimizer_state_dict': optimizer.state_dict(),
                'val_acc': val_acc,
                'args': vars(args),
            }, output_path)
        
        print(f"Epoch {epoch+1:3d}/{args.epochs} | "
              f"Train Loss: {train_loss:.4f} Acc: {train_acc:.4f} | "
              f"Val Loss: {val_loss:.4f} Acc: {val_acc:.4f} "
              f"{'*' if epoch + 1 == best_epoch else ''}")
    
    # Load best model for final evaluation
    checkpoint = torch.load(args.output, weights_only=False)
    model.load_state_dict(checkpoint['model_state_dict'])
    
    # Final evaluation on test set
    print(f"\n{'='*60}")
    print(f"Final Evaluation (Best model from epoch {best_epoch})")
    print(f"{'='*60}")
    
    test_loss, test_acc, preds, labels = evaluate(model, test_loader, criterion, device)
    
    print(f"\nTest Accuracy: {test_acc:.4f} ({test_acc*100:.1f}%)")
    print(f"\nClassification Report:")
    print(classification_report(labels.astype(int), preds.astype(int), 
                                target_names=['Closed', 'Open']))
    
    print(f"\nConfusion Matrix:")
    cm = confusion_matrix(labels.astype(int), preds.astype(int))
    print(f"              Predicted")
    print(f"              Closed  Open")
    print(f"Actual Closed   {cm[0,0]:4d}  {cm[0,1]:4d}")
    print(f"       Open     {cm[1,0]:4d}  {cm[1,1]:4d}")
    
    print(f"\nModel saved to: {args.output}")
    
    # Export to ONNX for production
    onnx_path = Path(args.output).with_suffix('.onnx')
    print(f"\nExporting to ONNX: {onnx_path}")
    
    try:
        model.eval()
        dummy_image = torch.randn(1, 1, args.image_size, args.image_size).to(device)
        dummy_meta = torch.randn(1, 4).to(device)
        
        torch.onnx.export(
            model,
            (dummy_image, dummy_meta),
            onnx_path,
            input_names=['image', 'metadata'],
            output_names=['roof_open_logit'],
            dynamic_axes={
                'image': {0: 'batch'},
                'metadata': {0: 'batch'},
                'roof_open_logit': {0: 'batch'}
            },
            opset_version=11
        )
        print(f"ONNX model saved to: {onnx_path}")
    except Exception as e:
        print(f"ONNX export failed: {e}")
        print("You can still use the .pth model with PyTorch")
        print("To enable ONNX export, run: pip install onnxscript")
    
    print(f"\n{'='*60}")
    print("Training complete!")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
