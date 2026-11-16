"""Synthetic case-owned LAF deletion through the existing reviewed boundary."""

from unittest.mock import patch
from unittest import skipUnless
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event

from django.core.exceptions import PermissionDenied
from django.db import connection, connections
from django.test import TestCase, TransactionTestCase, override_settings

from core.models import (
    ComplianceAuditEvent,
    GroupSheetConfiguration,
    IntegrationOperation,
    JawabuFarmerMaster,
    RequisitionBatch,
)
from core.services.miniapp_deletion import CASCADE, SelectionChanged, delete_selection, preview_selection
from origination.models import OriginationDocumentTemplate
from payments.models import PaymentBatch, PaymentBatchCase

from .models import PortalLaf, PortalLafVersion, PortalLafSignature, PortalLafRequest
from .services import archive
from . import tests as laf_fixtures


@override_settings(PORTAL_LAF_FORM_ENABLED=True, MINIAPP_TEST_DELETION_ENABLED=True)
class LafDeletionTests(TestCase):
    setUp = laf_fixtures.LafTests.setUp
    act = laf_fixtures.LafTests.act
    sign = laf_fixtures.LafTests.sign

    def plan(self, record=None):
        record = record or self.case
        return preview_selection(model_label=record._meta.label, ids=[record.pk], actor=self.bro, mode=CASCADE)

    def delete(self, plan):
        return delete_selection(
            model_label=self.case._meta.label,
            ids=[self.case.pk],
            actor=self.bro,
            mode=CASCADE,
            fingerprint=plan["fingerprint"],
            request_id="delete-portal-laf",
        )

    def test_draft_case_deletion_includes_laf_and_rejects_unauthorized_requests(self):
        self.act("start")
        plan = self.plan()
        self.assertEqual(plan["blockers"], [])
        self.assertTrue(any(label == "portal_lafs.PortalLafVersion" for label, _ in plan["deleted"]))
        with override_settings(MINIAPP_TEST_DELETION_ENABLED=False), self.assertRaises(PermissionDenied):
            self.delete(plan)
        with self.assertRaises(PermissionDenied):
            preview_selection(model_label=self.case._meta.label, ids=[self.case.pk], actor=self.outsider)
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=self.case.pk).exists())
        self.delete(plan)
        self.assertFalse(JawabuFarmerMaster.objects.filter(pk=self.case.pk).exists())
        self.assertFalse(PortalLaf.objects.exists())
        self.assertTrue(OriginationDocumentTemplate.objects.filter(pk=self.template.pk).exists())

    def test_signed_case_deletion_removes_all_versions_and_cancels_only_its_archive_work(self):
        self.act("start")
        self.sign("bro_1")
        old = PortalLaf.objects.get(case=self.case).current
        self.act("replace", confirm=True)
        self.sign("bro_1")
        self.case.workflow_state = "credit"
        self.case.save(update_fields=["workflow_state"])
        self.sign("credit_analyst", self.ca)
        self.case.workflow_state = "final_review"
        self.case.save(update_fields=["workflow_state"])
        self.sign("branch_manager", self.head)
        laf = PortalLaf.objects.get(case=self.case)
        version = laf.current
        group = GroupSheetConfiguration.objects.create(
            group_id="synthetic-laf-delete", sheet_id="synthetic-laf-sheet", workflow={"type": "jawabu_homebiogas"}
        )
        self.case.group_configuration = group
        order = RequisitionBatch.objects.create(
            group_configuration=group, order_number="HB-TEST", farmer_ids=[str(self.case.pk)]
        )
        self.case.requisition_batch = order
        self.case.save(update_fields=["group_configuration", "requisition_batch"])
        payment = PaymentBatch.objects.create(group_configuration=group, payment_number=1)
        PaymentBatchCase.objects.create(batch=payment, farmer=self.case, payment_mode="CASH")
        outside_case = JawabuFarmerMaster.objects.create(
            customer_name="Other synthetic case", group_configuration=group
        )
        outside_laf = PortalLaf.objects.create(case=outside_case)
        outside_version = PortalLafVersion.objects.create(laf=outside_laf, template=self.template, officer=self.bro)
        outside_laf.current = outside_version
        outside_laf.save()
        pending = IntegrationOperation.objects.create(
            integration="google_drive",
            operation_type="portal_laf_archive",
            source_model="portal_lafs.PortalLafVersion",
            source_id=str(version.pk),
            deduplication_key="laf-delete-own",
        )
        other = IntegrationOperation.objects.create(
            integration="google_drive",
            operation_type="portal_laf_archive",
            source_model="portal_lafs.PortalLafVersion",
            source_id=str(outside_version.pk),
            deduplication_key="laf-delete-other",
        )
        signature = version.signatures.first()
        plan = self.plan()
        self.assertEqual(plan["blockers"], [])
        self.assertIn(("portal_lafs.PortalLafVersion", str(old.pk)), plan["deleted"])
        self.assertEqual(self.plan(signature)["deleted"], plan["deleted"])
        self.assertNotIn((outside_case._meta.label, str(outside_case.pk)), plan["deleted"])
        self.assertIn((order._meta.label, str(order.pk)), plan["deleted"])
        self.assertIn((payment._meta.label, str(payment.pk)), plan["deleted"])
        with patch("core.services.order_approval.GoogleDriveMediaStorage.upload") as drive:
            result = self.delete(plan)
            self.assertTrue(result["drive_files_untouched"])
            self.assertEqual(len(result["sheet_operations"]), 2)
            self.assertTrue(self.delete(plan)["replayed"])
            archive(version.pk)
            drive.assert_not_called()
        for model in (PortalLafVersion, PortalLafSignature, PortalLafRequest):
            query = {"laf_id": laf.pk} if model != PortalLafSignature else {"version__laf_id": laf.pk}
            self.assertFalse(model.objects.filter(**query).exists())
        self.assertFalse(JawabuFarmerMaster.objects.filter(pk=self.case.pk).exists())
        self.assertFalse(RequisitionBatch.objects.filter(pk=order.pk).exists())
        self.assertFalse(PaymentBatch.objects.filter(pk=payment.pk).exists())
        self.assertTrue(PortalLafVersion.objects.filter(pk=outside_version.pk).exists())
        self.assertTrue(OriginationDocumentTemplate.objects.filter(pk=self.template.pk).exists())
        pending.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(pending.status, "dead_letter")
        self.assertEqual(pending.last_error_code, "source_deleted")
        self.assertEqual(other.status, "pending")
        self.assertEqual(ComplianceAuditEvent.objects.filter(action="records.deleted").count(), 1)

    def test_new_signature_requires_a_fresh_deletion_confirmation(self):
        self.act("start")
        plan = self.plan()
        self.sign("bro_1")
        with self.assertRaises(SelectionChanged):
            self.delete(plan)
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=self.case.pk).exists())
        self.assertTrue(PortalLafSignature.objects.exists())


