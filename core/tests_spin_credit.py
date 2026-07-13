import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import GroupSheetConfiguration, SpinCreditRequest
from core.services.spin_credit import classify_spin_progress_event, parse_spin_entry, process_spin_batch_export


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
        self.assertEqual(parsed.request_type, 'spin_crb')
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
        self.assertEqual(parsed.request_type, 'spin_crb')
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
        mock_append.return_value = {'success': True, 'row_numbers': [2, 3], 'sheet_name': 'Legacy SPIN Imports'}
        config = GroupSheetConfiguration.objects.create(
            group_id='-100spin',
            display_name='JBL Thika Road Branch',
            sheet_id='sheet-id',
            sheet_name='SPIN Requests',
            enabled=True,
            workflow={'type': 'spin_credit_analysis', 'header_row': 1, 'legacy_batch_sheet_name': 'Legacy SPIN Imports'},
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
        self.assertEqual(mock_append.call_args.kwargs.get('sheet_name'), 'Legacy SPIN Imports')
        first_record = SpinCreditRequest.objects.order_by('request_datetime').first()
        self.assertEqual(first_record.sheet_name, 'Legacy SPIN Imports')
        self.assertEqual(first_record.parsed_fields.get('analysis_status'), 'Credit Analysis Shared')
        self.assertIn('This analysis has been shared', first_record.parsed_fields.get('analyst_response', ''))
        self.assertEqual(result['progress_events'], 1)
        self.assertEqual(result['linked_progress_events'], 1)

        duplicate_result = process_spin_batch_export(config, export, telegram_message_id='100', sender='Tester')
        self.assertEqual(duplicate_result['duplicates'], 2)
        self.assertEqual(SpinCreditRequest.objects.count(), 2)

    @patch('core.services.spin_credit.append_spin_requests_to_sheet')
    def test_process_batch_links_statement_and_analysis_progress_to_pending_request(self, mock_append):
        mock_append.return_value = {'success': True, 'row_numbers': [2], 'sheet_name': 'SPIN Legacy Batch'}
        config = GroupSheetConfiguration.objects.create(
            group_id='-100spinprogress',
            display_name='JBL Corporate Branch',
            sheet_id='sheet-id',
            sheet_name='SPIN Requests',
            enabled=True,
            workflow={'type': 'spin_credit_analysis', 'header_row': 1},
        )
        export = """3/16/26, 11:07 - Catherine JBL: Kindly share spin for Paul Ndegwa
Id 13452329
Phn 0724967956
Existing client in transport business requesting for 20k to pay with 6wks.
Code 856189
3/16/26, 13:30 - Gladys JBL Accountant: Kindly share statement
3/16/26, 14:00 - Catherine JBL: Mpesa statement shared. Code 142140
3/16/26, 14:08 - Gladys JBL Accountant: This analysis has been shared"""

        result = process_spin_batch_export(config, export, telegram_message_id='101', sender='Tester')

        self.assertEqual(result['processed'], 1)
        self.assertEqual(result['progress_events'], 3)
        self.assertEqual(result['linked_progress_events'], 3)
        record = SpinCreditRequest.objects.get(group_id='-100spinprogress')
        self.assertEqual(record.sheet_name, 'SPIN Legacy Batch')
        self.assertEqual(record.parsed_fields.get('analysis_status'), 'Credit Analysis Shared')
        response = record.parsed_fields.get('analyst_response', '')
        self.assertIn('Statement Requested', response)
        self.assertIn('Statement Shared', response)
        self.assertIn('Credit Analysis Shared', response)
        mock_append.assert_called_once()
        self.assertEqual(mock_append.call_args.kwargs.get('sheet_name'), 'SPIN Legacy Batch')


class SpinCreditMiniAppTestCase(TestCase):
    @override_settings(SPIN_WEBAPP_REQUIRE_TELEGRAM_AUTH=False)
    @patch('core.api.views._post_telegram_reply')
    @patch('core.services.spin_credit.append_spin_requests_to_sheet')
    def test_form_submission_normalizes_phone_and_syncs_sheet(self, mock_append, mock_reply):
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
                'request_type': 'spin_crb',
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
        self.assertEqual(record.request_type, 'spin_crb')
        self.assertEqual(record.primary_phone, '254712345678')
        self.assertEqual(record.row_number, 5)
        mock_append.assert_called_once()
        mock_reply.assert_called_once()



    @override_settings(SPIN_WEBAPP_REQUIRE_TELEGRAM_AUTH=False)
    @patch('core.api.views._post_telegram_reply')
    @patch('core.services.order_approval.store_uploaded_files_for_order')
    @patch('core.services.spin_credit.append_spin_requests_to_sheet')
    def test_form_submission_uploads_laf_docs_and_writes_media_urls(self, mock_append, mock_store, mock_reply):
        mock_append.return_value = {'success': True, 'row_numbers': [6]}
        mock_store.return_value = SimpleNamespace(links=['https://drive.google.com/file/d/laf-doc/view'], stored_count=1, skipped_count=0, warnings=[])
        GroupSheetConfiguration.objects.create(group_id='-100spinmedia', display_name='Nakuru SPIN Requests', sheet_id='sheet-id', sheet_name='SPIN Requests', enabled=True, workflow={'type': 'spin_credit_analysis', 'header_row': 1})
        from core.services.group_config import GroupRegistry
        GroupRegistry._instance = None
        response = self.client.post('/api/spin/submit/', data={
            'group_id': '-100spinmedia', 'request_type': 'spin_crb', 'customer_name': 'Peter Mwangi', 'national_id': '12345678',
            'primary_phone': '0712345678', 'requested_amount': '54000', 'tenor': '12 months',
            'supporting_docs': SimpleUploadedFile('laf.pdf', b'%PDF-1.4 test', content_type='application/pdf'),
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['files_stored'], 1)
        uploaded_files = mock_store.call_args.kwargs['uploaded_files']
        self.assertEqual(uploaded_files[0].file_type, 'laf_doc')
        record = SpinCreditRequest.objects.get(group_id='-100spinmedia')
        self.assertEqual(record.attachment_names, ['laf.pdf'])
        self.assertEqual(record.parsed_fields['media_urls'], 'https://drive.google.com/file/d/laf-doc/view')
        mock_append.assert_called_once()
        mock_reply.assert_called_once()


class SpinCreditSheetSyncTestCase(TestCase):
    @patch('core.services.spin_credit.get_sheets_service')
    def test_append_spin_requests_to_sheet_serializes_decimal(self, mock_get_sheets_service):
        from decimal import Decimal
        from unittest.mock import MagicMock
        from core.services.spin_credit import append_spin_requests_to_sheet

        # Create a mock sheet service and sheet
        mock_service = MagicMock()
        mock_sheet = MagicMock()
        mock_service.is_available.return_value = True
        mock_service._sheet = mock_sheet
        mock_get_sheets_service.return_value = mock_service

        from core.services.spin_credit import DEFAULT_FIELD_HEADERS
        # Mock sheet row values (headers)
        mock_sheet.row_values.return_value = list(DEFAULT_FIELD_HEADERS.values())
        
        # Create a config
        config = GroupSheetConfiguration.objects.create(
            group_id='-100spin_test',
            display_name='Nakuru SPIN Requests',
            sheet_id='sheet-id',
            sheet_name='SPIN Requests',
            enabled=True,
            workflow={
                'type': 'spin_credit_analysis',
                'header_row': 1,
            }
        )

        # Create a record with a Decimal amount
        record = SpinCreditRequest.objects.create(
            group_id='-100spin_test',
            request_type='spin',
            customer_name='TEST FARMER',
            requested_amount=Decimal('25000.50'),
            request_datetime=timezone.make_aware(datetime(2026, 6, 24, 14, 35)),
        )

        # Call append_spin_requests_to_sheet
        mock_sheet.append_rows.return_value = {
            'updates': {'updatedRange': 'Sheet1!A2:C2'}
        }
        result = append_spin_requests_to_sheet(config, [record])

        # Verify sheets service was used
        self.assertTrue(result['success'])
        mock_sheet.append_rows.assert_called_once()
        args, kwargs = mock_sheet.append_rows.call_args
        
        # Check that the list of rows does not contain a Decimal object
        rows = args[0]
        self.assertEqual(len(rows), 1)
        customer_name_idx = list(DEFAULT_FIELD_HEADERS.keys()).index('customer_name')
        requested_amount_idx = list(DEFAULT_FIELD_HEADERS.keys()).index('requested_amount')
        request_month_idx = list(DEFAULT_FIELD_HEADERS.keys()).index('request_month')
        self.assertEqual(rows[0][customer_name_idx], 'TEST FARMER')
        self.assertEqual(rows[0][requested_amount_idx], 25000.50)
        self.assertIsInstance(rows[0][requested_amount_idx], float)
        self.assertEqual(rows[0][request_month_idx], '2026-06-01')


class SpinCreditPortalTestCase(TestCase):
    def setUp(self):
        self.config = GroupSheetConfiguration.objects.create(
            group_id='-100spin_test',
            display_name='Nakuru SPIN Requests',
            sheet_id='sheet-id',
            sheet_name='SPIN Requests',
            enabled=True,
            workflow={
                'type': 'spin_credit_analysis',
                'header_row': 1,
            }
        )
        from core.services.group_config import GroupRegistry
        GroupRegistry._instance = None
        
        self.record = SpinCreditRequest.objects.create(
            group_id='-100spin_test',
            request_type='spin',
            customer_name='JOHN DOE',
            national_id='12345678',
            primary_phone='254712345678',
            requested_amount=15000,
            tenor='6 weeks',
            row_number=5,
        )

    def test_is_user_spin_analyst(self):
        from django.test import override_settings
        from core.services.spin_credit import is_user_spin_analyst
        
        with override_settings(SPIN_ANALYSTS=['analyst1', '12345']):
            self.assertTrue(is_user_spin_analyst({'username': 'analyst1', 'id': '99999'}))
            self.assertTrue(is_user_spin_analyst({'username': 'other', 'id': '12345'}))
            self.assertFalse(is_user_spin_analyst({'username': 'other', 'id': '99999'}))
            self.assertFalse(is_user_spin_analyst(None))

    @patch('core.services.spin_credit.validate_spin_telegram_webapp_init_data')
    def test_spin_form_requests_analyst(self, mock_validate):
        import json
        mock_validate.return_value = (True, None, {'user': json.dumps({'username': 'analyst1', 'id': '12345'})})
        
        from django.test import override_settings
        with override_settings(SPIN_ANALYSTS=['analyst1']):
            url = f"/api/spin/requests/?group_id={self.config.group_id}&init_data=mock_data"
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            res_data = response.json()
            self.assertTrue(res_data['success'])
            self.assertTrue(res_data['is_analyst'])
            self.assertEqual(len(res_data['requests']), 1)
            self.assertEqual(res_data['requests'][0]['customer_name'], 'JOHN DOE')

    @patch('core.services.spin_credit.validate_spin_telegram_webapp_init_data')
    @patch('core.api.views._post_telegram_reply')
    @patch('core.services.spin_credit.update_spin_request_in_sheet')
    @patch('core.services.spin_credit.upload_report')
    def test_spin_form_complete(self, mock_upload, mock_update_sheet, mock_tg_reply, mock_validate):
        import json
        mock_validate.return_value = (True, None, {'user': json.dumps({'username': 'analyst1', 'id': '12345'})})
        mock_upload.side_effect = lambda config, file, type, sender, nat_id: f"https://drive.google.com/{type}"
        mock_update_sheet.return_value = True

        from django.test import override_settings
        with override_settings(SPIN_ANALYSTS=['analyst1']):
            from django.core.files.uploadedfile import SimpleUploadedFile
            spin_file = SimpleUploadedFile("spin.pdf", b"spin_data", content_type="application/pdf")
            crb_file = SimpleUploadedFile("crb.pdf", b"crb_data", content_type="application/pdf")
            
            payload = {
                'request_id': str(self.record.id),
                'group_id': self.config.group_id,
                'init_data': 'mock_data',
                'spin_report': spin_file,
                'crb_report': crb_file,
            }
            response = self.client.post("/api/spin/complete/", payload)
            self.assertEqual(response.status_code, 200)
            res_data = response.json()
            self.assertTrue(res_data['success'])
            
            # Verify record updated
            self.record.refresh_from_db()
            self.assertEqual(self.record.import_status, 'completed')
            self.assertEqual(self.record.parsed_fields['spin_report_url'], 'https://drive.google.com/spin_report')
            self.assertEqual(self.record.parsed_fields['crb_report_url'], 'https://drive.google.com/crb_report')
            self.assertIn('analysis_completed_at', self.record.parsed_fields)

            mock_update_sheet.assert_called_once()
            mock_tg_reply.assert_called_once()
