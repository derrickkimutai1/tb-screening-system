"""
Views for the screening workflow.

The upload view coordinates the services in the order set out in the proposal's
activity diagram: quality check, preprocessing, prediction, triage, explanation,
then storage. The services themselves know nothing about the database; this is
where their results are persisted.
"""

import csv
import json
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
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.core.paginator import Paginator
from django.db import connections, transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.db.utils import OperationalError
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render, resolve_url
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
from .models import (
    AccessEvent,
    PredictionRecord,
    Profile,
    ReviewNote,
    facility_name,
    profile_for,
)
from .services.gradcam import GRADCAM_METHOD_NAME, GradCAMGenerator
from .services.occlusion import METHOD_NAME, OcclusionGenerator
from .services.overlays import ExplanationUnavailable
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

    Returns the fields to persist. The explanation is left pending and built
    on first view, so a batch upload is not held up producing maps for images
    nobody opens.
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
        # The explanation is built when somebody opens the case, not here.
        # An occlusion map is several hundred forward passes; building one for
        # every image of a batch of twenty would add minutes to an upload, and
        # most of those images are never opened.
        "explanation_status": PredictionRecord.ExplanationStatus.PENDING,
        "explanation_image": None,
        "explanation_method": "",
    }

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


def screen_one(uploaded, reference, screener):
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
            screened_by=screener,
            # Copied rather than followed, so a record stays with the clinic it
            # was taken at even if the person later moves to another one.
            facility=profile_for(screener).facility,
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
                    uploaded,
                    reference_for(base, position, len(images)),
                    request.user,
                )
                if record is not None:
                    screened.append(record)
                    AccessEvent.record(
                        request,
                        AccessEvent.Action.SCREENED,
                        case_id=record.case_id,
                        facility=facility_name(record.facility),
                        detail=record.patient_reference,
                    )
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
    # visible_to rather than a plain lookup, so a case at another clinic is
    # not found rather than refused: a 403 would confirm the reference exists.
    record = get_object_or_404(
        PredictionRecord.objects.visible_to(request.user), case_id=case_id
    )

    AccessEvent.record(
        request,
        AccessEvent.Action.VIEWED,
        case_id=record.case_id,
        facility=facility_name(record.facility),
        detail=record.patient_reference,
    )

    # Confirming or dismissing a case is a clinical judgement, so the form is
    # only offered to the roles that may make one. The check is repeated on the
    # POST because a hidden form is not an access control.
    viewer = profile_for(request.user)
    may_review = viewer.may_review

    if request.method == "POST":
        if not may_review:
            AccessEvent.record(
                request,
                AccessEvent.Action.REFUSED,
                case_id=record.case_id,
                facility=facility_name(record.facility),
                detail="review refused: role is not permitted",
            )
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
            AccessEvent.record(
                request,
                AccessEvent.Action.REVIEWED,
                case_id=record.case_id,
                facility=facility_name(record.facility),
                detail=f"set to {review_form.cleaned_data['status_set']}",
            )
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
            "history": (
                PredictionRecord.objects.visible_to(request.user)
                .for_patient(record.patient_reference, excluding=record.pk)
                .order_by("-created_at")[:10]
            ),
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
    screened = PredictionRecord.objects.filter(screened_by=request.user).count()

    return render(
        request,
        "screening/profile.html",
        {
            "profile": profile,
            "form": form,
            "active": "profile",
            "reviewed_total": reviewed.count(),
            "screened_total": screened,
            "recent_reviews": recent,
            "cases_reviewed": (
                PredictionRecord.objects.visible_to(request.user)
                .filter(review_notes__reviewer=request.user)
                .distinct()
                .count()
            ),
        },
    )


