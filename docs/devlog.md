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

---

## 19 October 2026 — Sprint review feedback, and what it exposed

The sprint review went badly. Three things were asked for that the project could
not answer, and all three were fair.

**1. No architecture was ever compared.** The proposal names MobileNetV2 and
justifies it by deployment: a clinic without a GPU. Seven runs existed, all of
them MobileNetV2, differing only in augmentation and regularisation. That is
hyperparameter tuning, not model selection. The lecturer's own course notes ask
under "CS Project II: Evidence Students Should Prepare" for "the baseline,
controlled comparisons ... and computing budget", and page 35 sets an activity
called "Choose the Better Model" on exactly this trade-off. The project had none
of it.

`train_model.py` now takes `--architecture`. Four are registered: MobileNetV2,
ResNet50, EfficientNetB0, and a small convolutional network with no pretrained
weights as the simpler baseline the checklist asks for. Every run shares the
splits, the head, the schedule, the regularisation and the seed, so a difference
is attributable to the architecture. What must differ is the input convention
each network was pretrained on, so `ml/preprocessing.py` stays the single source
of truth for reading a file and the conversion happens inside the model.

`compare_architectures.py` writes the comparison and the figure, including
bootstrap confidence intervals on the difference, because a gap of a few
hundredths of AUC on 121 validation images may be nothing.

**2. The upload accepted one image at a time.** It now accepts a multiple
selection, up to 20, screening each separately. A single upload is unchanged.
A batch turns the reference into a zero-padded prefix and reports what was
screened and what the quality check turned away.

**3. Grad-CAM was measured, not just described.** See the entry below; the
7 by 7 map was worse than chance and is now at chance.

**Two bugs the work exposed**
- `record_experiment` wrote `dropout` and `weight_decay` into a row whose column
  list omitted both, so any new run would have raised ValueError after training
  finished. It had never fired because the seven existing runs predate the
  columns being added to the row. Fixed, and the existing rows were backfilled
  from each run's own `metadata.json` rather than from memory.
- The first ResNet50 adapter wrapped `preprocess_input` in a `Lambda`. It trained
  correctly and could not be deserialised, so the saved model would not load. A
  one-epoch smoke test caught it before the long run; the adapter is now built
  from stock layers.

**A correction to the record**
The Grad-CAM lift of 1.11 recorded on 17 October was measured on the test split
alone, 21 Montgomery images. Across all 138 the same configuration gives 0.49.
The earlier figure was flattered by the sample, and the conclusion drawn from it
was too generous.

**Blockers**
- None.
## 19 October 2026 — Sign-in

The screening views were open to anyone who could reach the port. The brief puts
login and role management outside the core scope "unless time and requirements
permit it" (section 118), and the records are clinical, so the gate went in.

**The approach: no passwords in this codebase**
- Identity comes from Google through `django-allauth`. The application never sees
  a password, so it has none to store, hash, reset, leak or get wrong.
- Local registration is closed, `screening/auth.py:ScreeningAccountAdapter`. The
  only routes in are Google and a `createsuperuser` account for the Django admin.
- A Google account alone is not a credential for clinical records, so admission
  is by allowlist on top of it: `SIGN_IN_ALLOWED_EMAILS` and
  `SIGN_IN_ALLOWED_DOMAINS`. The check runs on every sign-in rather than only at
  first sign-up, so removing an address locks out a returning user too.
- An empty allowlist admits any Google account. That is the local-demonstration
  default and is marked in `.env.example` as unsuitable for deployment.

**Keeping a credential-free checkout runnable**
- The Google provider is registered only when both credentials are present in the
  environment. Without them the application still starts, the sign-in page reports
  the provider as unconfigured, and the test suite and CI run unchanged. This
  matters because the credentials cannot be committed.

**Other pieces**
- `screening/migrations/0002_site_domain.py` names the `django.contrib.sites` row
  from `DJANGO_SITE_DOMAIN`, defaulting to `localhost:8000`. The shipped default
  of `example.com` would otherwise send a successful sign-in to a domain nobody
  owns.
- The sign-in page is its own template at `screening/templates/account/login.html`
  with no navigation, since there is nowhere to go without a session. `TEMPLATES`
  now lists `screening/templates` in `DIRS` so it is found ahead of the plain
  pages allauth ships.
- The masthead carries the signed-in address, so it is always clear whose session
  is recording a review.

**Tests**
- 42 pass, up from 29. The new ones cover redirection of anonymous visitors from
  all four views including a case record, the closed registration route, the gate
  rendering without credentials, and eight allowlist cases including a lookalike
  domain.

