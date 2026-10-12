"""
Provenance for an experiment run.

Records what an experiment was actually run against: the exact commit of the
code, whether anything was uncommitted at the time, and a fingerprint of the
dataset split. Without these, a saved metric cannot be tied back to the code and
data that produced it, and the run is not reproducible in any useful sense.

The `code_is_clean` flag matters as much as the commit. A run made with
uncommitted changes cannot be reproduced from the repository, and saying so is
more useful than recording a commit that does not describe what ran.
"""

import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _git(*arguments):
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None


def dataset_fingerprint(manifest=None):
    """Hash the split manifest, so a changed split is visible as a changed run."""
    manifest = Path(manifest or ROOT / "ml" / "artifacts" / "splits.csv")
    if not manifest.exists():
        return None
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()[:16]
    rows = manifest.read_text(encoding="utf-8").count("\n") - 1
    return {"manifest": manifest.name, "sha256_prefix": digest, "images": rows}


def describe(manifest=None):
    """Everything needed to tie this run to a version of the code and data."""
    status = _git("status", "--porcelain")
    return {
        "git_commit": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "code_is_clean": status == "" if status is not None else None,
        "dataset": dataset_fingerprint(manifest),
    }
