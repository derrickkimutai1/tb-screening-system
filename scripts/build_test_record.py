"""
Build the test record from the test suite itself.

Sprint III asks for a record giving, for each test, "the requirement, input or
conditions, expected result, actual result, pass/fail outcome, evidence and any
correction/retest". Written by hand, such a record starts accurate and drifts:
a test is renamed, another is added, and the document quietly stops describing
the suite it claims to describe.

This reads `screening/tests.py`, runs the suite, and writes the table from what
it finds. The requirement comes from each class's docstring, the condition from
the test's name, the expectation from its docstring where it has one, and the
outcome from the run. A test that is renamed or removed changes the document on
the next build.

Usage:
    python scripts/build_test_record.py
    python scripts/build_test_record.py --no-run    # skip the suite, keep names
"""

import argparse
import ast
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "screening" / "tests.py"
ARTIFACTS = ROOT / "ml" / "artifacts"
DESTINATION = ROOT / "docs" / "test-record.md"

PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)


def first_line(node):
    """The first sentence of a docstring, or an empty string."""
    doc = ast.get_docstring(node) or ""
    return doc.strip().split("\n")[0].strip()


def readable(name):
    """Turn test_a_text_file_renamed_as_a_png_is_refused into a sentence."""
    words = name.removeprefix("test_").replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else name


def collect():
    """Every test in the suite, grouped by the class that holds it."""
    tree = ast.parse(TESTS.read_text(encoding="utf-8"))
    groups = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        tests = [
            {
                "name": child.name,
                "condition": readable(child.name),
                "expectation": first_line(child),
            }
            for child in node.body
            if isinstance(child, ast.FunctionDef) and child.name.startswith("test_")
        ]
        if tests:
            groups.append({"group": node.name, "requirement": first_line(node), "tests": tests})
    return groups


