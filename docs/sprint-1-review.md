# Sprint 1 Review — Data Preparation and Development Environment

Sprint goal, from proposal Table 3.1: *environment configured, datasets inspected and
split.*

Status: **complete**.

---

## 1. Development environment

| Component | Version | Verified |
|---|---|---|
| Python | 3.11.4 | yes |
| Django | 5.2 LTS | yes |
| PostgreSQL | 17.5 | connected, migrations applied |
| TensorFlow / Keras | 2.21 / 3.15 | imports and runs on CPU |
| OpenCV | 4.12 (headless) | yes |
| scikit-learn, NumPy, pandas | 1.7 / 2.2 / 2.3 | yes |

Dependencies are split into `requirements.txt`, which is what the web application needs
in order to run, and `requirements-ml.txt`, which adds training, evaluation and tooling.
Credentials are read from a `.env` file that is not committed; `.env.example` records the
keys required.

MobileNetV2 was built and its final convolutional layer confirmed as `out_relu`, which is
the layer Grad-CAM will target in Sprint 4. Confirming this now removes a risk from a
later sprint.

## 2. Codebase organisation

```
config/        Django project settings and root URLs
screening/     The screening application
  services/    Image processing, quality, prediction, triage, Grad-CAM
ml/
  preprocessing.py   Image preparation shared by training and the application
  scripts/           Data acquisition and preparation
  artifacts/         Split manifest and data summary
data/          Datasets, downloaded rather than tracked
media/         Uploaded radiographs and generated overlays
docs/          Development log and sprint reviews
```

Training code is deliberately separate from the web application. The one module they
share is `ml/preprocessing.py`, which is imported by both so that the way an image is
prepared cannot differ between training and inference.

## 3. Version control

- 23 commits, all pushed to `github.com/derrickkimutai1/tb-screening-system`
- Each commit is a working checkpoint rather than a save point, so any change can be
  traced or reverted on its own
- Datasets, media, the virtual environment and `.env` are excluded from the repository
- `.gitattributes` normalises line endings so the history stays clean across machines

## 4. Data preparation

Datasets: Montgomery County and Shenzhen No. 3 People's Hospital, both from the U.S.
National Library of Medicine, retrieved by `ml/scripts/download_shenzhen.py` so the
acquisition is reproducible rather than described.

| Split | Montgomery normal | Montgomery TB | Shenzhen normal | Shenzhen TB | Total | TB share |
|---|---|---|---|---|---|---|
| train | 56 | 40 | 228 | 235 | 559 | 49.2% |
| validation | 12 | 9 | 49 | 51 | 121 | 49.6% |
| test | 12 | 9 | 49 | 50 | 120 | 49.2% |
| **all** | 80 | 58 | 326 | 336 | **800** | **49.2%** |

Checks carried out on all 800 images:

- Every image decodes. No corrupt files.
- No duplicates by content hash, within either dataset or across the two. A duplicate
  crossing a split boundary would leak test data into training.
- Both datasets hold one image per patient, so the image-level split is also a
  patient-level split.
- The split is stratified on source dataset and class together, and seeded, so it
  reproduces exactly.

Two findings changed the preprocessing design:

- The images are not uniformly encoded. Montgomery is 8-bit greyscale; Shenzhen is 635
  palette and 27 RGB. Loaded without conversion these produce arrays of different shapes.
- Dimensions range from 1130 x 948 to 4892 x 4892, so aspect ratios differ.

Both are handled in one place by `ml/preprocessing.py`, which converts any source
encoding to intensity, resizes to 224 x 224, repeats across three channels and scales to
the range -1 to 1.

## 5. Automation

| Mechanism | What it does | When |
|---|---|---|
| Pre-commit hooks | Lint, format, normalise line endings, block large files and private keys, refuse a model change without a migration | Every commit |
| GitHub Actions | The same checks plus the full test suite against a PostgreSQL 17 service | Every push |
| `prepare_data.py` | Inspects, de-duplicates and splits the datasets | Repeatable, seeded |
| `download_shenzhen.py` | Retrieves the dataset, skipping files already present | Restartable |

Test suite: 16 tests covering the upload path, validation messages for unusable files,
filtering, dashboard counts against both an empty and a populated database, the review
workflow, and the shared preprocessing.

Two of the preprocessing tests are worth noting. One asserts that the scaling is
identical to `tf.keras.applications.mobilenet_v2.preprocess_input`, which is what allows
the module to avoid a TensorFlow dependency without risking a mismatch. The other asserts
that greyscale, palette and RGB inputs produce byte-identical output.

## 6. Working application

The Django application runs against PostgreSQL with four pages: upload, result, paginated
case history, and reporting dashboard. An upload is validated, stored, and rendered as a
result with a score gauge and a threshold scale.

The prediction is a fixed placeholder marked `placeholder-0` in the model version field,
so placeholder records can be distinguished from real ones. This is deliberate: the
database and the workflow are proven before any model is connected, so the two are never
being debugged at the same time.

## 7. Carried into Sprint 2

- Image quality checking with OpenCV, per proposal Objective 4
- Augmentation applied to the training split only
- Wireframes, per proposal section 3.6.2
- Chapter 3 diagrams updated to match the implemented design
