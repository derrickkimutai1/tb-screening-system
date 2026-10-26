# Demo runbook — Sprints 1 and 2

About ten minutes. The order tells a story: the system works, it is correct, it is
measured, it is versioned, it is automated, and it is recoverable.

---

## Before the session

1. **Start PostgreSQL** — it starts with Windows, but check pgAdmin connects.
2. **Start the application** and leave it running:
   ```
   .venv/Scripts/python.exe manage.py runserver
   ```
3. **Warm the model.** Upload one X-ray and discard the result. The first prediction
   takes about 2.7 seconds because the model loads on first use; every one after takes
   about 150 milliseconds. Do this before anyone is watching.
4. **Copy two test X-rays to the Desktop**, so they are easy to find in the file picker.
   Pick them from the test split, which the model has never been trained on:
   - one TB case, filename ending `_1.png`
   - one normal case, filename ending `_0.png`
5. **Open these tabs:** the running app, your GitHub repository, the GitHub Actions tab,
   drive.google.com, and the Colab notebook already run once so it does not ask for
   access mid-demo.
6. **Check Google Drive is running** — the `G:` drive should be present.

---

## 1. The working system, about 3 minutes

Open the app at `localhost:8000`.

> "A clinician uploads a chest X-ray with a non-identifying case reference."

Upload the **TB case**. Say what it is before the result appears, so the result is a
prediction rather than a reveal.

On the result page, point at each part:

- **The score**, drawn as a gauge. This is the model's output, between 0 and 1.
- **The triage level**, with its written justification naming the thresholds used.
- **The threshold scale** showing where this score sits across the bands.
- **The two panels** — the original radiograph and the explanation beside it. On a case
  nobody has opened before, the panel says it is building and fills in after about three
  seconds. That is deliberate: the map is measured, not inferred, so it is produced when
  somebody actually looks at a case rather than for every image of a batch.

> "The heatmap is an occlusion map. Each region is covered in turn and the image scored
> again, so the bright areas are the ones the score actually depended on. It shows what
> the model used, not where disease is."

If asked why it is not Grad-CAM: Grad-CAM scored a lift of 1.11 against hand-drawn lung
masks, where 1.0 is a map placed at random. This scores 1.63, a paired gain of +0.447
[+0.125, +0.780] across the 58 masked TB radiographs.

Then upload the **normal case** and show the score drops and the triage level changes.

> "Nothing here is hard-coded. Every value comes from the model, and the thresholds come
> from validation."

## 2. The data is stored, about 1 minute

Click **Cases** — the records, with scores, triage levels, quality status and review
status. Click **Dashboard** — counts, the suspicion doughnut, the activity chart.

Then open **pgAdmin**: `tb_screening` → Schemas → public → Tables →
`screening_predictionrecord` → right-click → View/Edit Data → All Rows.

> "The same records, in PostgreSQL. Each row stores the score, the model version and the
> thresholds it was judged under, so an old result stays interpretable after the
> thresholds change."

## 3. The evidence, about 2 minutes

This is Sprint 2's evaluation requirement. Open `ml/artifacts/`:

- **`metrics.json`** — the test results
- **`confusion_matrix.png`** and **`roc_curve.png`**
- **`threshold_selection.png`** — how the threshold was chosen
- **`experiments.csv`** — the four training variants compared

> "The model was evaluated once on 120 images held out from training and from model
> selection. AUC 0.891, sensitivity 0.949, specificity 0.508. Every figure has a
> confidence interval, because 120 images cannot support a single precise number.
>
> I chose the threshold on validation to reach 90 per cent sensitivity, which is the WHO
> target for a TB triage test, because in screening a missed case costs more than a false
> alarm. Specificity is 50.8 per cent, below the 70 per cent target, so the system
> over-refers. That is my main outstanding defect.
>
> Validation AUC was 0.893 and test AUC 0.891, so the result generalises."

## 4. Testing, about 1 minute

In a second terminal:

```
.venv/Scripts/python.exe manage.py test screening
```

29 tests, then `OK`.

Then open `docs/sprint-2-test-record.md` — expected result, actual result, and the
corrections made during the sprint.

## 5. Version control and automation, about 1 minute

Your GitHub repository, then the commit list, then the **Actions** tab.

> "Every push builds the project from scratch on a clean machine with a real PostgreSQL
> server, runs the linter and runs all 29 tests. Checks also run on every commit, so a
> dataset or a password cannot be committed by accident."

## 6. The cloud, about 1 minute

**drive.google.com** → `tb-screening-system`: `datasets.zip`, the database dump, the
model and artefacts.

Then the **Colab** notebook: it mounts Drive, clones the code from GitHub, and runs the
same preprocessing module the application uses.

> "Code is in GitHub, data and models are in Drive, and Colab reads from both. If this
> laptop failed I would clone the repository, restore the data and the database from
> Drive, and carry on."

## 7. Close with what is outstanding, about 1 minute

Say these before being asked:

- **Specificity is 63.9 per cent on the held-out test split**, against a 70 per cent
  target, at the 0.102 threshold the system actually runs at. Sensitivity is 91.5 per
  cent, above the 90 per cent asked for. No threshold meets both at once, which is a
  property of the model on this data rather than a tuning oversight.
- **The explanation localises, but weakly, and the gain is not confirmed on held-out
  data.** The occlusion map scores 1.63 against lung masks where Grad-CAM scored 1.11,
  and paired over the 58 masked TB films the gain is +0.447 [+0.125, +0.780]. On the 9
  test films the interval includes zero. Montgomery has no more masked TB films.
- **The lung-mask metric is gameable**, and it is better to say so first: coarser maps
  score higher, up to 2.12 for a 5×5 grid that cannot point at a lesion, and a map that
  is hot everywhere still scores 1.00. The shipped setting is the finest that clearly
  beats Grad-CAM, not the best-scoring one.
- **The dataset is small and not Kenyan**, which limits both performance and
  generalisability.

Then `docs/sprint-backlog.md` shows these as planned Sprint 3 tasks against the
objectives they serve.

---

## If something fails on the day

- **The app will not start** — check PostgreSQL is running, then that the terminal is in
  the project folder.
- **A prediction is slow** — the model is loading. It only happens on the first call.
- **No internet** — the app is entirely local and needs none. Skip sections 5 and 6, and
  show the committed artefacts in `ml/artifacts/` instead.
- **Colab asks for access** — this is why you run it once beforehand.
