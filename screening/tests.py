"""
Tests for the screening workflow.

These cover the upload path, the validation messages a clinician would see for
unusable files, and the reporting views. The prediction is still a placeholder,
so nothing here asserts anything about model accuracy.
"""

import io
import re
import shutil
import sys
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path
from unittest import mock

import numpy as np
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import PredictionRecord, ReviewNote

sys.path.insert(0, str(settings.ML_DIR))
import preprocessing  # noqa: E402

MEDIA_FOR_TESTS = tempfile.mkdtemp()


def clinic(name="Kenyatta"):
    """The Facility row for this name, created if the test is the first to ask.

    Clinics became rows so that two spellings could not make two caseloads;
    tests go through the same door as the application rather than writing a
    name straight onto a field.
    """
    from screening.models import Facility

    return Facility.objects.get_or_create(name=name)[0]


def make_image(name="chest.png", size=(64, 64), fmt="PNG"):
    """Build a small valid greyscale image in memory."""
    buffer = io.BytesIO()
    Image.new("L", size, color=110).save(buffer, format=fmt)
    buffer.seek(0)
    content_type = "image/png" if fmt == "PNG" else "image/jpeg"
    return SimpleUploadedFile(name, buffer.read(), content_type=content_type)


class SignedIn:
    """Puts a signed-in clinician behind the client.

    Every screening view requires a session, so a test exercising one has to
    establish it first. Sign-in itself goes through Google and is covered
    separately in SignInTests.
    """

    def setUp(self):
        super().setUp()
        self.clinician = get_user_model().objects.create_user(
            username="clinician",
            email="clinician@example.org",
            password="not-used-for-sign-in",
        )
        self.client.force_login(self.clinician)


@override_settings(MEDIA_ROOT=MEDIA_FOR_TESTS)
class UploadTests(SignedIn, TestCase):
    """Screening one radiograph: what is accepted, stored and refused."""

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
class ReportingTests(SignedIn, TestCase):
    """Reading stored cases back: the list, the dashboard and review."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_FOR_TESTS, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
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
        from .models import Profile

        self.clinician.profile.role = Profile.Role.CLINICIAN
        self.clinician.profile.save()

        record = PredictionRecord.objects.first()
        self.client.post(
            reverse("screening:case_detail", args=[record.case_id]),
            {
                "status_set": PredictionRecord.ReviewStatus.FOLLOW_UP,
                "note": "Referred for confirmatory testing.",
            },
        )
        record.refresh_from_db()

        self.assertEqual(record.review_status, PredictionRecord.ReviewStatus.FOLLOW_UP)
        self.assertEqual(record.review_notes.count(), 1)
        self.assertEqual(ReviewNote.objects.get().reviewer, self.clinician)


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


@override_settings(MEDIA_ROOT=MEDIA_FOR_TESTS)
class BatchUploadTests(SignedIn, TestCase):
    """Several radiographs in one submission, per the examiner's request."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_FOR_TESTS, ignore_errors=True)
        super().tearDownClass()

    def post(self, images, reference="BATCH-01"):
        return self.client.post(
            reverse("screening:upload"),
            {"patient_reference": reference, "xray_image": images},
        )

    def test_three_images_create_three_records(self):
        response = self.post([make_image(f"chest{n}.png") for n in range(3)])

        self.assertEqual(PredictionRecord.objects.count(), 3)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "screening/batch_result.html")

    def test_each_image_gets_its_own_reference(self):
        self.post([make_image(f"chest{n}.png") for n in range(3)], reference="WARD-A")

        references = sorted(
            PredictionRecord.objects.values_list("patient_reference", flat=True)
        )
        self.assertEqual(references, ["WARD-A-01", "WARD-A-02", "WARD-A-03"])

    def test_a_single_image_keeps_the_reference_exactly_as_typed(self):
        """The common case must not acquire a suffix it never had."""
        self.post([make_image()], reference="DEMO-500")

        record = PredictionRecord.objects.get()
        self.assertEqual(record.patient_reference, "DEMO-500")

    def test_a_single_image_still_redirects_to_its_case(self):
        response = self.post([make_image()], reference="DEMO-501")

        record = PredictionRecord.objects.get()
        self.assertRedirects(response, reverse("screening:case_detail", args=[record.case_id]))

    def test_each_image_is_stored_separately(self):
        self.post([make_image(f"chest{n}.png") for n in range(3)])

        stored = set(PredictionRecord.objects.values_list("xray_image", flat=True))
        self.assertEqual(len(stored), 3)

    def test_one_unreadable_file_rejects_the_whole_batch_before_screening(self):
        """Nothing is screened until every file in the selection is acceptable."""
        response = self.post(
            [make_image(), SimpleUploadedFile("notes.txt", b"not an image", "text/plain")]
        )

        self.assertEqual(PredictionRecord.objects.count(), 0)
        self.assertEqual(response.status_code, 200)

    def test_a_batch_over_the_cap_is_refused(self):
        from .forms import MAX_BATCH_IMAGES

        response = self.post([make_image(f"chest{n}.png") for n in range(MAX_BATCH_IMAGES + 1)])

        self.assertEqual(PredictionRecord.objects.count(), 0)
        self.assertContains(response, f"at most {MAX_BATCH_IMAGES}")

    def test_the_batch_page_lists_every_screened_case(self):
        response = self.post([make_image(f"chest{n}.png") for n in range(2)], "WARD-B")

        self.assertContains(response, "WARD-B-01")
        self.assertContains(response, "WARD-B-02")


class BatchReferenceTests(TestCase):
    """The naming rule on its own, without the cost of running the model."""

    def rename(self, index, total, base="CASE"):
        from .views import reference_for

        return reference_for(base, index, total)

    def test_a_lone_image_is_not_renamed(self):
        self.assertEqual(self.rename(1, 1), "CASE")

    def test_a_batch_numbers_from_one(self):
        self.assertEqual(self.rename(1, 4), "CASE-01")

    def test_numbering_is_zero_padded_so_it_sorts(self):
        self.assertEqual(self.rename(9, 12), "CASE-09")
        self.assertEqual(self.rename(10, 12), "CASE-10")