@skipUnless(connection.vendor == "postgresql", "Archive/deletion locking requires PostgreSQL.")
@override_settings(
    PORTAL_LAF_FORM_ENABLED=True,
    MINIAPP_TEST_DELETION_ENABLED=True,
    GOOGLE_DRIVE_MEDIA_FOLDER_ID="synthetic-laf-test-folder",
)
class LafArchiveDeletionConcurrencyTests(TransactionTestCase):
    setUp = laf_fixtures.LafTests.setUp
    act = laf_fixtures.LafTests.act
    sign = laf_fixtures.LafTests.sign
    plan = LafDeletionTests.plan
    delete = LafDeletionTests.delete

    def test_archive_finishes_before_deletion_and_changed_receipt_requires_review(self):
        from core.models import ComplianceAuditChainState

        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.act("start")
        for role, actor, stage in (
            ("bro_1", self.bro, "jbl_visit"),
            ("credit_analyst", self.ca, "credit"),
            ("branch_manager", self.head, "final_review"),
        ):
            self.case.workflow_state = stage
            self.case.save(update_fields=["workflow_state"])
            self.sign(role, actor)
        version_id = PortalLaf.objects.get(case=self.case).current_id
        plan = self.plan()
        uploading, finish_upload, deleting = Event(), Event(), Event()

        def upload(*args, **kwargs):
            uploading.set()
            if not finish_upload.wait(10):
                raise AssertionError("Synthetic upload was not released")
            return "synthetic-archived-file", "https://example.test/synthetic"

        def archive_worker():
            try:
                archive(version_id)
            finally:
                connections.close_all()

        def delete_worker():
            try:
                deleting.set()
                self.delete(plan)
            finally:
                connections.close_all()

        with patch("core.services.order_approval.GoogleDriveMediaStorage.upload", side_effect=upload):
            with ThreadPoolExecutor(max_workers=2) as workers:
                publishing = workers.submit(archive_worker)
                try:
                    if not uploading.wait(5):
                        publishing.result(timeout=1)
                        self.fail("The archive returned before entering the synthetic upload")
                    removal = workers.submit(delete_worker)
                    self.assertTrue(deleting.wait(5))
                    with self.assertRaises(TimeoutError):
                        removal.result(timeout=0.3)
                finally:
                    finish_upload.set()
                publishing.result(timeout=10)
                with self.assertRaises(SelectionChanged):
                    removal.result(timeout=10)
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=self.case.pk).exists())
        self.delete(self.plan())
        self.assertFalse(JawabuFarmerMaster.objects.filter(pk=self.case.pk).exists())
