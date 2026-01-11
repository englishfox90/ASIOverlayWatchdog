#!/usr/bin/env python3
"""
Label Distribution Report for PFR Sentinel ML Data

Analyzes labeled calibration data and reports on sample distribution,
missing categories, and suggested targets for balanced training.

Usage:
    python ml/label_report.py "E:\Pier Camera ML Data"
    python ml/label_report.py  # Uses default path
"""
import sys
import json
import argparse
from pathlib import Path
from collections import defaultdict


# Target samples per category for a well-balanced model
TARGETS = {
    'roof_state': {
        'open': 200,
        'closed': 200,
    },
    'sky_condition': {
        'Clear': 100,
        'Mostly Clear': 75,
        'Partly Cloudy': 75,
        'Mostly Cloudy': 50,
        'Overcast': 50,
        'Fog/Haze': 25,
    },
    'time_period': {
        'day_open': 50,
        'day_closed': 50,
        'night_open': 150,
        'night_closed': 100,
        'twilight': 50,
    },
    'celestial': {
        'stars_visible': 150,
        'moon_visible': 75,
        'stars_high_density': 50,  # star_density > 0.7
    }
}


def load_calibration_files(data_dir: Path) -> list:
    """Load all calibration JSON files."""
    samples = []
    for cal_file in data_dir.rglob("calibration_*.json"):
        try:
            with open(cal_file, 'r') as f:
                data = json.load(f)
            data['_file'] = cal_file
            data['_folder'] = cal_file.parent.name
            samples.append(data)
        except Exception as e:
            print(f"Warning: Failed to load {cal_file}: {e}")
    return samples


def analyze_samples(samples: list) -> dict:
    """Analyze sample distribution."""
    stats = {
        'total': len(samples),
        'labeled': 0,
        'unlabeled': 0,
        'roof': {'open': 0, 'closed': 0, 'unknown': 0},
        'sky_condition': defaultdict(int),
        'time_period': defaultdict(int),
        'stars_visible': 0,
        'stars_not_visible': 0,
        'star_density_bins': {'none': 0, 'low': 0, 'medium': 0, 'high': 0},
        'moon_visible': 0,
        'moon_not_visible': 0,
        'clouds_visible': 0,
        'clouds_not_visible': 0,
        'combinations': defaultdict(int),
        'by_folder': defaultdict(lambda: {'total': 0, 'labeled': 0}),
    }
    
    for sample in samples:
        folder = sample.get('_folder', 'unknown')
        stats['by_folder'][folder]['total'] += 1
        
        labels = sample.get('labels', {})
        has_labels = bool(labels.get('labeled_at'))
        
        if has_labels:
            stats['labeled'] += 1
            stats['by_folder'][folder]['labeled'] += 1
            
            # Roof state
            if labels.get('roof_open'):
                stats['roof']['open'] += 1
            else:
                stats['roof']['closed'] += 1
            
            # Sky condition
            sky = labels.get('sky_condition', 'Not set')
            stats['sky_condition'][sky] += 1
            
            # Stars
            if labels.get('stars_visible'):
                stats['stars_visible'] += 1
                density = labels.get('star_density', 0)
                if density == 0:
                    stats['star_density_bins']['none'] += 1
                elif density < 0.3:
                    stats['star_density_bins']['low'] += 1
                elif density < 0.7:
                    stats['star_density_bins']['medium'] += 1
                else:
                    stats['star_density_bins']['high'] += 1
            else:
                stats['stars_not_visible'] += 1
            
            # Moon
            if labels.get('moon_visible'):
                stats['moon_visible'] += 1
            else:
                stats['moon_not_visible'] += 1
            
            # Clouds
            if labels.get('clouds_visible'):
                stats['clouds_visible'] += 1
            else:
                stats['clouds_not_visible'] += 1
            
            # Time period combinations
            tc = sample.get('time_context', {})
            if tc.get('is_daylight'):
                period = 'day'
            elif tc.get('is_astronomical_night'):
                period = 'night'
            else:
                period = 'twilight'
            
            roof_str = 'open' if labels.get('roof_open') else 'closed'
            combo = f"{period}_{roof_str}"
            stats['time_period'][combo] += 1
            
            # Full combination key for rare scenario detection
            combo_key = f"roof={roof_str}, sky={sky}, stars={labels.get('stars_visible')}, moon={labels.get('moon_visible')}"
            stats['combinations'][combo_key] += 1
        else:
            stats['unlabeled'] += 1
    
    return stats


def print_bar(count: int, target: int, width: int = 30) -> str:
    """Create a progress bar."""
    if target == 0:
        pct = 100
    else:
        pct = min(100, (count / target) * 100)
    filled = int(width * pct / 100)
    bar = '█' * filled + '░' * (width - filled)
    status = '✓' if count >= target else ' '
    return f"{bar} {count:4d}/{target:4d} ({pct:5.1f}%) {status}"