**Still to do**
- Attribute `ReviewNote` to the signed-in user. The model records a reviewer name
  as free text today; now that there is a session it should be a foreign key.
- Role separation. Everyone who signs in currently has the same access.

**Blockers**
- The Google Cloud Console credentials have to be created by hand; the steps are
  in `docs/google-sign-in-setup.md`.

---

## 19 October 2026 — User profiles and role separation

Sign-in answered who someone is. It did not answer what they are allowed to do,
and every signed-in user had identical access. A profile now carries that.

**What a profile holds**
- **Role**, one of radiographer, clinician or administrator. A radiographer
  captures and screens; confirming or dismissing a case is a clinical judgement,
  so `Profile.may_review` is true only for the latter two. The check runs on the
  POST as well as deciding whether the form is drawn, because a hidden form is
  not an access control.
- **Facility**, which the user sets themselves.
- Role is deliberately **not** in `ProfileForm`. A user who could choose their
  own role could grant themselves review rights, which would make the role
  decorative. It is set in the Django admin.

**Reviews are attributed, not typed**
`ReviewNote` gains a nullable foreign key to the user. The free-text
`reviewer_name` stays and is filled from the signed-in account, so a note still
reads correctly after the account is removed; `on_delete=SET_NULL` means a
clinical record does not lose its history when someone leaves. The review form
no longer asks for a name, because nothing could verify one.

**Why a signal rather than lazy creation**
A profile is created by `post_save` on the user, so every account has exactly
one from the moment it exists. Creating it on first access instead would leave
every view, template and query to handle a user without one, which is the kind
of absence that surfaces as a crash on one page months later.

**Tests**
67 pass, up from 53. The new ones cover profile creation with the account,
default role, the page requiring a session, the facility being editable by its
owner, the role not being, a radiographer refused with 403 on the POST, a
clinician permitted, attribution to the signed-in user, and a note surviving its
author's deletion.

**Blockers**
- None.


## 25 October 2026 — the test split, for the last time

**What was measured**
`evaluate_model.py` run at the operating point the system actually ships,
decision threshold 0.102. Until now `metrics.json` described threshold 0.041,
an earlier point used while the selection margin was being investigated, so
there was no test-set sensitivity or specificity for the deployed setting at
all. The threshold itself was not touched: it was chosen from the validation
curve alone, and this run only measures what it does on unseen data.

**Result, 120 test images, 59 of them TB**

| | Validation | Test |
|---|---|---|
| Sensitivity | 0.9333 | **0.9153** [0.839, 0.983] |
| Specificity | 0.6393 | **0.6393** [0.509, 0.758] |
| Accuracy | — | 0.7750 [0.700, 0.850] |

54 true positives, 39 true negatives, 22 false positives, **5 TB cases missed**.
AUC is threshold-independent and unchanged at 0.9291 [0.878, 0.970].

**The margin earned its keep**
The threshold was selected for 0.92 sensitivity rather than the WHO minimum of
0.90, after a threshold picked for exactly 0.900 delivered 0.881 on unseen
data. Sensitivity dropped 1.8 points in transfer and landed at 0.9153, still
above the requirement. Chosen at the minimum it would have fallen below it.
Specificity transferred exactly.

**What is still not met**
Specificity 0.639 against the WHO target of 0.70. The validation curve already
said no threshold satisfies both targets at once; the test split agrees. It
stays a reported finding, not something to tune away against the data meant to
judge it.

**The cost**
This was the test split's fourth and final consultation — model selection, the
cross-dataset work, the earlier threshold investigation, and now this. Chapter
5 should state it. Each look weakens the independence of the figure, which is
why the operating point was still chosen without it.

**Blockers**
- Hosting. The Dockerfile and the deploy workflow are ready and need a Neon
  connection string, a Space name and a Hugging Face write token.

## 3 November 2026 — whether 800 images is what limits the model

"The dataset is small" is the easiest thing to say about this project and the
hardest to answer, because on its own it is a description rather than a
finding. Asserting that 800 images is enough would be no better. So it was
measured.

`ml/scripts/learning_curve.py` retrains the deployed recipe on 25, 50, 75 and
100 per cent of the training split, three stratified draws at each size, scored
every time on the same fixed validation split. Twelve retrainings, about ninety
minutes of CPU. The test split was not touched.

| Training images | Mean AUC | Range across draws |
|---|---|---|
| 140 | 0.8646 | 0.8402 to 0.8889 |
| 280 | 0.8730 | 0.8643 to 0.8801 |
| 419 | 0.8941 | 0.8883 to 0.9040 |
| 559 | 0.9082 | 0.9029 to 0.9123 |