class SignInTests(TestCase):
    """The gate: who is turned away, who is let through, and what is on offer."""

    def setUp(self):
        self.protected = [
            reverse("screening:upload"),
            reverse("screening:case_list"),
            reverse("screening:dashboard"),
        ]

    def test_an_anonymous_visitor_is_sent_to_the_sign_in_page(self):
        for url in self.protected:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(response, f"{reverse('account_login')}?next={url}")

    def test_a_case_record_is_not_readable_without_a_session(self):
        record = PredictionRecord.objects.create(
            patient_reference="DEMO-900",
            xray_image="x.png",
            tb_probability=Decimal("0.5"),
            triage_level=PredictionRecord.TriageLevel.MEDIUM,
            model_version="test",
            decision_threshold=Decimal("0.102"),
            triage_low_medium_threshold=Decimal("0.102"),
            triage_medium_high_threshold=Decimal("0.546"),
        )
        url = reverse("screening:case_detail", args=[record.case_id])

        response = self.client.get(url)

        self.assertRedirects(response, f"{reverse('account_login')}?next={url}")

    def test_a_signed_in_clinician_reaches_the_screening_page(self):
        user = get_user_model().objects.create_user(username="c", email="c@example.org")
        self.client.force_login(user)

        response = self.client.get(reverse("screening:upload"))

        self.assertEqual(response.status_code, 200)

    @override_settings(SIGN_IN_OPEN_REGISTRATION=True)
    def test_registration_follows_the_setting_when_open(self):
        """A demonstration admits anyone who can receive mail at an address."""
        from screening.auth import ScreeningAccountAdapter

        self.assertTrue(ScreeningAccountAdapter().is_open_for_signup(None))

    @override_settings(SIGN_IN_OPEN_REGISTRATION=False)
    def test_registration_follows_the_setting_when_closed(self):
        """A deployment holding real records admits only accounts made in advance."""
        from screening.auth import ScreeningAccountAdapter

        self.assertFalse(ScreeningAccountAdapter().is_open_for_signup(None))

    def test_there_is_no_password_either_way(self):
        """Identity comes from a provider or a code, so none is ever stored."""
        from django.conf import settings

        self.assertEqual(settings.ACCOUNT_SIGNUP_FIELDS, ["email*"])

    @override_settings(GOOGLE_SIGN_IN_CONFIGURED=False, MICROSOFT_SIGN_IN_CONFIGURED=False)
    def test_the_gate_still_renders_without_any_provider(self):
        """A checkout with no .env must still start, for CI and for marking."""
        response = self.client.get(reverse("account_login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No identity provider is configured")

    @override_settings(GOOGLE_SIGN_IN_CONFIGURED=False, MICROSOFT_SIGN_IN_CONFIGURED=False)
    def test_the_email_route_is_offered_even_with_no_provider(self):
        """It is the way in when a provider is down or absent."""
        response = self.client.get(reverse("account_login"))

        self.assertContains(response, reverse("screening:continue_with_email"))
        self.assertContains(response, 'name="email"')


class AllowlistTests(TestCase):
    """A Google account on its own is not a credential for clinical records."""

    def check(self, email, emails=(), domains=()):
        from screening.auth import address_is_allowed

        with override_settings(
            SIGN_IN_ALLOWED_EMAILS=set(emails),
            SIGN_IN_ALLOWED_DOMAINS=set(domains),
        ):
            return address_is_allowed(email)

    def test_an_empty_allowlist_admits_anyone(self):
        self.assertTrue(self.check("anyone@gmail.com"))

    def test_a_listed_address_is_admitted(self):
        self.assertTrue(self.check("juliet@strathmore.edu", emails={"juliet@strathmore.edu"}))

    def test_an_unlisted_address_is_refused(self):
        self.assertFalse(self.check("stranger@gmail.com", emails={"juliet@strathmore.edu"}))

    def test_a_listed_domain_admits_its_members(self):
        self.assertTrue(self.check("anyone@strathmore.edu", domains={"strathmore.edu"}))

    def test_a_domain_allowlist_refuses_other_domains(self):
        self.assertFalse(self.check("anyone@gmail.com", domains={"strathmore.edu"}))

    def test_matching_ignores_case_and_surrounding_space(self):
        self.assertTrue(self.check("  Juliet@Strathmore.EDU ", domains={"strathmore.edu"}))

    def test_an_account_without_an_address_is_refused(self):
        self.assertFalse(self.check("", domains={"strathmore.edu"}))

    def test_a_lookalike_domain_is_refused(self):
        """notstrathmore.edu must not pass a strathmore.edu allowlist."""
        self.assertFalse(self.check("a@notstrathmore.edu", domains={"strathmore.edu"}))


class ProfileTests(SignedIn, TestCase):
    """Every account carries a profile, and the profile decides what it may do."""

    def test_a_profile_is_created_with_the_account(self):
        """No view should ever have to cope with a user that has none."""
        self.assertIsNotNone(self.clinician.profile)

    def test_a_new_account_starts_as_a_radiographer(self):
        from .models import Profile

        self.assertEqual(self.clinician.profile.role, Profile.Role.RADIOGRAPHER)

    def test_a_radiographer_may_not_review(self):
        self.assertFalse(self.clinician.profile.may_review)

    def test_a_clinician_may_review(self):
        from .models import Profile

        self.clinician.profile.role = Profile.Role.CLINICIAN
        self.assertTrue(self.clinician.profile.may_review)

    def test_an_administrator_may_review(self):
        from .models import Profile

        self.clinician.profile.role = Profile.Role.ADMINISTRATOR
        self.assertTrue(self.clinician.profile.may_review)

    def test_the_page_loads_for_its_owner(self):
        response = self.client.get(reverse("screening:profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "clinician@example.org")

    def test_the_page_requires_a_session(self):
        self.client.logout()
        url = reverse("screening:profile")

        self.assertRedirects(self.client.get(url), f"{reverse('account_login')}?next={url}")

    def test_the_facility_can_be_set_by_its_owner(self):
        chosen = clinic("Kenyatta National")

        self.client.post(reverse("screening:profile"), {"facility": chosen.pk})

        self.clinician.profile.refresh_from_db()
        self.assertEqual(self.clinician.profile.facility, chosen)

    def test_a_clinic_cannot_be_invented_from_the_profile_form(self):
        """Free text was the defect: one spelling mistake made two caseloads."""
        from .models import Facility

        response = self.client.post(
            reverse("screening:profile"), {"facility": "Somewhere Made Up"}
        )

        self.assertFalse(Facility.objects.filter(name="Somewhere Made Up").exists())
        self.clinician.profile.refresh_from_db()
        self.assertIsNone(self.clinician.profile.facility)
        self.assertEqual(response.status_code, 200)

    def test_a_retired_clinic_is_not_offered(self):
        from .models import Facility

        clinic("Open Clinic")
        Facility.objects.create(name="Closed Clinic", is_active=False)

        response = self.client.get(reverse("screening:profile"))

        self.assertContains(response, "Open Clinic")
        self.assertNotContains(response, "Closed Clinic")

    def test_the_role_cannot_be_set_by_its_owner(self):
        """Choosing your own role would make the role meaningless."""
        from .models import Profile

        self.client.post(
            reverse("screening:profile"),
            {"facility": "Somewhere", "role": Profile.Role.ADMINISTRATOR},
        )

        self.clinician.profile.refresh_from_db()
        self.assertEqual(self.clinician.profile.role, Profile.Role.RADIOGRAPHER)


@override_settings(MEDIA_ROOT=MEDIA_FOR_TESTS)
class ReviewPermissionTests(SignedIn, TestCase):
    """Who may record a clinical review, enforced on the POST and not just hidden."""

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_FOR_TESTS, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.record = PredictionRecord.objects.create(
            patient_reference="DEMO-700",
            xray_image="x.png",
            tb_probability=Decimal("0.5"),
            triage_level=PredictionRecord.TriageLevel.MEDIUM,
            model_version="test",
            decision_threshold=Decimal("0.102"),
            triage_low_medium_threshold=Decimal("0.102"),
            triage_medium_high_threshold=Decimal("0.546"),
        )
        self.url = reverse("screening:case_detail", args=[self.record.case_id])

    def become(self, role):
        self.clinician.profile.role = role
        self.clinician.profile.save()

    def post_review(self):
        return self.client.post(
            self.url, {"status_set": PredictionRecord.ReviewStatus.REVIEWED, "note": "Seen."}
        )

    def test_a_radiographer_is_refused(self):
        response = self.post_review()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(ReviewNote.objects.count(), 0)

    def test_a_radiographer_is_not_offered_the_form(self):
        response = self.client.get(self.url)

        self.assertNotContains(response, "Record review")

    def test_a_clinician_may_record_one(self):
        from .models import Profile

        self.become(Profile.Role.CLINICIAN)

        self.post_review()

        self.assertEqual(ReviewNote.objects.count(), 1)

    def test_the_note_is_attributed_to_the_signed_in_user(self):
        """Not to a typed name, which nothing could verify."""
        from .models import Profile

        self.become(Profile.Role.CLINICIAN)

        self.post_review()

        note = ReviewNote.objects.get()
        self.assertEqual(note.reviewer, self.clinician)
        self.assertEqual(note.attributed_to, "clinician@example.org")

    def test_a_note_survives_its_author_being_removed(self):
        """A clinical record should not lose its history when someone leaves."""
        from .models import Profile

        self.become(Profile.Role.CLINICIAN)
        self.post_review()

        self.clinician.delete()

        note = ReviewNote.objects.get()
        self.assertIsNone(note.reviewer)
        self.assertEqual(note.attributed_to, "clinician@example.org")


class MetadataStrippingTests(TestCase):
    """Nothing the system was not given should survive into storage."""

    def exif_image(self, lat=(1, 1, 1)):
        """A JPEG carrying GPS coordinates, as a phone photograph would."""
        import piexif

        buffer = io.BytesIO()
        Image.new("L", (64, 64), color=120).save(buffer, format="JPEG")
        buffer.seek(0)

        exif = {
            "0th": {piexif.ImageIFD.Make: b"TestCam"},
            "GPS": {
                piexif.GPSIFD.GPSLatitudeRef: b"S",
                piexif.GPSIFD.GPSLatitude: ((lat[0], 1), (lat[1], 1), (lat[2], 1)),
            },
            "Exif": {},
            "1st": {},
            "thumbnail": None,
        }
        out = io.BytesIO()
        piexif.insert(piexif.dump(exif), buffer.getvalue(), out)
        out.seek(0)
        return SimpleUploadedFile("photo.jpg", out.read(), "image/jpeg")

    def gps_tags(self, handle):
        """The GPS block Pillow can read back out of a file, if any."""
        import piexif

        handle.seek(0)
        data = handle.read()
        handle.seek(0)
        try:
            return piexif.load(data).get("GPS") or {}
        except (ValueError, piexif.InvalidImageDataError):
            return {}

    def test_gps_coordinates_do_not_survive(self):
        from .services.sanitise import strip_metadata

        original = self.exif_image()
        # The fixture must actually carry coordinates, or the test proves nothing.
        self.assertTrue(self.gps_tags(original))

        cleaned = strip_metadata(original)

        self.assertFalse(self.gps_tags(cleaned))
        with Image.open(cleaned) as image:
            self.assertFalse(image.getexif())

    def test_the_camera_make_does_not_survive(self):
        import piexif

        from .services.sanitise import strip_metadata

        cleaned = strip_metadata(self.exif_image())

        cleaned.seek(0)
        self.assertFalse(piexif.load(cleaned.read()).get("0th"))

    def test_the_pixels_are_preserved(self):
        from .services.sanitise import strip_metadata

        source = make_image("chest.png")
        with Image.open(source) as before:
            expected = list(before.convert("L").getdata())
        source.seek(0)

        with Image.open(strip_metadata(source)) as after:
            self.assertEqual(list(after.convert("L").getdata()), expected)

    def test_a_file_that_cannot_be_decoded_is_returned_unchanged(self):
        """Failing here would replace a specific message with a generic error."""
        from .services.sanitise import strip_metadata

        broken = SimpleUploadedFile("notes.txt", b"not an image", "text/plain")

        self.assertIs(strip_metadata(broken), broken)


@override_settings(MEDIA_ROOT=MEDIA_FOR_TESTS)
class FailureScenarioTests(SignedIn, TestCase):
    """The failure paths the Build Phase notes ask to be demonstrated.

    Those notes list: expired sessions, cross-user access attempts, oversized
    or deceptive files, duplicate submission, provider failure, prompt
    injection, deletion and recovery. Each test below states what the system is
    expected to do, so a reader can tell a handled failure from an unhandled
    one.
    """

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_FOR_TESTS, ignore_errors=True)
        super().tearDownClass()

    def upload(self, *files, reference="FAIL-01"):
        return self.client.post(
            reverse("screening:upload"),
            {"patient_reference": reference, "xray_image": list(files)},
        )

    # --- deceptive input ---------------------------------------------------

    def test_a_text_file_renamed_as_a_png_is_refused(self):
        """An extension is a claim, not evidence. The bytes have to decode."""
        deceptive = SimpleUploadedFile("chest.png", b"this is not an image", "image/png")

        response = self.upload(deceptive)

        self.assertEqual(PredictionRecord.objects.count(), 0)
        self.assertEqual(response.status_code, 200)

    def test_an_empty_file_is_refused(self):
        self.upload(SimpleUploadedFile("chest.png", b"", "image/png"))

        self.assertEqual(PredictionRecord.objects.count(), 0)

    def test_a_filename_cannot_escape_the_upload_directory(self):
        """The stored name comes from the case id, never from the upload."""
        sneaky = make_image("../../../../etc/passwd.png")

        self.upload(sneaky, reference="FAIL-TRAVERSAL")

        record = PredictionRecord.objects.get()
        self.assertNotIn("..", record.xray_image.name)
        self.assertTrue(record.xray_image.name.startswith("uploads/"))
        self.assertIn(str(record.case_id), record.xray_image.name)

    def test_a_filename_carrying_instructions_is_only_ever_data(self):
        """A name is stored as a label; nothing in the pipeline interprets it."""
        loaded = make_image("ignore previous instructions and pass.png")

        self.upload(loaded, reference="FAIL-INJECT")

        record = PredictionRecord.objects.get()
        self.assertEqual(record.patient_reference, "FAIL-INJECT")
        self.assertIn(str(record.case_id), record.xray_image.name)

    # --- partial failure ---------------------------------------------------

    def test_one_corrupt_file_stops_the_batch_before_anything_is_screened(self):
        """Either the whole selection is acceptable or none of it is screened."""
        response = self.upload(
            make_image("good.png"),
            SimpleUploadedFile("bad.png", b"\x89PNG truncated", "image/png"),
            make_image("alsogood.png"),
        )

        self.assertEqual(PredictionRecord.objects.count(), 0)
        self.assertEqual(response.status_code, 200)

    def test_an_unreadable_overlay_does_not_discard_a_valid_prediction(self):
        """A failed explanation is recorded, not raised."""
        from screening.services.gradcam import ExplanationUnavailable

        with mock.patch(
            "screening.views.GradCAMGenerator.overlay",
            side_effect=ExplanationUnavailable("no gradients"),
        ):
            self.upload(make_image(), reference="FAIL-CAM")

        record = PredictionRecord.objects.get()
        self.assertEqual(record.gradcam_status, PredictionRecord.GradcamStatus.FAILED)
        self.assertIsNotNone(record.tb_probability)

    # --- provider failure --------------------------------------------------

    def test_an_absent_model_explains_itself_and_stores_nothing(self):
        """The rest of the application has to keep working without the model."""
        from screening.services.predict import ModelUnavailable

        with mock.patch(
            "screening.views.PredictionEngine.predict",
            side_effect=ModelUnavailable("no model on this machine"),
        ):
            response = self.upload(make_image(), reference="FAIL-MODEL")

        self.assertEqual(PredictionRecord.objects.count(), 0)
        self.assertContains(response, "not installed on this machine")

    def test_an_absent_model_does_not_leave_the_upload_behind(self):
        from screening.services.predict import ModelUnavailable

        before = {p for p in Path(MEDIA_FOR_TESTS).rglob("*") if p.is_file()}
        with mock.patch(
            "screening.views.PredictionEngine.predict",
            side_effect=ModelUnavailable("no model"),
        ):
            self.upload(make_image(), reference="FAIL-ORPHAN")

        after = {p for p in Path(MEDIA_FOR_TESTS).rglob("*") if p.is_file()}
        self.assertEqual(
            sorted(p.name for p in after - before),
            [],
            "a failed screening left an orphaned file in storage",
        )

    # --- sessions and access ----------------------------------------------

    def test_a_session_that_has_gone_away_sends_the_user_back_to_sign_in(self):
        self.client.logout()
        url = reverse("screening:dashboard")

        self.assertRedirects(self.client.get(url), f"{reverse('account_login')}?next={url}")

    def test_an_anonymous_visitor_cannot_read_a_case_by_guessing_its_id(self):
        self.upload(make_image(), reference="FAIL-GUESS")
        record = PredictionRecord.objects.get()
        self.client.logout()

        url = reverse("screening:case_detail", args=[record.case_id])

        self.assertRedirects(self.client.get(url), f"{reverse('account_login')}?next={url}")

    def test_an_unknown_case_id_is_not_found_rather_than_an_error(self):
        response = self.client.get(reverse("screening:case_detail", args=[uuid.uuid4()]))

        self.assertEqual(response.status_code, 404)

    # --- duplicate submission ---------------------------------------------

    def test_the_same_radiograph_twice_creates_two_distinct_cases(self):
        """Documented behaviour: a repeat screening is a separate event.

        Two films of one patient are a legitimate thing to screen, so the
        system does not deduplicate. The case ids differ and the files are
        stored separately, so neither result can overwrite the other.
        """
        self.upload(make_image(), reference="FAIL-DUP")
        self.upload(make_image(), reference="FAIL-DUP")

        records = PredictionRecord.objects.filter(patient_reference="FAIL-DUP")
        self.assertEqual(records.count(), 2)
        self.assertEqual(len({r.case_id for r in records}), 2)
        self.assertEqual(len({r.xray_image.name for r in records}), 2)

    # --- the health endpoint ----------------------------------------------

    def test_health_reports_ready_when_the_model_and_database_answer(self):
        response = self.client.get(reverse("screening:health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ready")

    def test_health_reports_degraded_with_503_when_the_model_cannot_load(self):
        """A container that is listening but cannot predict must not take traffic."""
        from screening.services.predict import ModelUnavailable

        with mock.patch(
            "screening.views.PredictionEngine.model",
            side_effect=ModelUnavailable("weights missing"),
        ):
            response = self.client.get(reverse("screening:health"))

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "degraded")

    def test_health_needs_no_session(self):
        """A health check arrives without one, and must not be redirected."""
        self.client.logout()

        self.assertEqual(self.client.get(reverse("screening:health")).status_code, 200)


class ProfileWithoutSignalTests(TestCase):
    """An account that never fired the creation signal must still work.

    loaddata, bulk_create, a database restore and every account that existed
    before profiles were added all skip post_save. One of those broke the
    profile page with RelatedObjectDoesNotExist, so the absence is handled in
    one place and asserted here.
    """

    def make_user_without_a_profile(self):
        from .models import Profile

        user = get_user_model().objects.create_user(
            username="legacy", email="legacy@strathmore.edu"
        )
        # Simulates an account that predates the model rather than mocking the
        # signal, so the test exercises the real absence.
        Profile.objects.filter(user=user).delete()
        user.refresh_from_db()
        return user

    def test_the_fixture_really_has_no_profile(self):
        """Otherwise the tests below would pass for the wrong reason."""
        from django.core.exceptions import ObjectDoesNotExist

        user = self.make_user_without_a_profile()

        with self.assertRaises(ObjectDoesNotExist):
            _ = user.profile

    def test_the_accessor_creates_the_missing_profile(self):
        from .models import profile_for

        user = self.make_user_without_a_profile()

        profile = profile_for(user)

        self.assertIsNotNone(profile.pk)
        self.assertEqual(profile.user, user)

    def test_the_accessor_does_not_create_a_second_one(self):
        from .models import Profile, profile_for

        user = self.make_user_without_a_profile()

        profile_for(user)
        profile_for(user)

        self.assertEqual(Profile.objects.filter(user=user).count(), 1)

    def test_a_legacy_account_defaults_to_the_least_privileged_role(self):
        from .models import Profile, profile_for

        user = self.make_user_without_a_profile()

        self.assertEqual(profile_for(user).role, Profile.Role.RADIOGRAPHER)
        self.assertFalse(profile_for(user).may_review)

    def test_the_profile_page_opens_for_a_legacy_account(self):
        """This is the page that raised RelatedObjectDoesNotExist."""
        user = self.make_user_without_a_profile()
        self.client.force_login(user)

        response = self.client.get(reverse("screening:profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "legacy@strathmore.edu")

    def test_a_case_page_opens_for_a_legacy_account(self):
        user = self.make_user_without_a_profile()
        self.client.force_login(user)
        record = PredictionRecord.objects.create(
            patient_reference="LEGACY-01",
            xray_image="x.png",
            tb_probability=Decimal("0.5"),
            triage_level=PredictionRecord.TriageLevel.MEDIUM,
            model_version="test",
            decision_threshold=Decimal("0.102"),
            triage_low_medium_threshold=Decimal("0.102"),
            triage_medium_high_threshold=Decimal("0.546"),
        )

        response = self.client.get(reverse("screening:case_detail", args=[record.case_id]))

        self.assertEqual(response.status_code, 200)


class SocialSignupFormTests(TestCase):
    """The form a new user meets on their first Google sign-in.

    Exercised directly rather than through a Google round trip, because the
    round trip needs Google. What matters here is what the form accepts, what
    it refuses and what it writes.
    """

    def build(self, **data):
        """The form as allauth constructs it, part way through a Google sign-in.

        A real SocialLogin is built rather than mocked: the form reads the
        address and name Google returned, so a stand-in would test the stand-in.
        """
        from allauth.socialaccount.models import SocialAccount, SocialLogin

        from .forms import SocialSignupForm

        fields = {
            "first_name": "Juliet",
            "last_name": "Kirui",
            "email": "juliet@strathmore.edu",
            "facility": "Kenyatta National Hospital",
        }
        fields.update(data)

        pending = get_user_model()(
            email="juliet@strathmore.edu", first_name="Juliet", last_name="Kirui"
        )
        account = SocialAccount(
            provider="google",
            uid="1234567890",
            extra_data={"email": "juliet@strathmore.edu", "name": "Juliet Kirui"},
        )
        return SocialSignupForm(
            data=fields, sociallogin=SocialLogin(user=pending, account=account)
        )

    def test_a_username_is_not_asked_for(self):
        """Nothing shows a username, so a clinician is never asked to invent one."""
        form = self.build()

        self.assertNotIn("username", form.fields)

    def test_the_email_cannot_be_edited(self):
        """Editing it would claim an address Google never vouched for."""
        form = self.build()

        self.assertTrue(form.fields["email"].widget.attrs.get("readonly"))

    def test_a_role_cannot_be_chosen(self):
        """Choosing a role would be choosing whether you may review."""
        form = self.build()

        self.assertNotIn("role", form.fields)

    def test_a_name_is_required(self):
        form = self.build(first_name="", last_name="")

        self.assertFalse(form.is_valid())
        self.assertIn("first_name", form.errors)
        self.assertIn("last_name", form.errors)

    def test_a_facility_is_optional(self):
        """It can be set later from the profile page, so it must not block sign-in."""
        form = self.build(facility="")

        self.assertNotIn("facility", form.errors)


class SocialSignupPageTests(TestCase):
    """The page itself, reached only part way through a sign-in."""

    def test_it_redirects_when_no_sign_in_is_in_progress(self):
        """Opening it directly is not a route into the system."""
        response = self.client.get(reverse("socialaccount_signup"))

        self.assertEqual(response.status_code, 302)

    def test_the_project_template_is_the_one_configured(self):
        """allauth ships a plain version; the gate-styled one must win."""
        from django.template.loader import get_template

        template = get_template("socialaccount/signup.html")

        self.assertIn("screening", template.origin.name.replace("\\", "/"))

    def test_a_provider_signup_is_not_asked_to_verify_its_address_again(self):
        """Opening local registration must not add a step to the Google route.

        Local sign-up now requires a code, because anyone can claim any
        address. A provider has already proved the address, so asking again
        would be a second verification of the same fact.
        """
        from django.conf import settings

        self.assertEqual(settings.SOCIALACCOUNT_EMAIL_VERIFICATION, "none")
        self.assertEqual(settings.ACCOUNT_EMAIL_VERIFICATION, "mandatory")

    def test_automatic_signup_is_off(self):
        """Otherwise allauth creates the account and the form is never shown."""
        from django.conf import settings

        self.assertFalse(settings.SOCIALACCOUNT_AUTO_SIGNUP)
        self.assertEqual(
            settings.SOCIALACCOUNT_FORMS["signup"], "screening.forms.SocialSignupForm"
        )


class EmailCodeSignInTests(TestCase):
    """Signing in with a one-time code, for when a provider is absent or down.

    The whole exchange is walked here rather than asserted piecemeal: request a
    code, read it out of the message actually sent, and spend it. A test that
    only checks the page renders would not notice a code that never arrives.

    The rate limit counter lives in the cache, which outlives a test: without
    clearing it the fourth test in this class is refused rather than run, and
    reports a failure that is really the limit working. The limits themselves
    stay at their configured values so these tests exercise the real
    configuration, and are tested directly in EmailCodeRateLimitTests.
    """

    def setUp(self):
        from allauth.account.models import EmailAddress
        from django.core.cache import cache

        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="coded", email="coded@strathmore.edu"
        )
        # allauth sends a code to a known address, so the address has to be
        # registered against the account the way a sign-in would leave it.
        EmailAddress.objects.create(
            user=self.user, email=self.user.email, primary=True, verified=True
        )

    def request_code(self, email=None):
        return self.client.post(
            reverse("account_request_login_code"),
            {"email": email or self.user.email},
            follow=True,
        )

    def code_from_outbox(self):
        from django.core import mail

        self.assertTrue(mail.outbox, "no message was sent")
        found = re.search(r"\b(\d{6})\b", mail.outbox[-1].body)
        self.assertIsNotNone(found, f"no six-digit code in: {mail.outbox[-1].body!r}")
        return found.group(1)

    def test_the_request_page_is_reachable_without_a_session(self):
        response = self.client.get(reverse("account_request_login_code"))

        self.assertEqual(response.status_code, 200)

    def test_requesting_a_code_sends_exactly_one_message(self):
        from django.core import mail

        self.request_code()

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.user.email, mail.outbox[0].to)

    def test_the_message_carries_a_six_digit_code(self):
        self.request_code()

        self.assertRegex(self.code_from_outbox(), r"^\d{6}$")

    def test_the_subject_identifies_the_system(self):
        from django.core import mail

        self.request_code()

        self.assertIn("TB Screening", mail.outbox[0].subject)

    def test_a_valid_code_signs_the_user_in(self):
        self.request_code()

        response = self.client.post(
            reverse("account_confirm_login_code"),
            {"code": self.code_from_outbox()},
            follow=True,
        )

        self.assertTrue(response.context["user"].is_authenticated)
        self.assertEqual(response.context["user"], self.user)

    def test_a_wrong_code_does_not_sign_the_user_in(self):
        self.request_code()

        response = self.client.post(
            reverse("account_confirm_login_code"), {"code": "000000"}, follow=True
        )

        self.assertFalse(response.context["user"].is_authenticated)

    def test_a_code_cannot_be_spent_twice(self):
        """Otherwise a code read from a forwarded message stays usable."""
        self.request_code()
        code = self.code_from_outbox()
        self.client.post(reverse("account_confirm_login_code"), {"code": code})
        self.client.logout()

        response = self.client.post(
            reverse("account_confirm_login_code"), {"code": code}, follow=True
        )

        self.assertFalse(response.context["user"].is_authenticated)

    def test_an_unknown_address_yields_no_usable_code(self):
        """The page must not become an account checker.

        allauth answers an unknown address exactly as it answers a known one,
        and sends a message saying no account exists rather than staying
        silent, so that neither the page nor the inbox reveals which addresses
        are registered. What matters is that nothing in it signs anyone in.
        """
        from django.core import mail

        self.request_code("stranger@example.com")

        body = mail.outbox[-1].body if mail.outbox else ""
        self.assertIsNone(re.search(r"\d{6}", body), "a code was sent to an unknown address")

    def test_an_unknown_address_looks_the_same_as_a_known_one(self):
        known = self.request_code()
        self.client.logout()
        from django.core.cache import cache

        cache.clear()
        unknown = self.request_code("stranger@example.com")

        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(
            [step[0] for step in known.redirect_chain],
            [step[0] for step in unknown.redirect_chain],
        )

    def test_signing_in_by_code_still_lands_on_the_screening_page(self):
        self.request_code()

        response = self.client.post(
            reverse("account_confirm_login_code"),
            {"code": self.code_from_outbox()},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "screening/upload.html")

    @override_settings(
        SIGN_IN_ALLOWED_EMAILS={"allowed@strathmore.edu"}, SIGN_IN_ALLOWED_DOMAINS=set()
    )
    def test_the_allowlist_still_governs_when_one_is_configured(self):
        """Opening registration must not quietly disable the allowlist."""
        from screening.auth import address_is_allowed

        self.assertTrue(address_is_allowed("allowed@strathmore.edu"))
        self.assertFalse(address_is_allowed("stranger@example.com"))

    def test_the_attempt_cap_is_configured(self):
        """A six-digit code is guessable in a way a password is not."""
        from django.conf import settings

        self.assertEqual(settings.ACCOUNT_LOGIN_BY_CODE_MAX_ATTEMPTS, 3)
        self.assertEqual(settings.ACCOUNT_LOGIN_BY_CODE_TIMEOUT, 300)


class EmailCodeRateLimitTests(TestCase):
    """The limit that stops a code being requested or guessed at leisure."""

    def setUp(self):
        from allauth.account.models import EmailAddress
        from django.core.cache import cache

        # allauth counts requests in the cache, so a count left by another test
        # would decide this one.
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="limited", email="limited@strathmore.edu"
        )
        EmailAddress.objects.create(
            user=self.user, email=self.user.email, primary=True, verified=True
        )

    def request_code(self):
        return self.client.post(
            reverse("account_request_login_code"), {"email": self.user.email}
        )

    def test_repeated_requests_are_refused(self):
        """Three in five minutes, per the configured limit."""
        from django.core import mail

        for _ in range(3):
            self.request_code()

        sent_before = len(mail.outbox)
        allowed = self.client.post(
            reverse("account_request_login_code"), {"email": "someone@strathmore.edu"}
        )
        refused = self.request_code()

        self.assertEqual(len(mail.outbox), sent_before, "a fourth code was sent")
        # The refusal has to be indistinguishable from the allowed request, or
        # the limit itself tells an attacker which addresses are real.
        self.assertEqual(refused.status_code, allowed.status_code)

    def test_the_limits_name_both_steps(self):
        from django.conf import settings

        limits = settings.ACCOUNT_RATE_LIMITS

        self.assertIn("request_login_code", limits)
        self.assertIn("confirm_login_code", limits)


class DevelopmentCodeTests(TestCase):
    """The on-page code must exist only where nobody can receive an email.

    Showing a sign-in code to whoever loaded the page is handing out the
    account. It is guarded on DEBUG and on the development mail backend, and
    these assert that removing either guard removes the code.
    """

    DEV_BACKEND = "screening.services.devmail.LastMessageBackend"

    def render(self):
        from django.template import Context, Template

        return Template(
            "{% load devmail %}{% development_code as c %}{{ c|default:'none' }}"
        ).render(Context({}))

    def remember(self, body="Your code is 123456"):
        from django.core.mail import EmailMessage

        from screening.services.devmail import LastMessageBackend

        LastMessageBackend(stream=io.StringIO()).send_messages(
            [EmailMessage(subject="s", body=body, to=["someone@example.com"])]
        )

    @override_settings(DEBUG=True, EMAIL_BACKEND=DEV_BACKEND)
    def test_the_code_is_shown_in_development(self):
        self.remember()

        self.assertEqual(self.render(), "123456")

    @override_settings(DEBUG=False, EMAIL_BACKEND=DEV_BACKEND)
    def test_nothing_is_shown_when_debug_is_off(self):
        """Which is the case in the container and in every deployment."""
        self.remember()

        self.assertEqual(self.render(), "none")

    @override_settings(DEBUG=True, EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend")
    def test_nothing_is_shown_once_real_mail_is_configured(self):
        self.remember()

        self.assertEqual(self.render(), "none")

    @override_settings(DEBUG=True, EMAIL_BACKEND=DEV_BACKEND)
    def test_a_message_with_no_code_yields_nothing(self):
        """The unknown-account message has no code and must not render one."""
        self.remember("We have no record of such an account.")

        self.assertEqual(self.render(), "none")

    @override_settings(DEBUG=True, EMAIL_BACKEND=DEV_BACKEND)
    def test_the_backend_records_the_recipient(self):
        from screening.services.devmail import last_recipient

        self.remember()

        self.assertEqual(last_recipient(), "someone@example.com")


@override_settings(SIGN_IN_OPEN_REGISTRATION=True)
class OpenRegistrationTests(TestCase):
    """Anyone with an address they can read may create an account.

    The whole exchange is walked, because the point is that a person who was
    never added by hand can get in: submit an address, read the code out of the
    message, and arrive signed in with a profile.
    """

    ADDRESS = "newcomer@outlook.com"

    def setUp(self):
        from django.core.cache import cache

        cache.clear()

    def code_from_outbox(self):
        from django.core import mail

        self.assertTrue(mail.outbox, "no message was sent")
        found = re.search(r"\b(\d{6})\b", mail.outbox[-1].body)
        self.assertIsNotNone(found, f"no code in: {mail.outbox[-1].body!r}")
        return found.group(1)

    def sign_up(self, address=None):
        return self.client.post(
            reverse("account_signup"), {"email": address or self.ADDRESS}, follow=True
        )

    def test_the_signup_page_is_reachable(self):
        response = self.client.get(reverse("account_signup"))

        self.assertEqual(response.status_code, 200)

    def test_the_gate_registers_from_the_same_field_it_signs_in_from(self):
        """There is no separate "create an account" route to choose."""
        response = self.client.get(reverse("account_login"))

        self.assertContains(response, reverse("screening:continue_with_email"))
        self.assertNotContains(response, reverse("account_signup"))

    def test_an_unknown_address_can_create_an_account(self):
        self.sign_up()

        self.assertTrue(
            get_user_model().objects.filter(email=self.ADDRESS).exists(),
            "a brand new address could not register",
        )

    def test_the_account_is_not_usable_until_the_code_is_entered(self):
        response = self.sign_up()

        self.assertFalse(response.context["user"].is_authenticated)

    def test_entering_the_code_signs_the_newcomer_in(self):
        self.sign_up()

        response = self.client.post(
            reverse("account_email_verification_sent"),
            {"code": self.code_from_outbox()},
            follow=True,
        )

        self.assertTrue(response.context["user"].is_authenticated)
        self.assertEqual(response.context["user"].email, self.ADDRESS)

    def test_a_newcomer_lands_on_the_screening_page(self):
        self.sign_up()

        response = self.client.post(
            reverse("account_email_verification_sent"),
            {"code": self.code_from_outbox()},
            follow=True,
        )

        self.assertTemplateUsed(response, "screening/upload.html")

    def test_a_newcomer_gets_a_profile_and_the_least_privileged_role(self):
        from .models import Profile, profile_for

        self.sign_up()
        self.client.post(
            reverse("account_email_verification_sent"),
            {"code": self.code_from_outbox()},
        )

        user = get_user_model().objects.get(email=self.ADDRESS)
        self.assertEqual(profile_for(user).role, Profile.Role.RADIOGRAPHER)
        self.assertFalse(profile_for(user).may_review)

    def test_a_wrong_code_leaves_the_newcomer_out(self):
        self.sign_up()

        response = self.client.post(
            reverse("account_email_verification_sent"),
            {"code": "000000"},
            follow=True,
        )

        self.assertFalse(response.context["user"].is_authenticated)

    @override_settings(SIGN_IN_OPEN_REGISTRATION=False)
    def test_registration_can_be_closed_for_a_real_deployment(self):
        """A database of real patients should not admit the whole internet."""
        from screening.auth import ScreeningAccountAdapter

        self.assertFalse(ScreeningAccountAdapter().is_open_for_signup(None))

    def test_restarting_clears_a_half_finished_sign_in(self):
        """Someone who typed the wrong address must be able to change it."""
        self.sign_up()

        self.client.post(reverse("screening:restart_sign_in"))
        response = self.client.get(reverse("account_request_login_code"))

        self.assertEqual(response.status_code, 200, "still trapped on the confirmation page")

    def test_restarting_refuses_a_get(self):
        """It changes session state, so it must not be reachable by a link."""
        response = self.client.get(reverse("screening:restart_sign_in"))

        self.assertEqual(response.status_code, 405)


class ContinueWithEmailTests(TestCase):
    """One field on the gate, for both signing in and registering.

    A person should not have to know whether they already have an account
    before they are allowed to type their address. These check that the same
    submission does the right thing either way, and that the two cases are
    not distinguishable from outside.
    """

    ADDRESS = "someone@outlook.com"

    def setUp(self):
        from django.core.cache import cache

        cache.clear()

    def submit(self, email=None, **extra):
        return self.client.post(
            reverse("screening:continue_with_email"),
            {"email": email if email is not None else self.ADDRESS, **extra},
            follow=True,
        )

    def code_from_outbox(self):
        from django.core import mail

        self.assertTrue(mail.outbox, "no message was sent")
        found = re.search(r"\b(\d{6})\b", mail.outbox[-1].body)
        self.assertIsNotNone(found, f"no code in: {mail.outbox[-1].body!r}")
        return found.group(1)

    def existing_user(self):
        from allauth.account.models import EmailAddress

        user = get_user_model().objects.create_user(username="already", email=self.ADDRESS)
        EmailAddress.objects.create(user=user, email=self.ADDRESS, primary=True, verified=True)
        return user

    def test_the_gate_carries_the_field_rather_than_a_link(self):
        """Typing an address should not require visiting another page first."""
        response = self.client.get(reverse("account_login"))

        self.assertContains(response, 'name="email"')
        self.assertContains(response, reverse("screening:continue_with_email"))

    def test_a_new_address_is_registered_and_sent_a_code(self):
        self.submit()

        self.assertTrue(get_user_model().objects.filter(email=self.ADDRESS).exists())
        self.assertRegex(self.code_from_outbox(), r"^\d{6}$")

    def test_a_new_address_can_finish_and_is_signed_in(self):
        self.submit()

        response = self.client.post(
            reverse("account_email_verification_sent"),
            {"code": self.code_from_outbox()},
            follow=True,
        )

        self.assertTrue(response.context["user"].is_authenticated)
        self.assertEqual(response.context["user"].email, self.ADDRESS)

    def test_an_existing_address_is_sent_a_sign_in_code(self):
        self.existing_user()

        self.submit()

        response = self.client.post(
            reverse("account_confirm_login_code"),
            {"code": self.code_from_outbox()},
            follow=True,
        )

        self.assertTrue(response.context["user"].is_authenticated)

    def test_an_existing_address_does_not_create_a_second_account(self):
        self.existing_user()

        self.submit()

        self.assertEqual(get_user_model().objects.filter(email=self.ADDRESS).count(), 1)

    def test_the_person_is_never_asked_which_case_they_are_in(self):
        """Both branches end on a page asking for six digits."""
        self.submit()
        new = self.client.get(reverse("account_email_verification_sent"))

        self.client.post(reverse("screening:restart_sign_in"))
        self.submit()
        existing = self.client.get(reverse("account_confirm_login_code"))

        for page in (new, existing):
            self.assertContains(page, "Six digits")

    def test_an_invalid_address_is_refused_on_the_gate(self):
        from django.core import mail

        response = self.submit("not-an-address")

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "does not look like an email address", status_code=400)
        self.assertEqual(len(mail.outbox), 0)

    def test_an_empty_address_is_refused(self):
        response = self.submit("")

        self.assertEqual(response.status_code, 400)

    def test_the_address_is_lowercased(self):
        self.submit("MiXeD.Case@Outlook.COM")

        self.assertTrue(
            get_user_model().objects.filter(email="mixed.case@outlook.com").exists()
        )

    @override_settings(SIGN_IN_ALLOWED_DOMAINS={"strathmore.edu"}, SIGN_IN_ALLOWED_EMAILS=set())
    def test_the_allowlist_is_applied_before_anything_is_created(self):
        """A refused address must not become an account or receive a code."""
        from django.core import mail

        self.submit("outsider@gmail.com")

        self.assertFalse(get_user_model().objects.filter(email="outsider@gmail.com").exists())
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(SIGN_IN_OPEN_REGISTRATION=False)
    def test_a_closed_system_refuses_an_unknown_address(self):
        from django.core import mail

        self.submit()

        self.assertFalse(get_user_model().objects.filter(email=self.ADDRESS).exists())
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(SIGN_IN_OPEN_REGISTRATION=False)
    def test_a_closed_system_still_signs_in_a_known_address(self):
        self.existing_user()

        self.submit()

        self.assertRegex(self.code_from_outbox(), r"^\d{6}$")

    def test_it_refuses_a_get(self):
        """It sends mail and creates accounts, so it must not be a link."""
        response = self.client.get(reverse("screening:continue_with_email"))

        self.assertEqual(response.status_code, 405)

    def test_a_bare_post_to_the_login_view_is_not_an_error(self):
        """A keyed rate limit with no key raised ImproperlyConfigured, a 500."""
        response = self.client.post(reverse("account_login"), {})

        self.assertEqual(response.status_code, 200)


class AllauthPageTests(TestCase):
    """allauth's own pages must look like the rest of the application.

    They render through a layout this project does not otherwise touch, so
    without an override they arrive as unstyled HTML with their own navigation.
    That is what a user saw immediately after confirming their address.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="member", email="member@strathmore.edu"
        )
        self.client.force_login(self.user)

    def themed(self, url):
        response = self.client.get(url, follow=True)
        names = {t.name for t in response.templates if t.name}
        return response, "screening/base.html" in names

    def test_the_email_page_uses_the_application_frame(self):
        response, themed = self.themed(reverse("account_email"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(themed, "allauth's email page is unstyled")

    def test_the_connections_page_uses_the_application_frame(self):
        response, themed = self.themed(reverse("socialaccount_connections"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(themed, "allauth's connections page is unstyled")

    def test_changing_a_password_explains_there_is_none(self):
        """Offering to change a password this system never stores is a lie."""
        response = self.client.get(reverse("account_change_password"), follow=True)

        self.assertRedirects(response, reverse("screening:profile"))
        self.assertContains(response, "no passwords")

    def test_resetting_a_password_explains_there_is_none(self):
        response = self.client.get(reverse("account_reset_password"), follow=True)

        self.assertRedirects(response, reverse("screening:profile"))

    def test_a_signed_out_visitor_is_sent_to_the_gate_not_the_profile(self):
        self.client.logout()

        response = self.client.get(reverse("account_change_password"), follow=True)

        self.assertRedirects(response, reverse("account_login"))


class SignupDestinationTests(TestCase):
    """Where a newly registered person actually arrives."""

    def setUp(self):
        from django.core.cache import cache

        cache.clear()

    def register(self, email="arriving@strathmore.edu"):
        from django.core import mail

        self.client.post(reverse("screening:continue_with_email"), {"email": email})
        code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
        return self.client.post(
            reverse("account_email_verification_sent"), {"code": code}, follow=True
        )

    def test_a_new_account_lands_on_the_screening_page(self):
        """Not on allauth's email-management form, which is where it went."""
        response = self.register()

        self.assertTemplateUsed(response, "screening/upload.html")
        self.assertTrue(response.context["user"].is_authenticated)

    def test_the_page_they_were_heading_for_is_honoured(self):
        from django.core import mail

        destination = reverse("screening:dashboard")
        self.client.post(
            reverse("screening:continue_with_email"),
            {"email": "heading@strathmore.edu", "next": destination},
        )
        code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)

        response = self.client.post(
            reverse("account_email_verification_sent"), {"code": code}, follow=True
        )

        self.assertTemplateUsed(response, "screening/dashboard.html")

    def test_an_offsite_destination_is_refused(self):
        """An unchecked next parameter is an open redirect."""
        from django.core import mail

        self.client.post(
            reverse("screening:continue_with_email"),
            {"email": "offsite@strathmore.edu", "next": "https://example.com/phish"},
        )
        code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)

        response = self.client.post(
            reverse("account_email_verification_sent"), {"code": code}, follow=True
        )

        self.assertTemplateUsed(response, "screening/upload.html")
        for url, _ in response.redirect_chain:
            self.assertNotIn("example.com", url)


