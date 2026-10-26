"""
Rename the explanation fields away from the method that used to produce them.

The heatmap was Grad-CAM, so the columns were called gradcam_image and
gradcam_status. It is now an occlusion map, and a column named after one
method holding the output of another is how a reader is misled a year later.

Renames rather than drops and adds, so every stored heatmap and its status
survive. The method that produced each existing image is written into the new
explanation_method column, because those rows really were Grad-CAM and must
not be read as though they came from the current pipeline.
"""

from django.db import migrations, models

import screening.models


def record_the_old_method(apps, schema_editor):
    """Everything already generated came from Grad-CAM. Say so."""
    PredictionRecord = apps.get_model("screening", "PredictionRecord")
    PredictionRecord.objects.filter(explanation_status="GENERATED").update(
        explanation_method="gradcam"
    )


def forget_the_old_method(apps, schema_editor):
    PredictionRecord = apps.get_model("screening", "PredictionRecord")
    PredictionRecord.objects.update(explanation_method="")


class Migration(migrations.Migration):
    dependencies = [("screening", "0012_seal_existing_audit_rows")]

    operations = [
        migrations.RenameField(
            model_name="predictionrecord",
            old_name="gradcam_image",
            new_name="explanation_image",
        ),
        migrations.RenameField(
            model_name="predictionrecord",
            old_name="gradcam_status",
            new_name="explanation_status",
        ),
        migrations.AddField(
            model_name="predictionrecord",
            name="explanation_method",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AlterField(
            model_name="predictionrecord",
            name="explanation_image",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to=screening.models.heatmap_upload_path,
            ),
        ),
        migrations.AlterField(
            model_name="predictionrecord",
            name="explanation_status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Not yet generated"),
                    ("GENERATED", "Generated"),
                    ("FAILED", "Failed"),
                    ("NOT_ATTEMPTED", "Not attempted"),
                ],
                default="PENDING",
                max_length=16,
            ),
        ),
        migrations.RunPython(record_the_old_method, forget_the_old_method),
    ]
