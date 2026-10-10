# Sprint 2 test record

Tests of the implemented functionality, covering expected behaviour, invalid inputs and
failure conditions. The automated tests run with:

```
.venv/Scripts/python.exe manage.py test screening
```

29 tests, all passing, and the same suite runs on every push through GitHub Actions.

---

## Automated tests

| # | Test | Expected | Actual | Outcome |
|---|---|---|---|---|
| 1 | Valid PNG upload | Record created, redirect to result | As expected | Pass |
| 2 | Upload stores model and thresholds used | Fields match `metadata.json` | As expected | Pass |
| 3 | Upload records a real prediction | Score between 0 and 1, label, triage, justification, timing all set | As expected | Pass |
| 4 | Upload records the quality assessment | Status, blur and brightness stored | As expected | Pass |
| 5 | Unsupported file type (.txt) | Rejected with a readable message, no record | As expected | Pass |
| 6 | Missing case reference | Rejected, no record | As expected | Pass |
| 7 | Oversized image | Rejected naming the actual and permitted size | As expected | Pass |
| 8 | Case list shows stored records | Both references listed | As expected | Pass |
| 9 | Case list filters by reference | Only the matching record shown | As expected | Pass |
| 10 | Dashboard counts | Totals match the database | As expected | Pass |
| 11 | Dashboard with an empty database | Renders, shows "No screening records yet" | As expected | Pass |
| 12 | Review workflow | Note appended, case status updated | As expected | Pass |
| 13 | Preprocessing output shape and range | (224, 224, 3), float32, within -1 to 1 | As expected | Pass |
| 14 | Greyscale, palette and RGB inputs | Byte-identical output | As expected | Pass |
| 15 | Scaling matches Keras `preprocess_input` | Identical arrays | Identical, maximum difference 0.0 | Pass |
| 16 | Label read from filename suffix | `_0` normal, `_1` TB, otherwise an error | As expected | Pass |
| 17 | Batch preparation | Shape (n, 224, 224, 3) | As expected | Pass |
| 18 | Single image as a batch of one | Shape (1, 224, 224, 3) | As expected | Pass |
| 19 | Detailed, well-exposed image | Quality acceptable, no warning | As expected | Pass |
| 20 | Flat image with no detail | Flagged as blurred | As expected | Pass |
| 21 | Dark image | Flagged as darker than expected | As expected | Pass |
| 22 | Bright image | Flagged as brighter than expected | As expected | Pass |
| 23 | File that is not an image | Status invalid, not usable | As expected | Pass |
| 24 | Degraded image | Still usable; warns rather than blocks | As expected | Pass |
| 25 | Score below the lower threshold | Low suspicion, justification quotes both figures | As expected | Pass |
| 26 | Score between thresholds | Medium suspicion | As expected | Pass |
| 27 | Score at or above the upper threshold | High suspicion | As expected | Pass |
| 28 | Score exactly on the lower threshold | Medium, matching the labelling rule | As expected | Pass |
| 29 | Every triage decision explains itself | Justification never empty | As expected | Pass |

## Manual end-to-end test

Six chest X-rays from the held-out test split were submitted through the web form. The
model had never seen any of them.

| Case | Actual | Score | Result | Triage | Heatmap | Inference | Correct |
|---|---|---|---|---|---|---|---|
| DEMO-001 | TB | 0.9999 | Likely TB | High suspicion | Generated | 2704 ms | Yes |
| DEMO-002 | TB | 0.9843 | Likely TB | High suspicion | Generated | 182 ms | Yes |
| DEMO-003 | TB | 0.9989 | Likely TB | High suspicion | Generated | 143 ms | Yes |
| DEMO-004 | Normal | 0.5928 | Likely TB | Medium suspicion | Generated | 150 ms | **No** |
| DEMO-005 | Normal | 0.1507 | Unlikely TB | Low suspicion | Generated | 153 ms | Yes |
| DEMO-006 | Normal | 0.0432 | Unlikely TB | Low suspicion | Generated | 155 ms | Yes |

Five of six correct. DEMO-004 is a false positive, consistent with the measured
specificity of 50.8 per cent: the model over-refers healthy patients.

The first prediction takes 2704 ms because the model is loaded and the computation graph
is built on first use. Every prediction after that takes about 150 ms on this laptop's
CPU, with no GPU, which supports the low-resource claim in the proposal.

## Corrections made during this sprint

| Problem found | How it was found | Correction |
|---|---|---|
| A weaker fine-tuned model could overwrite a stronger head-only one | Reading the checkpoint logic before the long run | Each training stage now checkpoints to its own file and the better one is selected |
| Training crashed after completing, on a stale variable in a final print | One-epoch smoke test before the full run | Variable renamed; the smoke test is now the standard first step |
| Heavier augmentation left black borders the model could learn from | Comparing four variants on validation | Lighter augmentation adopted; it improved AUC from 0.865 to 0.878 |
| Recall of only 0.717 at the default 0.50 threshold | Reading the validation metrics | Threshold chosen from validation at 0.362, raising test sensitivity to 0.949 |
| The triage filter repeated its arrow icon across the whole control | Viewing the rendered page | Background repeat and position rules added to the stylesheet |
| Heatmap overlays were written at up to 4892 pixels, several megabytes each | Watching the result page load slowly | Overlay capped at 1024 pixels; the activation map behind it is only 7 by 7 |
| The large-file commit guard blocked the 26 MB trained model | Attempting to commit it | The selected model is exempted by name; the guard still blocks datasets |

## Known limitations and outstanding defects

- **Specificity is 50.8 per cent**, against the WHO target of 70. The model over-refers,
  flagging 30 of 61 healthy patients in the test set. This is the main outstanding defect.
- **The Grad-CAM heatmaps are not yet verified to focus on the lungs.** Inspection of one
  TB case showed strong activation over the mediastinum and along the image border, near
  the "PA ERECT" annotation. The model may be partly reading markers rather than
  pathology. Montgomery ships 276 manual lung masks, which allow this to be measured
  rather than guessed, and that measurement is planned.
- **AUC of 0.891 is below the 0.95 and above commonly published** on these datasets.
- **Original uploads are served at full resolution**, up to 4892 pixels, so the result
  page is slow with research-grade images.
- **No authentication.** Any visitor can upload and review. The proposal places login and
  role management outside scope unless time permits.
