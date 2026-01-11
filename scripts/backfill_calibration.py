#!/usr/bin/env python3
"""
Backfill Calibration JSON Files

Adds missing fields (corner_analysis, percentiles, time_context) to existing
calibration JSON files by re-analyzing the corresponding raw/lum FITS files.

Usage:
    python backfill_calibration.py <directory> [--dry-run]
    
Examples:
    python backfill_calibration.py "H:\\raw_debug" --dry-run
    python backfill_calibration.py "H:\\raw_debug\\Roof Closed Day Time"
"""
import argparse
import json
import os
import sys
import re
from datetime import datetime, date, timedelta
from pathlib import Path

import numpy as np

try:
    from astropy.io import fits
except ImportError:
    print("ERROR: astropy required. Install with: pip install astropy")
    sys.exit(1)

# Try to import astral for accurate sun calculations
try:
    from astral import LocationInfo
    from astral.sun import sun, twilight
    ASTRAL_AVAILABLE = True
except ImportError:
    ASTRAL_AVAILABLE = False
    print("WARNING: astral not installed. Using simple hour-based time classification.")
    print("         Install with: pip install astral")

# Try to import Config for location settings
try:
    # Add parent directory to path to import services
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from services.config import Config
    CONFIG_AVAILABLE = True
except ImportError:
    CONFIG_AVAILABLE = False
    if ASTRAL_AVAILABLE:
        print("WARNING: Could not import Config. Will use simple hour-based time classification.")


def parse_timestamp_from_filename(filename):
    """
    Extract timestamp from filename like calibration_20260105_165636.json
    Returns datetime object or None if pattern doesn't match.
    """
    match = re.search(r'(\d{8})_(\d{6})', filename)
    if match:
        date_str, time_str = match.groups()
        try:
            return datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
        except ValueError:
            return None
    return None


def compute_corner_analysis(lum, norm_array=None, roi_size=50, margin=5):
    """
    Compute corner-vs-center analysis for mode classification.
    """
    h, w = lum.shape
    
    # Define corner ROIs
    corners = {
        'tl': lum[margin:margin+roi_size, margin:margin+roi_size],
        'tr': lum[margin:margin+roi_size, w-margin-roi_size:w-margin],
        'bl': lum[h-margin-roi_size:h-margin, margin:margin+roi_size],
        'br': lum[h-margin-roi_size:h-margin, w-margin-roi_size:w-margin],
    }
    
    all_corners = np.concatenate([c.flatten() for c in corners.values()])
    
    # Center ROI (central 25%)
    ch, cw = h // 4, w // 4
    center = lum[ch:3*ch, cw:3*cw]
    
    # Corner stats
    corner_med = float(np.median(all_corners))
    corner_p90 = float(np.percentile(all_corners, 90))
    corner_mad = float(np.median(np.abs(all_corners - corner_med)))
    corner_stddev = float(corner_mad * 1.4826)
    
    corner_meds = {k: float(np.median(c)) for k, c in corners.items()}
    
    # Center stats
    center_flat = center.flatten()
    center_med = float(np.median(center_flat))
    center_p90 = float(np.percentile(center_flat, 90))
    
    # Ratios
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
    
    # Per-channel RGB corner bias
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


def compute_percentiles(lum):
    """Compute extended percentile stats."""
    return {
        'p1': round(float(np.percentile(lum, 1)), 6),
        'p10': round(float(np.percentile(lum, 10)), 6),
        'p50': round(float(np.median(lum)), 6),
        'p90': round(float(np.percentile(lum, 90)), 6),
        'p99': round(float(np.percentile(lum, 99)), 6),
    }


