"""
Download the Shenzhen No. 3 People's Hospital chest X-ray set.

The bulk archive on openi.nlm.nih.gov was intermittently unavailable and does not
honour range requests, so a failed transfer could not be resumed. This script
fetches the images individually from the National Library of Medicine data
portal instead. It skips anything already on disk, so it can be re-run after an
interruption without repeating work.

The set contains 662 images. The label is carried in the filename suffix: `_0`
for normal and `_1` for TB. The suffix for a given index is not known in advance,
so each index is tried with both.

Usage:
    python ml/scripts/download_shenzhen.py
"""

import sys
import time
from pathlib import Path

import requests

BASE_URL = (
    "https://data.lhncbc.nlm.nih.gov/public/Tuberculosis-Chest-X-ray-Datasets"
    "/Shenzhen-Hospital-CXR-Set/CXR_png"
)
LAST_INDEX = 662
DESTINATION = Path(__file__).resolve().parents[2] / "data" / "raw" / "shenzhen" / "CXR_png"

# The portal is a public research resource. Requests are made one at a time with
# a short pause so the download stays within reasonable use.
PAUSE_SECONDS = 0.15
TIMEOUT_SECONDS = 120
ATTEMPTS_PER_FILE = 4


def existing_names(directory):
    return {path.name for path in directory.glob("CHNCXR_*.png")}


def fetch(session, url, target):
    """Download one image to a temporary name, then move it into place.

    Writing to a temporary file first means an interrupted transfer never leaves
    a truncated image that a later run would mistake for a complete one.
    """
    partial = target.with_suffix(".part")
    with session.get(url, stream=True, timeout=TIMEOUT_SECONDS) as response:
        if response.status_code == 404:
            return False
        response.raise_for_status()
        with open(partial, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 16):
                handle.write(chunk)
    partial.replace(target)
    return True


def main():
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for leftover in DESTINATION.glob("*.part"):
        leftover.unlink()

    already_have = existing_names(DESTINATION)
    print(f"destination: {DESTINATION}")
    print(f"already on disk: {len(already_have)} images")

    session = requests.Session()
    session.headers["User-Agent"] = "tb-screening-capstone/1.0 (academic use)"

    downloaded = 0
    missing = []

    for index in range(1, LAST_INDEX + 1):
        stem = f"CHNCXR_{index:04d}"
        if any(name.startswith(stem) for name in already_have):
            continue

        placed = False
        for label in ("0", "1"):
            name = f"{stem}_{label}.png"
            target = DESTINATION / name

            for attempt in range(1, ATTEMPTS_PER_FILE + 1):
                try:
                    if fetch(session, f"{BASE_URL}/{name}", target):
                        downloaded += 1
                        placed = True
                    break
                except Exception as error:
                    if attempt == ATTEMPTS_PER_FILE:
                        print(f"  {name}: giving up after {attempt} attempts ({error})")
                    else:
                        time.sleep(3 * attempt)
            if placed:
                break

        if not placed:
            missing.append(stem)

        if index % 25 == 0:
            have = len(existing_names(DESTINATION))
            print(f"  index {index:>3}/{LAST_INDEX}  on disk {have:>3}", flush=True)

        time.sleep(PAUSE_SECONDS)

    final = existing_names(DESTINATION)
    normal = sum(1 for name in final if name.endswith("_0.png"))
    tb = sum(1 for name in final if name.endswith("_1.png"))

    print()
    print(f"downloaded this run : {downloaded}")
    print(f"total on disk       : {len(final)}")
    print(f"  normal (_0)       : {normal}")
    print(f"  TB (_1)           : {tb}")
    if missing:
        print(f"not retrieved       : {len(missing)} -> {', '.join(missing[:10])}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