@login_required
def case_list(request):
    records = PredictionRecord.objects.visible_to(request.user)

    reference = request.GET.get("reference", "").strip()
    AccessEvent.record(
        request,
        AccessEvent.Action.LISTED,
        facility=facility_name(profile_for(request.user).facility),
        detail=f"search: {reference}" if reference else "",
    )
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
    records = PredictionRecord.objects.visible_to(request.user)
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

    # success_url is where the person ends up once verification has finished,
    # not the page that collects the code; allauth routes them to that itself.
    # Passing the collection page sent a newly registered user to allauth's
    # email-management screen, which is a strange first sight of a screening
    # system.
    return complete_signup(
        request,
        user=user,
        email_verification=settings.ACCOUNT_EMAIL_VERIFICATION,
        success_url=_safe_next(redirect_to) or resolve_url(settings.LOGIN_REDIRECT_URL),
    )


def _safe_next(redirect_to):
    """The page the user was trying to reach, if it is one of ours.

    An unchecked next parameter is an open redirect: a link to this site that
    bounces the visitor somewhere else after they sign in.
    """
    if redirect_to and url_has_allowed_host_and_scheme(
        redirect_to,
        allowed_hosts=set(settings.ALLOWED_HOSTS),
        require_https=request_is_secure(),
    ):
        return redirect_to
    return None


def request_is_secure():
    """Whether to insist a next URL is https, matching how the site is served."""
    return not settings.DEBUG


def _with_next(name, redirect_to):
    """Carry the page the user was trying to reach through the code exchange."""
    url = reverse(name)
    destination = _safe_next(redirect_to)
    return f"{url}?next={quote(destination)}" if destination else url


def no_password_here(request):
    """Explain that there is no password, rather than offering to change one.

    allauth registers password change, set and reset routes whether or not any
    account has a password. Nothing here does: identity comes from a provider
    or a one-time code. A page inviting someone to change a password that does
    not exist is worse than a missing page, so these routes say so and send the
    user somewhere useful.
    """
    messages.info(
        request,
        "This system has no passwords. You sign in with Google, Microsoft or a "
        "one-time code sent to your email address, so there is nothing to change.",
    )
    return redirect("screening:profile" if request.user.is_authenticated else "account_login")


@login_required
def worklist(request):
    """What still needs a clinical decision, most urgent first.

    The case list is an archive: everything ever screened, newest first. That
    answers "what happened" and not "what do I do now", which is the question
    someone arriving for a shift actually has. This is the queue.
    """
    queue = (
        PredictionRecord.objects.visible_to(request.user)
        .awaiting_review()
        .in_clinical_order()
        .select_related("screened_by", "facility")
    )

    AccessEvent.record(
        request,
        AccessEvent.Action.LISTED,
        facility=facility_name(profile_for(request.user).facility),
        detail="worklist",
    )

    paginator = Paginator(queue, 25)
    page = paginator.get_page(request.GET.get("page"))

    counts = queue.aggregate(
        high=Count("pk", filter=Q(triage_level=PredictionRecord.TriageLevel.HIGH)),
        medium=Count("pk", filter=Q(triage_level=PredictionRecord.TriageLevel.MEDIUM)),
        low=Count("pk", filter=Q(triage_level=PredictionRecord.TriageLevel.LOW)),
    )

    oldest = queue.order_by("created_at").first()

    return render(
        request,
        "screening/worklist.html",
        {
            "page": page,
            "counts": counts,
            "waiting": queue.count(),
            "oldest_days": oldest.waiting_days if oldest else None,
            "may_review": profile_for(request.user).may_review,
            "active": "worklist",
        },
    )


