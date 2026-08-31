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
- The Shenzhen download failed part-way with a connection reset and was restarted with
  resume and retry enabled. Montgomery completed and was verified. The remaining download
  does not block the application work.