def compute_time_context(dt):
    """
    Compute time-of-day context using astral for accurate sun calculations.
    
    Uses configured latitude/longitude from weather settings to calculate
    accurate sunrise, sunset, and twilight times.
    
    Args:
        dt: datetime object for the capture time
        
    Returns:
        dict with time context information
    """
    # Try to get location from config
    lat, lon, location_name = get_configured_location()
    
    # If astral available and location configured, use accurate calculations
    if ASTRAL_AVAILABLE and lat is not None and lon is not None:
        return compute_astral_time_context(dt, lat, lon, location_name)
    
    # Fallback to simple hour-based classification
    return compute_simple_time_context(dt)


def get_configured_location():
    """
    Get latitude/longitude from weather config.
    
    Falls back to default observatory location if not configured.
    
    Returns:
        tuple: (latitude, longitude, location_name)
    """
    # Default location: Rockwood, Texas observatory
    DEFAULT_LAT = 31.3303162
    DEFAULT_LON = -100.4570705
    DEFAULT_NAME = "Rockwood, Texas"
    
    if not CONFIG_AVAILABLE:
        return DEFAULT_LAT, DEFAULT_LON, DEFAULT_NAME
    
    try:
        config = Config()
        weather_config = config.get('weather', {})
        
        lat_str = weather_config.get('latitude', '')
        lon_str = weather_config.get('longitude', '')
        location_name = weather_config.get('location', DEFAULT_NAME)
        
        if lat_str and lon_str:
            return float(lat_str), float(lon_str), location_name
        
        # Fall back to default
        return DEFAULT_LAT, DEFAULT_LON, DEFAULT_NAME
    except Exception as e:
        return DEFAULT_LAT, DEFAULT_LON, DEFAULT_NAME


def compute_astral_time_context(now, lat, lon, location_name):
    """
    Compute accurate twilight times using astral package.
    
    Args:
        now: datetime for the capture time (naive local time)
        lat: Latitude in degrees
        lon: Longitude in degrees  
        location_name: Name of location
        
    Returns:
        dict with accurate sun position and twilight phase
    """
    try:
        # Create location
        loc = LocationInfo(
            name=location_name,
            region="",
            timezone="UTC",
            latitude=lat,
            longitude=lon
        )
        
        # Get sun times for that date (returns UTC)
        capture_date = now.date()
        s = sun(loc.observer, date=capture_date)
        
        # Convert now to UTC for comparison
        import time
        local_tz_offset = time.timezone if time.daylight == 0 else time.altzone
        now_utc = now + timedelta(seconds=local_tz_offset)
        
        # Extract times
        dawn = s.get('dawn')
        sunrise = s.get('sunrise')
        noon = s.get('noon')
        sunset = s.get('sunset')
        dusk = s.get('dusk')
        
        # Strip timezone for comparison
        def strip_tz(dt):
            return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt
        
        dawn_naive = strip_tz(dawn)
        sunrise_naive = strip_tz(sunrise)
        noon_naive = strip_tz(noon)
        sunset_naive = strip_tz(sunset)
        dusk_naive = strip_tz(dusk)
        
        sun_times_naive = {
            'dawn': dawn_naive,
            'sunrise': sunrise_naive,
            'noon': noon_naive,
            'sunset': sunset_naive,
            'dusk': dusk_naive,
        }
        
        # Classify time period
        period, detailed_period = classify_time_period(now_utc, sun_times_naive)
        
        # Check for astronomical night
        is_astro_night = False
        try:
            astro_twilight = twilight(loc.observer, date=capture_date, direction=1)
            astro_dusk = twilight(loc.observer, date=capture_date, direction=-1)
            
            if astro_twilight and astro_dusk:
                astro_dawn_start = strip_tz(astro_twilight[0])
                astro_dusk_end = strip_tz(astro_dusk[1])
                is_astro_night = now_utc < astro_dawn_start or now_utc > astro_dusk_end
        except Exception:
            if dawn_naive and dusk_naive:
                is_astro_night = now_utc < dawn_naive or now_utc > dusk_naive
        
        return {
            'hour': now.hour,
            'minute': now.minute,
            'period': period,
            'detailed_period': detailed_period,
            'is_daylight': period == 'day',
            'is_astronomical_night': is_astro_night,
            'location': {
                'name': location_name,
                'latitude': lat,
                'longitude': lon,
            },
            'sun_times': {
                'dawn': dawn.isoformat() if dawn else None,
                'sunrise': sunrise.isoformat() if sunrise else None,
                'noon': noon.isoformat() if noon else None,
                'sunset': sunset.isoformat() if sunset else None,
                'dusk': dusk.isoformat() if dusk else None,
            },
            'calculation_method': 'astral',
        }
        
    except Exception as e:
        print(f"  Warning: Astral calculation failed ({e}), using fallback")
        return compute_simple_time_context(now)