def print_report(stats: dict):
    """Print the analysis report."""
    print("\n" + "=" * 70)
    print("  PFR SENTINEL ML DATA - LABELING REPORT")
    print("=" * 70)
    
    # Overall progress
    print("\n📊 OVERALL PROGRESS")
    print("-" * 40)
    labeled_pct = (stats['labeled'] / stats['total'] * 100) if stats['total'] > 0 else 0
    print(f"  Total samples:    {stats['total']}")
    print(f"  Labeled:          {stats['labeled']} ({labeled_pct:.1f}%)")
    print(f"  Unlabeled:        {stats['unlabeled']}")
    
    # By folder
    print("\n📁 BY FOLDER")
    print("-" * 40)
    for folder, counts in sorted(stats['by_folder'].items()):
        pct = (counts['labeled'] / counts['total'] * 100) if counts['total'] > 0 else 0
        status = '✓' if pct == 100 else ' '
        print(f"  {folder:20s} {counts['labeled']:4d}/{counts['total']:4d} ({pct:5.1f}%) {status}")
    
    # Roof state
    print("\n🏠 ROOF STATE")
    print("-" * 40)
    print(f"  Open:   {print_bar(stats['roof']['open'], TARGETS['roof_state']['open'])}")
    print(f"  Closed: {print_bar(stats['roof']['closed'], TARGETS['roof_state']['closed'])}")
    
    # Time period combinations
    print("\n⏰ TIME PERIOD + ROOF")
    print("-" * 40)
    for combo, target in TARGETS['time_period'].items():
        count = stats['time_period'].get(combo, 0)
        print(f"  {combo:15s} {print_bar(count, target)}")
    
    # Sky conditions
    print("\n🌤️  SKY CONDITIONS (when roof open)")
    print("-" * 40)
    for condition, target in TARGETS['sky_condition'].items():
        count = stats['sky_condition'].get(condition, 0)
        print(f"  {condition:15s} {print_bar(count, target)}")
    not_set = stats['sky_condition'].get('Not set', 0)
    if not_set > 0:
        print(f"  {'Not set':15s} {not_set:4d} (needs labeling)")
    
    # Celestial objects
    print("\n✨ CELESTIAL OBJECTS")
    print("-" * 40)
    print(f"  Stars visible:  {print_bar(stats['stars_visible'], TARGETS['celestial']['stars_visible'])}")
    high_density = stats['star_density_bins']['high']
    print(f"  High density:   {print_bar(high_density, TARGETS['celestial']['stars_high_density'])}")
    print(f"  Moon visible:   {print_bar(stats['moon_visible'], TARGETS['celestial']['moon_visible'])}")
    
    # Star density distribution
    print("\n  Star density breakdown:")
    for bin_name, count in stats['star_density_bins'].items():
        print(f"    {bin_name:10s} {count:4d}")
    
    # Clouds
    print("\n☁️  CLOUDS")
    print("-" * 40)
    print(f"  Clouds visible:     {stats['clouds_visible']}")
    print(f"  No clouds visible:  {stats['clouds_not_visible']}")
    
    # Recommendations
    print("\n" + "=" * 70)
    print("  RECOMMENDATIONS")
    print("=" * 70)
    
    needs = []
    
    # Check roof balance
    if stats['roof']['open'] < TARGETS['roof_state']['open']:
        needs.append(f"  • Need {TARGETS['roof_state']['open'] - stats['roof']['open']} more ROOF OPEN samples")
    if stats['roof']['closed'] < TARGETS['roof_state']['closed']:
        needs.append(f"  • Need {TARGETS['roof_state']['closed'] - stats['roof']['closed']} more ROOF CLOSED samples")
    
    # Check time periods
    for combo, target in TARGETS['time_period'].items():
        count = stats['time_period'].get(combo, 0)
        if count < target:
            needs.append(f"  • Need {target - count} more {combo.upper()} samples")
    
    # Check sky conditions
    for condition, target in TARGETS['sky_condition'].items():
        count = stats['sky_condition'].get(condition, 0)
        if count < target * 0.5:  # Less than 50% of target
            needs.append(f"  • Need more '{condition}' weather samples ({count}/{target})")
    
    # Check celestial
    if stats['moon_visible'] < TARGETS['celestial']['moon_visible']:
        needs.append(f"  • Need {TARGETS['celestial']['moon_visible'] - stats['moon_visible']} more samples with MOON visible")
    
    high_density = stats['star_density_bins']['high']
    if high_density < TARGETS['celestial']['stars_high_density']:
        needs.append(f"  • Need {TARGETS['celestial']['stars_high_density'] - high_density} more HIGH STAR DENSITY samples (Milky Way nights)")
    
    if needs:
        print("\n🎯 PRIORITY COLLECTION TARGETS:\n")
        for need in needs:
            print(need)
    else:
        print("\n✅ All targets met! Dataset is well-balanced.")
    
    # Rare combinations
    print("\n📋 SAMPLE COMBINATIONS (top 10):")
    print("-" * 40)
    sorted_combos = sorted(stats['combinations'].items(), key=lambda x: -x[1])[:10]
    for combo, count in sorted_combos:
        print(f"  {count:4d}x  {combo}")
    
    print("\n" + "=" * 70)
    print()


def main():
    parser = argparse.ArgumentParser(description="Label distribution report for ML data")
    parser.add_argument("data_dir", nargs="?", default=r"E:\Pier Camera ML Data",
                        help="Directory containing calibration files")
    args = parser.parse_args()
    
    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Error: Directory not found: {data_dir}")
        sys.exit(1)
    
    print(f"Loading calibration files from: {data_dir}")
    samples = load_calibration_files(data_dir)
    
    if not samples:
        print("No calibration files found!")
        sys.exit(1)
    
    print(f"Found {len(samples)} calibration files")
    
    stats = analyze_samples(samples)
    print_report(stats)


if __name__ == "__main__":
    main()
