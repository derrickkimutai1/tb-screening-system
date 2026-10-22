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
from urllib.parse import quote

from allauth.account.forms import SignupForm
from allauth.account.internal.flows.login_by_code import LoginCodeVerificationProcess
from allauth.account.internal.stagekit import clear_login
from allauth.account.utils import complete_signup, filter_users_by_email
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db import connections, transaction
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.db.utils import OperationalError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .auth import address_is_allowed
from .forms import (
    MAX_BATCH_IMAGES,
    EmailEntryForm,
    ProfileForm,
    ReviewForm,
    ScreeningUploadForm,
)
from .models import PredictionRecord, ReviewNote, profile_for
from .services.gradcam import ExplanationUnavailable, GradCAMGenerator
from .services.predict import ModelUnavailable, PredictionEngine
from .services.quality import ImageQualityChecker
from .services.sanitise import strip_metadata

logger = logging.getLogger(__name__)


def store_upload(case_id, uploaded):
    """Write the upload to media storage and return its stored name.

    The file is stripped of metadata on the way in, so nothing the system was
    not given is kept, and it is stored under the case id rather than under the
    name it arrived with.
    """
    suffix = Path(uploaded.name).suffix.lower() or ".png"
    name = f"uploads/{timezone.now():%Y/%m}/{case_id}{suffix}"
    return default_storage.save(name, strip_metadata(uploaded))


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


def reference_for(base, index, total):
    """Name one image within a batch.

    A single upload keeps the reference exactly as typed, so nothing changes
    for the common case. A batch needs each image distinguishable, so the
    reference becomes a prefix and the position is appended.
    """
    if total == 1:
        return base
    return f"{base}-{index:02d}"


def screen_one(uploaded, reference):
    """Store, quality check and screen one image.

    Returns (record, failure). Exactly one of the two is set. A failure is
    returned rather than raised so that a batch continues past a rejected
    image: one unusable film should not discard the work already done on the
    others, nor stop the ones still queued.
    """
    case_id = uuid.uuid4()
    stored = store_upload(case_id, uploaded)
    image_path = default_storage.path(stored)

    report = ImageQualityChecker().check(image_path)
    if not report.is_usable:
        default_storage.delete(stored)
        return None, {
            "filename": uploaded.name,
            "reference": reference,
            "reason": report.message,
        }

    # The file is on disk before the model is asked for anything, so a failure
    # from here on has to remove it. Without this a screening that could not
    # run leaves an image in storage with no record pointing at it, which is
    # both clutter and a radiograph the system is holding for no reason.
    try:
        fields = screen(case_id, image_path)
    except Exception:
        default_storage.delete(stored)
        raise

    with transaction.atomic():
        record = PredictionRecord.objects.create(
            case_id=case_id,
            patient_reference=reference,
            xray_image=stored,
            quality_status=report.status,
            quality_message=report.message,
            blur_score=report.blur_score,
            brightness_mean=report.brightness_mean,
            **fields,
        )
    return record, None


@login_required
def upload(request):
    form = ScreeningUploadForm(request.POST or None, request.FILES or None)
    unavailable = None

    if request.method == "POST" and form.is_valid():
        images = form.cleaned_data["xray_image"]
        base = form.cleaned_data["patient_reference"]
        screened, rejected = [], []

        try:
            for position, uploaded in enumerate(images, start=1):
                record, failure = screen_one(
                    uploaded, reference_for(base, position, len(images))
                )
                if record is not None:
                    screened.append(record)
                else:
                    rejected.append(failure)
        except ModelUnavailable:
            logger.exception("No trained model available")
            unavailable = (
                "The screening model is not installed on this machine, so no "
                "prediction can be made. The rest of the application is unaffected."
            )
        else:
            # One image behaves exactly as it always has.
            if len(images) == 1 and screened:
                return redirect("screening:case_detail", case_id=screened[0].case_id)
            if len(images) == 1 and rejected:
                form.add_error("xray_image", rejected[0]["reason"])
            else:
                return render(
                    request,
                    "screening/batch_result.html",
                    {
                        "active": "upload",
                        "screened": screened,
                        "rejected": rejected,
                        "total": len(images),
                    },
                )

    return render(
        request,
        "screening/upload.html",
        {
            "form": form,
            "active": "upload",
            "unavailable": unavailable,
            "max_upload_mb": settings.MAX_UPLOAD_BYTES // (1024 * 1024),
            "max_batch": MAX_BATCH_IMAGES,
        },
    )


@login_required
def case_detail(request, case_id):
    record = get_object_or_404(PredictionRecord, case_id=case_id)

    # Confirming or dismissing a case is a clinical judgement, so the form is
    # only offered to the roles that may make one. The check is repeated on the
    # POST because a hidden form is not an access control.
    viewer = profile_for(request.user)
    may_review = viewer.may_review

    if request.method == "POST":
        if not may_review:
            raise PermissionDenied("Your role does not permit recording a review.")

        review_form = ReviewForm(request.POST)
        if review_form.is_valid():
            with transaction.atomic():
                ReviewNote.objects.create(
                    record=record,
                    reviewer=request.user,
                    # Kept as well as the link, so the note still reads
                    # correctly if the account is later removed.
                    reviewer_name=viewer.display_name,
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
            "may_review": may_review,
            "notes": record.review_notes.select_related("reviewer"),
            "active": "cases",
        },
    )