**It is still rising where the data stops.** The last 140 images bought 0.0141
AUC against the 0.0114 this measurement can resolve, so the gain is real rather
than run-to-run noise. The dataset is a binding constraint on this model, not a
cosmetic complaint about it.

The three draws per size were the point of the exercise. A single run at each
size would have produced a curve, and the curve would have been unreadable: the
spread at 140 images is 0.0487, wider than the entire rise from 140 to 559. Any
claim made from one draw per point would have been a claim about which images
happened to be drawn.

**What it costs to fix.** Fitted as a power law, error falls 17 per cent per
doubling (R-squared 0.64). Extended, AUC 0.93 wants around 1,861 training
images and 0.95 wants around 6,519. Those are projections and are labelled as
such in the artefact; a two-parameter fit over a range of 140 to 559 images is
not entitled to speak about 6,000.

**What it does not say.** The yardstick is 121 validation images and stays 121
images at every point, so each AUC carries its own sampling error that has
nothing to do with training size. And nothing here is about Kenya: a curve
showing that more Montgomery and Shenzhen films would help says nothing about
whether those are the films that should be collected. `cross_dataset.json`
remains where that question is measured.

One incidental correction: the mean at 100 per cent is 0.9082 across three
seeds, against the 0.9119 recorded for `reg-both`. The deployed figure is one
draw of that distribution and sits slightly above its middle, which is worth
knowing when a single validation number is quoted anywhere.

## 4 November 2026 — correcting figures that had drifted from the artefacts

Fixing a stale test count turned into a sweep, because the count was not the
only number restated by hand and left behind.

**The explanation lift, in five places.** `README.md`, `traceability.md` and
`what-measuring-found.md` all carried 1.11 for Grad-CAM and 1.63 for occlusion.
The artefacts say 1.1587 and 1.6058. The 1.63 was worse than stale: it is the
figure from the *development* split, quoted beside the sentence "over the 58
masked TB radiographs", which is the `all` split. Two different measurements
had been spliced into one claim. Corrected to 1.16 and 1.61 throughout, read
from `gradcam-block_13_expand_relu-all-tb_evaluation.json` and
`occlusion-p32s16-all-tb_evaluation.json`.

**The region ablation.** `traceability.md` and the model card quoted intact
0.8625, lungs 0.7884, surroundings 0.5453, described as "all 138 Montgomery
images". The committed artefact holds 0.8241, 0.7870 and 0.4259 over 21. The
difference is not a drift but a method: `evaluate_shortcuts.py` restricts the
region test to the test split, and the 138-image run from 17 October (recorded
above) includes images the model trained on. The 21-image figure is the
defensible one even though it looks weaker, and the surroundings number is
stronger evidence anyway — 0.4259 is below chance, not "a little above" it.
Worth noting the intact figure the docs carried, 0.8625, is the cross-dataset
AUC from a different experiment entirely.

**Response time.** `traceability.md` said median 5.97s and p90 6.43s;
`response_times.json` says 6.24 and 6.90. Both pass NFR-01.

**Test counts.** 257 in the README, 220 in traceability, 67 in a verification
command, 29 in the demo runbook. All 365. `docs/test-record.md` was itself
stale at 196 and has been regenerated, which is the whole reason it is
generated.

**The demo runbook was the worst of it**, because it is read aloud. Its script
quoted AUC 0.891, sensitivity 0.949 and specificity 0.508 against the true
0.9291, 0.9153 and 0.6393, and claimed a threshold chosen for 90 per cent
sensitivity when it was chosen for 92. It also had no section on the live
release, which is the Sprint III requirement.

**The pattern.** Every one of these is a number copied into prose at the moment
it was measured and never read again. The model performance page and the case
report had the same defect on 2 November and were fixed by reading the
artefacts at render time. Prose cannot do that, so prose should carry fewer
numbers and more pointers. Two generators that write committed files,
`build_test_record.py` and the new `learning_curve.py`, now write LF endings
explicitly, so regenerating one no longer produces a diff that is entirely line
endings and no longer trips the pre-commit hook.

**Also closed:** the traceability gap "No deployed release over HTTPS". The
release has been live on Azure Container Apps since 3 November and `/health/`
answers 200. The row was still describing the blocker that had been removed.

## 4 November 2026 — rebuilding the interface to the wireframes