def classify_time_period(now, sun_times):
    """
    Classify time into period and detailed_period.
    
    Args:
        now: Current datetime (naive)
        sun_times: Dict with dawn/sunrise/noon/sunset/dusk
        
    Returns:
        tuple: (period, detailed_period)
    """
    dawn = sun_times.get('dawn')
    sunrise = sun_times.get('sunrise')
    noon = sun_times.get('noon')
    sunset = sun_times.get('sunset')
    dusk = sun_times.get('dusk')
    
    # Determine period
    if sunrise and sunset and sunrise <= now <= sunset:
        period = 'day'
    elif (dawn and sunrise and dawn <= now < sunrise) or \
         (sunset and dusk and sunset < now <= dusk):
        period = 'twilight'
    else:
        period = 'night'
    
    # Determine detailed period
    if dawn and now < dawn:
        detailed_period = 'night'
    elif dawn and sunrise and dawn <= now < sunrise:
        detailed_period = 'dawn'
    elif sunrise and noon and sunrise <= now < noon:
        detailed_period = 'morning'
    elif noon and sunset:
        afternoon_end = sunset.replace(
            hour=max(0, sunset.hour - 2),
            minute=sunset.minute
        )
        if noon <= now < afternoon_end:
            detailed_period = 'afternoon'
        elif afternoon_end <= now < sunset:
            detailed_period = 'evening'
        elif sunset <= now:
            if dusk and now <= dusk:
                detailed_period = 'dusk'
            else:
                detailed_period = 'night'
        else:
            detailed_period = 'afternoon'
    else:
        detailed_period = hour_to_detailed_period(now.hour)
    
    return period, detailed_period


def hour_to_detailed_period(hour):
    """Simple hour-based detailed period (fallback)."""
    if 5 <= hour < 8:
        return 'dawn'
    elif 8 <= hour < 12:
        return 'morning'
    elif 12 <= hour < 17:
        return 'afternoon'
    elif 17 <= hour < 20:
        return 'evening'
    elif 20 <= hour < 22:
        return 'dusk'
    else:
        return 'night'


def compute_simple_time_context(dt):
    """
    Fallback: Simple hour-based time classification.
    
    Used when astral is not available or location not configured.
    """
    hour = dt.hour
    
    if 6 <= hour < 18:
        period = 'day'
    elif 18 <= hour < 21 or 5 <= hour < 6:
        period = 'twilight'
    else:
        period = 'night'
    
    detailed_period = hour_to_detailed_period(hour)
    
    return {
        'hour': hour,
        'minute': dt.minute,
        'period': period,
        'detailed_period': detailed_period,
        'is_daylight': 6 <= hour < 20,
        'is_astronomical_night': hour >= 22 or hour < 5,
        'calculation_method': 'simple_hour_based',
    }


def load_fits_normalized(fits_path, denom=None):
    """
    Load FITS file and return normalized array.
    
    Args:
        fits_path: Path to FITS file
        denom: Normalization denominator (auto-detect if None)
    
    Returns:
        Normalized array (0-1 range)
    """
    with fits.open(fits_path) as hdul:
        data = hdul[0].data.astype(np.float32)
        
        # Handle RGB FITS (C, H, W) -> (H, W, C)
        if data.ndim == 3 and data.shape[0] == 3:
            data = np.transpose(data, (1, 2, 0))
        
        # Auto-detect denominator if not provided
        if denom is None:
            raw_max = np.max(data)
            if raw_max <= 1.0:
                # Already normalized (luminance file)
                return data
            elif raw_max <= 255:
                denom = 255.0
            elif raw_max <= 4095:
                denom = 4095.0
            else:
                denom = 65535.0
        
        return data / denom


