"""Image stretch engine — MTF and shadow-clipping pipeline."""
import numpy as np
from PIL import Image
from .logger import app_logger


def mtf_stretch(value, midtone):
    """
    Apply Midtone Transfer Function (MTF) stretch.

    This is the standard astrophotography stretch function (PixInsight-style) that maps
    pixel values through a curve controlled by the midtone parameter.

    The MTF is defined such that:
    - MTF(0) = 0
    - MTF(m) = 0.5  (midtone maps to middle gray)
    - MTF(1) = 1

    Standard formula: MTF(x, m) = (m - 1) * x / ((2*m - 1) * x - m)

    Note: When m < 0.5, the stretch brightens dark values (most common in astrophotography)
          When m > 0.5, the stretch darkens values
          When m = 0.5, it's the identity function

    Args:
        value: Input pixel value(s) normalized to 0-1 range (can be numpy array)
        midtone: Midtone parameter (0 < m < 1). Lower values = more aggressive brightening.
                 Typical values for dark astro images: 0.05-0.25

    Returns:
        Stretched value(s) in 0-1 range
    """
    m = np.clip(midtone, 0.0001, 0.9999)
    x = np.clip(value, 0.0, 1.0)

    numerator = (m - 1.0) * x
    denominator = (2.0 * m - 1.0) * x - m

    result = np.where(
        np.abs(denominator) > 1e-10,
        numerator / denominator,
        x
    )

    return np.clip(result, 0.0, 1.0)