The Figma wireframes for Chapter 4 arrived, and the application did not look
like them. They describe a clinical workspace: a fixed navigation rail, a
header carrying the breadcrumb and the signed-in identity, white panels on a
pale blue ground, and the score shown as a figure beside its threshold scale
rather than as a gauge. What was there was the opposite — a dark olive ground,
a condensed uppercase display face, an acid accent and a top masthead. A report
whose wireframes disagree with its screenshots invites the obvious question,
so the application moved rather than the drawings.

**What this actually changed.** The stylesheet was rewritten around two sets of
custom properties: the lit workspace and a reading room, the second because
films are read with the lights down and a bright interface beside a dark film
is the usual complaint. Nothing below the token block names a colour, so the
two cannot drift. The interface face is now IBM Plex Sans, which was already
vendored and unused; it was drawn for technical interfaces and holds at the
sizes a worklist needs.

**Three things the wireframes showed that did not exist**, and were built
rather than faked. The dashboard's four tiles — screenings this month, high
suspicion rate, pending review, clinical agreement — are computed in the view
over denominators the tile states, because a percentage over nine decided cases
is not a performance claim and a tile that hides the denominator invites it to
be read as one. The worklist gained a search, a triage filter and an ordering.
The case archive gained a decision filter and a date range, and the CSV export
now shares one `filter_cases` function with the page, so a download cannot
quietly cover a different span from the table it came from.

**The reveal animation is gone.** `.rise` held `opacity: 0` and a scroll
observer lifted it; the figures counted up from zero. For a clinical readout
that is backwards — it should be correct the instant it paints. The test that
guarded the old narrowing was rewritten to assert nothing hides content at all,
which is the stronger claim.

**Two defects found while checking, neither of them cosmetic.**

The account-closing confirmation never ran. `profile.html` carried a literal
newline inside a JavaScript string — the same backslash mangling that damaged
the artefact writers on 3 November — so the script threw a `SyntaxError` on
parse and `window.confirm` was never reached. The typed-address check on the
server still held, so the account could not be closed by accident, but the
second guard had been silently absent.

The rail reintroduced the sideways scroll NFR-10 forbids. Below 1100 pixels the
rail lies down as a strip, and the grid declared its content column `1fr`. A
bare `1fr` track will not go narrower than its widest content, so the strip
pushed every page to 966 pixels at a 375 pixel viewport — the exact defect the
masthead had in October, reintroduced by the thing meant to prevent it.
`minmax(0, 1fr)` fixes it. Measured afterwards at 375, 1024 and 1280: every
page fits.

**`--ink-dim` moved again**, from `#85907e` to `#5f6e8b`, because on white it
measured 4.29:1 where AA asks 4.50 and on the sunken table header 4.47. The
test that caught the last two moves named the hex it expected, which only
records which colour was current when it was written; it now computes the
contrast ratio for both themes against both grounds, so it will catch the next
one too.

Verified by walking every page in a browser at three widths and in both
themes, screening a real test-split film end to end, and checking the chain
verification, the explanation build and the printed report. 365 tests pass.

## 4 November 2026 — the two pages the redesign had missed

Asked whether everything had been redesigned, and checking rather than
answering turned up two places where it had not.

**The account pages have never been framed.** `/accounts/email/` and
`/accounts/3rdparty/` rendered allauth's raw markup — bare headings, bare
buttons, a bare input — floating inside the application shell with no panel
around it. The cause is a block-name collision: `allauth/layouts/base.html`
called its frame `content`, and every allauth page it wraps defines a block
called `content` too, so the leaf won and the frame was discarded. The
`manage.html` shim written to route around this could not work either, because
it also defined `content`. `screening/base.html` now has an outer `body` block
for a layout that needs to wrap a page rather than be one, the account layout
fills that, and `content` is left free for the page inside it.

The two tests covering these pages both passed throughout. They asserted
`screening/base.html` was in the template chain, which it was: the rail, the
header and the footer were all present. What they could not see was that the
panel between them was gone. The new test looks for the page's own heading
*inside* the panel body, and was checked against the broken layout to make
sure it fails there.

allauth's markup carries no classes, so the elements themselves are styled
inside the one `.allauth-body` wrapper rather than forking a dozen templates.

**Onboarding was the wrong shape.** The wireframe draws "Complete your
profile" as a single centred card with its own slim top bar; it had been built
as the two-column gate the other sign-in pages use. It is a form to fill in
rather than a decision to make, and the fields read better in one column.
`account/base_auth.html` gained a `frame` block so a page can replace the gate
instead of fighting the grid from inside it.

That page only appears partway through a provider sign-in, which cannot be
driven locally, so it was rendered outside its flow with the same form and the
same template and served from the dev server to be looked at. The card measures
640 pixels at 1440, as drawn.

