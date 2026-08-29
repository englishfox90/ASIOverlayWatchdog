"""
Tests for ml/image_preprocess.py — the shared resize path for the roof/sky
classifiers. Pure numpy, no ONNX model needed, so these must run in the
default suite (not gated behind requires_ml_models).
"""
import numpy as np
import pytest

from ml.image_preprocess import (
    as_gray_float32,
    block_average_resize,
    center_crop_square,
    crop_for_model,
    resize_for_model,
    to_gray_float32,
)


def _reference_luma(img):
    """The whole-frame float64 expression to_gray_float32 replaces."""
    return (0.299 * img[:, :, 0]
            + 0.587 * img[:, :, 1]
            + 0.114 * img[:, :, 2]).astype(np.float32)


class TestToGrayFloat32:
    def test_rgb_is_bit_identical_to_the_float64_reference(self):
        img = np.random.default_rng(10).integers(0, 65535, (37, 53, 3)).astype(np.uint16)
        np.testing.assert_array_equal(to_gray_float32(img), _reference_luma(img))

    def test_rgb_is_bit_identical_across_the_row_chunk_boundary(self):
        # Taller than the internal chunk height, so the chunked accumulation is
        # exercised and must still match the whole-frame reference exactly.
        img = np.random.default_rng(11).integers(0, 65535, (700, 9, 3)).astype(np.uint16)
        np.testing.assert_array_equal(to_gray_float32(img), _reference_luma(img))

    def test_float_rgb_is_bit_identical_to_the_reference(self):
        img = np.random.default_rng(12).random((300, 40, 3)).astype(np.float32)
        np.testing.assert_array_equal(to_gray_float32(img), _reference_luma(img))

    def test_returns_2d_float32(self):
        img = np.zeros((8, 6, 3), dtype=np.uint8)
        out = to_gray_float32(img)
        assert out.dtype == np.float32
        assert out.shape == (8, 6)

    def test_non_three_channel_takes_first_channel(self):
        img = np.arange(4 * 5 * 4, dtype=np.uint16).reshape(4, 5, 4)
        np.testing.assert_array_equal(to_gray_float32(img), img[:, :, 0].astype(np.float32))

    def test_two_d_integer_input_is_converted(self):
        img = np.array([[1, 2], [3, 4]], dtype=np.uint16)
        out = to_gray_float32(img)
        assert out.dtype == np.float32
        np.testing.assert_array_equal(out, [[1.0, 2.0], [3.0, 4.0]])

    def test_two_d_float32_input_is_copied_never_aliased(self):
        # The returned plane is shared between classifiers and one of them
        # stretches its own copy of it; aliasing the caller's array here would
        # let a later in-place op corrupt the source.
        img = np.ones((4, 4), dtype=np.float32)
        out = to_gray_float32(img)
        assert out is not img
        assert not np.shares_memory(out, img)
        out[0, 0] = 99.0
        assert img[0, 0] == 1.0


class TestAsGrayFloat32:
    def test_float32_2d_plane_is_reused_as_is(self):
        img = np.ones((4, 4), dtype=np.float32)
        assert as_gray_float32(img) is img

    def test_rgb_frame_is_converted(self):
        img = np.random.default_rng(13).integers(0, 255, (16, 16, 3)).astype(np.uint8)
        np.testing.assert_array_equal(as_gray_float32(img), _reference_luma(img))

    def test_non_float32_2d_frame_is_converted(self):
        img = np.ones((4, 4), dtype=np.uint16)
        out = as_gray_float32(img)
        assert out.dtype == np.float32
        assert out is not img


class TestCropForModel:
    @pytest.mark.parametrize("shape,size", [
        ((3552, 3552), 384),
        ((3552, 3552), 128),
        ((256, 256), 32),
        ((480, 640), 64),
        ((300, 500), 16),
        ((101, 97), 8),
    ])
    def test_cropping_first_does_not_change_the_resize_output(self, shape, size):
        img = np.random.default_rng(14).random(shape).astype(np.float32)
        direct = resize_for_model(img, size)
        cropped = resize_for_model(crop_for_model(img, size), size)
        np.testing.assert_array_equal(direct, cropped)

    def test_cropped_region_divides_evenly_into_blocks(self):
        img = np.zeros((3552, 3552), dtype=np.float32)
        cropped = crop_for_model(img, 384)
        assert cropped.shape == (3456, 3456)
        assert cropped.shape[0] % 384 == 0

    def test_source_smaller_than_target_is_left_to_resize_for_model(self):
        img = np.zeros((3, 10), dtype=np.float32)
        cropped = crop_for_model(img, 8)
        assert cropped.shape == (3, 3)  # center_crop_square only; no block trim
        assert resize_for_model(cropped, 8).shape == (8, 8)


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