def compute_luminance(rgb_array):
    """Compute luminance from RGB array."""
    if rgb_array.ndim == 2:
        return rgb_array
    elif rgb_array.ndim == 3 and rgb_array.shape[2] == 3:
        return 0.299 * rgb_array[:,:,0] + 0.587 * rgb_array[:,:,1] + 0.114 * rgb_array[:,:,2]
    else:
        return rgb_array.mean(axis=-1) if rgb_array.ndim > 2 else rgb_array


def backfill_calibration(json_path, dry_run=False, force_time=False):
    """
    Backfill missing fields in a calibration JSON file.
    
    Args:
        json_path: Path to calibration JSON file
        dry_run: If True, don't modify files
        force_time: If True, recalculate time_context even if exists
    
    Returns:
        tuple: (success: bool, message: str, fields_added: list)
    """
    json_path = Path(json_path)
    
    # Load existing calibration
    try:
        with open(json_path, 'r') as f:
            cal = json.load(f)
    except Exception as e:
        return False, f"Failed to load JSON: {e}", []
    
    # Check what's missing (or needs updating)
    fields_to_add = []
    if 'corner_analysis' not in cal:
        fields_to_add.append('corner_analysis')
    if 'percentiles' not in cal:
        fields_to_add.append('percentiles')
    if 'time_context' not in cal:
        fields_to_add.append('time_context')
    elif force_time:
        # Check if current time_context uses old simple method
        tc = cal.get('time_context', {})
        if tc.get('calculation_method') != 'astral':
            fields_to_add.append('time_context')
    
    if not fields_to_add:
        return True, "Already complete", []
    
    # Extract timestamp from filename
    dt = parse_timestamp_from_filename(json_path.name)
    if not dt:
        return False, "Could not parse timestamp from filename", []
    
    timestamp_str = dt.strftime("%Y%m%d_%H%M%S")
    
    # Find matching FITS files
    parent_dir = json_path.parent
    lum_path = parent_dir / f"lum_{timestamp_str}.fits"
    raw_path = parent_dir / f"raw_{timestamp_str}.fits"
    
    # Determine if we need FITS files (only for corner_analysis or percentiles)
    needs_fits = 'corner_analysis' in fields_to_add or 'percentiles' in fields_to_add
    
    # Find matching FITS files if needed
    have_lum = lum_path.exists()
    have_raw = raw_path.exists()
    
    if needs_fits and not have_lum and not have_raw:
        return False, f"No matching FITS files found (looked for lum_{timestamp_str}.fits, raw_{timestamp_str}.fits)", []
    
    # Get normalization denominator from existing calibration
    denom = cal.get('normalization', {}).get('denom', 65535)
    
    # Load data only if needed
    lum = None
    norm_rgb = None
    
    if needs_fits:
        if have_lum:
            try:
                lum = load_fits_normalized(lum_path)
                if lum.ndim == 3:
                    lum = compute_luminance(lum)
            except Exception as e:
                return False, f"Failed to load lum FITS: {e}", []
        
        if have_raw:
            try:
                norm_rgb = load_fits_normalized(raw_path, denom)
                if lum is None:
                    lum = compute_luminance(norm_rgb)
            except Exception as e:
                if lum is None:
                    return False, f"Failed to load raw FITS: {e}", []
                # Can continue without raw if we have lum
                norm_rgb = None
    
    # Compute missing fields
    if 'corner_analysis' in fields_to_add:
        cal['corner_analysis'] = compute_corner_analysis(lum, norm_rgb)
    
    if 'percentiles' in fields_to_add:
        cal['percentiles'] = compute_percentiles(lum)
    
    if 'time_context' in fields_to_add:
        cal['time_context'] = compute_time_context(dt)
    
    # Save updated calibration
    if not dry_run:
        try:
            with open(json_path, 'w') as f:
                json.dump(cal, f, indent=2)
        except Exception as e:
            return False, f"Failed to save JSON: {e}", fields_to_add
    
    return True, "Updated", fields_to_add


