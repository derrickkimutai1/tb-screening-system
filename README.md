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
