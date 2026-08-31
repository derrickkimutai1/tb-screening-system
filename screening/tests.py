"""
Tests for the screening workflow.

These cover the upload path, the validation messages a clinician would see for
unusable files, and the reporting views. The prediction is still a placeholder,
so nothing here asserts anything about model accuracy.
"""

import io
import shutil
import tempfile
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import PredictionRecord, ReviewNote

MEDIA_FOR_TESTS = tempfile.mkdtemp()


def make_image(name="chest.png", size=(64, 64), fmt="PNG"):
    """Build a small valid greyscale image in memory."""
    buffer = io.BytesIO()
    Image.new("L", size, color=110).save(buffer, format=fmt)
    buffer.seek(0)
    content_type = "image/png" if fmt == "PNG" else "image/jpeg"
    return SimpleUploadedFile(name, buffer.read(), content_type=content_type)


@override_settings(MEDIA_ROOT=MEDIA_FOR_TESTS)
class UploadTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_FOR_TESTS, ignore_errors=True)
        super().tearDownClass()

    def test_valid_upload_creates_record_and_redirects(self):
        response = self.client.post(
            reverse("screening:upload"),
            {"patient_reference": "DEMO-100", "xray_image": make_image()},
        )

        self.assertEqual(PredictionRecord.objects.count(), 1)
        record = PredictionRecord.objects.get()
        self.assertEqual(record.patient_reference, "DEMO-100")
        self.assertRedirects(
            response, reverse("screening:case_detail", args=[record.case_id])
        )

    def test_upload_stores_the_thresholds_used(self):
        """A record must remain interpretable after thresholds are revised."""
        self.client.post(
            reverse("screening:upload"),
            {"patient_reference": "DEMO-101", "xray_image": make_image()},
        )
        record = PredictionRecord.objects.get()

        self.assertEqual(record.decision_threshold, Decimal("0.500"))
        self.assertEqual(record.triage_low_medium_threshold, Decimal("0.500"))
        self.assertEqual(record.triage_medium_high_threshold, Decimal("0.800"))
        self.assertEqual(record.model_version, "placeholder-0")

    def test_unsupported_file_type_is_rejected_with_a_readable_message(self):
        bad = SimpleUploadedFile("notes.txt", b"this is not an image", "text/plain")
        response = self.client.post(
            reverse("screening:upload"),
            {"patient_reference": "DEMO-102", "xray_image": bad},
        )

        self.assertEqual(PredictionRecord.objects.count(), 0)
        self.assertContains(response, "valid image", status_code=200)

    def test_missing_case_reference_is_rejected(self):
        response = self.client.post(
            reverse("screening:upload"),
            {"patient_reference": "", "xray_image": make_image()},
        )
        self.assertEqual(PredictionRecord.objects.count(), 0)
        self.assertEqual(response.status_code, 200)

    @override_settings(MAX_UPLOAD_BYTES=500)
    def test_oversized_image_is_rejected(self):
        response = self.client.post(
            reverse("screening:upload"),
            {"patient_reference": "DEMO-103", "xray_image": make_image(size=(400, 400))},
        )
        self.assertEqual(PredictionRecord.objects.count(), 0)
        self.assertContains(response, "larger than", status_code=200)


@override_settings(MEDIA_ROOT=MEDIA_FOR_TESTS)
class ReportingTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_FOR_TESTS, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        for reference in ("DEMO-201", "DEMO-202"):
            self.client.post(
                reverse("screening:upload"),
                {"patient_reference": reference, "xray_image": make_image()},
            )

    def test_case_list_shows_stored_records(self):
        response = self.client.get(reverse("screening:case_list"))
        self.assertContains(response, "DEMO-201")
        self.assertContains(response, "DEMO-202")

    def test_case_list_filters_by_reference(self):
        response = self.client.get(reverse("screening:case_list"), {"reference": "201"})
        self.assertContains(response, "DEMO-201")
        self.assertNotContains(response, "DEMO-202")

    def test_dashboard_counts_match_stored_records(self):
        response = self.client.get(reverse("screening:dashboard"))
        self.assertEqual(response.context["total"], 2)
        self.assertEqual(response.context["pending"], 2)
        self.assertEqual(response.context["follow_up"], 0)

    def test_dashboard_handles_an_empty_database(self):
        PredictionRecord.objects.all().delete()
        response = self.client.get(reverse("screening:dashboard"))
        self.assertEqual(response.context["total"], 0)
        self.assertContains(response, "No screening records yet")

    def test_review_appends_a_note_and_updates_the_case_status(self):
        record = PredictionRecord.objects.first()
        self.client.post(
            reverse("screening:case_detail", args=[record.case_id]),
            {
                "reviewer_name": "D. Kimutai",
                "status_set": PredictionRecord.ReviewStatus.FOLLOW_UP,
                "note": "Referred for confirmatory testing.",
            },
        )
        record.refresh_from_db()

        self.assertEqual(record.review_status, PredictionRecord.ReviewStatus.FOLLOW_UP)
        self.assertEqual(record.review_notes.count(), 1)
        self.assertEqual(ReviewNote.objects.get().reviewer_name, "D. Kimutai")
