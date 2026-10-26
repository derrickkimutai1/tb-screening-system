# Which explanation the system shows, and why

The first version showed a Grad-CAM heatmap. Measured against Montgomery's
hand-drawn lung masks it did not localise: a lift of 0.9963 over all 138
images, where 1.0 is what a map thrown at the radiograph at random would score.
That is recorded in `gradcam_evaluation.json` and was reported as a limitation
rather than hidden.

This note records what replaced it, what was tried and rejected, and what the
replacement can and cannot be claimed to do.

## What lift measures, and what it does not

For each image: the share of strongly activated pixels falling inside the
lungs, divided by the share of the image the lungs occupy. Above 1 means the
explanation favours the lungs. Only Montgomery carries masks, so only its 138
images can be checked, and only its 58 TB images are a fair test — on a normal
radiograph there is no lesion, so "did the heat land on the lungs" has no
right answer and both methods score badly there for no interesting reason.

**The metric rewards coarseness, and can be gamed.** This matters more than it
first appears, and the numbers below show it.

## The methods tried

All measured on the 49 Montgomery TB images in the train and validation
splits — the development set, chosen so that the setting was not tuned on the
images the result is reported on.

| Method | Lift | Median |
|---|---|---|
| Grad-CAM, `block_13_expand_relu` | 1.11 | 0.84 |
| Score-CAM, top 32 channels | 0.26 | 0.00 |
| Occlusion, patch 48 stride 16 | 1.12 | — |
| **Occlusion, patch 32 stride 16** | **1.63** | **1.44** |

**Score-CAM was rejected.** Its maps land on the image borders. The first
implementation scored 0.04 because of a real bug: the published method takes a
softmax over the masked scores, which assumes logits spanning a wide range,
and this model ends in a single sigmoid whose outputs all sit inside 0..1. The
softmax came out nearly uniform, so the result was an unweighted average of
the broadest feature maps. Corrected to weight by the score directly, it
reaches 0.26. Still far below chance. The module is kept at
`screening/services/scorecam.py` so the comparison can be rerun; nothing in
the application imports it.

**Patch size, not stride, carried the improvement for occlusion.** A 48 pixel
patch covers about a fifth of the image: hiding it moves the score without
saying which part of that fifth mattered, and it scored 1.12, barely above
Grad-CAM. Dropping to 32 took it to 1.63.

## Why stride 16, when coarser scores higher

| Stride | Map | Lift | Median | Forward passes |
|---|---|---|---|---|
| 8 | 25×25 | 1.51 | 1.17 | 625 |
| **16** | **13×13** | **1.63** | **1.44** | **169** |
| 24 | 9×9 | 1.97 | 1.77 | 81 |
| 32 | 7×7 | 1.85 | 1.77 | 49 |
| 48 | 5×5 | 2.12 | 2.06 | 25 |
| *uniform map, control* | 1×1 | *1.00* | *1.00* | 0 |

The best score belongs to a 5×5 map. Twenty-five cells over an entire chest
cannot point at a lesion, and a map that marks the middle of the chest overlaps
the lungs well while telling a clinician nothing. The control shows the floor:
a map that is hot everywhere, carrying no information at all, still scores 1.00
rather than 0. A 7×7 map being too coarse to hold a lesion is exactly why
Grad-CAM was moved off `out_relu` in the first place.

So the setting is **the finest one that clearly beats Grad-CAM**, not the one
with the best number. Maximising this metric would have produced a worse
explanation with a better score.

## What can be claimed

Paired per-image comparison, Grad-CAM against occlusion patch 32 stride 16,
both measured on the same films. Pairing matters here: lift varies far more
between images than between methods, so comparing two means on 58 images
mostly measures which images were in the set.

| Images | Mean difference | 95% CI | Occlusion higher on |
|---|---|---|---|
| All 58 TB films | **+0.447** | **[+0.125, +0.780]** | 42 of 58 |
| 9 held-out test films | +0.077 | [−0.968, +1.274] | 4 of 9 |

**On the 58 TB films the improvement is real**: the interval excludes zero and
occlusion wins on 72% of images individually.

**On the held-out 9 it cannot be confirmed.** The direction is the same, the
interval is far too wide to say anything, and nine images is simply not enough.
Montgomery has no more masked TB radiographs to offer.

The honest statement is therefore: *occlusion localises better than Grad-CAM
across the masked TB radiographs available, by a margin that excludes zero on
the full set of 58; the 9-image held-out subset is too small to confirm it
independently.* Anyone wanting a stronger claim needs a masked dataset larger
than Montgomery.

One caveat stated plainly: the stride was chosen on 49 of those 58 films. The
method-level conclusion does not rest on that choice, because every occlusion
setting tried beat Grad-CAM on the development images — but the exact figure
of +0.447 includes images the setting was selected on.

## Why this is the better thing to show regardless

Grad-CAM is correlational: it reads gradients at an internal layer and reports
what co-varied with the score. Occlusion is causal: it covers a region, runs
the model again, and reports what the score actually lost. The shortcut
investigation in `evaluate_shortcuts.py` already relied on that property, and
it is the evidence the project trusts most — intact 0.8625 AUC, lungs only
0.7884, surroundings only 0.5453.

It remains an explanation of the model, not of the patient. Bright regions are
where the score came from. They are not a claim that disease is present there,
and the result page and printed report both say so.

## Cost, and what follows from it

2.87s per map against Grad-CAM's 0.48s, best of three on an idle CPU. That is
why the map is built the first time somebody opens a case rather than during
the upload: a batch of twenty would otherwise add about a minute to an upload
producing maps for images nobody opens.

## Reproducing all of this

```
python ml/scripts/evaluate_explanations.py --split development --labels tb --method occlusion --patch 32 --stride 16
python ml/scripts/evaluate_explanations.py --split all --labels tb
python ml/scripts/evaluate_explanations.py --split all --labels tb --method occlusion --patch 32 --stride 16
python ml/scripts/compare_explanations.py \
    ml/artifacts/gradcam-block_13_expand_relu-all-tb_evaluation.json \
    ml/artifacts/occlusion-p32s16-all-tb_evaluation.json
```

Every run writes a file named for its method, settings and split, so no two
runs overwrite each other. An earlier version of the script did not, and one
stride's results silently destroyed another's.
