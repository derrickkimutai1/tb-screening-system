# Development Log

This log replaces the daily stand-up for a solo project, as described in section 3.4.4
of the proposal. Each entry records what was completed, what is planned next, and any
blockers encountered. Entries feed the sprint reviews and retrospectives.

---

## Sprint 1 — Project setup and dataset validation
Goal: environment configured, datasets inspected and split.

### 31 August 2026

**Completed**
- Confirmed the local toolchain: Python 3.11.4, Git 2.47.0, PostgreSQL 17.5, VS Code 1.132.
- Initialised the Git repository and created the virtual environment.
- Fixed the dependency set and split it into runtime and model-development requirements.
- Resolved two conflicts between the proposal and the engineering brief:
  the database design becomes `ScreeningCase` with a related `ReviewNote` table, and
  preprocessing uses the MobileNetV2 `preprocess_input` scaling rather than 0 to 1.
  Both changes are to be reflected in the proposal text and diagrams.

- Created the `tb_screening` database and the `tb_app` role in pgAdmin, and confirmed
  Django connects to PostgreSQL 17.5.
- Created the Django project (`config`) and the `screening` application. Settings read
  all credentials from `.env`; timezone set to Africa/Nairobi.
- Built the `PredictionRecord` and `ReviewNote` models and applied the first migration.
  Database-level check constraints reject probabilities outside 0 to 1 and triage
  thresholds that are out of order. Both were verified by attempted inserts.
- Confirmed the environment: TensorFlow 2.21 runs on CPU under Windows, and MobileNetV2
  builds with `out_relu` as its final convolutional layer, which is the layer Grad-CAM
  will target in Sprint 4.
- Started the Montgomery and Shenzhen dataset downloads from the National Library of
  Medicine.

**Decisions recorded**
- The database uses `PredictionRecord` with a related `ReviewNote` table. The proposal's
  section 3.5.3 describes a single entity while section 3.6.1 lists six; five of those six
  are one-to-one with a single screening event, whereas review notes are genuinely
  one-to-many. The ERD and class diagram are to be updated to match.
- Thresholds are stored on every record so that historical results stay interpretable
  after the thresholds are revised during validation.

- Built the upload, result, case history and reporting dashboard views against the
  database, using a fixed placeholder in place of a model prediction.
- Wrote the interface theme. The first light version was rejected on review as too flat,
  and was reworked as a dark reading-room theme: radiographs are read against dark
  backgrounds on viewing stations, so the interface follows that convention rather than
  a general web style.
- Two defects were found by reviewing the rendered pages rather than the code. A triage
  marker rendered as a stray letter, and the radiograph panel had no height limit, so one
  image pushed the review form off the screen. Both were fixed.
- Wrote and ran ten tests covering uploads, rejected files, filtering, dashboard counts on
  an empty and a populated database, and the review workflow. All pass.

**Phase 1 definition of done: met.** An upload creates a stored record, the result renders,
and the record appears in the dashboard, the case history and the Django admin.

- Reworked the interface twice on review. The first version was too restrained and the
  second still read as generic, so the theme was rebuilt with layered translucent
  surfaces over a near-black ground, an electric lime accent, and entrance and hover
  transitions. Triage labels and reduced-motion support were kept throughout.
- Verified the Montgomery archive. It contains 138 chest radiographs, 80 normal and 58
  TB-positive, which matches the figures quoted in proposal section 3.2.1. Labels are
  encoded in the filename suffix, `_0` for normal and `_1` for TB.
- Confirmed the archive also ships 276 manual lung masks, a left and a right mask per
  image, plus 139 radiologist clinical readings. The masks make it possible to measure
  how much of the Grad-CAM activation falls inside the lung fields, and the readings will
  support the error analysis in Phase 4.

**Planned next**
- Write `ml/preprocessing.py`, imported by both the training scripts and the application
  so that training and inference preprocessing cannot diverge.
- Write `ml/scripts/prepare_data.py` to inspect both datasets for corrupt and duplicate
  images and produce the stratified 70/15/15 split as a manifest recording each image's
  source dataset.

**Blockers**
- The Shenzhen download failed part-way with a connection reset. Carried into 1 September.

### 1 September 2026

**Completed**
- Replaced the Shenzhen bulk download. The archive on openi.nlm.nih.gov began returning an
  error page and the server does not honour range requests, so an interrupted transfer
  could not be resumed. The images are now fetched individually from the National Library
  of Medicine data portal by `ml/scripts/download_shenzhen.py`, which skips files already
  present and is therefore restartable. This route also proved roughly twenty times
  faster.
- Retrieved all 662 Shenzhen images: 326 normal and 336 TB-positive, matching the figures
  quoted in proposal section 3.2.1.
- Verified the set. No corrupt files, no exact duplicates, and no truncated downloads.

**Findings that affect preprocessing**
- The Shenzhen images are not uniformly encoded: 635 are palette mode and 27 are RGB.
  Loaded without conversion these produce arrays of different shapes, which would either
  fail or silently pass malformed input for about four per cent of the data.
- Image dimensions vary widely, from 1130 by 948 to 3001 by 3001 in the Shenzhen set and
  around 4020 by 4892 in Montgomery. Aspect ratios therefore differ, so the resize
  strategy has to be decided and applied identically in training and inference.
- Both findings reinforce the decision to keep a single preprocessing module imported by
  the training scripts and the web application.

**Planned next**
- Write `ml/preprocessing.py` and `ml/scripts/prepare_data.py`.
- Produce the stratified 70/15/15 split with a manifest recording each image's source
  dataset.

**Blockers**
- None.

### 9 September 2026

**Completed**
- Reworked the interface after further review. The ground moved to a warm olive
  charcoal with a single acid accent, headings to a heavy condensed face at display
  size, and technical fields to monospaced small caps. Content settles in on scroll,
  dashboard figures count up, and the score gauge sweeps to its reading. All motion is
  suppressed under `prefers-reduced-motion` and triage markers keep their text labels.
- Extracted and inspected the Montgomery set: 138 images, 80 normal and 58 TB, no
  corrupt files, all 8-bit greyscale, 4020 to 4892 pixels square.
- Wrote `ml/preprocessing.py`, the single image-preparation module imported by both the
  training scripts and the web application. It converts any source encoding to intensity,
  resizes to 224 by 224, repeats across three channels and scales to the range -1 to 1.
- Wrote `ml/scripts/prepare_data.py`, which inspects both datasets, checks for duplicate
  images by content hash within and across them, and writes the stratified split.
- Produced the split: 559 training, 121 validation, 120 test images, stratified on source
  dataset and class together so both stay proportional across all three. Seed 42, so the
  split reproduces exactly. No duplicates were found in 800 images.

**Verified rather than assumed**
- The scaling in `ml/preprocessing.py` was compared against
  `tf.keras.applications.mobilenet_v2.preprocess_input` and is identical, so the module
  can stay free of a TensorFlow dependency without risking a mismatch. A test now pins
  this.
- A further test confirms that greyscale, palette and RGB inputs produce byte-identical
  output, which is the defect the combined dataset would otherwise have introduced.
- Batches load from each split with correct shapes, dtype, value range and labels.

**Notes for the report**
- Both reference datasets hold one image per patient, so the image-level split is also a
  patient-level split. This satisfies the data-integrity requirement without needing
  patient identifiers.
- The combined set is 800 images at 49.2 per cent TB, so no resampling or class weighting
  is required.

**Planned next**
- Sprint 2: image quality checking with OpenCV, and the augmentation pipeline for the
  training split only.

**Blockers**
- None.
