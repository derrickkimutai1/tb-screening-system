"""
Make Grad-CAM the explanation on records that already exist.

SO4 names Grad-CAM, and the system now shows it as the explanation with the
occlusion map beside it as the comparison. Records screened before that change
hold the opposite arrangement: the occlusion map in explanation_image and the
Grad-CAM in comparison_image.

Leaving them would mean two kinds of record in one caseload, and a case page
whose labels contradict the picture above them. The two are swapped instead,
images and method names together, so every record reads the same way.

Nothing is regenerated and no pixel changes. Both maps were produced from the
same radiograph by the same model; only which field holds which moves. A
record carrying just one of the two is left alone, because there is nothing to
swap it with and guessing which method made it would be worse than leaving the
method name that was recorded at the time.
"""

from django.db import migrations


def swap(apps, schema_editor):
    PredictionRecord = apps.get_model("screening", "PredictionRecord")

    both = PredictionRecord.objects.exclude(explanation_image="").exclude(
        comparison_image=""
    )
    for record in both.exclude(comparison_image=None).iterator():
        explanation, comparison = record.explanation_image, record.comparison_image
        method, other = record.explanation_method, record.comparison_method
        PredictionRecord.objects.filter(pk=record.pk).update(
            explanation_image=comparison,
            explanation_method=other,
            comparison_image=explanation,
            comparison_method=method,
        )


class Migration(migrations.Migration):
    dependencies = [("screening", "0015_comparison_explanation")]

    # Swapping twice restores the original arrangement, so the same function
    # reverses it.
    operations = [migrations.RunPython(swap, swap)]
