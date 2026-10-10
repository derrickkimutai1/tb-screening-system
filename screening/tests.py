"""
Tests for the screening workflow.

These cover the upload path, the validation messages a clinician would see for
unusable files, and the reporting views. The prediction is still a placeholder,
so nothing here asserts anything about model accuracy.
"""

import io
import shutil
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

import numpy as np
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import PredictionRecord, ReviewNote

sys.path.insert(0, str(settings.ML_DIR))
import preprocessing  # noqa: E402

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
        self.assertRedirects(response, reverse("screening:case_detail", args=[record.case_id]))

    def test_upload_stores_the_model_and_thresholds_used(self):
        """A record must remain interpretable after thresholds are revised."""
        from screening.services.predict import PredictionEngine

        thresholds = PredictionEngine.metadata()["thresholds"]

        self.client.post(
            reverse("screening:upload"),
            {"patient_reference": "DEMO-101", "xray_image": make_image()},
        )
        record = PredictionRecord.objects.get()

        self.assertEqual(record.decision_threshold, Decimal(str(thresholds["decision"])))
        self.assertEqual(
            record.triage_low_medium_threshold, Decimal(str(thresholds["triage_low_medium"]))
        )
        self.assertEqual(
            record.triage_medium_high_threshold,
            Decimal(str(thresholds["triage_medium_high"])),
        )
        self.assertEqual(record.model_version, "tb_mobilenetv2_v1")

    def test_upload_records_a_real_prediction(self):
        """The stored score must come from the model, not a fixed value."""
        self.client.post(
            reverse("screening:upload"),
            {"patient_reference": "DEMO-104", "xray_image": make_image()},
        )
        record = PredictionRecord.objects.get()

        self.assertGreaterEqual(record.tb_probability, Decimal("0"))
        self.assertLessEqual(record.tb_probability, Decimal("1"))
        self.assertIn(record.predicted_label, PredictionRecord.PredictedLabel.values)
        self.assertIn(record.triage_level, PredictionRecord.TriageLevel.values)
        self.assertTrue(record.triage_justification)
        self.assertIsNotNone(record.inference_ms)

    def test_upload_records_the_image_quality_assessment(self):
        self.client.post(
            reverse("screening:upload"),
            {"patient_reference": "DEMO-105", "xray_image": make_image()},
        )
        record = PredictionRecord.objects.get()

        self.assertIn(record.quality_status, PredictionRecord.QualityStatus.values)
        self.assertIsNotNone(record.blur_score)
        self.assertIsNotNone(record.brightness_mean)

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


class PreprocessingTests(TestCase):
    """The image preparation shared by training and inference.

    A mismatch between the two would not raise an error, it would simply make
    every prediction meaningless, so the behaviour is pinned here.
    """

    def test_output_shape_and_range(self):
        prepared = preprocessing.prepare(make_image(size=(700, 900)))

        self.assertEqual(prepared.shape, (224, 224, 3))
        self.assertEqual(prepared.dtype, np.float32)
        self.assertGreaterEqual(prepared.min(), -1.0)
        self.assertLessEqual(prepared.max(), 1.0)

    def test_all_source_colour_modes_produce_the_same_result(self):
        """Montgomery is greyscale, Shenzhen mixes palette and RGB."""
        grey = Image.new("L", (300, 300), color=128)
        outputs = []
        for mode in ("L", "P", "RGB"):
            buffer = io.BytesIO()
            grey.convert(mode).save(buffer, format="PNG")
            buffer.seek(0)
            outputs.append(preprocessing.prepare(buffer))

        for other in outputs[1:]:
            np.testing.assert_array_equal(outputs[0], other)

    def test_scaling_matches_keras_preprocess_input(self):
        """Our scaling must equal the function MobileNetV2 was trained with."""
        from tensorflow.keras.applications.mobilenet_v2 import preprocess_input

        source = make_image(size=(400, 320))
        ours = preprocessing.prepare(source)

        source.seek(0)
        with Image.open(source) as image:
            resized = image.convert("L").resize((224, 224), Image.Resampling.BILINEAR)
        raw = np.repeat(np.asarray(resized, dtype=np.float32)[..., np.newaxis], 3, axis=-1)

        np.testing.assert_array_equal(ours, preprocess_input(raw))

    def test_label_is_read_from_the_filename_suffix(self):
        self.assertEqual(preprocessing.label_from_filename("MCUCXR_0001_0.png"), 0)
        self.assertEqual(preprocessing.label_from_filename("CHNCXR_0002_1.png"), 1)

        with self.assertRaises(ValueError):
            preprocessing.label_from_filename("radiograph.png")

    def test_batch_stacks_images(self):
        batch = preprocessing.prepare_batch([make_image(), make_image()])
        self.assertEqual(batch.shape, (2, 224, 224, 3))

    def test_single_image_is_shaped_as_a_batch_of_one(self):
        self.assertEqual(preprocessing.as_model_input(make_image()).shape, (1, 224, 224, 3))


