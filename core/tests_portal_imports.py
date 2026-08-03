"""Focused tests for IT-only, review-only Portal FarmUp/SysUp staging."""

from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core.models import GroupSheetConfiguration, JawabuFarmerMaster, JawabuFarmerUploadBatch
from core.services.portal_imports import (
    PortalImportError,
    attempt_import_archive,
    serialize_import_batch,
    stage_portal_import,
)


FARMUP_CSV = (
    'Full Name,ID NUMBER,HBG Hub,Mobile,Phone,Actual Receipts,Sign Date,Sales Person\n'
    'David Mugambi [23215888],,Embu,+254721997481,+254704408281,5000,01/05/2026,Jane Sales\n'
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
            group_id=self.group.group_id,
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

    def test_group_scope_cannot_stage_into_another_group(self):
        with self.assertRaisesMessage(PortalImportError, 'Select an active Jawabu HomeBiogas group'):
            self.stage(allowed_group_ids={'-100different-group'})
        self.assertFalse(JawabuFarmerUploadBatch.objects.exists())

    def test_replay_cannot_cross_import_group_scope(self):
        batch, _operation, _replayed = self.stage(allowed_group_ids={self.group.group_id})

        with self.assertRaisesMessage(PortalImportError, 'unavailable in your scope'):
            self.stage(allowed_group_ids={'-100different-group'})
        self.assertEqual(JawabuFarmerUploadBatch.objects.get(pk=batch.pk).group_id, self.group.group_id)

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
