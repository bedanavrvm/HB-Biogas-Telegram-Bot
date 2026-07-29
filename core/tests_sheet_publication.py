from types import SimpleNamespace

from django.test import SimpleTestCase

from core.services.live_sheet_records import (
    LiveSheetRecordError,
    delete_live_sheet_row,
    update_live_sheet_row,
)
from core.services.sheet_publication import (
    aliases_for,
    coverage_for_headers,
    surfaces_for_configuration,
)
from core.services.sheet_sync import sync_all_configured_groups, sync_group_from_sheet


class SheetPublicationRegistryTests(SimpleTestCase):
    def test_coverage_matches_aliases_without_reading_rows(self):
        report = coverage_for_headers(
            'jawabu_master',
            ['Customer Number', 'National ID', 'Branch', 'Ward'],
        )

        self.assertEqual(report['present_count'], 4)
        self.assertEqual(
            {item['field'] for item in report['present']},
            {'customer_no', 'national_id', 'branch', 'ward'},
        )
        self.assertIn('payment_call_up_comment', {item['field'] for item in report['missing']})

    def test_jawabu_configuration_reports_master_and_internal_surfaces(self):
        config = SimpleNamespace(
            sheet_id='primary',
            sheet_name='Master Data',
            workflow={
                'type': 'jawabu_homebiogas',
                'master_sync_enabled': True,
                'master_sheet_id': 'master',
                'internal_order_sync_enabled': True,
                'internal_order_sheet_id': 'orders',
            },
        )

        targets = surfaces_for_configuration(config)

        self.assertEqual([target['surface'] for target in targets], ['jawabu_master', 'internal_order'])

    def test_system_export_headers_are_supported_by_publication_aliases(self):
        self.assertIn('Customer ID', aliases_for('jawabu_master', 'customer_no'))
        self.assertIn('Name', aliases_for('jawabu_master', 'customer_name'))
        self.assertIn('Mobile No', aliases_for('jawabu_master', 'primary_phone'))
        self.assertIn('ID NO', aliases_for('jawabu_master', 'national_id'))
        self.assertIn('Loan Officer', aliases_for('jawabu_master', 'system_loan_officer'))
        self.assertIn('Product Name', aliases_for('jawabu_master', 'payment_product'))
        self.assertIn('LGF Balance', aliases_for('jawabu_master', 'system_deposit_paid_jbl'))


class SheetImportBoundaryTests(SimpleTestCase):
    def test_legacy_import_calls_are_explicitly_disabled(self):
        result = sync_group_from_sheet('group-1')
        self.assertEqual(result['status'], 'disabled')
        self.assertEqual(result['code'], 'SHEET_IMPORT_DISABLED')
        self.assertEqual(sync_all_configured_groups()['code'], 'SHEET_IMPORT_DISABLED')

    def test_live_sheet_mutations_are_rejected(self):
        with self.assertRaisesRegex(LiveSheetRecordError, 'SHEET_IMPORT_DISABLED'):
            update_live_sheet_row(SimpleNamespace(), 'Orders', 2, {0: 'changed'})
        with self.assertRaisesRegex(LiveSheetRecordError, 'SHEET_IMPORT_DISABLED'):
            delete_live_sheet_row(SimpleNamespace(), 'Orders', 2)