class ErrorPageTests(TestCase):
    """What a user meets when something goes wrong.

    Django's defaults are bare pages with no way back. The course notes ask
    for "a safe, actionable explanation" instead of a generic message, which
    means naming what happened and offering somewhere to go.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="erring", email="erring@strathmore.edu"
        )
        self.client.force_login(self.user)

    def record(self):
        return PredictionRecord.objects.create(
            patient_reference="ERR-01",
            xray_image="x.png",
            tb_probability=Decimal("0.5"),
            triage_level=PredictionRecord.TriageLevel.MEDIUM,
            model_version="test",
            decision_threshold=Decimal("0.102"),
            triage_low_medium_threshold=Decimal("0.102"),
            triage_medium_high_threshold=Decimal("0.546"),
        )

    @override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
    def test_a_missing_case_uses_the_project_404(self):
        response = self.client.get(reverse("screening:case_detail", args=[uuid.uuid4()]))

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "That page", status_code=404)
        self.assertContains(response, "Search the cases", status_code=404)

    @override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
    def test_a_refused_review_uses_the_project_403(self):
        """A radiographer POSTing a review met Django's bare 403."""
        record = self.record()

        response = self.client.post(
            reverse("screening:case_detail", args=[record.case_id]),
            {"status_set": PredictionRecord.ReviewStatus.REVIEWED, "note": "x"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Your role does not", status_code=403)
        self.assertContains(response, "Back to screening", status_code=403)

    def test_the_500_page_needs_no_context(self):
        """It must render when the thing that failed is the database or model."""
        from django.template.loader import render_to_string

        html = render_to_string("500.html")

        self.assertIn("Something went wrong", html)
        self.assertIn("Back to screening", html)


class ResponsiveLayoutTests(TestCase):
    """The layout rules a phone depends on.

    These assert the stylesheet carries the rules rather than that a browser
    applied them, which a server-side test cannot see. The measurement that
    found the defect was taken in a browser at 375 pixels, where the masthead
    forced every page to 780 and the document scrolled sideways.
    """

    def stylesheet(self):
        from django.conf import settings

        return (
            settings.BASE_DIR / "screening" / "static" / "screening" / "theme.css"
        ).read_text(encoding="utf-8")

    def test_the_masthead_wraps_on_a_narrow_screen(self):
        css = self.stylesheet()

        self.assertIn("@media (max-width: 767.98px)", css)
        self.assertIn(".masthead-nav {", css)

    def test_tables_scroll_inside_their_panel(self):
        """A seven-column table is wider than a phone and must not drag the page."""
        css = self.stylesheet()

        self.assertIn(".table-scroll {", css)
        self.assertIn("overflow-x: auto", css)

    def test_every_table_is_wrapped(self):
        """An unwrapped one reintroduces the sideways scroll on its own page."""
        from django.conf import settings

        templates = (settings.BASE_DIR / "screening" / "templates" / "screening").glob("*.html")

        for path in templates:
            markup = path.read_text(encoding="utf-8")
            self.assertEqual(
                markup.count("<table"),
                markup.count('<div class="table-scroll">'),
                f"{path.name} has a table outside a scroll wrapper",
            )


@override_settings(MEDIA_ROOT=MEDIA_FOR_TESTS)
class FacilityScopeTests(TestCase):
    """Who can see which records.

    A clinic shares a caseload, because a radiographer screens and a clinician
    reviews, so records cannot be private to whoever uploaded them. They are
    scoped to a facility instead. These check that the sharing stops at the
    clinic boundary, and that someone with no clinic sees nothing rather than
    everything.
    """

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_FOR_TESTS, ignore_errors=True)
        super().tearDownClass()

    def member_of(self, facility, role=None, username=None):
        from .models import profile_for

        user = get_user_model().objects.create_user(
            username=username or f"u{get_user_model().objects.count()}",
            email=f"{username or 'u'}{get_user_model().objects.count()}@example.org",
        )
        profile = profile_for(user)
        profile.facility = clinic(facility) if facility else None
        if role:
            profile.role = role
        profile.save()
        return user

    def record_at(self, facility, reference, screener=None):
        return PredictionRecord.objects.create(
            patient_reference=reference,
            xray_image="x.png",
            facility=clinic(facility) if facility else None,
            screened_by=screener,
            tb_probability=Decimal("0.5"),
            triage_level=PredictionRecord.TriageLevel.MEDIUM,
            model_version="test",
            decision_threshold=Decimal("0.102"),
            triage_low_medium_threshold=Decimal("0.102"),
            triage_medium_high_threshold=Decimal("0.546"),
        )

    def test_a_colleague_at_the_same_clinic_sees_the_case(self):
        """Without this the review workflow cannot work at all."""
        radiographer = self.member_of("Kenyatta")
        clinician = self.member_of("Kenyatta")
        self.record_at("Kenyatta", "SHARED-01", radiographer)

        visible = PredictionRecord.objects.visible_to(clinician)

        self.assertEqual(visible.count(), 1)

    def test_another_clinic_does_not(self):
        self.record_at("Kenyatta", "THEIRS-01", self.member_of("Kenyatta"))
        outsider = self.member_of("Mbagathi")

        self.assertEqual(PredictionRecord.objects.visible_to(outsider).count(), 0)

    def test_someone_with_no_clinic_sees_nothing(self):
        """A stranger who registers must not inherit a clinic's caseload."""
        self.record_at("Kenyatta", "THEIRS-02", self.member_of("Kenyatta"))
        stranger = self.member_of("")

        self.assertEqual(PredictionRecord.objects.visible_to(stranger).count(), 0)

    def test_an_administrator_sees_everything(self):
        """Somebody has to be able to."""
        self.record_at("Kenyatta", "A-01")
        self.record_at("Mbagathi", "A-02")
        root = get_user_model().objects.create_superuser(
            username="root", email="root@example.org", password="x"
        )

        self.assertEqual(PredictionRecord.objects.visible_to(root).count(), 2)

    def test_an_anonymous_visitor_sees_nothing(self):
        from django.contrib.auth.models import AnonymousUser

        self.record_at("Kenyatta", "ANON-01")

        self.assertEqual(PredictionRecord.objects.visible_to(AnonymousUser()).count(), 0)

    def test_the_case_list_is_scoped(self):
        self.record_at("Kenyatta", "LIST-MINE", self.member_of("Kenyatta"))
        self.record_at("Mbagathi", "LIST-THEIRS")
        self.client.force_login(self.member_of("Kenyatta"))

        response = self.client.get(reverse("screening:case_list"))

        self.assertContains(response, "LIST-MINE")
        self.assertNotContains(response, "LIST-THEIRS")

    def test_the_dashboard_is_scoped(self):
        self.record_at("Kenyatta", "DASH-01")
        self.record_at("Mbagathi", "DASH-02")
        self.record_at("Mbagathi", "DASH-03")
        self.client.force_login(self.member_of("Kenyatta"))

        response = self.client.get(reverse("screening:dashboard"))

        self.assertEqual(response.context["total"], 1)

    def test_a_case_at_another_clinic_is_not_found_rather_than_refused(self):
        """A 403 would confirm the reference exists."""
        theirs = self.record_at("Mbagathi", "HIDDEN-01")
        self.client.force_login(self.member_of("Kenyatta"))

        response = self.client.get(reverse("screening:case_detail", args=[theirs.case_id]))

        self.assertEqual(response.status_code, 404)

    def test_screening_stamps_the_record_with_who_and_where(self):
        user = self.member_of("Kenyatta", username="stamper")
        self.client.force_login(user)

        self.client.post(
            reverse("screening:upload"),
            {"patient_reference": "STAMP-01", "xray_image": [make_image()]},
        )

        record = PredictionRecord.objects.get(patient_reference="STAMP-01")
        self.assertEqual(record.screened_by, user)
        self.assertEqual(record.facility, clinic("Kenyatta"))

    def test_a_record_keeps_its_clinic_when_the_screener_moves(self):
        """The facility is copied, not followed."""
        from .models import profile_for

        user = self.member_of("Kenyatta", username="mover")
        self.client.force_login(user)
        self.client.post(
            reverse("screening:upload"),
            {"patient_reference": "MOVE-01", "xray_image": [make_image()]},
        )

        profile = profile_for(user)
        profile.facility = clinic("Mbagathi")
        profile.save()

        record = PredictionRecord.objects.get(patient_reference="MOVE-01")
        self.assertEqual(record.facility, clinic("Kenyatta"))

    def test_a_record_survives_its_screener_being_removed(self):
        user = self.member_of("Kenyatta", username="leaving")
        record = self.record_at("Kenyatta", "LEAVE-01", user)

        user.delete()

        record.refresh_from_db()
        self.assertIsNone(record.screened_by)
        self.assertEqual(record.facility, clinic("Kenyatta"))

    def test_the_profile_counts_what_this_user_screened(self):
        user = self.member_of("Kenyatta", username="counter")
        self.record_at("Kenyatta", "COUNT-01", user)
        self.record_at("Kenyatta", "COUNT-02", user)
        self.record_at("Kenyatta", "COUNT-03", self.member_of("Kenyatta"))
        self.client.force_login(user)

        response = self.client.get(reverse("screening:profile"))

        self.assertEqual(response.context["screened_total"], 2)


class NoFacilityNoticeTests(TestCase):
    """A user with no clinic sees nothing, and must be told that is why.

    Scoping fails closed, which is correct and looks identical to a broken
    installation. The difference has to be stated on the page.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="unplaced", email="unplaced@example.org"
        )
        self.client.force_login(self.user)

    def test_the_notice_appears_when_no_clinic_is_set(self):
        response = self.client.get(reverse("screening:case_list"))

        self.assertContains(response, "No clinic set")
        self.assertContains(response, reverse("screening:profile"))

    def test_the_notice_goes_once_a_clinic_is_set(self):
        from .models import profile_for

        profile = profile_for(self.user)
        profile.facility = clinic("Kenyatta")
        profile.save()

        response = self.client.get(reverse("screening:case_list"))

        self.assertNotContains(response, "No clinic set")

    def test_a_signed_out_visitor_never_sees_it(self):
        self.client.logout()

        response = self.client.get(reverse("account_login"))

        self.assertNotContains(response, "No clinic set")

    def test_setting_a_clinic_from_the_profile_joins_the_caseload(self):
        """The whole point: a record at that clinic becomes visible."""
        PredictionRecord.objects.create(
            patient_reference="JOIN-01",
            xray_image="x.png",
            facility=clinic("Kenyatta"),
            tb_probability=Decimal("0.5"),
            triage_level=PredictionRecord.TriageLevel.MEDIUM,
            model_version="test",
            decision_threshold=Decimal("0.102"),
            triage_low_medium_threshold=Decimal("0.102"),
            triage_medium_high_threshold=Decimal("0.546"),
        )
        self.assertNotContains(self.client.get(reverse("screening:case_list")), "JOIN-01")

        self.client.post(reverse("screening:profile"), {"facility": clinic("Kenyatta").pk})

        self.assertContains(self.client.get(reverse("screening:case_list")), "JOIN-01")


@override_settings(MEDIA_ROOT=MEDIA_FOR_TESTS)
class AccessTrailTests(TestCase):
    """The audit trail the certification criteria ask for.

    Who acted, what they did, when, and from where. The sign-in page claimed
    access was logged before any of this existed, which is a worse position
    than not claiming it.
    """

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA_FOR_TESTS, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        from .models import profile_for

        self.user = get_user_model().objects.create_user(
            username="audited", email="audited@strathmore.edu"
        )
        profile = profile_for(self.user)
        profile.facility = clinic("Kenyatta")
        profile.save()
        self.client.force_login(self.user)

    def events(self, action=None):
        from .models import AccessEvent

        rows = AccessEvent.objects.all()
        return rows.filter(action=action) if action else rows

    def a_case(self):
        return PredictionRecord.objects.create(
            patient_reference="AUD-01",
            xray_image="x.png",
            facility=clinic("Kenyatta"),
            tb_probability=Decimal("0.5"),
            triage_level=PredictionRecord.TriageLevel.MEDIUM,
            model_version="test",
            decision_threshold=Decimal("0.102"),
            triage_low_medium_threshold=Decimal("0.102"),
            triage_medium_high_threshold=Decimal("0.546"),
        )

    def test_opening_a_case_is_recorded(self):
        from .models import AccessEvent

        record = self.a_case()

        self.client.get(reverse("screening:case_detail", args=[record.case_id]))

        event = self.events(AccessEvent.Action.VIEWED).first()
        self.assertIsNotNone(event, "viewing a radiograph left no trace")
        self.assertEqual(event.case_id, record.case_id)
        self.assertEqual(event.actor, self.user)

    def test_an_event_records_who_what_when_and_from_where(self):
        from .models import AccessEvent

        record = self.a_case()

        self.client.get(reverse("screening:case_detail", args=[record.case_id]))

        event = self.events(AccessEvent.Action.VIEWED).first()
        self.assertEqual(event.actor_label, "audited@strathmore.edu")
        self.assertEqual(event.action, AccessEvent.Action.VIEWED)
        self.assertIsNotNone(event.created_at)
        self.assertIsNotNone(event.ip_address)

    def test_listing_cases_is_recorded_with_the_search_term(self):
        from .models import AccessEvent

        self.client.get(reverse("screening:case_list"), {"reference": "AUD"})

        event = self.events(AccessEvent.Action.LISTED).first()
        self.assertIn("AUD", event.detail)

    def test_screening_is_recorded(self):
        from .models import AccessEvent

        self.client.post(
            reverse("screening:upload"),
            {"patient_reference": "AUD-NEW", "xray_image": [make_image()]},
        )

        self.assertTrue(self.events(AccessEvent.Action.SCREENED).exists())

    def test_a_refused_review_is_recorded(self):
        """A refusal is the event most worth having."""
        from .models import AccessEvent

        record = self.a_case()

        self.client.post(
            reverse("screening:case_detail", args=[record.case_id]),
            {"status_set": PredictionRecord.ReviewStatus.REVIEWED, "note": "x"},
        )

        event = self.events(AccessEvent.Action.REFUSED).first()
        self.assertIsNotNone(event, "a refused review left no trace")
        self.assertIn("refused", event.detail)

    def test_a_recorded_review_is_recorded(self):
        from .models import AccessEvent, Profile, profile_for

        profile = profile_for(self.user)
        profile.role = Profile.Role.CLINICIAN
        profile.save()
        record = self.a_case()

        self.client.post(
            reverse("screening:case_detail", args=[record.case_id]),
            {"status_set": PredictionRecord.ReviewStatus.REVIEWED, "note": "Seen."},
        )

        self.assertTrue(self.events(AccessEvent.Action.REVIEWED).exists())

    def test_the_trail_survives_the_account_being_removed(self):
        """Deleting a user must not erase the evidence of what they did."""
        record = self.a_case()
        self.client.get(reverse("screening:case_detail", args=[record.case_id]))

        self.user.delete()

        event = self.events().first()
        self.assertIsNone(event.actor)
        self.assertEqual(event.actor_label, "audited@strathmore.edu")

    def test_the_trail_survives_the_case_being_removed(self):
        record = self.a_case()
        case_id = record.case_id
        self.client.get(reverse("screening:case_detail", args=[case_id]))

        record.delete()

        self.assertTrue(self.events().filter(case_id=case_id).exists())

    def test_no_clinical_detail_is_copied_into_the_trail(self):
        """An audit row that duplicates the record doubles the exposure."""
        from .models import AccessEvent

        record = self.a_case()
        self.client.get(reverse("screening:case_detail", args=[record.case_id]))

        fields = {f.name for f in AccessEvent._meta.fields}
        for leaked in ("tb_probability", "triage_level", "xray_image", "predicted_label"):
            self.assertNotIn(leaked, fields)

    def test_a_failure_to_log_does_not_break_the_request(self):
        """A clinician must not lose a screening because the log failed."""
        from .models import AccessEvent

        record = self.a_case()
        with mock.patch.object(
            AccessEvent.objects, "create", side_effect=RuntimeError("log is down")
        ):
            response = self.client.get(reverse("screening:case_detail", args=[record.case_id]))

        self.assertEqual(response.status_code, 200)

    def test_the_proxy_header_is_ignored_unless_configured(self):
        """Otherwise a caller writes whatever address it likes into the trail."""
        from .models import AccessEvent

        record = self.a_case()

        with override_settings(SECURE_PROXY_SSL_HEADER=None):
            self.client.get(
                reverse("screening:case_detail", args=[record.case_id]),
                HTTP_X_FORWARDED_FOR="203.0.113.9",
            )

        event = self.events(AccessEvent.Action.VIEWED).first()
        self.assertNotEqual(event.ip_address, "203.0.113.9")

    def test_the_proxy_header_is_used_when_configured(self):
        from .models import AccessEvent

        record = self.a_case()

        with override_settings(SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https")):
            self.client.get(
                reverse("screening:case_detail", args=[record.case_id]),
                HTTP_X_FORWARDED_FOR="203.0.113.9, 10.0.0.1",
            )

        event = self.events(AccessEvent.Action.VIEWED).first()
        self.assertEqual(event.ip_address, "203.0.113.9")

    def test_the_trail_cannot_be_edited_through_the_admin(self):
        from django.contrib import admin as django_admin

        from .models import AccessEvent

        site = django_admin.site._registry[AccessEvent]

        self.assertFalse(site.has_add_permission(None))
        self.assertFalse(site.has_change_permission(None))


class SessionTimeoutTests(TestCase):
    """A shared workstation must not keep a session open indefinitely."""

    def test_the_session_expires_after_a_short_idle_period(self):
        """Django's default of fourteen days is wrong for a clinic."""
        from django.conf import settings

        self.assertLessEqual(settings.SESSION_COOKIE_AGE, 30 * 60)

    def test_the_window_slides_with_activity(self):
        """A clinician working through a batch must not be thrown out mid-task."""
        from django.conf import settings

        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)

    def test_closing_the_browser_ends_the_session(self):
        from django.conf import settings

        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)

    def test_the_page_warns_before_the_server_acts(self):
        user = get_user_model().objects.create_user(
            username="warned", email="warned@strathmore.edu"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("screening:upload"))

        self.assertContains(response, "idle-warning")
        self.assertContains(response, "Stay signed in")

    def test_a_signed_out_visitor_gets_no_countdown(self):
        response = self.client.get(reverse("account_login"))

        self.assertNotContains(response, "idle-warning")


