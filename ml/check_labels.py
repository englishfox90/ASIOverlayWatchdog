#!/usr/bin/env python3
"""Quick script to check label distribution by folder."""
import json
from pathlib import Path
from collections import defaultdict

data_dir = Path('E:/Pier Camera ML Data')
stats = defaultdict(lambda: {'open': 0, 'closed': 0, 'unlabeled': 0})

for cal_file in data_dir.rglob('calibration_*.json'):
    folder = cal_file.parent.name
    with open(cal_file) as f:
        data = json.load(f)
    labels = data.get('labels', {})
    if labels.get('labeled_at'):
        if labels.get('roof_open'):
            stats[folder]['open'] += 1
        else:
            stats[folder]['closed'] += 1
    else:
        stats[folder]['unlabeled'] += 1

print('=' * 60)
print('LABEL DISTRIBUTION BY FOLDER (from your manual labels)')
print('=' * 60)
print()

total_open = 0
total_closed = 0
total_unlabeled = 0

for folder, counts in sorted(stats.items()):
    total = counts['open'] + counts['closed'] + counts['unlabeled']
    total_open += counts['open']
    total_closed += counts['closed']
    total_unlabeled += counts['unlabeled']
    
    print(f'Folder: {folder}')
    print(f'  Labeled OPEN:   {counts["open"]:4d}')
    print(f'  Labeled CLOSED: {counts["closed"]:4d}')
    print(f'  Unlabeled:      {counts["unlabeled"]:4d}')
    
    # Check for potential mismatches
    if 'open' in folder.lower() and counts['closed'] > 0:
        print(f'  ⚠️  {counts["closed"]} images labeled CLOSED in "Open" folder')
    if 'closed' in folder.lower() and counts['open'] > 0:
        print(f'  ⚠️  {counts["open"]} images labeled OPEN in "Closed" folder')
    print()

print('=' * 60)
print('TOTALS')
print('=' * 60)
print(f'  Total OPEN:     {total_open}')
print(f'  Total CLOSED:   {total_closed}')
print(f'  Total Unlabeled: {total_unlabeled}')
print(f'  Total Samples:  {total_open + total_closed + total_unlabeled}')
print()
print('The model trains on YOUR LABELS, not folder names.')
