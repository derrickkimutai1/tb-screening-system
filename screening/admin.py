from django.contrib import admin

from .models import PredictionRecord, ReviewNote


class ReviewNoteInline(admin.TabularInline):
    model = ReviewNote
    extra = 0
    readonly_fields = ["created_at"]


@admin.register(PredictionRecord)
class PredictionRecordAdmin(admin.ModelAdmin):
    list_display = [
        "patient_reference",
        "predicted_label",
        "tb_probability",
        "triage_level",
        "quality_status",
        "review_status",
        "model_version",
        "created_at",
    ]
    list_filter = [
        "predicted_label",
        "triage_level",
        "review_status",
        "quality_status",
        "model_version",
    ]
    search_fields = ["patient_reference", "case_id"]
    date_hierarchy = "created_at"
    inlines = [ReviewNoteInline]

    # Prediction output is a record of what the model did and is not editable
    # after the fact. Only the review workflow fields can be changed here.
    readonly_fields = [
        "case_id",
        "xray_image",
        "quality_status",
        "quality_message",
        "blur_score",
        "brightness_mean",
        "predicted_label",
        "tb_probability",
        "decision_threshold",
        "triage_level",
        "triage_justification",
        "triage_low_medium_threshold",
        "triage_medium_high_threshold",
        "gradcam_image",
        "gradcam_status",
        "model_version",
        "inference_ms",
        "created_at",
        "updated_at",
    ]


@admin.register(ReviewNote)
class ReviewNoteAdmin(admin.ModelAdmin):
    list_display = ["record", "reviewer_name", "status_set", "created_at"]
    list_filter = ["status_set"]
    search_fields = ["reviewer_name", "note", "record__patient_reference"]
