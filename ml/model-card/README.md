---
license: other
license_name: research-use-only
library_name: keras
pipeline_tag: image-classification
tags:
  - medical-imaging
  - chest-xray
  - tuberculosis
  - screening
  - transfer-learning
  - mobilenetv2
base_model: google/mobilenet_v2_1.0_224
metrics:
  - auc
  - recall
  - specificity
---

# tb_mobilenetv2_v1

A MobileNetV2 classifier that scores a frontal chest radiograph for how far it
resembles the tuberculosis-positive films it was trained on, built for triage
in Kenyan health facilities that have an X-ray machine and no radiologist on
site. It runs on a CPU in about 150 milliseconds and is small enough to ship
inside a Windows executable, which is why it was chosen over a network that
scores higher.

**This is not a diagnostic device and it is not clinically validated.** It was
trained on 800 images from two public research datasets, neither of them
Kenyan, and evaluated on 120 of them. Every output needs a clinician's
reading. Nothing here should be used to decide a person's treatment.

## What it is for

Ordering a queue. A clinic with more films than reading time can use the score
to decide which radiograph a clinician looks at first, and the system built
around this model presents three triage bands rather than a yes or a no.

It is not for confirming or excluding tuberculosis, not for any population
whose radiographs differ systematically from the training sources, not for
paediatric films, not for lateral views, and not as a second reader whose
agreement adds confidence to a clinician's own reading.

## How to use it

```python
import numpy as np
from keras.models import load_model
from keras.applications.mobilenet_v2 import preprocess_input

model = load_model("tb_mobilenetv2_v1.keras")

# A single-channel radiograph, resized to 224x224 with bilinear resampling and
# repeated across three channels, then scaled to [-1, 1] the way MobileNetV2
# expects. Any other scaling silently changes the score.
batch = preprocess_input(np.stack([image_224x224_rgb]).astype("float32"))
score = float(model.predict(batch, verbose=0)[0][0])

likely_tb = score >= 0.102          # the decision threshold
high_suspicion = score >= 0.546     # the top triage band
```

The score is **not a probability**. It is not calibrated, and presenting it as
a percentage would assert an accuracy it does not have. See *Calibration*
below.

## Training data

| | |
|---|---|
| Sources | NLM Shenzhen and NLM Montgomery chest radiograph sets |
| Images | 800 |
| Split | stratified 70 / 15 / 15, seeded at 42, giving 559 train / 121 validation / 120 test |
| Test positives | 59 of 120 |
| Manifest | `splits.csv`, SHA-256 prefix `fecb7a83594b671a` |

Both sets are public research collections of de-identified films, released by
the U.S. National Library of Medicine. No patient data from any Kenyan
facility was used to train this model, which is the single largest limitation
on reading these results as applicable to the setting it was designed for.

## How it was trained

MobileNetV2 with ImageNet weights and a custom classification head. The head
was trained first, then the top 60 layers were unfrozen and fine-tuned at a
learning rate of 1e-4. Dropout 0.5, weight decay 1e-4, batch size 32, light
augmentation only: rotation 0.02 and zoom 0.05, no translation and no
brightness change, because a radiograph's orientation and exposure carry
meaning that aggressive augmentation destroys.

TensorFlow 2.21.0, Keras 3.15.1, seed 42, CPU only. The run is tagged
`reg-both` in `ml/artifacts/experiments.csv`, where the seven tuning runs and
the four architecture runs behind the choices below are recorded.

## How it performs

On the held-out test split of 120 images at the shipped decision threshold of
0.102, with 95% confidence intervals from 2000 bootstrap samples:

| | Value | 95% CI |
|---|---|---|
| AUC | 0.9291 | 0.8778 - 0.9695 |
| Sensitivity | 0.9153 | 0.8393 - 0.9831 |
| Specificity | 0.6393 | 0.5091 - 0.7576 |
| Precision | 0.7105 | 0.6071 - 0.8089 |
| F1 | 0.8000 | 0.7218 - 0.8677 |
| Accuracy | 0.7750 | 0.7000 - 0.8500 |

Confusion matrix: 54 true positive, 39 true negative, 22 false positive,
**5 false negative**. Those five are the number that matters for a screening
tool, and they are five people with tuberculosis the model called unlikely.

The threshold 0.102 was chosen on validation with a deliberate margin above
the WHO target sensitivity of 0.90, because a threshold picked to land exactly
on 0.90 delivered 0.881 on unseen data. The margin earned its keep:
sensitivity fell 1.8 points in transfer and stayed above the target.

## Where it fails

**The WHO specificity target is not met.** WHO's target product profile for a
triage test asks for at least 0.90 sensitivity and at least 0.70 specificity.
This model meets the first and misses the second: 0.6393 on test, and on
validation no threshold satisfies both at once, the best specificity at or
above 0.90 sensitivity being 0.689. Twenty-two of 61 people without
tuberculosis were flagged. In a screening setting that is 22 unnecessary
confirmatory tests.