def auto_stretch_image(img, config, raw_16bit=None):
    """
    Apply automatic MTF stretch to enhance image contrast.

    This function analyzes the image histogram and applies an MTF (Midtone Transfer
    Function) stretch to bring out detail in the shadows and midtones while protecting
    highlights. This is the standard approach used in astrophotography software.

    When raw_16bit data is provided, processing happens in 16-bit precision for
    better dynamic range preservation before converting to 8-bit output.

    Args:
        img: PIL Image object (8-bit)
        config: Dictionary with stretch settings:
               - target_median: Target median brightness (0.0-1.0)
               - linked_stretch: Apply same stretch to all channels (prevents color shifts)
               - preserve_blacks: Keep true blacks dark instead of lifting to grey
               - black_point: Manual black point (0.0-0.1) - pixels below this stay black
               - shadow_aggressiveness: MAD multiplier (1.5=aggressive, 2.8=standard, 4.0=gentle)
               - saturation_boost: Post-stretch saturation multiplier
               - normalize_channels: Equalize channel medians before stretch (for dark scenes with color cast)
               - dark_scene_threshold: Median below this triggers dark scene mode (default 0.05)
        raw_16bit: Optional numpy array with 16-bit RGB data (H, W, 3) dtype=uint16.
                   When provided, stretching uses full 16-bit precision for better results.

    Returns:
        PIL Image with stretch applied (8-bit output)
    """
    try:
        # Convert, then scale IN PLACE. `astype(...) / scale` allocates a second
        # full-frame float32 array (83 MB for a 2628x2628 RGB frame) just to
        # hold the quotient; `/=` reuses the buffer astype already made.
        if raw_16bit is not None and raw_16bit.dtype == np.uint16:
            img_array = raw_16bit.astype(np.float32)
            img_array /= 65535.0
            bit_depth_str = "16-bit"
        else:
            img_array = np.array(img, dtype=np.float32)
            img_array /= 255.0
            bit_depth_str = "8-bit"

        target_median = config.get('target_median', 0.25)
        linked_stretch = config.get('linked_stretch', True)
        preserve_blacks = config.get('preserve_blacks', True)
        black_point = config.get('black_point', 0.0)
        shadow_aggressiveness = config.get('shadow_aggressiveness', 2.8)
        saturation_boost = config.get('saturation_boost', 1.5)
        normalize_channels = config.get('normalize_channels', False)
        dark_scene_threshold = config.get('dark_scene_threshold', 0.05)

        target_median = np.clip(target_median, 0.05, 0.95)
        black_point = np.clip(black_point, 0.0, 0.1)
        shadow_aggressiveness = np.clip(shadow_aggressiveness, 1.0, 5.0)

        if len(img_array.shape) == 2:
            current_brightness = np.median(img_array)
        else:
            if img_array.shape[2] >= 3:
                current_brightness = np.median(
                    0.299 * img_array[:,:,0] + 0.587 * img_array[:,:,1] + 0.114 * img_array[:,:,2]
                )
            else:
                current_brightness = np.median(img_array)

        if current_brightness > target_median + 0.1:
            app_logger.debug(f"Auto-stretch skipped ({bit_depth_str}): image already bright (median={current_brightness:.3f} > target={target_median:.3f})")
            return img

        app_logger.debug(f"Auto-stretch starting ({bit_depth_str}): current_median={current_brightness:.3f}, target={target_median:.3f}, preserve_blacks={preserve_blacks}")

        is_dark_scene = current_brightness < dark_scene_threshold
        if normalize_channels and is_dark_scene and len(img_array.shape) == 3 and img_array.shape[2] >= 3:
            img_array = _normalize_channel_medians(img_array)

        if len(img_array.shape) == 2:
            stretched = _stretch_channel(img_array, target_median, 'L',
                                        preserve_blacks, black_point, shadow_aggressiveness)
        elif img_array.shape[2] == 3:
            if linked_stretch:
                stretched = _stretch_linked_rgb(img_array, target_median,
                                               preserve_blacks, black_point, shadow_aggressiveness)
            else:
                stretched = np.zeros_like(img_array)
                channel_names = ['R', 'G', 'B']
                for c in range(3):
                    stretched[:,:,c] = _stretch_channel(
                        img_array[:,:,c], target_median, channel_names[c],
                        preserve_blacks, black_point, shadow_aggressiveness
                    )
        elif img_array.shape[2] == 4:
            rgb = img_array[:,:,:3]
            alpha = img_array[:,:,3]

            if linked_stretch:
                stretched_rgb = _stretch_linked_rgb(rgb, target_median,
                                                   preserve_blacks, black_point, shadow_aggressiveness)
            else:
                stretched_rgb = np.zeros_like(rgb)
                channel_names = ['R', 'G', 'B']
                for c in range(3):
                    stretched_rgb[:,:,c] = _stretch_channel(
                        rgb[:,:,c], target_median, channel_names[c],
                        preserve_blacks, black_point, shadow_aggressiveness
                    )

            stretched = np.dstack([stretched_rgb, alpha])
        else:
            return img

        scnr_amount = config.get('scnr_amount', 0.0)
        if scnr_amount > 0 and len(stretched.shape) == 3 and stretched.shape[2] >= 3:
            stretched = _apply_scnr(stretched, scnr_amount)

        # Scale in place: by this point *stretched* is always a freshly built
        # array — every branch above produced one via np.zeros_like, np.dstack,
        # or _stretch_channel's leading .copy() — so it never aliases the
        # caller's data, and `stretched * 255.0` would be one more full-frame
        # float32 temp (83 MB at 2628x2628) for no reader.
        np.multiply(stretched, 255.0, out=stretched)
        stretched_uint8 = stretched.astype(np.uint8)
        result_img = Image.fromarray(stretched_uint8, mode=img.mode)

        if saturation_boost != 1.0 and result_img.mode in ('RGB', 'RGBA'):
            from PIL import ImageEnhance
            enhancer = ImageEnhance.Color(result_img)
            result_img = enhancer.enhance(saturation_boost)
            app_logger.debug(f"Auto-stretch saturation boost: {saturation_boost:.2f}")

        return result_img

    except Exception as e:
        app_logger.error(f"Auto-stretch error: {e}")
        return img


