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
  the database design becomes `PredictionRecord` with a related `ReviewNote` table, and
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

---

## Sprint 2 — Core functionality, integration and initial testing

### 10 October 2026

**Completed**
- Trained the baseline classifier. MobileNetV2 transfer learning in two stages, as set out
  in proposal section 3.2.3, with augmentation on the training split only.
- Compared four training variants on the validation split alone and recorded them in
  `ml/artifacts/experiments.csv`. Lighter augmentation with a deeper fine-tune at a higher
  learning rate won on both AUC and recall.
- Selected the decision and triage thresholds from validation behaviour rather than
  defaulting to 0.50, targeting the World Health Organization product profile for a TB
  triage test. The chosen decision threshold is 0.362, the lowest reaching 90 per cent
  sensitivity.
- Evaluated once on the held-out test split. Every figure carries a bootstrap confidence
  interval, because 120 images cannot support a single precise number.
- Built the five services named in the proposal class diagram: `ImageProcessor`,
  `ImageQualityChecker`, `PredictionEngine`, `TriageJustifier` and `GradCAMGenerator`.
- Calibrated the image quality thresholds against the 559 training radiographs rather than
  choosing them arbitrarily, so an image is flagged only when it falls outside the range
  of images already accepted as readable.
- Integrated everything into the upload workflow. An upload now runs a quality check,
  preprocessing, prediction, triage and Grad-CAM, and stores the result in PostgreSQL.
- Wrote the Sprint 2 test record and the product backlog.

**Results on the held-out test split**
- AUC 0.891, 95% CI [0.825, 0.944]
- Sensitivity 0.949, 95% CI [0.887, 1.000] — meets the WHO target of 90 per cent
- Specificity 0.508, 95% CI [0.382, 0.641] — below the WHO target of 70 per cent
- 56 of 59 TB cases detected; 30 of 61 healthy patients incorrectly flagged
- Validation AUC was 0.893 and test AUC 0.891, so the result generalises and the
  selection process did not overfit the validation split.

**Observations**
- Inference takes about 150 milliseconds per image on this laptop's CPU after the first
  call, which supports the low-resource claim with a measurement rather than an assertion.
- Inspecting a Grad-CAM overlay for a TB case showed strong activation over the
  mediastinum and along the top edge near the "PA ERECT" annotation, rather than clearly
  over the lung fields. The model may be partly reading acquisition markers. Montgomery's
  276 manual lung masks make this measurable, and that measurement is planned for Sprint 3.

**Planned next**
- Improve specificity, the main outstanding defect.
- Measure Grad-CAM activation inside the lung fields.
- Update Chapter 5 and the Chapter 4 diagrams.

**Blockers**
- None technical. Documentation remains behind the implementation.

### 17 October 2026

**Completed**
- Tested whether the classifier reads pathology or shortcuts, prompted by the Grad-CAM
  lung concentration of 1.11 measured on 12 October. Three tests, in
  `ml/scripts/evaluate_shortcuts.py`, all against the held-out test split.

**Results**
- *Source separability.* A classifier trained to predict which dataset an image came from,
  ignoring TB entirely, scores AUC 1.000 and 100 per cent accuracy. The two datasets are
  perfectly distinguishable, so the shortcut is available to be learned.
- *Corner occlusion.* Blanking the top band, where the acquisition markers sit, moves AUC
  from 0.891 to 0.869, a loss of 0.021. Blanking the bottom band as a control changes
  nothing, 0.894. There is therefore a small but real dependence on the marker region.
- *Lungs against surroundings.* On the 21 Montgomery test images with masks, the intact
  images score 0.824. With everything outside the lungs blanked the score is 0.787, so
  almost all of the signal survives. With the lungs blanked and only the surroundings left
  the score falls to 0.426, below chance.

**Interpretation**
- The model reads the lungs. The signal lives inside them: remove the surroundings and
  performance barely moves, remove the lungs and it collapses below chance.
- The shortcut exists and is trivially learnable, but the model is not substantially
  relying on it. The marker region contributes about 0.02 of AUC.
- The Grad-CAM lung concentration of 1.11 therefore understates where the model is
  actually looking. The limitation is in the explanation method, not in the classifier.
  Grad-CAM produces a 7 by 7 map stretched across the image, which is too coarse to
  localise the diffuse texture changes that TB produces across both lungs.
