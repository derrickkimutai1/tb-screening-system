# Demo runbook — Sprints 1 to 3

About thirteen minutes. The order tells a story: the system works, it is correct, it is
measured, it is versioned, it is automated, it is deployed, and it is recoverable.

---

## Before the session

1. **Start PostgreSQL** — it starts with Windows, but check pgAdmin connects.
2. **Start the application** and leave it running:
   ```
   .venv/Scripts/python.exe manage.py runserver
   ```
3. **Set `SIGN_IN_CODE_ON_SCREEN=True` in `.env`, then sign in.** The app opens on a
   sign-in page, not the upload form, so this comes before anything else you do in it.
   The six-digit code appears on the page instead of being emailed. See "Signing in as
   each role" below for the three accounts and what to say about the flag.

   **Request a code at most twice while rehearsing.** Three requests for one address
   inside five minutes are refused, by design, and the refusal lasts five minutes.

4. **Warm the model.** Signed in, upload one X-ray and discard the result. The first
   prediction takes about 2.7 seconds because the model loads on first use; scoring
   itself is about 121 milliseconds after that. A complete screening including the
   heatmap runs a median 6.2 seconds, inside the 10 seconds NFR-01 asks for, on 50
   timed runs. Do this before anyone is watching.
5. **Copy two test X-rays to the Desktop**, so they are easy to find in the file picker.
   Pick them from the test split, which the model has never been trained on:
   - one TB case, filename ending `_1.png`
   - one normal case, filename ending `_0.png`
6. **Open these tabs:** the running app, your GitHub repository, the GitHub Actions tab,
   drive.google.com, and the Colab notebook already run once so it does not ask for
   access mid-demo.
7. **Check Google Drive is running** — the `G:` drive should be present.
8. **Delete the rehearsal records** so the Cases list is not full of `DEMO-001`
   duplicates when it goes on screen. Then `manage.py prunemedia --delete` to
   remove the images they left behind.
9. **Build any waiting heatmaps:** `manage.py buildexplanations`. A batch upload
   defers its maps until each case is opened, so a case nobody has opened shows
   "building the explanation" rather than the picture. It is only a wait, but it
   is the wrong thing to have on screen. `--dry-run` first if you want to see
   what is outstanding; budget about five seconds a case.
10. **Confirm the audit chain:** `manage.py verifyaudit` should report the chain
    intact. The Audit trail page has the same check behind a button, which is
    worth running live rather than claiming.

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
- **The two panels** — the original radiograph and the explanation beside it, marked
  **Generated**. A single upload builds its map before the page is shown, because
  NFR-08 asks for every result to be presented with the picture that produced it. A
  batch is the exception and defers: an occlusion map is several hundred forward
  passes, so twenty of them would spend minutes on images nobody has opened. A
  deferred case builds its map when somebody first opens it, and `manage.py
  buildexplanations` warms them all in advance so that never happens on screen.

  Say "generated before the page was rendered" rather than "building now". An earlier
  version of the system deferred every map, including single uploads, and this runbook
  described that; the behaviour changed and the panel no longer shows a waiting state
  for the upload you are about to do.

> "The Explanation panel is Grad-CAM, which is the method the proposal names in SO4.
> Its caption says the map localises weakly, and the measurement is directly below it."

Then scroll to the **Occlusion map, for comparison** panel, which is a second panel
under the first. Do not skip it — it is the stronger half of the answer.

> "Both maps were measured against Montgomery's hand-drawn lung masks, where a map
> thrown at the radiograph at random scores 1.00. Grad-CAM scores 1.16. The occlusion
> map scores 1.61, and paired over the 58 masked TB films the gain is +0.447 with a
> confidence interval of +0.125 to +0.780, so it is a real difference and not a sample.
>
> The occlusion map covers each region in turn and scores the image again, so its bright
> areas are the ones the score actually depended on. I show both: the objective asks for
> Grad-CAM, and the measurement says what it is worth. Neither shows where disease is."

The figures on that panel are read from the evaluation artefacts when the page renders,
so they cannot disagree with the measurement. Say that if asked how you know they are
current.

Then upload the **normal case** and show the score drops and the triage level changes.

> "Nothing here is hard-coded. Every value comes from the model, and the thresholds come
> from validation."

## 2. The data is stored, about 1 minute

Click **Case list** — the archive, with scores, triage levels, quality status and
review status. Click **Dashboard** — the four figures, the triage doughnut and
the screening volume chart.

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
- **`experiments.csv`** — every training variant compared, and `architecture_comparison.md`
- **`learning_curve.md`** — whether 800 images is what limits the model

> "The model was evaluated on 120 images held out from training and from model
> selection. AUC 0.9291, sensitivity 0.9153, specificity 0.6393. Every figure has a
> confidence interval, because 120 images cannot support a single precise number:
> sensitivity is 0.839 to 0.983, specificity 0.509 to 0.758.
>
> I chose the threshold on validation to reach 92 per cent sensitivity rather than the
> WHO minimum of 90, because in screening a missed case costs more than a false alarm.
> That margin earned its keep: sensitivity fell to 0.9153 in transfer, so a threshold
> picked at exactly 0.900 would have landed below the requirement.
>
> Specificity is 63.9 per cent against the 70 per cent target, so the system over-refers.
> That is my main outstanding defect, and the validation curve already showed no
> threshold satisfies both targets at once on this data.
>
> Validation AUC was 0.9119 and test AUC 0.9291, so the result generalises."