**Count:** of the eleven wireframes, ten were already built as drawn and the
eleventh is now. Six templates were never touched by the redesign; four of
them inherit the system and were checked in a browser, and the other two were
these.

## 4 November 2026 — a sweep for errors, and the five it found

Asked to find and fix everything while nobody was watching, so the checking
was done by machine where a machine can check and by eye where it cannot: a
breadth sweep over every URL as every role against records in awkward states,
an overflow measurement at three widths in both themes, a contrast audit of
every text-on-background pair, and a console read on every page.

**A null byte in a search box returned 500.** `/cases/?reference=%00` carried
the byte into an icontains filter; PostgreSQL refused it, correctly, since a
text column cannot hold one. The same value was on its way into the access
trail's detail field. Every other route for free text goes through a form, and
Django puts a null-character validator on every `CharField`, so the forms were
already covered — a query parameter never meets a form. The three search boxes
now clean what they are handed, dropping unprintable characters and capping the
length, and four tests cover it.

**Toggling the theme on the dashboard threw.** The repaint walked both charts
setting axis colours, and a doughnut has no axes. Chart.js still hands it an
`options.scales` object, so testing for that was not enough: reading `.x.border`
off it threw on every theme change, and the bar chart's gridlines stayed painted
for the side the interface had just left.

**A failed explanation left the comparison panel building for ever.** The
occlusion map is produced in the same pass as Grad-CAM, so it cannot arrive on
its own, but the panel was only hidden on the success path. A case whose image
had gone showed "Building the comparison" for as long as the page stayed open.

**The signed-out 404 claimed there was no model.** The rail reports a file
check that only runs for a signed-in user, and the template read the absent
value as a negative answer, so a visitor was told "No model on this machine" on
a machine that had one. A rail that states the opposite of the truth is worse
than one that stays quiet.

**The amber triage chip measured 4.42:1** against its own background, where AA
asks 4.5 for text under 24px. It looked perfectly readable, which is the point:
these are not failures anybody spots by looking. The contrast test now covers
all sixteen text-on-background pairs in both themes rather than the one colour
that had failed before, and the primary button's label on its own fill.

**Also:** keyboard focus is now declared for every control in one rule. The
buttons had a ring, but several of the resets here remove the browser's own
outline, and nothing had replaced it for plain links.

What the sweep did not find is worth recording too: no horizontal overflow on
ten pages at 375, 1024 and 1440 in both themes; no unrendered template syntax,
no broken images and no other console errors; every awkward record state —
degraded quality, a failed explanation, a missing image file, the longest
reference the column allows, a case at another clinic — renders correctly.

## 4 November 2026 — closing the list, and the error check I had not finished

Asked what was outstanding, checked rather than answered from memory, and the
checking found more than the answer would have.

**The live deployment was still serving the old interface.** Every push since
the redesign built an image and skipped the deploy: the step is gated on
`vars.AZURE_DEPLOY == 'true'`, which is not set on the repository. Nothing in
the repository can fix that, and this machine has neither `gh` nor `az`
installed, so it is handed back with the two steps it needs.

**`docs/user-guide.md` described an interface that no longer exists** — Screen
in the top navigation, Analyse radiograph, Cases. All three were renamed by the
redesign. It now also documents the rail and the reading-room control, which
nothing did.

**The runbook said "Click Cases"**, and the rail says Case list. One line, read
aloud.

**HTTPS is now forced behind the proxy flag**, with the one exemption that
makes it safe: the platform's health probe reaches the container directly
rather than through the ingress, so it arrives without `X-Forwarded-Proto` and
Django would answer it 301. A redirect is not a healthy response, so the
hardening would have taken the site out of service. `SECURE_REDIRECT_EXEMPT`
covers `^health/$` and nothing else, and three tests hold that line. HSTS is an
hour rather than the customary year, because a year is the hardest thing on
that list to undo; `includeSubDomains` and `preload` are refused outright and
silenced with their reasons, since this runs on a shared platform domain and
speaking for its siblings is not this application's business.

**The comparison panel is now hidden unless there is a map to show.** The
earlier fix added a call to hide it on the failure path, which left the
burden on every future path to remember. Inverting the default removes the
burden: forgetting now leaves the panel hidden rather than leaving it saying
"Building the comparison" for ever. Three tests cover the three states.

