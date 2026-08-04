"""Focused tests for IT-only, review-only Portal FarmUp/SysUp staging."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import resolve

from core.models import ComplianceAuditEvent, GroupSheetConfiguration, JawabuFarmerMaster, JawabuFarmerUploadBatch
from core.services.portal_imports import (
    PortalImportError,
    archive_portal_import_working_list,
    attempt_import_archive,
    serialize_import_batch,
    source_table_page,
    stage_portal_import,
)


FARMUP_CSV = (
    'Full Name,ID NUMBER,HBG Hub,Mobile,Phone,Actual Receipts,Sign Date,Sales Person\n'
    'David Mugambi [23215888],,Embu,+254721997481,+254704408281,5000,01/05/2026,Jane Sales\n'
).encode('utf-8')

SYSUP_CSV = (
    'Customer ID,Name,Mobile No,ID NO,Branch,Loan Officer,Product Name,LGF Balance\n'
    '12345,MWANGI JANE,+254721997481,23215888,EMBU,Jane Officer,HomeBiogas,"5,000"\n'
).encode('utf-8')


class PortalImportStagingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='portal-import-it', is_active=True)
        self.group = GroupSheetConfiguration.objects.create(
            group_id='-100portal-imports',
            display_name='Jawabu HomeBiogas',
            sheet_id='test-sheet-id',
            workflow={'type': 'jawabu_homebiogas'},
        )

    def stage(self, *, request_id='portal-import-key-0001', allowed_group_ids=None):
        return stage_portal_import(
            kind='farmup',
            filename='farmers.csv',
            content=FARMUP_CSV,
            request_id=request_id,
            actor=self.user,
            allowed_group_ids=allowed_group_ids,
        )

    def test_stage_is_review_only_and_idempotent(self):
        batch, operation, replayed = self.stage(allowed_group_ids={self.group.group_id})

        self.assertFalse(replayed)
        self.assertEqual(batch.status, 'pending_review')
        self.assertEqual(batch.created_by, self.user)
        self.assertEqual(batch.source_content, FARMUP_CSV)
        self.assertTrue(batch.source_content_hash)
        self.assertEqual(batch.total_rows, 1)
        self.assertFalse(JawabuFarmerMaster.objects.exists())

        repeated, repeated_operation, replayed = self.stage(allowed_group_ids={self.group.group_id})
        self.assertTrue(replayed)
        self.assertEqual(repeated.pk, batch.pk)
        self.assertEqual(repeated_operation.pk, operation.pk)
        self.assertEqual(JawabuFarmerUploadBatch.objects.count(), 1)
        self.assertFalse(JawabuFarmerMaster.objects.exists())

    def test_source_review_preserves_uploaded_columns_and_values_without_parser_fields(self):
        batch, _operation, _replayed = self.stage(allowed_group_ids={self.group.group_id})

        table = source_table_page(batch, page=1, page_size=50)

        self.assertEqual(
            table['headers'],
            ['Full Name', 'ID NUMBER', 'HBG Hub', 'Mobile', 'Phone', 'Actual Receipts', 'Sign Date', 'Sales Person'],
        )
        self.assertEqual(
            table['rows'],
            [['David Mugambi [23215888]', '', 'Embu', '+254721997481', '+254704408281', '5000', '01/05/2026', 'Jane Sales']],
        )
        self.assertNotIn('Import Status', table['headers'])
        self.assertNotIn('Cleaning Notes', table['headers'])

    def test_sysup_source_review_preserves_export_headers_and_original_values(self):
        batch, _operation, _replayed = stage_portal_import(
            kind='sysup',
            filename='customers-without-loans.csv',
            content=SYSUP_CSV,
            request_id='portal-import-sysup-source-review-0001',
            actor=self.user,
            allowed_group_ids={self.group.group_id},
        )

        table = source_table_page(batch, page=1, page_size=50)

        self.assertEqual(
            table['headers'],
            ['Customer ID', 'Name', 'Mobile No', 'ID NO', 'Branch', 'Loan Officer', 'Product Name', 'LGF Balance'],
        )
        self.assertEqual(
            table['rows'],
            [['12345', 'MWANGI JANE', '+254721997481', '23215888', 'EMBU', 'Jane Officer', 'HomeBiogas', '5,000']],
        )
        self.assertNotIn('Match Basis', table['headers'])
        self.assertNotIn('Matched Farmer ID', table['headers'])

    def test_configured_import_group_must_be_in_staff_scope(self):
        with self.assertRaisesMessage(PortalImportError, 'does not cover the configured Jawabu HomeBiogas workflow'):
            self.stage(allowed_group_ids={'-100different-group'})
        self.assertFalse(JawabuFarmerUploadBatch.objects.exists())

    def test_replay_cannot_cross_import_group_scope(self):
        batch, _operation, _replayed = self.stage(allowed_group_ids={self.group.group_id})

        with self.assertRaisesMessage(PortalImportError, 'unavailable in your scope'):
            self.stage(allowed_group_ids={'-100different-group'})
        self.assertEqual(JawabuFarmerUploadBatch.objects.get(pk=batch.pk).group_id, self.group.group_id)

    def test_import_group_is_fixed_to_the_single_configured_workflow(self):
        GroupSheetConfiguration.objects.create(
            group_id='-100another-jawabu-group',
            display_name='Another Jawabu workflow',
            sheet_id='another-sheet-id',
            workflow={'type': 'jawabu'},
        )

        batch, _operation, _replayed = self.stage(allowed_group_ids={self.group.group_id})

        self.assertEqual(batch.group_id, self.group.group_id)

    def test_multiple_configured_import_workflows_are_a_safe_configuration_error(self):
        GroupSheetConfiguration.objects.create(
            group_id='-100duplicate-import-workflow',
            display_name='Duplicate Jawabu HomeBiogas',
            sheet_id='duplicate-sheet-id',
            workflow={'type': 'jawabu_homebiogas'},
        )

        with self.assertRaisesMessage(PortalImportError, 'More than one Jawabu HomeBiogas import workflow'):
            self.stage()

    def test_django_superuser_import_scope_is_global(self):
        from core.api.portal_views import _portal_import_group_ids

        request = SimpleNamespace(portal_access={'technical_override': True, 'grants': []})

        self.assertIsNone(_portal_import_group_ids(request))

    def test_import_action_routes_precede_the_generic_batch_detail_route(self):
        self.assertEqual(
            resolve('/api/portal/imports/archive-attempt/').func.__name__,
            'portal_import_archive_attempt',
        )
        self.assertEqual(
            resolve('/api/portal/imports/example-batch/archive/').func.__name__,
            'portal_import_archive',
        )

    def test_working_list_archive_is_idempotent_and_preserves_import_evidence(self):
        batch, _operation, _replayed = self.stage(allowed_group_ids={self.group.group_id})
        original_source = batch.source_content
        original_rows = list(batch.parsed_rows)
        original_status = batch.status

        archived, replayed = archive_portal_import_working_list(
            batch_id=str(batch.pk),
            actor=self.user,
            request_id='portal-import-working-list-archive-0001',
            allowed_group_ids={self.group.group_id},
        )
        self.assertFalse(replayed)
        self.assertTrue(archived.is_portal_archived)
        self.assertEqual(archived.portal_archived_by, self.user)
        self.assertIsNotNone(archived.portal_archived_at)
        batch.refresh_from_db()
        self.assertEqual(batch.source_content, original_source)
        self.assertEqual(batch.parsed_rows, original_rows)
        self.assertEqual(batch.status, original_status)
        self.assertTrue(ComplianceAuditEvent.objects.filter(
            action='portal.import.working_list_archived', subject_id=str(batch.pk),
        ).exists())

        repeated, replayed = archive_portal_import_working_list(
            batch_id=str(batch.pk),
            actor=self.user,
            request_id='portal-import-working-list-archive-0002',
            allowed_group_ids={self.group.group_id},
        )
        self.assertTrue(replayed)
        self.assertEqual(repeated.pk, batch.pk)
        self.assertEqual(ComplianceAuditEvent.objects.filter(
            action='portal.import.working_list_archived', subject_id=str(batch.pk),
        ).count(), 1)

    def test_working_list_archive_never_crosses_group_scope(self):
        batch, _operation, _replayed = self.stage(allowed_group_ids={self.group.group_id})

        with self.assertRaisesMessage(PortalImportError, 'unavailable in your scope'):
            archive_portal_import_working_list(
                batch_id=str(batch.pk),
                actor=self.user,
                request_id='portal-import-working-list-scope-0001',
                allowed_group_ids={'-100different-group'},
            )
        batch.refresh_from_db()
        self.assertFalse(batch.is_portal_archived)

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False)
    @patch('core.api.portal_views._portal_import_group_ids', return_value=None)
    def test_import_archive_endpoint_removes_only_the_active_list_entry(self, _group_scope):
        batch, _operation, _replayed = self.stage(allowed_group_ids={self.group.group_id})
        request_id = 'portal-import-working-list-api-0001'

        response = self.client.post(
            f'/api/portal/imports/{batch.pk}/archive/',
            data={'client_request_id': request_id},
            content_type='application/json',
            headers={'X-Request-ID': request_id, 'Idempotency-Key': request_id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertTrue(response.json()['batch']['is_portal_archived'])

        active_list = self.client.get('/api/portal/imports/')
        self.assertEqual(active_list.status_code, 200)
        self.assertEqual(active_list.json()['batches'], [])
        retained_detail = self.client.get(f'/api/portal/imports/{batch.pk}/')
        self.assertEqual(retained_detail.status_code, 200)
        self.assertEqual(len(retained_detail.json()['batch']['source_table']['rows']), 1)

    @override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='test-shared-drive-root')
    @patch('core.services.order_approval.GoogleDriveMediaStorage.upload', return_value=('drive-file-1', 'https://drive.example/file-1'))
    def test_drive_archive_runs_after_staging_and_never_exposes_raw_source(self, upload):
        batch, operation, _replayed = self.stage(allowed_group_ids={self.group.group_id})

        result = attempt_import_archive(str(operation.pk))
        batch.refresh_from_db()

        self.assertTrue(result['ok'])
        self.assertEqual(batch.archive_file_id, 'drive-file-1')
        self.assertEqual(batch.archive_url, 'https://drive.example/file-1')
        upload.assert_called_once()
        payload = serialize_import_batch(batch)
        self.assertNotIn('source_content', payload)
        self.assertNotIn('archive_url', payload)
