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

from django.conf import settings
from django.db import models
from django.utils import timezone


def xray_upload_path(instance, filename):
    """Store uploads under a date folder, named by case reference."""
    suffix = Path(filename).suffix.lower() or ".png"
    return f"uploads/{timezone.now():%Y/%m}/{instance.case_id}{suffix}"


def heatmap_upload_path(instance, filename):
    """Grad-CAM overlays are always written as PNG."""
    return f"heatmaps/{timezone.now():%Y/%m}/{instance.case_id}.png"


class Facility(models.Model):
    """A clinic or hospital that shares a caseload.

    Previously this was free text on each profile, and visibility was decided
    by comparing those strings. Two spellings of one hospital therefore made
    two separate caseloads, and a typo silently hid every record from the
    person who made it. Making the clinic a row removes the question: records
    are scoped by which clinic, not by how it was spelled.

    Administrators maintain the list. A user picks from it and cannot invent
    one, which is the point; somewhere that is not on the list is a question
    for an administrator rather than something to type around.
    """

    name = models.CharField(max_length=120, unique=True)
    # Somewhere that closes should stop being offered without taking its
    # records with it.
    is_active = models.BooleanField(
        default=True,
        help_text="Clear this to stop offering the clinic without removing its records.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Facilities"

    def __str__(self):
        return self.name


class PredictionRecordQuerySet(models.QuerySet):
    """Visibility rules, in one place rather than repeated in each view."""

    def visible_to(self, user):
        """The records this user may see.

        Scoped by facility, because that is how a caseload is shared: everyone
        at a clinic works the same list, which is what makes the review
        workflow possible at all. Narrowing it to the person who uploaded each
        record would leave a clinician with nothing to review.

        An administrator sees everything, since somebody has to be able to.

        A user with no facility set sees only records that also have none. That
        is deliberate: it means someone who registers out of nowhere sees an
        empty system rather than a clinic's caseload, and it fails closed
        rather than open.
        """
        if not user.is_authenticated:
            return self.none()
        if user.is_superuser:
            return self
        profile = Profile.objects.filter(user=user).select_related("facility").first()
        facility = profile.facility if profile else None
        if facility is None:
            return self.filter(facility__isnull=True)
        return self.filter(facility=facility)


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

    # Who screened this, and where
    #
    # A clinic shares a caseload: a radiographer screens and a clinician
    # reviews, so a record cannot belong privately to whoever uploaded it.
    # What it does belong to is a facility, which is what scopes who may see
    # it. The person is recorded as well, because "which did I screen" is a
    # reasonable question and nothing could answer it before.
    #
    # Both survive the account being removed. A screening record outliving the
    # person who took it is normal; losing the record is not.
    screened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="screenings",
    )
    # PROTECT: a clinic with records cannot be deleted out from under them.
    # Deactivating it stops it being offered, which is the intended way to
    # retire one.
    facility = models.ForeignKey(
        "Facility",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="records",
        help_text=(
            "The clinic this screening belongs to, taken from the profile of "
            "whoever screened it. Records are visible to that clinic."
        ),
    )

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
    triage_level = models.CharField(max_length=8, choices=TriageLevel.choices, db_index=True)
    triage_justification = models.TextField(blank=True)
    triage_low_medium_threshold = models.DecimalField(max_digits=4, decimal_places=3)
    triage_medium_high_threshold = models.DecimalField(max_digits=4, decimal_places=3)

    # Explainability
    gradcam_image = models.ImageField(upload_to=heatmap_upload_path, null=True, blank=True)
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

    objects = PredictionRecordQuerySet.as_manager()

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
                    triage_low_medium_threshold__lt=models.F("triage_medium_high_threshold")
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

    # Circumference of the gauge arc, for a circle of radius 52.
    GAUGE_CIRCUMFERENCE = 327

    @property
    def triage_slug(self):
        """Lower-case triage level, for building CSS class names."""
        return self.triage_level.lower()

    @property
    def gauge_offset(self):
        """Stroke offset that fills the score gauge to the model's score."""
        return round(self.GAUGE_CIRCUMFERENCE * (1 - float(self.tb_probability)), 1)

    @property
    def scale_bands(self):
        """Widths of the low, medium and high bands as percentages.

        Drawn from the thresholds stored on this record, so the scale always
        reflects the thresholds the result was actually judged under.
        """
        low = float(self.triage_low_medium_threshold) * 100
        high = float(self.triage_medium_high_threshold) * 100
        return {"low": low, "medium": high - low, "high": 100 - high}

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
    # Who wrote it, now that there is a session to ask. The note survives the
    # account being removed, because a clinical record should not lose its
    # history when someone leaves; reviewer_name keeps the name as it was at
    # the time, so an old note still reads correctly either way.
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
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
        return f"{self.attributed_to} on {self.record.patient_reference}"

    @property
    def attributed_to(self):
        """The best name available for whoever wrote this note."""
        if self.reviewer_id:
            return self.reviewer.get_full_name() or self.reviewer.email or str(self.reviewer)
        return self.reviewer_name or "Unnamed reviewer"