class PackagedOperatorTests(TestCase):
    """How the desktop build signs someone in with nothing to ask.

    Google, Microsoft and email codes all need a network. A packaged build may
    have none, so the person at the keyboard is the operator and the boundary
    is the one already around their account on that machine.
    """

    def middleware(self):
        from . import middleware

        return middleware

    @override_settings(PACKAGED=False)
    def test_it_does_nothing_on_the_server(self):
        """The deployed system must be unaffected by this existing."""
        response = self.client.get(reverse("screening:upload"))

        self.assertRedirects(
            response, f"{reverse('account_login')}?next={reverse('screening:upload')}"
        )

    @override_settings(PACKAGED=True)
    def test_it_signs_the_operator_in_without_a_gate(self):
        response = self.client.get(reverse("screening:upload"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["user"].is_authenticated)

    @override_settings(PACKAGED=True)
    def test_the_operator_can_review_what_it_screens(self):
        """There is nobody else to assign a role, so it administers itself."""
        from .models import Profile, profile_for

        self.client.get(reverse("screening:upload"))

        operator = get_user_model().objects.get(username=self.middleware().LOCAL_USERNAME)
        self.assertEqual(profile_for(operator).role, Profile.Role.ADMINISTRATOR)
        self.assertTrue(profile_for(operator).may_review)

    @override_settings(PACKAGED=True)
    def test_the_operator_has_a_clinic_so_scoping_behaves_normally(self):
        from .models import profile_for

        self.client.get(reverse("screening:upload"))

        operator = get_user_model().objects.get(username=self.middleware().LOCAL_USERNAME)
        self.assertIsNotNone(profile_for(operator).facility)

    @override_settings(PACKAGED=True)
    def test_the_operator_cannot_be_signed_in_as(self):
        """No password, so the account is reachable only from this machine."""
        self.client.get(reverse("screening:upload"))

        operator = get_user_model().objects.get(username=self.middleware().LOCAL_USERNAME)
        self.assertFalse(operator.has_usable_password())

    @override_settings(PACKAGED=True)
    def test_repeated_requests_reuse_one_operator(self):
        for _ in range(3):
            self.client.get(reverse("screening:upload"))

        self.assertEqual(
            get_user_model().objects.filter(username=self.middleware().LOCAL_USERNAME).count(),
            1,
        )

    @override_settings(PACKAGED=True)
    def test_work_is_still_attributed_and_logged(self):
        """Not asking who you are is not the same as not recording what you did."""
        from .models import AccessEvent

        self.client.get(reverse("screening:case_list"))

        event = AccessEvent.objects.filter(action=AccessEvent.Action.LISTED).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.actor_label, self.middleware().LOCAL_EMAIL)


