# Demo runbook — Sprints 1 to 3

About thirteen minutes. The order tells a story: the system works, it is correct, it is
measured, it is versioned, it is automated, it is deployed, and it is recoverable.

---

## Before the session

1. **Start PostgreSQL** — it starts with Windows, but check pgAdmin connects.
2. **Start the application** and leave it running: double-click `start-app.bat`, or
   ```
   .venv/Scripts/python.exe manage.py runserver
   ```
3. **Decide where the sign-in code goes, then sign in.** The app opens on a sign-in
   page, not the upload form, so this comes before anything else you do in it. One
   line in `.env` settles it:

   | `SIGN_IN_CODE_ON_SCREEN` | Where the code appears | Use it when |
   |---|---|---|
   | `True` | On the page, under "CODE SENT" | **Presenting.** Needs no network and no inbox, and switching between the three roles costs nothing |
   | `False` | Really emailed, through Gmail | Ordinary use, and when showing that delivery is real |

   Restart the server after changing it; `.env` is read once at startup.

   **Set it to `True` before the session.** With it `False` the demonstration
   depends on the room's wifi, on Gmail, and on an inbox being open on screen
   beside the clinical records — three things that can fail in front of an
   examiner and none of which are part of what is being marked. See "Signing in
   as each role" below for the three accounts and what to say about the flag.

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

## The shape of the thirteen minutes

The old order of this runbook opened on the upload form. That is the weakest
thing here and it went first, which left the evidence — the part that took
most of the project — at minute four, after the plumbing.

The order below is reversed on purpose. **Say what the system does and what it
cannot do before showing it work.** A score on screen means nothing to a panel
that does not yet know the error rate behind it; shown afterwards, the same
number is a demonstration of something already established. It also puts every
weakness on the record in your own words in the first two minutes, which is
the difference between a limitation and a thing you were caught not saying.

| | Section | Minutes |
|---|---|---|
| 1 | What it does, and what it cannot | 2.5 |
| 2 | One screening | 3 |
| 3 | What the explanation is worth | 2 |
| 4 | It behaves like a clinical system | 2 |
| 5 | How I know it works | 2 |
| 6 | Deployed, offline, recoverable | 1.5 |
| 7 | Close on method | 1 |

---

## 1. What it does, and what it cannot, about 2.5 minutes

**Open the application on `/performance/`. Not the upload form.**

This page is the strongest thing in the project and it reads every figure from
the evaluation artefacts when the page loads, so nothing on it can drift from
the run that produced it. Say that: it is the difference between a number and
a claim.

Open with this, roughly:

> "Before I show you the system working, this is how well it works and where
> it fails, because the second matters more.
>
> It was evaluated on 120 radiographs held out from training **and from model
> selection**. AUC 0.9291. It finds 54 of 59 TB cases and misses 5.
>
> Every figure here carries a confidence interval from 2,000 bootstrap
> resamples, because 120 images cannot support a single precise number.
> Sensitivity is 0.9153, and the interval runs 0.839 to 0.983.
>
> Specificity is 0.6393 against the WHO target of 0.70. **It over-refers, and
> it does so by design.** I set the threshold on validation to reach 92 per
> cent sensitivity rather than the 90 WHO asks for, because in screening a
> missed case costs more than a false alarm. That margin earned its keep —
> sensitivity fell to 0.9153 in transfer, so a threshold picked at exactly
> 0.900 would have landed below the requirement. No threshold on this data
> meets both targets at once, and the validation curve showed that before I
> chose one."

Then scroll to **Known limitations** and read the four tiles aloud. They are
already written in the system's own words: both WHO targets cannot be met at
once, the score is not a probability (ECE 0.1018), changing hospital costs
0.0711 of AUC, and the explanation localises only weakly.

> "The application publishes its own failures. I did not want a version of
> this that only looks good."

Then the two tables further down, each in one sentence:

- **Why this model and not a larger one.** "ResNet50 scores 0.0359 of AUC
  higher and is 9.8 times the size. I am not running it. A model that scores
  better and cannot run on a clinic's processor has no sensitivity at all, so
  the choice was made on deployment and the cost of making it is the last
  column."
