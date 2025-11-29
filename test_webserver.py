"""
Quick test for web output server functionality
"""
from services.web_output import WebOutputServer
from PIL import Image
import time

# Create a test image
img = Image.new('RGB', (640, 480), color='blue')
print("Created test image: 640x480 blue")

# Start web server
server = WebOutputServer(host='127.0.0.1', port=8081)
print("Starting web server...")
if server.start():
    print(f"✓ Server started: {server.get_url()}")
    print(f"✓ Status endpoint: {server.get_status_url()}")
    
    # Update with test image
    print("\nUpdating with test image...")
    import io
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    server.update_image("test.png", img_bytes.getvalue(), {"test": "metadata"})
    print("✓ Image updated")
    
    print(f"\nAccess the image at: {server.get_url()}")
    print(f"Access status at: {server.get_status_url()}")
    print("\nPress Ctrl+C to stop...")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nStopping server...")
        server.stop()
        print("✓ Server stopped")
else:
    print("❌ Failed to start server")
