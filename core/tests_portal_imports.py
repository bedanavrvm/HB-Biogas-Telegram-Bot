"""Focused tests for Portal FarmUp intake and IT-only SysUp source review."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import resolve

from core.models import ComplianceAuditEvent, GroupSheetConfiguration, JawabuFarmerMaster, JawabuFarmerUploadBatch
from core.services.portal_imports import (
    PortalImportConflict,
    PortalImportError,
    apply_portal_farmup_mapping,
    archive_portal_import_working_list,
    attempt_import_archive,
    commit_portal_farmup,
    farmup_revision_token,
    farmup_mapping_analysis,
    serialize_import_batch,
    source_table_page,
    stage_portal_import,
    stage_portal_farmup_version,
    validate_portal_farmup,
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

    def test_exact_file_with_new_request_key_reopens_monthly_worklist(self):
        batch, operation, _ = stage_portal_import(
            kind='farmup', filename='farmers.csv', content=FARMUP_CSV,
            request_id='monthly-upload-1', actor=self.user,
            allowed_group_ids={self.group.group_id}, period='2026-08',
        )
        repeated, repeated_operation, replayed = stage_portal_import(
            kind='farmup', filename='renamed-copy.csv', content=FARMUP_CSV,
            request_id='monthly-upload-2', actor=self.user,
            allowed_group_ids={self.group.group_id}, period='2026-08',
        )
        self.assertTrue(replayed)
        self.assertEqual(repeated.pk, batch.pk)
        self.assertEqual(repeated_operation.pk, operation.pk)
        self.assertEqual(JawabuFarmerUploadBatch.objects.count(), 1)

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
        self.assertEqual(resolve('/api/portal/farmup/stage/').func.__name__, 'portal_farmup_stage')
        self.assertEqual(resolve('/api/portal/farmup/example-batch/versions/').func.__name__, 'portal_farmup_version')
        self.assertEqual(resolve('/api/portal/farmup/example-batch/mapping/').func.__name__, 'portal_farmup_mapping')
        self.assertEqual(resolve('/api/portal/farmup/example-batch/validate/').func.__name__, 'portal_farmup_validate')
        self.assertEqual(resolve('/api/portal/farmup/example-batch/commit/').func.__name__, 'portal_farmup_commit')

    def test_reordered_known_columns_are_mapped_without_position_assumptions(self):
        csv_text = (
            'Sales Person,Phone,Sign Date,Actual Receipts,Mobile,HBG Hub,ID NUMBER,Full Name\n'
            'Jane Sales,+254704408281,01/05/2026,5000,+254721997481,Embu,23215888,David Mugambi\n'
        ).encode('utf-8')
        batch, _operation, _replayed = stage_portal_import(
            kind='farmup', filename='reordered.csv', content=csv_text,
            request_id='portal-farmup-reordered-0001', actor=self.user,
            allowed_group_ids={self.group.group_id},
        )
        self.assertEqual(batch.mapping['state'], 'auto_ready')
        self.assertEqual(batch.parsed_rows[0]['Customer Name'], 'DAVID MUGAMBI')
        self.assertEqual(batch.parsed_rows[0]['National ID'], '23215888')

    def test_unknown_header_requires_explicit_mapping_then_reparses_idempotently(self):
        csv_text = FARMUP_CSV.replace(b'Full Name', b'Applicant Legal Name')
        batch, _operation, _replayed = stage_portal_import(
            kind='farmup', filename='renamed.csv', content=csv_text,
            request_id='portal-farmup-guided-0001', actor=self.user,
            allowed_group_ids={self.group.group_id},
        )
        self.assertEqual(batch.mapping['state'], 'needs_mapping')
        self.assertEqual(batch.parsed_rows, [])
        self.assertNotIn('sample_values', batch.mapping['columns'][0])
        decisions = [
            {
                'source_id': item['source_id'],
                'target_field': 'customer_name' if item['source_id'] == 'Applicant Legal Name' else item['target_field'],
            }
            for item in batch.mapping['columns']
        ]
        mapped, replayed = apply_portal_farmup_mapping(
            batch_id=str(batch.pk), decisions=decisions,
            revision_token=farmup_revision_token(batch),
            request_id='portal-farmup-mapping-0001', actor=self.user,
            allowed_group_ids={self.group.group_id},
        )
        self.assertFalse(replayed)
        self.assertEqual(mapped.mapping['state'], 'confirmed')
        self.assertEqual(mapped.parsed_rows[0]['Customer Name'], 'DAVID MUGAMBI')
        self.assertTrue(ComplianceAuditEvent.objects.filter(action='portal.farmup.mapping_changed').exists())
        repeated, replayed = apply_portal_farmup_mapping(
            batch_id=str(batch.pk), decisions=decisions,
            revision_token=farmup_revision_token(batch),
            request_id='portal-farmup-mapping-0001', actor=self.user,
            allowed_group_ids={self.group.group_id},
        )
        self.assertTrue(replayed)
        self.assertEqual(repeated.pk, mapped.pk)

    def test_mapping_rejects_duplicate_targets_and_can_leave_required_field_for_row_entry(self):
        analysis = farmup_mapping_analysis(FARMUP_CSV.decode('utf-8'))
        decisions = [
            {'source_id': item['source_id'], 'target_field': item['target_field']}
            for item in analysis['columns']
        ]
        decisions[1]['target_field'] = decisions[0]['target_field']
        with self.assertRaisesMessage(PortalImportError, 'More than one CSV column'):
            farmup_mapping_analysis(FARMUP_CSV.decode('utf-8'), decisions)

        missing_name = [
            {'source_id': item['source_id'], 'target_field': '' if item['target_field'] == 'customer_name' else item['target_field']}
            for item in analysis['columns']
        ]
        remapped = farmup_mapping_analysis(FARMUP_CSV.decode('utf-8'), missing_name)
        self.assertIn('customer_name', remapped['missing_required_fields'])
        self.assertEqual(remapped['state'], 'confirmed')

    def test_mapping_rejects_missing_headers_and_overflow_rows(self):
        with self.assertRaisesMessage(PortalImportError, 'no usable header row'):
            farmup_mapping_analysis('')
        with self.assertRaisesMessage(PortalImportError, 'more values than the header row'):
            farmup_mapping_analysis('Full Name,Mobile\nJane,254700000001,unexpected\n')

    def test_warning_rows_require_actor_acknowledgement(self):
        batch, _operation, _replayed = self.stage(allowed_group_ids={self.group.group_id})
        row = dict(batch.parsed_rows[0], **{'National ID': '123456', 'approved': True})
        _batch, validation, counts = validate_portal_farmup(
            batch_id=str(batch.pk), rows=[row], revision_token=farmup_revision_token(batch),
            allowed_group_ids={self.group.group_id},
        )
        self.assertEqual(validation[0]['state'], 'warning')
        self.assertEqual(counts['selected'], 0)
        with self.assertRaisesMessage(PortalImportError, 'must be acknowledged'):
            commit_portal_farmup(
                batch_id=str(batch.pk), rows=[row], revision_token=farmup_revision_token(batch),
                request_id='portal-farmup-warning-0001', actor=self.user,
                allowed_group_ids={self.group.group_id},
            )
        row['warning_acknowledged'] = True
        _batch, _validation, counts = validate_portal_farmup(
            batch_id=str(batch.pk), rows=[row], revision_token=farmup_revision_token(batch),
            allowed_group_ids={self.group.group_id},
        )
        self.assertEqual(counts['selected'], 1)
        self.assertEqual(counts['warning_overrides'], 1)

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False)
    @patch('core.api.portal_views._portal_import_group_ids', return_value=None)
    def test_mapping_endpoint_returns_editable_fields_and_replays_after_mapping_was_applied(self, _group_scope):
        csv_text = FARMUP_CSV.replace(b'Full Name', b'Applicant Legal Name')
        batch, _operation, _replayed = stage_portal_import(
            kind='farmup', filename='renamed.csv', content=csv_text,
            request_id='portal-farmup-mapping-endpoint-stage-0001', actor=self.user,
            allowed_group_ids={self.group.group_id},
        )
        decisions = [
            {
                'source_id': item['source_id'],
                'target_field': 'customer_name' if item['source_id'] == 'Applicant Legal Name' else item['target_field'],
            }
            for item in batch.mapping['columns']
        ]
        request_key = 'portal-farmup-mapping-endpoint-0001'
        payload = {
            'mapping': decisions,
            'revision_token': farmup_revision_token(batch),
            'client_request_id': request_key,
        }
        response = self.client.post(
            f'/api/portal/farmup/{batch.pk}/mapping/', data=payload,
            content_type='application/json',
            headers={'X-Request-ID': request_key, 'Idempotency-Key': request_key},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('Customer Name', response.json()['batch']['editable_fields'])
        self.assertFalse(response.json()['replayed'])

        # This is the production failure mode: the mutation succeeded but the
        # response crashed. Retrying the original body/key must now succeed.
        replay = self.client.post(
            f'/api/portal/farmup/{batch.pk}/mapping/', data=payload,
            content_type='application/json',
            headers={'X-Request-ID': request_key, 'Idempotency-Key': request_key},
        )
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()['replayed'])
        self.assertIn('Customer Name', replay.json()['batch']['editable_fields'])

    def test_portal_farmup_commit_is_revision_bound_and_exactly_replayable(self):
        batch, _operation, _replayed = self.stage(allowed_group_ids={self.group.group_id})
        rows = list(batch.parsed_rows)
        token = farmup_revision_token(batch)

        committed_batch, result, replayed = commit_portal_farmup(
            batch_id=str(batch.pk), rows=rows, revision_token=token,
            request_id='portal-farmup-commit-0001', actor=self.user,
            allowed_group_ids={self.group.group_id},
        )

        self.assertFalse(replayed)
        self.assertTrue(result['success'])
        self.assertEqual(result['committed'], 1)
        self.assertEqual(committed_batch.portal_revision, 2)
        self.assertEqual(JawabuFarmerMaster.objects.count(), 1)
        event = ComplianceAuditEvent.objects.get(action='portal.farmup.committed')
        self.assertEqual(event.actor, self.user)
        self.assertNotIn('David Mugambi', str(event.after_values) + str(event.metadata))
        self.assertNotIn('23215888', str(event.after_values) + str(event.metadata))

        repeated_batch, repeated_result, replayed = commit_portal_farmup(
            batch_id=str(batch.pk), rows=rows, revision_token=token,
            request_id='portal-farmup-commit-0001', actor=self.user,
            allowed_group_ids={self.group.group_id},
        )
        self.assertTrue(replayed)
        self.assertEqual(repeated_batch.pk, batch.pk)
        self.assertEqual(repeated_result, result)
        self.assertEqual(JawabuFarmerMaster.objects.count(), 1)
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='portal.farmup.committed').count(), 1)

        changed_rows = [dict(rows[0], **{'Customer Name': 'Changed payload'})]
        with self.assertRaisesMessage(PortalImportConflict, 'different FarmUp rows'):
            commit_portal_farmup(
                batch_id=str(batch.pk), rows=changed_rows, revision_token=token,
                request_id='portal-farmup-commit-0001', actor=self.user,
                allowed_group_ids={self.group.group_id},
            )

    def test_portal_farmup_rejects_stale_revision_and_sysup_batch(self):
        batch, _operation, _replayed = self.stage(allowed_group_ids={self.group.group_id})
        token = farmup_revision_token(batch)
        batch.portal_revision += 1
        batch.save(update_fields=['portal_revision'])
        with self.assertRaisesMessage(PortalImportConflict, 'Another reviewer changed'):
            commit_portal_farmup(
                batch_id=str(batch.pk), rows=list(batch.parsed_rows), revision_token=token,
                request_id='portal-farmup-commit-stale-0001', actor=self.user,
                allowed_group_ids={self.group.group_id},
            )

        sysup, _operation, _replayed = stage_portal_import(
            kind='sysup', filename='customers.csv', content=SYSUP_CSV,
            request_id='portal-farmup-sysup-reject-0001', actor=self.user,
            allowed_group_ids={self.group.group_id},
        )
        with self.assertRaisesMessage(PortalImportError, 'SysUp batches'):
            commit_portal_farmup(
                batch_id=str(sysup.pk), rows=list(sysup.parsed_rows),
                revision_token=farmup_revision_token(sysup),
                request_id='portal-farmup-commit-sysup-0001', actor=self.user,
                allowed_group_ids={self.group.group_id},
            )

    def test_portal_farmup_supports_partial_then_complete_commit(self):
        batch, _operation, _replayed = self.stage(allowed_group_ids={self.group.group_id})
        valid = dict(batch.parsed_rows[0])
        flagged = dict(valid)
        flagged.update({
            'row_id': 2,
            'Customer Name': 'Second Farmer',
            'National ID': '',
            'Primary Phone': '254722000222',
            'Secondary Phone': '254733000333',
            'Import Status': 'review_needed',
            'Cleaning Notes': 'National ID is required',
            'approved': False,
        })
        batch.parsed_rows = [valid, flagged]
        batch.total_rows = 2
        batch.review_needed = 1
        batch.save(update_fields=['parsed_rows', 'total_rows', 'review_needed'])

        batch, first, replayed = commit_portal_farmup(
            batch_id=str(batch.pk), rows=[valid, flagged],
            revision_token=farmup_revision_token(batch),
            request_id='portal-farmup-partial-0001', actor=self.user,
            allowed_group_ids={self.group.group_id},
        )
        self.assertFalse(replayed)
        self.assertEqual(first['committed'], 1)
        self.assertEqual(first['review_needed'], 1)
        self.assertEqual(batch.status, 'pending_review')
        self.assertEqual(len(batch.parsed_rows), 1)

        corrected = dict(batch.parsed_rows[0])
        corrected.update({'National ID': '23215889', 'Cleaning Notes': '', 'approved': True})
        batch, final, _replayed = commit_portal_farmup(
            batch_id=str(batch.pk), rows=[corrected],
            revision_token=farmup_revision_token(batch),
            request_id='portal-farmup-complete-0001', actor=self.user,
            allowed_group_ids={self.group.group_id},
        )
        self.assertTrue(final['success'])
        self.assertEqual(final['review_needed'], 0)
        self.assertEqual(batch.status, 'committed')
        self.assertEqual(batch.committed_count, 2)

    def test_valid_unselected_row_is_held_and_can_commit_later(self):
        batch, _operation, _replayed = self.stage(allowed_group_ids={self.group.group_id})
        first = dict(batch.parsed_rows[0])
        second = dict(first)
        second.update({
            'row_id': 2, 'Customer Name': 'Held Farmer', 'National ID': '23215889',
            'Primary Phone': '254722000222', 'Secondary Phone': '254733000333',
            'approved': False, 'disposition': 'hold',
        })
        batch.parsed_rows = [first, second]
        batch.total_rows = 2
        batch.save(update_fields=['parsed_rows', 'total_rows'])

        batch, result, _ = commit_portal_farmup(
            batch_id=str(batch.pk), rows=[first, second], revision_token=farmup_revision_token(batch),
            request_id='partial-hold-1', actor=self.user, allowed_group_ids={self.group.group_id},
        )
        self.assertEqual(result['committed'], 1)
        self.assertEqual(result['held'], 1)
        self.assertEqual(len(batch.parsed_rows), 1)
        self.assertEqual(batch.parsed_rows[0]['disposition'], 'hold')

        held = dict(batch.parsed_rows[0], approved=True, disposition='commit_now')
        batch, result, _ = commit_portal_farmup(
            batch_id=str(batch.pk), rows=[held], revision_token=farmup_revision_token(batch),
            request_id='partial-hold-2', actor=self.user, allowed_group_ids={self.group.group_id},
        )
        self.assertEqual(result['committed'], 1)
        self.assertEqual(batch.committed_count, 2)
        self.assertEqual(batch.status, 'committed')

    def test_updated_monthly_version_recognizes_committed_row_and_addition(self):
        batch, _operation, _ = stage_portal_import(
            kind='farmup', filename='august.csv', content=FARMUP_CSV,
            request_id='monthly-v1', actor=self.user,
            allowed_group_ids={self.group.group_id}, period='2026-08',
        )
        commit_portal_farmup(
            batch_id=str(batch.pk), rows=list(batch.parsed_rows), revision_token=farmup_revision_token(batch),
            request_id='monthly-v1-commit', actor=self.user, allowed_group_ids={self.group.group_id},
        )
        expanded = FARMUP_CSV + (
            b'Held Farmer [23215889],,Embu,+254722000222,+254733000333,6000,02/05/2026,Jane Sales\n'
        )
        version, _operation, replayed = stage_portal_farmup_version(
            batch_id=str(batch.pk), filename='august-latest.csv', content=expanded,
            request_id='monthly-v2', actor=self.user, allowed_group_ids={self.group.group_id},
        )
        self.assertFalse(replayed)
        self.assertEqual(version.worklist_id, batch.worklist_id)
        self.assertEqual(version.version_number, 2)
        _batch, rows, counts = validate_portal_farmup(
            batch_id=str(version.pk), rows=list(version.parsed_rows),
            revision_token=farmup_revision_token(version), allowed_group_ids={self.group.group_id},
        )
        self.assertEqual(counts['unchanged'], 1)
        self.assertEqual(counts['new'], 1)
        self.assertEqual(sum(1 for row in rows if row['disposition'] == 'already_committed'), 1)

    def test_changed_existing_case_requires_update_acknowledgement(self):
        batch, _operation, _ = stage_portal_import(
            kind='farmup', filename='august.csv', content=FARMUP_CSV,
            request_id='update-v1', actor=self.user,
            allowed_group_ids={self.group.group_id}, period='2026-08',
        )
        commit_portal_farmup(
            batch_id=str(batch.pk), rows=list(batch.parsed_rows), revision_token=farmup_revision_token(batch),
            request_id='update-v1-commit', actor=self.user, allowed_group_ids={self.group.group_id},
        )
        changed_csv = FARMUP_CSV.replace(b'David Mugambi', b'David M. Mugambi')
        version, _operation, _ = stage_portal_farmup_version(
            batch_id=str(batch.pk), filename='august-latest.csv', content=changed_csv,
            request_id='update-v2', actor=self.user, allowed_group_ids={self.group.group_id},
        )
        rows = list(version.parsed_rows)
        _batch, validation, counts = validate_portal_farmup(
            batch_id=str(version.pk), rows=rows, revision_token=farmup_revision_token(version),
            allowed_group_ids={self.group.group_id},
        )
        self.assertEqual(validation[0]['match']['kind'], 'update')
        self.assertIn('Customer Name', validation[0]['match']['changed_fields'])
        self.assertEqual(counts['unresolved'], 1)
        with self.assertRaisesMessage(PortalImportError, 'acknowledge'):
            commit_portal_farmup(
                batch_id=str(version.pk), rows=rows, revision_token=farmup_revision_token(version),
                request_id='update-v2-commit', actor=self.user, allowed_group_ids={self.group.group_id},
            )

        acknowledged = [dict(rows[0], warning_acknowledged=True, update_acknowledged=True)]
        _batch, result, _ = commit_portal_farmup(
            batch_id=str(version.pk), rows=acknowledged, revision_token=farmup_revision_token(version),
            request_id='update-v2-commit-ack', actor=self.user, allowed_group_ids={self.group.group_id},
        )
        self.assertEqual(result['updated'], 1)
        self.assertEqual(JawabuFarmerMaster.objects.get().customer_name, 'DAVID M. MUGAMBI')

    def test_portal_commit_queues_master_publication_without_google_call(self):
        self.group.workflow = {'type': 'jawabu_homebiogas', 'master_sync_enabled': True}
        self.group.save(update_fields=['workflow'])
        batch, _operation, _ = self.stage(
            request_id='publication-stage', allowed_group_ids={self.group.group_id},
        )
        with patch('core.services.portal_publication._targets_for_farmer', return_value=['jawabu_master_publish']), \
                patch('core.services.jawabu_master.sync_committed_farmup_rows_to_master_sheet') as direct_sync:
            _batch, result, _ = commit_portal_farmup(
                batch_id=str(batch.pk), rows=list(batch.parsed_rows), revision_token=farmup_revision_token(batch),
                request_id='publication-commit', actor=self.user, allowed_group_ids={self.group.group_id},
            )
        direct_sync.assert_not_called()
        self.assertEqual(result['sheet_sync']['status'], 'pending')
        self.assertTrue(result['publications'][0]['pending_operation_ids'])

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
    def test_farmup_archive_endpoint_keeps_batch_in_history(self, _group_scope):
        batch, _operation, _replayed = self.stage(allowed_group_ids={self.group.group_id})
        request_id = 'portal-import-working-list-api-0001'

        response = self.client.post(
            f'/api/portal/farmup/{batch.pk}/archive/',
            data={'client_request_id': request_id},
            content_type='application/json',
            headers={'X-Request-ID': request_id, 'Idempotency-Key': request_id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertTrue(response.json()['batch']['is_portal_archived'])

        active_list = self.client.get('/api/portal/farmup/')
        self.assertEqual(active_list.status_code, 200)
        self.assertEqual(len(active_list.json()['batches']), 1)
        listed_batch = active_list.json()['batches'][0]
        self.assertIsInstance(listed_batch, dict)
        self.assertTrue(listed_batch['is_portal_archived'])
        self.assertIsInstance(listed_batch['publication'], dict)
        self.assertEqual(listed_batch['publication']['status'], 'not_required')
        retained_detail = self.client.get(f'/api/portal/farmup/{batch.pk}/')
        self.assertEqual(retained_detail.status_code, 200)
        self.assertEqual(len(retained_detail.json()['batch']['rows']), 1)

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