- The sample for the third test is 21 images, so it is indicative rather than precise.

**Planned next**
- Repeat the lungs-against-surroundings test on more images, by training a model on
  Shenzhen and testing on all 138 Montgomery images.
- Report the Grad-CAM limitation honestly rather than presenting the heatmap as evidence
  of where the model looks.

**Blockers**
- None.

### 17 October 2026, continued

**Regularisation, to address specificity**
- Three variants trained and judged on validation only: higher dropout, weight decay, and
  both. Validation AUC rose from 0.8930 for the previous model to 0.9077, 0.9016 and
  0.9119 respectively. `reg-both`, dropout 0.5 with weight decay 1e-4, was promoted.
- On the test split: AUC 0.9291, accuracy 0.800, precision 0.754, specificity 0.721,
  recall 0.881. Against the previous model that is AUC up 0.039 and specificity up from
  0.508 to 0.721, which meets the WHO target of 0.70 for the first time. False positives
  fell from 30 of 61 healthy patients to 17.
- Recall fell from 0.949 to 0.881, so the WHO sensitivity target of 0.90 is now narrowly
  missed, and missed cases rose from 3 to 7.
- The cause is threshold transfer rather than the model. The threshold was chosen on
  validation to reach exactly 0.900 sensitivity; on the test split the same threshold
  delivered 0.881. With 121 validation images a sensitivity estimate carries roughly
  ±0.07, so aiming at exactly 0.90 leaves no margin. Targeting a higher sensitivity on
  validation would leave room for the transfer, and that decision can be made without
  consulting the test results.

**Cross-dataset validation**
- Trained on Shenzhen alone, 463 images, and tested on all 138 Montgomery images, none of
  which the model had seen.
- Within Shenzhen the validation AUC was 0.9336. Across to Montgomery it was 0.8625.
  **The cost of changing hospital is 0.071 of AUC.** Specificity at 90 per cent
  sensitivity on the unseen hospital was 0.525.
- This is the closest available estimate of what deploying to a Kenyan clinic would cost,
  and it is a measured figure rather than the assertion the proposal currently makes.

**The region test, repeated on 138 images instead of 21**
- Intact 0.8625, lungs only 0.7884, surroundings only 0.5453.
- The earlier finding holds on the larger sample: most of the signal is inside the lungs.
  The surroundings retain a little above chance, consistent with the 0.021 of AUC the
  occlusion test attributed to the acquisition markers.

**Planned next**
- Decide whether to re-select the threshold with a sensitivity margin, which would mean
  consulting the test split a third time and must be disclosed if done.

**Blockers**
- None.

### 18 October 2026

**Operating point settled**
- The threshold selection now carries a margin above the WHO requirement. A threshold
  picked for exactly 0.90 sensitivity on 121 validation images does not transfer
  precisely; one selected at 0.900 delivered 0.881 on unseen data.
- The margin is two points rather than more. The validation trade-off is steep in this
  region: raising the selection target from 0.92 to 0.95 buys two points of sensitivity
  for ten of specificity.

| Selection target | Threshold | Sensitivity | Specificity |
|---|---|---|---|
| 0.90 | 0.133 | 0.900 | 0.689 |
| 0.92 | 0.102 | 0.933 | 0.639 |
| 0.95 | 0.050 | 0.950 | 0.541 |
| 0.98 | 0.036 | 0.983 | 0.393 |

- Decision threshold is therefore **0.102**, high suspicion **0.546**. The application
  reads both from `metadata.json` and now uses them. All 29 tests pass.

**A result worth reporting in its own right**
- **No threshold satisfies both WHO targets at once.** The best specificity available at
  or above 90 per cent sensitivity is 0.689 on validation, short of the 0.70 the target
  product profile asks for. This is a property of the model on this data rather than a
  tuning problem.
- The 0.721 specificity recorded earlier was transfer luck; validation gave 0.689 for the
  same selection rule.

**Deliberately not done**
- The test split was not evaluated again after settling on 0.102. It had been consulted
  three times by then, and each further look weakens the independence of the final figure.
  The operating point was chosen entirely from the validation curve above.
- `ml/artifacts/OPERATING_POINT.md` records what each stored figure describes, including
  that the threshold-dependent numbers in `metrics.json` belong to an earlier setting
  while its AUC of 0.9291 remains valid.

**Blockers**
- None.
