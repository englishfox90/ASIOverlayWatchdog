"""
Test compass rose overlay
"""
import pytest
import os
import sys
import json
import numpy as np
from PIL import Image

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services.compass_overlay import draw_compass


def _make_image(w=256, h=256):
    """Create a test RGBA image."""
    return Image.new('RGBA', (w, h), (0, 0, 0, 255))


class TestCompassRendering:
    """Test compass overlay rendering"""

    def test_compass_renders_without_error(self):
        """Test compass renders on image without error at default rotation"""
        img = _make_image()
        result = draw_compass(img, rotation=0)
        assert result is not None
        assert result.size == (256, 256)

    def test_compass_modifies_image(self):
        """Test compass actually draws on the image (pixels change)"""
        img = _make_image()
        original = np.array(img).copy()
        result = draw_compass(img, rotation=0)
        assert not np.array_equal(original, np.array(result))

    def test_rotations_produce_distinct_output(self):
        """Test compass at 0, 90, 180, 270 rotations produces distinct outputs"""
        images = []
        for angle in [0, 90, 180, 270]:
            img = _make_image()
            result = draw_compass(img, rotation=angle)
            images.append(np.array(result))

        # Each rotation should differ from at least one other
        all_same = True
        for i in range(len(images)):
            for j in range(i + 1, len(images)):
                if not np.array_equal(images[i], images[j]):
                    all_same = False
                    break
        assert not all_same, "Different rotations should produce distinct outputs"


class TestCompassMirror:
    """Test the E/W mirror option"""

    def test_mirror_changes_output(self):
        """Test mirroring produces a different image from the default"""
        normal = np.array(draw_compass(_make_image(), size=160, cx=128, cy=128))
        mirrored = np.array(draw_compass(_make_image(), size=160, cx=128, cy=128,
                                         mirror=True))
        assert not np.array_equal(normal, mirrored)

    def test_mirror_swaps_east_and_west_labels(self):
        """Test the E label moves to the W side (and vice versa) when mirrored"""
        size, cx, cy = 160, 128, 128
        normal = draw_compass(_make_image(), size=size, cx=cx, cy=cy)
        mirrored = draw_compass(_make_image(), size=size, cx=cx, cy=cy, mirror=True)

        def _label_ink(img, x0, x1):
            # Band sits outside the star points, so it only contains the label
            crop = img.crop((cx + x0, cy - 20, cx + x1, cy + 20))
            return int(np.array(crop)[:, :, :3].sum())

        west_band, east_band = (-92, -58), (58, 92)
        assert _label_ink(normal, *east_band) == _label_ink(mirrored, *west_band)
        assert _label_ink(normal, *west_band) == _label_ink(mirrored, *east_band)
        # Guard the assertions above against E and W rendering identically
        assert _label_ink(normal, *east_band) != _label_ink(normal, *west_band)

    def test_mirror_keeps_north_up(self):
        """Test mirroring is left-right only — N stays where rotation puts it"""
        size, cx, cy = 160, 128, 128
        label_r = (size // 2) * 0.88
        box = 18

        def _north(img):
            return np.array(img.crop((cx - box, int(cy - label_r - box),
                                      cx + box, int(cy - label_r + box))))

        normal = draw_compass(_make_image(), size=size, cx=cx, cy=cy)
        mirrored = draw_compass(_make_image(), size=size, cx=cx, cy=cy, mirror=True)
        assert np.array_equal(_north(normal), _north(mirrored))


class TestCompassPosition:
    """Test compass position options"""

    def test_all_positions_render(self):
        """Test compass position is configurable (center, corners)"""
        positions = ['center', 'top-left', 'top-right', 'bottom-left', 'bottom-right']
        for pos in positions:
            img = _make_image()
            result = draw_compass(img, position=pos)
            assert result is not None, f"Failed to render at position {pos}"

    def test_positions_differ(self):
        """Test different positions produce different images"""
        img1 = draw_compass(_make_image(), position='top-left')
        img2 = draw_compass(_make_image(), position='bottom-right')
        assert not np.array_equal(np.array(img1), np.array(img2))


class TestCompassEdgeCases:
    """Test edge cases"""

    def test_small_image_no_crash(self):
        """Test compass on small image doesn't crash or overflow bounds"""
        img = _make_image(32, 32)
        # Small image should skip drawing (too small for compass)
        result = draw_compass(img, size=80)
        assert result is not None

    def test_rgb_input_converted(self):
        """Test RGB input is handled (converted to RGBA)"""
        img = Image.new('RGB', (256, 256), (0, 0, 0))
        result = draw_compass(img)
        assert result.mode == 'RGBA'

    def test_custom_size(self):
        """Test custom compass size"""
        img = _make_image(512, 512)
        result = draw_compass(img, size=120)
        assert result is not None


class TestCompassExplicitCoords:
    """Test compass with explicit cx/cy coordinates"""

    def test_explicit_coords(self):
        """Test compass renders at explicit cx/cy coordinates"""
        img = _make_image(256, 256)
        result = draw_compass(img, rotation=0, size=60, cx=128, cy=128)
        assert result is not None
        assert result.size == (256, 256)
        # Should have drawn something
        assert not np.array_equal(np.array(_make_image(256, 256)), np.array(result))

    def test_explicit_coords_override_position(self):
        """Test cx/cy take precedence over position string"""
        img1 = draw_compass(_make_image(), cx=50, cy=50, size=40)
        img2 = draw_compass(_make_image(), position='bottom-right', cx=50, cy=50, size=40)
        assert np.array_equal(np.array(img1), np.array(img2))


class TestCompassConfig:
    """Test compass overlay config round-trip via overlays list"""

    def test_config_round_trip(self, temp_config):
        """Test compass overlay config round-trips through save/load"""
        from services.config import Config
        config = Config(temp_config)

        overlays = config.get('overlays', [])
        overlays.append({
            'name': 'Compass Rose',
            'type': 'compass',
            'rotation': 45,
            'size': 100,
            'anchor': 'Top-Right',
            'offset_x': 20,
            'offset_y': 20,
        })
        config.set('overlays', overlays)
        config.save()

        config2 = Config(temp_config)
        loaded_overlays = config2.get('overlays', [])
        compass = [o for o in loaded_overlays if o.get('type') == 'compass']
        assert len(compass) == 1
        assert compass[0]['rotation'] == 45
        assert compass[0]['size'] == 100
        assert compass[0]['anchor'] == 'Top-Right'
