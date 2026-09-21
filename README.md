# AI-Assisted Tuberculosis Screening and Triage from Chest X-Ray Images

An undergraduate capstone project at Strathmore University, School of Computing and
Engineering Sciences.

A clinician uploads a chest X-ray. The system checks the image quality, estimates whether
pulmonary tuberculosis is likely, assigns a low, medium or high suspicion triage level with
a short justification, generates a Grad-CAM heatmap showing the regions that influenced the
prediction, and stores the result in PostgreSQL for later review and reporting.

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

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/derrickkimutai1/tb-screening-system/blob/main/ml/notebooks/colab_workspace.ipynb)

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
  services/      Image processing, quality checking, prediction, triage, Grad-CAM
ml/
  scripts/       Data preparation, training and evaluation
  models/        Saved models and their metadata
  artifacts/     Metrics and evaluation figures
data/            Datasets, downloaded rather than tracked
media/           Uploaded X-rays and generated heatmap overlays
docs/            Development log and project documentation
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

## Status

In development. The Django application, database schema and environment are in place.
Model training, Grad-CAM and the screening interface are in progress.