def find_calibration_files(directory, recursive=True):
    """Find all calibration_*.json files in directory."""
    directory = Path(directory)
    pattern = "calibration_*.json"
    
    if recursive:
        return list(directory.rglob(pattern))
    else:
        return list(directory.glob(pattern))


def main():
    parser = argparse.ArgumentParser(
        description="Backfill missing fields in calibration JSON files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python backfill_calibration.py "H:\\raw_debug" --dry-run
    python backfill_calibration.py "H:\\raw_debug\\Roof Closed Day Time"
    python backfill_calibration.py "H:\\raw_debug" --no-recursive
    python backfill_calibration.py "H:\\raw_debug" --force-time
        """
    )
    parser.add_argument('directory', help='Directory containing calibration files')
    parser.add_argument('--dry-run', action='store_true', 
                        help='Show what would be done without making changes')
    parser.add_argument('--no-recursive', action='store_true',
                        help='Do not search subdirectories')
    parser.add_argument('--force-time', action='store_true',
                        help='Force recalculation of time_context using astral (even if exists)')
    
    args = parser.parse_args()
    
    directory = Path(args.directory)
    if not directory.exists():
        print(f"ERROR: Directory not found: {directory}")
        sys.exit(1)
    
    # Check astral availability when --force-time is used
    if args.force_time:
        if ASTRAL_AVAILABLE and CONFIG_AVAILABLE:
            lat, lon, loc_name = get_configured_location()
            if lat is not None:
                print(f"Using astral calculations for location: {loc_name} ({lat}, {lon})")
            else:
                print("WARNING: Location not configured in config.json weather settings")
                print("         Will use simple hour-based classification")
        elif not ASTRAL_AVAILABLE:
            print("WARNING: astral not installed, --force-time will use simple classification")
    
    # Find all calibration files
    print(f"Searching for calibration files in: {directory}")
    cal_files = find_calibration_files(directory, recursive=not args.no_recursive)
    
    if not cal_files:
        print("No calibration_*.json files found")
        sys.exit(0)
    
    print(f"Found {len(cal_files)} calibration file(s)")
    if args.dry_run:
        print("=== DRY RUN - No changes will be made ===\n")
    
    # Process each file
    stats = {'success': 0, 'skipped': 0, 'failed': 0, 'complete': 0}
    
    for cal_path in sorted(cal_files):
        rel_path = cal_path.relative_to(directory) if cal_path.is_relative_to(directory) else cal_path
        
        success, message, fields_added = backfill_calibration(
            cal_path, 
            dry_run=args.dry_run,
            force_time=args.force_time
        )
        
        if success:
            if fields_added:
                action = "Would update" if args.dry_run else "Updated"
                print(f"+ {rel_path}: {action} {', '.join(fields_added)}")
                stats['success'] += 1
            else:
                print(f"  {rel_path}: {message}")
                stats['complete'] += 1
        else:
            print(f"X {rel_path}: {message}")
            stats['failed'] += 1
    
    # Summary
    print(f"\n{'='*50}")
    print(f"Summary:")
    print(f"  Already complete: {stats['complete']}")
    print(f"  {'Would update' if args.dry_run else 'Updated'}: {stats['success']}")
    print(f"  Failed: {stats['failed']}")
    
    if args.dry_run and stats['success'] > 0:
        print(f"\nRun without --dry-run to apply changes")


if __name__ == '__main__':
    main()
