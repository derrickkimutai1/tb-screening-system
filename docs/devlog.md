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
