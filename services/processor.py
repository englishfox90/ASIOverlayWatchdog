"""
Image processing and metadata parsing
"""
import os
import re
import tempfile
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from services.logger import app_logger


def is_safe_path(path: str) -> bool:
    """
    Check if path is safe (no directory traversal attacks).
    SEC-003 fix: Prevents loading files from unintended directories.
    
    Args:
        path: File path to validate
        
    Returns:
        True if path is safe, False if potentially malicious
    """
    if not path:
        return False
    
    # Allow special dynamic placeholders
    if path == 'WEATHER_ICON':
        return True
    
    # Normalize the path to resolve any . or .. components
    normalized = os.path.normpath(path)
    
    # Check for directory traversal patterns
    # After normpath, '..' should not appear in a safe path
    if '..' in normalized:
        return False
    
    return True


def save_image_atomic(img, output_path: str, format_name: str, **save_kwargs) -> None:
    """
    Save image atomically to prevent corruption on crash/power loss.
    REL-001 fix: Uses temp file + rename pattern for atomic writes.
    
    Args:
        img: PIL Image to save
        output_path: Final destination path
        format_name: Image format (JPEG, PNG, etc.)
        **save_kwargs: Additional arguments for PIL save()
    """
    output_dir = os.path.dirname(output_path)
    
    # Ensure output directory exists
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
    
    # Create temp file in same directory for atomic rename
    fd, temp_path = tempfile.mkstemp(
        suffix='.tmp',
        dir=output_dir if output_dir else '.',
        prefix='.saving_'
    )
    
    try:
        os.close(fd)  # Close the file descriptor, PIL will reopen
        
        # Save to temp file
        img.save(temp_path, format_name, **save_kwargs)
        
        # Atomic rename (os.replace is atomic on same filesystem)
        os.replace(temp_path, output_path)
        
    except Exception:
        # Clean up temp file on error
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass  # Best effort cleanup
        raise


