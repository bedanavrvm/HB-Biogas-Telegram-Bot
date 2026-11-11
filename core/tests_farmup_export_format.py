"""Synthetic HomeBiogas export acceptance through native FarmUp boundaries."""
import csv
import io
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import (
    ComplianceAuditEvent, GroupSheetConfiguration, IntegrationOperation,
    JawabuCustomer, JawabuFarmerMaster, JawabuFarmerUploadBatch,
)
from core.services.jawabu_master import build_cleaned_master_preview, create_farmup_review_batch
from core.services.portal_imports import (
    PortalImportError, apply_portal_farmup_mapping, commit_portal_farmup,
    farmup_mapping_analysis, farmup_revision_token, source_table_page,
    stage_portal_farmup_version, stage_portal_import, validate_portal_farmup,
)
from core.services.sheet_columns import NamedColumns, SheetColumnError
from hb_operations.deposits import deposit_state


HEADERS = [
    'Count', 'Full Name', 'ID NUMBER', 'COMMENTS', 'HBG Contract Name',
    'Sign Date', 'Sign Date', 'Contract Type', 'Financial Partners',
    'Installation Status', 'Actual Receipts Currency', 'HBG Hub',
    'Sales Person', 'Mobile', 'Phone', 'Created Date', 'Uploaded Date',
]


def export_row(number=1, *, first='1/11/2026', second='', receipt='KES 5,000.00'):
    return [
        str(number), f'Synthetic Farmer {number} [880000{number:02d}]', '',
        'Synthetic visit note', f'SYNTHETIC-CONTRACT-{number}', first, second,
        'D2C (direct 2 consumer)', 'Jawabu', 'Pending', receipt,
        'Nakuru' if number == 1 else 'Kiambu', 'Synthetic Sales [111]',
        f'07110000{number:02d}', f'07220000{number:02d}', '1/11/2026', '7/11/2026',
    ]


def export_bytes(rows=None, headers=None):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(HEADERS if headers is None else headers)
    writer.writerows([export_row()] if rows is None else rows)
    return stream.getvalue().encode('utf-8-sig')


class FarmUpExportFormatTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username='synthetic-farmup-it')
        self.group = GroupSheetConfiguration.objects.create(
            group_id='synthetic-farmup-export', sheet_id='synthetic-register',
            workflow={'type': 'jawabu_homebiogas', 'master_sync_enabled': True,
                      'master_sheet_name': 'Master Data', 'eco_conserve_sheet_name': 'Eco-conserve'},
        )
        self.allowed = {self.group.group_id}

    def stage(self, content=None, *, request='synthetic-native-export'):
        return stage_portal_import(
            kind='farmup', filename='synthetic-farmers.csv',
            content=export_bytes() if content is None else content,
            request_id=request, actor=self.actor, allowed_group_ids=self.allowed,
            period='2026-11',
        )[0]

    def validate(self, batch):
        return validate_portal_farmup(
            batch_id=str(batch.pk), rows=list(batch.parsed_rows),
            revision_token=farmup_revision_token(batch), allowed_group_ids=self.allowed,
        )

    def test_raw_export_stages_without_cleanup_and_retains_exact_source(self):
        content = export_bytes([export_row(), [''] * len(HEADERS), export_row(2, receipt='KES 0.00')])
        batch = self.stage(content)
        self.assertEqual(bytes(batch.source_content), content)
        self.assertEqual(batch.mapping['state'], 'auto_ready')
        self.assertEqual(batch.mapping['unresolved_columns'], [])
        self.assertEqual(batch.mapping['missing_required_fields'], [])
        self.assertEqual(batch.total_rows, 2)
        self.assertEqual(batch.review_needed, 0)
        self.assertEqual([r['Source Row'] for r in batch.parsed_rows], [2, 4])
        first = batch.parsed_rows[0]
        self.assertEqual(first['Customer Name'], 'SYNTHETIC FARMER 1')
        self.assertEqual(first['National ID'], '88000001')
        self.assertEqual(first['Primary Phone'], '254711000001')
        self.assertEqual(first['Secondary Phone'], '254722000001')
        self.assertEqual(first['County'], 'NAKURU')
        self.assertEqual(first['HB Sales Person'], 'SYNTHETIC SALES')
        self.assertEqual(first['Deposit Paid to HB'], '5000')
        self.assertEqual(first['HBG Visit Date'], '01-11-2026')
        self.assertEqual(first['Installation Status'], '')
        self.assertEqual(first['Order No.'], '')
        table = source_table_page(batch, page=1, page_size=50)
        self.assertEqual(table['headers'], HEADERS)
        self.assertEqual(table['rows'][0], export_row())
        self.assertFalse(JawabuFarmerMaster.objects.exists())
        _, validation, counts = self.validate(batch)
        self.assertEqual(counts['new'], 2)
        self.assertEqual(counts['unresolved'], 0)
        self.assertTrue(all(r['selected'] for r in validation))

    def test_second_export_date_is_preferred_and_blank_second_falls_back_per_row(self):
        batch = self.stage(export_bytes([
            export_row(first='1/11/2026', second='4/11/2026'),
            export_row(2, first='22/10/2026'),
        ]))
        self.assertEqual([r['HBG Visit Date'] for r in batch.parsed_rows],
                         ['04-11-2026', '22-10-2026'])
        columns = {c['source_id']: c for c in batch.mapping['columns']}
        self.assertEqual(columns['Sign Date__2']['target_field'], 'sign_date')
        self.assertEqual(columns['Sign Date']['resolution'], 'ignored')

    def test_explicit_mapping_uses_export_date_fallback_and_can_disable_it(self):
        batch = self.stage()
        decisions = [{'source_id': c['source_id'], 'target_field': c['target_field']}
                     for c in batch.mapping['columns']]
        batch, _ = apply_portal_farmup_mapping(
            batch_id=str(batch.pk), decisions=decisions, revision_token=farmup_revision_token(batch),
            request_id='synthetic-export-map', actor=self.actor, allowed_group_ids=self.allowed,
        )
        self.assertEqual(batch.parsed_rows[0]['HBG Visit Date'], '01-11-2026')
        decisions = [{**c, 'target_field': '' if c['target_field'] in {'sign_date', 'actual_receipts'} else c['target_field']}
                     for c in decisions]
        batch, _ = apply_portal_farmup_mapping(
            batch_id=str(batch.pk), decisions=decisions, revision_token=farmup_revision_token(batch),
            request_id='synthetic-export-ignore-date', actor=self.actor, allowed_group_ids=self.allowed,
        )
        self.assertEqual(batch.parsed_rows[0]['HBG Visit Date'], '')
        self.assertEqual(batch.parsed_rows[0]['Deposit Paid to HB'], '')
        _, validation, _ = self.validate(batch)
        self.assertTrue(any('Missing HBG Visit Date' in issue['message'] for issue in validation[0]['issues']))

    def test_reordered_export_columns_preserve_named_bindings(self):
        order = [13, 14, 12, 11, 10, 5, 6, 1, 2, 0, 3, 4, 7, 8, 9, 15, 16]
        row = export_row()
        batch = self.stage(export_bytes([[row[i] for i in order]], [HEADERS[i] for i in order]))
        self.assertEqual(batch.mapping['state'], 'auto_ready')
        self.assertEqual(batch.parsed_rows[0]['Deposit Paid to HB'], '5000')
        self.assertEqual(batch.parsed_rows[0]['HBG Visit Date'], '01-11-2026')
        self.assertEqual(batch.parsed_rows[0]['Primary Phone'], '254711000001')

    def test_separate_amount_and_currency_columns_keep_their_own_meaning(self):
        headers = HEADERS + ['Actual Receipts']
        row = export_row()
        row[10] = 'KES'
        batch = self.stage(export_bytes([row + ['5250.50']], headers))
        columns = {c['source_id']: c for c in batch.mapping['columns']}
        self.assertEqual(columns['Actual Receipts Currency']['target_field'], 'actual_receipts_currency')
        self.assertEqual(columns['Actual Receipts']['target_field'], 'actual_receipts')
        self.assertEqual(batch.parsed_rows[0]['Deposit Paid to HB'], '5250.5')

    def test_currency_code_without_amount_is_not_invented_as_zero(self):
        batch = self.stage(export_bytes([export_row(receipt='KES')]))
        self.assertEqual(batch.parsed_rows[0]['Deposit Paid to HB'], '')
        self.assertIn('actual_receipts', batch.mapping['missing_required_fields'])

    def test_bad_or_foreign_receipts_are_held_and_cannot_create_cases(self):
        for value in ('KES -5.00', 'KES 5,000.001', 'USD 5,000.00', 'KES NaN', 'KES 10000000000.00'):
            with self.subTest(value=value):
                batch = self.stage(export_bytes([export_row(receipt=value)]), request='bad-amount-' + value)
                row = dict(batch.parsed_rows[0], approved=True, disposition='commit_now')
                self.assertEqual(row['Deposit Paid to HB'], value)
                with self.assertRaisesMessage(PortalImportError, 'needs correction'):
                    commit_portal_farmup(
                        batch_id=str(batch.pk), rows=[row], revision_token=farmup_revision_token(batch),
                        request_id='bad-commit-' + value, actor=self.actor, allowed_group_ids=self.allowed,
                    )
                self.assertFalse(JawabuFarmerMaster.objects.exists())
                self.assertFalse(JawabuCustomer.objects.exists())
                batch.delete()

    def test_duplicate_source_fields_and_live_register_columns_stay_strict(self):
        for headers in (
            ['Full Name', 'Full Name'], ['Sign Date', 'Sign Date', 'Sign Date'],
            ['Sign Date', 'Sign Date', 'Sign Date__2'], ['National ID', ' national id '],
        ):
            with self.subTest(headers=headers), self.assertRaises(SheetColumnError):
                farmup_mapping_analysis(export_bytes([[''] * len(headers)], headers).decode('utf-8-sig'))
        with self.assertRaises(SheetColumnError):
            NamedColumns(['Sign Date', 'Sign Date'])
        self.assertFalse(JawabuFarmerUploadBatch.objects.exists())

    def test_unknown_source_fields_still_require_review(self):
        batch = self.stage(export_bytes([export_row() + ['synthetic']], HEADERS + ['Unfamiliar field']))
        self.assertEqual(batch.mapping['state'], 'needs_mapping')
        self.assertEqual(batch.parsed_rows, [])
        self.assertEqual(batch.mapping['unresolved_columns'], ['Unfamiliar field'])

    def test_telegram_review_uses_the_same_native_export_parser(self):
        batch, stats = create_farmup_review_batch(
            group_id=self.group.group_id, telegram_message_id='synthetic-message', sender='Synthetic staff',
            source_filename='synthetic-export.csv', csv_text=export_bytes().decode('utf-8-sig'),
            group_config=self.group,
        )
        self.assertEqual(stats['review_needed'], 0)
        self.assertEqual(batch.parsed_rows[0]['National ID'], '88000001')
        self.assertEqual(batch.parsed_rows[0]['Deposit Paid to HB'], '5000')

    def test_original_export_reconciles_with_staged_cleaned_copy_without_changes(self):
        headers = list(HEADERS)
        headers[5], headers[6], headers[10] = 'HBG Visit Date', 'Unused Sign Date', 'Actual Receipts'
        cleaned = export_row()
        cleaned[10] = '5000.00'
        content = export_bytes([cleaned], headers)
        batch = self.stage(content)
        decisions = [{'source_id': c['source_id'], 'target_field': c['target_field']}
                     for c in batch.mapping['columns']]
        batch, _ = apply_portal_farmup_mapping(
            batch_id=str(batch.pk), decisions=decisions, revision_token=farmup_revision_token(batch),
            request_id='synthetic-cleaned-map', actor=self.actor, allowed_group_ids=self.allowed,
        )
        original = export_bytes()
        version, _, _ = stage_portal_farmup_version(
            batch_id=str(batch.pk), filename='synthetic-original.csv', content=original,
            request_id='synthetic-original-version', actor=self.actor, allowed_group_ids=self.allowed,
        )
        self.assertEqual(version.worklist_id, batch.worklist_id)
        self.assertEqual(version.mapping['state'], 'auto_ready')
        self.assertEqual(version.reconciliation['source_unchanged'], 1)
        self.assertEqual(version.reconciliation['source_changed'], 0)
        self.assertEqual(bytes(version.source_content), original)
        batch.refresh_from_db()
        self.assertEqual(bytes(batch.source_content), content)
        self.assertFalse(batch.is_current_version)
        self.assertFalse(JawabuFarmerMaster.objects.exists())

    def test_raw_export_commit_replay_and_monthly_version_preserve_cases_and_source(self):
        content = export_bytes([export_row(), export_row(2, receipt='KES 0.00')])
        batch = self.stage(content)
        rows, token = list(batch.parsed_rows), farmup_revision_token(batch)
        with patch('core.services.jawabu_master.sync_committed_farmup_rows_to_master_sheet') as direct_sync:
            batch, result, replayed = commit_portal_farmup(
                batch_id=str(batch.pk), rows=rows, revision_token=token,
                request_id='synthetic-export-commit', actor=self.actor, allowed_group_ids=self.allowed,
            )
        self.assertFalse(replayed)
        self.assertEqual(result['created'], 2)
        self.assertEqual(result['updated'], 0)
        self.assertEqual(batch.status, 'committed')
        self.assertEqual(bytes(batch.source_content), content)
        direct_sync.assert_not_called()
        cases = list(JawabuFarmerMaster.objects.order_by('national_id'))
        self.assertFalse(deposit_state(cases[0])['deposit_hold'])
        self.assertTrue(deposit_state(cases[1])['deposit_hold'])
        self.assertEqual(cases[0].deposit_paid_hbg, Decimal('5000.00'))
        self.assertEqual(cases[0].hbg_visit_date.isoformat(), '2026-11-01')
        self.assertTrue(all(not f.jbl_visit_date and not f.credit_decided_at and not f.order_number for f in cases))
        operations = IntegrationOperation.objects.filter(operation_type='jawabu_master_publish')
        self.assertEqual(operations.count(), 2)
        self.assertEqual({o.metadata['destination']['tab'] for o in operations}, {'Master Data', 'Eco-conserve'})
        _, repeated, replayed = commit_portal_farmup(
            batch_id=str(batch.pk), rows=rows, revision_token=token,
            request_id='synthetic-export-commit', actor=self.actor, allowed_group_ids=self.allowed,
        )
        self.assertTrue(replayed)
        self.assertEqual(repeated, result)
        self.assertEqual(JawabuFarmerMaster.objects.count(), 2)
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='portal.farmup.committed').count(), 1)
        version_content = export_bytes([export_row(), export_row(2, receipt='KES 0.00'), export_row(3)])
        version, _, _ = stage_portal_farmup_version(
            batch_id=str(batch.pk), filename='synthetic-updated.csv', content=version_content,
            request_id='synthetic-export-version', actor=self.actor, allowed_group_ids=self.allowed,
        )
        _, validation, counts = self.validate(version)
        self.assertEqual(counts['unchanged'], 2)
        self.assertEqual(sum(row['match']['kind'] == 'new' for row in validation), 1)
        self.assertEqual(JawabuFarmerMaster.objects.count(), 2)
        batch.refresh_from_db()
        self.assertEqual(bytes(batch.source_content), content)
        self.assertEqual(bytes(version.source_content), version_content)

    def test_impossible_date_stays_visible_and_blocks_commit(self):
        batch = self.stage(export_bytes([export_row(second='31/11/2026')]))
        row = dict(batch.parsed_rows[0], approved=True, disposition='commit_now')
        with self.assertRaisesMessage(PortalImportError, 'needs correction'):
            commit_portal_farmup(
                batch_id=str(batch.pk), rows=[row], revision_token=farmup_revision_token(batch),
                request_id='synthetic-bad-export-date', actor=self.actor, allowed_group_ids=self.allowed,
            )
        self.assertFalse(JawabuFarmerMaster.objects.exists())

    def test_source_ids_keep_leading_zeroes(self):
        row = export_row()
        row[1] = 'Synthetic Farmer [00012345]'
        preview, _ = build_cleaned_master_preview(io.StringIO(export_bytes([row]).decode('utf-8-sig')))
        self.assertEqual(preview[0]['National ID'], '00012345')
