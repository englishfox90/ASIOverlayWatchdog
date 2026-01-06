#!/usr/bin/env python3
"""
Collect and add labels to calibration files for ML training.

The calibration files now auto-populate most fields. This script handles:
1. Adding normalized/derived features for camera-agnostic ML
2. Interactive labeling for manual fields (scene, recipe_used, stacking)
3. Batch processing of calibration directories

Usage:
    # Add normalized features to all files
    python collect_labels.py "H:\\raw_debug" --add-features
    
    # Interactive labeling for manual fields
    python collect_labels.py "H:\\raw_debug" --interactive
    
    # Process single file
    python collect_labels.py calibration_file.json --interactive
    
    # Show summary of existing labels
    python collect_labels.py "H:\\raw_debug" --summary
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Dict, Any

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def load_calibration(path: Path) -> dict:
    """Load calibration JSON file."""
    with open(path, 'r') as f:
        return json.load(f)


def save_calibration(data: dict, path: Path) -> None:
    """Save calibration JSON file."""
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"  ✓ Saved: {path.name}")


def add_normalized_features(cal: dict) -> dict:
    """
    Add normalized/derived features for camera-agnostic ML training.
    
    These features use ratios and percentages that transfer well
    across different cameras with different bit depths and sensitivities.
    """
    p = cal.get('percentiles', {})
    c = cal.get('corner_analysis', {})
    
    # Avoid division by zero
    p50 = p.get('p50', 0.001) or 0.001
    p10 = p.get('p10', 0.001) or 0.001
    corner_med = c.get('corner_med', 0.001) or 0.001
    
    cal['normalized_features'] = {
        # Percentile ratios (how spread out is the histogram?)
        'p99_p50_ratio': round(p.get('p99', 0) / p50, 4),
        'p90_p10_ratio': round(p.get('p90', 0) / p10, 4),
        'dynamic_range_norm': round((p.get('p99', 0) - p.get('p1', 0)) / p50, 4),
        
        # Spatial ratios (corner vs center brightness)
        'center_minus_corner_norm': round(c.get('center_minus_corner', 0) / p50, 4),
        'corner_stddev_norm': round(c.get('corner_stddev', 0) / corner_med, 4),
        
        # RGB imbalance (how unbalanced are the color channels?)
        'rgb_imbalance': calculate_rgb_imbalance(c.get('rgb_corner_bias', {})),
    }
    
    return cal


def calculate_rgb_imbalance(rgb_bias: dict) -> float:
    """
    Calculate RGB imbalance as max/min ratio of corner biases.
    
    A value of 1.0 means perfectly balanced RGB.
    Higher values indicate color cast (e.g., blue excess).
    """
    r = rgb_bias.get('bias_r', 0)
    g = rgb_bias.get('bias_g', 0)
    b = rgb_bias.get('bias_b', 0)
    
    if not all([r, g, b]) or min(r, g, b) <= 0:
        return 1.0
    
    values = [r, g, b]
    return round(max(values) / min(values), 4)


def classify_mode(cal: dict) -> str:
    """
    Classify image mode from calibration data.
    
    Returns one of:
    - day_roof_open, day_roof_closed
    - night_roof_open, night_roof_closed  
    - twilight
    - unknown
    """
    tc = cal.get('time_context', {})
    rs = cal.get('roof_state', {})
    ca = cal.get('corner_analysis', {})
    
    # Determine day/night
    if tc.get('is_daylight'):
        time_period = 'day'
    elif tc.get('is_astronomical_night'):
        time_period = 'night'
    elif tc.get('period') == 'twilight':
        return 'twilight'
    else:
        hour = tc.get('hour', 12)
        time_period = 'night' if (hour >= 20 or hour < 6) else 'day'
    
    # Determine roof state
    if rs.get('available') and rs.get('source') == 'nina_api':
        roof_open = rs.get('roof_open', False)
    else:
        # Infer from corner ratio (ratio ~1.0 = uniform = closed)
        ratio = ca.get('corner_to_center_ratio', 0.95)
        roof_open = ratio < 0.95
    
    roof_str = 'roof_open' if roof_open else 'roof_closed'
    return f"{time_period}_{roof_str}"


def show_context(cal: dict) -> None:
    """Display calibration context for labeling."""
    print("\n" + "="*70)
    print(f"Timestamp: {cal.get('timestamp', 'unknown')}")
    print("="*70)
    
    # Basic info
    print(f"\nCamera: {cal.get('camera', '?')}")
    print(f"Exposure: {cal.get('exposure', '?')}, Gain: {cal.get('gain', '?')}")
    
    # Time context
    tc = cal.get('time_context', {})
    print(f"\nTime: {tc.get('hour', '?')}:{tc.get('minute', 0):02d}")
    print(f"  Period: {tc.get('period', '?')} ({tc.get('detailed_period', '?')})")
    print(f"  Daylight: {tc.get('is_daylight', '?')}")
    print(f"  Astronomical night: {tc.get('is_astronomical_night', '?')}")
    
    # Moon
    mc = cal.get('moon_context', {})
    if mc.get('available'):
        print(f"\nMoon: {mc.get('phase_name', '?')} ({mc.get('illumination_pct', 0):.0f}%)")
        print(f"  Moon is up: {mc.get('moon_is_up', '?')}")
        print(f"  Bright moon: {mc.get('is_bright_moon', '?')}")
    
    # Roof
    rs = cal.get('roof_state', {})
    if rs.get('available'):
        print(f"\nRoof: {'OPEN' if rs.get('roof_open') else 'CLOSED'} (from {rs.get('source', '?')})")
    
    # Weather
    wc = cal.get('weather_context', {})
    if wc.get('available'):
        print(f"\nWeather: {wc.get('condition', '?')} - {wc.get('description', '?')}")
        print(f"  Clouds: {wc.get('cloud_coverage_pct', '?')}%")
        print(f"  Humidity: {wc.get('humidity_pct', '?')}%")
        print(f"  Clear: {wc.get('is_clear', '?')}")
    
    # Seeing
    se = cal.get('seeing_estimate', {})
    if se.get('available'):
        print(f"\nSeeing: {se.get('quality', '?')} (score: {se.get('overall_score', 0):.2f})")
        print(f"  Dew risk: {se.get('dew_risk', '?')}")
    
    # Image stats
    st = cal.get('stretch', {})
    print(f"\nImage Stats:")
    print(f"  Median luminance: {st.get('median_lum', 0):.4f}")
    print(f"  Dynamic range: {st.get('dynamic_range', 0):.4f}")
    print(f"  Dark scene: {st.get('is_dark_scene', '?')}")
    print(f"  Recommended asinh: {st.get('recommended_asinh_strength', 0):.0f}")
    
    # Corner analysis
    ca = cal.get('corner_analysis', {})
    print(f"\nCorner Analysis:")
    print(f"  Corner/center ratio: {ca.get('corner_to_center_ratio', 0):.4f}")
    
    # Classified mode
    mode = classify_mode(cal)
    print(f"\n>>> Classified Mode: {mode}")


def interactive_label(cal: dict, image_path: Optional[Path] = None) -> dict:
    """
    Interactive labeling session for manual fields.
    """
    show_context(cal)
    
    if image_path and image_path.exists():
        print(f"\n  Image file: {image_path}")
        print("  (Open in viewer to see actual scene)")
    
    # Initialize scene dict if needed
    if 'scene' not in cal:
        cal['scene'] = {}
    
    print("\n" + "-"*50)
    print("MANUAL LABELS (Enter to skip, 'q' to quit)")
    print("-"*50)
    
    # Binary questions
    cal['scene']['stars_visible'] = ask_bool(
        "Stars visible in processed output?", 
        cal['scene'].get('stars_visible')
    )
    
    cal['scene']['moon_in_frame'] = ask_bool(
        "Moon visible IN the frame?", 
        cal['scene'].get('moon_in_frame')
    )
    
    cal['scene']['clouds_visible'] = ask_bool(
        "Clouds visible?", 
        cal['scene'].get('clouds_visible')
    )
    
    cal['scene']['imaging_train_visible'] = ask_bool(
        "Telescope/imaging train visible?", 
        cal['scene'].get('imaging_train_visible')
    )
    
    # Continuous values (0-1)
    if cal['scene'].get('stars_visible'):
        cal['scene']['star_density'] = ask_float(
            "Star density (0=few, 0.5=moderate, 1=milky way)?", 
            cal['scene'].get('star_density'), 0, 1
        )
    
    if cal['scene'].get('clouds_visible'):
        cal['scene']['cloud_coverage_visual'] = ask_float(
            "Visual cloud coverage (0=trace, 0.5=half, 1=overcast)?",
            cal['scene'].get('cloud_coverage_visual'), 0, 1
        )
    
    if cal['scene'].get('moon_in_frame'):
        cal['scene']['moon_brightness_visual'] = ask_float(
            "Moon brightness (0=crescent, 0.5=half, 1=full)?",
            cal['scene'].get('moon_brightness_visual'), 0, 1
        )
    
    # Quality rating
    cal['scene']['output_quality_rating'] = ask_int(
        "Output quality rating (1=poor, 3=ok, 5=excellent)?",
        cal['scene'].get('output_quality_rating'), 1, 5
    )
    
    return cal


def label_recipe(cal: dict) -> dict:
    """
    Label the recipe that produced good results.
    
    This is for supervised learning of recipe parameters.
    """
    print("\n" + "-"*50)
    print("RECIPE USED (what parameters worked well?)")
    print("-"*50)
    
    if 'recipe_used' not in cal:
        cal['recipe_used'] = {}
    
    # Recipe name/category
    cal['recipe_used']['recipe_name'] = ask_string(
        "Recipe name (e.g., night_stars, day_clear)?",
        cal['recipe_used'].get('recipe_name')
    )
    
    # Key parameters
    cal['recipe_used']['asinh'] = ask_float(
        "asinh strength used?",
        cal['recipe_used'].get('asinh'), 0, 1000
    )
    
    cal['recipe_used']['gamma'] = ask_float(
        "gamma used?",
        cal['recipe_used'].get('gamma'), 0.1, 3.0
    )
    
    cal['recipe_used']['shadow_denoise'] = ask_float(
        "shadow_denoise (0-1)?",
        cal['recipe_used'].get('shadow_denoise'), 0, 1
    )
    
    cal['recipe_used']['chroma_blur'] = ask_int(
        "chroma_blur kernel size?",
        cal['recipe_used'].get('chroma_blur'), 0, 15
    )
    
    cal['recipe_used']['blue_suppress'] = ask_float(
        "blue_suppress (0-1)?",
        cal['recipe_used'].get('blue_suppress'), 0, 1
    )
    
    return cal


def ask_bool(prompt: str, current: Optional[bool] = None) -> Optional[bool]:
    """Ask a yes/no question."""
    current_str = f" [{current}]" if current is not None else ""
    response = input(f"  {prompt}{current_str} (y/n): ").strip().lower()
    
    if response == 'q':
        raise KeyboardInterrupt
    if response == '':
        return current
    if response in ('y', 'yes', '1', 'true'):
        return True
    if response in ('n', 'no', '0', 'false'):
        return False
    return current


def ask_float(prompt: str, current: Optional[float], min_val: float, max_val: float) -> Optional[float]:
    """Ask for a float value within range."""
    current_str = f" [{current:.2f}]" if current is not None else ""
    response = input(f"  {prompt}{current_str}: ").strip()
    
    if response == 'q':
        raise KeyboardInterrupt
    if response == '':
        return current
    
    try:
        value = float(response)
        return max(min_val, min(max_val, value))
    except ValueError:
        return current


def ask_int(prompt: str, current: Optional[int], min_val: int, max_val: int) -> Optional[int]:
    """Ask for an integer value within range."""
    current_str = f" [{current}]" if current is not None else ""
    response = input(f"  {prompt}{current_str}: ").strip()
    
    if response == 'q':
        raise KeyboardInterrupt
    if response == '':
        return current
    
    try:
        value = int(response)
        return max(min_val, min(max_val, value))
    except ValueError:
        return current


def ask_string(prompt: str, current: Optional[str] = None) -> Optional[str]:
    """Ask for a string value."""
    current_str = f" [{current}]" if current else ""
    response = input(f"  {prompt}{current_str}: ").strip()
    
    if response == 'q':
        raise KeyboardInterrupt
    if response == '':
        return current
    return response


def show_summary(directory: Path) -> None:
    """Show summary of labels in calibration files."""
    cal_files = sorted(directory.glob("calibration_*.json"))
    
    if not cal_files:
        print(f"No calibration files found in {directory}")
        return
    
    print(f"\nFound {len(cal_files)} calibration files\n")
    
    # Count modes and labels
    mode_counts: Dict[str, int] = {}
    labeled_count = 0
    has_recipe_count = 0
    
    for cal_path in cal_files:
        cal = load_calibration(cal_path)
        
        # Classify mode
        mode = classify_mode(cal)
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
        
        # Check for labels
        scene = cal.get('scene', {})
        if scene.get('output_quality_rating') is not None:
            labeled_count += 1
        
        if cal.get('recipe_used', {}).get('recipe_name'):
            has_recipe_count += 1
    
    print("Mode Distribution:")
    print("-"*40)
    for mode, count in sorted(mode_counts.items()):
        pct = count / len(cal_files) * 100
        bar = "█" * int(pct / 5)
        print(f"  {mode:20s} {count:3d} ({pct:5.1f}%) {bar}")
    
    print(f"\nLabeling Progress:")
    print("-"*40)
    print(f"  Quality rated: {labeled_count}/{len(cal_files)} ({labeled_count/len(cal_files)*100:.0f}%)")
    print(f"  Recipe labeled: {has_recipe_count}/{len(cal_files)} ({has_recipe_count/len(cal_files)*100:.0f}%)")
    
    # Recommendations
    print(f"\nRecommendations:")
    print("-"*40)
    min_per_mode = 20
    for mode, count in mode_counts.items():
        if count < min_per_mode:
            print(f"  ⚠ Need {min_per_mode - count} more '{mode}' samples")


def process_directory(directory: Path, args) -> None:
    """Process all calibration files in directory."""
    cal_files = sorted(directory.glob("calibration_*.json"))
    
    if not cal_files:
        print(f"No calibration files found in {directory}")
        return
    
    print(f"Found {len(cal_files)} calibration files")
    
    for i, cal_path in enumerate(cal_files, 1):
        print(f"\n[{i}/{len(cal_files)}] {cal_path.name}")
        
        cal = load_calibration(cal_path)
        modified = False
        
        # Add normalized features if requested or missing
        if args.add_features or 'normalized_features' not in cal:
            cal = add_normalized_features(cal)
            modified = True
            print("  + Added normalized features")
        
        # Interactive labeling
        if args.interactive:
            # Find corresponding image for reference
            timestamp = cal_path.stem.replace("calibration_", "")
            image_path = cal_path.parent / f"lum_{timestamp}.fits"
            if not image_path.exists():
                # Try raw
                image_path = cal_path.parent / f"raw_{timestamp}.fits"
            if not image_path.exists():
                image_path = None
            
            try:
                cal = interactive_label(cal, image_path)
                modified = True
                
                # Ask about recipe if quality rated
                if cal.get('scene', {}).get('output_quality_rating'):
                    add_recipe = input("\n  Add recipe parameters? (y/n): ").strip().lower()
                    if add_recipe in ('y', 'yes'):
                        cal = label_recipe(cal)
                
            except KeyboardInterrupt:
                print("\n\nLabeling interrupted, saving progress...")
                if modified:
                    save_calibration(cal, cal_path)
                break
        
        if modified:
            save_calibration(cal, cal_path)


def main():
    ap = argparse.ArgumentParser(
        description="Add labels to calibration files for ML training",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "H:\\raw_debug" --summary          # Show label statistics
  %(prog)s "H:\\raw_debug" --add-features     # Add normalized features
  %(prog)s "H:\\raw_debug" --interactive      # Interactive labeling
  %(prog)s calibration.json --interactive     # Label single file
        """
    )
    
    ap.add_argument("path", help="Directory with calibration files or single file")
    ap.add_argument("--add-features", action="store_true", 
                    help="Add normalized features for ML training")
    ap.add_argument("--interactive", "-i", action="store_true",
                    help="Interactive labeling for manual fields")
    ap.add_argument("--summary", "-s", action="store_true",
                    help="Show summary of existing labels")
    
    args = ap.parse_args()
    
    path = Path(args.path)
    
    if args.summary:
        if path.is_dir():
            show_summary(path)
        else:
            print("--summary requires a directory path")
            sys.exit(1)
        return
    
    if path.is_file():
        # Single file
        cal = load_calibration(path)
        
        cal = add_normalized_features(cal)
        
        if args.interactive:
            try:
                cal = interactive_label(cal)
                add_recipe = input("\n  Add recipe parameters? (y/n): ").strip().lower()
                if add_recipe in ('y', 'yes'):
                    cal = label_recipe(cal)
            except KeyboardInterrupt:
                print("\n\nLabeling interrupted, saving...")
        
        save_calibration(cal, path)
        
    elif path.is_dir():
        process_directory(path, args)
    else:
        print(f"ERROR: Path not found: {path}")
        sys.exit(1)


if __name__ == "__main__":
    main()
