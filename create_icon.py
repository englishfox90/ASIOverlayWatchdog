"""
Generate application icon for ASIOverlayWatchDog
Creates an astronomy-themed icon with telescope/camera motif
"""
from PIL import Image, ImageDraw, ImageFont
import os

def create_app_icon():
    """Create a multi-resolution icon file"""
    
    # Create base image at highest resolution (256x256)
    size = 256
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Dark blue gradient background (night sky)
    for i in range(size):
        # Gradient from dark blue to darker blue
        r = int(10 + (30 - 10) * (i / size))
        g = int(15 + (45 - 15) * (i / size))
        b = int(40 + (80 - 40) * (i / size))
        draw.rectangle([(0, i), (size, i+1)], fill=(r, g, b, 255))
    
    # Draw stars (small white dots)
    import random
    random.seed(42)  # Consistent stars
    for _ in range(20):
        x = random.randint(10, size-10)
        y = random.randint(10, size-10)
        star_size = random.randint(1, 3)
        draw.ellipse([x-star_size, y-star_size, x+star_size, y+star_size], 
                     fill=(255, 255, 255, random.randint(180, 255)))
    
    # Draw telescope/camera body (simplified camera shape)
    cam_color = (60, 60, 70, 255)
    lens_color = (40, 40, 50, 255)
    highlight_color = (200, 200, 220, 255)
    
    # Main camera body (rounded rectangle)
    body_rect = [size*0.25, size*0.35, size*0.75, size*0.75]
    draw.rounded_rectangle(body_rect, radius=15, fill=cam_color, outline=highlight_color, width=3)
    
    # Lens (circle on left side)
    lens_center_x = size * 0.35
    lens_center_y = size * 0.55
    lens_radius = size * 0.15
    draw.ellipse([lens_center_x - lens_radius, lens_center_y - lens_radius,
                  lens_center_x + lens_radius, lens_center_y + lens_radius],
                 fill=lens_color, outline=highlight_color, width=3)
    
    # Lens glass reflection (inner circle)
    inner_radius = lens_radius * 0.6
    draw.ellipse([lens_center_x - inner_radius, lens_center_y - inner_radius,
                  lens_center_x + inner_radius, lens_center_y + inner_radius],
                 fill=(70, 70, 90, 255))
    
    # Lens highlight (small white arc)
    highlight_radius = lens_radius * 0.3
    highlight_x = lens_center_x - lens_radius * 0.3
    highlight_y = lens_center_y - lens_radius * 0.3
    draw.ellipse([highlight_x - highlight_radius, highlight_y - highlight_radius,
                  highlight_x + highlight_radius, highlight_y + highlight_radius],
                 fill=(200, 220, 255, 200))
    
    # Viewfinder bump on top
    viewfinder_rect = [size*0.42, size*0.25, size*0.58, size*0.38]
    draw.rounded_rectangle(viewfinder_rect, radius=5, fill=cam_color, outline=highlight_color, width=2)
    
    # Button/indicator LEDs (small colored dots)
    # Red LED
    led_x = size * 0.65
    led_y = size * 0.45
    led_size = size * 0.02
    draw.ellipse([led_x - led_size, led_y - led_size, led_x + led_size, led_y + led_size],
                 fill=(255, 50, 50, 255), outline=(200, 200, 200, 255), width=1)
    
    # Green LED
    led_x = size * 0.65
    led_y = size * 0.52
    draw.ellipse([led_x - led_size, led_y - led_size, led_x + led_size, led_y + led_size],
                 fill=(50, 255, 50, 255), outline=(200, 200, 200, 255), width=1)
    
    # Overlay text indicator (small text at bottom)
    # Draw "ASI" text on lens
    try:
        # Try to use a bold font
        font_size = int(size * 0.12)
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
            font_bold = ImageFont.truetype("arialbd.ttf", font_size)
        except:
            font = ImageFont.load_default()
            font_bold = font
        
        # Draw ASI text
        text = "ASI"
        # Get text bounding box
        bbox = draw.textbbox((0, 0), text, font=font_bold)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        text_x = lens_center_x - text_width / 2
        text_y = lens_center_y + lens_radius + 8
        
        # Draw text with shadow
        draw.text((text_x + 2, text_y + 2), text, fill=(0, 0, 0, 180), font=font_bold)
        draw.text((text_x, text_y), text, fill=(100, 200, 255, 255), font=font_bold)
    except Exception as e:
        print(f"Font rendering skipped: {e}")
    
    # Save at multiple resolutions for Windows icon
    icon_sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    icon_images = []
    
    for icon_size in icon_sizes:
        if icon_size == (256, 256):
            icon_images.append(img)
        else:
            resized = img.resize(icon_size, Image.Resampling.LANCZOS)
            icon_images.append(resized)
    
    # Save as .ico file (Windows icon format with multiple resolutions)
    icon_path = 'app_icon.ico'
    icon_images[0].save(icon_path, format='ICO', sizes=[(img.size[0], img.size[1]) for img in icon_images])
    print(f"✓ Created {icon_path} with {len(icon_images)} resolutions")
    
    # Also save as PNG for reference/other uses
    png_path = 'app_icon.png'
    img.save(png_path, 'PNG')
    print(f"✓ Created {png_path} (256x256)")
    
    return icon_path, png_path

if __name__ == '__main__':
    icon_file, png_file = create_app_icon()
    print(f"\n✅ Icon files created successfully!")
    print(f"   - {icon_file} (for Windows executable)")
    print(f"   - {png_file} (reference image)")
    print(f"\nNext steps:")
    print(f"   1. Icon is ready to use")
    print(f"   2. Will be applied to window and executable automatically")
