"""Upload and review forms, with validation messages written for clinical staff."""

from pathlib import Path

from allauth.socialaccount.forms import SignupForm as SocialAccountSignupForm
from django import forms
from django.conf import settings
from django.template.defaultfilters import filesizeformat

from .models import Facility, PredictionRecord, Profile, profile_for

# The roles a person may choose for themselves: every role the model defines
# except administrator. Derived rather than listed, so a role added later is
# offered without this being remembered, and the one exclusion stays exact.
SELECTABLE_ROLES = [
    (value, label)
    for value, label in Profile.Role.choices
    if value != Profile.Role.ADMINISTRATOR
]

ACCEPTED_SUFFIXES = {".png", ".jpg", ".jpeg"}


def active_facilities(including=None):
    """The clinics a user may choose.

    Retired ones are not offered, but one already recorded against a profile
    stays selectable so that saving an unrelated change does not quietly move
    someone out of their clinic.
    """
    from django.db.models import Q

    condition = Q(is_active=True)
    if including:
        condition |= Q(pk=including)
    return Facility.objects.filter(condition)


# A clinic working through a morning's films wants to submit them together
# rather than one at a time. The cap exists because screening happens inside
# the request: each image costs an inference and a heatmap, so an unbounded
# selection would hold the connection open for minutes and time out.
MAX_BATCH_IMAGES = 20


