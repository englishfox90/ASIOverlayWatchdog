#!/usr/bin/env python3
"""
Dataset + label constants for the sky/celestial classifier (Phase 2).

Extracted from train_sky_classifier.py so the training module stays within the
file-size budget and the data-loading responsibility lives on its own.
"""
import random
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset

try:
    from astropy.io import fits
    ASTROPY_AVAILABLE = True
except ImportError:
    ASTROPY_AVAILABLE = False


# Sky condition classes. Collapsed from the original 5-class scheme to 3: the
# open-roof pier set is overwhelmingly "Clear" (you only image on clear nights),
# which starved the in-between buckets (Mostly Cloudy had 8 training samples).
SKY_CONDITIONS = ['Clear', 'Partly Cloudy', 'Overcast']
SKY_TO_IDX = {cond: i for i, cond in enumerate(SKY_CONDITIONS)}
IDX_TO_SKY = {i: cond for i, cond in enumerate(SKY_CONDITIONS)}

# Folds the old 5-class labels (and labeling-only classes like Fog/Haze) into the
# nearest of the 3. Single source of truth for the label migration, the labeling
# tool, and load-time folding of any legacy label.
SKY_CONDITION_COLLAPSE = {
    'Clear': 'Clear',
    'Mostly Clear': 'Clear',
    'Partly Cloudy': 'Partly Cloudy',
    'Mostly Cloudy': 'Overcast',
    'Overcast': 'Overcast',
    'Fog/Haze': 'Overcast',
}


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