**It is not calibrated.** Measured on validation: expected calibration error
0.1018, worst bin off by 0.3498, Brier score 0.1302 against 0.25 for
predicting the base rate alone. The model is systematically underconfident, so
the score is reported as a model score and never as a probability or a
confidence. Platt scaling or isotonic regression on validation would fix this
and has not been done.

**It loses accuracy at a new hospital.** Trained on Shenzhen alone and tested
on all 138 unseen Montgomery films, AUC falls from 0.9336 within source to
0.8625 across source, a generalisation cost of 0.071. Specificity at 0.90
sensitivity on the unseen hospital falls to 0.525. A Kenyan deployment is a
third source, and this figure is the honest estimate of what changing hospital
costs.

**It is not reading an acquisition shortcut, and that was checked.** A
classifier trained to predict which dataset an image came from scores AUC
1.000, so the shortcut was perfectly available. Blanking the acquisition
markers cost 0.021 of AUC against a control that cost nothing. On the 21 masked
Montgomery films, restricting the image to the lungs gives 0.7870 and to
everything outside them 0.4259, against 0.8241 intact. Keeping only the lungs
costs little; keeping only what surrounds them puts the model below chance. The
signal lives in the lungs.

**The heatmap does not localise well.** Measured against Montgomery's
hand-drawn lung masks over the 58 masked tuberculosis films, where a map
placed at random scores 1.00:

| Map | Lift | Median |
|---|---|---|
| Grad-CAM, `block_13_expand_relu` at 14x14 | 1.16 | 0.88 |
| Occlusion, patch 32 stride 16 | 1.61 | 1.38 |

Paired per image, occlusion gains 0.447 of lift, 95% CI 0.125 - 0.780, higher
on 42 of 58. On the 9 held-out test films that interval includes zero, so the
improvement is measured rather than proven, and Montgomery has no further
masked positives to settle it.

Grad-CAM is still what the system shows, because the approved project
objective names it, and the figure above is printed next to the map so nobody
reads it as showing where disease is. Note also that the lung-mask metric is
gameable: coarsening the occlusion grid to stride 48 scores 2.12 while being
clinically useless, and a map that is hot everywhere scores 1.00 rather than
0. Stride 16 is the finest setting that clearly beats Grad-CAM, not the
highest-scoring one.

**The test split has been consulted four times**, which is its final use. Any
further figure from it would be a selection result rather than a held-out one.

## Why MobileNetV2 and not something larger

Four architectures were trained under one schedule, sharing splits, head,
regularisation and seed, so the comparison is about the network and nothing
else. Selection was on validation:

| Architecture | Parameters | Validation AUC |
|---|---|---|
| ResNet50 | 23,866,497 | 0.9478 |
| EfficientNetB0 | 4,226,980 | 0.9126 |
| MobileNetV2 | 2,435,393 | 0.9119 |
| Small CNN, no pretraining | 436,337 | 0.6108 |

**ResNet50 scores higher and the gap is real**, not noise: paired bootstrap
difference 0.0022 - 0.0744, excluding zero. MobileNetV2 ships anyway, on ten
times fewer parameters, because the deliverable is an offline Windows build
carrying the weights and running on clinic hardware with no GPU. That is a
deployment decision with a measured cost, stated rather than hidden.

The scratch network at 0.6108 is what the ImageNet weights are worth.

## Speed

Fifty single-image screenings end to end, including the heatmap: median 6.24
seconds, 90th percentile 6.90, slowest 10.84, with 49 of 50 inside the
ten-second requirement. Measured on Windows, AMD64, 11.4 GB RAM, no GPU, where
the requirement names 8 GB. Prediction alone is about 150 milliseconds; the
rest is image handling and building the explanation.

## Ethics and data protection

The system around this model stores radiographs and results under the Kenya
Data Protection Act 2019, with facility-scoped access, a hash-chained audit
trail, and no patient names, only a case reference typed by the operator. The
model itself carries no patient data.

Deploying a screening tool that over-refers, as this one does, shifts cost on
to the people it flags. That tradeoff belongs to the clinic adopting it and
should be decided with the specificity figure above in hand.

## Provenance

| | |
|---|---|
| Model version | `tb_mobilenetv2_v1` |
| Run tag | `reg-both` |
| Trained | 17 October 2026 |
| Dataset manifest | `splits.csv`, SHA-256 prefix `fecb7a83594b671a` |
| Source code | https://github.com/derrickkimutai1/tb-screening-system |
| Evaluation artifacts | `ml/artifacts/` in that repository |

Every figure on this card is read from a file in `ml/artifacts/` produced by a
script in `ml/scripts/`, not transcribed from a notebook.

## Datasets and citation

Jaeger S, Candemir S, Antani S, Wang Y-X, Lu P-X, Thoma G. Two public chest
X-ray datasets for computer-aided screening of pulmonary diseases. *Quantitative
Imaging in Medicine and Surgery*, 2014;4(6):475-477.

The Shenzhen and Montgomery sets are distributed by the U.S. National Library
of Medicine for research use, and their terms govern any use of weights
derived from them. These weights are released for research and academic
evaluation only.

Built by Derrick Kimutai Kibet at Strathmore University, Nairobi, as a
final-year project, supervised by Mrs Juliet Kirui.