- **Does it read the lungs, or the label in the corner?** "This is the one I
  would show if I could only show one. Blank the lungs and re-score, and AUC
  falls from 0.8625 to 0.5453 — near a coin flip. That is causal evidence that
  the signal is in the lungs rather than in acquisition markers or borders.
  Most of what gets called explainability is correlational. This is not."

---

## 2. One screening, about 3 minutes

Only now open the upload form.

> "A radiographer uploads a chest X-ray with a non-identifying case reference."

Upload the **TB case**, and say what it is *before* the result appears, so the
result is a prediction and not a reveal.

On the result page, point at each part:

- **The score**, drawn as a gauge. The model's output between 0 and 1, and not
  a probability — the calibration tile said why.
- **The triage level**, with its written justification naming the thresholds
  used. The band is explained rather than asserted.
- **The provenance record**: the model version and the thresholds this result
  was judged under are written into the row. "A result from last month stays
  interpretable after I change the thresholds, which is why they are stored
  rather than looked up."
- **The two panels**, marked **Generated**. A single upload builds its map
  before the page is shown. A batch defers, because an occlusion map is
  several hundred forward passes.

Then upload the **normal case**. The score drops and the band changes.

> "Nothing here is hard-coded. Every value comes from the model, and the
> thresholds came from validation."

**Thirty seconds on storage, no more.** Open pgAdmin: `tb_screening` → Schemas
→ public → `screening_predictionrecord` → View/Edit Data → All Rows.

> "The same records, in PostgreSQL."

---

## 3. What the explanation is worth, about 2 minutes

Scroll to the **Occlusion map, for comparison** panel. **Do not skip this** —
it is the strongest two minutes available and the part most students cannot
do at all.

> "The proposal's fourth objective asks for Grad-CAM, so Grad-CAM is what the
> system shows. Then I measured whether it was worth anything.
>
> Montgomery ships hand-drawn lung masks, so this can be measured instead of
> judged by eye. A map thrown at the radiograph at random scores 1.00.
> **Grad-CAM scores 1.16** — barely above random. I am not going to stand here
> and call that an explanation.
>
> So I built an occlusion map, which covers each region in turn and re-scores
> the image, so its bright areas are the ones the score actually depended on.
> It scores **1.61**. Paired across the 58 masked TB films the gain is
> **+0.447, with a 95 per cent interval of 0.125 to 0.780**, so it is a real
> difference and not a sample. On the 9 held-out films the interval includes
> zero, so the improvement is measured rather than proven, and I would rather
> say that than round it away.
>
> I also built Score-CAM. It scored 0.26 — below chance. I rejected it and
> kept the module so anyone can re-run the comparison."

Then the point that wins the exchange:

> "The metric is gameable, and it is better that I say so than that you find
> it. Coarser maps score higher — a 5×5 grid reaches 2.12 and cannot point at
> a lesion, and a map that is hot everywhere still scores 1.00. What ships is
> the finest setting that clearly beats Grad-CAM, not the best-scoring one."

The figures on that panel are read from the artefacts when the page renders,
so they cannot disagree with the measurement. Say that if asked how you know
they are current.

---

## 4. It behaves like a clinical system, about 2 minutes

Sign out and back in as the **clinician** (see "Signing in as each role"
below). Record a decision on the case you just screened, with a note.

> "Confirming or dismissing a case is a clinical decision, so it is a separate
> role. The radiographer sees the same caseload — nothing is hidden from them
> — but the review panel is replaced by a note saying a clinician decides. And
> the server refuses the review even if the form is bypassed. It answers 403,
> and that is tested rather than asserted."

Then **Audit trail**, and press **Verify chain integrity** live.

> "Every view, list, screening, review, refusal and export is recorded. Each
> row hashes its own contents together with the hash of the row before it, so
> changing a field or removing a row from the middle breaks every hash after
> it. That is what makes it evidence rather than a list.
>
> It detects alteration. It does not prevent it — somebody with write access
> to the database could recompute the whole chain. Saying which of the two it
> is matters more than the feature."

