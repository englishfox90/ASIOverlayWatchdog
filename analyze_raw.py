"""
Standalone script to analyze raw FITS/TIFF images and test stretch algorithms.

Usage:
    python analyze_raw.py path/to/raw_image.fits
    
This tool helps determine optimal stretch parameters for dark images by:
- Loading raw FITS/TIFF data
- Analyzing per-channel statistics
- Testing various stretch algorithms with different parameters
- Displaying side-by-side comparisons
"""

import sys
import os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from PIL import Image


def _infer_fits_normalization(data, header, scaled, mul16_rate, bit_depth, img_bits):
    """
    Infer the correct normalization denominator for FITS data.
    
    Priority:
    1. If SCALED=True -> RAW8 scaled to uint16, use 65535 (already 0-65535 range)
    2. If MUL16RAT > 1 -> 12-bit left-shifted, use 65535 (data fills 16-bit range)
    3. If IMGBITS=8 or dtype=uint8 -> use 255
    4. If BITDEPTH known -> use (2^BITDEPTH - 1) e.g., 4095 for 12-bit
    5. Auto-detect from data range as fallback
    
    Returns:
        float: Normalization denominator
    """
    # Case 1: RAW8 scaled to uint16
    if scaled:
        return 65535.0
    
    # Case 2: Left-shifted 12-bit data
    if mul16_rate > 1:
        return 65535.0
    
    # Case 3: 8-bit data
    if img_bits == 8 or data.dtype == np.uint8:
        return 255.0
    
    # Case 4: Use ADC bit depth if known
    if bit_depth not in ('N/A', None) and isinstance(bit_depth, (int, float)):
        bit_depth = int(bit_depth)
        if bit_depth == 12:
            # Check if data actually uses 12-bit range or full 16-bit
            max_val = np.max(data)
            if max_val > 4095:
                # Data exceeds 12-bit, probably left-shifted or scaled
                return 65535.0
            else:
                return 4095.0
        elif bit_depth == 14:
            return 16383.0
        elif bit_depth == 16:
            return 65535.0
        elif bit_depth == 8:
            return 255.0
    
    # Case 5: Auto-detect from data range
    if data.dtype == np.uint16:
        max_val = np.max(data)
        if max_val <= 255:
            # Likely 8-bit data in 16-bit container
            print(f"  Auto-detect: max={max_val}, using 255 (8-bit range)")
            return 255.0
        elif max_val <= 4095:
            # Likely 12-bit data
            print(f"  Auto-detect: max={max_val}, using 4095 (12-bit range)")
            return 4095.0
        else:
            # Full 16-bit or scaled data
            print(f"  Auto-detect: max={max_val}, using 65535 (16-bit range)")
            return 65535.0
    elif data.dtype == np.uint8:
        return 255.0
    else:
        # Float data or unknown - assume already normalized or use 1.0
        if data.max() <= 1.0:
            return 1.0
        return 65535.0


def load_raw_image(filepath):
    """Load raw image from FITS or TIFF format with proper RAW16 support"""
    ext = os.path.splitext(filepath)[1].lower()
    
    if ext == '.fits':
        try:
            from astropy.io import fits
            with fits.open(filepath) as hdul:
                data = hdul[0].data
                header = hdul[0].header
                
                # Display camera/bit depth info from header
                camera = header.get('CAMERA', header.get('INSTRUME', 'Unknown'))
                bit_depth = header.get('BITDEPTH', 'N/A')
                img_bits = header.get('IMGBITS', 'N/A')
                bayer = header.get('BAYERPAT', 'N/A')
                pixel_size = header.get('PIXSIZE', 'N/A')
                egain = header.get('EGAIN', 'N/A')
                scaled = header.get('SCALED', False)
                mul16_rate = header.get('MUL16RAT', 1)  # Left-shift factor for 12-bit in 16-bit
                
                print(f"Camera: {camera}")
                print(f"Sensor ADC: {bit_depth}-bit" if bit_depth != 'N/A' else "")
                print(f"Image mode: {img_bits}-bit" if img_bits != 'N/A' else "")
                print(f"Bayer: {bayer}" if bayer != 'N/A' else "")
                if pixel_size != 'N/A':
                    print(f"Pixel size: {pixel_size} µm")
                if egain != 'N/A':
                    print(f"e-/ADU: {egain}")
                if scaled:
                    print(f"Note: RAW8 data scaled to uint16 (SCALED=True)")
                if mul16_rate > 1:
                    print(f"Note: 12-bit data left-shifted by {mul16_rate}x (MUL16RAT={mul16_rate})")
                
                # FITS data is in (height, width, channels) or (channels, height, width)
                if data.ndim == 3:
                    # Check if channels are first or last
                    if data.shape[0] == 3:  # (3, H, W)
                        data = np.transpose(data, (1, 2, 0))  # -> (H, W, 3)
                    # else already (H, W, 3)
                
                # Determine correct normalization denominator
                denom = _infer_fits_normalization(data, header, scaled, mul16_rate, bit_depth, img_bits)
                print(f"Normalization: dividing by {denom}")
                
                data = data.astype(np.float32) / denom
                return data
        except ImportError:
            print("ERROR: astropy not installed. Install with: pip install astropy")
            sys.exit(1)
    
    elif ext in ['.tif', '.tiff']:
        img = Image.open(filepath)
        data = np.array(img).astype(np.float32) / 255.0
        return data
    
    else:
        # Try loading as standard image
        img = Image.open(filepath)
        data = np.array(img).astype(np.float32) / 255.0
        return data


