"""
Test image output and overlay functionality
"""
import pytest
import os
import sys
from PIL import Image

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services.processor import add_overlays, process_image


class TestImageOverlay:
    """Test image overlay functionality"""
    
    def test_text_overlay_basic(self, sample_image, sample_metadata):
        """Test basic text overlay application"""
        overlay = {
            'type': 'text',
            'text': 'Test Overlay',
            'anchor': 'Top-Left',
            'offset_x': 10,
            'offset_y': 10,
            'font_size': 24,
            'color': 'white'
        }
        
        result = add_overlays(sample_image, [overlay], sample_metadata)
        
        assert result is not None
        assert result.size == sample_image.size
    
    def test_text_overlay_token_replacement(self, sample_image, sample_metadata):
        """Test that tokens are replaced in overlay text"""
        overlay = {
            'type': 'text',
            'text': 'Camera: {CAMERA}\nExposure: {EXPOSURE}',
            'anchor': 'Bottom-Left',
            'offset_x': 10,
            'offset_y': 10,
            'font_size': 20,
            'color': 'white'
        }
        
        result = add_overlays(sample_image, [overlay], sample_metadata)
        
        # Image should be created without error
        assert result is not None
    
    def test_multiple_overlays(self, sample_image, sample_metadata):
        """Test multiple overlays can be applied"""
        overlays = [
            {
                'type': 'text',
                'text': 'Top Left',
                'anchor': 'Top-Left',
                'offset_x': 10,
                'offset_y': 10,
                'font_size': 20,
                'color': 'white'
            },
            {
                'type': 'text',
                'text': 'Bottom Right',
                'anchor': 'Bottom-Right',
                'offset_x': 10,
                'offset_y': 10,
                'font_size': 20,
                'color': 'yellow'
            }
        ]
        
        result = add_overlays(sample_image, overlays, sample_metadata)
        
        assert result is not None
    
    def test_overlay_anchors(self, sample_image, sample_metadata):
        """Test all anchor positions work"""
        anchors = ['Top-Left', 'Top-Right', 'Bottom-Left', 'Bottom-Right', 'Center']
        
        for anchor in anchors:
            overlay = {
                'type': 'text',
                'text': f'At {anchor}',
                'anchor': anchor,
                'offset_x': 10,
                'offset_y': 10,
                'font_size': 20,
                'color': 'white'
            }
            
            result = add_overlays(sample_image.copy(), [overlay], sample_metadata)
            assert result is not None, f"Failed for anchor: {anchor}"
    
    def test_text_overlay_with_background(self, sample_image, sample_metadata):
        """Test text overlay with background"""
        overlay = {
            'type': 'text',
            'text': 'With Background',
            'anchor': 'Center',
            'offset_x': 0,
            'offset_y': 0,
            'font_size': 24,
            'color': 'white',
            'background_enabled': True,
            'background_color': 'black',
            'background_padding': 5
        }
        
        result = add_overlays(sample_image, [overlay], sample_metadata)
        assert result is not None


class TestImageOutput:
    """Test image output/saving functionality"""
    
    def test_save_jpeg(self, sample_image, temp_dir):
        """Test saving as JPEG"""
        output_path = os.path.join(temp_dir, "test_output.jpg")
        
        sample_image.save(output_path, format='JPEG', quality=95)
        
        assert os.path.exists(output_path)
        
        # Verify it's a valid JPEG
        loaded = Image.open(output_path)
        assert loaded.format == 'JPEG'
    
    def test_save_png(self, sample_image, temp_dir):
        """Test saving as PNG"""
        output_path = os.path.join(temp_dir, "test_output.png")
        
        sample_image.save(output_path, format='PNG')
        
        assert os.path.exists(output_path)
        
        loaded = Image.open(output_path)
        assert loaded.format == 'PNG'
    
    def test_jpeg_quality_affects_size(self, sample_image, temp_dir):
        """Test that JPEG quality setting affects file size"""
        low_quality_path = os.path.join(temp_dir, "low_quality.jpg")
        high_quality_path = os.path.join(temp_dir, "high_quality.jpg")
        
        sample_image.save(low_quality_path, format='JPEG', quality=20)
        sample_image.save(high_quality_path, format='JPEG', quality=95)
        
        low_size = os.path.getsize(low_quality_path)
        high_size = os.path.getsize(high_quality_path)
        
        # High quality should be larger
        assert high_size > low_size
    
    def test_image_resize(self, sample_image, temp_dir):
        """Test image resizing functionality"""
        original_size = sample_image.size
        
        # Resize to 50%
        new_width = int(original_size[0] * 0.5)
        new_height = int(original_size[1] * 0.5)
        
        resized = sample_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        assert resized.size[0] == new_width
        assert resized.size[1] == new_height