def _normalize_channel_medians(img_array):
    """Equalise per-channel medians toward luminance, IN PLACE.

    Mutates *img_array* and returns it. The only caller (auto_stretch_image)
    owns a private float32 frame and rebinds the result immediately, so the
    defensive copy this used to make was a whole extra frame (83 MB at
    2628x2628) that nothing ever read. All three channel medians are sampled
    before any channel is written, so scaling in place cannot feed a rescaled
    channel back into a later channel's target.
    """
    r_median = np.median(img_array[:,:,0])
    g_median = np.median(img_array[:,:,1])
    b_median = np.median(img_array[:,:,2])

    target_median = 0.299 * r_median + 0.587 * g_median + 0.114 * b_median

    min_median = 0.001

    app_logger.debug(f"Dark scene normalization: R={r_median:.4f}, G={g_median:.4f}, B={b_median:.4f}")
    app_logger.debug(f"  Luminance target: {target_median:.4f}")

    for c, (median, name) in enumerate(
            ((r_median, 'R'), (g_median, 'G'), (b_median, 'B'))):
        if median <= min_median:
            continue
        scale = target_median / median
        scale = 1.0 + 0.5 * (scale - 1.0)
        channel = img_array[:, :, c]
        np.multiply(channel, scale, out=channel)
        np.clip(channel, 0.0, 1.0, out=channel)
        app_logger.debug(f"  {name} scaled by {scale:.3f}")

    return img_array


def _apply_scnr(img_array, amount=0.5):
    # Subtractive Chromatic Noise Reduction — PixInsight Average Neutral protection.
    # Clamps green to never exceed average(R, B). amount blends original ↔ corrected.
    amount = np.clip(amount, 0.0, 1.0)

    r = img_array[:, :, 0]
    g = img_array[:, :, 1]
    b = img_array[:, :, 2]

    neutral = (r + b) * 0.5
    corrected_g = np.minimum(g, neutral)
    new_g = g * (1.0 - amount) + corrected_g * amount

    green_excess = np.median(np.maximum(g - neutral, 0))
    correction_pct = (1.0 - np.median(new_g) / (np.median(g) + 1e-10)) * 100

    result = img_array.copy()
    result[:, :, 1] = new_g

    app_logger.debug(
        f"SCNR: amount={amount:.0%}, green_excess={green_excess:.4f}, "
        f"median_reduction={correction_pct:.1f}%"
    )

    return result


def _stretch_linked_rgb(img_array, target_median, preserve_blacks=True,
                        black_point=0.0, shadow_aggressiveness=2.8):
    luminance = 0.299 * img_array[:,:,0] + 0.587 * img_array[:,:,1] + 0.114 * img_array[:,:,2]

    median_lum = np.median(luminance)
    mad_lum = np.median(np.abs(luminance - median_lum))
    mad_lum = max(mad_lum, 0.001)

    shadow_clip = max(0.0, median_lum - shadow_aggressiveness * mad_lum)
    shadow_clip = min(shadow_clip, median_lum * 0.8)

    effective_black_point = max(shadow_clip, black_point)

    app_logger.debug(f"Auto-stretch (linked): lum_median={median_lum:.4f}, MAD={mad_lum:.4f}, "
                    f"shadow_clip={shadow_clip:.4f}, black_point={black_point:.4f}")

    stretched = np.zeros_like(img_array)

    if preserve_blacks:
        true_black = np.percentile(luminance, 1)
        transition_start = true_black
        transition_end = effective_black_point

        app_logger.debug(f"Preserve blacks: true_black={true_black:.4f}, transition=[{transition_start:.4f}-{transition_end:.4f}]")

        for c in range(3):
            channel = img_array[:,:,c].copy()

            if transition_end > transition_start:
                is_black = luminance <= transition_start
                is_transition = (luminance > transition_start) & (luminance <= transition_end)
                is_normal = luminance > transition_end

                channel[is_black] = 0.0

                if np.any(is_transition):
                    t = (luminance[is_transition] - transition_start) / (transition_end - transition_start)
                    t = t * t * (3 - 2 * t)
                    orig_val = channel[is_transition]
                    stretched_val = (orig_val - effective_black_point) / (1.0 - effective_black_point)
                    stretched_val = np.clip(stretched_val, 0, 1)
                    channel[is_transition] = t * stretched_val

                if np.any(is_normal):
                    normal_vals = channel[is_normal]
                    normal_vals = np.clip(normal_vals, effective_black_point, 1.0)
                    channel[is_normal] = (normal_vals - effective_black_point) / (1.0 - effective_black_point)
            else:
                if effective_black_point > 0:
                    channel = np.clip(channel, effective_black_point, 1.0)
                    channel = (channel - effective_black_point) / (1.0 - effective_black_point)

            stretched[:,:,c] = channel
    else:
        for c in range(3):
            channel = img_array[:,:,c]
            if effective_black_point > 0:
                channel = np.clip(channel, effective_black_point, 1.0)
                channel = (channel - effective_black_point) / (1.0 - effective_black_point)
            stretched[:,:,c] = channel

    lum_clipped = 0.299 * stretched[:,:,0] + 0.587 * stretched[:,:,1] + 0.114 * stretched[:,:,2]
    current_median = np.median(lum_clipped)

    if abs(current_median - target_median) < 0.01:
        app_logger.debug(f"MTF (linked): skipped - already at target (median={current_median:.4f})")
        return stretched

    midtone = _calculate_mtf_midtone(current_median, target_median)

    for c in range(3):
        stretched[:,:,c] = mtf_stretch(stretched[:,:,c], midtone)

    app_logger.debug(f"MTF (linked): post-clip_median={current_median:.4f}, midtone={midtone:.4f}, target={target_median:.3f}")

    return stretched