def analyze_statistics(data, name="Image"):
    """Print detailed per-channel statistics"""
    print(f"\n{'='*60}")
    print(f"{name} Statistics")
    print('='*60)
    
    for c, channel_name in enumerate(['Red', 'Green', 'Blue']):
        if c < data.shape[2]:
            channel = data[:, :, c]
            median = np.median(channel)
            mean = np.mean(channel)
            std = np.std(channel)
            mad = np.median(np.abs(channel - median))
            
            print(f"\n{channel_name} Channel:")
            print(f"  Median:  {median:.6f}")
            print(f"  Mean:    {mean:.6f}")
            print(f"  Std Dev: {std:.6f}")
            print(f"  MAD:     {mad:.6f}")
            print(f"  Min:     {np.min(channel):.6f}")
            print(f"  Max:     {np.max(channel):.6f}")
            print(f"  P1:      {np.percentile(channel, 1):.6f}")
            print(f"  P25:     {np.percentile(channel, 25):.6f}")
            print(f"  P75:     {np.percentile(channel, 75):.6f}")
            print(f"  P99:     {np.percentile(channel, 99):.6f}")
    
    # Overall luminance
    lum = 0.299 * data[:,:,0] + 0.587 * data[:,:,1] + 0.114 * data[:,:,2]
    print(f"\nLuminance:")
    print(f"  Median:  {np.median(lum):.6f}")
    print(f"  Mean:    {np.mean(lum):.6f}")
    print(f"  MAD:     {np.median(np.abs(lum - np.median(lum))):.6f}")
    
    # Color balance
    r_mean = np.mean(data[:,:,0])
    g_mean = np.mean(data[:,:,1])
    b_mean = np.mean(data[:,:,2])
    print(f"\nColor Balance (relative to Green):")
    print(f"  R/G: {r_mean/g_mean:.3f}")
    print(f"  B/G: {b_mean/g_mean:.3f}")
    print(f"  (1.0 = neutral)")


def mtf_stretch(data, target_median=0.27, shadow_clip=0.0):
    """MTF (Midtone Transfer Function) stretch - standard astrophotography method"""
    stretched = data.copy()
    
    for c in range(3):
        channel = data[:, :, c]
        
        # Calculate shadow clipping point using MAD
        if shadow_clip > 0:
            median = np.median(channel)
            mad = np.median(np.abs(channel - median))
            clip_point = median - shadow_clip * mad
            clip_point = max(0, clip_point)
        else:
            clip_point = 0.0
        
        # Clip shadows
        channel = np.clip(channel - clip_point, 0, 1)
        
        # Normalize
        if np.max(channel) > 0:
            channel = channel / np.max(channel)
        
        # Calculate midtone for target median
        current_median = np.median(channel[channel > 0])
        if current_median > 0 and current_median < 1:
            midtone = (target_median - 1) / ((2 * target_median - 1) * current_median - target_median)
            midtone = np.clip(midtone, 0.001, 1000)
            
            # Apply MTF
            channel = (midtone - 1) * channel / ((2 * midtone - 1) * channel - midtone)
            channel = np.clip(channel, 0, 1)
        
        stretched[:, :, c] = channel
    
    return stretched


def adaptive_stretch_with_normalization(data, target_median=0.27, normalize=True, correction_strength=0.5):
    """Adaptive stretch with optional dark scene color normalization"""
    stretched = data.copy()
    
    # Detect dark scene
    lum = 0.299 * data[:,:,0] + 0.587 * data[:,:,1] + 0.114 * data[:,:,2]
    is_dark = np.median(lum) < 0.05
    
    if is_dark and normalize:
        print("\nDark scene detected - applying color normalization...")
        # Calculate per-channel medians
        r_med = np.median(data[:,:,0])
        g_med = np.median(data[:,:,1])
        b_med = np.median(data[:,:,2])
        
        # Calculate luminance-weighted target
        target = 0.299 * r_med + 0.587 * g_med + 0.114 * b_med
        
        print(f"  R median: {r_med:.6f}, G median: {g_med:.6f}, B median: {b_med:.6f}")
        print(f"  Luminance target: {target:.6f}")
        
        # Apply partial correction
        for c, name in enumerate(['R', 'G', 'B']):
            current = [r_med, g_med, b_med][c]
            if current > 0:
                scale = 1.0 + correction_strength * (target / current - 1.0)
                stretched[:,:,c] = np.clip(data[:,:,c] * scale, 0, 1)
                print(f"  {name} scaled by {scale:.3f}")
    
    # Apply MTF stretch
    return mtf_stretch(stretched, target_median=target_median, shadow_clip=2.8)


def gamma_stretch(data, gamma=2.2):
    """Simple gamma stretch"""
    return np.clip(data ** (1/gamma), 0, 1)


def histogram_equalization(data):
    """Histogram equalization per channel"""
    stretched = np.zeros_like(data)
    for c in range(3):
        channel = data[:, :, c]
        # Flatten and sort
        flat = channel.flatten()
        sorted_vals = np.sort(flat)
        # Create lookup table
        lut = np.interp(channel, sorted_vals, np.linspace(0, 1, len(sorted_vals)))
        stretched[:, :, c] = lut
    return stretched


def normalize_color_balance(data, correction_strength=1.0, method='luminance'):
    """
    Normalize color balance by scaling channels to match a target.
    
    Args:
        data: Input image (H, W, 3) in 0-1 float range
        correction_strength: 0-1, how much correction to apply (1.0 = full correction)
        method: 'luminance' = preserve luminance, 'median' = equalize medians
    """
    normalized = data.copy()
    
    # Calculate per-channel medians
    r_med = np.median(data[:,:,0])
    g_med = np.median(data[:,:,1])
    b_med = np.median(data[:,:,2])
    
    if method == 'luminance':
        # Luminance-weighted target (preserves perceived brightness)
        target = 0.299 * r_med + 0.587 * g_med + 0.114 * b_med
    elif method == 'median':
        # Use overall median as target
        target = np.median([r_med, g_med, b_med])
    else:
        target = g_med  # Default to green channel
    
    # Apply partial correction to each channel
    for c in range(3):
        current = [r_med, g_med, b_med][c]
        if current > 0:
            scale = 1.0 + correction_strength * (target / current - 1.0)
            normalized[:,:,c] = np.clip(data[:,:,c] * scale, 0, 1)
    
    return normalized


def histogram_equalization_with_color_fix(data, normalize_first=True, normalize_strength=0.75):
    """
    Histogram equalization with color normalization.
    
    Args:
        normalize_first: If True, normalize before histogram equalization
                        If False, normalize after
        normalize_strength: 0-1, strength of color correction
    """
    if normalize_first:
        # Normalize first, then histogram equalize
        normalized = normalize_color_balance(data, correction_strength=normalize_strength)
        return histogram_equalization(normalized)
    else:
        # Histogram equalize first, then normalize
        equalized = histogram_equalization(data)
        return normalize_color_balance(equalized, correction_strength=normalize_strength)