class TestImageProcessor:
    """Test the full image processing pipeline"""
    
    def test_process_image_from_pil(self, sample_image, sample_metadata, temp_dir):
        """Test processing a PIL Image directly"""
        overlays = [{
            'type': 'text',
            'text': 'Processed Image',
            'anchor': 'Top-Left',
            'offset_x': 10,
            'offset_y': 10,
            'font_size': 24,
            'color': 'white'
        }]
        
        result = add_overlays(sample_image, overlays, sample_metadata)
        
        output_path = os.path.join(temp_dir, "processed.jpg")
        result.save(output_path, format='JPEG')
        
        assert os.path.exists(output_path)
    
    def test_process_image_from_path(self, sample_image, sample_metadata, temp_dir):
        """Test processing an image from file path"""
        # Save sample image first
        input_path = os.path.join(temp_dir, "input.jpg")
        sample_image.save(input_path, format='JPEG')
        
        overlays = [{
            'type': 'text',
            'text': 'From File Path',
            'anchor': 'Bottom-Left',
            'offset_x': 10,
            'offset_y': 10,
            'font_size': 24,
            'color': 'white'
        }]
        
        # Process using file path
        result = add_overlays(input_path, overlays, sample_metadata)
        
        assert result is not None
        assert isinstance(result, Image.Image)
    
    def test_output_matches_config_format(self, sample_image, temp_dir):
        """Test that output format matches configuration"""
        # Test PNG output
        png_path = os.path.join(temp_dir, "output.png")
        sample_image.save(png_path, format='PNG')
        loaded_png = Image.open(png_path)
        assert loaded_png.format == 'PNG'
        
        # Test JPEG output
        jpg_path = os.path.join(temp_dir, "output.jpg")
        sample_image.save(jpg_path, format='JPEG')
        loaded_jpg = Image.open(jpg_path)
        assert loaded_jpg.format == 'JPEG'


class TestAutoStretch:
    """Test auto-stretch (MTF) functionality"""
    
    def test_mtf_stretch_function(self):
        """Test the MTF stretch function"""
        import numpy as np
        from services.processor import mtf_stretch
        
        # Test with known values
        # When midtone = 0.5, output should equal input (identity)
        test_value = 0.3
        result = mtf_stretch(test_value, 0.5)
        assert abs(result - test_value) < 0.01
        
        # Test with array input
        test_array = np.array([0.0, 0.25, 0.5, 0.75, 1.0])
        result = mtf_stretch(test_array, 0.25)
        
        # Results should be in valid range
        assert np.all(result >= 0.0)
        assert np.all(result <= 1.0)
        
        # With midtone < 0.5, output should be brighter (higher values)
        assert result[1] > test_array[1]  # 0.25 should be stretched brighter
    
    def test_auto_stretch_dark_image(self, sample_image):
        """Test auto-stretch on a dark image"""
        import numpy as np
        from services.processor import auto_stretch_image
        
        # Create a dark image (simulating underexposed sky)
        dark_img = sample_image.point(lambda p: p * 0.1)
        
        stretch_config = {
            'enabled': True,
            'target_median': 0.25,
            'shadows_clip': 0.0,
            'highlights_clip': 1.0,
            'linked_stretch': True
        }
        
        result = auto_stretch_image(dark_img, stretch_config)
        
        # Result should be brighter than input
        input_array = np.array(dark_img).astype(float)
        output_array = np.array(result).astype(float)
        
        assert np.mean(output_array) > np.mean(input_array)
    
    def test_auto_stretch_preserves_size(self, sample_image):
        """Test that auto-stretch preserves image dimensions"""
        from services.processor import auto_stretch_image
        
        stretch_config = {
            'target_median': 0.25,
            'shadows_clip': 0.0,
            'highlights_clip': 1.0,
            'linked_stretch': True
        }
        
        result = auto_stretch_image(sample_image, stretch_config)
        
        assert result.size == sample_image.size
        assert result.mode == sample_image.mode
    
    def test_auto_stretch_shadow_clipping(self):
        """Test that MAD-based shadow clipping works correctly"""
        import numpy as np
        from services.processor import _stretch_channel
        
        # Create test channel with noise floor at ~0.05 and signal up to ~0.3
        np.random.seed(42)
        noise = np.random.normal(0.05, 0.01, (50, 50)).astype(np.float32)  # Noise floor around 0.05
        signal = np.zeros((50, 50), dtype=np.float32)
        signal[20:30, 20:30] = 0.3  # Some signal
        channel = np.clip(noise + signal, 0, 1)
        
        # Apply MAD-based stretch
        stretched = _stretch_channel(channel, target_median=0.25)
        
        # Result should be properly clipped and stretched
        assert stretched.min() >= 0.0
        assert stretched.max() <= 1.0
        # Median should be close to target
        assert abs(np.median(stretched) - 0.25) < 0.1
    
    def test_mtf_midtone_calculation(self):
        """Test MTF midtone parameter calculation"""
        from services.processor import _calculate_mtf_midtone
        
        # If current equals target, midtone should be ~0.5
        midtone = _calculate_mtf_midtone(0.25, 0.25)
        assert abs(midtone - 0.5) < 0.01
        
        # If current is darker than target, midtone should be < 0.5
        midtone_stretch = _calculate_mtf_midtone(0.1, 0.25)
        assert midtone_stretch < 0.5