def _stretch_channel(channel, target_median, channel_name='',
                    preserve_blacks=True, black_point=0.0, shadow_aggressiveness=2.8):
    channel = channel.copy()

    median = np.median(channel)
    mad = np.median(np.abs(channel - median))
    mad = max(mad, 0.001)

    shadow_clip = max(0.0, median - shadow_aggressiveness * mad)
    shadow_clip = min(shadow_clip, median * 0.8)

    effective_black_point = max(shadow_clip, black_point)

    if channel_name:
        app_logger.debug(f"Auto-stretch {channel_name}: median={median:.4f}, MAD={mad:.4f}, "
                        f"shadow_clip={shadow_clip:.4f}, effective_bp={effective_black_point:.4f}")

    if preserve_blacks and effective_black_point > 0:
        true_black = np.percentile(channel, 1)

        is_black = channel <= true_black
        is_normal = channel > effective_black_point
        is_transition = ~is_black & ~is_normal

        result = np.zeros_like(channel)
        result[is_black] = 0.0

        if np.any(is_transition):
            t = (channel[is_transition] - true_black) / (effective_black_point - true_black + 1e-10)
            t = t * t * (3 - 2 * t)
            stretched_val = (channel[is_transition] - effective_black_point) / (1.0 - effective_black_point)
            stretched_val = np.clip(stretched_val, 0, 1)
            result[is_transition] = t * stretched_val

        if np.any(is_normal):
            normal_vals = np.clip(channel[is_normal], effective_black_point, 1.0)
            result[is_normal] = (normal_vals - effective_black_point) / (1.0 - effective_black_point)

        channel = result
    elif effective_black_point > 0:
        channel = np.clip(channel, effective_black_point, 1.0)
        channel = (channel - effective_black_point) / (1.0 - effective_black_point)

    current_median = np.median(channel)

    if abs(current_median - target_median) < 0.01 or current_median < 0.0001:
        return channel

    midtone = _calculate_mtf_midtone(current_median, target_median)

    if channel_name:
        app_logger.debug(f"MTF {channel_name}: post-clip_median={current_median:.4f}, midtone={midtone:.4f}")

    return mtf_stretch(channel, midtone)


def _calculate_mtf_midtone(current_median, target_median):
    x = np.clip(current_median, 0.0001, 0.9999)
    y = np.clip(target_median, 0.0001, 0.9999)

    if abs(x - y) < 0.001:
        return 0.5

    numerator = x * (y - 1.0)
    denominator = x * (2.0 * y - 1.0) - y

    if abs(denominator) < 1e-10:
        return 0.5

    midtone = numerator / denominator
    return np.clip(midtone, 0.0001, 0.9999)