**And the error check I had reported as done was not.** Pages, roles, layout,
contrast and console had been swept; the routes that change something had not.
A second sweep exercised every POST in every role — reviews valid, empty,
malformed and forbidden; profile saves including a nonexistent clinic; the data
export; closing an account with the wrong address; signing in with an address
that is empty, malformed, four hundred characters long, or carrying control
characters; the explanation and trail endpoints by the wrong method and with no
session; and every admin page for every model as a superuser. Nothing was
found, which is worth recording precisely because the first report of "no
errors" had not looked here.

The two management commands were run: the audit chain verifies over 414 rows,
and `prunemedia` reports 78 orphaned files holding 113 MB, left by records
deleted over the life of the project. It is a dry run until `--delete`, and
that is the operator's call rather than mine.

## The same film twice

Found by walking the upload page rather than by reading it. A radiograph
dropped on the panel was appended to the queue, so dragging the same file
twice queued it twice, screened it twice, and produced two records under two
references. A clinician then has two cases to decide for one chest.

What made it hard to see is that identity here cannot be the filename. This
system stores a radiograph under its case id, so the same film saved out
twice carries two unrelated names; comparing names finds nothing wrong with
either. The check has to read the bytes. It now does, in two places: the
queue hashes each file with `crypto.subtle` before adding it and says which
file it skipped and why, and the upload view hashes each file of a batch and
rejects a repeat against the reference it repeats. A check that only runs in
the browser is not a check, and the server had none at all.

The guard is scoped to one submission. The same film arriving again next
month is a follow-up, not a mistake, and a test holds that distinction.

**The suite could not have caught this, and said the opposite.** `make_image()`
built identical pixels on every call, so `test_three_images_create_three_records`
was handing in one film under three names and asserting that three records came
back - the exact behaviour now being removed, written down as correct. The
fixture derives its base tone from the filename: the same name still gives the
same image on every run, and two names never give the same one. Six new tests
cover the guard, and four of them were confirmed to fail with it disabled.

Worth recording how this got past a sweep that reported no errors. The sweep
drove the server over HTTP and never dropped a file on the page, so a defect
living entirely in a drag handler was outside everything it touched.

Counted across `media/uploads/`: 62 files holding 37 distinct images, two of
which account for 22 files on their own. Scored across those 37, the model
spans 0.0016 to 0.9999 and fills the middle, which is the answer to whether
identical scores meant a collapsed model. They meant identical inputs.

## Moving the code to meet the document, rather than the other way round

Reading the approved proposal against the running system turned up four
divergences. Two of them were mine to fix in code; the other two are the
document's to correct.

**NFR-08 asks that every result be displayed with its heatmap**, so that no
prediction reaches a clinician without the picture that produced it. The
explanation was being built when a case was first opened, which meant the
result page arrived saying "building the explanation" - a requirement about
what is displayed is not met by a page that will display it shortly. The
obvious response was to reword NFR-08. The better one was to notice that
deferring is only needed for a batch: an occlusion map is several hundred
forward passes, and twenty of them would spend minutes on images nobody has
opened, but one fits inside the ten seconds NFR-01 allows, and the measured
6.24 second median already included building it. A single screening now
builds its map before the redirect; a batch still defers. The build moved
into `build_explanation`, called by both paths, so there is one implementation
rather than two that drift.

One existing test failed on this, correctly: it asserted that the map is built
on first view, which was true when it was written and is the behaviour that
changed. Rewritten to fail where the failure now happens, with a second test
added for the deferred path, because the two now fail in different places.

**NFR-06 and NFR-07 contradict each other** and no code resolves that. NFR-06
says a record is stored only after both inference and heatmap succeed; NFR-07
says a failed heatmap must leave the prediction standing, which requires the
record to exist. The implementation follows NFR-07, since losing a valid
screening to a failed picture is the worse outcome, and records the
explanation's state explicitly so nothing points at a file that was never
written. NFR-06 needs rewording to say that.

## "Pending review" was offered as a decision

The review dropdown was built from the model's status choices unfiltered, so
its first entry - and therefore its default - was "Pending review". A
clinician who typed a note and submitted recorded a review that decided
nothing and left the case in the queue, while the audit trail logged that a
review had been recorded.

It had happened three times on one case during a walkthrough before anyone
noticed, and a case sitting at 0.9758 with a clinical note on it was still
pending. In a clinic the reviewer would believe they were finished.

Pending is the state a case arrives in, not a judgement anybody reaches. The
choices are now the two real decisions, the field opens on nothing so there is
no careless default to land on, and the server refuses a crafted submission
that sets a case back to pending. Seven tests, four of which were confirmed to
fail with the guard removed.

## Measuring what it costs to run, not only what it can detect

