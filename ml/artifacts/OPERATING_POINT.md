# Operating point, and what the stored metrics describe

The model and the thresholds were settled at different moments, and the test split was
deliberately not consulted again after the final threshold was chosen. This note records
exactly what each stored file describes, so no figure is read as something it is not.

## The model

`tb_mobilenetv2_v1.keras`, run tag `reg-both`: lighter augmentation, 60 base layers
unfrozen at 1e-4, dropout 0.5, weight decay 1e-4. Chosen on validation from seven runs
recorded in `experiments.csv`.

**AUC 0.9291, 95% confidence interval [0.878, 0.970]**, measured on the held-out test
split. AUC does not depend on a threshold, so this figure describes the current model and
remains valid.

## The operating point

Decision threshold **0.102**, chosen on the validation split alone by
`select_thresholds.py`. On validation it gives sensitivity 0.933 and specificity 0.639.

The selection target is 0.92, two points above the WHO requirement of 0.90. The margin
exists because a threshold chosen for exactly 0.90 on 121 validation images does not
transfer precisely: one selected at 0.900 delivered 0.881 on unseen data. The margin is
small because the trade-off is steep here, as the validation curve shows:

| Selection target | Threshold | Sensitivity | Specificity |
|---|---|---|---|
| 0.90 | 0.133 | 0.900 | 0.689 |
| **0.92** | **0.102** | **0.933** | **0.639** |
| 0.95 | 0.050 | 0.950 | 0.541 |
| 0.98 | 0.036 | 0.983 | 0.393 |

High-suspicion threshold **0.546**, the lowest cutoff reaching 95 per cent specificity on
validation.

## A finding worth stating plainly

**No threshold satisfies both WHO targets at once.** The best specificity available at or
above 90 per cent sensitivity is 0.689 on validation, short of the 0.70 the target product
profile asks for. This is a property of the model on this data, not a tuning problem, and
it is reported rather than worked around.

## What `metrics.json` describes

`metrics.json` now describes the operating point the system actually runs at: decision
threshold **0.102**, measured on the held-out test split on 25 October 2026.

| | Sensitivity | Specificity | Accuracy |
|---|---|---|---|
| Validation, where the threshold was chosen | 0.9333 | 0.6393 | — |
| **Test, unseen until this evaluation** | **0.9153** [0.839, 0.983] | **0.6393** [0.509, 0.758] | **0.7750** [0.700, 0.850] |

Confusion matrix on 120 test images, 59 of them TB: 54 true positives, 39 true negatives,
22 false positives, **5 TB cases missed**.

**The margin did its job.** The threshold was selected for 0.92 sensitivity on validation
rather than for the WHO minimum of 0.90, because an earlier threshold chosen for exactly
0.900 delivered 0.881 on unseen data. Sensitivity here fell by 1.8 points in transfer,
from 0.9333 to 0.9153, and stayed above the 0.90 requirement. Without the margin it would
not have. Specificity transferred exactly, 0.6393 on both splits.

**The WHO specificity target remains unmet**, 0.639 against the 0.70 the target product
profile asks for, which is the same finding the validation curve gave and is reported
rather than worked around.

An earlier version of this file described threshold 0.041, an operating point used while
the margin was being investigated. Those figures are superseded; the previous run's
headline numbers were accuracy 0.700, recall 0.9831 and specificity 0.4262.

**This was the test split's fourth and final consultation**, and Chapter 5 should say so.
The first three were model selection, the cross-dataset work and the earlier threshold
investigation. The operating point itself was still chosen entirely from the validation
curve above, which needs no test data; this evaluation only measured the result. AUC is
threshold-independent and is unchanged at 0.9291 [0.878, 0.970].

Regenerate with:

```
python ml/scripts/evaluate_model.py
```