def facility_name(facility):
    """The clinic's name, for the places that store text rather than a link.

    The audit trail keeps a name rather than a foreign key, so a row survives
    the clinic being renamed or removed and still says where it happened.
    """
    return facility.name if facility else ""


def profile_for(user):
    """The user's profile, creating it if somehow it is missing.

    A signal creates a profile when an account is created, which covers every
    account the application makes itself. It does not cover an account that
    arrived another way: loaddata, bulk_create and a database restore all skip
    signals, and so did every account that existed before profiles were added.

    Reaching for user.profile directly raises RelatedObjectDoesNotExist in
    those cases, which is a 500 on a page that had no need to fail. This is the
    one place that absence is handled, so no view has to think about it.
    """
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


class Profile(models.Model):
    """What the system knows about a signed-in member of staff.

    Google answers who someone is. It cannot answer what they are allowed to do
    here or where they work, so that is kept alongside the account rather than
    inside it. A profile is created the first time a user signs in, so every
    account has exactly one and no view has to handle its absence.
    """

    class Role(models.TextChoices):
        RADIOGRAPHER = "radiographer", "Radiographer"
        CLINICIAN = "clinician", "Clinician"
        ADMINISTRATOR = "administrator", "Administrator"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    # A radiographer captures and screens; confirming a case is a clinical
    # judgement, so review is limited to clinicians and administrators.
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.RADIOGRAPHER,
        help_text="Determines whether this user may record a clinical review.",
    )
    facility = models.ForeignKey(
        "Facility",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff",
        limit_choices_to={"is_active": True},
        help_text=(
            "The clinic you work at. Records are shared with everyone at the "
            "same clinic. Ask an administrator if yours is not listed."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__email"]

    def __str__(self):
        return f"{self.display_name} ({self.get_role_display()})"

    @property
    def display_name(self):
        return self.user.get_full_name() or self.user.email or self.user.get_username()

    @property
    def may_review(self):
        """Whether this user may record a clinical review decision."""
        return self.role in {self.Role.CLINICIAN, self.Role.ADMINISTRATOR}


# ASCII unit separator. Used to join an audit row's fields before hashing,
# because no field can contain it.
FIELD_SEPARATOR = chr(31)


class AccessEvent(models.Model):
    """One line per thing somebody did to a screening record.

    The certification criteria for health records ask for an audit trail
    recording who acted, what they did, when, and from where. This project's
    own sign-in page claimed access was logged before any of it existed, which
    is a worse position than not claiming it.

    Append-only by intent: nothing in the application updates or deletes a row,
    and the admin registration forbids both. A log that can be quietly edited
    answers no question worth asking of it.

    Intent is not evidence, though, and the certification criteria ask a log to
    detect its own alteration. Each row therefore carries a hash of its own
    contents together with the hash of the row before it. Changing any field of
    any row, or removing a row, breaks that row's hash and every hash after it,
    so the damage is visible and its position is known. `manage.py verifyaudit`
    walks the chain.

    This detects tampering; it does not prevent it. Someone with write access
    to the database could recompute the whole chain. Preventing that needs the
    rows signed with a key the database does not hold, or copied somewhere
    append-only, and neither belongs in a capstone; what belongs is being clear
    about which of the two this is.

    What is deliberately not stored: the radiograph, the score, or anything
    about the patient. The row says a person opened a case, not what they saw
    in it. An audit trail that duplicates the record it protects doubles the
    exposure rather than reducing it.
    """

    class Action(models.TextChoices):
        VIEWED = "VIEWED", "Viewed a case"
        SCREENED = "SCREENED", "Screened a radiograph"
        REVIEWED = "REVIEWED", "Recorded a review"
        LISTED = "LISTED", "Listed cases"
        SIGNED_IN = "SIGNED_IN", "Signed in"
        SIGNED_OUT = "SIGNED_OUT", "Signed out"
        REFUSED = "REFUSED", "Refused an action"

    # SET_NULL rather than CASCADE: deleting an account must not erase the
    # evidence of what it did. actor_label keeps the address as it was.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="access_events",
    )
    actor_label = models.CharField(max_length=254, blank=True)
    action = models.CharField(max_length=16, choices=Action.choices, db_index=True)

    # The case this concerns, by its public identifier rather than a foreign
    # key, so the trail survives a record being removed.
    case_id = models.UUIDField(null=True, blank=True, db_index=True)
    facility = models.CharField(max_length=120, blank=True, db_index=True)

    # Where from. Truncated user agents are useless and whole ones are long.
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=200, blank=True)

    detail = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # The chain. Set once, when the row is written, and never afterwards.
    previous_hash = models.CharField(max_length=64, blank=True, editable=False)
    entry_hash = models.CharField(max_length=64, blank=True, editable=False, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Access event"
        indexes = [
            models.Index(fields=["actor", "-created_at"]),
            models.Index(fields=["case_id", "-created_at"]),
        ]

    def __str__(self):
        who = self.actor_label or "anonymous"
        return f"{who} {self.get_action_display().lower()} at {self.created_at:%Y-%m-%d %H:%M}"

    # Every field whose alteration the chain should catch. created_at is in it,
    # so back-dating an event is as detectable as changing what it says.
    CHAINED_FIELDS = (
        "actor_id",
        "actor_label",
        "action",
        "case_id",
        "facility",
        "ip_address",
        "user_agent",
        "detail",
        "created_at",
    )

    def save(self, *args, **kwargs):
        """Link this row to the one before it, once, on the way in."""
        if self.entry_hash:
            super().save(*args, **kwargs)
            return

        previous = (
            AccessEvent.objects.order_by("-id").values_list("entry_hash", flat=True).first()
            or ""
        )
        # created_at is set by auto_now_add during the insert, so the hash
        # cannot include it until the row exists. The row is written first and
        # sealed immediately afterwards.
        super().save(*args, **kwargs)
        self.previous_hash = previous
        self.entry_hash = self.compute_hash(previous)
        super().save(update_fields=["previous_hash", "entry_hash"])

    def compute_hash(self, previous_hash=""):
        """This row's hash, given the hash of the row before it.

        The values are joined with a unit separator rather than a comma or a
        space: it is a control character, so it cannot appear in an address, a
        clinic name or a user agent, and two different rows cannot be made to
        produce the same string by moving a character from one field into the
        next.
        """
        import hashlib

        parts = [previous_hash]
        for name in self.CHAINED_FIELDS:
            value = getattr(self, name, None)
            parts.append("" if value is None else str(value))
        return hashlib.sha256(FIELD_SEPARATOR.join(parts).encode("utf-8")).hexdigest()

    @classmethod
    def verify_chain(cls):
        """Walk the log and report the first row that does not add up.

        Returns (checked, problems), where a problem names the row and what is
        wrong with it. An empty list means every row still hashes to what it
        did when it was written, and that none has been removed from between
        two others.
        """
        problems = []
        previous = ""
        checked = 0

        for event in cls.objects.order_by("id").iterator():
            checked += 1
            if event.previous_hash != previous:
                problems.append(
                    f"row {event.pk}: expected to follow {previous[:12] or '(start)'}, "
                    f"claims to follow {event.previous_hash[:12] or '(start)'}: "
                    "a row before this one was altered or removed"
                )
            expected = event.compute_hash(event.previous_hash)
            if event.entry_hash != expected:
                problems.append(
                    f"row {event.pk}: contents do not match its hash; "
                    "this row was altered after it was written"
                )
            previous = event.entry_hash

        return checked, problems

    @classmethod
    def record(cls, request, action, *, case_id=None, facility="", detail=""):
        """Write one event. Never raises.

        An audit failure must not take down the thing being audited: a
        clinician should not lose a screening because the log could not be
        written. The failure is itself logged, so a trail that has stopped
        recording is visible rather than silent.
        """
        import logging

        user = getattr(request, "user", None)
        signed_in = bool(user and user.is_authenticated)

        try:
            return cls.objects.create(
                actor=user if signed_in else None,
                actor_label=(user.email or user.get_username()) if signed_in else "",
                action=action,
                case_id=case_id,
                facility=facility,
                ip_address=cls.client_ip(request),
                user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:200],
                detail=detail[:200],
            )
        except Exception:
            logging.getLogger(__name__).exception("Could not write an access event")
            return None

    @staticmethod
    def client_ip(request):
        """The caller's address, trusting the proxy header only when configured.

        X-Forwarded-For is set by the client when nothing strips it, so it is
        read only where the deployment has said it sits behind a proxy. Taking
        it otherwise would let a caller write any address it liked into the
        audit trail.
        """
        from django.conf import settings as django_settings

        if getattr(django_settings, "SECURE_PROXY_SSL_HEADER", None):
            forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
            if forwarded:
                return forwarded.split(",")[0].strip() or None
        return request.META.get("REMOTE_ADDR") or None
