# What was built

An inventory of the system as it stands, with the figure each claim rests on.
Every number here is read from a committed artefact under `ml/artifacts/` or
counted from the repository, and the file that holds it is named so a reader
can check rather than take it on trust.

Totals: **17,370 lines of Python** across 79 files, **407 tests** in 58
classes, 25 templates, 16 migrations, **75 committed measurement artefacts**,
15 engineering documents, 134 commits.

---

## 1. Data pipeline

- Two public chest radiograph sources combined into one manifest: Montgomery
  (138 films, with hand-drawn left and right lung masks) and Shenzhen.
  **800 images** in total, split into train, validation and test and recorded
  in `splits.csv` with a SHA-256 prefix, so a later run can prove it used the
  same data.
- Preprocessing is one module (`ml/preprocessing.py`) shared by training,
  evaluation and the running application, so a film is prepared identically
  wherever it is scored. A test asserts that equivalence rather than assuming
  it.
- **The test split is held out from model selection as well as training.**
  Thresholds and the explanation settings were both chosen on validation or on
  a development split, so the reported figures were not tuned against.

## 2. Screening model

- MobileNetV2 transfer learning, two-stage schedule, 60 base layers unfrozen
  at 1e-4, light augmentation, dropout 0.5, weight decay 1e-4.
  **2,435,393 parameters, 26.0 MB on disk.**
- **Five training variants** were run and compared (`experiments.csv`):
  baseline, no-aug, light-aug, deep-tune and reg-both. `reg-both` was
  promoted.
- Held-out test results, with 95% confidence intervals from **2,000 bootstrap
  resamples** (`metrics.json`):

  | | Value | 95% CI |
  |---|---|---|
  | AUC | 0.9291 | 0.878 – 0.970 |
  | Sensitivity | 0.9153 | 0.839 – 0.983 |
  | Specificity | 0.6393 | 0.509 – 0.758 |
  | Accuracy | 0.7750 | 0.700 – 0.850 |

- Decision threshold **0.102**, high-suspicion **0.546**, chosen on validation
  to reach 92 per cent sensitivity rather than the WHO minimum of 90, because
  a missed case costs more than a false alarm in screening. That margin earned
  its keep: sensitivity fell to 0.9153 in transfer, so a threshold set at
  exactly 0.900 would have landed below the requirement.

## 3. Explainability

- **Grad-CAM**, read from `block_13_expand_relu` (14×14) rather than the final
  convolutional layer (7×7), because the final layer measured worse.
- **An occlusion map** beside it, patch 32 stride 16, which covers each region
  in turn and re-scores the image, so its bright areas are the ones the score
  actually depended on.
- **Score-CAM was built, measured and rejected** at a lift of 0.26, below
  chance. The module is kept so the comparison can be re-run.
- Both maps are scored against Montgomery's hand-drawn lung masks, where a map
  thrown at the radiograph at random scores 1.00. Grad-CAM **1.16**, occlusion
  **1.61**, paired difference **+0.447, 95% CI [0.125, 0.780]**, higher on 42
  of 58 films. On the 9 held-out films the interval includes zero, and that is
  stated rather than hidden.

## 4. Triage

- Every score is turned into LOW, MEDIUM or HIGH with a **written
  justification naming the thresholds used**, so a band is explained rather
  than asserted.
- Each record stores the model version and the thresholds it was judged under,
  so a result from last month stays interpretable after the thresholds change.

## 5. Web application

Django 5.2 and PostgreSQL 17, 25 templates, 18 routes.

- Single and batch upload with a drag-and-drop queue that **de-duplicates by
  content hash** in the browser and again on the server, so the same film
  cannot be screened twice in one batch under two names.
- Image quality gate (blur and brightness) before scoring; a film that fails
  is listed with its reason and is not scored.
- Result page: score gauge, triage band with justification, threshold scale,
  the radiograph and the Grad-CAM map side by side, the occlusion map beneath
  with the lung-mask measurement, the full provenance record, and the review
  history.
- Clinical worklist ordered by urgency then waiting time, with filters and
  search; case archive with CSV export; printable case report that changes
  type once a case has been reviewed.
- Dashboard with screening volume, triage distribution, high-suspicion rate
  and clinician agreement.
- **Model performance page** that reads every figure from the evaluation
  artefacts at request time, so a number on screen cannot drift from the run
  that produced it, and that publishes its own limitations.

## 6. Security and governance

- **Three roles** — radiographer, clinician, administrator — enforced on the
  server, not only in the template. A radiographer who bypasses the form and
  POSTs a review is refused.