The proposal answers low-resource deployment in section 2.3.3 with a GPU-free
design and a lightweight network. Those are reasons to expect the claim to
hold. They are not evidence that it does, and the chapter had nothing behind
them beyond the model being small. Four measurements now sit in the artefacts
directory and on the performance page, which already reads its figures at
request time.

**On one processor core**, pinned with `cpu_affinity`, a complete screening
takes a median of 10.93 seconds over 30 runs, with a peak of 1,331 MB. Only 4
of the 30 come in under the ten seconds NFR-01 allows, where the requirement
asks for nine in ten. So the system fits inside 2 GB on a single core and
misses its own latency requirement there, and the page says both rather than
the better of the two.

**The packaged build** answers 2.05 seconds after launch, occupies 1.32 GB,
and - the figure that matters - fetches from **zero** outside hosts. Fonts,
stylesheets, scripts and the chart library are all local.

**One screening moves 11.68 MB**: 4.96 MB up and 6.86 MB of radiograph and
maps back. The interface itself is 505 KB and only on the first visit. The
lever on a slow connection is image size; nothing in the interface comes
close.

**Hosting is free at any volume a clinic would produce.** At 100 screenings a
day the application is active 5.8 hours a month and uses 11.7 per cent of the
platform's published free grant; the grant covers about 28,500 screenings a
month. Keeping one replica running permanently would be 14.4 times the grant,
which is the measured case for scaling to zero rather than an assertion about
it. No currency figure is given, because published rates change and differ by
region while the grant settles the question a facility actually asks.

### Two measurements that were wrong first

**The first single-core figure was 15.4 seconds and it was contention.** The
packaged build was loading on the same machine while the timing ran. Pinning a
process to one core does not stop another process competing for memory
bandwidth and disc. Re-run alone it is 10.93.

**The offline build appeared to hang for ten minutes and did not.** Two
versions of the harness read its console through a pipe, and the build sat at
"Preparing the database" without ever answering; it was close to being written
up as a defect in the deliverable. Started the way a person starts it, with
its output going to a file, the same build answers in two seconds. The harness
now finds the port by asking the operating system which one the process is
listening on, and the comment in the script says why.

**And the first offline check reported 36 external hosts.** Every one was a
bug tracker in a code comment, a line of licence text, or the w3.org namespace
that every SVG declares and nothing requests. A number that counts those is
true and useless. The check now looks only where a browser is actually made to
fetch - src, stylesheet links, CSS url() and @import, fetch calls, form
actions - and counts hosts behind an anchor separately, because a link
somebody has to click is not something the page loads. The answer is zero.

## A figure that no script owned

`explanation_side_by_side.png` is the worked example: one radiograph, the
Grad-CAM map, the occlusion map. It is the figure most likely to end up on a
slide and be asked about, and until now it was the only figure in
`ml/artifacts/` that no script produced. It had been assembled by hand in
October and left there.

Two faults, from the one cause.

**The numbers on it were from a superseded run.** It printed lift 1.11 beside
the Grad-CAM panel and 1.63 beside the occlusion panel. The sweep on 4
November corrected those two values in `README.md`, `traceability.md` and
`what-measuring-found.md`; it could not correct them here, because they were
pixels. A number drawn into an image does not turn up in a grep, which is the
whole argument for not drawing numbers into images by hand.

**Worse, they were the wrong kind of number.** 1.11 and 1.63 are *dataset
means* - and from the development split at that, where the occlusion settings
were chosen. They were printed beside a *single film*, where every reader will
take them for that film's values. They are not. The film shown is
`MCUCXR_0104_1`, and its own lifts are **1.74 for Grad-CAM and 2.18 for
occlusion**. The figure was stating one thing and inviting the reading of
another.

`ml/scripts/plot_explanation_example.py` now draws it. What changed:

- Both maps come from the application's own generators and are drawn by the
  application's own renderer, so the figure shows what the system produces
  rather than a second implementation that could drift from it.
- Each panel is labelled **lift on this film**, and the dataset means sit in
  the footer labelled as means over all 58 masked TB films, with the paired
  difference, its interval, and the fact that the interval on the 9 held-out
  films includes zero. The two quantities can no longer be confused.
- The hand-drawn lung boundary is traced on both heatmap panels. Lift is the
  share of the highlight falling inside that line divided by the share of the
  frame the line encloses, so with the line drawn the figure shows its own
  arithmetic instead of asserting a ratio.
- The script recomputes each lift and compares it against the value the
  evaluation run recorded for the same film. If they disagree by more than
  0.01 it refuses to write the figure and says which artefact to re-run.
  Tested by perturbing a stored lift: it exits and writes nothing.

