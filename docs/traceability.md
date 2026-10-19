# Objective traceability

Sprint III asks for "a traceability record connecting each objective or requirement
to its implemented component, test or evaluation, result and supporting evidence",
and for any unmet requirement to be explained honestly. This is that record.

Objectives are quoted from the approved proposal, section 1.4. Every file path is
relative to the repository root and every figure named here exists in it.

---

## SO1 — Analyse the current TB screening process in resource-constrained settings

> "To analyse the current tuberculosis screening process using chest X-ray images
> in resource-constrained healthcare settings."

| | |
|---|---|
| **Type** | Literature and context. Not a software deliverable. |
| **Where** | Chapter 2 of the report. |
| **Evidence in this repository** | The WHO target product profile for a TB triage test, at least 90% sensitivity and 70% specificity, is the requirement the operating point is selected against. `ml/scripts/select_thresholds.py` encodes it and `ml/artifacts/OPERATING_POINT.md` reports the result. |
| **Status** | Addressed in the report. Its consequence for the build is traceable to the threshold. |

---

## SO2 — Study existing computer-aided detection systems

> "To study existing computer-aided detection systems used for tuberculosis
> screening and identify their strengths and limitations."

| | |
|---|---|
| **Type** | Literature. Not a software deliverable. |
| **Where** | Chapter 2 of the report. |
| **Evidence in this repository** | `ml/artifacts/architecture_comparison.md` compares four architectures under identical conditions, which is the implementation-side counterpart to the literature comparison. |
| **Status** | Addressed in the report. |

---

## SO3 — Identify gaps in current AI-based TB screening systems

> "To identify gaps in current AI-based tuberculosis screening systems, especially
> in explainability, image quality handling, triage support, and record keeping."

Four named gaps. Each one is answered by a component below, and SO3 is the reason
each of them exists rather than an afterthought.

| Named gap | Answered by |
|---|---|
| Explainability | `screening/services/gradcam.py`, measured by `ml/scripts/evaluate_explanations.py` |
| Image quality handling | `screening/services/quality.py` |
| Triage support | `screening/services/triage.py`, thresholds from `ml/scripts/select_thresholds.py` |
| Record keeping | `screening/models.py`: `PredictionRecord`, `ReviewNote`, `Profile` |

---

## SO4 — Develop the web-based screening and triage system

> "To develop a web-based system that uses deep learning to screen chest X-ray
> images for likely pulmonary tuberculosis and display supporting information such
> as confidence score, triage level, Grad-CAM heatmap, image quality warning, and
> clinician notes."

Six components are named. Each is traced separately, because the objective is met
only to the extent that each one is.

### 4a — Screen chest X-ray images with deep learning

| | |
|---|---|
| **Implemented in** | `ml/scripts/train_model.py`, `screening/services/predict.py`, `ml/preprocessing.py` |
| **Tested by** | `UploadTests.test_upload_records_a_real_prediction`, `PreprocessingTests` (6 tests) |
| **Result** | MobileNetV2 transfer learning. **Test AUC 0.9291, 95% CI [0.878, 0.970]**. Inference about 120 ms on CPU. |
| **Evidence** | `ml/artifacts/metrics.json`, `roc_curve.png`, `model_report_reg-both.md` |
| **Status** | **Met.** |

`ml/preprocessing.py` is imported by both the training scripts and the web
application, so the pixels the model is served cannot drift from the pixels it was
trained on. `PreprocessingTests.test_scaling_matches_keras_preprocess_input`
asserts that equivalence.

### 4b — Display a score

| | |
|---|---|
| **Implemented in** | `screening/templates/screening/case_detail.html`, `PredictionRecord.tb_probability` |
| **Tested by** | `UploadTests.test_upload_stores_the_model_and_thresholds_used` |
| **Status** | **Met, with a deliberate deviation from the proposal's wording.** |

The proposal says "confidence score". The interface says **model score**. The
deviation is intentional, and it is now measured rather than assumed.

