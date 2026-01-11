#!/usr/bin/env python3
"""
Analyze Calibration Data Across All Scenes

Summarizes corner_analysis and time_context from all calibration files
to help determine classification thresholds.

Usage:
    python analyze_calibration_data.py <directory>
"""
import argparse
import json
import sys
from pathlib import Path
from collections import defaultdict


def load_calibration_files(directory):
    """Load all calibration JSON files."""
    directory = Path(directory)
    cal_files = list(directory.rglob("calibration_*.json"))
    
    data = []
    for path in cal_files:
        try:
            cal = json.loads(path.read_text())
            cal['_path'] = str(path)
            cal['_folder'] = path.parent.name
            data.append(cal)
        except Exception as e:
            print(f"Warning: Failed to load {path}: {e}")
    
    return data


def analyze_data(calibrations):
    """Analyze and summarize calibration data."""
    
    # Group by folder (assumed scene type)
    by_folder = defaultdict(list)
    for cal in calibrations:
        by_folder[cal['_folder']].append(cal)
    
    print(f"\n{'='*70}")
    print(f"CALIBRATION DATA ANALYSIS")
    print(f"{'='*70}")
    print(f"Total files: {len(calibrations)}")
    print(f"Folders: {list(by_folder.keys())}")
    
    # Analyze each folder
    for folder, cals in sorted(by_folder.items()):
        print(f"\n{'─'*70}")
        print(f"📁 {folder} ({len(cals)} files)")
        print(f"{'─'*70}")
        
        # Extract metrics
        ratios = []
        deltas = []
        hours = []
        p50s = []
        p99s = []
        
        for cal in cals:
            ca = cal.get('corner_analysis', {})
            tc = cal.get('time_context', {})
            perc = cal.get('percentiles', {})
            
            if ca:
                ratios.append(ca.get('corner_to_center_ratio', 0))
                deltas.append(ca.get('center_minus_corner', 0))
            if tc:
                hours.append(tc.get('hour', -1))
            if perc:
                p50s.append(perc.get('p50', 0))
                p99s.append(perc.get('p99', 0))
        
        if ratios:
            print(f"\n  Corner-to-Center Ratio:")
            print(f"    min: {min(ratios):.4f}  max: {max(ratios):.4f}  avg: {sum(ratios)/len(ratios):.4f}")
            
        if deltas:
            print(f"\n  Center-Minus-Corner Delta:")
            print(f"    min: {min(deltas):.4f}  max: {max(deltas):.4f}  avg: {sum(deltas)/len(deltas):.4f}")
        
        if hours and hours[0] >= 0:
            print(f"\n  Time of Day:")
            print(f"    hour range: {min(hours):02d}:00 - {max(hours):02d}:00")
            day_count = sum(1 for h in hours if 6 <= h < 20)
            night_count = len(hours) - day_count
            print(f"    daylight: {day_count}  night: {night_count}")
        
        if p50s:
            print(f"\n  Luminance Percentiles:")
            print(f"    p50 range: {min(p50s):.4f} - {max(p50s):.4f}")
            print(f"    p99 range: {min(p99s):.4f} - {max(p99s):.4f}")
    
    # Summary table for threshold tuning
    print(f"\n{'='*70}")
    print(f"THRESHOLD TUNING SUMMARY")
    print(f"{'='*70}")
    print(f"\n{'Folder':<30} {'Ratio':<20} {'Delta':<20} {'Period'}")
    print(f"{'-'*30} {'-'*20} {'-'*20} {'-'*10}")
    
    for folder, cals in sorted(by_folder.items()):
        ratios = [c.get('corner_analysis', {}).get('corner_to_center_ratio', 0) for c in cals if c.get('corner_analysis')]
        deltas = [c.get('corner_analysis', {}).get('center_minus_corner', 0) for c in cals if c.get('corner_analysis')]
        hours = [c.get('time_context', {}).get('hour', -1) for c in cals if c.get('time_context')]
        
        if ratios:
            ratio_str = f"{min(ratios):.3f} - {max(ratios):.3f}"
            delta_str = f"{min(deltas):.4f} - {max(deltas):.4f}"
            
            # Determine period
            if hours and hours[0] >= 0:
                avg_hour = sum(hours) / len(hours)
                if 6 <= avg_hour < 20:
                    period = "day"
                else:
                    period = "night"
            else:
                period = "?"
            
            print(f"{folder:<30} {ratio_str:<20} {delta_str:<20} {period}")
    
    print(f"\n{'='*70}")
    print("RECOMMENDED NEXT STEPS:")
    print("  1. Capture 'Roof Open' images (day and night)")
    print("  2. Re-run this script to see the full distribution")
    print("  3. Set thresholds based on gaps between scene types")
    print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(description="Analyze calibration data for threshold tuning")
    parser.add_argument('directory', help='Directory containing calibration files')
    args = parser.parse_args()
    
    directory = Path(args.directory)
    if not directory.exists():
        print(f"ERROR: Directory not found: {directory}")
        sys.exit(1)
    
    calibrations = load_calibration_files(directory)
    if not calibrations:
        print("No calibration files found")
        sys.exit(1)
    
    analyze_data(calibrations)


if __name__ == '__main__':
    main()