@login_required
@require_POST
def case_explanation(request, case_id):
    """Build the explanation for one case, on demand.

    Called by the case page when the map has not been made yet. It is a POST
    because it creates something and costs real work, so it must not be
    triggered by a prefetch, a crawler or a refresh of a cached GET.

    The answer is JSON rather than a redirect: the page has already rendered
    by the time this runs, and swapping an image into it is all that is left
    to do.
    """
    record = get_object_or_404(
        PredictionRecord.objects.visible_to(request.user), case_id=case_id
    )

    if record.has_explanation:
        return JsonResponse(
            {"status": record.explanation_status, "url": record.explanation_image.url}
        )
    if not record.explanation_awaited:
        # Already attempted and failed. Retrying on every page load would
        # spend the same work to fail the same way.
        return JsonResponse({"status": record.explanation_status, "url": None})

    source = Path(settings.MEDIA_ROOT) / record.xray_image.name
    relative = f"heatmaps/{record.created_at:%Y/%m}/{record.case_id}.png"
    destination = Path(settings.MEDIA_ROOT) / relative

    engine = PredictionEngine()
    try:
        prepared = engine.processor.prepare(source)
        OcclusionGenerator().overlay(source, engine.model(), prepared, destination)
    except (ExplanationUnavailable, OSError, ValueError):
        logger.exception("The explanation failed for case %s", record.case_id)
        record.explanation_status = PredictionRecord.ExplanationStatus.FAILED
        record.save(update_fields=["explanation_status", "updated_at"])
        return JsonResponse({"status": record.explanation_status, "url": None})

    record.explanation_image = relative
    record.explanation_status = PredictionRecord.ExplanationStatus.GENERATED
    record.explanation_method = METHOD_NAME

    # The map the proposal named, built beside the one that replaced it.
    #
    # It costs about half a second against the occlusion map's three, and it
    # answers the objective as written. A failure here must not lose the
    # explanation that does work, so it is caught separately and the record is
    # saved either way: the comparison is the part that can be missing.
    comparison = f"gradcam/{record.created_at:%Y/%m}/{record.case_id}.png"
    fields = ["explanation_image", "explanation_status", "explanation_method"]
    try:
        GradCAMGenerator().overlay(
            source, engine.model(), prepared, Path(settings.MEDIA_ROOT) / comparison
        )
    except (ExplanationUnavailable, OSError, ValueError):
        logger.warning("The Grad-CAM comparison failed for case %s", record.case_id)
    else:
        record.comparison_image = comparison
        record.comparison_method = GRADCAM_METHOD_NAME
        fields += ["comparison_image", "comparison_method"]

    record.save(update_fields=[*fields, "updated_at"])
    return JsonResponse(
        {
            "status": record.explanation_status,
            "url": record.explanation_image.url,
            "comparison_url": (
                record.comparison_image.url if record.comparison_image else None
            ),
        }
    )


@login_required
def protected_media(request, path):
    """Serve a stored radiograph or heatmap, to someone entitled to see it.

    These files were reachable by anyone who knew the address. The pages that
    show them required a session and the files behind those pages did not, so
    a chest radiograph could be fetched with no account at all. The case
    identifier in the path is obscurity, not access control, and the proposal's
    NFR-05 asks for them to be "served only through authenticated application
    routes".

    Both upload paths name the file after the case, so the record it belongs to
    can be found from the path and the same visibility rule that governs the
    case page governs the image. A file that does not resolve to a visible
    record is not found rather than refused, exactly as the case page behaves:
    a 403 would confirm that the case exists.
    """
    candidate = (Path(settings.MEDIA_ROOT) / path).resolve()
    root = Path(settings.MEDIA_ROOT).resolve()
    # A path that climbs out of the media folder is not a missing file, it is
    # an attempt at a different one.
    if root not in candidate.parents or not candidate.is_file():
        raise Http404("No such file.")

    try:
        case_id = uuid.UUID(candidate.stem)
    except ValueError:
        # Nothing else in this folder is served. Anything the application
        # writes here is named after the case it belongs to, so a name that is
        # not a case identifier is not a file this view should hand out.
        raise Http404("No such file.") from None

    if not PredictionRecord.objects.visible_to(request.user).filter(case_id=case_id).exists():
        raise Http404("No such file.")

    return FileResponse(candidate.open("rb"))