`ml/scripts/evaluate_calibration.py` on the validation split: **expected
calibration error 0.1018**, worst populated bin off by **0.3498**. The model is
systematically **underconfident** — images scoring around 0.24 are actually TB
56% of the time, and every one of the ten bins below 0.5 understates the true
rate. Brier score 0.1302 against 0.2500 for predicting the base rate alone, so
the score is informative; it is simply not a probability.

Calling 0.0032 a "0.3% confidence" would therefore have been wrong by a
measurable margin, not merely imprecise. Evidence:
`ml/artifacts/calibration.json`, `calibration.png`. Calibrating the score, by
Platt scaling or isotonic regression fitted on validation, is future work.

### 4c — Triage level

| | |
|---|---|
| **Implemented in** | `screening/services/triage.py`, thresholds chosen by `ml/scripts/select_thresholds.py` |
| **Tested by** | `TriageTests` (5 tests, including both boundaries) |
| **Result** | Decision threshold **0.102**, high suspicion **0.546**, both selected on the validation split alone. At 0.102 validation sensitivity is 0.933 and specificity 0.639. |
| **Evidence** | `ml/artifacts/threshold_selection.png`, `OPERATING_POINT.md` |
| **Status** | **Met, with one requirement not reachable.** |

**No threshold satisfies both WHO targets at once.** The best specificity available
at or above 90% sensitivity is 0.689 on validation, against the 0.70 the target
product profile asks for. This is a property of the model on this data, not a
tuning oversight, and is reported rather than worked around.

Every record stores the thresholds it was judged under, so revising them later does
not silently reinterpret historical results.

### 4d — Grad-CAM heatmap

| | |
|---|---|
| **Implemented in** | `screening/services/gradcam.py` |
| **Measured by** | `ml/scripts/evaluate_explanations.py` against Montgomery's 276 hand-drawn lung masks |
| **Result** | **Lift 1.00** reading from `block_13_expand_relu` (14×14), against **0.49** from `out_relu` (7×7), across all 138 Montgomery images. 1.16 on TB cases, 0.88 on normal. |
| **Evidence** | `ml/artifacts/gradcam_evaluation.json`, `gradcam_evaluation_out_relu.json`, `gradcam_lung_concentration.png`, `gradcam_vs_lungs.png` |
| **Status** | **Partially met, and the shortfall is stated.** |

A heatmap is produced for every successful prediction and the failure path is
handled rather than fatal: `PredictionRecord.gradcam_status` records
`GENERATED`, `FAILED` or `NOT_ATTEMPTED`, and a failed heatmap does not discard a
valid prediction.

What is not met is usefulness. A lift of 1.00 means activation falls inside the
lungs about as often as a map placed at random would. Moving from a 7×7 to a 14×14
layer doubled it from 0.49, so resolution was part of the problem and not all of
it. **The heatmap should not be presented as evidence of where the model looked.**

That the model reads the lungs is established instead by occlusion, which is causal
rather than correlational. `ml/scripts/evaluate_shortcuts.py`, on all 138 Montgomery
images: intact 0.8625, **lungs only 0.7884, surroundings only 0.5453**. Removing the
lungs reduces the model to near chance.

### 4e — Image quality warning

| | |
|---|---|
| **Implemented in** | `screening/services/quality.py`, previewed before upload by `screening/templates/screening/upload.html` |
| **Tested by** | `QualityCheckerTests` (6 tests) |
| **Result** | Blur, under- and over-exposure and undecodable files are detected. Thresholds calibrated against 559 training images. Unusable images are rejected with a specific reason; degraded but usable images are screened with a warning. |
| **Status** | **Met.** |

This component is absent from the engineering brief and present in the proposal
(Specific Objective 4, RQ4, RQ5, the class diagram and the schema). It was built
because the proposal governs.

### 4f — Clinician notes

| | |
|---|---|
| **Implemented in** | `ReviewNote`, `Profile`, `screening/views.py:case_detail` |
| **Tested by** | `ReviewPermissionTests` (5 tests), `ProfileTests` (9 tests) |
| **Result** | Notes are append-only, so a case carries a review history rather than one overwritten field. Only a clinician or administrator may record one, enforced on the POST. Notes are attributed to the signed-in user, and survive that account being deleted. |
| **Status** | **Met.** |

