"""Upload and review forms, with validation messages written for clinical staff."""

from pathlib import Path

from django import forms
from django.conf import settings
from django.template.defaultfilters import filesizeformat

from .models import PredictionRecord

ACCEPTED_SUFFIXES = {".png", ".jpg", ".jpeg"}

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


class ReviewForm(forms.Form):
    """Records a reviewer's decision and note against a case."""

    reviewer_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    status_set = forms.ChoiceField(
        choices=PredictionRecord.ReviewStatus.choices,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    note = forms.CharField(
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )
