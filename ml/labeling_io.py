#!/usr/bin/env python3
import shutil
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage

try:
    from astropy.io import fits
    ASTROPY_AVAILABLE = True
except ImportError:
    ASTROPY_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


def find_sample_sets(data_dir: Path) -> list:
    """Find all sample sets by timestamp (searches recursively).

    Returns list of dicts with paths to each file type.
    """
    samples = {}

    for cal_file in data_dir.rglob("calibration_*.json"):
        name = cal_file.stem
        if name.startswith("calibration_"):
            timestamp = name[len("calibration_"):]

            if timestamp not in samples:
                samples[timestamp] = {
                    'timestamp': timestamp,
                    'folder': cal_file.parent
                }

            samples[timestamp]['calibration'] = cal_file

    for timestamp, sample in samples.items():
        folder = sample['folder']
        lum_path = folder / f"lum_{timestamp}.fits"

        if lum_path.exists():
            sample['lum'] = lum_path

    return [samples[ts] for ts in sorted(samples.keys())]


def remove_sample_files(sample: dict, trash_dir: Path) -> list:
    """Move a sample's files (calibration JSON + lum FITS) to trash_dir.

    Recoverable by design — moves rather than deletes. Name-collisions in the
    trash get a numeric suffix so an earlier removal is never clobbered. Returns
    the list of destination paths actually moved.
    """
    trash_dir = Path(trash_dir)
    trash_dir.mkdir(parents=True, exist_ok=True)
    moved = []
    for key in ('calibration', 'lum'):
        src = sample.get(key)
        if not src or not Path(src).is_file():
            continue
        src = Path(src)
        dest = trash_dir / src.name
        n = 1
        while dest.exists():
            dest = trash_dir / f"{src.stem}_{n}{src.suffix}"
            n += 1
        shutil.move(str(src), str(dest))
        moved.append(dest)
    return moved


def create_placeholder_pixmap(text: str, size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.darkGray)
    return pixmap


def stretch_fits_to_uint8(fits_path: Path):
    """Load a FITS frame and return an arcsinh-stretched 8-bit grayscale array.

    This is the single source of truth for how a lum frame is rendered for human
    eyes — the AI labeler sends the *same* stretch so its judgement matches what a
    person sees in the tool. Returns None if astropy is missing or the frame is empty.
    """
    if not ASTROPY_AVAILABLE:
        return None

    with fits.open(fits_path) as hdul:
        data = hdul[0].data

    if data is None:
        return None

    data = data.astype(np.float32)

    vmin, vmax = np.percentile(data, [1, 99])
    if vmax > vmin:
        data = (data - vmin) / (vmax - vmin)
    data = np.clip(data, 0, 1)

    stretch = 5.0
    data = np.arcsinh(data * stretch) / np.arcsinh(stretch)

    return (data * 255).astype(np.uint8)


def load_fits_as_qpixmap(fits_path: Path, target_size: int = 400) -> QPixmap:
    """Load FITS file and return as QPixmap with basic stretch."""
    if not ASTROPY_AVAILABLE:
        return create_placeholder_pixmap("FITS not available\n(install astropy)", target_size)

    try:
        img_8bit = stretch_fits_to_uint8(fits_path)
        if img_8bit is None:
            return create_placeholder_pixmap("No image data", target_size)

        h, w = img_8bit.shape
        qimg = QImage(img_8bit.data, w, h, w, QImage.Format_Grayscale8)
        pixmap = QPixmap.fromImage(qimg.copy())

        return pixmap.scaled(target_size, target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)

    except Exception as e:
        return create_placeholder_pixmap(f"Error: {e}", target_size)


def fits_to_jpeg_bytes(fits_path: Path, max_size: int = 768, quality: int = 85) -> bytes:
    """Render a lum FITS frame to JPEG bytes for sending to a vision model.

    Uses the same stretch as the on-screen preview so the model sees what the
    labeller sees. Downsizes to max_size to keep token cost low. Raises on failure.
    """
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow not available — cannot encode JPEG")

    img_8bit = stretch_fits_to_uint8(fits_path)
    if img_8bit is None:
        raise ValueError(f"No usable image data in {fits_path}")

    img = Image.fromarray(img_8bit, mode="L")
    img.thumbnail((max_size, max_size), Image.LANCZOS)

    import io
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()
