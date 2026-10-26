from django.contrib import admin

from .models import AccessEvent, Facility, PredictionRecord, Profile, ReviewNote


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
        "explanation_image",
        "explanation_status",
        "explanation_method",
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


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    """Where roles are assigned.

    Role is deliberately not editable by its owner, so this is the only place
    a user becomes a clinician or an administrator.
    """

    list_display = ["display_name", "role", "facility", "may_review", "created_at"]
    list_filter = ["role", "facility"]
    search_fields = ["user__email", "user__username", "facility"]
    autocomplete_fields = ["user"]
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(boolean=True, description="May review")
    def may_review(self, profile):
        return profile.may_review

    @admin.display(description="Name")
    def display_name(self, profile):
        return profile.display_name


@admin.register(AccessEvent)
class AccessEventAdmin(admin.ModelAdmin):
    """The audit trail, readable and not writable.

    Every field is read-only and neither adding nor changing is permitted, so
    the log cannot be edited through the interface that displays it. Deleting
    is left to a superuser, because a retention policy eventually has to remove
    old rows and that has to happen somewhere.
    """

    list_display = ["created_at", "actor_label", "action", "facility", "case_id", "ip_address"]
    list_filter = ["action", "facility", "created_at"]
    search_fields = ["actor_label", "case_id", "detail", "ip_address"]
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in AccessEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # Retention has to be possible, but only for someone who can already
        # reach everything.
        return request.user.is_superuser


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    """Where the list of clinics is maintained.

    Users pick from this list and cannot add to it, which is the point: a
    clinic typed freely produced two caseloads out of one spelling mistake.
    """

    list_display = ["name", "is_active", "staff_count", "record_count", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name"]
    readonly_fields = ["created_at"]

    @admin.display(description="Staff")
    def staff_count(self, facility):
        return facility.staff.count()

    @admin.display(description="Records")
    def record_count(self, facility):
        return facility.records.count()

    def has_delete_permission(self, request, obj=None):
        # A clinic holding records cannot be removed; retire it instead, which
        # stops it being offered without touching what it holds.
        if obj is not None and obj.records.exists():
            return False
        return super().has_delete_permission(request, obj)
