"""
Views for the screening workflow.

The prediction itself is still a fixed placeholder at this stage. The purpose of
the current phase is to prove that an upload creates a stored record and renders
a result page before any model is connected. Phase 6 replaces
`placeholder_prediction` with the real service call and changes nothing else.
"""

from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import ReviewForm, ScreeningUploadForm
from .models import PredictionRecord, ReviewNote

# Prototype thresholds. These are provisional and will be replaced by values
# justified from validation results in Sprint 3. Every record stores the
# thresholds it was judged under, so earlier results stay interpretable.
DECISION_THRESHOLD = Decimal("0.500")
TRIAGE_LOW_MEDIUM = Decimal("0.500")
TRIAGE_MEDIUM_HIGH = Decimal("0.800")

PLACEHOLDER_MODEL_VERSION = "placeholder-0"


def placeholder_prediction():
    """Return a fixed result so the workflow can be verified without a model.

    Replaced in Phase 6 by the prediction service. The model version is
    deliberately marked so placeholder records can be told apart from real ones.
    """
    return {
        "tb_probability": Decimal("0.5000"),
        "predicted_label": PredictionRecord.PredictedLabel.LIKELY_TB,
        "triage_level": PredictionRecord.TriageLevel.MEDIUM,
        "triage_justification": (
            "Placeholder result. No model is connected at this stage of development."
        ),
        "quality_status": PredictionRecord.QualityStatus.ACCEPTABLE,
        "quality_message": "",
        "model_version": PLACEHOLDER_MODEL_VERSION,
    }


def upload(request):
    if request.method == "POST":
        form = ScreeningUploadForm(request.POST, request.FILES)
        if form.is_valid():
            result = placeholder_prediction()
            with transaction.atomic():
                record = PredictionRecord.objects.create(
                    patient_reference=form.cleaned_data["patient_reference"],
                    xray_image=form.cleaned_data["xray_image"],
                    decision_threshold=DECISION_THRESHOLD,
                    triage_low_medium_threshold=TRIAGE_LOW_MEDIUM,
                    triage_medium_high_threshold=TRIAGE_MEDIUM_HIGH,
                    **result,
                )
            return redirect("screening:case_detail", case_id=record.case_id)
    else:
        form = ScreeningUploadForm()

    return render(
        request,
        "screening/upload.html",
        {
            "form": form,
            "active": "upload",
            "max_upload_mb": settings.MAX_UPLOAD_BYTES // (1024 * 1024),
        },
    )


def case_detail(request, case_id):
    record = get_object_or_404(PredictionRecord, case_id=case_id)

    if request.method == "POST":
        review_form = ReviewForm(request.POST)
        if review_form.is_valid():
            with transaction.atomic():
                ReviewNote.objects.create(
                    record=record,
                    reviewer_name=review_form.cleaned_data["reviewer_name"],
                    note=review_form.cleaned_data["note"],
                    status_set=review_form.cleaned_data["status_set"],
                )
                record.review_status = review_form.cleaned_data["status_set"]
                record.save(update_fields=["review_status", "updated_at"])
            return redirect("screening:case_detail", case_id=record.case_id)
    else:
        review_form = ReviewForm(initial={"status_set": record.review_status})

    return render(
        request,
        "screening/case_detail.html",
        {
            "record": record,
            "review_form": review_form,
            "notes": record.review_notes.all(),
            "active": "cases",
        },
    )


def case_list(request):
    records = PredictionRecord.objects.all()

    reference = request.GET.get("reference", "").strip()
    if reference:
        records = records.filter(patient_reference__icontains=reference)

    triage = request.GET.get("triage", "")
    if triage in PredictionRecord.TriageLevel.values:
        records = records.filter(triage_level=triage)

    paginator = Paginator(records, 25)
    page = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "screening/case_list.html",
        {
            "page": page,
            "reference": reference,
            "triage": triage,
            "triage_choices": PredictionRecord.TriageLevel.choices,
            "active": "cases",
        },
    )


def dashboard(request):
    records = PredictionRecord.objects.all()
    total = records.count()

    by_label = dict(
        records.values_list("predicted_label").annotate(n=Count("id")).order_by()
    )
    by_triage = dict(
        records.values_list("triage_level").annotate(n=Count("id")).order_by()
    )

    week_ago = timezone.now() - timedelta(days=7)

    triage_counts = [
        (label, by_triage.get(value, 0))
        for value, label in PredictionRecord.TriageLevel.choices
    ]

    # Screening activity over the last fortnight, including days with no
    # activity so the chart shows real gaps rather than compressing them away.
    first_day = (timezone.localtime() - timedelta(days=13)).date()
    per_day = dict(
        records.filter(created_at__date__gte=first_day)
        .annotate(day=TruncDate("created_at"))
        .values_list("day")
        .annotate(n=Count("id"))
        .order_by()
    )
    activity = [
        {
            "label": f"{(first_day + timedelta(days=offset)).day} "
            f"{(first_day + timedelta(days=offset)):%b}",
            "count": per_day.get(first_day + timedelta(days=offset), 0),
        }
        for offset in range(14)
    ]

    return render(
        request,
        "screening/dashboard.html",
        {
            "total": total,
            "likely": by_label.get(PredictionRecord.PredictedLabel.LIKELY_TB, 0),
            "unlikely": by_label.get(PredictionRecord.PredictedLabel.UNLIKELY_TB, 0),
            "triage_counts": triage_counts,
            "triage_labels": [label for label, _ in triage_counts],
            "triage_values": [count for _, count in triage_counts],
            "activity_labels": [day["label"] for day in activity],
            "activity_values": [day["count"] for day in activity],
            "recent": records.filter(created_at__gte=week_ago).count(),
            "follow_up": records.filter(
                review_status=PredictionRecord.ReviewStatus.FOLLOW_UP
            ).count(),
            "pending": records.filter(
                review_status=PredictionRecord.ReviewStatus.PENDING
            ).count(),
            "latest": records[:8],
            "active": "dashboard",
        },
    )
