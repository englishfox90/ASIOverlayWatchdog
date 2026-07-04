#!/usr/bin/env python3
"""
Dataset + label constants for the sky/celestial classifier (Phase 2).

Extracted from train_sky_classifier.py so the training module stays within the
file-size budget and the data-loading responsibility lives on its own.
"""
import os
import random
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import torch
from torch.utils.data import Dataset

try:
    from astropy.io import fits
    ASTROPY_AVAILABLE = True
except ImportError:
    ASTROPY_AVAILABLE = False

try:
    from ml.image_preprocess import resize_for_model
except ImportError:  # run as a script: ml/ is on path, not the project root
    from image_preprocess import resize_for_model


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

    def __init__(self, samples: list, image_size: int = 256, augment: bool = False,
                 preload: bool = True, preload_workers: int = None):
        """
        Args:
            samples: List of dicts with 'lum_path', 'sky_condition', 'stars_visible',
                     'star_density', 'moon_visible', 'metadata'
            image_size: Target image size (larger than roof model)
            augment: Whether to apply data augmentation
            preload: Whether to preload all images into memory (faster training)
            preload_workers: Threads for the preload (defaults to min(cpu_count, 16))
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
            workers = preload_workers or min((os.cpu_count() or 4), 16)
            print(f"  Preloading {len(samples)} images ({workers} workers)...")
            # The FITS read + arcsinh stretch is the heavy, parallelisable part.
            # load_image/preprocess are pure reads (no shared mutable state), so
            # threads are safe and numpy/astropy release the GIL during the read
            # and the big-array math. ThreadPoolExecutor.map preserves order, so
            # images[idx] stays aligned with samples[idx].
            with ThreadPoolExecutor(max_workers=workers) as ex:
                self.images = list(ex.map(self._load_tensor, samples))

            # Metadata/labels are cheap scalar work — build them serially.
            for sample in samples:
                meta = sample['metadata']
                self.metadata.append(torch.tensor([
                    meta.get('corner_to_center_ratio', 1.0),
                    meta.get('median_lum', 0.0),
                    1.0 if meta.get('is_astronomical_night') else 0.0,
                    meta.get('hour', 12) / 24.0,
                    meta.get('moon_illumination', 0.0) / 100.0,
                    1.0 if meta.get('moon_is_up') else 0.0,
                ], dtype=torch.float32))
                self.labels.append({
                    'sky': torch.tensor(SKY_TO_IDX.get(sample['sky_condition'], 0), dtype=torch.long),
                    'stars': torch.tensor(1.0 if sample['stars_visible'] else 0.0, dtype=torch.float32),
                    'density': torch.tensor(float(sample.get('star_density', 0.0)), dtype=torch.float32),
                    'moon': torch.tensor(1.0 if sample['moon_visible'] else 0.0, dtype=torch.float32),
                })
            print(f"  ✓ Preloaded {len(samples)} images")

    def _load_tensor(self, sample) -> torch.Tensor:
        """Load + preprocess one image to a (1, H, W) tensor. Thread-safe."""
        img = self.preprocess(self.load_image(sample['image_path']))
        return torch.from_numpy(img).unsqueeze(0).float()

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
        image = resize_for_model(image, self.image_size)

        return image.astype(np.float32)