def luminance_histogram_equalization(data, preserve_color=True):
    """
    Histogram equalization on luminance channel only, preserving color ratios.
    This prevents color shifts while enhancing contrast.
    """
    # Calculate luminance
    lum = 0.299 * data[:,:,0] + 0.587 * data[:,:,1] + 0.114 * data[:,:,2]
    
    # Equalize luminance
    flat_lum = lum.flatten()
    sorted_lum = np.sort(flat_lum)
    equalized_lum = np.interp(lum, sorted_lum, np.linspace(0, 1, len(sorted_lum)))
    
    if preserve_color:
        # Scale each channel proportionally to maintain color ratios
        result = np.zeros_like(data)
        # Avoid division by zero
        scale = np.where(lum > 1e-6, equalized_lum / (lum + 1e-6), 1.0)
        for c in range(3):
            result[:,:,c] = np.clip(data[:,:,c] * scale, 0, 1)
        return result
    else:
        # Just use equalized luminance as grayscale
        return np.stack([equalized_lum] * 3, axis=-1)


def luminance_histogram_eq_with_color_fix(data, normalize_strength=1.0):
    """
    BEST OF BOTH WORLDS: Color normalization + luminance histogram equalization.
    
    1. First normalizes color balance (fixes the 2x blue sensor bias)
    2. Then applies luminance-based histogram equalization (preserves corrected colors)
    
    This gives great detail like histogram eq, but with proper color balance.
    """
    # Step 1: Normalize color balance first
    normalized = normalize_color_balance(data, correction_strength=normalize_strength, method='luminance')
    
    # Step 2: Apply luminance histogram equalization (preserves the corrected color ratios)
    return luminance_histogram_equalization(normalized, preserve_color=True)


def luminance_hist_eq_gray_world(data, normalize_strength=1.0):
    """
    Alternative: Gray world assumption + luminance histogram equalization.
    
    Uses gray world color correction (assumes scene should average to gray)
    instead of luminance-weighted correction.
    """
    # Step 1: Gray world color normalization
    r_mean = np.mean(data[:,:,0])
    g_mean = np.mean(data[:,:,1])
    b_mean = np.mean(data[:,:,2])
    
    # Target is average of all channels (gray world assumes neutral average)
    target = (r_mean + g_mean + b_mean) / 3.0
    
    normalized = data.copy()
    for c, current in enumerate([r_mean, g_mean, b_mean]):
        if current > 0:
            scale = 1.0 + normalize_strength * (target / current - 1.0)
            normalized[:,:,c] = np.clip(data[:,:,c] * scale, 0, 1)
    
    # Step 2: Apply luminance histogram equalization
    return luminance_histogram_equalization(normalized, preserve_color=True)


def unsharp_mask(data, radius=2.0, amount=1.5):
    """
    Apply unsharp masking to enhance local contrast/details.
    
    Args:
        data: Input image (H, W, 3) in 0-1 float range
        radius: Blur radius (higher = larger scale details)
        amount: Strength of sharpening (1.0 = subtle, 2.0 = strong)
    """
    try:
        from scipy.ndimage import gaussian_filter
        
        result = np.zeros_like(data)
        for c in range(3):
            channel = data[:, :, c]
            blurred = gaussian_filter(channel, sigma=radius)
            # Unsharp mask: original + amount * (original - blurred)
            sharpened = channel + amount * (channel - blurred)
            result[:, :, c] = np.clip(sharpened, 0, 1)
        return result
    except ImportError:
        print("  WARNING: scipy not available for unsharp mask")
        return data


def local_contrast_enhancement(data, kernel_size=50, strength=1.0):
    """
    Enhance local contrast using local mean subtraction.
    This brings out details in both dark and bright regions.
    
    Args:
        kernel_size: Size of local region (larger = more global contrast)
        strength: How much local contrast to add (0-2, 1.0 = moderate)
    """
    try:
        from scipy.ndimage import uniform_filter
        
        result = np.zeros_like(data)
        for c in range(3):
            channel = data[:, :, c]
            
            # Calculate local mean
            local_mean = uniform_filter(channel, size=kernel_size)
            
            # Local deviation from mean
            local_detail = channel - local_mean
            
            # Enhance: global mean + enhanced local detail
            global_mean = np.mean(channel)
            enhanced = global_mean + local_detail * (1 + strength)
            
            result[:, :, c] = np.clip(enhanced, 0, 1)
        
        return result
    except ImportError:
        print("  WARNING: scipy not available for local contrast enhancement")
        return data


def lum_hist_eq_with_detail_boost(data, normalize_strength=1.0, detail_amount=1.5):
    """
    RECOMMENDED: Color normalization + luminance hist eq + detail enhancement.
    
    This method:
    1. Normalizes color balance (fixes sensor bias)
    2. Applies luminance histogram equalization (global contrast)
    3. Adds unsharp masking (local detail enhancement)
    """
    # Step 1: Normalize color
    normalized = normalize_color_balance(data, correction_strength=normalize_strength, method='luminance')
    
    # Step 2: Luminance histogram equalization
    equalized = luminance_histogram_equalization(normalized, preserve_color=True)
    
    # Step 3: Unsharp mask for detail
    return unsharp_mask(equalized, radius=2.0, amount=detail_amount)


def lum_hist_eq_with_local_contrast(data, normalize_strength=1.0, contrast_strength=1.0):
    """
    Color normalization + luminance hist eq + local contrast enhancement.
    
    Better for bringing out subtle details in dark regions.
    """
    # Step 1: Normalize color
    normalized = normalize_color_balance(data, correction_strength=normalize_strength, method='luminance')
    
    # Step 2: Luminance histogram equalization
    equalized = luminance_histogram_equalization(normalized, preserve_color=True)
    
    # Step 3: Local contrast enhancement
    return local_contrast_enhancement(equalized, kernel_size=50, strength=contrast_strength)


