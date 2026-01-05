"""
Dev Mode Utilities for Image Processor

Handles saving debug data (FITS files, calibration JSON) when dev_mode is enabled.
Contains image analysis functions for stretch calibration and mode detection.
"""
import os
import json
import numpy as np
from datetime import datetime

from services.logger import app_logger


class DevModeDataSaver:
    """Handles saving raw FITS and calibration data in dev_mode"""
    
    def save_dev_mode_data(self, img, raw_array, output_dir, metadata, dev_config):
        """
        Save raw data and calibration JSON when dev_mode is enabled.
        
        Creates:
        - raw_YYYYMMDD_HHMMSS.fits - Raw RGB FITS file
        - lum_YYYYMMDD_HHMMSS.fits - Grayscale luminance FITS
        - calibration_YYYYMMDD_HHMMSS.json - Calibration parameters
        
        Args:
            img: PIL Image (for fallback, not currently used)
            raw_array: numpy array (uint8 or uint16), shape (H,W) or (H,W,3)
            output_dir: Directory to save files (uses raw_debug subfolder)
            metadata: Image metadata dict
            dev_config: Dev mode configuration dict
        """
        try:
            # Create raw_debug subdirectory
            raw_dir = os.path.join(output_dir, 'raw_debug')
            os.makedirs(raw_dir, exist_ok=True)
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # Get camera bit depth info from metadata
            camera_bit_depth = metadata.get('CAMERA_BIT_DEPTH', 8)
            image_bit_depth = metadata.get('IMAGE_BIT_DEPTH', 8)
            
            # Infer correct normalization denominator with full diagnostics
            denom, denom_reason, denom_details = self._infer_normalization_denom(
                raw_array, image_bit_depth, camera_bit_depth
            )
            
            # Log single comprehensive line with all key diagnostics
            app_logger.info(
                f"DEV MODE Raw Values: min={denom_details['raw_min']}, "
                f"median={denom_details.get('raw_median', 'N/A')}, "
                f"p99={denom_details.get('raw_p99', 'N/A')}, "
                f"max={denom_details['raw_max']}, "
                f"denom={int(denom)}, "
                f"mul16_rate={denom_details['mul16_rate']:.3f}, "
                f"unique_ratio={denom_details['unique_ratio']:.4f}, "
                f"reason=\"{denom_reason}\""
            )
            
            app_logger.info(
                f"DEV MODE: Camera ADC: {camera_bit_depth}-bit, "
                f"Image mode: {image_bit_depth}-bit, Denom: {denom} ({denom_reason})"
            )
            
            # Base header info for FITS files
            base_header = {
                'CAMERA': metadata.get('CAMERA', 'Unknown'),
                'EXPOSURE': metadata.get('EXPOSURE', 'N/A'),
                'GAIN': metadata.get('GAIN', 'N/A'),
                'TEMP': metadata.get('TEMP', 'N/A'),
                'DATE-OBS': metadata.get('DATETIME', datetime.now().isoformat()),
                'INSTRUME': metadata.get('CAMERA', 'ZWO ASI Camera'),
                'BITDEPTH': (camera_bit_depth, 'Camera ADC bit depth'),
                'IMGBITS': (image_bit_depth, 'Original image bit depth'),
                'NORMDNOM': (denom, 'Normalization denominator used'),
                'BAYERPAT': metadata.get('BAYER_PATTERN', 'BGGR'),
                'PIXSIZE': (metadata.get('PIXEL_SIZE', 0), 'Pixel size in microns'),
                'EGAIN': (metadata.get('ELEC_PER_ADU', 1.0), 'Electrons per ADU'),
            }
            
            # === Save raw RGB/mono FITS ===
            raw_fits_path = os.path.join(raw_dir, f"raw_{timestamp}.fits")
            self._save_raw_fits(raw_fits_path, raw_array, image_bit_depth, base_header)
            
            # === Compute normalized array for statistics ===
            norm_array = raw_array.astype(np.float32) / denom
            
            # === Log per-channel statistics ===
            if dev_config.get('save_histogram_stats', True):
                self._log_channel_statistics(norm_array, raw_array)
            
            # === Compute and save grayscale luminance FITS ===
            lum = self._compute_luminance(norm_array)
            
            lum_fits_path = os.path.join(raw_dir, f"lum_{timestamp}.fits")
            lum_header = base_header.copy()
            lum_header['COMMENT'] = 'Grayscale luminance (0.299R + 0.587G + 0.114B)'
            lum_header['DATATYPE'] = ('float32', 'Luminance in 0..1 range')
            self._write_fits(lum_fits_path, lum.astype(np.float32), lum_header)
            app_logger.info(
                f"DEV MODE: ✓ Saved luminance FITS to lum_{timestamp}.fits (shape: {lum.shape})"
            )
            
            # === Generate and save stretch calibration JSON ===
            calibration = self._compute_stretch_calibration(
                lum, norm_array, metadata, denom, denom_reason, denom_details
            )
            json_path = os.path.join(raw_dir, f"calibration_{timestamp}.json")
            self._write_json(json_path, calibration)
            app_logger.info(f"DEV MODE: ✓ Saved calibration JSON to calibration_{timestamp}.json")
            
            # Log key calibration values
            app_logger.info(
                f"DEV MODE Calibration: black_pt={calibration['stretch']['black_point']:.4f}, "
                f"white_pt={calibration['stretch']['white_point']:.4f}, "
                f"median_lum={calibration['stretch']['median_lum']:.4f}, "
                f"asinh_strength={calibration['stretch']['recommended_asinh_strength']:.1f}"
            )
            
            # Log corner analysis (for mode detection debugging)
            ca = calibration.get('corner_analysis', {})
            if ca:
                app_logger.info(
                    f"DEV MODE Corner Analysis: corner_med={ca.get('corner_med', 0):.4f}, "
                    f"center_med={ca.get('center_med', 0):.4f}, "
                    f"ratio={ca.get('corner_to_center_ratio', 0):.3f}, "
                    f"delta={ca.get('center_minus_corner', 0):.4f}"
                )
            
        except Exception as e:
            import traceback
            app_logger.error(f"DEV MODE: Failed to save debug data: {e}")
            app_logger.error(traceback.format_exc())
    
    def _infer_normalization_denom(self, raw_array, image_bit_depth, camera_bit_depth):
        """
        Infer the correct normalization denominator based on actual data.
        
        Analyzes actual pixel values to detect:
        - 8-bit payload in 16-bit container
        - 12-bit data (max <= 4095)
        - 12-bit left-shifted to 16-bit (many multiples of 16)
        - True 16-bit data
        """
        # Early exit for 8-bit capture mode
        if image_bit_depth == 8:
            return 255.0, "8-bit capture mode (IMAGE_BIT_DEPTH=8)", {
                'raw_min': int(np.min(raw_array)),
                'raw_max': int(np.max(raw_array)),
                'mul16_rate': 0.0,
                'unique_ratio': 1.0,
                'unique_count': 0,
            }
        
        # For 16-bit container, analyze actual values
        if raw_array.dtype == np.uint8:
            return 255.0, "8-bit array dtype despite IMAGE_BIT_DEPTH=16", {
                'raw_min': int(np.min(raw_array)),
                'raw_max': int(np.max(raw_array)),
                'mul16_rate': 0.0,
                'unique_ratio': 1.0,
                'unique_count': 0,
            }
        
        # Compute statistics on flattened array
        flat = raw_array.flatten().astype(np.uint16)
        
        raw_min = int(np.min(flat))
        raw_max = int(np.max(flat))
        raw_median = int(np.median(flat))
        raw_p99 = int(np.percentile(flat, 99))
        
        # Sample for expensive computations
        sample_size = min(100000, flat.size)
        if flat.size > sample_size:
            sample = flat[np.random.choice(flat.size, sample_size, replace=False)]
        else:
            sample = flat
        
        # Detect left-shifted 12-bit data (values are multiples of 16 = 2^4)
        mul16_rate = float(np.mean(sample % 16 == 0))
        
        # Unique value analysis
        unique_vals = np.unique(sample)
        unique_count = len(unique_vals)
        unique_ratio = unique_count / len(sample)
        
        # Build base details dict
        details = {
            'raw_min': raw_min,
            'raw_max': raw_max,
            'raw_median': raw_median,
            'raw_p99': raw_p99,
            'mul16_rate': round(mul16_rate, 4),
            'unique_count': unique_count,
            'unique_ratio': round(unique_ratio, 6),
            'sample_size': len(sample),
        }
        
        # === Inference rules (in priority order) ===
        
        # Rule 1: 8-bit payload in 16-bit container
        if raw_max <= 255:
            details['suggested_downshift_bits'] = 0
            return 255.0, f"8-bit payload detected (max={raw_max})", details
        
        # Rule 2: 12-bit range (max <= 4095)
        if raw_max <= 4095:
            details['suggested_downshift_bits'] = 0
            return 4095.0, f"12-bit range detected (max={raw_max})", details
        
        # Rule 3: Left-shifted 12-bit data
        if mul16_rate >= 0.90:
            details['suggested_downshift_bits'] = 4
            return 65535.0, f"12-bit left-shifted (mul16_rate={mul16_rate:.2f})", details
        
        # Rule 4: Default to 16-bit
        details['suggested_downshift_bits'] = 0
        return 65535.0, f"16-bit range detected (max={raw_max})", details
    
    def _compute_luminance(self, norm_array):
        """Compute luminance from normalized RGB array using Rec.601 coefficients."""
        if norm_array.ndim == 2:
            return norm_array
        elif norm_array.ndim == 3 and norm_array.shape[2] == 3:
            return 0.299 * norm_array[:,:,0] + 0.587 * norm_array[:,:,1] + 0.114 * norm_array[:,:,2]
        else:
            app_logger.warning(f"DEV MODE: Unexpected array shape {norm_array.shape}")
            return norm_array.mean(axis=-1) if norm_array.ndim > 2 else norm_array
    
    def _save_raw_fits(self, path, raw_array, image_bit_depth, header_kv):
        """Save raw image data as FITS, preserving true dynamic range."""
        try:
            from astropy.io import fits
            
            if image_bit_depth == 16:
                data = raw_array.astype(np.uint16)
                header_kv['SCALED'] = (False, 'Data saved without scaling')
                header_kv['COMMENT'] = 'RAW16 data - true sensor values preserved'
            else:
                data = (raw_array.astype(np.uint16) * 257)
                header_kv['SCALED'] = (True, 'RAW8 scaled to 16-bit (x257)')
                header_kv['COMMENT'] = 'RAW8 data scaled to 16-bit for FITS'
            
            if data.ndim == 3 and data.shape[2] == 3:
                data = np.transpose(data, (2, 0, 1))
                header_kv['COLORTYP'] = ('RGB', 'Color type of image')
            elif data.ndim == 2:
                header_kv['COLORTYP'] = ('MONO', 'Grayscale/mono image')
            
            self._write_fits(path, data, header_kv)
            app_logger.info(
                f"DEV MODE: ✓ Saved raw FITS to {os.path.basename(path)} "
                f"(shape: {data.shape}, scaled={image_bit_depth != 16})"
            )
            
        except ImportError:
            from PIL import Image
            tiff_path = path.replace('.fits', '.tiff')
            Image.fromarray(raw_array).save(tiff_path, 'TIFF', compression=None)
            app_logger.info(
                f"DEV MODE: ✓ Saved raw TIFF to {os.path.basename(tiff_path)} "
                "(astropy not installed)"
            )
    
    def _write_fits(self, path, data, header_kv):
        """Write data to FITS file with header keywords."""
        from astropy.io import fits
        
        hdu = fits.PrimaryHDU(data)
        for key, val in header_kv.items():
            if isinstance(val, tuple) and len(val) == 2:
                hdu.header[key] = val
            else:
                hdu.header[key] = val
        
        hdu.writeto(path, overwrite=True)
    
    def _write_json(self, path, payload):
        """Write dictionary to JSON file with pretty formatting"""
        with open(path, 'w') as f:
            json.dump(payload, f, indent=2, default=str)
    
    def _compute_corner_analysis(self, lum, norm_array=None, roi_size=50, margin=5):
        """
        Compute corner-vs-center analysis for mode classification.
        
        This analysis helps detect:
        - Roof open vs closed (corners ~= center when closed)
        - Day vs night (absolute brightness levels)
        - Overscan bias levels (corner medians)
        """
        h, w = lum.shape
        
        # Define corner ROIs (50x50, 5px margin from edge)
        corners = {
            'tl': lum[margin:margin+roi_size, margin:margin+roi_size],
            'tr': lum[margin:margin+roi_size, w-margin-roi_size:w-margin],
            'bl': lum[h-margin-roi_size:h-margin, margin:margin+roi_size],
            'br': lum[h-margin-roi_size:h-margin, w-margin-roi_size:w-margin],
        }
        
        all_corners = np.concatenate([c.flatten() for c in corners.values()])
        
        # Define center ROI (central 25% of image)
        ch, cw = h // 4, w // 4
        center = lum[ch:3*ch, cw:3*cw]
        
        # Compute corner stats
        corner_med = float(np.median(all_corners))
        corner_p90 = float(np.percentile(all_corners, 90))
        corner_mad = float(np.median(np.abs(all_corners - corner_med)))
        corner_stddev = float(corner_mad * 1.4826)
        
        corner_meds = {k: float(np.median(c)) for k, c in corners.items()}
        
        # Compute center stats
        center_flat = center.flatten()
        center_med = float(np.median(center_flat))
        center_p90 = float(np.percentile(center_flat, 90))
        
        # Ratios for mode classification
        corner_to_center_ratio = corner_med / center_med if center_med > 0.001 else 1.0
        center_minus_corner = center_med - corner_med
        
        result = {
            'roi_size': roi_size,
            'margin': margin,
            'corner_med': round(corner_med, 6),
            'corner_p90': round(corner_p90, 6),
            'corner_stddev': round(corner_stddev, 6),
            'corner_meds': {k: round(v, 6) for k, v in corner_meds.items()},
            'center_med': round(center_med, 6),
            'center_p90': round(center_p90, 6),
            'corner_to_center_ratio': round(corner_to_center_ratio, 4),
            'center_minus_corner': round(center_minus_corner, 6),
        }
        
        # Per-channel RGB corner bias (if RGB array provided)
        if norm_array is not None and norm_array.ndim == 3 and norm_array.shape[2] == 3:
            rgb_bias = {}
            for c, name in enumerate(['bias_r', 'bias_g', 'bias_b']):
                channel = norm_array[:,:,c]
                ch_corners = np.concatenate([
                    channel[margin:margin+roi_size, margin:margin+roi_size].flatten(),
                    channel[margin:margin+roi_size, w-margin-roi_size:w-margin].flatten(),
                    channel[h-margin-roi_size:h-margin, margin:margin+roi_size].flatten(),
                    channel[h-margin-roi_size:h-margin, w-margin-roi_size:w-margin].flatten(),
                ])
                rgb_bias[name] = round(float(np.median(ch_corners)), 6)
            result['rgb_corner_bias'] = rgb_bias
        
        return result
    
    def _log_channel_statistics(self, norm_array, raw_array):
        """Log detailed per-channel statistics"""
        channel_names = ['R', 'G', 'B'] if norm_array.ndim == 3 and norm_array.shape[2] == 3 else ['Y']
        
        for c, channel_name in enumerate(channel_names):
            if norm_array.ndim == 3:
                channel = norm_array[:, :, c]
                raw_channel = raw_array[:, :, c]
            else:
                channel = norm_array
                raw_channel = raw_array
            
            median = np.median(channel)
            mean = np.mean(channel)
            std = np.std(channel)
            min_val = np.min(channel)
            max_val = np.max(channel)
            p1 = np.percentile(channel, 1)
            p99 = np.percentile(channel, 99)
            mad = np.median(np.abs(channel - median))
            
            raw_min = int(np.min(raw_channel))
            raw_max = int(np.max(raw_channel))
            
            app_logger.info(
                f"DEV MODE {channel_name}: median={median:.4f}, mean={mean:.4f}, "
                f"std={std:.4f}, MAD={mad:.4f}, min={min_val:.4f}, max={max_val:.4f}, "
                f"p1={p1:.4f}, p99={p99:.4f}, raw_range=[{raw_min}-{raw_max}]"
            )
            
            if norm_array.ndim == 2:
                break
        
        # Log luminance stats for RGB
        if norm_array.ndim == 3 and norm_array.shape[2] == 3:
            lum = self._compute_luminance(norm_array)
            app_logger.info(
                f"DEV MODE Luminance: median={np.median(lum):.4f}, mean={np.mean(lum):.4f}, "
                f"MAD={np.median(np.abs(lum - np.median(lum))):.4f}"
            )
            
            r_mean = np.mean(norm_array[:,:,0])
            g_mean = np.mean(norm_array[:,:,1])
            b_mean = np.mean(norm_array[:,:,2])
            app_logger.info(
                f"DEV MODE Color Balance: R/G={r_mean/g_mean:.3f}, B/G={b_mean/g_mean:.3f} "
                f"(1.0 = neutral)"
            )
    
    def _compute_stretch_calibration(self, lum, norm_array, metadata, denom, denom_reason, denom_details):
        """
        Compute stretch calibration parameters from luminance.
        
        Returns:
            dict with calibration data including:
            - Basic info (timestamp, camera, exposure, gain)
            - Normalization details
            - Stretch parameters (black/white point, percentiles)
            - Corner analysis (for mode detection: day/night, roof open/closed)
            - Color balance
        """
        # Extended percentile stats
        p1 = float(np.percentile(lum, 1))
        p10 = float(np.percentile(lum, 10))
        p50 = float(np.median(lum))
        p90 = float(np.percentile(lum, 90))
        p99 = float(np.percentile(lum, 99))
        
        black_point = float(np.percentile(lum, 2))
        white_point = float(np.percentile(lum, 99.7))
        mean_lum = float(np.mean(lum))
        dynamic_range = white_point - black_point
        
        is_dark_scene = p50 < 0.05
        
        if p50 > 0.001:
            asinh_strength = min(500, max(50, 5.0 / p50))
        else:
            asinh_strength = 500
        
        # Compute corner analysis
        corner_analysis = self._compute_corner_analysis(lum, norm_array)
        
        # Color balance
        color_balance = {}
        if norm_array.ndim == 3 and norm_array.shape[2] == 3:
            r_mean = float(np.mean(norm_array[:,:,0]))
            g_mean = float(np.mean(norm_array[:,:,1]))
            b_mean = float(np.mean(norm_array[:,:,2]))
            if g_mean > 0:
                color_balance = {
                    'r_g': round(r_mean / g_mean, 3),
                    'b_g': round(b_mean / g_mean, 3)
                }
        
        return {
            'timestamp': datetime.now().isoformat(),
            'camera': metadata.get('CAMERA', 'Unknown'),
            'exposure': metadata.get('EXPOSURE', 'N/A'),
            'gain': metadata.get('GAIN', 'N/A'),
            'image_bit_depth': metadata.get('IMAGE_BIT_DEPTH', 8),
            'camera_bit_depth': metadata.get('CAMERA_BIT_DEPTH', 8),
            'bayer_pattern': metadata.get('BAYER_PATTERN', 'BGGR'),
            'normalization': {
                'denom': int(denom),
                'reason': denom_reason,
                'raw_max': denom_details.get('raw_max', 0),
                'raw_min': denom_details.get('raw_min', 0),
                'mul16_rate': denom_details.get('mul16_rate', 0.0),
                'unique_ratio': denom_details.get('unique_ratio', 0.0),
                'unique_count': denom_details.get('unique_count', 0),
                'suggested_downshift_bits': denom_details.get('suggested_downshift_bits', 0),
            },
            'stretch': {
                'black_point': round(black_point, 6),
                'white_point': round(white_point, 6),
                'median_lum': round(p50, 6),
                'mean_lum': round(mean_lum, 6),
                'dynamic_range': round(dynamic_range, 6),
                'is_dark_scene': is_dark_scene,
                'recommended_asinh_strength': round(asinh_strength, 1)
            },
            'percentiles': {
                'p1': round(p1, 6),
                'p10': round(p10, 6),
                'p50': round(p50, 6),
                'p90': round(p90, 6),
                'p99': round(p99, 6),
            },
            'corner_analysis': corner_analysis,
            'color_balance': color_balance,
            'time_context': self._compute_time_context(),
        }
    
    def _compute_time_context(self):
        """
        Compute time-of-day context for mode classification.
        
        Helps distinguish between:
        - Day + Roof Closed (light leaking through dome)
        - Night + Roof Open (sky visible)
        
        Returns:
            dict with time context information
        """
        now = datetime.now()
        hour = now.hour
        
        # Simple day/night classification based on hour
        # Could be enhanced with sunrise/sunset calculation using location
        if 6 <= hour < 18:
            period = 'day'
        elif 18 <= hour < 21 or 5 <= hour < 6:
            period = 'twilight'
        else:
            period = 'night'
        
        # More granular time periods
        if 5 <= hour < 8:
            detailed_period = 'dawn'
        elif 8 <= hour < 12:
            detailed_period = 'morning'
        elif 12 <= hour < 17:
            detailed_period = 'afternoon'
        elif 17 <= hour < 20:
            detailed_period = 'evening'
        elif 20 <= hour < 22:
            detailed_period = 'dusk'
        else:
            detailed_period = 'night'
        
        return {
            'hour': hour,
            'minute': now.minute,
            'period': period,           # 'day', 'twilight', 'night'
            'detailed_period': detailed_period,  # 'dawn', 'morning', etc.
            'is_daylight': 6 <= hour < 20,
            'is_astronomical_night': hour >= 22 or hour < 5,
        }


# Singleton instance for use by ImageProcessorWorker
dev_mode_saver = DevModeDataSaver()
