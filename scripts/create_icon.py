"""
Generate application icon for PFR Sentinel
Converts Icon.png or Icon.svg to multi-resolution .ico file for Windows

Usage:
    python scripts/create_icon.py
    
Source files (in assets/):
    - Icon.png (preferred) - High-res PNG source
    - Icon.svg (fallback) - SVG source (requires cairosvg)
    
Output files (in assets/):
    - app_icon.ico - Multi-resolution Windows icon (16x16 to 256x256)
    - app_icon.png - 256x256 PNG copy for reference

Style Guide:
    - Corner radius: 12.5% of icon size (matches PFRAstro liquid glass aesthetic)
    - This gives ~32px radius on 256px icon, scaling proportionally
"""
from PIL import Image, ImageDraw
import os
import sys

# Corner radius as percentage of icon size (PFRAstro style guide)
CORNER_RADIUS_PERCENT = 12.5


def add_rounded_corners(img: Image.Image, radius_percent: float = CORNER_RADIUS_PERCENT) -> Image.Image:
    """Add rounded corners to an image using an alpha mask.
    
    Args:
        img: Source PIL Image (will be converted to RGBA)
        radius_percent: Corner radius as percentage of image size
        
    Returns:
        New image with rounded corners and transparent background
    """
    # Ensure RGBA
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    
    size = img.size[0]  # Assuming square
    radius = int(size * radius_percent / 100)
    
    # Create a mask for rounded corners
    mask = Image.new('L', img.size, 0)
    draw = ImageDraw.Draw(mask)
    
    # Draw rounded rectangle (white = opaque, black = transparent)
    draw.rounded_rectangle(
        [(0, 0), (size - 1, size - 1)],
        radius=radius,
        fill=255
    )
    
    # Create output with transparent background
    output = Image.new('RGBA', img.size, (0, 0, 0, 0))
    output.paste(img, (0, 0))
    
    # Apply the rounded corner mask to alpha channel
    # Composite: keep RGB from img, use mask for alpha
    r, g, b, a = output.split()
    # Combine existing alpha with rounded corner mask
    combined_alpha = Image.composite(a, Image.new('L', img.size, 0), mask)
    output = Image.merge('RGBA', (r, g, b, combined_alpha))
    
    return output


