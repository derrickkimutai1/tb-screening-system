"""
Give the records that predate facilities somewhere to live.

Visibility is now scoped by facility, and every record created before this
migration has none. Left as they are they would be visible only to users who
also have no facility, which is nobody once people fill their profile in, so
the existing caseload would quietly disappear from the interface.

They are adopted by the facility of the longest-standing administrator or
clinician, because that is whose clinic they were screened at in practice.
Falling back to the oldest account covers an installation where nobody has a
role yet. If no account has a facility either, they are left unscoped, which
is correct: there is no clinic to assign them to, and inventing one would be
worse than leaving them where only an administrator can see them.
"""

from django.db import migrations


def adopt(apps, schema_editor):
    PredictionRecord = apps.get_model("screening", "PredictionRecord")
    Profile = apps.get_model("screening", "Profile")

    orphaned = PredictionRecord.objects.filter(facility="")
    if not orphaned.exists():
        return

    owner = (
        Profile.objects.exclude(facility="")
        .filter(role__in=["administrator", "clinician"])
        .order_by("created_at")
        .first()
        or Profile.objects.exclude(facility="").order_by("created_at").first()
    )
    if owner is None:
        return

    orphaned.update(facility=owner.facility, screened_by=owner.user_id)


def unassign(apps, schema_editor):
    # Reversing puts them back where they were: unscoped, which is what the
    # column meant before this ran.
    PredictionRecord = apps.get_model("screening", "PredictionRecord")
    PredictionRecord.objects.update(facility="", screened_by=None)


class Migration(migrations.Migration):
    dependencies = [
        ("screening", "0005_record_facility_and_screener"),
    ]

    operations = [
        migrations.RunPython(adopt, unassign),
    ]
