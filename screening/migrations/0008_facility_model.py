"""
Introduce the clinic as a row, alongside the free text it replaces.

Visibility was decided by comparing the facility typed on each profile with
the one stored on each record. Two spellings of one hospital made two separate
caseloads, and a typo silently hid every record from the person who made it.

The conversion is deliberately three migrations rather than one. Altering a
text column into a foreign key in place asks the database to read "Kenyatta
National Hospital" as a row id, which at best fails and at worst empties the
column. So this adds the new column beside the old one, 0009 copies the data
across, and 0010 removes the old one. Each step is reversible on its own.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("screening", "0007_access_event"),
    ]

    operations = [
        migrations.CreateModel(
            name="Facility",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="Clear this to stop offering the clinic without removing its records.",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["name"], "verbose_name_plural": "Facilities"},
        ),
        migrations.AddField(
            model_name="predictionrecord",
            name="facility_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="records",
                to="screening.facility",
                help_text=(
                    "The clinic this screening belongs to, taken from the profile of "
                    "whoever screened it. Records are visible to that clinic."
                ),
            ),
        ),
        migrations.AddField(
            model_name="profile",
            name="facility_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="staff",
                to="screening.facility",
                limit_choices_to={"is_active": True},
                help_text=(
                    "The clinic you work at. Records are shared with everyone at the "
                    "same clinic. Ask an administrator if yours is not listed."
                ),
            ),
        ),
    ]
