"""
Image processing and metadata parsing
"""
import os
import re
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from services.logger import app_logger


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


def add_overlays(image_input, overlays, metadata):
    """
    Add text overlays to an image.
    
    Args:
        image_input: Either a file path (str) or PIL Image object
        overlays: List of overlay configurations
        metadata: Metadata dictionary
    
    Returns the modified PIL Image object.
    """
    try:
        # Load image if it's a path, otherwise use the Image object directly
        if isinstance(image_input, str):
            img = Image.open(image_input)
        else:
            img = image_input
        
        # Only convert palette mode - preserve RGB/RGBA
        if img.mode in ('P',):  # Only convert palette mode
            img = img.convert('RGB')
        
        # Ensure RGB mode for drawing
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        draw = ImageDraw.Draw(img)
        
        for overlay in overlays:
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
            x_offset = overlay.get('x_offset', 10)
            y_offset = overlay.get('y_offset', 10)
            draw_background = overlay.get('background', True)
            
            # Load font (use default if custom font loading fails)
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except:
                try:
                    font = ImageFont.truetype("Arial.ttf", font_size)
                except:
                    # Fall back to default font
                    font = ImageFont.load_default()
            
            # Calculate text size
            text_width, text_height = get_text_bbox(draw, text, font)
            
            # Calculate position
            x, y = calculate_position(img.size, (text_width, text_height), anchor, x_offset, y_offset)
            
            # Draw solid background box if enabled
            if draw_background:
                padding = 5
                box_coords = [
                    x - padding,
                    y - padding,
                    x + text_width + padding,
                    y + text_height + padding
                ]
                draw.rectangle(box_coords, fill=(0, 0, 0))
            
            # Draw text
            draw.text((x, y), text, fill=color, font=font)
        
        return img
    
    except Exception as e:
        error_msg = f"Error adding overlays: {e}"
        print(error_msg)
        raise Exception(error_msg)


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
        
        # Add overlays to image
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
        
        # Save processed image with format-specific options
        if output_format.upper() in ['JPG', 'JPEG']:
            # Convert RGBA to RGB for JPG (JPG doesn't support transparency)
            if processed_img.mode == 'RGBA':
                # Create white background
                rgb_img = Image.new('RGB', processed_img.size, (0, 0, 0))
                rgb_img.paste(processed_img, mask=processed_img.split()[3])  # Use alpha channel as mask
                processed_img = rgb_img
            elif processed_img.mode != 'RGB':
                processed_img = processed_img.convert('RGB')
            
            jpg_quality = config.get('jpg_quality', 85)
            processed_img.save(output_path, 'JPEG', quality=jpg_quality, optimize=True)
        else:
            processed_img.save(output_path)
        
        # Return processed image and path for output mode handlers
        # processed_img is returned so webserver/RTSP can use it without reloading
        return True, output_path, None, processed_img
    
    except Exception as e:
        return False, None, str(e), None
