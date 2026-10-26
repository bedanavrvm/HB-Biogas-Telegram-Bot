"""Regression boundaries reproduced by the isolated Portal workflow audit."""
from datetime import datetime, timezone as datetime_timezone
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings

from core.models import GroupSheetConfiguration, JawabuFarmerMaster, ParsedInvoice
from core.services.invoice_parser import _exact_invoice_identity_match, parse_invoice_text
from core.services.jawabu_master import update_master_sheet_row
from core.services.jawabu_pipeline import sync_farmer_to_master_sheet
from core.services.sheet_columns import SheetColumnError
from core.test_named_sheet import NamedSheet
from core.tests import FakeJawabuService, FakeMasterDataSheet


class PortalAuditRegressionTests(SimpleTestCase):
    def test_sheet_update_resolves_punctuation_aliases_and_preserves_staff_cells(self):
        sheet = NamedSheet(['Staff formula', 'Order No', 'Payment No'], [['=SUM(1,2)', '', '']])
        update_master_sheet_row(sheet, 2, ['=SUM(1,2)', 'HB-1', '1'],
                                headers=sheet.row_values(1), header_row=1,
                                changed_headers=['Order No.', 'Payment No #'])
        self.assertEqual(sheet.value(2, 'Order No'), 'HB-1')
        self.assertEqual(sheet.value(2, 'Payment No'), '1')
        self.assertEqual(sheet.value(2, 'Staff formula'), '=SUM(1,2)')

    def test_sheet_update_rejects_ambiguous_or_missing_headers_before_writing(self):
        for headers, changes in ((['Order No', 'Order No.'], ['Order No.']),
                                 (['Customer Name'], ['Order No.'])):
            with self.subTest(headers=headers):
                sheet = NamedSheet(headers, [[''] * len(headers)])
                before = sheet.get_all_values()
                with self.assertRaises(SheetColumnError):
                    update_master_sheet_row(sheet, 2, ['HB-1'] * len(headers),
                                            headers=headers, header_row=1, changed_headers=changes)
                self.assertEqual(sheet.get_all_values(), before)

    def test_invoice_parser_keeps_phone_mismatches_in_supported_formats(self):
        farmer = JawabuFarmerMaster(customer_name='Synthetic Applicant', national_id='99000009',
                                   primary_phone='254712345678')
        for phone in ('+254798765432', '254798765432', '0798765432',
                      '00254798765432', '005798765432', '+254 798 765 432',
                      '+254 (0) 798-765-432'):
            with self.subTest(phone=phone):
                parsed = parse_invoice_text(
                    f'HOMEBIOGAS VENTURES LIMITED\nBILL TO\nSynthetic Applicant\n99000009\n{phone}\n'
                    'INVOICE 9001\nDATE 26/10/2026\nTOTAL 100.00\nBALANCE DUE 100.00', 1)
                self.assertTrue(parsed['customer_phone'])
                invoice = ParsedInvoice(customer_name=parsed['customer_name'], customer_id=parsed['customer_id'],
                                        customer_phone=parsed['customer_phone'])
                self.assertFalse(_exact_invoice_identity_match(invoice, farmer))
                farmer.primary_phone = '254798765432'
                self.assertTrue(_exact_invoice_identity_match(invoice, farmer))
                farmer.primary_phone = '254712345678'


@override_settings(TIME_ZONE='Africa/Nairobi')
class PortalSheetTimestampTests(TestCase):
    @patch('core.services.sheets.GoogleSheetsService.get_instance')
    def test_publication_formats_nairobi_time_across_the_utc_date_boundary(self, sheets):
        group = GroupSheetConfiguration.objects.create(group_id='synthetic-zone-audit',
            sheet_id='synthetic-local-sheet', enabled=True,
            workflow={'type': 'jawabu_homebiogas', 'master_sync_enabled': True,
                      'master_sheet_name': 'Master Data', 'master_header_row': 1, 'master_data_start_row': 2})
        farmer = JawabuFarmerMaster.objects.create(group_configuration=group, customer_name='Synthetic Applicant',
                                                   national_id='99000009', primary_phone='254712345678')
        sheet = FakeMasterDataSheet(['No.', 'Customer Name', 'Last Updated At'])
        sheet.values = [['No.', 'Customer Name', 'Last Updated At']]
        sheets.return_value = FakeJawabuService(sheet)
        frozen = datetime(2026, 10, 25, 22, 15, tzinfo=datetime_timezone.utc)
        with patch('core.services.jawabu_pipeline.timezone.now', return_value=frozen):
            self.assertTrue(sync_farmer_to_master_sheet(farmer))
        self.assertEqual(sheet.values[1][sheet.values[0].index('Last Updated At')], '26-Oct-2026 01:15')
