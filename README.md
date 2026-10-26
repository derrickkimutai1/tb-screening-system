# AI-Assisted Tuberculosis Screening and Triage from Chest X-Ray Images

An undergraduate capstone project at Strathmore University, School of Computing and
Engineering Sciences.

A clinician uploads a chest X-ray. The system checks the image quality, estimates whether
pulmonary tuberculosis is likely, assigns a low, medium or high suspicion triage level with
a short justification, builds an occlusion map showing the regions the prediction actually
depended on, and stores the result in PostgreSQL for later review and reporting.

## Scope and clinical boundary

This prototype supports preliminary TB screening and prioritisation only. It does not
provide a final diagnosis. Clinical review and confirmatory testing remain necessary.

It screens for pulmonary tuberculosis only, from chest radiographs of adults and
adolescents. It does not cover extrapulmonary TB, paediatric-specific screening,
drug-resistant TB, or any other chest pathology. It is a research prototype, not a
deployable medical device, and it has not been clinically validated.

## Technology

| Layer | Choice |
|---|---|
| Language | Python 3.11 |
| Web framework | Django 5.2 LTS |
| Database | PostgreSQL 17 |
| Deep learning | TensorFlow / Keras, MobileNetV2 transfer learning |
| Image processing | OpenCV |
| Evaluation | scikit-learn, NumPy, pandas, Matplotlib |
| Front end | Django templates, Bootstrap with a custom theme layer |

## Setup

Requires Python 3.11 and PostgreSQL 17.

Create the database and an application role, for example through pgAdmin:

```sql
CREATE ROLE tb_app WITH LOGIN PASSWORD 'your-password';
CREATE DATABASE tb_screening OWNER tb_app;

-- Django builds a temporary database when running the test suite.
ALTER ROLE tb_app CREATEDB;
```

Create the virtual environment and install dependencies:

```bash
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-ml.txt
```

`requirements.txt` holds what the web application needs to run, including inference.
`requirements-ml.txt` adds the model training, evaluation and linting packages.

Copy `.env.example` to `.env` and fill in the database password and a Django secret key.
The `.env` file is never committed.

Apply migrations and start the development server:

```bash
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py createsuperuser
.venv/Scripts/python.exe manage.py runserver
```

### Signing in

Every screening page requires a session. There are three ways to get one, and
none of them involves a password: this system stores none, so it has none to
leak or reset.

| Route | Needs | Set up in |
|---|---|---|
| Google | OAuth credentials | `docs/google-sign-in-setup.md` |
| Microsoft | An Azure app registration | optional, same pattern |
| A six-digit code by email | A mail provider | `docs/deployment.md`, step 1b |

The gate asks for an address in one field and works out the rest. An address
that already has an account is sent a sign-in code; one that does not is
registered and sent a confirmation code. Nobody is asked to know which case
they are in before they are allowed to type.

With none of them configured the application still starts and the sign-in page
says which routes are missing, so a fresh clone runs and the tests pass without
any credentials at all.

**Working without a mail provider.** With no `EMAIL_HOST`, messages go to the
server console rather than an inbox, and the confirmation page shows the code
it would have sent. That only happens while `DEBUG` is on *and* mail is going
to the console; see `screening/services/devmail.py`.

**Who may sign in.** `SIGN_IN_OPEN_REGISTRATION` decides whether a visitor can
create an account with any address they can read mail at. `SIGN_IN_ALLOWED_EMAILS`
and `SIGN_IN_ALLOWED_DOMAINS` restrict admission independently. A deployment
holding real patient records should close the first and set the second.

**Sessions end.** Thirty idle minutes on a shared workstation, sliding with
activity and ending when the browser closes. The page warns two minutes
before, so a half-written review note can be saved.

**Access is logged.** Every view, list, screening, review and refusal is
recorded with who, what, when and from where, readable by an administrator
and not editable through the interface.

**Roles.** A new account is a radiographer: it can screen and read cases but not
record a clinical review. Clinician and administrator can. Roles are assigned in
the Django admin, never by the user.

Run the tests with:

```bash
.venv/Scripts/python.exe manage.py test screening
```

## Development workflow

Checks run automatically rather than by memory.

**Before each commit.** Install the hooks once per clone:

```bash
.venv/Scripts/python.exe -m pre_commit install
```

They then lint and format the code, normalise line endings, and block an accidental
commit of a large file or a private key.

**On every push.** GitHub Actions runs the same checks against a PostgreSQL 17
service: lint, formatting, missing-migration check, Django system checks, and the
full test suite. See `.github/workflows/ci.yml`.