## 4. Testing, about 3 minutes

In a second terminal:

```
.venv/Scripts/python.exe manage.py test screening
```

407 tests, then `OK`.

Then open `docs/sprint-2-test-record.md` — expected result, actual result, and the
corrections made during the sprint.

## 5. Version control and automation, about 1 minute

Your GitHub repository, then the commit list, then the **Actions** tab.

> "Every push builds the project from scratch on a clean machine with a real PostgreSQL
> server, runs the linter and runs all 407 tests. Checks also run on every commit, so a
> dataset or a password cannot be committed by accident."

## 6. The cloud, about 2 minutes

First the live release, because Sprint III asks for one:

<https://tb-screening.happybay-20a0549c.southafricanorth.azurecontainerapps.io/health/>

> "It answers 200 with the database reachable and the model loaded. The same image the
> tests passed on is what runs there, tagged with the commit that produced it, so I can
> say which code is live and roll back to the previous tag with one command.
>
> It scales to zero to stay inside the free grant, so the first visit after a quiet
> period waits for TensorFlow to load. Warm it before the session."

Then the backup, which is a different question:

**drive.google.com** → `tb-screening-system`: `datasets.zip`, the database dump, the
model and artefacts.

Then the **Colab** notebook: it mounts Drive, clones the code from GitHub, and runs the
same preprocessing module the application uses.

> "Code is in GitHub, data and models are in Drive, and Colab reads from both. If this
> laptop failed I would clone the repository, restore the data and the database from
> Drive, and carry on."

## Signing in as each role during the demonstration

An examiner will likely ask to see the system as a radiographer and as a
clinician. Three accounts exist for that, all at Kenyatta National Hospital so
they share a caseload and differ only in what they may do:

| Address | Role | What it demonstrates |
|---|---|---|
| `derrickkimutai@students.uonbi.ac.ke` | Radiographer | Sees every case, cannot review one |
| `derrick.kim46@gmail.com` | Clinician | Can record a review |
| `derrick.kimutai@strathmore.edu` | Administrator | Can review, and reaches `/admin/` to set roles |

Set `SIGN_IN_CODE_ON_SCREEN=True` in `.env` before presenting. The six-digit
code then appears on the page instead of being emailed, so the whole sequence
is typed in front of the room rather than fetched from three different
inboxes, and it does not depend on the venue's network. Nothing else changes:
the address is typed, the code is generated and checked, and a wrong code is
still refused. The flag is ignored unless `DEBUG` is on, so it cannot be
turned on in a deployment.

Say what it is if asked, rather than letting it be noticed: the code is being
shown instead of sent, and the sign-in itself is the real one.

**The point to make while switching roles**: the radiographer sees the same
caseload, so nothing is hidden from them, but the Review panel is
replaced by a note saying a clinician has to decide. Then add that the server
refuses the review even if the form is bypassed - it answers 403, which is
tested rather than asserted.

**If asked why a user cannot choose their own role**: because anyone who could
would grant themselves the right to sign off TB cases, and the role would be
decoration. It is set by an administrator in `/admin/`.

## 7. Close with what is outstanding, about 1 minute

Say these before being asked:

- **Specificity is 63.9 per cent on the held-out test split**, against a 70 per cent
  target, at the 0.102 threshold the system actually runs at. Sensitivity is 91.5 per
  cent, above the 90 per cent asked for. No threshold meets both at once, which is a
  property of the model on this data rather than a tuning oversight.
- **The explanation localises, but weakly, and the gain is not confirmed on held-out
  data.** The occlusion map scores 1.61 against lung masks where Grad-CAM scored 1.16,
  and paired over the 58 masked TB films the gain is +0.447 [+0.125, +0.780]. On the 9
  test films the interval includes zero. Montgomery has no more masked TB films.
- **The lung-mask metric is gameable**, and it is better to say so first: coarser maps
  score higher, up to 2.12 for a 5×5 grid that cannot point at a lesion, and a map that
  is hot everywhere still scores 1.00. The shipped setting is the finest that clearly
  beats Grad-CAM, not the best-scoring one.
- **The dataset is small and not Kenyan**, which limits both performance and
  generalisability. How small is now measured rather than conceded: retrained on
  quarters of the training split, validation AUC runs 0.8646, 0.8730, 0.8941, 0.9082
  and is still rising where the data stops. So more radiographs would still help this
  model, and `ml/artifacts/learning_curve.md` says roughly how many.

Then `docs/sprint-backlog.md` shows these as planned Sprint 3 tasks against the
objectives they serve.

---

## If something fails on the day

- **The app will not start** — check PostgreSQL is running, then that the terminal is in
  the project folder.
- **A prediction is slow** — the model is loading. It only happens on the first call.
- **The sign-in code is refused and no new one arrives** — three requests for one
  address inside five minutes are rate-limited. Wait, or sign in as one of the other
  two accounts, which have their own allowance.
- **No internet** — the app is entirely local and needs none. Skip sections 5 and 6, and
  show the committed artefacts in `ml/artifacts/` instead.
- **Colab asks for access** — this is why you run it once beforehand.
