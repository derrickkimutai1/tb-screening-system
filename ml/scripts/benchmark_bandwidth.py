"""How many bytes one screening puts on the wire.

The proposal's low-resource section names high-bandwidth internet as one of
the two things that cannot be assumed at a less-resourced Kenyan facility.
The model size answers the other one. This answers this one, and until now it
was not measured at all.

Two figures matter and they are different. The first visit to the application
carries the interface with it: stylesheet, scripts, fonts. Every visit after
that is served from the browser cache, so a clinic on a slow link pays the
interface once and the screening traffic thereafter.

Measured through Django's test client, which runs the real middleware, views,
templates and database. It does not include TLS overhead, HTTP headers or
compression, so the figures describe payload rather than packets. Compression
in particular would reduce the HTML and the stylesheet substantially and does
not touch the radiographs, which dominate.

    .venv/Scripts/python.exe ml/scripts/benchmark_bandwidth.py
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")


def kb(n):
    return round(n / 1024, 1)


def main():
    import django

    django.setup()

    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.test import Client
    from django.test.utils import setup_test_environment

    from screening.models import PredictionRecord, Profile

    setup_test_environment()

    films = sorted((ROOT / "data/raw/montgomery/MontgomerySet/CXR_png").glob("*.png"))
    if not films:
        sys.exit("no radiographs to screen")
    film = films[0]

    User = get_user_model()
    user = User.objects.filter(profile__role=Profile.Role.RADIOGRAPHER).first()
    if user is None:
        sys.exit("no radiographer account to screen as")

    client = Client()
    client.force_login(user)

    # The interface, paid once per browser.
    page = client.get("/")
    shell = len(page.content)
    assets = {}
    static_root = Path(settings.BASE_DIR) / "screening" / "static" / "screening"
    for name in ("theme.css", "vendor/bootstrap.min.css", "vendor/bootstrap.bundle.min.js"):
        path = static_root / name
        if path.exists():
            assets[name] = path.stat().st_size
    fonts = static_root / "vendor" / "fonts"
    font_bytes = (
        sum(f.stat().st_size for f in fonts.rglob("*") if f.is_file()) if fonts.exists() else 0
    )

    # One screening.
    upload_bytes = film.stat().st_size
    reference = "BANDWIDTH-01"
    with film.open("rb") as handle:
        result = client.post(
            "/", {"patient_reference": reference, "xray_image": handle}, follow=True
        )
    result_html = len(result.content)

    record = PredictionRecord.objects.filter(patient_reference=reference).first()
    if record is None:
        sys.exit("the screening did not produce a record")

    media = Path(settings.MEDIA_ROOT)
    images = {}
    for label, field in (
        ("radiograph", record.xray_image),
        ("heatmap", record.explanation_image),
        ("occlusion", record.comparison_image),
    ):
        if field:
            path = media / field.name
            if path.exists():
                images[label] = path.stat().st_size

    worklist = len(client.get("/worklist/").content)

    # Leave nothing behind.
    for field in (record.xray_image, record.explanation_image, record.comparison_image):
        if field:
            path = media / field.name
            if path.exists():
                path.unlink()
    record.delete()

    first_visit = shell + sum(assets.values()) + font_bytes
    per_screening = upload_bytes + result_html + sum(images.values())

    result_json = {
        "measures": "payload bytes for the first visit and for one complete screening",
        "first_visit": {
            "page_html_bytes": shell,
            "stylesheets_and_scripts_bytes": sum(assets.values()),
            "fonts_bytes": font_bytes,
            "total_bytes": first_visit,
            "total_kb": kb(first_visit),
            "note": "Served from the browser cache on every later visit.",
        },
        "one_screening": {
            "upload_bytes": upload_bytes,
            "upload_mb": round(upload_bytes / (1024**2), 2),
            "result_page_html_bytes": result_html,
            "images_returned_bytes": sum(images.values()),
            "images_returned": {k: kb(v) for k, v in images.items()},
            "total_bytes": per_screening,
            "total_mb": round(per_screening / (1024**2), 2),
        },
        "worklist_page_html_bytes": worklist,
        "film_used": film.name,
        "note": (
            "Measured through Django's test client over the real middleware, "
            "views, templates and database. Payload only: no TLS overhead, no "
            "HTTP headers and no compression, which would reduce the HTML and "
            "the stylesheet substantially and would not touch the "
            "radiographs. The upload dominates, and the radiograph that "
            "comes back dominates again, so the practical lever on a slow "
            "link is image size rather than anything in the interface."
        ),
    }

    out = ROOT / "ml" / "artifacts" / "bandwidth_benchmark.json"
    out.write_text(json.dumps(result_json, indent=2), encoding="utf-8", newline="")

    print(f"first visit    {kb(first_visit)} KB (cached afterwards)")
    print(f"one screening  {round(per_screening / (1024**2), 2)} MB")
    print(f"  upload       {round(upload_bytes / (1024**2), 2)} MB")
    print(f"  result page  {kb(result_html)} KB")
    print(f"  images back  {kb(sum(images.values()))} KB")
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
