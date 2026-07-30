"""Focused regression tests for physically signed/stamped finance documents."""

import json

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase

from core.api.portal_views import portal_document_physical_signoff_upload
from core.models import (
    AccessGrant,
    DocumentPhysicalSignoff,
    DocumentPhysicalSignoffEvent,
    DocumentSignoffPolicy,
    RequisitionBatch,
)
from core.services.document_signoffs import (
    PhysicalSignoffError,
    document_signoff_summary,
    submit_physical_signoff,
)
from core.services.access_control import (
    APPROVER_GROUP_NAME,
    approve_request,
    create_document_signoff_policy_request,
)
from core.services.telegram_identity import user_access


class PhysicalDocumentSignoffTests(TestCase):
    def setUp(self):
        self.admin_user = get_user_model().objects.create_user(
            username='document-admin', is_active=True,
        )
        self.officer = get_user_model().objects.create_user(
            username='document-officer', is_active=True,
        )
        AccessGrant.objects.create(
            user=self.admin_user, workflow='jawabu_portal', role='BUSINESS_ADMIN', branch='EMBU',
        )
        AccessGrant.objects.create(
            user=self.officer, workflow='jawabu_portal', role='JBL_OFFICER', branch='EMBU',
        )
        self.batch = RequisitionBatch.objects.create(
            order_number='SIGN-001',
            version=2,
            status='generated',
            filename='JBL_Requisition_SIGN-001_v2.xlsx',
            file_content=b'retained-requisition-workbook-v2',
            farmer_ids=[],
        )
        self.factory = RequestFactory()

    def _scan(self, name='signed.pdf', data=b'%PDF-physical-signed-scan'):
        return SimpleUploadedFile(name, data, content_type='application/pdf')

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_authorised_role_retains_exact_source_and_approves_scan(self, storage):
        storage.return_value.upload.return_value = ('drive-scan-1', 'https://drive.test/signed-scan-1')

        signoff, replayed = submit_physical_signoff(
            document_type='requisition',
            document_id=str(self.batch.id),
            uploaded_file=self._scan(),
            actor=self.admin_user,
            access=user_access(self.admin_user, 'jawabu_portal'),
            request_id='signed-scan-1',
        )

        self.assertFalse(replayed)
        self.assertEqual(signoff.status, DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED)
        self.assertEqual(signoff.source_version, 2)
        self.assertEqual(signoff.source_file_content, self.batch.file_content)
        self.assertTrue(signoff.drive_url)
        self.assertEqual(signoff.approved_by, self.admin_user)
        self.assertTrue(DocumentPhysicalSignoffEvent.objects.filter(
            signoff=signoff,
            action=DocumentPhysicalSignoffEvent.ACTION_APPROVED,
        ).exists())

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_repeat_request_reuses_same_signoff_without_second_drive_upload(self, storage):
        storage.return_value.upload.return_value = ('drive-scan-1', 'https://drive.test/signed-scan-1')
        access = user_access(self.admin_user, 'jawabu_portal')
        first, _ = submit_physical_signoff(
            document_type='requisition', document_id=str(self.batch.id),
            uploaded_file=self._scan(), actor=self.admin_user, access=access,
            request_id='deduplicated-request',
        )
        repeated, replayed = submit_physical_signoff(
            document_type='requisition', document_id=str(self.batch.id),
            uploaded_file=self._scan(), actor=self.admin_user, access=access,
            request_id='deduplicated-request',
        )

        self.assertTrue(replayed)
        self.assertEqual(first.pk, repeated.pk)
        self.assertEqual(storage.return_value.upload.call_count, 1)

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_regenerated_document_keeps_prior_approved_scan_visible(self, storage):
        storage.return_value.upload.return_value = ('drive-scan-1', 'https://drive.test/signed-scan-1')
        submit_physical_signoff(
            document_type='requisition', document_id=str(self.batch.id),
            uploaded_file=self._scan(), actor=self.admin_user,
            access=user_access(self.admin_user, 'jawabu_portal'), request_id='old-approved-scan',
        )
        self.batch.version = 3
        self.batch.filename = 'JBL_Requisition_SIGN-001_v3.xlsx'
        self.batch.file_content = b'retained-requisition-workbook-v3'
        self.batch.save(update_fields=['version', 'filename', 'file_content', 'updated_at'])

        summary = document_signoff_summary('requisition', self.batch, can_upload=True)

        self.assertEqual(summary['status'], 'awaiting_signed_scan')
        self.assertEqual(len(summary['previous_approved']), 1)
        self.assertEqual(summary['previous_approved'][0]['source_version'], 2)

    def test_role_without_signoff_capability_is_denied(self):
        with self.assertRaises(PhysicalSignoffError):
            submit_physical_signoff(
                document_type='requisition', document_id=str(self.batch.id),
                uploaded_file=self._scan(), actor=self.officer,
                access=user_access(self.officer, 'jawabu_portal'), request_id='denied-request',
            )

    def test_signoff_policy_change_requires_independent_approver(self):
        maker = get_user_model().objects.create_superuser(
            username='signoff-maker', email='signoff-maker@example.test', password='password',
        )
        checker = get_user_model().objects.create_superuser(
            username='signoff-checker', email='signoff-checker@example.test', password='password',
        )
        checker.groups.add(Group.objects.get_or_create(name=APPROVER_GROUP_NAME)[0])
        request = create_document_signoff_policy_request(
            requester=maker,
            document_type='payment',
            approval_role='BUSINESS_ADMIN',
            reason='Confirm the initial payment sign-off authority.',
        )

        with self.assertRaises(PermissionDenied):
            approve_request(request_id=request.pk, approver=maker)
        approve_request(request_id=request.pk, approver=checker)

        self.assertEqual(DocumentSignoffPolicy.objects.get(document_type='payment').approval_role, 'BUSINESS_ADMIN')

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_drive_failure_keeps_scan_for_retry(self, storage):
        storage.return_value.upload.side_effect = RuntimeError('Drive unavailable')

        signoff, _ = submit_physical_signoff(
            document_type='requisition', document_id=str(self.batch.id),
            uploaded_file=self._scan(), actor=self.admin_user,
            access=user_access(self.admin_user, 'jawabu_portal'), request_id='retryable-scan',
        )

        self.assertEqual(signoff.status, DocumentPhysicalSignoff.STATUS_UPLOAD_FAILED)
        self.assertEqual(signoff.scan_file_content, b'%PDF-physical-signed-scan')
        self.assertTrue(signoff.drive_next_retry_at)

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_upload_endpoint_requires_attestation_then_uses_authorised_actor(self, storage):
        storage.return_value.upload.return_value = ('drive-scan-2', 'https://drive.test/signed-scan-2')
        missing_attestation = self.factory.post(
            '/api/portal/document-signoffs/requisition/upload/',
            {'signed_scan': self._scan()},
        )
        missing_attestation.portal_user = self.admin_user
        missing_attestation.portal_access = user_access(self.admin_user, 'jawabu_portal')

        rejected = portal_document_physical_signoff_upload(
            missing_attestation, 'requisition', str(self.batch.id),
        )

        self.assertEqual(rejected.status_code, 400)
        self.assertEqual(DocumentPhysicalSignoff.objects.count(), 0)

        request = self.factory.post(
            '/api/portal/document-signoffs/requisition/upload/',
            {'signed_scan': self._scan(), 'attested_complete': 'true'},
        )
        request.portal_user = self.admin_user
        request.portal_access = user_access(self.admin_user, 'jawabu_portal')

        response = portal_document_physical_signoff_upload(request, 'requisition', str(self.batch.id))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.content)['ok'])
        self.assertEqual(DocumentPhysicalSignoff.objects.filter(
            requisition_batch=self.batch,
            status=DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED,
        ).count(), 1)
