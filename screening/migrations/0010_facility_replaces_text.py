"""
Drop the free-text clinic now that every row points at a facility.

Separate from 0009 so the copy is committed before the source is removed: if
the two were one migration and the rename failed, the names would be gone with
nothing holding them.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("screening", "0009_adopt_facility_names"),
    ]

    operations = [
        migrations.RemoveField(model_name="predictionrecord", name="facility"),
        migrations.RemoveField(model_name="profile", name="facility"),
        migrations.RenameField(
            model_name="predictionrecord", old_name="facility_ref", new_name="facility"
        ),
        migrations.RenameField(
            model_name="profile", old_name="facility_ref", new_name="facility"
        ),
    ]
