"""
Views for the screening workflow.

The upload view coordinates the services in the order set out in the proposal's
activity diagram: quality check, preprocessing, prediction, triage, explanation,
then storage. The services themselves know nothing about the database; this is
where their results are persisted.
"""

import logging
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import ReviewForm, ScreeningUploadForm
from .models import PredictionRecord, ReviewNote
from .services.gradcam import ExplanationUnavailable, GradCAMGenerator
from .services.predict import ModelUnavailable, PredictionEngine
from .services.quality import ImageQualityChecker

logger = logging.getLogger(__name__)


def store_upload(case_id, uploaded):
    """Write the upload to media storage and return its stored name."""
    suffix = Path(uploaded.name).suffix.lower() or ".png"
    name = f"uploads/{timezone.now():%Y/%m}/{case_id}{suffix}"
    return default_storage.save(name, uploaded)


def screen(case_id, image_path):
    """Run the screening pipeline over one stored radiograph.

    Returns the fields to persist. A failed explanation is recorded rather than
    raised: the prediction is still valid and useful without the heatmap, and
    the result page says which of the two happened.
    """
    engine = PredictionEngine()
    prediction = engine.predict(image_path)

    fields = {
        "predicted_label": prediction.label,
        "tb_probability": Decimal(str(prediction.probability)),
        "decision_threshold": Decimal(str(prediction.decision_threshold)),
        "triage_level": prediction.triage_level,
        "triage_justification": prediction.triage_justification,
        "triage_low_medium_threshold": Decimal(str(prediction.triage_low_medium)),
        "triage_medium_high_threshold": Decimal(str(prediction.triage_medium_high)),
        "model_version": prediction.model_version,
        "inference_ms": prediction.inference_ms,
        "gradcam_status": PredictionRecord.GradcamStatus.NOT_ATTEMPTED,
        "gradcam_image": None,
    }

    relative = f"heatmaps/{timezone.now():%Y/%m}/{case_id}.png"
    destination = Path(settings.MEDIA_ROOT) / relative
    try:
        prepared = engine.processor.prepare(image_path)
        GradCAMGenerator().overlay(image_path, engine.model(), prepared, destination)
        fields["gradcam_status"] = PredictionRecord.GradcamStatus.GENERATED
        fields["gradcam_image"] = relative
    except (ExplanationUnavailable, OSError, ValueError):
        logger.exception("Grad-CAM failed for case %s", case_id)
        fields["gradcam_status"] = PredictionRecord.GradcamStatus.FAILED

    return fields


@login_required
def upload(request):
    form = ScreeningUploadForm(request.POST or None, request.FILES or None)
    unavailable = None

    if request.method == "POST" and form.is_valid():
        case_id = uuid.uuid4()
        stored = store_upload(case_id, form.cleaned_data["xray_image"])
        image_path = default_storage.path(stored)

        report = ImageQualityChecker().check(image_path)
        if not report.is_usable:
            default_storage.delete(stored)
            form.add_error("xray_image", report.message)
        else:
            try:
                fields = screen(case_id, image_path)
            except ModelUnavailable:
                logger.exception("No trained model available")
                default_storage.delete(stored)
                unavailable = (
                    "The screening model is not installed on this machine, so no "
                    "prediction can be made. The rest of the application is unaffected."
                )
            else:
                with transaction.atomic():
                    record = PredictionRecord.objects.create(
                        case_id=case_id,
                        patient_reference=form.cleaned_data["patient_reference"],
                        xray_image=stored,
                        quality_status=report.status,
                        quality_message=report.message,
                        blur_score=report.blur_score,
                        brightness_mean=report.brightness_mean,
                        **fields,
                    )
                return redirect("screening:case_detail", case_id=record.case_id)

    return render(
        request,
        "screening/upload.html",
        {
            "form": form,
            "active": "upload",
            "unavailable": unavailable,
            "max_upload_mb": settings.MAX_UPLOAD_BYTES // (1024 * 1024),
        },
    )


@login_required
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


@login_required
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


@login_required
def dashboard(request):
    records = PredictionRecord.objects.all()
    total = records.count()

    by_label = dict(records.values_list("predicted_label").annotate(n=Count("id")).order_by())
    by_triage = dict(records.values_list("triage_level").annotate(n=Count("id")).order_by())

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