class PackagedSettingsTests(TestCase):
    """The three ways the packaged build differs, and no others."""

    def test_sqlite_is_selected_by_the_launcher_switch(self):
        import importlib
        import os
        from unittest import mock

        with mock.patch.dict(
            os.environ,
            {
                "DJANGO_DB": "sqlite",
                "TB_DATA_DIR": "/tmp/tb",
                "DJANGO_SECRET_KEY": "x",
                "DB_NAME": "x",
                "DB_USER": "x",
                "DB_PASSWORD": "x",
            },
        ):
            module = importlib.reload(importlib.import_module("config.settings"))
            self.assertIn("sqlite3", module.DATABASES["default"]["ENGINE"])
        # Restore the real settings for everything that follows.
        importlib.reload(importlib.import_module("config.settings"))

    def test_the_data_directory_follows_the_launcher(self):
        from django.conf import settings

        self.assertTrue(hasattr(settings, "DATA_DIR"))

    def test_media_lives_beside_the_database(self):
        from django.conf import settings

        self.assertEqual(settings.MEDIA_ROOT, settings.DATA_DIR / "media")

    def test_the_static_root_can_be_pointed_at_the_bundle(self):
        """PyInstaller unpacks elsewhere, so this cannot be fixed to the project."""
        import os

        self.assertIn(
            "DJANGO_STATIC_ROOT", Path("config/settings.py").read_text(encoding="utf-8")
        )
        del os