If there is time, the **Profile** page: role, clinic, and the Data Protection
Act 2019 section — an export of your own data, and account closure that does
*not* delete clinical records, because a log somebody leaving could empty
would answer nothing.

---

## 5. How I know it works, about 2 minutes

In a second terminal:

```
.venv/Scripts/python.exe manage.py test screening
```

**429 tests, then `OK`.**

> "Four hundred and seven tests, covering uploads, oversized files, batch
> duplicate rejection, quality thresholds, triage boundaries, preprocessing
> equivalence, role permissions, metadata stripping, and the audit chain
> detecting its own alteration."

Then `docs/sprint-2-test-record.md` — expected result, actual result, and the
corrections made during the sprint.

Then GitHub: the commit list, then the **Actions** tab.

> "Every push builds the project from scratch on a clean machine with a real
> PostgreSQL server, runs the linter and runs all 429 tests. A dataset or a
> password cannot be committed by accident."

---

## 6. Deployed, offline, recoverable, about 1.5 minutes

The live release:

<https://tb-screening.happybay-20a0549c.southafricanorth.azurecontainerapps.io/health/>

> "It answers 200 with the database reachable and the model loaded. The same
> image the tests passed on is what runs there, tagged with the commit that
> produced it, so I can say which code is live and roll back with one command."

Then the resource measurements from the Performance page, in one breath:

> "I measured what it costs to run rather than asserting it. On a single
> processor core a screening takes a median 10.9 seconds, so **the ten-second
> requirement is met on the recommended machine and missed on the minimum
> one** — both are reported rather than the better of the two. The packaged
> Windows build answers 2 seconds after launch, occupies 1.32 GB, and fetches
> from zero outside hosts, so it runs where there is no internet. One
> screening moves 11.7 MB. Hosting is free to about 28,000 screenings a
> month."

Then recovery, briefly: code in GitHub, data and models in Google Drive, Colab
reads from both.

> "If this laptop failed I would clone the repository, restore from Drive, and
> carry on."

---

## 7. Close on method, not apology, about 1 minute

Do not end on a list of faults. Every fault has already been said, in section
1, in your own words. End on how you know.

> "Most of this project was not building the system. It was trying to show
> that it does not work.
>
> Thirteen separate measurement studies. I compared four architectures and the
> largest won, and I am not running it — the cost of that choice is on the
> screen. I blanked the lungs and showed the model falls to chance, so the
> signal is where it should be. I retrained on quarters of the data twelve
> times to find out whether 800 images is what limits it, and it still rises
> where the data stops, so more radiographs would help and the curve says
> roughly how many. I measured the explanation the proposal asked me for,
> found it barely beats random, and said so on the page rather than in a
> footnote.
>
> What is outstanding is specificity, a dataset that is small and not Kenyan,
> and an explanation whose improvement is not confirmed on held-out data.
> All three are measured rather than estimated, and `docs/sprint-backlog.md`
> has them as Sprint 3 tasks against the objectives they serve."

### If you are asked the hard version of any question

- **"Why MobileNetV2 when ResNet50 is better?"** — "It is better, by 0.0359 of
  AUC, and it is 9.8 times the size. The target is a clinic with no graphics
  card. A model that cannot run there has no sensitivity at all."
- **"Your specificity fails the target."** — "It does, 0.6393 against 0.70,
  and it is on the screen. No threshold on this data meets both targets. I
  chose to miss specificity rather than sensitivity, because a missed TB case
  costs more than a second look at someone healthy."
- **"Your Grad-CAM barely works."** — "It scores 1.16 where random scores
  1.00, and I measured that rather than waiting to be told. That is why there
  is an occlusion map beside it at 1.61, with the paired interval."
- **"It is not Kenyan data."** — "No, and section 1.5.1 of the approved
  proposal excludes Kenyan clinical data from scope. What I could measure is
  what changing hospital costs, and it is 0.0711 of AUC between the two
  sources I have. The application states that no Kenyan equipment was tested."
- **"Is this a medical device?"** — "No. It has no regulatory clearance, no
  clinical validation study, and no DICOM or hospital-system integration. It
  behaves like a clinical system in how it handles access, attribution and
  evidence. It is not one, and the performance page says so before anyone
  asks."

---

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
