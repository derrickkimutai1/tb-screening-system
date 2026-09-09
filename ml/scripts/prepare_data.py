"""
Inspect the reference datasets and produce the train, validation and test split.

Runs three jobs in order:

1.  Inspects every image. Confirms it decodes, and records its source dataset,
    class, dimensions and colour mode.
2.  Checks for duplicates by content hash, both within each dataset and across
    the two. A duplicate that crossed a split boundary would leak test data into
    training and inflate every metric that follows.
3.  Writes a 70 / 15 / 15 split, stratified on source and class together so each
    split holds the same mix of both datasets and both classes.

Outputs `splits.csv`, the manifest every later script reads, and a summary table
for the report. Nothing is copied or moved; the manifest records paths.

The split is seeded, so re-running reproduces it exactly.

Usage:
    python ml/scripts/prepare_data.py
"""

import csv
import hashlib
import sys
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))

from preprocessing import label_from_filename  # noqa: E402

SOURCES = {
    "montgomery": ROOT / "data/raw/montgomery/MontgomerySet/CXR_png",
    "shenzhen": ROOT / "data/raw/shenzhen/CXR_png",
}

ARTIFACTS = ROOT / "ml" / "artifacts"
MANIFEST = ARTIFACTS / "splits.csv"
SUMMARY = ARTIFACTS / "data_summary.md"

TEST_FRACTION = 0.15
VALIDATION_FRACTION = 0.15
SEED = 42

Image.MAX_IMAGE_PIXELS = None


def inspect(path, source):
    """Decode one image and record what it is."""
    digest = hashlib.md5(path.read_bytes()).hexdigest()
    with Image.open(path) as image:
        image.verify()
    with Image.open(path) as image:
        width, height = image.size
        mode = image.mode
    return {
        "filename": path.name,
        "filepath": str(path.relative_to(ROOT)).replace("\\", "/"),
        "source": source,
        "label": label_from_filename(path),
        "width": width,
        "height": height,
        "mode": mode,
        "md5": digest,
    }


def collect():
    records, failures = [], []
    for source, directory in SOURCES.items():
        if not directory.is_dir():
            raise SystemExit(f"Dataset directory missing: {directory}")
        for path in sorted(directory.glob("*.png")):
            try:
                records.append(inspect(path, source))
            except Exception as error:
                failures.append((path.name, str(error)))
    return records, failures


def find_duplicates(records):
    """Group records that share a content hash."""
    by_digest = defaultdict(list)
    for record in records:
        by_digest[record["md5"]].append(record)
    return {d: group for d, group in by_digest.items() if len(group) > 1}


def assign_splits(records):
    """Split 70 / 15 / 15, stratified on source and class together.

    Stratifying on the pair rather than the class alone keeps the proportion of
    Montgomery to Shenzhen images, and of TB to normal, steady across all three
    splits. Without it a small test set can drift badly on both counts.
    """
    strata = [f"{r['source']}:{r['label']}" for r in records]

    remaining, test = train_test_split(
        records,
        test_size=TEST_FRACTION,
        stratify=strata,
        random_state=SEED,
        shuffle=True,
    )

    remaining_strata = [f"{r['source']}:{r['label']}" for r in remaining]
    validation_share = VALIDATION_FRACTION / (1 - TEST_FRACTION)
    train, validation = train_test_split(
        remaining,
        test_size=validation_share,
        stratify=remaining_strata,
        random_state=SEED,
        shuffle=True,
    )

    for group, name in ((train, "train"), (validation, "validation"), (test, "test")):
        for record in group:
            record["split"] = name
    return records


def write_manifest(records):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    columns = [
        "filename", "filepath", "source", "label", "split",
        "width", "height", "mode", "md5",
    ]
    with open(MANIFEST, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(sorted(records, key=lambda r: (r["source"], r["filename"])))


def write_summary(records, duplicates):
    counts = Counter((r["split"], r["source"], r["label"]) for r in records)
    splits = ("train", "validation", "test")

    lines = [
        "# Dataset summary",
        "",
        "Produced by `ml/scripts/prepare_data.py`. Regenerate rather than edit.",
        "",
        f"- Split: {int((1 - TEST_FRACTION - VALIDATION_FRACTION) * 100)}"
        f" / {int(VALIDATION_FRACTION * 100)} / {int(TEST_FRACTION * 100)},"
        " stratified on source dataset and class together",
        f"- Random seed: {SEED}",
        f"- Duplicate images found: {len(duplicates)}",
        "- Both reference datasets hold one image per patient, so an image-level"
        " split is also a patient-level split",
        "",
        "## Images per split",
        "",
        "| Split | Montgomery normal | Montgomery TB | Shenzhen normal | Shenzhen TB | Total | TB share |",
        "|---|---|---|---|---|---|---|",
    ]

    for split in splits:
        mn = counts[(split, "montgomery", 0)]
        mt = counts[(split, "montgomery", 1)]
        sn = counts[(split, "shenzhen", 0)]
        st = counts[(split, "shenzhen", 1)]
        total = mn + mt + sn + st
        share = (mt + st) / total * 100 if total else 0
        lines.append(f"| {split} | {mn} | {mt} | {sn} | {st} | {total} | {share:.1f}% |")

    total_all = len(records)
    tb_all = sum(1 for r in records if r["label"] == 1)
    lines.append(
        f"| **all** | {counts[('train','montgomery',0)] + counts[('validation','montgomery',0)] + counts[('test','montgomery',0)]} "
        f"| {counts[('train','montgomery',1)] + counts[('validation','montgomery',1)] + counts[('test','montgomery',1)]} "
        f"| {counts[('train','shenzhen',0)] + counts[('validation','shenzhen',0)] + counts[('test','shenzhen',0)]} "
        f"| {counts[('train','shenzhen',1)] + counts[('validation','shenzhen',1)] + counts[('test','shenzhen',1)]} "
        f"| **{total_all}** | **{tb_all / total_all * 100:.1f}%** |"
    )

    modes = Counter(r["mode"] for r in records)
    widths = [r["width"] for r in records]
    heights = [r["height"] for r in records]
    lines += [
        "",
        "## Source characteristics",
        "",
        f"- Colour modes present: {dict(modes)}",
        f"- Width: {min(widths)} to {max(widths)} pixels",
        f"- Height: {min(heights)} to {max(heights)} pixels",
        "- All images are converted to single-channel intensity, resized to"
        " 224 by 224 and repeated across three channels by `ml/preprocessing.py`",
        "",
    ]
    SUMMARY.write_text("\n".join(lines), encoding="utf-8")


def main():
    records, failures = collect()
    print(f"inspected {len(records)} images")
    if failures:
        print(f"  failed to read {len(failures)}:")
        for name, error in failures[:10]:
            print(f"    {name}: {error}")
        return 1

    duplicates = find_duplicates(records)
    print(f"duplicate groups: {len(duplicates)}")
    for group in list(duplicates.values())[:5]:
        print("   ", ", ".join(f"{r['source']}/{r['filename']}" for r in group))

    assign_splits(records)
    write_manifest(records)
    write_summary(records, duplicates)

    print()
    counts = Counter((r["split"], r["label"]) for r in records)
    for split in ("train", "validation", "test"):
        normal, tb = counts[(split, 0)], counts[(split, 1)]
        print(f"  {split:<11} {normal + tb:>4}  (normal {normal:>3}, TB {tb:>3})")
    print(f"  {'total':<11} {len(records):>4}")
    print()
    print(f"manifest -> {MANIFEST.relative_to(ROOT)}")
    print(f"summary  -> {SUMMARY.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