@login_required
def export_my_data(request):
    """Everything this system holds that is about the signed-in person.

    The Data Protection Act 2019 gives a data subject the right to a copy of
    their personal data in a structured, commonly used, machine-readable form,
    so this is JSON rather than a page to screenshot.

    What it contains is the person: their account, their role and clinic, and
    the actions attributed to them. What it does not contain is the patients:
    a screening belongs to the clinic's caseload and to whoever it is of, not
    to the operator who uploaded it, so this lists the screenings they
    performed without the radiographs or the scores. Exporting somebody else's
    chest X-ray because a third party happened to upload it would be the
    opposite of a privacy right.
    """
    viewer = profile_for(request.user)

    payload = {
        "exported_at": timezone.now().isoformat(),
        "about": (
            "The personal data this system holds about this account. Clinical "
            "records are not included: a screening belongs to the clinic and "
            "to the patient, not to the operator who uploaded it."
        ),
        "account": {
            "email": request.user.email,
            "name": request.user.get_full_name() or request.user.username,
            "joined": request.user.date_joined.isoformat(),
            "last_signed_in": (
                request.user.last_login.isoformat() if request.user.last_login else None
            ),
        },
        "role_and_clinic": {
            "role": viewer.get_role_display(),
            "may_record_reviews": viewer.may_review,
            "clinic": facility_name(viewer.facility) or None,
            "note": "The role is set by an administrator and is not self-chosen.",
        },
        "screenings_performed": [
            {
                "case_reference": record.patient_reference,
                "case_id": str(record.case_id),
                "screened_at": record.created_at.isoformat(),
                "clinic": facility_name(record.facility) or None,
            }
            for record in PredictionRecord.objects.filter(screened_by=request.user).order_by(
                "created_at"
            )
        ],
        "reviews_written": [
            {
                "case_id": str(note.record.case_id),
                "written_at": note.created_at.isoformat(),
                "status_set": note.get_status_set_display(),
                "note": note.note,
            }
            for note in ReviewNote.objects.filter(reviewer=request.user)
            .select_related("record")
            .order_by("created_at")
        ],
        "recorded_actions": [
            {
                "at": event.created_at.isoformat(),
                "action": event.get_action_display(),
                "case_id": str(event.case_id) if event.case_id else None,
                "clinic": event.facility or None,
                "from_address": event.ip_address,
                "detail": event.detail,
            }
            for event in AccessEvent.objects.filter(actor=request.user).order_by("created_at")
        ],
    }

    AccessEvent.record(
        request,
        AccessEvent.Action.LISTED,
        facility=facility_name(viewer.facility),
        detail="exported their own personal data",
    )

    stamp = timezone.now().strftime("%Y-%m-%d")
    response = HttpResponse(
        json.dumps(payload, indent=2, ensure_ascii=False),
        content_type="application/json",
    )
    response["Content-Disposition"] = f'attachment; filename="my-data-{stamp}.json"'
    return response


@login_required
@require_POST
def delete_my_account(request):
    """Close this account, and say plainly what that does and does not remove.

    Erasure is a real right and it is not unlimited. A screening is a clinical
    record of a patient, held by a clinic; the operator who uploaded it cannot
    erase it by closing their own account, any more than a radiographer
    leaving a hospital deletes the films they took. The audit trail is the same
    - a log that a departing member of staff could empty would answer nothing.

    So this removes the person: the account, the ability to sign in, the link
    from each record to that account. It keeps the records, and keeps the name
    already written into them as text, so the history stays readable and the
    hash chain stays intact.

    Confirmed by typing the address, because a destructive action reached by
    one click is reached by accident.
    """
    viewer = profile_for(request.user)
    typed = (request.POST.get("confirm_email") or "").strip().lower()

    if typed != (request.user.email or "").strip().lower():
        messages.error(
            request,
            "The address did not match, so nothing was changed. Type the "
            "address you signed in with to confirm.",
        )
        return redirect("screening:profile")

    administrators = Profile.objects.filter(role=Profile.Role.ADMINISTRATOR)
    if viewer.role == Profile.Role.ADMINISTRATOR and administrators.count() <= 1:
        messages.error(
            request,
            "You are the only administrator. Give somebody else that role "
            "first, or nobody will be able to set roles afterwards.",
        )
        return redirect("screening:profile")

    AccessEvent.record(
        request,
        AccessEvent.Action.REFUSED,
        facility=facility_name(viewer.facility),
        detail=f"closed their own account ({request.user.email})",
    )

    user = request.user
    logout(request)
    user.delete()

    messages.success(
        request,
        "Your account is closed. The screenings and reviews you recorded stay "
        "with the clinic as clinical records, under the name already written "
        "into them.",
    )
    return redirect("account_login")


