"""
Back up to Google Drive everything that Git does not hold.

Code and its history live in GitHub. This script covers the rest, so the
project can be rebuilt on another machine if this one is lost:

    datasets.zip          Montgomery and Shenzhen images, as one archive
    ml/models/            trained models
    ml/artifacts/         split manifest, metrics and evaluation figures
    media/                uploaded radiographs and generated heatmaps
    database/             a plain-SQL dump of the PostgreSQL database

The target is a folder inside Google Drive for desktop, which uploads it to the
cloud on its own. Only new or changed files are copied, so later runs are quick.
The `.env` file is deliberately not copied: it holds credentials.

The datasets are stored as a single archive because Colab reads one large file
from Drive far faster than 800 small ones.

Usage:
    python scripts/backup_to_drive.py
    python scripts/backup_to_drive.py --dry-run
    python scripts/backup_to_drive.py --target "D:\\My Drive\\tb-screening-system"
"""

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = Path(os.environ.get("DRIVE_BACKUP_DIR", r"G:\My Drive\tb-screening-system"))

DATASET_DIRS = [ROOT / "data/raw/montgomery", ROOT / "data/raw/shenzhen"]
MIRRORED = ["ml/models", "ml/artifacts", "media"]


def files_under(directories):
    return [p for d in directories if d.is_dir() for p in d.rglob("*") if p.is_file()]


def archive_datasets(target, dry_run):
    """Rewrite datasets.zip only when an image is newer than the archive."""
    files = files_under(DATASET_DIRS)
    if not files:
        print("  datasets      none found under data/raw, skipped")
        return

    archive = target / "datasets.zip"
    newest = max(p.stat().st_mtime for p in files)
    if archive.exists() and archive.stat().st_mtime >= newest:
        print(f"  datasets      unchanged ({len(files)} files)")
        return

    print(f"  datasets      writing archive of {len(files)} files")
    if dry_run:
        return

    # Written under a temporary name and moved into place, so Drive never
    # uploads a half-written archive.
    partial = archive.with_suffix(".zip.part")
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_STORED) as bundle:
        for path in files:
            bundle.write(path, arcname=path.relative_to(ROOT).as_posix())
    partial.replace(archive)


def mirror(folder, target, dry_run):
    """Copy files that are missing from the target or have changed."""
    source = ROOT / folder
    if not source.is_dir():
        print(f"  {folder:<13} not present, skipped")
        return

    copied = 0
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        destination = target / folder / path.relative_to(source)
        current = destination.exists() and (
            destination.stat().st_size == path.stat().st_size
            and destination.stat().st_mtime >= path.stat().st_mtime
        )
        if current:
            continue
        copied += 1
        if not dry_run:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
    print(f"  {folder:<13} {copied} file{'s' if copied != 1 else ''} copied")


def dump_database(target, dry_run):
    """Write a plain-SQL dump that can be restored with psql."""
    load_dotenv(ROOT / ".env")
    if not shutil.which("pg_dump"):
        print("  database      pg_dump not found, skipped")
        return

    name = os.environ.get("DB_NAME")
    if not name:
        print("  database      no DB_NAME in .env, skipped")
        return

    stamp = datetime.now().strftime("%Y-%m-%d")
    destination = target / "database" / f"{name}_{stamp}.sql"
    print(f"  database      dumping {name} to {destination.name}")
    if dry_run:
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "PGPASSWORD": os.environ.get("DB_PASSWORD", "")}
    subprocess.run(
        [
            "pg_dump",
            "--host",
            os.environ.get("DB_HOST", "localhost"),
            "--port",
            os.environ.get("DB_PORT", "5432"),
            "--username",
            os.environ.get("DB_USER", ""),
            "--dbname",
            name,
            "--no-owner",
            "--clean",
            "--if-exists",
            "--file",
            str(destination),
        ],
        env=environment,
        check=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--dry-run", action="store_true", help="report without copying")
    args = parser.parse_args()

    target = args.target
    if not target.parent.exists():
        print(f"Drive folder not found: {target.parent}")
        print("Install Google Drive for desktop and sign in, or pass --target.")
        return 1

    if not args.dry_run:
        target.mkdir(parents=True, exist_ok=True)

    print(f"backing up to {target}{'  (dry run)' if args.dry_run else ''}")
    archive_datasets(target, args.dry_run)
    for folder in MIRRORED:
        mirror(folder, target, args.dry_run)
    dump_database(target, args.dry_run)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