- **Facility scoping**: a clinic sees its own caseload and no other.
- **Hash-chained audit trail.** Every view, list, screening, review, refusal
  and export is recorded, each row hashing its own contents together with the
  hash of the row before it. Altering or removing a row breaks every hash
  after it. Verifiable from a button in the interface and from
  `manage.py verifyaudit`. **The chain is what makes the log evidence rather
  than a list**, and the page says plainly that it detects alteration rather
  than preventing it.
- **Passwordless sign-in**: six-digit email codes, Google and GitHub. The
  system never receives or stores a password.
- EXIF and GPS metadata stripped from every upload before storage.
- **Data Protection Act 2019**: a machine-readable export of a user's own
  data, and account closure. Both state their limits — the export excludes the
  radiographs, and closing an account does not delete clinical records or
  audit rows, because a log somebody leaving could empty would answer nothing.

## 7. Deployment

- **Containerised and deployed** to Azure Container Apps, live, with a health
  endpoint reporting database and model status.
- **A packaged Windows build** that runs with no Python, no database server
  and no network: 1.32 GB on disk, **2.05 s from launch to first answer**, and
  **zero external hosts** named by anything it serves.
- Continuous integration on every push: migrations, linting and the full test
  suite.
- A one-click launcher for local use, and a backup script to Google Drive.

## 8. Measurement studies

The part of this project that is least like a prototype. Each is a separate
experiment with a committed artefact.

| Study | What it answers | Result |
|---|---|---|
| `compare_architectures` | Is MobileNetV2 the right size? | ResNet50 scores **+0.0359 AUC** higher and is 9.8× the size. The smaller model was chosen and the cost is stated rather than hidden |
| `learning_curve` | Is 800 images the binding constraint? | **12 runs**, 25/50/75/100 per cent of the training split, three seeds each |
| `cross_dataset` | What does changing hospital cost? | AUC 0.9336 within source, **0.8625 across** — a drop of 0.0711 |
| `evaluate_shortcuts` | Does it read the lungs or the markers? | With the lungs blanked AUC falls to **0.5453**, near chance. Causal, not correlational |
| `evaluate_calibration` | Is the score a probability? | **ECE 0.1018**, systematically underconfident. This is why nothing in the interface calls it a confidence |
| `evaluate_explanations` | Do the maps point at the lungs? | Lung-mask lift for Grad-CAM, occlusion and Score-CAM |
| `compare_explanations` | Is the difference real or noise? | Paired bootstrap, **+0.447 [0.125, 0.780]** |
| `select_thresholds` | Where should the cut-off sit? | Chosen on validation, with the sensitivity margin argued |
| `benchmark_constrained` | Will it run on one core? | Median **10.93 s**, peak 1,332 MB. **The requirement is missed on the minimum machine and that is reported** |
| `benchmark_offline` | Does it work with no internet? | 2.05 s cold start, **0 external hosts** |
| `benchmark_bandwidth` | What does it cost on a slow link? | **11.68 MB** per screening, interface 505 KB once |
| `benchmark_cost` | What does hosting cost a clinic? | Free to about **28,461 screenings a month** |
| `measure_screening_time` | Is it fast enough? | Median **6.24 s**, p90 6.90 s over 50 runs — within the 10 s requirement |

## 9. Testing

- **407 automated tests in 58 classes, all passing**, covering valid and
  invalid uploads, oversized files, unsupported types, batch behaviour and
  duplicate rejection, quality thresholds, triage boundaries, preprocessing
  equivalence, authentication, role permissions, review attribution, metadata
  stripping, the audit chain detecting its own alteration, and the failure
  scenarios the Build Phase notes enumerate.
- The suite runs on every push.
- A test asserts that the suite itself cannot write into the real media
  folder, after a defect that did exactly that for most of the project.

## 10. Documentation and repository

15 engineering documents, including a development log recording decisions and
the measurements that settled them, a requirements traceability matrix, an
operating-point note, deployment guides for Azure and for the packaged build,
a demonstration runbook, a user guide, and three sign-in setup guides.

134 commits with the reasoning in the messages.

---

## Deviations from the proposal, and why

- **The explanation shown is Grad-CAM, as SO4 specifies, with an occlusion map
  beside it.** Grad-CAM measured barely above chance on lung concentration.
  Removing it would leave the objective unanswered; showing it without the
  measurement would overstate it. Both are shown, with the figures.
- **Score-CAM was built and rejected on measurement**, not on preference.
- **No Kenyan radiographs were used.** The approved proposal excludes Kenyan
  clinical data from scope, and no public Kenyan chest radiograph dataset was
  available. The performance page states that no Kenyan equipment was tested.
- **Specificity is 0.6393 against the WHO target of 0.70.** The validation
  curve showed no threshold satisfying both targets on this data, so the
  system over-refers by design and says so.
- **On a single processor core the ten-second requirement is missed**, at 4 of
  30 screenings inside the limit. It is met on the recommended machine. Both
  are reported rather than the better of the two.