The film is unchanged - `MCUCXR_0104_1`, Montgomery, test split, confirmed TB,
scoring 0.8395. Keeping it matters: choosing a new film after seeing which one
flatters the method is how a figure stops being evidence, so the film is a
flag rather than a default and the default is the one that was always there.

One thing checked and deliberately left alone: `explanation_methods.md` also
carries 1.11 and 1.63. Those are correct there. That table is measured on the
49 development films and says so in its own header, and 1.63 is
`occlusion-p32s16-development-tb_evaluation.json` read accurately. The error
was never in the development table; it was in quoting the development figure
where the all-split figure belonged.

## A sweep of the whole system before the defence

Not a feature, an audit: every page, route, command, script and stored row
checked for anything that would misbehave in front of an examiner. Most of it
came back clean, and the three things that did not were worth the pass.

**The test suite was writing into the real media folder.** Eleven test classes
carried `@override_settings(MEDIA_ROOT=...)` and four did not, so every run
left twenty-two radiographs and heatmaps in the directory holding real
screenings. 291 files and 166 MB had collected that way. Nothing ever failed,
which is why it lasted: a test that writes to the wrong directory still
passes, and only `prunemedia` counting orphans brought it to light.

Redirecting per class was the wrong mechanism, because it has to be remembered
on every class anyone adds later and twice it was not. `config/test_runner.py`
now redirects `MEDIA_ROOT` for the whole run, which covers classes that have
not been written yet. `MediaIsolationTests` asserts the redirect is actually
in force; with the runner removed it fails, so the protection is tested rather
than assumed. Verified by counting the directory before and after a run:
twenty-two files before the change, zero after.

That change broke `test_media_lives_beside_the_database`, which compared the
two live settings. The comparison only ever showed they happened to be equal
in that process. It now sets `TB_DATA_DIR`, reloads, and asserts `MEDIA_ROOT`
follows it, which is the packaging property the test was named for and is
immune to a test-time override.

**Seventeen of thirty-nine records were still showing "building the
explanation".** A batch upload defers its maps on purpose - an occlusion map
is several hundred forward passes and twenty of them would spend minutes on
images nobody has opened - and builds each one when its case is first opened.
Correct for throughput, and the wrong state for a worklist about to be shown
to somebody, because an unopened case displays the notice where NFR-08 asks
for the picture. Opening seventeen cases by hand is not a procedure, so
`manage.py buildexplanations` exists: it builds every pending map, takes
`--dry-run`, `--retry` and `--limit`, and counts a failure rather than
abandoning the run. All seventeen built, 106 seconds, none failed.

**The worklist opened on fifteen demonstration rows.** Five identical copies
of DEMO-001 at 0.9758 from the duplicate-upload defect fixed earlier, plus
`demo`, `demo 01`, `Demo-005` and the rest, all waiting twenty-six days at the
top of the clinical worklist. The twenty-four KNH-26-00xx cases underneath
read as a real caseload. Removed with the images they referenced, then the 291
orphans with `prunemedia --delete`.

### What the sweep found nothing wrong with

Worth recording, because an audit that only lists faults does not say what was
checked.

- `manage.py check` clean; `check --deploy` clean under the production flags,
  with the two HSTS warnings silenced deliberately and the reason in settings.
- No missing migrations; all sixteen applied.
- `ruff check` and `ruff format` clean over 63 files.
- Every URL resolved as every role: anonymous redirects to sign-in on all
  fourteen protected pages, all three roles get 200 on all of them, and the
  two 405s are the POST-only endpoints.
- No JavaScript console error on any page.
- Every `{% url %}`, `{% include %}`, `{% extends %}` and `{% static %}`
  reference resolves; 140 static files collect.
- The audit chain verifies: 698 rows, intact.
- Both dashboard charts carry the right labels and data, read back out of
  Chart.js rather than read off a screenshot.
- Every figure on the performance page matches the artefact it is read from.

### And one instrument that damaged what it measured

Checking that each `ml/scripts` file still loads, I ran every one with
`--help`. Eleven of them do not use argparse, so `--help` is an ignored
argument and the script simply runs: `metrics.json`,
`architecture_comparison`, two benchmark artefacts and `test_predictions.csv`
were overwritten before the sweep was stopped, and nine stray `BENCH-` records
were left in the database. All reverted from git, the records removed.

The same lesson as the offline benchmark that appeared to hang: a check has to
be read for what it does to the system, not for what it is meant to ask. The
import check is now static - it parses each file and resolves the imports
without executing anything.
