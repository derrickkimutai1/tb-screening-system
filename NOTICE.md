# Notices

The MIT licence in `LICENSE` covers the source code in this repository. Three
things in or around this project are not covered by it, and matter more than
the code terms do.

## The radiographs are not ours to license

The model was trained on two public chest radiograph collections published by
the **United States National Library of Medicine**:

- **Montgomery County chest X-ray set** — 138 images with hand-drawn lung masks
- **Shenzhen chest X-ray set** — 662 images

Both are obtained from
`https://data.lhncbc.nlm.nih.gov/public/Tuberculosis-Chest-X-ray-Datasets`
by `ml/scripts/download_shenzhen.py` and `ml/scripts/prepare_data.py`. Neither
collection is redistributed here: `data/` is not tracked by Git, and the
scripts fetch from the source each time.

Their use is governed by the terms the National Library of Medicine sets for
them, not by this repository's licence. Anyone reusing this work for anything
beyond reading the code should read those terms at the source rather than
assume MIT applies to the images. The datasets are described in:

> Jaeger S, Candemir S, Antani S, Wáng Y-XJ, Lu P-X, Thoma G. Two public chest
> X-ray datasets for computer-aided screening of pulmonary diseases.
> *Quantitative Imaging in Medicine and Surgery*, 2014;4(6):475–477.

## The pretrained weights are not ours either

`ml/models/tb_mobilenetv2_v1.keras` is a **MobileNetV2** network initialised
from ImageNet-pretrained weights supplied by Keras, then fine-tuned on the
datasets above. The base architecture and its pretrained weights carry the
terms of their own publishers. The fine-tuned weights in this repository are a
derivative of them and cannot grant rights the originals do not.

## This is not a medical device

**The software is a screening aid. It has not been clinically validated, it is
not registered or approved as a medical device in any jurisdiction, and it
must not be used to make a clinical decision about a patient.**

Every output requires a clinician to read the radiograph and confirmatory
testing before anything is decided. The limits are measured and stated rather
than estimated:

- On the held-out test split at the operating point the system runs, it found
  54 of 59 TB radiographs. **Five were missed.** A low score is not a
  clearance.
- Specificity is 0.639 against the WHO target product profile's 0.70, so the
  system over-refers. No threshold satisfies both WHO targets at once on this
  data, which is a property of the model rather than a tuning oversight.
- The score is **not a calibrated probability**. Expected calibration error is
  0.1018 and the model is systematically underconfident, which is why the
  interface calls it a model score and never a confidence.
- The explanation heatmap shows which regions the score depended on. It is
  **not** a claim that disease is present in those regions, and it localises
  only weakly.

The warranty disclaimer in `LICENSE` is the legal position. This section is
the practical one: using this software clinically without the review and
confirmatory testing described above would be unsafe, and no licence term
changes that.

Full evidence for each figure above is in `docs/traceability.md`,
`ml/artifacts/OPERATING_POINT.md` and `ml/artifacts/explanation_methods.md`.

## Third-party packages

Runtime and development dependencies are listed in `requirements.txt` and
`requirements-ml.txt` and remain under their own licences. Nothing in this
repository relicenses them.