# Characters a spreadsheet treats as the start of a formula rather than text.
FORMULA_LEADERS = ("=", "+", "-", "@", chr(9), chr(13))


def _spreadsheet_safe(value):
    """Keep a cell as text when a spreadsheet would otherwise run it.

    A case reference is typed by a person, and nothing stops that person
    typing one that begins with an equals sign. Excel and Sheets read such a
    cell as a formula, so an exported record could run =cmd|'/c calc'!A1 or
    fetch a URL on the machine of whoever opened the file. This export exists
    so that colleagues open it in a spreadsheet, which is exactly the
    situation the attack needs.

    A leading apostrophe is the usual remedy: the spreadsheet shows the text
    and does not evaluate it. The CSV still carries the original characters,
    so a program reading it rather than a spreadsheet loses nothing it cannot
    strip.
    """
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_LEADERS) else text


def _artifact(name):
    """Read one measurement file, or None if this build does not carry it."""
    path = Path(settings.BASE_DIR) / "ml" / "artifacts" / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@login_required
def model_performance(request):
    """What the model is measured to do, in the application that uses it.

    These figures existed only as JSON files beside the training scripts, so
    the people relying on the score could not see what it is worth. A clinician
    deciding how much weight to give a result should be able to read the
    sensitivity, and the fact that five TB cases in fifty-nine were missed,
    without opening a repository.

    Read from the evaluation artifacts at request time rather than copied into
    a template, so a figure here cannot drift from the file that produced it.
    Nothing is computed on this page; re-running an evaluation script changes
    what it shows.
    """
    test = _artifact("metrics.json")
    calibration = _artifact("calibration.json")
    across = _artifact("cross_dataset.json")
    explanation = _artifact("explanation_comparison-all.json")
    occlusion = _artifact("occlusion-p32s16-all-tb_evaluation.json")
    gradcam = _artifact("gradcam-block_13_expand_relu-all-tb_evaluation.json")
    timing = _artifact("response_times.json")

    matrix = (test or {}).get("confusion_matrix") or {}
    missed = matrix.get("false_negative")
    positives = (matrix.get("true_positive") or 0) + (missed or 0)

    return render(
        request,
        "screening/model_performance.html",
        {
            "test": test,
            "calibration": calibration,
            "across": across,
            "explanation": explanation,
            "occlusion": occlusion,
            "gradcam": gradcam,
            "timing": timing,
            "matrix": matrix,
            "missed": missed,
            "positives": positives,
            "available": test is not None,
            "active": "performance",
        },
    )


@login_required
def access_trail(request):
    """The log of who did what, and a way to check it has not been edited.

    The trail existed only in the database and the Django admin, which means
    the one property worth demonstrating - that it detects its own alteration
    - could only be shown from a terminal. A clinical system should be able to
    answer "who opened this patient's record" to the person accountable for
    it, not only to whoever has a database client.

    Administrators see the whole installation. Everyone else sees their own
    clinic, for the same reason the case list does.
    """
    viewer = profile_for(request.user)
    events = AccessEvent.objects.order_by("-id")
    if viewer.role != Profile.Role.ADMINISTRATOR:
        events = events.filter(facility=facility_name(viewer.facility))

    action = request.GET.get("action", "")
    if action in AccessEvent.Action.values:
        events = events.filter(action=action)

    paginator = Paginator(events.select_related("actor"), 50)
    page = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "screening/access_trail.html",
        {
            "page": page,
            "action": action,
            "actions": AccessEvent.Action.choices,
            "total": events.count(),
            "is_administrator": viewer.role == Profile.Role.ADMINISTRATOR,
            "active": "trail",
        },
    )


