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

**Planned next**
- Upload, result, history and dashboard routes with a fixed placeholder result.
- Inspect the datasets once downloaded and build the stratified 70/15/15 split.

**Blockers**
- Dataset download is running at roughly 175 KB/s, so the full 4.4 GB will take several
  hours. It does not block the Django work.
