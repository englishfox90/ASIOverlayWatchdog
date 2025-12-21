"""
Test image overlay functionality
"""
from PIL import Image, ImageDraw
from services.processor import add_overlays
import os

# Create a test image
test_img = Image.new('RGB', (800, 600), color=(50, 50, 50))
draw = ImageDraw.Draw(test_img)
draw.text((400, 300), "Test Image", fill='white')

# Create a simple overlay image (logo placeholder)
overlay_img = Image.new('RGBA', (100, 100), color=(255, 0, 0, 128))
draw2 = ImageDraw.Draw(overlay_img)
draw2.text((20, 40), "LOGO", fill='white')

# Save overlay image
overlay_path = "test_overlay.png"
overlay_img.save(overlay_path)

# Test image overlay configuration
image_overlay_config = {
    'type': 'image',
    'name': 'Test Logo',
    'image_path': overlay_path,
    'width': 150,
    'height': 150,
    'maintain_aspect': True,
    'opacity': 80,
    'anchor': 'Bottom-Right',
    'offset_x': 20,
    'offset_y': 20
}

# Test text overlay configuration
text_overlay_config = {
    'type': 'text',
    'text': 'Test Overlay',
    'font_size': 24,
    'color': 'white',
    'anchor': 'Top-Left',
    'offset_x': 10,
    'offset_y': 10,
    'background_enabled': True,
    'background_color': 'black'
}

# Apply overlays
overlays = [image_overlay_config, text_overlay_config]
metadata = {}

try:
    result = add_overlays(test_img, overlays, metadata)
    result.save('test_output.png')
    print("✓ Image overlay test successful!")
    print(f"Output saved to: test_output.png")
    
    # Cleanup
    if os.path.exists(overlay_path):
        os.remove(overlay_path)
    
except Exception as e:
    print(f"✗ Test failed: {e}")
    import traceback
    traceback.print_exc()
