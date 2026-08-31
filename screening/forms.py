"""Upload and review forms, with validation messages written for clinical staff."""

from pathlib import Path

from django import forms
from django.conf import settings
from django.template.defaultfilters import filesizeformat

from .models import PredictionRecord

ACCEPTED_SUFFIXES = {".png", ".jpg", ".jpeg"}


class ScreeningUploadForm(forms.Form):
    """Collects a case reference and a chest radiograph for screening."""

    patient_reference = forms.CharField(
        max_length=32,
        help_text="A non-identifying reference for this case, for example DEMO-001.",
        widget=forms.TextInput(
            attrs={"class": "form-control", "autocomplete": "off", "placeholder": "DEMO-001"}
        ),
    )
    xray_image = forms.ImageField(
        help_text="PNG, JPG or JPEG export of a chest radiograph.",
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control", "accept": ".png,.jpg,.jpeg"}
        ),
    )

    def clean_patient_reference(self):
        reference = self.cleaned_data["patient_reference"].strip()
        if not reference:
            raise forms.ValidationError("Enter a case reference.")
        return reference

    def clean_xray_image(self):
        """Check the extension and size.

        Django's ImageField has already confirmed the file decodes as an image,
        which is what rules out a renamed document or an corrupt upload. The
        checks here cover the file type we accept and the size limit.
        """
        image = self.cleaned_data["xray_image"]

        suffix = Path(image.name).suffix.lower()
        if suffix not in ACCEPTED_SUFFIXES:
            raise forms.ValidationError(
                "That file type is not supported. Upload a PNG, JPG or JPEG image."
            )

        if image.size > settings.MAX_UPLOAD_BYTES:
            raise forms.ValidationError(
                "That image is %(actual)s, which is larger than the %(limit)s limit."
                % {
                    "actual": filesizeformat(image.size),
                    "limit": filesizeformat(settings.MAX_UPLOAD_BYTES),
                }
            )

        return image


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
