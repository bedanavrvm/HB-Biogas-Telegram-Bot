"""Synthetic Portal lifecycle and shared PDF evidence, without external side effects."""

from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from core.models import JawabuFarmerMaster, AccessGrant
from origination.models import OriginationDocumentTemplate, OriginationTemplateConfigurationRevision
from .models import PortalLaf, PortalLafVersion, PortalLafSignature
from .services import mutate, serialize, LafError, evidence_ready, require_stage


def blank_pdf():
    stream = BytesIO()
    pdf = canvas.Canvas(stream)
    pdf.drawString(20, 750, "SYNTHETIC BIOGAS LAF")
    pdf.showPage()
    pdf.save()
    return stream.getvalue()


@override_settings(PORTAL_LAF_FORM_ENABLED=True)
class LafTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.bro = users.objects.create_user("laf_bro", is_superuser=True)
        self.ca = users.objects.create_user("laf_ca", is_superuser=True)
        self.head = users.objects.create_user("laf_head", is_superuser=True)
        self.outsider = users.objects.create_user("laf_outside")
        self.case = JawabuFarmerMaster.objects.create(
            customer_name="Synthetic Farmer",
            national_id="90000001",
            primary_phone="0712345678",
            branch="Synthetic",
            village="Test village",
            county="Test county",
            workflow_state="jbl_visit",
            deposit_paid_hbg="5000",
        )
        fields = [
            {"key": key, "label": label, "type": typ, "required": required, "section_key": "details"}
            for key, label, typ, required in [
                ("applicant_full_name", "Full Name", "text", True),
                ("applicant_phone", "Phone", "phone", True),
                ("notes", "Notes", "textarea", False),
                ("visit_date", "Visit Date", "date", False),
            ]
        ]
        self.schema = {"sections": [{"key": "details", "label": "Applicant Details"}], "fields": fields}
        roles = ["bro_1", "credit_analyst", "branch_manager"]
        self.slots = [
            {
                "role": role,
                "label": role,
                "required": True,
                "stage": stage,
                "external": False,
                "slots": [
                    {
                        "key": role + "_signature",
                        "type": "signature",
                        "required": True,
                        "placement": {
                            "page_number": 1,
                            "box": {"x": 20, "y": 80 + index * 40, "width": 140, "height": 30},
                        },
                    }
                ],
            }
            for index, (role, stage) in enumerate(zip(roles, ["visit", "credit", "final"]))
        ]
        self.template = OriginationDocumentTemplate.objects.create(
            document_type="lipa_mdogo_mdogo_laf",
            name="Synthetic Biogas LAF",
            version=1,
            status="active",
            source_sha256="a" * 64,
            page_count=1,
            source_byte_size=len(blank_pdf()),
            created_by=self.bro,
        )
        self.config = {
            "field_overlay_manifest": {
                "fields": {
                    str(i): {
                        "context_key": f["key"],
                        "page_number": 1,
                        "box": {"x": 20, "y": 700 - i * 30, "width": 200, "height": 20},
                    }
                    for i, f in enumerate(fields)
                }
            },
            "signature_overlay_manifest": {
                "slots": {s["role"] + "." + s["slots"][0]["key"]: s["slots"][0]["placement"] for s in self.slots}
            },
        }
        rev = OriginationTemplateConfigurationRevision.objects.create(
            template=self.template, revision=1, configuration=self.config, is_published=True, created_by=self.bro
        )
        self.template.published_configuration_revision = rev
        self.template.save()
        self.contract = patch(
            "portal_lafs.services.template_contract", return_value=(self.template, self.schema, self.config, self.slots)
        )
        self.contract.start()
        self.addCleanup(self.contract.stop)
        self.source = patch("origination.services.origination_templates.load_template_source", return_value=blank_pdf())
        self.source.start()
        self.addCleanup(self.source.stop)
        self.archive = patch("portal_lafs.publication.queue_archive")
        self.archive.start()
        self.addCleanup(self.archive.stop)
        self.counter = 0

    def act(self, action, actor=None, **extra):
        self.counter += 1
        laf = PortalLaf.objects.filter(case=self.case).select_related("current").first()
        payload = {
            "action": action,
            **({"version_id": str(laf.current_id), "revision": laf.current.revision} if laf and laf.current else {}),
            **extra,
        }
        return mutate(self.case.pk, actor or self.bro, None, payload, f"test:{self.counter}")

    def sign(self, role, actor=None):
        result = self.act("preview", actor)
        from .models import PortalLafRequest

        PortalLafRequest.objects.create(
            laf=PortalLaf.objects.get(case=self.case),
            key=f"page:{self.counter}",
            digest="0" * 64,
            result={"actor_id": str((actor or self.bro).pk), "page": 1, "page_digest": result["version"]["digest"]},
        )
        return self.act(
            "sign",
            actor,
            role=role,
            digest=result["version"]["digest"],
            consent=True,
            capture={"method": "typed", "name": (actor or self.bro).username},
        )

    def test_draft_upload_default_and_resume_without_new_application(self):
        result = self.act("start")
        self.assertEqual(result["active_source"], "upload")
        self.act("save", values={"notes": "Saved on device one", "visit_date": "2026-11-23"})
        restored = serialize(self.case, self.bro, None)
        self.assertEqual(restored["version"]["values"]["notes"], "Saved on device one")
        from origination.models import LoanOriginationApplication

        self.assertFalse(LoanOriginationApplication.objects.exists())
        self.assertEqual(PortalLafVersion.objects.count(), 1)
        self.assertEqual(self.act("start")["version"]["id"], result["version"]["id"])

    def test_staff_sign_at_existing_stages_and_exact_signed_pdf_retained(self):
        self.act("start")
        self.sign("bro_1")
        self.act("source", source="form", confirm=True)
        self.assertTrue(evidence_ready(self.case))
        with self.assertRaises(LafError):
            require_stage(self.case, "credit")
        version = PortalLaf.objects.get(case=self.case).current
        base = bytes(version.base_pdf)
        with self.assertRaises(LafError):
            self.sign("credit_analyst", self.ca)
        self.case.workflow_state = "credit"
        self.case.save(update_fields=["workflow_state"])
        self.sign("credit_analyst", self.ca)
        require_stage(self.case, "credit")
        self.case.workflow_state = "final_review"
        self.case.save(update_fields=["workflow_state"])
        self.sign("branch_manager", self.head)
        require_stage(self.case, "final")
        version.refresh_from_db()
        self.assertEqual(bytes(version.base_pdf), base)
        self.assertEqual(len(PdfReader(BytesIO(bytes(version.pdf))).pages), 1)
        self.assertEqual(version.signatures.count(), 3)

    def test_scoped_portal_authority_is_not_origination_authority(self):
        AccessGrant.objects.create(user=self.outsider, workflow="loan_origination", role="JBL_OFFICER")
        with self.assertRaises(PermissionDenied):
            self.act("start", self.outsider)

    def test_existing_portal_media_grants_control_form_and_document_reads(self):
        from .services import authorize

        AccessGrant.objects.create(user=self.outsider, workflow="jawabu_portal", role="HB_STAFF")
        with self.assertRaises(PermissionDenied):
            authorize(self.case, self.outsider, None)
        bro = get_user_model().objects.create_user("scoped_laf_bro")
        self.case.branch = "Ruiru"
        self.case.save(update_fields=["branch"])
        AccessGrant.objects.create(user=bro, workflow="jawabu_portal", role="JBL_OFFICER", branch="Ruiru")
        result = self.act("start", bro)
        self.assertEqual(result["active_source"], "upload")
        AccessGrant.objects.create(user=self.outsider, workflow="jawabu_portal", role="JBL_OFFICER", branch="Elsewhere")
        with self.assertRaises(PermissionDenied):
            self.act("start", self.outsider)

    def test_retry_conflict_and_signed_answers_cannot_change(self):
        first = mutate(self.case.pk, self.bro, None, {"action": "start"}, "same")
        self.assertEqual(
            mutate(self.case.pk, self.bro, None, {"action": "start"}, "same")["version"]["id"], first["version"]["id"]
        )
        with self.assertRaises(LafError):
            mutate(self.case.pk, self.bro, None, {"action": "start", "other": 1}, "same")
        with self.assertRaises(LafError):
            self.act("save", revision=0, values={"notes": "stale"})
        self.sign("bro_1")
        with self.assertRaises(LafError):
            self.act("save", values={"notes": "rewrite"})

    def test_replacement_preserves_history_and_does_not_select_unfinished_form(self):
        self.act("start")
        self.sign("bro_1")
        self.act("source", source="form", confirm=True)
        old = PortalLaf.objects.get(case=self.case).current
        self.act("replace", confirm=True)
        self.assertEqual(PortalLafVersion.objects.count(), 2)
        self.assertTrue(PortalLafSignature.objects.filter(version=old).exists())
        self.assertEqual(PortalLaf.objects.get(case=self.case).active_source, "upload")

    def test_required_fields_dates_and_material_changes_are_checked(self):
        self.act("start")
        with self.assertRaises(LafError):
            self.act("save", values={"visit_date": "23/11/2026"})
        self.act("save", values={"applicant_full_name": ""})
        with self.assertRaises(LafError):
            self.sign("bro_1")
        self.act("save", values={"applicant_full_name": "Synthetic Farmer"})
        self.sign("bro_1")
        self.act("source", source="form", confirm=True)
        self.case.primary_phone = "0712345679"
        self.case.save(update_fields=["primary_phone"])
        self.assertFalse(evidence_ready(self.case))

    def test_missing_template_and_feature_off_leave_upload_available(self):
        with override_settings(PORTAL_LAF_FORM_ENABLED=False):
            self.assertFalse(serialize(self.case, self.bro, None)["enabled"])
            with self.assertRaises(LafError):
                self.act("start")
        with patch("portal_lafs.services.template_contract", side_effect=LafError("Publish template")):
            self.assertEqual(serialize(self.case, self.bro, None)["active_source"], "upload")

    def test_a_different_person_must_preview_before_signing(self):
        self.act("start")
        self.act("preview")
        self.case.workflow_state = "credit"
        self.case.save(update_fields=["workflow_state"])
        with self.assertRaises(LafError):
            self.act(
                "sign",
                self.ca,
                role="credit_analyst",
                digest=PortalLaf.objects.get(case=self.case).current.digest,
                consent=True,
                capture={"method": "typed", "name": "Analyst"},
            )

    def test_in_person_signing_requires_consent_and_officer_witness_without_sms(self):
        self.slots.append(
            {
                "role": "borrower",
                "label": "Client",
                "required": True,
                "stage": "visit",
                "external": True,
                "slots": [
                    {
                        "key": "borrower_signature",
                        "type": "signature",
                        "placement": {"page_number": 1, "box": {"x": 20, "y": 40, "width": 140, "height": 30}},
                    }
                ],
            }
        )
        self.act("start")
        self.sign("bro_1")
        preview = self.act("preview")
        from .models import PortalLafRequest

        laf = PortalLaf.objects.get(case=self.case)
        PortalLafRequest.objects.create(
            laf=laf,
            key="client-page",
            digest="0" * 64,
            result={"actor_id": str(self.bro.pk), "page": 1, "page_digest": preview["version"]["digest"]},
        )
        signature = {
            "role": "borrower",
            "consent": True,
            "witnessed": True,
            "signing_mode": "in_person",
            "digest": preview["version"]["digest"],
            "capture": {"method": "typed", "name": "Synthetic Client"},
        }
        for invalid in ({"consent": False}, {"witnessed": False}, {"signing_mode": "remote"}):
            with self.subTest(invalid=invalid), self.assertRaises(LafError):
                self.act("sign", **{**signature, **invalid})
        with self.assertRaises(PermissionDenied):
            self.act("sign", self.ca, **signature)
        posted = {"action": "sign", "version_id": str(laf.current_id), "revision": laf.current.revision, **signature}
        with (
            patch(
                "origination.services.origination_esign.esign_enabled",
                side_effect=AssertionError("No SMS prerequisite"),
            ),
            patch("origination.services.origination_sms.submit") as sms,
        ):
            mutate(self.case.pk, self.bro, None, posted, "client-sign")
            mutate(self.case.pk, self.bro, None, posted, "client-sign")
            sms.assert_not_called()
        saved = PortalLafSignature.objects.get(role="borrower")
        self.assertIsNone(saved.actor)
        self.assertTrue(saved.evidence["consent"])
        self.assertEqual(saved.evidence["signing_mode"], "in_person")
        self.assertEqual(saved.evidence["witnessed_by"], str(self.bro.pk))
        self.assertNotIn("otp_verified", saved.evidence)
        self.assertEqual(PortalLafSignature.objects.filter(role="borrower").count(), 1)
        self.assertFalse(evidence_ready(self.case))
        self.act("source", source="form", confirm=True)
        self.assertTrue(evidence_ready(self.case))

    def test_preview_without_signature_does_not_lock_draft_answers(self):
        self.act("start")
        self.act("preview")
        self.assertTrue(serialize(self.case, self.bro, None)["version"]["can_edit"])
        self.act("save", values={"notes": "Corrected before any confirmed signature"})
        version = PortalLaf.objects.get(case=self.case).current
        self.assertFalse(version.base_pdf)
        self.assertEqual(version.values["notes"], "Corrected before any confirmed signature")

    def test_archive_failure_keeps_bytes_and_reports_failure_to_runner(self):
        self.act("start")
        self.sign("bro_1")
        self.case.workflow_state = "credit"
        self.case.save(update_fields=["workflow_state"])
        self.sign("credit_analyst", self.ca)
        self.case.workflow_state = "final_review"
        self.case.save(update_fields=["workflow_state"])
        self.sign("branch_manager", self.head)
        version = PortalLaf.objects.get(case=self.case).current
        from .services import archive

        with patch("core.services.order_approval.GoogleDriveMediaStorage.upload", side_effect=OSError("offline")):
            with self.assertRaises(RuntimeError):
                archive(version.pk)
        version.refresh_from_db()
        self.assertTrue(version.pdf)
        self.assertTrue(version.archive_error)

    def test_real_http_authentication_and_retry_key_reach_the_laf_service(self):
        from core.models import UserProfile
        from core.tests_telegram_authentication import signed_init_data, BOT_TOKEN

        UserProfile.objects.create(user=self.bro, telegram_id="9988001")
        proof = signed_init_data(user={"id": 9988001})
        url = f"/api/portal/cases/{self.case.pk}/laf/"
        with override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN, PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True):
            response = self.client.post(
                url,
                {"action": "start"},
                content_type="application/json",
                HTTP_X_TELEGRAM_INIT_DATA=proof,
                HTTP_IDEMPOTENCY_KEY="http:test:1",
            )
            self.assertEqual(response.status_code, 200, response.content)
            again = self.client.post(
                url,
                {"action": "start"},
                content_type="application/json",
                HTTP_X_TELEGRAM_INIT_DATA=proof,
                HTTP_IDEMPOTENCY_KEY="http:test:1",
            )
            self.assertEqual(again.status_code, 200, again.content)
            self.assertEqual(PortalLafVersion.objects.count(), 1)
            self.assertEqual(self.client.get(url).status_code, 403)
            from core.models import PortalMaintenanceState

            PortalMaintenanceState.objects.update_or_create(singleton=1, defaults={"mode": "maintenance"})
            held = self.client.post(
                url,
                {"action": "sign", "role": "borrower", "witnessed": True},
                content_type="application/json",
                HTTP_X_TELEGRAM_INIT_DATA=proof,
                HTTP_IDEMPOTENCY_KEY="http:paused",
            )
            self.assertEqual(held.status_code, 503, held.content)
            self.assertFalse(PortalLafSignature.objects.exists())

    def test_unsigned_template_adoption_retains_superseded_answers(self):
        self.act("start")
        self.act("save", values={"notes": "Retain this source answer"})
        old = PortalLaf.objects.get(case=self.case).current
        changed = {**self.config, "new_layout_revision": 2}
        with patch(
            "portal_lafs.services.template_contract", return_value=(self.template, self.schema, changed, self.slots)
        ):
            with self.assertRaises(LafError):
                self.act("preview")
            result = self.act("save", values={"notes": "Retain this source answer"})
            self.assertTrue(result["form_updated"])
            self.assertNotEqual(result["version"]["id"], str(old.pk))
        old.refresh_from_db()
        self.assertEqual(old.values["notes"], "Retain this source answer")

    def test_form_cannot_mix_a_different_amount_with_the_canonical_quote(self):
        self.case.product_quote_snapshot = {"inputs": {"amount": "1000.00"}}
        self.case.save(update_fields=["product_quote_snapshot"])
        self.schema["fields"].append(
            {"key": "loan_amount", "label": "Loan Amount", "type": "money", "section_key": "details"}
        )
        result = self.act("start")
        self.assertEqual(result["version"]["values"]["loan_amount"], "1000.00")
        with self.assertRaises(LafError):
            self.act("save", values={"loan_amount": "2000.00"})

    def test_template_outage_leaves_a_resumable_draft_with_actionable_guidance(self):
        self.act("start")
        from origination.services.origination_templates import OriginationTemplateError

        with patch(
            "origination.services.origination_templates.load_template_source",
            side_effect=OriginationTemplateError("unavailable"),
        ):
            with self.assertRaises(LafError) as result:
                self.act("preview")
        self.assertEqual(result.exception.status, 503)
        self.assertIn("draft is saved", str(result.exception))
        self.assertTrue(PortalLaf.objects.get(case=self.case).current_id)

    def test_negative_credit_outcome_does_not_require_analyst_approval_signature(self):
        self.act("start")
        self.sign("bro_1")
        self.act("source", source="form", confirm=True)
        self.case.workflow_state = "credit"
        self.case.jbl_visit_date = timezone.localdate()
        self.case.save(update_fields=["workflow_state", "jbl_visit_date"])
        from core.services.jawabu_pipeline import set_credit_decision

        ok, error = set_credit_decision(
            self.case, decision="Rejected", reason_code="r01", actor_user=self.ca, request_id="reject:laf"
        )
        self.assertTrue(ok, error)
        self.assertFalse(PortalLafSignature.objects.filter(role="credit_analyst").exists())


