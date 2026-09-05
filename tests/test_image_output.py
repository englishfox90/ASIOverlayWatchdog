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


class TestAllSkyOutputCleanliness:
    """Phase 1 invariant: the all-sky overlay is preview-only and must never
    be baked into the output render (file / web / Discord / timelapse).

    The output path is add_overlays(); these tests guard against the
    `__allsky_config` bake-in branch ever being reintroduced there.
    """

    # Matches tests/test_allsky_rendering.py's proven recipe: this model +
    # config provably draws on a 1920x1080 frame.
    def _valid_calibration(self, tmp_path):
        from services.allsky.fisheye import FisheyeModel
        model = FisheyeModel(
            cx=960.0, cy=540.0, a1=600.0, a3=0.0, a5=0.0,
            roll=0.0, axis_alt=90.0, axis_az=0.0,
            rms_residual=1.0, n_matches=50,
            calibrated_at="2024-01-01T00:00:00+00:00",
            image_width=1920, image_height=1080,
        )
        cal_path = str(tmp_path / "cal.json")
        model.save(cal_path)
        return cal_path

    def _allsky_config(self, cal_path):
        return {
            'enabled': True,
            'calibration_file': cal_path,
            '_lat': 51.5, '_lon': -0.1,
            '_obs_utc': '2024-06-21T22:00:00+00:00',
            'grid': {'enabled': True, 'horizon': True, 'altitude_rings': True,
                     'opacity': 200},
            'constellations': {'enabled': True, 'lines': True, 'labels': False},
            'messier': {'enabled': True},
            'ngc': {'enabled': False},
            'planets': {'enabled': True, 'opacity': 255, 'marker_size': 10,
                        'label_size': 12, 'colors': {}},
        }

    def test_allsky_config_is_live(self, tmp_path):
        """Sanity / non-vacuity: this calibration + config DOES draw an overlay.

        Without this, the cleanliness assertion below could pass simply
        because nothing ever renders.
        """
        import numpy as np
        from services.allsky.overlay_renderer import render_allsky_overlay
        cal_path = self._valid_calibration(tmp_path)
        cfg = self._allsky_config(cal_path)

        img = Image.new('RGB', (1920, 1080), (10, 10, 30))
        result = render_allsky_overlay(img.copy(), cfg, {})
        diff = np.abs(np.array(img).astype(int)
                      - np.array(result.convert('RGB')).astype(int))
        assert diff.sum() > 0, "fixture is vacuous — overlay never draws"

    def test_allsky_config_not_baked_into_output(self, tmp_path):
        """add_overlays must ignore __allsky_config — output stays clean even
        with all-sky enabled and a valid calibration present."""
        import numpy as np
        cal_path = self._valid_calibration(tmp_path)
        cfg = self._allsky_config(cal_path)

        img = Image.new('RGB', (1920, 1080), (10, 10, 30))
        overlays = [{
            'type': 'text', 'text': 'Live', 'anchor': 'Top-Left',
            'offset_x': 10, 'offset_y': 10, 'font_size': 24, 'color': 'white',
        }]

        clean = add_overlays(img.copy(), overlays, {})
        with_allsky = add_overlays(
            img.copy(), overlays, {'__allsky_config': cfg})

        diff = np.abs(np.array(clean).astype(int)
                      - np.array(with_allsky).astype(int))
        assert diff.sum() == 0, (
            "all-sky overlay leaked into the output render — it must be "
            "preview-only (Phase 1 requirement)")

    # -- Opt-in per-destination burn-in (GitHub issue #10) -------------------
    #
    # These exercise the routing worker (ImageProcessorWorker._process_task)
    # rather than add_overlays() directly, since burn-in is chosen at the
    # pipeline level, reusing the preview render — it never touches add_overlays.

    def _run_worker(self, tmp_path, burn_into_output: dict):
        """Run one frame through ImageProcessorWorker._process_task with a
        live calibration + the given burn_into_output flags.

        Returns (preview_img, output_img, output_path, dispatch_img).
        weather is left unconfigured so the observing-window gate falls
        through to True deterministically (no real-time sun check) — see
        services/observing_window.py `_evaluate`.
        """
        pytest.importorskip("PySide6.QtWidgets")
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from ui.controllers.image_processor import ImageProcessorWorker, ImageProcessingTask

        cal_path = self._valid_calibration(tmp_path)
        allsky_cfg = self._allsky_config(cal_path)
        allsky_cfg['burn_into_output'] = burn_into_output

        config = {
            'output_dir': str(tmp_path),
            'output_format': 'PNG',
            'resize_percent': 100,
            'auto_stretch': {'enabled': False},
            'overlays': [],
            'dev_mode': {'enabled': False},
            'ml_contribution': {'enabled': False},
            'ml_models': {'enabled': False},
            'meteor': {},
            'sharpening': {},
            'allsky_overlay': allsky_cfg,
            'weather': {},
        }
        img = Image.new('RGB', (1920, 1080), (10, 10, 30))
        metadata = {'FILENAME': 'burn_in_test.png'}

        worker = ImageProcessorWorker()
        worker._main_window = None
        results = []
        worker.processing_complete.connect(
            lambda preview, out, meta, path, dispatch: results.append((preview, out, path, dispatch))
        )
        worker._process_task(ImageProcessingTask(img, metadata, config))

        assert results, "processing_complete did not fire"
        preview_img, output_img, output_path, dispatch_img = results[0]
        return preview_img, output_img, output_path, dispatch_img

    @staticmethod
    def _diff_sum(a: Image.Image, b: Image.Image) -> int:
        import numpy as np
        return int(np.abs(np.array(a.convert('RGB')).astype(int)
                          - np.array(b.convert('RGB')).astype(int)).sum())

    def test_burn_into_output_default_off_stays_clean_everywhere(self, tmp_path):
        """burn_into_output defaulting to all-False must leave the saved file
        and the web/library dispatch image clean, matching today's behaviour."""
        preview_img, output_img, output_path, dispatch_img = self._run_worker(
            tmp_path, burn_into_output={})

        saved = Image.open(output_path)
        assert self._diff_sum(saved, output_img) == 0, (
            "saved file changed even though burn_into_output is off by default")
        assert self._diff_sum(dispatch_img, output_img) == 0, (
            "web/Library dispatch image changed even though burn_into_output.web is off")
        # GUI preview is unaffected by burn_into_output — it always shows the overlay.
        assert self._diff_sum(preview_img, output_img) > 0, (
            "fixture regression — GUI preview should still show the live overlay")

    def test_burn_into_output_saved_file_enabled_bakes_overlay_in(self, tmp_path):
        """saved_file=True must bake the overlay into the file on disk while
        output_img (the signal's clean slot, cached by watch mode for
        'Calibrate Now') stays clean."""
        _, output_img, output_path, dispatch_img = self._run_worker(
            tmp_path, burn_into_output={'saved_file': True, 'web': False, 'timelapse': False})

        saved = Image.open(output_path)
        assert self._diff_sum(saved, output_img) > 0, (
            "saved_file=True but the on-disk file matches the clean render")
        # web wasn't opted in — dispatch must stay clean despite saved_file being on.
        assert self._diff_sum(dispatch_img, output_img) == 0, (
            "burn_into_output.web is off but the dispatch image carries the overlay")

    def test_burn_into_output_web_enabled_only_affects_dispatch(self, tmp_path):
        """web=True must burn the overlay into the web/Library dispatch image
        without touching the saved file."""
        _, output_img, output_path, dispatch_img = self._run_worker(
            tmp_path, burn_into_output={'saved_file': False, 'web': True, 'timelapse': False})

        saved = Image.open(output_path)
        assert self._diff_sum(saved, output_img) == 0, (
            "burn_into_output.saved_file is off but the saved file carries the overlay")
        assert self._diff_sum(dispatch_img, output_img) > 0, (
            "web=True but the dispatch image matches the clean render")

    def test_burn_into_output_all_enabled_output_img_still_clean(self, tmp_path):
        """Even with every destination opted in, output_img itself — the
        object ui/main_window/output.py caches verbatim as the clean
        watch-mode 'Calibrate Now' frame — must never carry the overlay."""
        preview_img, output_img, output_path, dispatch_img = self._run_worker(
            tmp_path, burn_into_output={'saved_file': True, 'web': True, 'timelapse': True})

        assert self._diff_sum(output_img, preview_img) > 0, (
            "output_img matches the overlaid preview — it must stay the clean frame")
        saved = Image.open(output_path)
        assert self._diff_sum(saved, output_img) > 0
        assert self._diff_sum(dispatch_img, output_img) > 0


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
