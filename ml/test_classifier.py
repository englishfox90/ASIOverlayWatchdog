"""Quick test of the roof classifier against manual labels."""
import json
from pathlib import Path
from ml.roof_classifier import RoofClassifier

# Load the trained model
print("Loading model...")
classifier = RoofClassifier.load('ml/models/roof_classifier_v1.pth', image_size=128)

# Test on samples using LABELS from calibration JSON
data_dir = Path('E:/Pier Camera ML Data')

print("\n" + "="*60)
print("ROOF CLASSIFIER TEST (vs Manual Labels)")
print("="*60)

# Collect samples by their LABEL (not folder)
labeled_open = []
labeled_closed = []

for cal_file in data_dir.rglob('calibration_*.json'):
    with open(cal_file) as f:
        cal_data = json.load(f)
    
    labels = cal_data.get('labels', {})
    if not labels.get('labeled_at'):
        continue
    
    timestamp = cal_file.stem.replace('calibration_', '')
    fits_path = cal_file.parent / f"lum_{timestamp}.fits"
    
    if not fits_path.exists():
        continue
    
    if labels.get('roof_open'):
        labeled_open.append((fits_path, cal_file.parent.name))
    else:
        labeled_closed.append((fits_path, cal_file.parent.name))

print(f"\nFound {len(labeled_open)} samples labeled OPEN")
print(f"Found {len(labeled_closed)} samples labeled CLOSED")

# Test samples labeled OPEN
correct_open = 0
print(f"\n--- Testing samples LABELED as OPEN (showing first 5) ---")
for fits_path, folder in labeled_open[:5]:
    result = classifier.predict_from_fits(fits_path)
    status = "OPEN" if result.roof_open else "CLOSED"
    match = "✓" if result.roof_open else "✗"
    print(f"  {match} {fits_path.name} [{folder}]: predicted {status} ({result.confidence:.1%})")

for fits_path, _ in labeled_open:
    result = classifier.predict_from_fits(fits_path)
    if result.roof_open:
        correct_open += 1

# Test samples labeled CLOSED
correct_closed = 0
print(f"\n--- Testing samples LABELED as CLOSED (showing first 5) ---")
for fits_path, folder in labeled_closed[:5]:
    result = classifier.predict_from_fits(fits_path)
    status = "OPEN" if result.roof_open else "CLOSED"
    match = "✓" if not result.roof_open else "✗"
    print(f"  {match} {fits_path.name} [{folder}]: predicted {status} ({result.confidence:.1%})")

for fits_path, _ in labeled_closed:
    result = classifier.predict_from_fits(fits_path)
    if not result.roof_open:
        correct_closed += 1

# Summary
print("\n" + "="*60)
print("RESULTS (vs YOUR LABELS)")
print("="*60)
print(f"  OPEN samples:   {correct_open}/{len(labeled_open)} correct ({100*correct_open/len(labeled_open):.1f}%)")
print(f"  CLOSED samples: {correct_closed}/{len(labeled_closed)} correct ({100*correct_closed/len(labeled_closed):.1f}%)")
total_correct = correct_open + correct_closed
total = len(labeled_open) + len(labeled_closed)
print(f"  TOTAL:          {total_correct}/{total} correct ({100*total_correct/total:.1f}%)")
print("="*60)
