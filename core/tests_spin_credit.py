import json`r`nfrom datetime import datetime
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import GroupSheetConfiguration, SpinCreditRequest
from core.services.spin_credit import parse_spin_entry, process_spin_batch_export


class SpinCreditParserTestCase(TestCase):
    def entry(self, text, sender='John Wachira BRO JBL'):
        return {
            'content': text,
            'sender': sender,
            'received_at': timezone.make_aware(datetime(2026, 3, 16, 11, 7)),
        }

    def test_parse_labelled_spin_request(self):
        text = """IMG-20260316-WA0004.jpg (file attached)
Kindly share spin for Paul Ndegwa
Id 13452329
Phn 0724967956
Existing client in transport business requesting for 20k to pay with 6wks.
Code 856189"""
        parsed = parse_spin_entry(self.entry(text))

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.request_type, 'spin')
        self.assertEqual(parsed.customer_name, 'PAUL NDEGWA')
        self.assertEqual(parsed.national_id, '13452329')
        self.assertEqual(parsed.primary_phone, '254724967956')
        self.assertEqual(str(parsed.requested_amount), '20000')
        self.assertEqual(parsed.tenor.lower(), '6wks')
        self.assertEqual(parsed.customer_type, 'Existing')
        self.assertEqual(parsed.code, '856189')
        self.assertIn('IMG-20260316-WA0004.jpg', parsed.attachment_names)

    def test_parse_inline_spin_credit_analysis_request(self):
        text = """IMG-20260319-WA0052.jpg (file attached)
Kindly share a spin and credit analysis for Eunice Njeri kamande a new customer running a textiles business at Nairobi textiles requesting for a msingi loan of 10,000 to repay in 6 weeks. ID 25111100 phone number 0721111379"""
        parsed = parse_spin_entry(self.entry(text))

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.request_type, 'spin')
        self.assertEqual(parsed.customer_name, 'EUNICE NJERI KAMANDE')
        self.assertEqual(parsed.national_id, '25111100')
        self.assertEqual(parsed.primary_phone, '254721111379')
        self.assertEqual(str(parsed.requested_amount), '10000')
        self.assertEqual(parsed.tenor.lower(), '6 weeks')
        self.assertEqual(parsed.loan_product, 'Msingi')
        self.assertEqual(parsed.customer_type, 'New')

    def test_parse_analysis_only_multiline_request(self):
        text = """IMG-20260610-WA0001.jpg (file attached)
Kindly share analysis for Gladly mwihaki kamau
22026930-379124
0723000000
New client at thika has rental units requesting ksh 90,000 to pay in 6 months."""
        parsed = parse_spin_entry(self.entry(text))

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.request_type, 'spin')
        self.assertEqual(parsed.customer_name, 'GLADLY MWIHAKI KAMAU')
        self.assertEqual(parsed.raw_id_text, '22026930-379124')
        self.assertEqual(parsed.national_id, '22026930')
        self.assertEqual(parsed.primary_phone, '254723000000')
        self.assertEqual(str(parsed.requested_amount), '90000')
        self.assertEqual(parsed.tenor.lower(), '6 months')

    def test_parse_crb_report_request_with_secondary_phone(self):
        text = """IMG-20260317-WA0007.jpg (file attached)
Kindly share CRB report of Henry mburu nene
He is requesting for kilimo Biashara loan of 300000 for 12 months
Id 3096263
Phone:0727655443/0727000320
Code 171889/633893"""
        parsed = parse_spin_entry(self.entry(text))

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.request_type, 'crb')
        self.assertEqual(parsed.customer_name, 'HENRY MBURU NENE')
        self.assertEqual(parsed.national_id, '3096263')
        self.assertEqual(parsed.primary_phone, '254727655443')
        self.assertEqual(parsed.secondary_phone, '254727000320')
        self.assertEqual(str(parsed.requested_amount), '300000')
        self.assertEqual(parsed.tenor.lower(), '12 months')
        self.assertEqual(parsed.loan_product, 'Kilimo Biashara')

    @patch('core.services.spin_credit.append_spin_requests_to_sheet')
    def test_process_batch_saves_requests_and_marks_duplicates(self, mock_append):
        mock_append.return_value = {'success': True, 'row_numbers': [2, 3]}
        config = GroupSheetConfiguration.objects.create(
            group_id='-100spin',
            display_name='JBL Thika Road Branch',
            sheet_id='sheet-id',
            sheet_name='SPIN Requests',
            enabled=True,
            workflow={'type': 'spin_credit_analysis', 'header_row': 1},
        )
        export = """3/16/26, 11:07 - Catherine JBL: IMG-20260316-WA0004.jpg (file attached)
Kindly share spin for Paul Ndegwa
Id 13452329
Phn 0724967956
Existing client in transport business requesting for 20k to pay with 6wks.
Code 856189
3/16/26, 12:05 - Gladys JBL Accountant: This analysis has been shared
3/17/26, 09:27 - Serah JBL: IMG-20260317-WA0007.jpg (file attached)
Kindly share CRB report of Henry mburu nene
He is requesting for kilimo Biashara loan of 300000 for 12 months
Id 3096263
Phone:0727655443/0727000320
Code 171889/633893"""

        result = process_spin_batch_export(config, export, telegram_message_id='99', sender='Tester')
        self.assertEqual(result['status'], 'spin_batch_processed')
        self.assertEqual(result['processed'], 2)
        self.assertEqual(result['imported'], 2)
        self.assertEqual(SpinCreditRequest.objects.count(), 2)
        self.assertEqual(SpinCreditRequest.objects.filter(row_number__isnull=False).count(), 2)

        duplicate_result = process_spin_batch_export(config, export, telegram_message_id='100', sender='Tester')
        self.assertEqual(duplicate_result['duplicates'], 2)
        self.assertEqual(SpinCreditRequest.objects.count(), 2)



class SpinCreditMiniAppTestCase(TestCase):
    @override_settings(SPIN_WEBAPP_REQUIRE_TELEGRAM_AUTH=False)
    @patch('core.services.spin_credit.append_spin_requests_to_sheet')
    def test_form_submission_normalizes_phone_and_syncs_sheet(self, mock_append):
        mock_append.return_value = {'success': True, 'row_numbers': [5]}
        GroupSheetConfiguration.objects.create(
            group_id='-100spinform',
            display_name='Nakuru SPIN Requests',
            sheet_id='sheet-id',
            sheet_name='SPIN Requests',
            enabled=True,
            workflow={'type': 'spin_credit_analysis', 'header_row': 1},
        )
        from core.services.group_config import GroupRegistry
        GroupRegistry._instance = None

        payload = {
            'group_id': '-100spinform',
            'fields': {
                'request_type': 'crb',
                'customer_name': 'Mary Wanjiku',
                'national_id': '12345678',
                'primary_phone': '0712345678',
                'secondary_phone': '',
                'requested_amount': '54000',
                'tenor': '12 months',
                'loan_product': 'Msingi',
                'customer_type': 'New',
                'business_notes': 'Runs a retail shop',
            },
        }

        response = self.client.post(
            '/api/spin/submit/',
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['success'])
        record = SpinCreditRequest.objects.get()
        self.assertEqual(record.request_type, 'crb')
        self.assertEqual(record.primary_phone, '254712345678')
        self.assertEqual(record.row_number, 5)
        mock_append.assert_called_once()
        mock_reply.assert_called_once()

