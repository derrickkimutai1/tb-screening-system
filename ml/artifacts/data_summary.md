# Dataset summary

Produced by `ml/scripts/prepare_data.py`. Regenerate rather than edit.

- Split: 70 / 15 / 15, stratified on source dataset and class together
- Random seed: 42
- Duplicate images found: 0
- Both reference datasets hold one image per patient, so an image-level split is also a patient-level split

## Images per split

| Split | Montgomery normal | Montgomery TB | Shenzhen normal | Shenzhen TB | Total | TB share |
|---|---|---|---|---|---|---|
| train | 56 | 40 | 228 | 235 | 559 | 49.2% |
| validation | 12 | 9 | 49 | 51 | 121 | 49.6% |
| test | 12 | 9 | 49 | 50 | 120 | 49.2% |
| **all** | 80 | 58 | 326 | 336 | **800** | **49.2%** |

## Source characteristics

- Colour modes present: {'L': 138, 'P': 635, 'RGB': 27}
- Width: 1130 to 4892 pixels
- Height: 948 to 4892 pixels
- All images are converted to single-channel intensity, resized to 224 by 224 and repeated across three channels by `ml/preprocessing.py`