---

## SO5 — Test and evaluate the system

> "To test and evaluate the developed system using model performance metrics and
> system testing."

### Model performance

| Evidence | Result | Artefact |
|---|---|---|
| Held-out test AUC with bootstrap CI | 0.9291 [0.878, 0.970] | `metrics.json`, `roc_curve.png` |
| Threshold selection from validation | 0.102 / 0.546, WHO specificity target not reachable | `threshold_selection.png` |
| Architecture comparison, four candidates | ResNet50 0.9478, EfficientNetB0 0.9126, MobileNetV2 0.9119, scratch CNN 0.6108 | `architecture_comparison.md` / `.png` |
| Cross-dataset generalisation | Changing hospital costs **0.071 AUC** (0.9336 → 0.8625) | `cross_dataset.json` |
| Shortcut and occlusion testing | Source AUC 1.000 available, occlusion cost 0.021, lungs 0.788 vs surroundings 0.545 | `shortcut_tests.json` / `.png` |
| Explanation quality | Lift 1.00 against lung masks | `gradcam_evaluation.json` |
| Score calibration | ECE 0.1018, underconfident; not a probability | `calibration.json` / `.png` |
| Overfitting diagnosis | Mild, AUC gap 0.057 | `model_report_reg-both.md` |

### System testing

| | |
|---|---|
| **Implemented in** | `screening/tests.py` |
| **Result** | **92 tests**, covering valid and invalid uploads, oversized files, unsupported types, batch behaviour, quality thresholds, triage boundaries, preprocessing equivalence, authentication, the allowlist, role permissions, review attribution, metadata stripping, and the fifteen failure scenarios the Build Phase notes enumerate. |
| **Automation** | GitHub Actions runs lint, formatting, migration checks and the suite against PostgreSQL on every push. |
| **Record** | `docs/sprint-2-test-record.md` |
| **Failure paths** | A deceptive file, an empty file, a filename attempting traversal, a filename carrying instructions, a corrupt image inside a batch, a failed heatmap, an absent model, an orphaned upload, a lost session, a guessed case id, an unknown case id, a duplicate submission, and the health endpoint under both outcomes. |
| **Status** | **Met for functional and failure testing. Not met for usability testing** — see below. |

---

## Not met, and why

Stated here rather than left to be discovered.

| Gap | Effect on the objectives | Plan |
|---|---|---|
| **No deployed release over HTTPS** | Sprint III requires a working operational release. The system runs only on a development machine. | The blocker is TensorFlow's memory footprint against free-tier limits. A route has to be chosen and provisioned. |
| **No usability testing with representative users** | SO5 says "system testing"; Sprint III asks for usability and failure scenarios with real participants. Functional tests do not substitute. | Needs participants and possibly ethics clearance, which has weeks of lead time. Raise with the supervisor now. |
| **Chapters 5 and 6 not written** | Required for submission. | Evidence exists for every claim; the writing does not. |
| **Grad-CAM lift at chance** | SO3 names explainability as a gap this project addresses. The heatmap does not localise reliably. | Reported as a limitation. The occlusion evidence carries the explainability claim instead. |
| **WHO specificity target not reachable** | SO1's requirement is not fully satisfiable by this model on this data. | Reported as a finding. |
| **Score is not calibrated** | 4b displays a raw score, not a probability. Now measured: ECE 0.1018, underconfident. | Labelled honestly as a model score. Platt or isotonic calibration is future work. |
| **Any signed-in user can open any case** | There is no per-case ownership check. Defensible for shared clinical records, but it is a decision that has not been written down or agreed. | Confirm with the supervisor whether case access should be restricted by facility. |

---

## How to verify any row above

```bash
.venv/Scripts/python.exe manage.py test screening      # the 67 tests
.venv/Scripts/python.exe ml/scripts/compare_architectures.py
.venv/Scripts/python.exe ml/scripts/evaluate_explanations.py --split all
```

Every artefact named here is committed under `ml/artifacts/` and every figure is
regenerated by the script that names it, not edited by hand.
