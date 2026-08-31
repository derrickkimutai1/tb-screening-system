"""
Database models for the screening prototype.

A PredictionRecord is written once per screening event and holds the facts of
that screening: the uploaded image, the quality assessment, the model output,
the triage decision, and the thresholds that decision was made under. Review
activity is kept in a separate ReviewNote table so that a case carries a review
history rather than a single overwritten field.
"""

import uuid
from pathlib import Path

from django.db import models
from django.utils import timezone


def xray_upload_path(instance, filename):
    """Store uploads under a date folder, named by case reference."""
    suffix = Path(filename).suffix.lower() or ".png"
    return f"uploads/{timezone.now():%Y/%m}/{instance.case_id}{suffix}"


def heatmap_upload_path(instance, filename):
    """Grad-CAM overlays are always written as PNG."""
    return f"heatmaps/{timezone.now():%Y/%m}/{instance.case_id}.png"


class PredictionRecord(models.Model):
    """A single chest X-ray screening event and its stored outcome."""

    class QualityStatus(models.TextChoices):
        ACCEPTABLE = "ACCEPTABLE", "Acceptable"
        DEGRADED = "DEGRADED", "Degraded"
        INVALID = "INVALID", "Invalid"

    class PredictedLabel(models.TextChoices):
        LIKELY_TB = "LIKELY_TB", "Likely TB"
        UNLIKELY_TB = "UNLIKELY_TB", "Unlikely TB"

    class TriageLevel(models.TextChoices):
        LOW = "LOW", "Low suspicion"
        MEDIUM = "MEDIUM", "Medium suspicion"
        HIGH = "HIGH", "High suspicion"

    class GradcamStatus(models.TextChoices):
        GENERATED = "GENERATED", "Generated"
        FAILED = "FAILED", "Failed"
        NOT_ATTEMPTED = "NOT_ATTEMPTED", "Not attempted"

    class ReviewStatus(models.TextChoices):
        PENDING = "PENDING", "Pending review"
        REVIEWED = "REVIEWED", "Reviewed"
        FOLLOW_UP = "FOLLOW_UP", "Follow-up required"

    # Identity
    case_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    patient_reference = models.CharField(
        max_length=32,
        db_index=True,
        help_text="Non-identifying case reference, for example DEMO-001.",
    )

    # Uploaded image
    xray_image = models.ImageField(upload_to=xray_upload_path)

    # Image quality assessment
    quality_status = models.CharField(max_length=16, choices=QualityStatus.choices)
    quality_message = models.CharField(max_length=200, blank=True)
    blur_score = models.FloatField(
        null=True,
        blank=True,
        help_text="Variance of the Laplacian. Lower values indicate a blurrier image.",
    )
    brightness_mean = models.FloatField(
        null=True,
        blank=True,
        help_text="Mean pixel intensity of the greyscale image, 0 to 255.",
    )

    # Model output
    predicted_label = models.CharField(max_length=16, choices=PredictedLabel.choices)
    tb_probability = models.DecimalField(max_digits=5, decimal_places=4)
    decision_threshold = models.DecimalField(max_digits=4, decimal_places=3)

    # Triage, derived from the probability rather than from a second model
    triage_level = models.CharField(
        max_length=8, choices=TriageLevel.choices, db_index=True
    )
    triage_justification = models.TextField(blank=True)
    triage_low_medium_threshold = models.DecimalField(max_digits=4, decimal_places=3)
    triage_medium_high_threshold = models.DecimalField(max_digits=4, decimal_places=3)

    # Explainability
    gradcam_image = models.ImageField(
        upload_to=heatmap_upload_path, null=True, blank=True
    )
    gradcam_status = models.CharField(
        max_length=16,
        choices=GradcamStatus.choices,
        default=GradcamStatus.NOT_ATTEMPTED,
    )

    # Provenance
    model_version = models.CharField(max_length=64)
    inference_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Inference time on this machine, used to evidence CPU suitability.",
    )

    # Review workflow
    review_status = models.CharField(
        max_length=16,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PENDING,
        db_index=True,
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Prediction record"
        indexes = [
            models.Index(
                fields=["review_status", "-created_at"],
                name="pred_review_created_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(tb_probability__gte=0) & models.Q(tb_probability__lte=1),
                name="tb_probability_within_zero_to_one",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    triage_low_medium_threshold__lt=models.F(
                        "triage_medium_high_threshold"
                    )
                ),
                name="triage_thresholds_ordered",
            ),
        ]

    def __str__(self):
        return f"{self.patient_reference} - {self.get_predicted_label_display()}"

    @property
    def probability_percent(self):
        """Probability as a percentage. Kept as Decimal so display stays exact."""
        return self.tb_probability * 100

    @property
    def triage_css_class(self):
        """Modifier class for the triage marker. Colour always accompanies the label."""
        return {
            self.TriageLevel.LOW: "triage-low",
            self.TriageLevel.MEDIUM: "triage-medium",
            self.TriageLevel.HIGH: "triage-high",
        }.get(self.triage_level, "triage-low")

    @property
    def has_explanation(self):
        return bool(self.gradcam_image) and self.gradcam_status == self.GradcamStatus.GENERATED


class ReviewNote(models.Model):
    """A reviewer's note against a case, kept as an append-only history."""

    record = models.ForeignKey(
        PredictionRecord,
        on_delete=models.CASCADE,
        related_name="review_notes",
    )
    reviewer_name = models.CharField(max_length=100, blank=True)
    note = models.TextField()
    status_set = models.CharField(
        max_length=16,
        choices=PredictionRecord.ReviewStatus.choices,
        help_text="Review status the reviewer set when this note was written.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        who = self.reviewer_name or "Unnamed reviewer"
        return f"{who} on {self.record.patient_reference}"
