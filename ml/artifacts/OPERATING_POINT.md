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

## What `metrics.json` currently describes

`metrics.json` was produced at an **earlier** operating point, decision threshold 0.041,
while the margin was being investigated. Its threshold-dependent figures — accuracy,
precision, recall, specificity, F1 and the confusion matrix — describe that setting and
**not** the current threshold of 0.102. Its AUC is unaffected.

The test split was not evaluated again after settling on 0.102. By then it had been
consulted three times, and each further look weakens the independence of the final figure.
The operating point was chosen entirely from the validation curve above, which needs no
test data.

The consequence is that there is no test-set estimate for the current operating point.
That is a deliberate trade: an honest AUC and a transparently chosen threshold, rather
than threshold-dependent figures tuned against the data meant to judge them.

Should a final test evaluation be wanted for the report, run:

```
python ml/scripts/evaluate_model.py
```

and record in Chapter 5 that the test split was consulted a fourth time.