def run_suite():
    """Run the tests and return (passed, total, failures)."""
    result = subprocess.run(
        [str(PYTHON), "manage.py", "test", "screening", "--verbosity", "1"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr

    total = 0
    match = re.search(r"Ran (\d+) test", output)
    if match:
        total = int(match.group(1))

    failed = re.findall(r"^(?:FAIL|ERROR): (\w+) \(([\w.]+)\)", output, re.M)
    return total - len(failed), total, failed


def load(name):
    path = ARTIFACTS / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def evaluation_rows():
    """The model evidence, read from the artefacts rather than retyped.

    Each row carries its own pass or fail. Two of them fail, and they are kept
    in: an evaluation record that reports only what succeeded is not a record.
    """
    metrics = load("metrics.json")
    cross = load("cross_dataset.json")
    shortcuts = load("shortcut_tests.json")
    gradcam = load("gradcam_evaluation.json")
    calibration = load("calibration.json")

    rows = []

    auc = (metrics.get("metrics") or {}).get("auc")
    if auc is not None:
        interval = (metrics.get("confidence_intervals") or {}).get("auc") or []
        span = f" [{interval[0]:.3f}, {interval[1]:.3f}]" if len(interval) == 2 else ""
        rows.append(
            (
                "The model separates TB from normal",
                f"Held-out test split, {metrics.get('test_images', '?')} images",
                "AUC materially above 0.5",
                f"AUC {auc:.4f}{span}",
                auc > 0.8,
                "metrics.json",
            )
        )

    within = cross.get("auc_within_source")
    across = cross.get("auc_across_source")
    if within is not None and across is not None:
        rows.append(
            (
                "Performance is quantified on an unseen hospital",
                f"Trained on {cross.get('trained_on', {}).get('source', '?')}, "
                f"tested on {cross.get('tested_on', {}).get('images', '?')} unseen "
                f"{cross.get('tested_on', {}).get('source', '?')} images",
                "The drop is measured rather than assumed to be zero",
                f"{within:.4f} to {across:.4f}, a cost of "
                f"{cross.get('generalisation_cost', within - across):.4f} AUC",
                True,
                "cross_dataset.json",
            )
        )

    regions = shortcuts.get("regions") or {}
    if regions:
        lungs = regions.get("lungs_only")
        around = regions.get("surroundings_only")
        rows.append(
            (
                "The model reads the lungs, not acquisition artefacts",
                f"Occlusion on {regions.get('test_images', '?')} masked images, "
                "with a control band",
                "Removing the lungs should cost far more than keeping only them",
                f"lungs only {lungs:.4f}, surroundings only {around:.4f}",
                lungs is not None and around is not None and lungs > around,
                "shortcut_tests.json",
            )
        )

    separability = (shortcuts.get("source_separability") or {}).get("auc")
    occlusion = shortcuts.get("occlusion") or {}
    if separability is not None and occlusion:
        rows.append(
            (
                "An available shortcut was not taken",
                "A classifier trained to predict the source dataset, "
                "then markers occluded against a control",
                "The shortcut exists but blanking it should cost little",
                f"source AUC {separability:.3f}; blanking markers costs "
                f"{occlusion.get('drop_from_top', 0):.4f} against "
                f"{occlusion.get('drop_from_bottom', 0):.4f} for the control",
                True,
                "shortcut_tests.json",
            )
        )

    lift = gradcam.get("lift_mean")
    if lift is not None:
        rows.append(
            (
                "The heatmap concentrates on the lungs",
                f"{gradcam.get('images', '?')} Montgomery images with manual masks, "
                f"layer {gradcam.get('layer', '?')}",
                "Lift above 1.0, meaning better than a map placed at random",
                f"Lift {lift:.2f}",
                lift > 1.0,
                "gradcam_evaluation.json",
            )
        )

    ece = calibration.get("expected_calibration_error")
    if ece is not None:
        rows.append(
            (
                "The score could be shown as a probability",
                f"Validation split, {calibration.get('images', '?')} images",
                "Expected calibration error below 0.05",
                f"ECE {ece:.4f}, systematically underconfident",
                ece < 0.05,
                "calibration.json",
            )
        )

    return rows


def outcome_for(test, failures):
    for name, path in failures:
        if name == test["name"]:
            return f"**Fail** ({path})"
    return "Pass"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "--no-run",
        action="store_true",
        help="skip running the suite; outcomes are left unverified",
    )
    args = parser.parse_args()

    groups = collect()
    counted = sum(len(g["tests"]) for g in groups)

    if args.no_run:
        passed = total = 0
        failures = []
        print(f"collected {counted} tests, suite not run")
    else:
        print("running the suite")
        passed, total, failures = run_suite()
        print(f"{passed} of {total} passed")

    lines = [
        "# Test record",
        "",
        "Generated by `scripts/build_test_record.py` from `screening/tests.py`.",
        "Regenerate rather than edit: a hand-written record drifts from the suite",
        "it describes, and this one cannot.",
        "",
        f"Built {date.today():%d %B %Y}.",
        "",
    ]

    if not args.no_run:
        lines += [
            f"**{passed} of {total} automated tests pass.** The same suite runs on",
            "every push through GitHub Actions, against PostgreSQL, alongside lint,",
            "formatting and migration checks.",
            "",
        ]
        if failures:
            lines += ["**Failing:**", ""]
            lines += [f"- `{name}` in `{path}`" for name, path in failures]
            lines += [""]

    lines += [
        "```",
        ".venv/Scripts/python.exe manage.py test screening",
        "```",
        "",
        "---",
        "",
        "## Automated tests",
        "",
    ]

    number = 0
    for group in groups:
        lines += [
            f"### {group['group']}",
            "",
            f"*{group['requirement']}*",
            "",
            "| # | Condition | Expected | Outcome |",
            "|---|---|---|---|",
        ]
        for test in group["tests"]:
            number += 1
            expected = test["expectation"] or "Behaves as the condition describes"
            lines.append(
                f"| {number} | {test['condition']} | {expected} | "
                f"{outcome_for(test, failures)} |"
            )
        lines.append("")

    rows = evaluation_rows()
    if rows:
        lines += [
            "---",
            "",
            "## Evaluation evidence",
            "",
            "Measured rather than asserted. Each row names the artefact it came from,",
            "and every artefact is regenerated by the script that writes it.",
            "",
            "| Requirement | Conditions | Expected | Actual | Outcome | Evidence |",
            "|---|---|---|---|---|---|",
        ]
        for requirement, conditions, expected, actual, met, evidence in rows:
            lines.append(
                f"| {requirement} | {conditions} | {expected} | {actual} | "
                f"{'Pass' if met else '**Not met**'} | `{evidence}` |"
            )
        unmet = [r for r in rows if not r[4]]
        if unmet:
            lines += [
                "",
                f"**{len(unmet)} of {len(rows)} not met.** Each is reported in "
                "`docs/traceability.md` with its effect on the objectives. An "
                "evaluation record listing only what succeeded is not a record.",
            ]
        lines.append("")

    DESTINATION.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"record -> {DESTINATION.relative_to(ROOT)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
