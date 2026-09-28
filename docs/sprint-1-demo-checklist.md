# Sprint 1 demo checklist

Where each requirement lives, what to open, and what it shows.

---

## 1. A properly set up development environment

**Open:** `requirements.txt`, `requirements-ml.txt`, `.env.example`

**Run:**

```
.venv/Scripts/python.exe manage.py check
```

**Shows:** `System check identified no issues (0 silenced).`

**Say:** Python 3.11, Django 5.2 LTS, PostgreSQL 17 and TensorFlow 2.21. Dependencies are
pinned and split into what the application needs to run and what model training needs.
Credentials come from a `.env` file that is never committed. The CI workflow rebuilds this
environment from scratch on every push, so the setup is proven rather than described.

---

## 2. A clean and professionally organised codebase

**Open:** the VS Code Explorer panel

```
config/     Django project settings and URLs
screening/  The web application: models, views, forms, templates, tests
ml/         Training code, kept separate from the application
scripts/    Operational tooling, such as the Drive backup
docs/       Development log and sprint records
```

**Run:**

```
.venv/Scripts/python.exe -m ruff check .
```

**Shows:** `All checks passed!`

**Say:** Training code is separate from the web application because they have different
lifecycles. The one module they share is `ml/preprocessing.py`, deliberately, so that the
way an image is prepared cannot differ between training and the running system. Style is
enforced automatically rather than by habit; the rules are in `pyproject.toml`.

---

## 3. All code maintained using Git version control

**Open:** github.com/derrickkimutai1/tb-screening-system, then the commit list

**Say:** Every commit is a working checkpoint with a message explaining the change, not a
periodic save. Datasets, the virtual environment and the `.env` file are excluded, so the
repository holds source code and its history and nothing else.

---

## 4. Relevant data, databases and files prepared

**Open:** `ml/artifacts/data_summary.md`, previewed with `Ctrl+Shift+V`

| Split | Total | TB share |
|---|---|---|
| train | 559 | 49.2% |
| validation | 121 | 49.6% |
| test | 120 | 49.2% |
| **all** | **800** | **49.2%** |

**Then open:** pgAdmin, `tb_screening`, table `screening_predictionrecord`, View/Edit Data

**Then open:** `G:\My Drive\tb-screening-system` and drive.google.com

**Say:** 800 chest X-rays from the Montgomery and Shenzhen datasets, both public and
de-identified. Every image is checked for corruption and fingerprinted, and those
fingerprints are compared within and across both datasets to rule out duplicates, because
a duplicate crossing a split boundary would mean testing the model on an image it had
already seen. The split is stratified on source dataset and class together and seeded, so
it reproduces exactly. No images are copied; a manifest records which split each belongs
to, so every script reads the same definition.

---

## 5. Appropriate use of automation

**Open:** the **Actions** tab on GitHub, showing a passing run

**Open:** `.pre-commit-config.yaml` and `.github/workflows/ci.yml`

**Run:**

```
.venv/Scripts/python.exe manage.py test screening
```

**Shows:** 16 tests, then `OK`

**Say:** Checks run without being remembered. On every commit, hooks lint and format the
code and block an accidental commit of a large file or a private key. On every push,
GitHub Actions builds the environment, runs the linter, checks that no model was changed
without a migration, and runs the full test suite against a real PostgreSQL service.
Data acquisition, preparation and backup are all scripted and repeatable:
`download_shenzhen.py`, `prepare_data.py` and `backup_to_drive.py`.

---

## Running order, about six minutes

1. VS Code: folder structure, then `manage.py check`
2. Terminal: `manage.py test screening`, 16 tests pass live
3. Browser at `localhost:8000`: upload an X-ray, result, case history, dashboard
4. pgAdmin: the record just created, in the database
5. GitHub: commits, then the Actions tab
6. Colab: *Open in Colab* from the README, mount Drive, clone, load the data

The order is a story: it works, it is tested, it is stored, it is versioned, it is checked
automatically, and it is recoverable from the cloud.

---

## Known gaps, to state rather than hide

- **Documentation.** The code is ahead of Chapter 3. The ERD and class diagram need
  redrawing around the implemented schema, the preprocessing section corrected, the tools
  list updated and the data summary table added.
- **Wireframes**, listed in proposal section 3.6.2, are outstanding.
- **The model.** The prediction is a fixed placeholder. This is deliberate sequencing: the
  database and workflow are proven before the model is connected, so the two are never
  debugged at the same time. Training is Sprint 3.