class QualityCheckerTests(TestCase):
    """Image quality checking, proposal Objective 4."""

    def setUp(self):
        from screening.services.quality import ImageQualityChecker

        self.checker = ImageQualityChecker()
        self.folder = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def write(self, array, name="test.png"):
        path = Path(self.folder) / name
        Image.fromarray(array.astype("uint8")).save(path)
        return path

    def textured(self, brightness=150, size=512):
        """An image with enough detail to pass the sharpness check."""
        rng = np.random.default_rng(3)
        noise = rng.normal(0, 40, (size, size))
        return np.clip(noise + brightness, 0, 255)

    def test_a_detailed_well_exposed_image_is_acceptable(self):
        report = self.checker.check(self.write(self.textured()))
        self.assertEqual(report.status, "ACCEPTABLE")
        self.assertEqual(report.message, "")

    def test_a_flat_image_is_flagged_as_blurred(self):
        flat = np.full((512, 512), 150.0)
        report = self.checker.check(self.write(flat))

        self.assertEqual(report.status, "DEGRADED")
        self.assertIn("blurred", report.message)
        self.assertLess(report.blur_score, 100)

    def test_a_dark_image_is_flagged(self):
        report = self.checker.check(self.write(self.textured(brightness=30)))

        self.assertEqual(report.status, "DEGRADED")
        self.assertIn("darker", report.message)

    def test_a_bright_image_is_flagged(self):
        report = self.checker.check(self.write(self.textured(brightness=240)))

        self.assertEqual(report.status, "DEGRADED")
        self.assertIn("brighter", report.message)

    def test_a_file_that_is_not_an_image_is_invalid(self):
        path = Path(self.folder) / "notes.txt"
        path.write_text("this is not an image", encoding="utf-8")
        report = self.checker.check(path)

        self.assertEqual(report.status, "INVALID")
        self.assertFalse(report.is_usable)

    def test_a_degraded_image_is_still_usable(self):
        """Poor quality warns the clinician; it does not block the screening."""
        report = self.checker.check(self.write(np.full((512, 512), 150.0)))
        self.assertTrue(report.is_usable)


class TriageTests(TestCase):
    """Triage is arithmetic on the score, not a second model."""

    def setUp(self):
        from screening.services.triage import TriageJustifier

        self.justifier = TriageJustifier()

    def decide(self, probability):
        return self.justifier.decide(probability, 0.362, 0.959)

    def test_below_the_lower_threshold_is_low_suspicion(self):
        decision = self.decide(0.1234)
        self.assertEqual(decision.level, "LOW")
        self.assertIn("0.1234", decision.justification)
        self.assertIn("0.362", decision.justification)

    def test_between_the_thresholds_is_medium_suspicion(self):
        self.assertEqual(self.decide(0.5000).level, "MEDIUM")

    def test_at_or_above_the_upper_threshold_is_high_suspicion(self):
        self.assertEqual(self.decide(0.9590).level, "HIGH")
        self.assertEqual(self.decide(0.9900).level, "HIGH")

    def test_exactly_on_the_lower_threshold_is_medium(self):
        """The boundary belongs to the band above it, matching the label rule."""
        self.assertEqual(self.decide(0.3620).level, "MEDIUM")

    def test_every_decision_explains_itself(self):
        for probability in (0.05, 0.5, 0.99):
            self.assertTrue(self.decide(probability).justification)