Run them by hand at any time:

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe manage.py makemigrations --check --dry-run
.venv/Scripts/python.exe manage.py test screening
```

## Cloud workflow: GitHub, Google Drive and Colab

Sprint 1, data preparation [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/derrickkimutai1/tb-screening-system/blob/main/ml/notebooks/01_sprint1_data_preparation.ipynb)

Sprint 2, baseline classifier [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/derrickkimutai1/tb-screening-system/blob/main/ml/notebooks/02_sprint2_baseline_classifier.ipynb)

Each place holds one thing, so nothing depends on a single machine:

| Location | Holds |
|---|---|
| Laptop | The working copy, where the application is developed and run |
| GitHub | The code and its full history |
| Google Drive | Datasets, trained models, evaluation outputs, uploaded images and database dumps |
| Colab | GPU compute for training |

```
Laptop  --git push-->  GitHub  --git clone-->  Colab
Laptop  --backup---->  Drive   <--mount----->  Colab
```

The project folder itself is not placed inside Drive. Drive's file sync conflicts with
Git's internal files, so code travels through GitHub and large files through Drive.

**Laptop to Drive.** With Google Drive for desktop installed and signed in:

```bash
.venv/Scripts/python.exe scripts/backup_to_drive.py
```

This writes the datasets as one archive, mirrors models, artefacts and uploads, and
dumps the database, copying only what has changed. Drive for desktop then uploads it.
The `.env` file is never copied.

**Colab.** The badge above opens `ml/notebooks/colab_workspace.ipynb`, which mounts
Drive, clones this repository, unpacks the datasets, checks the pipeline, and saves
training output back to Drive for the laptop to pick up.

**Recovering on a new machine.** Clone from GitHub, restore `datasets.zip` into the
project folder, and load the latest dump from Drive with `psql`.

## Preparing the data

Two scripts fetch and prepare the datasets. Both are repeatable; re-running skips
work already done.

```bash
.venv/Scripts/python.exe ml/scripts/download_shenzhen.py
.venv/Scripts/python.exe ml/scripts/prepare_data.py
```

`prepare_data.py` inspects every image, checks for duplicates by content hash within
and across both datasets, and writes a seeded 70/15/15 split stratified on source and
class together. It produces `ml/artifacts/splits.csv`, the manifest every later script
reads, and `ml/artifacts/data_summary.md`.

## Layout

```
config/          Django project settings and root URLs
screening/       The screening application
  services/      Image processing, quality checking, prediction, triage, explanations
ml/
  scripts/       Data preparation, training and evaluation
  models/        Saved models and their metadata
  artifacts/     Metrics and evaluation figures
data/            Datasets, downloaded rather than tracked
media/           Uploaded X-rays and generated heatmap overlays
docs/            Development log and project documentation
deploy/          Container entry point and Hugging Face Space configuration
scripts/         Backup to Drive, and the test-record generator
Dockerfile       The deployable image, built in two stages
```

Training code is kept separate from the web application. Preprocessing lives in a single
module imported by both the training scripts and the application, so the two cannot drift
apart.

## Data

Training and evaluation use the Montgomery County and Shenzhen No. 3 People's Hospital
chest X-ray datasets, published by the U.S. National Library of Medicine and introduced by
Jaeger et al. (2014). Both are publicly available. The datasets are not redistributed in
this repository.

These collections were gathered in the United States and China. Radiological presentation,
image acquisition and patient demographics differ from Kenyan health facilities, which
limits how far the results generalise. This is measured and reported rather than assumed.

## Documentation

| Document | What it covers |
|---|---|
| `docs/traceability.md` | Each objective traced to its component, test, result and evidence, and what is not met |
| `docs/test-record.md` | Generated from the suite by `scripts/build_test_record.py` |
| `docs/deployment.md` | Deploying to a Hugging Face Space, and configuring mail |
| `docs/usability-study.md` | Protocol and recording sheet for the usability evaluation |
| `docs/devlog.md` | Development log, decisions and the reasoning behind them |
| `docs/google-sign-in-setup.md` | Creating the Google OAuth credentials |
| `ml/artifacts/OPERATING_POINT.md` | What each stored metric describes, and what it does not |
| `ml/artifacts/architecture_comparison.md` | Why MobileNetV2, measured against three alternatives |

## Status

The application is complete and runs: sign-in, screening of single images and
batches, quality checking, triage, explanations, a review queue, review with
role separation, printable reports, CSV export, a tamper-evident access trail
and a health endpoint. 257 tests pass, and the same suite runs on every push.

**Headline results.** Test AUC 0.9291 [0.878, 0.970]. Decision threshold 0.102,
chosen on validation against the WHO target product profile; at that threshold
the held-out test split gives sensitivity 0.9153 [0.839, 0.983] and specificity
0.6393 [0.509, 0.758]. Changing hospital costs 0.071 of AUC. Occlusion shows the
model reads the lungs: 0.788 with lungs alone against 0.545 with everything
else.

**Not finished.** No deployed release yet; the container and its workflow are
ready and need an account to push to. No usability study yet; the instrument is
written and needs participants.

**Known limitations**, each measured rather than assumed:

- **No threshold meets both WHO targets.** The best specificity at or above 90%
  sensitivity is 0.689 against the 0.70 asked for.
- **The explanation localises weakly, and only on positive cases.** The shipped
  occlusion map scores a lift of 1.63 against hand-drawn lung masks on TB films,
  against 1.11 for the Grad-CAM map it replaced, and a paired comparison over
  the 58 masked TB radiographs puts the gain at +0.447 [+0.125, +0.780]. On the
  9 held-out test films the interval includes zero, so the improvement is not
  independently confirmed and no masked dataset larger than Montgomery was
  available to settle it. The map shows what the score depended on, not where
  disease is. `ml/artifacts/explanation_methods.md` records the full comparison,
  including why the best-scoring configuration was deliberately not chosen.
- **The score is not a calibrated probability.** Expected calibration error
  0.1018, systematically underconfident, which is why the interface calls it a
  model score and reports AUC.
- **A clinic is typed, not chosen.** Records are scoped by facility, so two
  spellings of one clinic make two separate caseloads.
- **The datasets are American and Chinese**, not Kenyan. See Data above.