def clahe_luminance_with_color_fix(data, normalize_strength=1.0, clip_limit=2.0, tile_size=8):
    """
    Color normalization + CLAHE on luminance only.
    
    CLAHE (Contrast Limited Adaptive Histogram Equalization) enhances local contrast
    without over-amplifying noise, and doing it on luminance preserves colors.
    """
    try:
        import cv2
        
        # Step 1: Normalize color balance
        normalized = normalize_color_balance(data, correction_strength=normalize_strength, method='luminance')
        
        # Step 2: Calculate luminance
        lum = 0.299 * normalized[:,:,0] + 0.587 * normalized[:,:,1] + 0.114 * normalized[:,:,2]
        
        # Convert to uint8 for CLAHE
        lum_uint8 = (np.clip(lum, 0, 1) * 255).astype(np.uint8)
        
        # Apply CLAHE to luminance
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(tile_size, tile_size))
        lum_clahe = clahe.apply(lum_uint8) / 255.0
        
        # Step 3: Scale RGB channels proportionally to match new luminance
        result = np.zeros_like(data)
        scale = np.where(lum > 1e-6, lum_clahe / (lum + 1e-6), 1.0)
        for c in range(3):
            result[:,:,c] = np.clip(normalized[:,:,c] * scale, 0, 1)
        
        return result
    except ImportError:
        print("  WARNING: OpenCV not available for CLAHE")
        return lum_hist_eq_with_detail_boost(data, normalize_strength)


def adaptive_histogram_equalization(data, clip_limit=0.03, normalize_first=True, normalize_strength=0.75):
    """
    CLAHE (Contrast Limited Adaptive Histogram Equalization) with color fix.
    Better for preserving local details without over-amplifying noise.
    """
    try:
        import cv2
        
        # Optionally normalize first
        working = normalize_color_balance(data, correction_strength=normalize_strength) if normalize_first else data.copy()
        
        # Convert to uint8 for OpenCV
        data_uint8 = (np.clip(working, 0, 1) * 255).astype(np.uint8)
        
        # Create CLAHE object
        clahe = cv2.createCLAHE(clipLimit=clip_limit * 100, tileGridSize=(8, 8))
        
        # Apply to each channel
        result = np.zeros_like(data)
        for c in range(3):
            equalized = clahe.apply(data_uint8[:,:,c])
            result[:,:,c] = equalized / 255.0
        
        return result
    except ImportError:
        print("  WARNING: OpenCV not available for CLAHE, using standard histogram equalization")
        return histogram_equalization_with_color_fix(data, normalize_first, normalize_strength)


def asinh_stretch(data, stretch_factor=100):
    """Asinh stretch - good for wide dynamic range"""
    return np.arcsinh(data * stretch_factor) / np.arcsinh(stretch_factor)


def denoise_nlm(data, h=10, template_size=7, search_size=21):
    """
    Non-local means denoising - excellent for astro images.
    Preserves edges while smoothing random noise.
    
    Args:
        data: Input image (H, W, 3) in 0-1 float range
        h: Filter strength (higher = more smoothing, 5-15 typical)
        template_size: Size of template patch (odd number, 7 is good)
        search_size: Size of search area (odd number, 21 is good)
    """
    try:
        import cv2
        
        # Convert to uint8 for OpenCV
        img_uint8 = (np.clip(data, 0, 1) * 255).astype(np.uint8)
        
        # Apply non-local means denoising (colored version)
        denoised = cv2.fastNlMeansDenoisingColored(
            img_uint8, None, h, h,  # h for luminance and color
            template_size, search_size
        )
        
        return denoised.astype(np.float32) / 255.0
    except ImportError:
        print("  WARNING: OpenCV not available for NLM denoising")
        return data


def denoise_bilateral(data, d=9, sigma_color=75, sigma_space=75):
    """
    Bilateral filter - edge-preserving smoothing.
    Faster than NLM but less effective on random noise.
    
    Args:
        data: Input image (H, W, 3) in 0-1 float range
        d: Diameter of pixel neighborhood (use -1 for auto from sigma_space)
        sigma_color: Filter sigma in color space (larger = more color mixing)
        sigma_space: Filter sigma in coordinate space (larger = more distant pixels influence)
    """
    try:
        import cv2
        
        # Convert to uint8 for OpenCV
        img_uint8 = (np.clip(data, 0, 1) * 255).astype(np.uint8)
        
        # Apply bilateral filter
        denoised = cv2.bilateralFilter(img_uint8, d, sigma_color, sigma_space)
        
        return denoised.astype(np.float32) / 255.0
    except ImportError:
        print("  WARNING: OpenCV not available for bilateral filter")
        return data


def denoise_gaussian(data, sigma=1.0):
    """
    Simple Gaussian blur for noise reduction.
    Fast but loses fine detail.
    
    Args:
        data: Input image (H, W, 3) in 0-1 float range
        sigma: Blur strength (0.5-2.0 typical)
    """
    try:
        from scipy.ndimage import gaussian_filter
        
        result = np.zeros_like(data)
        for c in range(3):
            result[:, :, c] = gaussian_filter(data[:, :, c], sigma=sigma)
        return result
    except ImportError:
        print("  WARNING: scipy not available for Gaussian blur")
        return data


def lum_hist_eq_denoised(data, normalize_strength=1.0, denoise_strength=10):
    """
    Color normalization + denoising + luminance histogram equalization.
    
    Denoises BEFORE stretching to prevent noise amplification.
    """
    # Step 1: Normalize color
    normalized = normalize_color_balance(data, correction_strength=normalize_strength, method='luminance')
    
    # Step 2: Denoise (before stretch to prevent noise amplification)
    denoised = denoise_nlm(normalized, h=denoise_strength)
    
    # Step 3: Luminance histogram equalization
    return luminance_histogram_equalization(denoised, preserve_color=True)


def lum_hist_eq_detail_denoised(data, normalize_strength=1.0, detail_amount=1.5, denoise_strength=8):
    """
    RECOMMENDED: Color norm + denoise + lum hist eq + detail boost.
    
    The denoising happens BEFORE detail enhancement, so we enhance
    real structure instead of amplifying noise.
    """
    # Step 1: Normalize color
    normalized = normalize_color_balance(data, correction_strength=normalize_strength, method='luminance')
    
    # Step 2: Denoise first
    denoised = denoise_nlm(normalized, h=denoise_strength)
    
    # Step 3: Luminance histogram equalization
    equalized = luminance_histogram_equalization(denoised, preserve_color=True)
    
    # Step 4: Detail enhancement (now enhances real structure, not noise)
    return unsharp_mask(equalized, radius=2.0, amount=detail_amount)