def convert_svg_to_png(svg_path: str, output_path: str, size: int = 512) -> bool:
    """Convert SVG to PNG using cairosvg if available.
    
    Args:
        svg_path: Path to source SVG file
        output_path: Path for output PNG file
        size: Output size in pixels (square)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        import cairosvg
        cairosvg.svg2png(
            url=svg_path,
            write_to=output_path,
            output_width=size,
            output_height=size
        )
        print(f"✓ Converted SVG to PNG ({size}x{size})")
        return True
    except ImportError:
        print("⚠ cairosvg not installed. Install with: pip install cairosvg")
        print("  (Also requires Cairo library on system)")
        return False
    except Exception as e:
        print(f"✗ SVG conversion failed: {e}")
        return False


def create_app_icon(source_png: str = None):
    """Create multi-resolution .ico file from source image.
    
    Args:
        source_png: Optional path to source PNG. If None, looks for
                   Icon.png or Icon.svg in assets folder.
                   
    Returns:
        Tuple of (ico_path, png_path) on success
    """
    # Determine paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(script_dir) == 'scripts':
        project_dir = os.path.dirname(script_dir)
    else:
        project_dir = script_dir
    assets_dir = os.path.join(project_dir, 'assets')
    os.makedirs(assets_dir, exist_ok=True)
    
    # Find source image
    if source_png and os.path.exists(source_png):
        source_path = source_png
        print(f"Using specified source: {source_path}")
    else:
        # Look for Icon.png first, then Icon.svg
        png_source = os.path.join(assets_dir, 'Icon.png')
        svg_source = os.path.join(assets_dir, 'Icon.svg')
        
        if os.path.exists(png_source):
            source_path = png_source
            print(f"Found source: {source_path}")
        elif os.path.exists(svg_source):
            # Convert SVG to temporary PNG
            temp_png = os.path.join(assets_dir, '_temp_icon.png')
            if convert_svg_to_png(svg_source, temp_png, size=512):
                source_path = temp_png
            else:
                print("✗ No usable icon source found!")
                print(f"  Place Icon.png or Icon.svg in {assets_dir}")
                sys.exit(1)
        else:
            print("✗ No icon source found!")
            print(f"  Place Icon.png or Icon.svg in {assets_dir}")
            sys.exit(1)
    
    # Load and process source image
    try:
        img = Image.open(source_path)
        print(f"Loaded: {img.size[0]}x{img.size[1]} {img.mode}")
        
        # Convert to RGBA if needed
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
            print(f"Converted to RGBA")
        
        # Resize to 256x256 if larger (ico max useful size)
        if img.size[0] > 256 or img.size[1] > 256:
            # Maintain aspect ratio, fit within 256x256
            img.thumbnail((256, 256), Image.Resampling.LANCZOS)
            print(f"Resized to: {img.size[0]}x{img.size[1]}")
        
        # Ensure square (pad if needed)
        if img.size[0] != img.size[1]:
            max_dim = max(img.size)
            square = Image.new('RGBA', (max_dim, max_dim), (0, 0, 0, 0))
            offset = ((max_dim - img.size[0]) // 2, (max_dim - img.size[1]) // 2)
            square.paste(img, offset)
            img = square
            print(f"Padded to square: {img.size[0]}x{img.size[1]}")
        
        # Apply rounded corners to base image
        img = add_rounded_corners(img, CORNER_RADIUS_PERCENT)
        print(f"Applied rounded corners ({CORNER_RADIUS_PERCENT}% radius)")
            
    except Exception as e:
        print(f"✗ Failed to load source image: {e}")
        sys.exit(1)
    
    # Create multiple resolutions for ICO
    # Apply rounded corners at each size for best quality
    icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    icon_images = []
    
    for icon_size in icon_sizes:
        if img.size == icon_size:
            # Already has rounded corners applied
            icon_images.append(img.copy())
        else:
            # Resize then re-apply rounded corners for crisp edges at each size
            resized = img.resize(icon_size, Image.Resampling.LANCZOS)
            # Re-apply corners at this size for sharper results
            resized = add_rounded_corners(resized, CORNER_RADIUS_PERCENT)
            icon_images.append(resized)
    
    # Save as .ico file (Windows icon format with multiple resolutions)
    icon_path = os.path.join(assets_dir, 'app_icon.ico')
    icon_images[0].save(
        icon_path, 
        format='ICO', 
        sizes=[(im.size[0], im.size[1]) for im in icon_images]
    )
    print(f"✓ Created {icon_path} with {len(icon_images)} resolutions")
    
    # Also save as PNG for reference/other uses
    png_path = os.path.join(assets_dir, 'app_icon.png')
    # Save largest size
    icon_images[0].save(png_path, 'PNG')
    print(f"✓ Created {png_path} (256x256)")
    
    # Cleanup temp file if created
    temp_png = os.path.join(assets_dir, '_temp_icon.png')
    if os.path.exists(temp_png):
        os.remove(temp_png)
    
    return icon_path, png_path


if __name__ == '__main__':
    print("=" * 50)
    print("PFR Sentinel Icon Generator")
    print("=" * 50)
    
    # Allow command-line source override
    source = sys.argv[1] if len(sys.argv) > 1 else None
    
    icon_file, png_file = create_app_icon(source)
    
    print()
    print("✅ Icon files created successfully!")
    print(f"   - {icon_file} (for Windows executable)")
    print(f"   - {png_file} (reference image)")
    print()
    print("The icon will be used for:")
    print("   • Application window title bar")
    print("   • Taskbar icon")  
    print("   • Executable file icon")
    print("   • Installer icon")