@override_settings(PORTAL_LAF_FORM_ENABLED=True)
class LafConcurrencyTests(TransactionTestCase):
    setUp = LafTests.setUp
    act = LafTests.act
    sign = LafTests.sign

    def test_two_workers_replay_one_case_draft_and_one_signature(self):
        from concurrent.futures import ThreadPoolExecutor
        from django.db import connections

        def run(payload, key):
            try:
                actor = get_user_model().objects.get(pk=self.bro.pk)
                return mutate(self.case.pk, actor, None, payload, key)["version"]["id"]
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run({"action": "start"}, "parallel:start"), range(2)))
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(PortalLafVersion.objects.count(), 1)
        preview = self.act("preview")
        from .models import PortalLafRequest

        PortalLafRequest.objects.create(
            laf=PortalLaf.objects.get(case=self.case),
            key="parallel:page",
            digest="0" * 64,
            result={"actor_id": str(self.bro.pk), "page": 1, "page_digest": preview["version"]["digest"]},
        )
        version = preview["version"]
        payload = {
            "action": "sign",
            "version_id": version["id"],
            "revision": version["revision"],
            "role": "bro_1",
            "digest": version["digest"],
            "consent": True,
            "capture": {"method": "typed", "name": "Synthetic BRO"},
        }
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: run(payload, "parallel:sign"), range(2)))
        self.assertEqual(PortalLafSignature.objects.count(), 1)