class MultipleFileInput(forms.ClearableFileInput):
    """A file input that accepts more than one selection.

    Django's widgets reject multiple files by default, because most forms want
    one. Opting in is a single flag, but it has to be set explicitly.
    """

    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    """An ImageField that validates every file in a multiple selection.

    forms.ImageField cleans one file. With a multiple-selection widget the data
    arrives as a list, so each entry is cleaned separately and the results are
    returned as a list. One bad file fails the field, which is what the upload
    page needs: nothing is screened until the whole selection is acceptable.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if not isinstance(data, list | tuple):
            data = [data] if data not in self.empty_values else []

        if len(data) > MAX_BATCH_IMAGES:
            raise forms.ValidationError(
                f"That is {len(data)} images. Upload at most {MAX_BATCH_IMAGES} at a time."
            )

        cleaned = [single(item, initial) for item in data]
        if not cleaned and self.required:
            raise forms.ValidationError(self.error_messages["required"], code="required")
        return cleaned


class ScreeningUploadForm(forms.Form):
    """Collects a case reference and a chest radiograph for screening."""

    patient_reference = forms.CharField(
        max_length=32,
        help_text="A non-identifying reference for this case, for example DEMO-001.",
        widget=forms.TextInput(
            attrs={"class": "form-control", "autocomplete": "off", "placeholder": "DEMO-001"}
        ),
    )
    xray_image = MultipleImageField(
        help_text=(
            "PNG, JPG or JPEG exports of chest radiographs. Select more than one "
            f"to screen a batch, up to {MAX_BATCH_IMAGES}."
        ),
        widget=MultipleFileInput(
            attrs={"class": "form-control", "accept": ".png,.jpg,.jpeg", "multiple": True}
        ),
    )

    def clean_patient_reference(self):
        reference = self.cleaned_data["patient_reference"].strip()
        if not reference:
            raise forms.ValidationError("Enter a case reference.")
        return reference

    def clean_xray_image(self):
        """Check every selected file for extension and size.

        Django's ImageField has already confirmed each file decodes as an image,
        which is what rules out a renamed document or a corrupt upload. The
        checks here cover the file type we accept and the size limit, and name
        the offending file so a rejected batch says which one to replace.
        """
        images = self.cleaned_data["xray_image"]
        limit = filesizeformat(settings.MAX_UPLOAD_BYTES)

        for image in images:
            if Path(image.name).suffix.lower() not in ACCEPTED_SUFFIXES:
                raise forms.ValidationError(
                    f"{image.name} is not a supported file type. "
                    "Upload PNG, JPG or JPEG images."
                )

            if image.size > settings.MAX_UPLOAD_BYTES:
                actual = filesizeformat(image.size)
                raise forms.ValidationError(
                    f"{image.name} is {actual}, which is larger than the {limit} limit."
                )

        return images


class ProfileForm(forms.ModelForm):
    """The parts of a profile its owner may set themselves.

    Role is not among them. A user who could choose their own role could grant
    themselves review rights, which would make the role meaningless; it is set
    by an administrator through the Django admin.
    """

    class Meta:
        model = Profile
        fields = ["facility"]
        widgets = {"facility": forms.Select(attrs={"class": "form-select"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only clinics still in use are offered, but a profile already pointing
        # at a retired one keeps it rather than being silently cleared on the
        # next save.
        field = self.fields["facility"]
        field.queryset = active_facilities(including=self.instance.facility_id)
        field.empty_label = "Not set"


class ReviewForm(forms.Form):
    """Records a reviewer's decision and note against a case.

    The reviewer is no longer asked for their name: there is a session, so the
    note is attributed to whoever is signed in. A typed name was unverifiable
    and a clinical record should not carry one.
    """

    status_set = forms.ChoiceField(
        choices=PredictionRecord.ReviewStatus.choices,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    note = forms.CharField(
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )


class SocialSignupForm(SocialAccountSignupForm):
    """Completes a new account on its first Google sign-in.

    Google supplies an identity and an email address. It does not know which
    clinic this person works at, and it has no opinion about what they are
    allowed to do here, so the first sign-in asks for the one and explains the
    other.

    Role is asked here, between the two clinical roles only. What separates a
    radiographer from a clinician is which work a person does, and the person
    signing in is the one who knows that; nobody else is present at this
    moment to be asked.

    Administrator is not offered and cannot be submitted. It is not a kind of
    clinical work, it is the right to change what everyone else may do, so a
    form offering it would let anybody take it. It is bound to one address in
    the environment, granted when the account is created, and reachable from
    no form at all. The choices below are built from the model's own roles
    with that one removed, so a role added later appears here and the
    exclusion stays exact.

    This does mean a new account can call itself a clinician and so may record
    reviews. That is a deliberate loosening: every review carries the name and
    the account that recorded it in a hash-chained trail, and an administrator
    can correct a role afterwards, so the claim is attributable rather than
    anonymous.

    There is no username field either. ACCOUNT_SIGNUP_FIELDS already limits
    allauth to the email address, so allauth derives a username itself and a
    clinician is never asked to invent one.
    """

    first_name = forms.CharField(
        max_length=150,
        label="First name",
        widget=forms.TextInput(attrs={"class": "form-control", "autocomplete": "given-name"}),
    )
    last_name = forms.CharField(
        max_length=150,
        label="Surname",
        widget=forms.TextInput(attrs={"class": "form-control", "autocomplete": "family-name"}),
    )
    facility = forms.ModelChoiceField(
        queryset=Facility.objects.none(),
        required=False,
        empty_label="Not set",
        label="Clinic or hospital",
        help_text=(
            "Optional, and changeable later. Records are shared with everyone "
            "at the same clinic."
        ),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    role = forms.ChoiceField(
        choices=SELECTABLE_ROLES,
        initial=Profile.Role.RADIOGRAPHER,
        label="Your role",
        help_text=(
            "A radiographer captures and screens. A clinician may also record "
            "a review, which is a clinical judgement and is recorded against "
            "your name."
        ),
        widget=forms.RadioSelect,
        error_messages={"invalid_choice": "Choose one of the roles offered."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Google has already supplied these and verified the address, so they
        # are shown as confirmation rather than asked for again. The email
        # field stays disabled: editing it here would claim an address Google
        # never vouched for.
        if "email" in self.fields:
            self.fields["email"].widget.attrs.update(
                {"class": "form-control", "readonly": True}
            )
        # Populated here rather than at import, so a clinic added today is
        # offered without restarting the application.
        self.fields["facility"].queryset = active_facilities()

        for name in ("first_name", "last_name"):
            initial = self.initial.get(name) or ""
            if initial:
                self.fields[name].initial = initial

    def save(self, request):
        user = super().save(request)

        user.first_name = self.cleaned_data["first_name"].strip()
        user.last_name = self.cleaned_data["last_name"].strip()
        user.save(update_fields=["first_name", "last_name"])

        # The signal has already created the profile by this point, so this
        # fills it in rather than creating a second one.
        profile = profile_for(user)
        profile.facility = self.cleaned_data.get("facility")
        # Not when the account is the administrator's. The signal granted that
        # role as the account was made, and this form's own choices never
        # include it, so writing the chosen role here unconditionally would
        # demote the one account that cannot be restored from any form.
        if profile.role != Profile.Role.ADMINISTRATOR:
            profile.role = self.cleaned_data["role"]
        profile.save(update_fields=["facility", "role", "updated_at"])

        return user


class EmailEntryForm(forms.Form):
    """The single field on the gate.

    Deliberately only an address. Whether it belongs to an existing account is
    something the system looks up, not something the person is asked to
    declare, so there is nothing else to fill in here.
    """

    email = forms.EmailField(
        error_messages={
            "required": "Enter your email address.",
            "invalid": "That does not look like an email address.",
        }
    )

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()
