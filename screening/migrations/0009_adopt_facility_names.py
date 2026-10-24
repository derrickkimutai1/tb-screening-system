"""
Turn the clinic names people typed into rows, and point everything at them.

Names are matched case-insensitively and with surrounding space removed, so
"Kenyatta National Hospital" and " kenyatta national hospital " become one
clinic rather than two. That merging is the whole point of the change: the
spellings that were separate caseloads become the same one.

The first spelling seen is the one kept, because there is nothing better to go
on and an administrator can rename it afterwards.
"""

from django.db import migrations


def adopt(apps, schema_editor):
    Facility = apps.get_model("screening", "Facility")
    Profile = apps.get_model("screening", "Profile")
    PredictionRecord = apps.get_model("screening", "PredictionRecord")

    names = set()
    for model in (Profile, PredictionRecord):
        names.update(
            value.strip()
            for value in model.objects.values_list("facility", flat=True)
            if value and value.strip()
        )

    by_key = {}
    for name in sorted(names):
        key = name.casefold()
        if key not in by_key:
            by_key[key], _ = Facility.objects.get_or_create(name=name)

    for model in (Profile, PredictionRecord):
        for row in model.objects.exclude(facility=""):
            facility = by_key.get((row.facility or "").strip().casefold())
            if facility is not None:
                model.objects.filter(pk=row.pk).update(facility_ref=facility.pk)


def unadopt(apps, schema_editor):
    """Write the names back into the text column, then drop the rows.

    Reversing has to leave the text column as it found it, or going backwards
    would lose what going forwards preserved.
    """
    Facility = apps.get_model("screening", "Facility")
    Profile = apps.get_model("screening", "Profile")
    PredictionRecord = apps.get_model("screening", "PredictionRecord")

    for model in (Profile, PredictionRecord):
        for row in model.objects.exclude(facility_ref__isnull=True):
            name = Facility.objects.filter(pk=row.facility_ref_id).values_list(
                "name", flat=True
            ).first()
            model.objects.filter(pk=row.pk).update(facility=name or "")
    Facility.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("screening", "0008_facility_model"),
    ]

    operations = [
        migrations.RunPython(adopt, unadopt),
    ]
