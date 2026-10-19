# Model report: reg-both

Produced by `ml/scripts/plot_training.py`. Regenerate rather than edit.

## Epochs

| Stage | Epoch limit | Epochs run | Best epoch | Validation AUC |
|---|---|---|---|---|
| Stage 1: classification head | 30 | 30 | 26 (epoch 26 overall) | 0.8907 |
| Stage 2: fine-tuning | 15 | 15 | 13 (epoch 43 overall) | 0.9119 |

**45 epochs were run in total.** The limits are upper bounds, not targets:
early stopping ends a stage once validation AUC has not improved for eight epochs,
and the weights kept are those of the best epoch rather than the last one. Epochs
after the best one are the model improving on the training images while getting
worse on unseen ones, so they are discarded.

## Overfitting or underfitting

At the best epoch of the stage that was kept (stage 2: fine-tuning):

| | Training | Validation | Gap |
|---|---|---|---|
| AUC | 0.9693 | 0.9119 | +0.0574 |
| Accuracy | 0.9123 | 0.8264 | +0.0859 |
| Loss | 0.2195 | 0.4176 | -0.1981 |

**Verdict: mild overfitting**, with an AUC gap of 0.057.

The model scores higher on images it has seen than on images it has not, which is
overfitting by definition. It is not underfitting: underfitting would mean weak
scores on both, whereas training AUC shows the model learned the data well.

The cause is the size of the training set. 559 images is small for a convolutional
network, which is why transfer learning was used rather than training from scratch,
and why augmentation and early stopping are applied.

## Does it generalise

| Validation AUC | Test AUC | Difference |
|---|---|---|
| 0.9119 | 0.9291 | 0.0172 |

Two separate sets of unseen images agree closely. There are two ways to overfit:
fitting the training images too closely, which the gap above shows, and fitting
the validation set through repeated tuning, which would make the final figure
meaningless. This agreement shows the second did not happen.

## Test results

| Metric | Value | 95% confidence interval |
|---|---|---|
| Accuracy | 0.7000 | [0.617, 0.783] |
| Precision | 0.6237 | [0.526, 0.722] |
| Recall | 0.9831 | [0.941, 1.000] |
| Specificity | 0.4262 | [0.304, 0.548] |
| F1 | 0.7632 | [0.685, 0.835] |
| Auc | 0.9291 | [0.878, 0.970] |

58 of 59 TB cases detected; 35 of 61 healthy patients flagged in error.

## Figure

![Training history](training_history_reg-both.png)