def parse_sidecar_file(sidecar_path):
    """
    Parse the sidecar text file into a dictionary.
    Format:
    [ZWO ASI676MC]
    Key = Value
    """
    metadata = {}
    camera_name = None
    
    if not os.path.exists(sidecar_path):
        return metadata
    
    try:
        with open(sidecar_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                
                # Check for camera header [ZWO ASI676MC]
                if line.startswith('[') and line.endswith(']'):
                    camera_name = line[1:-1]
                    metadata['CAMERA'] = camera_name
                    continue
                
                # Parse key = value pairs
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    metadata[key.upper()] = value
    
    except Exception as e:
        print(f"Error parsing sidecar file {sidecar_path}: {e}")
    
    return metadata


def derive_metadata(metadata, image_filename, session_name):
    """
    Derive additional metadata values from parsed data.
    """
    derived = metadata.copy()
    
    # Derive resolution from "Capture Area Size"
    if 'CAPTURE AREA SIZE' in metadata:
        # Format: "3552 * 3552"
        area = metadata['CAPTURE AREA SIZE']
        area = area.replace('*', 'x').replace(' ', '')
        derived['RES'] = area
    
    # Add filename and session
    derived['FILENAME'] = image_filename
    derived['SESSION'] = session_name
    
    # Add current datetime
    derived['DATETIME'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Map common fields for easier access
    for key in ['EXPOSURE', 'GAIN', 'TEMPERATURE']:
        if key not in derived and key.title() in metadata:
            derived[key] = metadata[key.title()]
    
    # Ensure TEMP is available
    if 'TEMP' not in derived and 'TEMPERATURE' in derived:
        derived['TEMP'] = derived['TEMPERATURE']
    
    return derived


def replace_tokens(text, metadata):
    """
    Replace tokens like {EXPOSURE}, {GAIN} with actual values.
    """
    # Create a copy of metadata with formatted values
    formatted_metadata = metadata.copy()
    
    # Format exposure to 2 decimal places if it exists
    if 'EXPOSURE' in formatted_metadata:
        exp_str = str(formatted_metadata['EXPOSURE'])
        if exp_str.endswith('s'):
            try:
                exp_value = float(exp_str[:-1])
                formatted_metadata['EXPOSURE'] = f"{exp_value:.2f}s"
            except ValueError:
                pass
    
    result = text
    
    # Find all tokens in the format {TOKEN}
    tokens = re.findall(r'\{([^}]+)\}', text)
    
    for token in tokens:
        token_upper = token.upper()
        value = formatted_metadata.get(token_upper, '?')
        result = result.replace(f'{{{token}}}', str(value))
    
    return result


def get_text_bbox(draw, text, font):
    """Get bounding box of text."""
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    return width, height


def calculate_position(image_size, text_size, anchor, x_offset, y_offset):
    """
    Calculate text position based on anchor point and offsets.
    """
    img_width, img_height = image_size
    text_width, text_height = text_size
    
    # Base positions for each anchor
    anchors = {
        "Top-Left": (x_offset, y_offset),
        "Top-Right": (img_width - text_width - x_offset, y_offset),
        "Bottom-Left": (x_offset, img_height - text_height - y_offset),
        "Bottom-Right": (img_width - text_width - x_offset, img_height - text_height - y_offset),
        "Center": ((img_width - text_width) // 2 + x_offset, (img_height - text_height) // 2 + y_offset)
    }
    
    return anchors.get(anchor, (x_offset, y_offset))


def parse_color(color_str):
    """
    Parse color string to RGB tuple.
    Supports: 'white', 'black', 'red', 'green', 'blue', or '#RRGGBB'
    """
    color_map = {
        'white': (255, 255, 255),
        'black': (0, 0, 0),
        'red': (255, 0, 0),
        'green': (0, 255, 0),
        'blue': (0, 0, 255),
        'yellow': (255, 255, 0),
        'cyan': (0, 255, 255),
        'magenta': (255, 0, 255)
    }
    
    color_lower = color_str.lower()
    
    if color_lower in color_map:
        return color_map[color_lower]
    
    # Try hex format
    if color_str.startswith('#') and len(color_str) == 7:
        try:
            r = int(color_str[1:3], 16)
            g = int(color_str[3:5], 16)
            b = int(color_str[5:7], 16)
            return (r, g, b)
        except:
            pass
    
    # Default to white
    return (255, 255, 255)


def add_overlays(image_input, overlays, metadata, image_cache=None, weather_service=None):
    """
    Add text and image overlays to an image.
    
    Args:
        image_input: Either a file path (str) or PIL Image object
        overlays: List of overlay configurations
        metadata: Metadata dictionary
        image_cache: Optional dict to cache loaded overlay images
        weather_service: Optional WeatherService instance for weather tokens
    
    Returns the modified PIL Image object.
    """
    try:
        # Merge weather data into metadata if weather service is available
        if weather_service and weather_service.is_configured():
            try:
                weather_tokens = weather_service.get_weather_tokens()
                if weather_tokens:
                    metadata.update(weather_tokens)
            except Exception as e:
                print(f"Warning: Failed to fetch weather data: {e}")
        
        # Load image if it's a path, otherwise use the Image object directly
        if isinstance(image_input, str):
            img = Image.open(image_input)
        else:
            img = image_input
        
        # Only convert palette mode - preserve RGB/RGBA
        if img.mode in ('P',):  # Only convert palette mode
            img = img.convert('RGB')
        
        # Ensure RGBA mode for drawing (to support image overlays with transparency)
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        
        draw = ImageDraw.Draw(img)
        
        for overlay in overlays:
            overlay_type = overlay.get('type', 'text')
            
            if overlay_type == 'image':
                # Handle image overlay with cache and weather service
                img = add_image_overlay(img, overlay, image_cache, weather_service)
            else:
                # Handle text overlay
                img = add_text_overlay(img, draw, overlay, metadata)
        
        # Convert back to RGB for final output
        if img.mode == 'RGBA':
            # Create RGB image with white background
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[3] if img.mode == 'RGBA' else None)
            img = rgb_img
        
        return img
    
    except Exception as e:
        error_msg = f"Error adding overlays: {e}"
        print(error_msg)
        raise Exception(error_msg)


def add_image_overlay(base_img, overlay, image_cache=None, weather_service=None):
    """
    Add an image overlay to the base image
    
    Args:
        base_img: Base PIL Image
        overlay: Overlay configuration dict
        image_cache: Optional dict to cache loaded images
        weather_service: Optional WeatherService for dynamic weather icons
        
    Returns:
        Modified PIL Image
    """
    try:
        import os
        
        image_path = overlay.get('image_path', '')
        if not image_path:
            print(f"Image overlay has no image_path: {overlay}")
            return base_img
        
        # SEC-003: Validate path before loading (prevent directory traversal)
        if not is_safe_path(image_path):
            app_logger.warning(f"Blocked potentially unsafe image overlay path: {image_path}")
            return base_img
        
        # Handle dynamic weather icon
        if image_path == 'WEATHER_ICON':
            if weather_service and weather_service.is_configured():
                actual_path = weather_service.get_weather_icon_path()
                if actual_path and os.path.exists(actual_path):
                    app_logger.debug(f"Resolved WEATHER_ICON to: {actual_path}")
                    image_path = actual_path
                else:
                    app_logger.warning("Weather icon not available - path not returned or doesn't exist")
                    return base_img
            else:
                app_logger.debug("Weather service not configured for WEATHER_ICON")
                return base_img
        
        if not os.path.exists(image_path):
            print(f"Image overlay path does not exist: {image_path}")
            return base_img
        
        # Use cache if available
        if image_cache is not None and image_path in image_cache:
            overlay_img = image_cache[image_path].copy()
        else:
            print(f"Loading image overlay from: {image_path}")
            # Load overlay image
            overlay_img = Image.open(image_path)
            print(f"Loaded image: {overlay_img.size}, mode: {overlay_img.mode}")
            
            # Cache the loaded image if cache is provided
            if image_cache is not None:
                image_cache[image_path] = overlay_img.copy()
        
        # Get size settings
        target_width = overlay.get('width', overlay_img.width)
        target_height = overlay.get('height', overlay_img.height)
        maintain_aspect = overlay.get('maintain_aspect', True)
        
        # Resize if needed
        if maintain_aspect and (target_width != overlay_img.width or target_height != overlay_img.height):
            # Calculate aspect-preserving size
            aspect_ratio = overlay_img.width / overlay_img.height
            if target_width / target_height > aspect_ratio:
                # Height is limiting factor
                target_width = int(target_height * aspect_ratio)
            else:
                # Width is limiting factor
                target_height = int(target_width / aspect_ratio)
        
        # Resize overlay image
        if target_width != overlay_img.width or target_height != overlay_img.height:
            overlay_img = overlay_img.resize((target_width, target_height), Image.Resampling.LANCZOS)
        
        # Apply opacity
        opacity = overlay.get('opacity', 100)
        if opacity < 100 and overlay_img.mode in ('RGBA', 'LA'):
            # Adjust alpha channel
            alpha = overlay_img.split()[3 if overlay_img.mode == 'RGBA' else 1]
            alpha = alpha.point(lambda p: int(p * opacity / 100))
            overlay_img.putalpha(alpha)
        elif opacity < 100:
            # Convert to RGBA and set opacity
            overlay_img = overlay_img.convert('RGBA')
            alpha = Image.new('L', overlay_img.size, int(255 * opacity / 100))
            overlay_img.putalpha(alpha)
        
        # Ensure overlay has alpha channel
        if overlay_img.mode != 'RGBA':
            overlay_img = overlay_img.convert('RGBA')
        
        # Calculate position
        anchor = overlay.get('anchor', 'Bottom-Right')
        x_offset = overlay.get('offset_x', 10)
        y_offset = overlay.get('offset_y', 10)
        
        x, y = calculate_position(base_img.size, (target_width, target_height), 
                                 anchor, x_offset, y_offset)
        
        # Paste overlay onto base image
        base_img.paste(overlay_img, (x, y), overlay_img)
        
        return base_img
        
    except Exception as e:
        print(f"Error adding image overlay: {e}")
        return base_img


def add_text_overlay(img, draw, overlay, metadata):
    """
    Add a text overlay to the image
    
    Args:
        img: PIL Image
        draw: ImageDraw object
        overlay: Overlay configuration dict
        metadata: Metadata dictionary
        
    Returns:
        Modified PIL Image
    """
    try:
        # Get datetime format from overlay config
        datetime_format = overlay.get('datetime_format', '%Y-%m-%d %H:%M:%S')
        
        # Create overlay-specific metadata with custom datetime format
        overlay_metadata = metadata.copy()
        if '{DATETIME}' in overlay.get('text', '').upper():
            overlay_metadata['DATETIME'] = datetime.now().strftime(datetime_format)
        
        # Replace tokens in overlay text
        text = replace_tokens(overlay.get('text', ''), overlay_metadata)
        
        # Get overlay properties
        font_size = overlay.get('font_size', 28)
        color = parse_color(overlay.get('color', 'white'))
        anchor = overlay.get('anchor', 'Bottom-Left')
        x_offset = overlay.get('offset_x', 10)  # Match config key
        y_offset = overlay.get('offset_y', 10)  # Match config key
        background_enabled = overlay.get('background_enabled', False)
        background_color = overlay.get('background_color', 'black')
        
        # Load font (use default if custom font loading fails)
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except:
            try:
                font = ImageFont.truetype("Arial.ttf", font_size)
            except:
                # Fall back to default font
                font = ImageFont.load_default()
        
        # Calculate text bounding box for proper padding
        # Get bbox relative to (0, 0) to find actual text dimensions including descenders
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Calculate position
        x, y = calculate_position(img.size, (text_width, text_height), anchor, x_offset, y_offset)
        
        # Draw background box if enabled and not transparent
        if background_enabled and background_color.lower() != 'transparent':
            padding = 5
            # Get bbox at actual drawing position for accurate background box
            text_bbox = draw.textbbox((x, y), text, font=font)
            box_coords = [
                text_bbox[0] - padding,  # left
                text_bbox[1] - padding,  # top
                text_bbox[2] + padding,  # right
                text_bbox[3] + padding   # bottom (includes descenders)
            ]
            # Parse background color (supports color names and hex)
            bg_color = parse_color(background_color)
            draw.rectangle(box_coords, fill=bg_color)
        
        # Draw text
        draw.text((x, y), text, fill=color, font=font)
        
        return img
        
    except Exception as e:
        print(f"Error adding text overlay: {e}")
        return img


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
    # Prevent division by zero and handle edge cases
    m = np.clip(midtone, 0.0001, 0.9999)
    x = np.clip(value, 0.0, 1.0)
    
    # Standard MTF formula: (m - 1) * x / ((2*m - 1) * x - m)
    numerator = (m - 1.0) * x
    denominator = (2.0 * m - 1.0) * x - m
    
    # Avoid division by zero
    result = np.where(
        np.abs(denominator) > 1e-10,
        numerator / denominator,
        x  # Return input value if denominator is too small
    )
    
    return np.clip(result, 0.0, 1.0)


def auto_stretch_image(img, config):
    """
    Apply automatic MTF stretch to enhance image contrast.
    
    This function analyzes the image histogram and applies an MTF (Midtone Transfer
    Function) stretch to bring out detail in the shadows and midtones while protecting
    highlights. This is the standard approach used in astrophotography software.
    
    Args:
        img: PIL Image object
        config: Dictionary with stretch settings:
               - target_median: Target median brightness (0.0-1.0)
               - shadows_clip: Shadow clipping point (0.0-0.5)
               - highlights_clip: Highlight clipping point (0.5-1.0)
               - linked_stretch: Apply same stretch to all channels
    
    Returns:
        PIL Image with stretch applied
    """
    try:
        # Convert to numpy array for processing
        img_array = np.array(img).astype(np.float32) / 255.0
        
        # Get stretch parameters
        target_median = config.get('target_median', 0.25)
        linked_stretch = config.get('linked_stretch', True)
        
        # Clamp target to valid range
        target_median = np.clip(target_median, 0.05, 0.95)
        
        # Check current image brightness - skip stretch if image is already bright
        # MTF stretch is designed for dark astro images, not daylight scenes
        if len(img_array.shape) == 2:
            current_brightness = np.median(img_array)
        else:
            # Use luminance for color images
            if img_array.shape[2] >= 3:
                current_brightness = np.median(
                    0.299 * img_array[:,:,0] + 0.587 * img_array[:,:,1] + 0.114 * img_array[:,:,2]
                )
            else:
                current_brightness = np.median(img_array)
        
        # Skip stretch if image is already brighter than target (e.g., daylight capture)
        if current_brightness > target_median + 0.1:
            app_logger.debug(f"Auto-stretch skipped: image already bright (median={current_brightness:.3f} > target={target_median:.3f})")
            return img
        
        app_logger.debug(f"Auto-stretch starting: current_median={current_brightness:.3f}, target={target_median:.3f}")
        
        # Determine if image is grayscale or color
        if len(img_array.shape) == 2:
            # Grayscale image
            stretched = _stretch_channel(img_array, target_median, 'L')
        elif img_array.shape[2] == 3:
            # RGB image
            if linked_stretch:
                # Linked stretch: use luminance for single MAD-based shadow clip
                luminance = 0.299 * img_array[:,:,0] + 0.587 * img_array[:,:,1] + 0.114 * img_array[:,:,2]
                
                # Calculate shadow clip from luminance using MAD
                median_lum = np.median(luminance)
                mad_lum = np.median(np.abs(luminance - median_lum))
                mad_lum = max(mad_lum, 0.001)
                shadow_clip = max(0.0, median_lum - 2.8 * mad_lum)
                shadow_clip = min(shadow_clip, median_lum * 0.8)
                
                app_logger.debug(f"Auto-stretch (linked): lum_median={median_lum:.4f}, MAD={mad_lum:.4f}, shadow_clip={shadow_clip:.4f}")
                
                # Apply same shadow clip to all channels
                stretched = np.zeros_like(img_array)
                for c in range(3):
                    channel = img_array[:,:,c]
                    if shadow_clip > 0:
                        channel = np.clip(channel, shadow_clip, 1.0)
                        channel = (channel - shadow_clip) / (1.0 - shadow_clip)
                    stretched[:,:,c] = channel
                
                # Calculate MTF from luminance after clipping
                lum_clipped = 0.299 * stretched[:,:,0] + 0.587 * stretched[:,:,1] + 0.114 * stretched[:,:,2]
                current_median = np.median(lum_clipped)
                midtone = _calculate_mtf_midtone(current_median, target_median)
                
                # Apply same MTF to all channels
                for c in range(3):
                    stretched[:,:,c] = mtf_stretch(stretched[:,:,c], midtone)
                    
                app_logger.debug(f"MTF (linked): post-clip_median={current_median:.4f}, midtone={midtone:.4f}, target={target_median:.3f}")
            else:
                # Independent stretch per channel with MAD-based shadow clipping
                stretched = np.zeros_like(img_array)
                channel_names = ['R', 'G', 'B']
                for c in range(3):
                    stretched[:,:,c] = _stretch_channel(
                        img_array[:,:,c], target_median, channel_names[c]
                    )
        elif img_array.shape[2] == 4:
            # RGBA image - stretch RGB, preserve alpha
            rgb = img_array[:,:,:3]
            alpha = img_array[:,:,3]
            
            if linked_stretch:
                # Linked stretch: use luminance for single MAD-based shadow clip
                luminance = 0.299 * rgb[:,:,0] + 0.587 * rgb[:,:,1] + 0.114 * rgb[:,:,2]
                
                median_lum = np.median(luminance)
                mad_lum = np.median(np.abs(luminance - median_lum))
                mad_lum = max(mad_lum, 0.001)
                shadow_clip = max(0.0, median_lum - 2.8 * mad_lum)
                shadow_clip = min(shadow_clip, median_lum * 0.8)
                
                stretched_rgb = np.zeros_like(rgb)
                for c in range(3):
                    channel = rgb[:,:,c]
                    if shadow_clip > 0:
                        channel = np.clip(channel, shadow_clip, 1.0)
                        channel = (channel - shadow_clip) / (1.0 - shadow_clip)
                    stretched_rgb[:,:,c] = channel
                
                # Calculate MTF from luminance after clipping
                lum_clipped = 0.299 * stretched_rgb[:,:,0] + 0.587 * stretched_rgb[:,:,1] + 0.114 * stretched_rgb[:,:,2]
                current_median = np.median(lum_clipped)
                midtone = _calculate_mtf_midtone(current_median, target_median)
                
                for c in range(3):
                    stretched_rgb[:,:,c] = mtf_stretch(stretched_rgb[:,:,c], midtone)
            else:
                # Independent stretch per channel with MAD-based shadow clipping
                stretched_rgb = np.zeros_like(rgb)
                channel_names = ['R', 'G', 'B']
                for c in range(3):
                    stretched_rgb[:,:,c] = _stretch_channel(
                        rgb[:,:,c], target_median, channel_names[c]
                    )
            
            stretched = np.dstack([stretched_rgb, alpha])
        else:
            # Unknown format, return unchanged
            return img
        
        # Convert back to uint8 and PIL Image
        stretched_uint8 = (stretched * 255.0).astype(np.uint8)
        return Image.fromarray(stretched_uint8, mode=img.mode)
        
    except Exception as e:
        app_logger.error(f"Auto-stretch error: {e}")
        return img


def _stretch_channel(channel, target_median, channel_name=''):
    """
    Stretch a single channel to target median using MAD-based shadow clipping.
    
    This uses the statistical approach: shadow_clip = median - 2.8 * MAD
    where MAD (Median Absolute Deviation) is a robust measure of noise floor.
    
    Args:
        channel: 2D numpy array (0-1 range)
        target_median: Target median value after stretch
        channel_name: Optional name for debug logging (e.g., 'R', 'G', 'B')
    
    Returns:
        Stretched channel
    """
    # Step 1: Calculate shadow clip using MAD (Median Absolute Deviation)
    median = np.median(channel)
    mad = np.median(np.abs(channel - median))
    
    # Ensure minimum MAD to prevent over-clipping uniform images
    mad = max(mad, 0.001)
    
    # Calculate shadow clip point: median - 2.8 * MAD
    # 2.8 sigma captures ~99.5% of noise in Gaussian distribution
    shadow_clip = max(0.0, median - 2.8 * mad)
    
    # Safety: don't clip more than 80% of the median value
    shadow_clip = min(shadow_clip, median * 0.8)
    
    if channel_name:
        app_logger.debug(f"Auto-stretch {channel_name}: median={median:.4f}, MAD={mad:.4f}, shadow_clip={shadow_clip:.4f}")
    
    # Step 2: Apply shadow clipping and rescale to 0-1
    if shadow_clip > 0:
        channel = np.clip(channel, shadow_clip, 1.0)
        channel = (channel - shadow_clip) / (1.0 - shadow_clip)
    
    # Step 3: Calculate current median after clipping
    current_median = np.median(channel)
    
    # Skip MTF if already at target or very dark
    if abs(current_median - target_median) < 0.01 or current_median < 0.0001:
        return channel
    
    # Step 4: Calculate MTF midtone parameter and apply stretch
    midtone = _calculate_mtf_midtone(current_median, target_median)
    
    if channel_name:
        app_logger.debug(f"MTF {channel_name}: post-clip_median={current_median:.4f}, midtone={midtone:.4f}")
    
    return mtf_stretch(channel, midtone)


def _calculate_mtf_midtone(current_median, target_median):
    """
    Calculate the MTF midtone parameter to map current_median to target_median.
    
    Given MTF(x, m) = (m - 1) * x / ((2*m - 1) * x - m) = y
    Solving for m: m = x*(y - 1) / (x*(2*y - 1) - y)
    where x = current_median, y = target_median
    
    Args:
        current_median: Current median of the image/channel (0-1)
        target_median: Desired median after stretch (0-1)
    
    Returns:
        Midtone parameter for MTF function
    """
    # Prevent edge cases
    x = np.clip(current_median, 0.0001, 0.9999)  # current
    y = np.clip(target_median, 0.0001, 0.9999)   # target
    
    # If current is already at target, return 0.5 (identity transform)
    if abs(x - y) < 0.001:
        return 0.5
    
    # Derived midtone formula: m = x*(y - 1) / (x*(2*y - 1) - y)
    numerator = x * (y - 1.0)
    denominator = x * (2.0 * y - 1.0) - y
    
    if abs(denominator) < 1e-10:
        return 0.5
    
    midtone = numerator / denominator
    
    # Clamp to valid range
    return np.clip(midtone, 0.0001, 0.9999)


def build_output_filename(pattern, metadata, output_format='PNG'):
    """
    Build output filename from pattern and metadata.
    Supports tokens: {filename}, {session}, {timestamp}
    """
    result = pattern
    
    # Replace filename token (without extension)
    if '{filename}' in result:
        filename_no_ext = os.path.splitext(metadata.get('FILENAME', 'image'))[0]
        result = result.replace('{filename}', filename_no_ext)
    
    # Replace session token
    if '{session}' in result:
        result = result.replace('{session}', metadata.get('SESSION', 'unknown'))
    
    # Replace timestamp token
    if '{timestamp}' in result:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        result = result.replace('{timestamp}', timestamp)
    
    # Determine extension from format
    ext_map = {
        'PNG': '.png',
        'JPG': '.jpg',
        'JPEG': '.jpg',
        'BMP': '.bmp',
        'TIFF': '.tiff'
    }
    extension = ext_map.get(output_format.upper(), '.jpg')
    
    # Add extension if not present
    if not any(result.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.bmp', '.tiff']):
        result += extension
    
    return result


def process_image(image_path, config, metadata_dict=None):
    """
    Main processing function:
    1. Parse sidecar file OR use provided metadata
    2. Add overlays
    3. Save to output directory
    
    Args:
        image_path: Path to image file OR PIL Image object
        config: Config object
        metadata_dict: Optional pre-built metadata dictionary (for camera capture)
    
    Returns: (success: bool, output_path: str, error: str)
    """
    try:
        # Get configuration
        output_dir = config.get('output_directory', '')
        output_pattern = config.get('output_pattern', '{session}_{filename}')
        overlays = config.get_overlays()
        resize_percent = config.get('resize_percent', 100)
        show_timestamp = config.get('show_timestamp_corner', False)
        timestamp_corner = config.get('timestamp_corner', 'Top-Right')
        
        if not output_dir:
            return False, None, "Output directory not configured"
        
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        # Handle metadata
        if metadata_dict:
            # Use provided metadata (camera capture mode)
            metadata = metadata_dict
            image_filename = metadata.get('FILENAME', 'image.png')
            parent_folder = metadata.get('SESSION', 'session')
        else:
            # Directory watch mode - parse from file
            image_filename = os.path.basename(image_path)
            parent_folder = os.path.basename(os.path.dirname(image_path))
            
            # Look for sidecar file
            sidecar_path = image_path + '.txt'
            
            # Parse sidecar file
            metadata = parse_sidecar_file(sidecar_path)
            
            # Derive additional metadata
            metadata = derive_metadata(metadata, image_filename, parent_folder)
        
        # Add timestamp corner overlay if enabled
        overlays_to_apply = overlays.copy()
        if show_timestamp:
            timestamp_overlay = {
                'text': '{DATETIME}',
                'anchor': timestamp_corner,
                'x_offset': 10,
                'y_offset': 10,
                'font_size': 24,
                'color': 'white',
                'background': True
            }
            overlays_to_apply.append(timestamp_overlay)
        
        # Apply auto-stretch (MTF) BEFORE overlays for best results
        auto_stretch_config = config.get('auto_stretch', {})
        if auto_stretch_config.get('enabled', False):
            # Load raw image for stretching
            if isinstance(image_path, str):
                raw_img = Image.open(image_path)
            else:
                raw_img = image_path
            
            # Convert to RGB if needed for stretching
            if raw_img.mode not in ('RGB', 'RGBA', 'L'):
                raw_img = raw_img.convert('RGB')
            
            # Apply MTF stretch
            raw_img = auto_stretch_image(raw_img, auto_stretch_config)
            
            # Add overlays to stretched image
            processed_img = add_overlays(raw_img, overlays_to_apply, metadata)
        else:
            # Add overlays to image (no stretch)
            processed_img = add_overlays(image_path, overlays_to_apply, metadata)
        
        # Apply auto brightness if enabled (for saved images)
        if config.get('auto_brightness', False):
            from PIL import ImageEnhance
            import numpy as np
            
            # Analyze image brightness
            img_array = np.array(processed_img.convert('L'))  # Convert to grayscale for analysis
            mean_brightness = np.mean(img_array)
            
            # Calculate adaptive enhancement factor
            # Target brightness: 128 (mid-gray)
            # If image is dark (e.g., mean=30), boost by 128/30 = 4.27x
            # If image is bright (e.g., mean=200), reduce by 128/200 = 0.64x
            target_brightness = 128
            auto_factor = target_brightness / max(mean_brightness, 10)  # Avoid division by zero
            
            # Clamp factor to reasonable range (0.5 - 4.0)
            auto_factor = max(0.5, min(auto_factor, 4.0))
            
            # Apply manual brightness factor as additional adjustment
            manual_factor = config.get('brightness_factor', 1.0)
            final_factor = auto_factor * manual_factor
            
            enhancer = ImageEnhance.Brightness(processed_img)
            processed_img = enhancer.enhance(final_factor)
            
            app_logger.debug(f"Auto brightness: mean={mean_brightness:.1f}, auto_factor={auto_factor:.2f}, manual={manual_factor:.2f}, final={final_factor:.2f}")
        
        # Apply saturation adjustment if not neutral
        saturation_factor = config.get('saturation_factor', 1.0)
        if saturation_factor != 1.0:
            from PIL import ImageEnhance
            enhancer = ImageEnhance.Color(processed_img)
            processed_img = enhancer.enhance(saturation_factor)
            app_logger.debug(f"Saturation adjusted: factor={saturation_factor:.2f}")
        
        # Resize image if needed
        if resize_percent > 0 and resize_percent != 100:
            original_width, original_height = processed_img.size
            new_width = int(original_width * resize_percent / 100)
            new_height = int(original_height * resize_percent / 100)
            processed_img = processed_img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Build output filename
        output_format = config.get('output_format', 'JPG')
        output_filename = build_output_filename(output_pattern, metadata, output_format)
        output_path = os.path.join(output_dir, output_filename)
        
        # Get output mode configuration
        output_mode = config.get('output', {}).get('mode', 'file')
        
        # Save processed image with format-specific options (REL-001: atomic writes)
        if output_format.upper() in ['JPG', 'JPEG']:
            # Convert RGBA to RGB for JPG (JPG doesn't support transparency)
            if processed_img.mode == 'RGBA':
                # Create black background (better for astrophotography)
                rgb_img = Image.new('RGB', processed_img.size, (0, 0, 0))
                rgb_img.paste(processed_img, mask=processed_img.split()[3])  # Use alpha channel as mask
                processed_img = rgb_img
            elif processed_img.mode != 'RGB':
                processed_img = processed_img.convert('RGB')
            
            jpg_quality = config.get('jpg_quality', 85)
            save_image_atomic(processed_img, output_path, 'JPEG', quality=jpg_quality, optimize=True)
        else:
            save_image_atomic(processed_img, output_path, output_format.upper())
        
        # Return processed image and path for output mode handlers
        # processed_img is returned so webserver/RTSP can use it without reloading
        return True, output_path, None, processed_img
    
    except Exception as e:
        return False, None, str(e), None
