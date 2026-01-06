"""
Dev Mode Utilities for Image Processor

Handles saving debug data (FITS files, calibration JSON) when dev_mode is enabled.
Orchestrates image analysis, file writing, and context gathering.
"""
import os
import numpy as np
from datetime import datetime

from services.logger import app_logger

# Import context fetchers (moon, roof, weather, allsky)
from ui.controllers.context_fetchers import (
    compute_moon_context,
    fetch_roof_state,
    fetch_weather_context,
    estimate_seeing_conditions,
    fetch_allsky_snapshot,
)

# Import extracted modules
from ui.controllers.file_writers import save_raw_fits, save_luminance_fits, write_json
from ui.controllers.time_context import compute_time_context
from ui.controllers.image_analysis import (
    infer_normalization_denom,
    compute_luminance,
    compute_corner_analysis,
    log_channel_statistics,
)


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
            denom, denom_reason, denom_details = infer_normalization_denom(
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
            save_raw_fits(raw_fits_path, raw_array, image_bit_depth, base_header)
            
            # === Compute normalized array for statistics ===
            norm_array = raw_array.astype(np.float32) / denom
            
            # === Log per-channel statistics ===
            if dev_config.get('save_histogram_stats', True):
                log_channel_statistics(norm_array, raw_array)
            
            # === Compute and save grayscale luminance FITS ===
            lum = compute_luminance(norm_array)
            
            lum_fits_path = os.path.join(raw_dir, f"lum_{timestamp}.fits")
            save_luminance_fits(lum_fits_path, lum, base_header)
            
            # === Generate and save stretch calibration JSON ===
            calibration = self._compute_stretch_calibration(
                lum, norm_array, metadata, denom, denom_reason, denom_details,
                raw_dir, timestamp  # Pass for allsky snapshot saving
            )
            json_path = os.path.join(raw_dir, f"calibration_{timestamp}.json")
            write_json(json_path, calibration)
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
    
    def _compute_stretch_calibration(self, lum, norm_array, metadata, denom, denom_reason, denom_details,
                                       output_dir=None, timestamp=None):
        """
        Compute stretch calibration parameters from luminance.
        
        Returns:
            dict with calibration data including:
            - Basic info (timestamp, camera, exposure, gain)
            - Normalization details
            - Stretch parameters (black/white point, percentiles)
            - Corner analysis (for mode detection: day/night, roof open/closed)
            - Color balance
            - Moon phase and visibility
            - Roof state from NINA
            - Weather conditions
            - Estimated seeing conditions
            - All-sky camera snapshot (visual sky reference)
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
        corner_analysis = compute_corner_analysis(lum, norm_array)
        
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
        
        # Fetch weather once for both weather_context and seeing_estimate
        weather_ctx = fetch_weather_context()
        
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
            'time_context': compute_time_context(),
            'moon_context': compute_moon_context(),
            'roof_state': fetch_roof_state(),
            'weather_context': weather_ctx,
            'seeing_estimate': estimate_seeing_conditions(weather_ctx),
            'allsky_snapshot': fetch_allsky_snapshot(output_dir, timestamp),  # Visual sky reference
        }


# Singleton instance for use by ImageProcessorWorker
dev_mode_saver = DevModeDataSaver()