@login_required
@require_POST
def verify_access_trail(request):
    """Walk the chain and report whether it still adds up.

    Deliberately a POST and deliberately not cached: the answer is about the
    database as it is at this moment, and a stale "intact" is worse than no
    answer at all. It reads every row, which is why it is a button rather
    than something the page does on every load.
    """
    checked, problems = AccessEvent.verify_chain()
    return JsonResponse(
        {
            "checked": checked,
            "intact": not problems,
            "problems": problems[:20],
            "more": max(0, len(problems) - 20),
        }
    )


@login_required
def case_report(request, case_id):
    """A one-page account of a screening, laid out for paper.

    A result that cannot leave the system is of limited use: it has to go into
    a patient's file, travel with a referral, or reach someone who has no
    account here. This is the printable version, and the browser's own print
    dialogue turns it into a PDF.
    """
    record = get_object_or_404(
        PredictionRecord.objects.visible_to(request.user).select_related(
            "screened_by", "facility"
        ),
        case_id=case_id,
    )

    AccessEvent.record(
        request,
        AccessEvent.Action.VIEWED,
        case_id=record.case_id,
        facility=facility_name(record.facility),
        detail=f"printed report for {record.patient_reference}",
    )

    return render(
        request,
        "screening/case_report.html",
        {
            "record": record,
            "notes": record.review_notes.select_related("reviewer"),
            "history": (
                PredictionRecord.objects.visible_to(request.user)
                .for_patient(record.patient_reference, excluding=record.pk)
                .order_by("-created_at")[:10]
            ),
            "printed_at": timezone.now(),
            "printed_by": profile_for(request.user).display_name,
        },
    )


@login_required
def export_cases(request):
    """The visible cases as CSV, for a spreadsheet or a report.

    Scoped exactly as the case list is, so an export cannot reach further than
    the screen it was taken from, and logged, because a bulk download of
    clinical records is the access most worth recording.
    """
    records = (
        PredictionRecord.objects.visible_to(request.user)
        .select_related("screened_by", "facility")
        .order_by("-created_at")
    )

    reference = request.GET.get("reference", "").strip()
    if reference:
        records = records.filter(patient_reference__icontains=reference)
    triage = request.GET.get("triage", "")
    if triage in PredictionRecord.TriageLevel.values:
        records = records.filter(triage_level=triage)

    AccessEvent.record(
        request,
        AccessEvent.Action.LISTED,
        facility=facility_name(profile_for(request.user).facility),
        detail=f"exported {records.count()} records as CSV",
    )

    stamp = timezone.now().strftime("%Y-%m-%d")
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="screenings-{stamp}.csv"'

    writer = csv.writer(response)
    writer.writerow(
        [
            "Case reference",
            "Case ID",
            "Screened at",
            "Clinic",
            "Screened by",
            "Result",
            "Model score",
            "Decision threshold",
            "Triage",
            "Image quality",
            "Review status",
            "Model version",
        ]
    )
    for record in records:
        # Every cell through the guard, not only the reference: the clinic
        # name and the address are also typed by somebody at some point, and
        # a rule that covers one field is a rule somebody forgets to extend.
        writer.writerow(
            [
                _spreadsheet_safe(value)
                for value in (
                    record.patient_reference,
                    record.case_id,
                    record.created_at.strftime("%Y-%m-%d %H:%M"),
                    facility_name(record.facility),
                    record.screened_by.email if record.screened_by else "",
                    record.get_predicted_label_display(),
                    record.tb_probability,
                    record.decision_threshold,
                    record.get_triage_level_display(),
                    record.get_quality_status_display(),
                    record.get_review_status_display(),
                    record.model_version,
                )
            ]
        )
    return response
