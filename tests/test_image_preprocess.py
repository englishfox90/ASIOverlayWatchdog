"""
Tests for ml/image_preprocess.py — the shared resize path for the roof/sky
classifiers. Pure numpy, no ONNX model needed, so these must run in the
default suite (not gated behind requires_ml_models).
"""
import numpy as np

from ml.image_preprocess import (
    block_average_resize,
    center_crop_square,
    resize_for_model,
)


class TestCenterCropSquare:
    def test_already_square_is_noop(self):
        img = np.arange(16).reshape(4, 4).astype(np.uint8)
        cropped = center_crop_square(img)
        assert cropped is img
        assert cropped.shape == (4, 4)

    def test_wide_image_crops_to_min_dimension(self):
        # 40 tall x 60 wide -> square of the min dimension (40)
        img = np.arange(40 * 60).reshape(40, 60).astype(np.uint8)
        cropped = center_crop_square(img)
        assert cropped.shape == (40, 40)

    def test_tall_image_crops_to_min_dimension(self):
        img = np.arange(60 * 40).reshape(60, 40).astype(np.uint8)
        cropped = center_crop_square(img)
        assert cropped.shape == (40, 40)

    def test_crop_is_centered_horizontally(self):
        h, w = 10, 20
        img = np.arange(h * w).reshape(h, w)
        cropped = center_crop_square(img)
        left = (w - h) // 2
        expected = img[:, left:left + h]
        np.testing.assert_array_equal(cropped, expected)

    def test_crop_is_centered_vertically(self):
        h, w = 20, 10
        img = np.arange(h * w).reshape(h, w)
        cropped = center_crop_square(img)
        top = (h - w) // 2
        expected = img[top:top + w, :]
        np.testing.assert_array_equal(cropped, expected)

    def test_odd_dimension_difference_floors_the_offset(self):
        # 11x20 -> crop width 11, left offset (20-11)//2 = 4 (not 4.5)
        img = np.arange(11 * 20).reshape(11, 20)
        cropped = center_crop_square(img)
        assert cropped.shape == (11, 11)
        np.testing.assert_array_equal(cropped, img[:, 4:15])


class TestBlockAverageResize:
    def test_output_shape_is_size_by_size(self):
        img = np.random.default_rng(0).integers(0, 256, (100, 100)).astype(np.uint8)
        out = block_average_resize(img, 10)
        assert out.shape == (10, 10)

    def test_output_is_floating_point(self):
        img = np.zeros((64, 64), dtype=np.uint8)
        out = block_average_resize(img, 8)
        assert np.issubdtype(out.dtype, np.floating)

    def test_uniform_input_produces_uniform_output(self):
        img = np.full((50, 50), 42, dtype=np.uint8)
        out = block_average_resize(img, 5)
        assert np.allclose(out, 42.0)

    def test_averages_within_each_block(self):
        # 4x4 image, target size 2 -> each output pixel averages a 2x2 block.
        img = np.array([
            [0, 0, 10, 10],
            [0, 0, 10, 10],
            [20, 20, 30, 30],
            [20, 20, 30, 30],
        ], dtype=np.float32)
        out = block_average_resize(img, 2)
        expected = np.array([[0.0, 10.0], [20.0, 30.0]])
        np.testing.assert_allclose(out, expected)

    def test_source_smaller_than_target_copies_into_top_left_corner(self):
        img = np.full((3, 3), 7, dtype=np.uint8)
        out = block_average_resize(img, 8)
        assert out.shape == (8, 8)
        assert np.all(out[:3, :3] == 7)
        # Everything outside the copied region stays at the zero fill value.
        assert np.all(out[3:, :] == 0)
        assert np.all(out[:, 3:] == 0)

    def test_source_smaller_on_one_side_only(self):
        # 3 rows but 10 cols: block_h == 0 triggers the copy branch, even
        # though block_w would not have.
        img = np.full((3, 10), 5, dtype=np.uint8)
        out = block_average_resize(img, 8)
        assert out.shape == (8, 8)
        assert np.all(out[:3, :8] == 5)


class TestResizeForModel:
    def test_square_input_end_to_end_shape(self):
        img = np.random.default_rng(1).integers(0, 256, (256, 256)).astype(np.uint8)
        out = resize_for_model(img, 32)
        assert out.shape == (32, 32)

    def test_non_square_input_crops_then_resizes(self):
        # Wide frame, e.g. a non-square all-sky/roof camera sensor crop.
        img = np.random.default_rng(2).integers(0, 256, (480, 640)).astype(np.uint8)
        out = resize_for_model(img, 64)
        assert out.shape == (64, 64)

    def test_matches_manual_crop_then_resize(self):
        img = np.random.default_rng(3).integers(0, 256, (300, 500)).astype(np.uint8)
        out = resize_for_model(img, 16)
        expected = block_average_resize(center_crop_square(img), 16)
        np.testing.assert_array_equal(out, expected)

    def test_already_square_frame_behaves_like_direct_resize(self):
        img = np.random.default_rng(4).integers(0, 256, (128, 128)).astype(np.uint8)
        out = resize_for_model(img, 16)
        expected = block_average_resize(img, 16)
        np.testing.assert_array_equal(out, expected)