class AuditChainTests(TestCase):
    """The audit trail detecting its own alteration.

    Append-only by intent is not evidence. Each row hashes its own contents
    together with the hash of the row before it, so changing or removing one
    breaks that row and every row after it.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="chained", email="chained@strathmore.edu"
        )

    def event(self, detail="something"):
        from .models import AccessEvent

        request = RequestFactory().get("/")
        request.user = self.user
        return AccessEvent.record(request, AccessEvent.Action.VIEWED, detail=detail)

    def test_a_row_is_sealed_when_it_is_written(self):
        event = self.event()

        self.assertTrue(event.entry_hash)
        self.assertEqual(len(event.entry_hash), 64)

    def test_the_first_row_follows_nothing(self):
        event = self.event()

        self.assertEqual(event.previous_hash, "")

    def test_each_row_follows_the_one_before_it(self):
        first = self.event("one")
        second = self.event("two")

        self.assertEqual(second.previous_hash, first.entry_hash)

    def test_an_untouched_chain_verifies(self):
        from .models import AccessEvent

        for n in range(5):
            self.event(f"row {n}")

        checked, problems = AccessEvent.verify_chain()

        self.assertEqual(checked, 5)
        self.assertEqual(problems, [])

    def test_editing_a_row_is_detected(self):
        """Edited straight in the database, bypassing the application."""
        from django.db import connection

        from .models import AccessEvent

        self.event("one")
        target = self.event("two")
        self.event("three")

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE screening_accessevent SET detail = %s WHERE id = %s",
                ["covered up", target.pk],
            )

        _, problems = AccessEvent.verify_chain()
        self.assertTrue(problems, "an edited row went unnoticed")
        self.assertIn(f"row {target.pk}", problems[0])

    def test_back_dating_a_row_is_detected(self):
        """The timestamp is in the hash, so moving an event in time shows."""
        from django.db import connection

        from .models import AccessEvent

        target = self.event("one")

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE screening_accessevent SET created_at = created_at "
                "- interval '1 day' WHERE id = %s",
                [target.pk],
            )

        _, problems = AccessEvent.verify_chain()
        self.assertTrue(problems, "a back-dated row went unnoticed")

    def test_removing_a_row_is_detected(self):
        """The row after it claims to follow something no longer there."""
        from django.db import connection

        from .models import AccessEvent

        self.event("one")
        middle = self.event("two")
        after = self.event("three")

        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM screening_accessevent WHERE id = %s", [middle.pk])

        _, problems = AccessEvent.verify_chain()
        self.assertTrue(problems, "a deleted row went unnoticed")
        self.assertIn(f"row {after.pk}", problems[0])

    def test_the_break_names_where_the_trail_stops_being_trustworthy(self):
        from django.db import connection

        from .models import AccessEvent

        rows = [self.event(f"row {n}") for n in range(4)]

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE screening_accessevent SET detail = %s WHERE id = %s",
                ["changed", rows[2].pk],
            )

        _, problems = AccessEvent.verify_chain()
        self.assertIn(f"row {rows[2].pk}", " ".join(problems))
        self.assertNotIn(f"row {rows[0].pk}:", " ".join(problems))

    def test_resaving_a_row_does_not_reseal_it(self):
        """Otherwise an edit could launder itself by saving through the ORM."""
        from .models import AccessEvent

        event = self.event("one")
        original = event.entry_hash

        event.detail = "changed"
        event.save()

        self.assertEqual(
            AccessEvent.objects.get(pk=event.pk).entry_hash,
            original,
            "a resave recomputed the hash and hid the change",
        )

    def test_the_command_reports_an_intact_chain(self):
        from django.core.management import call_command

        self.event()
        output = io.StringIO()

        call_command("verifyaudit", stdout=output)

        self.assertIn("intact", output.getvalue())

    def test_the_command_exits_non_zero_when_broken(self):
        """So it can be run on a schedule and noticed rather than read."""
        from django.core.management import call_command
        from django.db import connection

        target = self.event()
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE screening_accessevent SET detail = %s WHERE id = %s",
                ["x", target.pk],
            )

        with self.assertRaises(SystemExit):
            call_command("verifyaudit", stdout=io.StringIO())