@login_required
def profile(request):
    """The signed-in user's own details, and what they have screened."""
    profile = profile_for(request.user)

    if request.method == "POST":
        form = ProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            return redirect("screening:profile")
    else:
        form = ProfileForm(instance=profile)

    reviewed = ReviewNote.objects.filter(reviewer=request.user).select_related("record")
    recent = reviewed[:10]

    return render(
        request,
        "screening/profile.html",
        {
            "profile": profile,
            "form": form,
            "active": "profile",
            "reviewed_total": reviewed.count(),
            "recent_reviews": recent,
            "cases_reviewed": (
                PredictionRecord.objects.filter(review_notes__reviewer=request.user)
                .distinct()
                .count()
            ),
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


def health(request):
    """Report whether this instance can actually serve a prediction.

    The deployment guidance asks for a lightweight health endpoint that reports
    readiness only after the model has loaded. A container that is listening
    but cannot answer is worse than one that is still starting, because a load
    balancer will send it traffic.

    Deliberately outside the sign-in gate: a health check has no session, and
    the response says nothing a visitor could not learn by using the site.
    """
    from django.http import JsonResponse

    checks = {}
    ok = True

    try:
        connections["default"].cursor().close()
        checks["database"] = "ok"
    except OperationalError as error:
        checks["database"] = f"unavailable: {error.__class__.__name__}"
        ok = False

    try:
        engine = PredictionEngine()
        engine.model()
        checks["model"] = engine.metadata().get("model_version", "loaded")
    except (ModelUnavailable, OSError) as error:
        checks["model"] = f"unavailable: {error.__class__.__name__}"
        ok = False

    return JsonResponse(
        {"status": "ready" if ok else "degraded", "checks": checks},
        status=200 if ok else 503,
    )


@require_POST
def restart_sign_in(request):
    """Abandon a half-finished sign-in and go back to the start.

    Asking for a code leaves a verification pending in the session, and while
    it is pending allauth sends the request page straight to the confirmation
    page. Someone who typed the wrong address is then looking at a form for a
    code that will never arrive, with no way back to change it: both the link
    to request a code and the sign-in page return them to the same screen.

    This clears the pending login so the address can be entered again. POST,
    because it changes session state, and deliberately outside the sign-in
    gate, since by definition nobody is signed in when they need it.
    """
    clear_login(request)
    return redirect("account_login")


@require_POST
def continue_with_email(request):
    """One field on the gate, for signing in and for registering alike.

    Asking someone to choose between "sign in" and "create an account" asks
    them to know something the system can work out: whether that address
    already has an account. Products people are used to do not ask. They take
    an address, send a code, and decide afterwards.

    So this is the single entry point. An address that has an account is sent a
    sign-in code; one that has none is registered and sent a confirmation code.
    Both land on a page asking for six digits, and the person never had to
    know which case they were in.

    allauth's own forms and flows do the work, so there is one implementation
    of creating an account and one of sending a code, not two.
    """
    email = (request.POST.get("email") or "").strip()
    redirect_to = request.POST.get("next") or ""

    form = EmailEntryForm({"email": email})
    if not form.is_valid():
        return render(
            request,
            "account/login.html",
            {"email_error": next(iter(form.errors["email"])), "email_value": email},
            status=400,
        )

    email = form.cleaned_data["email"]

    # The allowlist decides admission before anything is created or sent, so a
    # refused address never becomes an account and never receives a code.
    if not address_is_allowed(email):
        messages.error(
            request,
            "That address is not authorised for this system. "
            "Contact the administrator to be added.",
        )
        return redirect("account_login")

    existing = filter_users_by_email(email, is_active=True, prefer_verified=True)

    if existing:
        LoginCodeVerificationProcess.initiate(request=request, user=existing[0], email=email)
        return redirect(_with_next("account_confirm_login_code", redirect_to))

    if not settings.SIGN_IN_OPEN_REGISTRATION:
        # Deliberately the same message and the same page as an address that
        # was refused, so this does not become a way to discover which
        # addresses are registered.
        messages.error(
            request,
            "That address is not authorised for this system. "
            "Contact the administrator to be added.",
        )
        return redirect("account_login")

    signup = SignupForm({"email": email, "email2": email})
    if not signup.is_valid():
        return render(
            request,
            "account/login.html",
            {
                "email_error": " ".join(
                    str(error) for errors in signup.errors.values() for error in errors
                ),
                "email_value": email,
            },
            status=400,
        )

    # try_save and complete_signup are what allauth's own signup view calls.
    # form.save alone creates the account without starting the verification
    # that turns it into a usable one, which is a half-registered user and no
    # code in their inbox.
    user, response = signup.try_save(request)
    if response is not None:
        return response

    return complete_signup(
        request,
        user=user,
        email_verification=settings.ACCOUNT_EMAIL_VERIFICATION,
        success_url=_with_next("account_email_verification_sent", redirect_to),
    )


def _with_next(name, redirect_to):
    """Carry the page the user was trying to reach through the code exchange."""
    url = reverse(name)
    if redirect_to and url_has_allowed_host_and_scheme(
        redirect_to, allowed_hosts={settings.ALLOWED_HOSTS and ""} | set(settings.ALLOWED_HOSTS)
    ):
        return f"{url}?next={quote(redirect_to)}"
    return url
