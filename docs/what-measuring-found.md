# What measuring found

Five things this project claimed. Each was measured. All five were false.

This is kept because the Build Phase guidance asks for known limitations and
outstanding defects to be documented honestly, and because a system that has
never had a claim disproved has usually not been tested hard enough to
disprove one. Every entry below has a commit, a number before, and a number
after.

None of them would have failed a unit test. They were found by running the
thing, by cloning it somewhere else, or by measuring the requirement the
proposal actually wrote down.

---

## 1. The test suite was failing on every push, and had been for five weeks

**The claim.** The README said the suite runs on every push, and the project
plan counts automated testing as a Sprint I deliverable.

**What measuring found.** It did run. It had failed on **every push from 21
October onward**. A clean clone of the repository, following the README
exactly, produced **131 errors**.

**Why it was invisible.** Static files are served through WhiteNoise's
manifest storage, which refuses any asset missing from the manifest that
`collectstatic` builds. `staticfiles/` is not tracked by Git, and Django's
test runner forces `DEBUG` off, so the manifest is required even to run tests.
The Dockerfile and the PyInstaller spec had always run `collectstatic`. The
workflow and the setup instructions never mentioned it. A developed machine
hides this permanently, because the folder has existed since the first time
somebody ran the command by hand.

**How it was found.** Cloning from GitHub into an empty directory and
following the project's own instructions as a stranger would.

**After.** All thirteen migrations apply from an empty database and **267 of
267 tests pass in the clean clone**. CI green for the first time in the
project's history. Commit `1a7e21e`.

---

## 2. The desktop build had never displayed a single image

**The claim.** A portable Windows build that screens offline, tagged and
presented as a deliverable.

**What measuring found.** It predicted correctly, stored records correctly and
wrote both the radiograph and the heatmap to disk correctly. Every image on
every result page was a **broken icon**, and always had been.

**Why.** `config/urls.py` served media only when `DEBUG` was on.
`django.conf.urls.static.static()` returns an empty list otherwise, WhiteNoise
serves only collected static files, and the packaged build runs with `DEBUG`
off. Nothing would hand the files back.

**How it was found.** Running the executable and looking at it, rather than
treating a successful build as a successful program.

**After.** Media is served by the application in the packaged build, with
directory traversal refused. Verified against a rebuilt executable: a
radiograph screens, a map builds in about five seconds, both images serve.
Commit `da8e3de`.

---

## 3. Stored radiographs could be downloaded with no account at all

**The claim.** NFR-05: uploaded images and heatmaps are "served only through
authenticated application routes".

**What measuring found.** The pages were protected. The images behind them
were not.

```
/cases/                                 302 redirect to sign-in
/media/heatmaps/2026/10/<case>.png      200, 1,633,350 bytes
```

No cookie, no session. The case identifier in the path is obscurity, not
access control.

**How it was found.** Reading the project's own non-functional requirement and
testing it instead of assuming it.

**After.** Media routes through the application in every environment and
carries the same clinic scoping as the case page: another clinic receives 404
rather than 403, because a refusal would confirm the case exists. Commit
`f38d10b`.

---

## 4. The system met its response-time requirement one time in fifty

**The claim.** NFR-01: at least 90 per cent of single-image screenings return a
complete result, including heatmap generation, within ten seconds, measured
over fifty consecutive uploads. Marked "verified by measurement". Nobody had
measured.

**What measuring found.**

| | Before |
|---|---|
| Median | 16.12s |
| 90th percentile | 20.37s |
| Slowest | 28.29s |
| **Within ten seconds** | **1 of 50 (2%)** |

**Why.** Not the model, which was steady. `strip_metadata`, which re-encodes
every upload to remove EXIF, took **9.9 seconds** on a 4892×4020 radiograph -
the entire budget, before the model saw the image. It copied the image with
`putdata(list(getdata()))`, building a Python list of nineteen million pixels,
then saved the PNG with `optimize=True`, spending nine seconds to make the
file seven per cent smaller.

**Why no test caught it.** `MetadataStrippingTests` passed throughout. It
checks that metadata is removed. It has never checked what removing it costs.

**After.** 9.88s becomes 1.69s for seven per cent more storage, with no loss:
PNG is lossless at every compression level and the stripping property is
unchanged.

| | After |
|---|---|
| Median | **5.97s** |
| 90th percentile | **6.43s** |
| **Within ten seconds** | **49 of 50 (98%)** |

Measured on 11.4 GB of RAM where the requirement names 8 GB, so the figures
describe better hardware than it specifies. `scripts/measure_screening_time.py`
reruns it. Commit `1d02f93`.

---

## 5. The explanation was not explaining anything

**The claim.** SO4 names a Grad-CAM heatmap showing the regions that
influenced the prediction.

**What measuring found.** Against Montgomery's hand-drawn lung masks, the
activation scored a lift of **1.11** on TB films, where **1.0 is what a map
thrown at the radiograph at random would score**. It was being displayed
anyway, with a caption admitting it.

**After.** An occlusion map replaces it: cover a region, re-score the image,
record what the score lost. Paired per-image over the 58 masked TB
radiographs the gain is **+0.447 of lift, 95% CI [+0.125, +0.780]**, higher on
42 of 58.

**What is deliberately not claimed.** On the 9 held-out test films the interval
includes zero, so the improvement is **not independently confirmed**, and
Montgomery has no more masked TB radiographs to settle it with.

**And the measurement itself is gameable.** Lift rises as the map gets coarser,
reaching **2.12 for a 5×5 grid** that could not point at a lesion, while a
control map that is hot everywhere still scores 1.00 rather than 0. So the
shipped setting is the finest one that clearly beats Grad-CAM rather than the
one with the best number. Maximising the metric would have produced a worse
explanation with a better score.

This diverges from the approved proposal, which names Grad-CAM explicitly.
`docs/traceability.md` section 4d states the divergence and why. Commit
`9207e31`, full comparison in `ml/artifacts/explanation_methods.md`.

---

## What this list is for

Not for showing that the project was broken. For showing that each claim it
makes has been tested by something other than the person who wrote it, and
that where the evidence disagreed with the claim, the claim was changed.

The honest reading is that four of these defects existed for weeks in a system
that looked finished, and the fifth was a published limitation nobody had
tried to fix. What found them was measuring the requirement as written,
running the artefact rather than the source, and setting the project up
somewhere that was not the machine it was built on.