def lum_hist_eq_local_denoised(data, normalize_strength=1.0, contrast_strength=1.5, denoise_strength=10):
    """
    Color norm + denoise + lum hist eq + local contrast.
    
    Best for bringing out subtle details without grain.
    """
    # Step 1: Normalize color
    normalized = normalize_color_balance(data, correction_strength=normalize_strength, method='luminance')
    
    # Step 2: Denoise first
    denoised = denoise_nlm(normalized, h=denoise_strength)
    
    # Step 3: Luminance histogram equalization
    equalized = luminance_histogram_equalization(denoised, preserve_color=True)
    
    # Step 4: Local contrast enhancement
    return local_contrast_enhancement(equalized, kernel_size=50, strength=contrast_strength)


def clahe_denoised(data, normalize_strength=1.0, clip_limit=2.0, denoise_strength=8):
    """
    Color norm + denoise + CLAHE on luminance.
    
    CLAHE already limits noise amplification, combined with denoising
    gives clean results with good local contrast.
    """
    # Step 1: Normalize color
    normalized = normalize_color_balance(data, correction_strength=normalize_strength, method='luminance')
    
    # Step 2: Denoise
    denoised = denoise_nlm(normalized, h=denoise_strength)
    
    # Step 3: CLAHE on luminance
    return clahe_luminance_with_color_fix(denoised, normalize_strength=0.0, clip_limit=clip_limit)


def visualize_comparisons(raw_data, filepath):
    """Create comparison visualization of different stretch methods"""
    fig = plt.figure(figsize=(24, 24))
    gs = GridSpec(6, 4, figure=fig, hspace=0.3, wspace=0.2)
    
    methods = [
        ("Raw (Linear)", raw_data),
        ("MTF (target=0.27)", mtf_stretch(raw_data, target_median=0.27)),
        ("Adaptive + Normalize (50%)", adaptive_stretch_with_normalization(raw_data, normalize=True, correction_strength=0.5)),
        ("Adaptive + Normalize (100%)", adaptive_stretch_with_normalization(raw_data, normalize=True, correction_strength=1.0)),
        
        ("Histogram Eq (no fix)", histogram_equalization(raw_data)),
        ("Hist Eq + Color Fix BEFORE", histogram_equalization_with_color_fix(raw_data, normalize_first=True, normalize_strength=0.75)),
        ("Lum Hist + Color Fix (100%)", luminance_histogram_eq_with_color_fix(raw_data, normalize_strength=1.0)),
        ("★ Lum Hist + Denoise", lum_hist_eq_denoised(raw_data, normalize_strength=1.0, denoise_strength=10)),
        
        ("★ Lum Hist + Detail Boost", lum_hist_eq_with_detail_boost(raw_data, normalize_strength=1.0, detail_amount=1.5)),
        ("★ Detail + Denoise (h=8)", lum_hist_eq_detail_denoised(raw_data, normalize_strength=1.0, detail_amount=1.5, denoise_strength=8)),
        ("★ Detail + Denoise (h=12)", lum_hist_eq_detail_denoised(raw_data, normalize_strength=1.0, detail_amount=1.5, denoise_strength=12)),
        ("★ Detail Strong + Denoise", lum_hist_eq_detail_denoised(raw_data, normalize_strength=1.0, detail_amount=2.0, denoise_strength=10)),
        
        ("★ Lum Hist + Local Contrast", lum_hist_eq_with_local_contrast(raw_data, normalize_strength=1.0, contrast_strength=1.0)),
        ("★ Local + Denoise (h=10)", lum_hist_eq_local_denoised(raw_data, normalize_strength=1.0, contrast_strength=1.5, denoise_strength=10)),
        ("★ Local + Denoise (h=15)", lum_hist_eq_local_denoised(raw_data, normalize_strength=1.0, contrast_strength=1.5, denoise_strength=15)),
        ("★ Local Strong + Denoise", lum_hist_eq_local_denoised(raw_data, normalize_strength=1.0, contrast_strength=2.0, denoise_strength=12)),
        
        ("★ CLAHE Lum + Color Fix", clahe_luminance_with_color_fix(raw_data, normalize_strength=1.0, clip_limit=2.0)),
        ("★ CLAHE + Denoise", clahe_denoised(raw_data, normalize_strength=1.0, clip_limit=2.0, denoise_strength=10)),
        ("Denoise Only (h=10)", denoise_nlm(normalize_color_balance(raw_data, correction_strength=1.0), h=10)),
        ("Bilateral Filter", denoise_bilateral(normalize_color_balance(raw_data, correction_strength=1.0), d=9, sigma_color=75, sigma_space=75)),
        
        ("Gamma 2.2", gamma_stretch(raw_data, gamma=2.2)),
        ("Gamma 3.0 + Color Fix", gamma_stretch(normalize_color_balance(raw_data, correction_strength=1.0), gamma=3.0)),
        ("Asinh + Color Fix", asinh_stretch(normalize_color_balance(raw_data, correction_strength=1.0), stretch_factor=100)),
        ("Asinh + Detail Boost", unsharp_mask(asinh_stretch(normalize_color_balance(raw_data, correction_strength=1.0), stretch_factor=100), radius=2.0, amount=1.5)),
    ]
    
    for idx, (name, result) in enumerate(methods):
        row = idx // 4
        col = idx % 4
        ax = fig.add_subplot(gs[row, col])
        ax.imshow(np.clip(result, 0, 1))
        # Highlight recommended methods with green border
        if name.startswith("★"):
            for spine in ax.spines.values():
                spine.set_edgecolor('lime')
                spine.set_linewidth(3)
        ax.set_title(name, fontsize=9, fontweight='bold')
        ax.axis('off')
        
        # Add median brightness and color balance as text
        lum = 0.299 * result[:,:,0] + 0.587 * result[:,:,1] + 0.114 * result[:,:,2]
        median_lum = np.median(lum)
        r_med = np.median(result[:,:,0])
        g_med = np.median(result[:,:,1])
        b_med = np.median(result[:,:,2])
        b_g_ratio = b_med / g_med if g_med > 0 else 0
        ax.text(0.5, -0.05, f"Med: {median_lum:.2f} | B/G: {b_g_ratio:.2f}", 
                transform=ax.transAxes, ha='center', fontsize=7, color='gray')
    
    fig.suptitle(f"Stretch Comparison: {os.path.basename(filepath)}\n★ = Recommended for dark scenes with color imbalance", 
                 fontsize=14, fontweight='bold')
    plt.show()


def interactive_analysis(filepath):
    """Interactive analysis with parameter adjustment"""
    print(f"\nLoading: {filepath}")
    raw_data = load_raw_image(filepath)
    print(f"Loaded image: {raw_data.shape} (H x W x C)")
    
    # Analyze raw statistics
    analyze_statistics(raw_data, "Raw Image")
    
    # Show comparison
    print("\n" + "="*60)
    print("Generating comparison visualization...")
    print("="*60)
    visualize_comparisons(raw_data, filepath)
    
    # Interactive parameter testing
    print("\n" + "="*60)
    print("Interactive Testing")
    print("="*60)
    
    while True:
        print("\nOptions:")
        print("1. Test MTF stretch (custom target median)")
        print("2. Test Adaptive + Normalize (custom correction strength)")
        print("3. Test Gamma stretch (custom gamma)")
        print("4. Test Asinh stretch (custom factor)")
        print("5. Test Histogram Eq with Color Fix (custom settings)")
        print("6. Test Luminance Histogram Eq (color fix, adjustable)")
        print("7. Test CLAHE with Color Fix (custom settings)")
        print("8. ★ Test Detail Boost (Lum Hist Eq + Unsharp Mask)")
        print("9. ★ Test Local Contrast (Lum Hist Eq + Local Contrast)")
        print("10. ★ Test CLAHE on Luminance (preserves colors)")
        print("--- DENOISING OPTIONS ---")
        print("11. ★ Test Detail + Denoise (RECOMMENDED)")
        print("12. ★ Test Local Contrast + Denoise")
        print("13. Test Denoise Only (NLM)")
        print("14. Compare Denoise Strengths")
        print("---")
        print("15. Show all comparisons again")
        print("16. Quit")
        
        choice = input("\nChoice: ").strip()
        
        if choice == '1':
            target = float(input("Target median (default 0.27): ") or 0.27)
            result = mtf_stretch(raw_data, target_median=target)
            analyze_statistics(result, f"MTF Stretch (target={target})")
            
            plt.figure(figsize=(15, 5))
            plt.subplot(131)
            plt.imshow(np.clip(raw_data, 0, 1))
            plt.title("Raw")
            plt.axis('off')
            plt.subplot(132)
            plt.imshow(np.clip(result, 0, 1))
            plt.title(f"MTF (target={target})")
            plt.axis('off')
            plt.subplot(133)
            diff = np.abs(result - raw_data)
            plt.imshow(diff)
            plt.title("Difference (absolute)")
            plt.axis('off')
            plt.tight_layout()
            plt.show()
        
        elif choice == '2':
            strength = float(input("Correction strength (0.0-1.0, default 0.5): ") or 0.5)
            result = adaptive_stretch_with_normalization(raw_data, normalize=True, correction_strength=strength)
            analyze_statistics(result, f"Adaptive + Normalize (strength={strength})")
            
            plt.figure(figsize=(10, 5))
            plt.subplot(121)
            plt.imshow(np.clip(raw_data, 0, 1))
            plt.title("Raw")
            plt.axis('off')
            plt.subplot(122)
            plt.imshow(np.clip(result, 0, 1))
            plt.title(f"Adaptive + Normalize ({strength*100:.0f}%)")
            plt.axis('off')
            plt.tight_layout()
            plt.show()
        
        elif choice == '3':
            gamma = float(input("Gamma value (default 2.2): ") or 2.2)
            result = gamma_stretch(raw_data, gamma=gamma)
            analyze_statistics(result, f"Gamma Stretch (gamma={gamma})")
            
            plt.figure(figsize=(10, 5))
            plt.subplot(121)
            plt.imshow(np.clip(raw_data, 0, 1))
            plt.title("Raw")
            plt.axis('off')
            plt.subplot(122)
            plt.imshow(np.clip(result, 0, 1))
            plt.title(f"Gamma {gamma}")
            plt.axis('off')
            plt.tight_layout()
            plt.show()
        
        elif choice == '4':
            factor = float(input("Stretch factor (default 100): ") or 100)
            result = asinh_stretch(raw_data, stretch_factor=factor)
            analyze_statistics(result, f"Asinh Stretch (factor={factor})")
            
            plt.figure(figsize=(10, 5))
            plt.subplot(121)
            plt.imshow(np.clip(raw_data, 0, 1))
            plt.title("Raw")
            plt.axis('off')
            plt.subplot(122)
            plt.imshow(np.clip(result, 0, 1))
            plt.title(f"Asinh (factor={factor})")
            plt.axis('off')
            plt.tight_layout()
            plt.show()
        
        elif choice == '5':
            print("\nHistogram Equalization with Color Fix")
            when = input("Normalize BEFORE or AFTER histogram eq? (before/after, default: before): ").strip().lower() or 'before'
            normalize_first = (when == 'before')
            strength = float(input("Color correction strength (0.0-1.0, default 0.75): ") or 0.75)
            
            result = histogram_equalization_with_color_fix(raw_data, normalize_first=normalize_first, normalize_strength=strength)
            analyze_statistics(result, f"Histogram Eq + Color Fix ({when}, strength={strength})")
            
            plt.figure(figsize=(15, 5))
            plt.subplot(131)
            plt.imshow(np.clip(raw_data, 0, 1))
            plt.title("Raw")
            plt.axis('off')
            plt.subplot(132)
            plt.imshow(np.clip(result, 0, 1))
            plt.title(f"Hist Eq + Color Fix\n({when}, {strength*100:.0f}%)")
            plt.axis('off')
            plt.subplot(133)
            # Show no-fix version for comparison
            no_fix = histogram_equalization(raw_data)
            plt.imshow(np.clip(no_fix, 0, 1))
            plt.title("Hist Eq (no color fix)")
            plt.axis('off')
            plt.tight_layout()
            plt.show()
        
        elif choice == '6':
            print("\nLuminance Histogram Eq with Color Fix")
            print("This method: 1) Normalizes color balance, 2) Then does luminance hist eq")
            strength = float(input("Color correction strength (0.0-1.0, default 1.0): ") or 1.0)
            
            result = luminance_histogram_eq_with_color_fix(raw_data, normalize_strength=strength)
            analyze_statistics(result, f"Lum Hist Eq + Color Fix (strength={strength})")
            
            plt.figure(figsize=(20, 5))
            plt.subplot(141)
            plt.imshow(np.clip(raw_data, 0, 1))
            plt.title("Raw")
            plt.axis('off')
            plt.subplot(142)
            plt.imshow(np.clip(result, 0, 1))
            plt.title(f"★ Lum Hist + Color Fix\n({strength*100:.0f}%)")
            plt.axis('off')
            plt.subplot(143)
            # Show luminance hist eq WITHOUT color fix for comparison
            no_fix = luminance_histogram_equalization(raw_data, preserve_color=True)
            plt.imshow(np.clip(no_fix, 0, 1))
            plt.title("Lum Hist Eq\n(no color fix - blue tint)")
            plt.axis('off')
            plt.subplot(144)
            # Show standard histogram eq for comparison
            std_hist = histogram_equalization(raw_data)
            plt.imshow(np.clip(std_hist, 0, 1))
            plt.title("Standard Hist Eq\n(per-channel - pink tint)")
            plt.axis('off')
            plt.tight_layout()
            plt.show()
        
        elif choice == '7':
            print("\nCLAHE (Contrast Limited Adaptive Histogram Eq) with Color Fix")
            clip_limit = float(input("Clip limit (0.01-0.05, default 0.03): ") or 0.03)
            strength = float(input("Color correction strength (0.0-1.0, default 0.75): ") or 0.75)
            
            result = adaptive_histogram_equalization(raw_data, clip_limit=clip_limit, normalize_first=True, normalize_strength=strength)
            analyze_statistics(result, f"CLAHE (clip={clip_limit}, strength={strength})")
            
            plt.figure(figsize=(15, 5))
            plt.subplot(131)
            plt.imshow(np.clip(raw_data, 0, 1))
            plt.title("Raw")
            plt.axis('off')
            plt.subplot(132)
            plt.imshow(np.clip(result, 0, 1))
            plt.title(f"CLAHE + Color Fix\n(clip={clip_limit}, {strength*100:.0f}%)")
            plt.axis('off')
            plt.subplot(133)
            # Show standard histogram eq for comparison
            std_hist = histogram_equalization(raw_data)
            plt.imshow(np.clip(std_hist, 0, 1))
            plt.title("Standard Histogram Eq\n(for comparison)")
            plt.axis('off')
            plt.tight_layout()
            plt.show()
        
        elif choice == '8':
            print("\n★ Detail Boost: Lum Hist Eq + Unsharp Mask")
            print("Adds local detail enhancement via unsharp masking")
            strength = float(input("Color correction strength (0.0-1.0, default 1.0): ") or 1.0)
            detail = float(input("Detail amount (0.5-3.0, default 1.5): ") or 1.5)
            
            result = lum_hist_eq_with_detail_boost(raw_data, normalize_strength=strength, detail_amount=detail)
            analyze_statistics(result, f"Lum Hist Eq + Detail Boost (detail={detail})")
            
            # Compare with base luminance hist eq
            base_result = luminance_histogram_eq_with_color_fix(raw_data, normalize_strength=strength)
            
            plt.figure(figsize=(20, 5))
            plt.subplot(141)
            plt.imshow(np.clip(raw_data, 0, 1))
            plt.title("Raw")
            plt.axis('off')
            plt.subplot(142)
            plt.imshow(np.clip(base_result, 0, 1))
            plt.title(f"Lum Hist + Color Fix\n(base - 'static')")
            plt.axis('off')
            plt.subplot(143)
            plt.imshow(np.clip(result, 0, 1))
            plt.title(f"★ + Detail Boost\n(detail={detail})")
            plt.axis('off')
            plt.subplot(144)
            # Show difference (detail added)
            diff = np.abs(result - base_result)
            plt.imshow(np.clip(diff * 5, 0, 1))  # Amplify difference for visibility
            plt.title("Detail Added (5x amplified)")
            plt.axis('off')
            plt.tight_layout()
            plt.show()
        
        elif choice == '9':
            print("\n★ Local Contrast: Lum Hist Eq + Local Contrast Enhancement")
            print("Enhances local contrast to reveal subtle details")
            strength = float(input("Color correction strength (0.0-1.0, default 1.0): ") or 1.0)
            contrast = float(input("Contrast strength (0.5-3.0, default 1.0): ") or 1.0)
            kernel = int(input("Kernel size (10-100, default 50): ") or 50)
            
            result = lum_hist_eq_with_local_contrast(raw_data, normalize_strength=strength, contrast_strength=contrast)
            analyze_statistics(result, f"Lum Hist Eq + Local Contrast (strength={contrast})")
            
            # Compare with base luminance hist eq
            base_result = luminance_histogram_eq_with_color_fix(raw_data, normalize_strength=strength)
            
            plt.figure(figsize=(20, 5))
            plt.subplot(141)
            plt.imshow(np.clip(raw_data, 0, 1))
            plt.title("Raw")
            plt.axis('off')
            plt.subplot(142)
            plt.imshow(np.clip(base_result, 0, 1))
            plt.title(f"Lum Hist + Color Fix\n(base - 'static')")
            plt.axis('off')
            plt.subplot(143)
            plt.imshow(np.clip(result, 0, 1))
            plt.title(f"★ + Local Contrast\n(strength={contrast})")
            plt.axis('off')
            plt.subplot(144)
            # Show difference
            diff = np.abs(result - base_result)
            plt.imshow(np.clip(diff * 5, 0, 1))
            plt.title("Contrast Added (5x amplified)")
            plt.axis('off')
            plt.tight_layout()
            plt.show()
        
        elif choice == '10':
            print("\n★ CLAHE on Luminance with Color Fix")
            print("CLAHE preserves local contrast better than global histogram eq")
            strength = float(input("Color correction strength (0.0-1.0, default 1.0): ") or 1.0)
            clip = float(input("CLAHE clip limit (1.0-8.0, default 2.0): ") or 2.0)
            tile = int(input("Tile size (4-16, default 8): ") or 8)
            
            result = clahe_luminance_with_color_fix(raw_data, normalize_strength=strength, clip_limit=clip, tile_size=tile)
            analyze_statistics(result, f"CLAHE Lum + Color Fix (clip={clip}, tile={tile})")
            
            # Compare with base luminance hist eq
            base_result = luminance_histogram_eq_with_color_fix(raw_data, normalize_strength=strength)
            
            plt.figure(figsize=(20, 5))
            plt.subplot(141)
            plt.imshow(np.clip(raw_data, 0, 1))
            plt.title("Raw")
            plt.axis('off')
            plt.subplot(142)
            plt.imshow(np.clip(base_result, 0, 1))
            plt.title(f"Lum Hist + Color Fix\n(global hist eq - 'static')")
            plt.axis('off')
            plt.subplot(143)
            plt.imshow(np.clip(result, 0, 1))
            plt.title(f"★ CLAHE Lum + Color Fix\n(clip={clip}, tile={tile})")
            plt.axis('off')
            plt.subplot(144)
            # Show difference
            diff = np.abs(result - base_result)
            plt.imshow(np.clip(diff * 5, 0, 1))
            plt.title("Difference (5x amplified)")
            plt.axis('off')
            plt.tight_layout()
            plt.show()
        
        elif choice == '11':
            print("\n★ Detail + Denoise: Color norm + denoise + lum hist eq + detail boost")
            print("Denoises BEFORE detail enhancement to enhance real structure")
            strength = float(input("Color correction strength (0.0-1.0, default 1.0): ") or 1.0)
            detail = float(input("Detail amount (0.5-3.0, default 1.5): ") or 1.5)
            denoise = float(input("Denoise strength h (5-20, default 10): ") or 10)
            
            result = lum_hist_eq_detail_denoised(raw_data, normalize_strength=strength, detail_amount=detail, denoise_strength=denoise)
            no_denoise = lum_hist_eq_with_detail_boost(raw_data, normalize_strength=strength, detail_amount=detail)
            
            analyze_statistics(result, f"Detail + Denoise (h={denoise})")
            
            plt.figure(figsize=(20, 5))
            plt.subplot(141)
            plt.imshow(np.clip(raw_data, 0, 1))
            plt.title("Raw")
            plt.axis('off')
            plt.subplot(142)
            plt.imshow(np.clip(no_denoise, 0, 1))
            plt.title(f"Detail Boost (no denoise)\n(grainy)")
            plt.axis('off')
            plt.subplot(143)
            plt.imshow(np.clip(result, 0, 1))
            plt.title(f"★ Detail + Denoise\n(h={denoise}, detail={detail})")
            plt.axis('off')
            plt.subplot(144)
            diff = np.abs(result - no_denoise)
            plt.imshow(np.clip(diff * 10, 0, 1))
            plt.title("Difference (10x)")
            plt.axis('off')
            plt.tight_layout()
            plt.show()
        
        elif choice == '12':
            print("\n★ Local Contrast + Denoise")
            print("Denoises BEFORE local contrast enhancement")
            strength = float(input("Color correction strength (0.0-1.0, default 1.0): ") or 1.0)
            contrast = float(input("Contrast strength (0.5-3.0, default 1.5): ") or 1.5)
            denoise = float(input("Denoise strength h (5-20, default 10): ") or 10)
            
            result = lum_hist_eq_local_denoised(raw_data, normalize_strength=strength, contrast_strength=contrast, denoise_strength=denoise)
            no_denoise = lum_hist_eq_with_local_contrast(raw_data, normalize_strength=strength, contrast_strength=contrast)
            
            analyze_statistics(result, f"Local Contrast + Denoise (h={denoise})")
            
            plt.figure(figsize=(20, 5))
            plt.subplot(141)
            plt.imshow(np.clip(raw_data, 0, 1))
            plt.title("Raw")
            plt.axis('off')
            plt.subplot(142)
            plt.imshow(np.clip(no_denoise, 0, 1))
            plt.title(f"Local Contrast (no denoise)\n(grainy)")
            plt.axis('off')
            plt.subplot(143)
            plt.imshow(np.clip(result, 0, 1))
            plt.title(f"★ Local + Denoise\n(h={denoise}, contrast={contrast})")
            plt.axis('off')
            plt.subplot(144)
            diff = np.abs(result - no_denoise)
            plt.imshow(np.clip(diff * 10, 0, 1))
            plt.title("Difference (10x)")
            plt.axis('off')
            plt.tight_layout()
            plt.show()
        
        elif choice == '13':
            print("\nNon-Local Means Denoising")
            print("Higher h = more smoothing (5-20 typical)")
            denoise = float(input("Denoise strength h (default 10): ") or 10)
            
            normalized = normalize_color_balance(raw_data, correction_strength=1.0)
            result = denoise_nlm(normalized, h=denoise)
            
            analyze_statistics(result, f"Denoise Only (h={denoise})")
            
            plt.figure(figsize=(15, 5))
            plt.subplot(131)
            plt.imshow(np.clip(normalized, 0, 1))
            plt.title("Color Normalized")
            plt.axis('off')
            plt.subplot(132)
            plt.imshow(np.clip(result, 0, 1))
            plt.title(f"Denoised (h={denoise})")
            plt.axis('off')
            plt.subplot(133)
            diff = np.abs(result - normalized)
            plt.imshow(np.clip(diff * 20, 0, 1))
            plt.title("Noise Removed (20x)")
            plt.axis('off')
            plt.tight_layout()
            plt.show()
        
        elif choice == '14':
            print("\nCompare Denoise Strengths")
            print("Comparing different h values with Detail Boost")
            
            strengths = [5, 8, 10, 12, 15, 20]
            fig, axes = plt.subplots(2, 3, figsize=(18, 12))
            
            for idx, h in enumerate(strengths):
                row, col = idx // 3, idx % 3
                result = lum_hist_eq_detail_denoised(raw_data, normalize_strength=1.0, detail_amount=1.5, denoise_strength=h)
                axes[row, col].imshow(np.clip(result, 0, 1))
                axes[row, col].set_title(f"h={h} (denoise strength)", fontsize=10)
                axes[row, col].axis('off')
            
            fig.suptitle("Denoise Strength Comparison (h value)\nLower h = more detail/noise, Higher h = smoother/less detail", fontsize=12)
            plt.tight_layout()
            plt.show()
        
        elif choice == '15':
            visualize_comparisons(raw_data, filepath)
        
        elif choice == '16':
            break


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_raw.py <path_to_raw_image.fits>")
        print("\nExample:")
        print("  python analyze_raw.py C:/Users/Paul/AppData/Local/PFRSentinel/raw_debug/raw_20260104_212149.fits")
        sys.exit(1)
    
    filepath = sys.argv[1]
    
    if not os.path.exists(filepath):
        print(f"ERROR: File not found: {filepath}")
        sys.exit(1)
    
    interactive_analysis(filepath)


if __name__ == "__main__":
    main()
