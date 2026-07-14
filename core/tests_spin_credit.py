import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import GroupSheetConfiguration, SpinCreditRequest
from core.services.spin_credit import classify_spin_message, classify_spin_progress_event, parse_spin_entry, process_spin_batch_export


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

    def test_parse_credit_analysis_assist_request(self):
        text = """Please assist with credit analysis for Mary Wambui
ID 22334455
Phone 0712345678
New customer requesting Ksh 45,000 to repay in 8 weeks
Code 001230"""
        parsed = parse_spin_entry(self.entry(text))

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.request_type, 'spin_crb')
        self.assertEqual(parsed.customer_name, 'MARY WAMBUI')
        self.assertEqual(parsed.national_id, '22334455')
        self.assertEqual(parsed.primary_phone, '254712345678')
        self.assertEqual(str(parsed.requested_amount), '45000')
        self.assertEqual(parsed.tenor.lower(), '8 weeks')
        self.assertEqual(parsed.code, '001230')

    def test_parse_do_spin_request(self):
        text = """Do spin for Peter Mwangi
ID 33445566
Phone no 0798765432
Existing client requesting 20k to repay with 6wks"""
        parsed = parse_spin_entry(self.entry(text))

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.request_type, 'spin')
        self.assertEqual(parsed.customer_name, 'PETER MWANGI')
        self.assertEqual(parsed.national_id, '33445566')
        self.assertEqual(parsed.primary_phone, '254798765432')
        self.assertEqual(str(parsed.requested_amount), '20000')

    def test_parse_need_crb_request(self):
        text = """Need CRB report for James Kariuki
ID 44556677
Phone 0722000000
Requesting 30,000 for 1 month"""
        parsed = parse_spin_entry(self.entry(text))

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.request_type, 'crb')
        self.assertEqual(parsed.customer_name, 'JAMES KARIUKI')
        self.assertEqual(parsed.national_id, '44556677')
        self.assertEqual(parsed.primary_phone, '254722000000')

    def test_classifies_keyword_only_message_as_incomplete(self):
        classification = classify_spin_message('Please send this to SPIN.')

        self.assertEqual(classification.category, 'incomplete')
        self.assertIn('spin', classification.keywords)
        self.assertIn('no customer identifier or loan details', classification.reason.lower())

    def test_classifies_customer_details_without_keyword_as_ambiguous(self):
        classification = classify_spin_message('Mary Wambui ID 22334455 phone 0712345678 requesting Ksh 45,000')

        self.assertEqual(classification.category, 'ambiguous')
        self.assertIn('national_id', classification.identifier_fields)
        self.assertIn('loan_amount', classification.loan_detail_fields)

    def test_classifies_unrelated_message_as_non_spin(self):
        classification = classify_spin_message('The team meeting has moved to 3pm.')

        self.assertEqual(classification.category, 'non_spin')

    def test_keyword_matching_allows_case_and_punctuation_variants(self):
        parsed = parse_spin_entry(self.entry('CREDIT-CHECK request for Alice Njeri ID 55667788 phone 0711000000'))

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.request_type, 'spin_crb')
        self.assertEqual(parsed.national_id, '55667788')

    def test_parse_nakuru_above_client_labelled_spin_request(self):
        text = """Morning, kindly assist me with the spin and credit analysis for the above client. A new client sells clothes at market
Code -654321
Name - Mary Wambui
ID-22334455
No-0712345678
Product-msingi
Amount-20k
Duration-8weeks"""
        parsed = parse_spin_entry(self.entry(text))

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.request_type, 'spin_crb')
        self.assertEqual(parsed.customer_name, 'MARY WAMBUI')
        self.assertEqual(parsed.national_id, '22334455')
        self.assertEqual(parsed.primary_phone, '254712345678')
        self.assertEqual(parsed.loan_product, 'Msingi')
        self.assertEqual(str(parsed.requested_amount), '20000')
        self.assertEqual(parsed.tenor.lower(), '8weeks')
        self.assertEqual(parsed.code, '654321')

    def test_parse_single_sentence_labelled_spin_request(self):
        text = (
            'Morning, kindly assist me with the spin and credit analysis for the above client. '
            'A new client sells clothes at market Code -654321 Name - Mary Wambui '
            'ID-22334455 No-0712345678 Product-msingi Amount-20k Duration-8weeks'
        )
        parsed = parse_spin_entry(self.entry(text))

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.request_type, 'spin_crb')
        self.assertEqual(parsed.customer_name, 'MARY WAMBUI')
        self.assertEqual(parsed.national_id, '22334455')
        self.assertEqual(parsed.primary_phone, '254712345678')
        self.assertEqual(parsed.loan_product, 'Msingi')
        self.assertEqual(str(parsed.requested_amount), '20000')
        self.assertEqual(parsed.tenor.lower(), '8weeks')
        self.assertEqual(parsed.code, '654321')

    def test_parse_east_multiline_share_spin_for_request(self):
        text = """Kindly share spin for
Duncan Wambugu
I'd no 27698225
Phone 0726843280/0740279575
He is a repeat client requesting for 20,000 in 8 weeks.
Code 877467"""
        parsed = parse_spin_entry(self.entry(text))

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.request_type, 'spin')
        self.assertEqual(parsed.customer_name, 'DUNCAN WAMBUGU')
        self.assertEqual(parsed.national_id, '27698225')
        self.assertEqual(parsed.primary_phone, '254726843280')
        self.assertEqual(parsed.secondary_phone, '254740279575')
        self.assertEqual(str(parsed.requested_amount), '20000')
        self.assertEqual(parsed.tenor.lower(), '8 weeks')
        self.assertEqual(parsed.code, '877467')

    def test_parse_limuru_spin_analysis_of_request(self):
        text = """Kindly share spin analysis of Paul Babu new customer mechanic based in Limuru, seeking msingi loan of ksh 20000 with a tenor of 12weeks, ID no 28400542
Ph no : 0712572050
Code 851904"""
        parsed = parse_spin_entry(self.entry(text))

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.request_type, 'spin_crb')
        self.assertEqual(parsed.customer_name, 'PAUL BABU')
        self.assertEqual(parsed.loan_product, 'Msingi')
        self.assertEqual(str(parsed.requested_amount), '20000')
        self.assertEqual(parsed.tenor.lower(), '12weeks')
        self.assertEqual(parsed.national_id, '28400542')
        self.assertEqual(parsed.primary_phone, '254712572050')
        self.assertEqual(parsed.code, '851904')

    def test_parse_west_compact_comma_separated_request(self):
        text = "kindly share spin for Mary Auma, she is a new customer requesting for micro-asset loan of 45,000 to be repaid in 6 months, id-27388611, p/no 0727458350, code-331507"
        parsed = parse_spin_entry(self.entry(text))

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.request_type, 'spin')
        self.assertEqual(parsed.customer_name, 'MARY AUMA')
        self.assertEqual(parsed.loan_product, 'Micro Asset')
        self.assertEqual(str(parsed.requested_amount), '45000')
        self.assertEqual(parsed.tenor.lower(), '6 months')
        self.assertEqual(parsed.national_id, '27388611')
        self.assertEqual(parsed.primary_phone, '254727458350')
        self.assertEqual(parsed.code, '331507')

    def test_parse_thika_compact_id_phn_request(self):
        text = "Kindly share spin for Selina Luta Id 11060375.phn 0722600894.New client located at Kayole requesting for a logbook loan of 150k to pay with 4months. Code 126572"
        parsed = parse_spin_entry(self.entry(text))

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.request_type, 'spin')
        self.assertEqual(parsed.customer_name, 'SELINA LUTA')
        self.assertEqual(parsed.loan_product, 'Logbook')
        self.assertEqual(str(parsed.requested_amount), '150000')
        self.assertEqual(parsed.tenor.lower(), '4months')
        self.assertEqual(parsed.national_id, '11060375')
        self.assertEqual(parsed.primary_phone, '254722600894')
        self.assertEqual(parsed.code, '126572')

    def test_payment_admin_message_is_not_spin_candidate(self):
        classification = classify_spin_message(
            'Kindly post this payment to Mary Wambui digital loan Id 22334455 phone number 0712345678'
        )

        self.assertEqual(classification.category, 'non_spin')

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
    def test_process_batch_reports_candidate_categories(self, mock_append):
        mock_append.return_value = {'success': True, 'row_numbers': [2], 'sheet_name': 'SPIN Legacy Batch'}
        config = GroupSheetConfiguration.objects.create(
            group_id='-100spincategories',
            display_name='JBL Branch',
            sheet_id='sheet-id',
            sheet_name='SPIN Requests',
            enabled=True,
            workflow={'type': 'spin_credit_analysis', 'header_row': 1},
        )
        export = """7/1/26, 09:00 - Catherine JBL: Please assist with credit analysis for Mary Wambui
ID 22334455
Phone 0712345678
Requesting Ksh 45,000 to repay in 8 weeks
7/1/26, 09:05 - Catherine JBL: Please send this to SPIN.
7/1/26, 09:07 - Catherine JBL: John Kamau ID 33445566 phone 0798765432 requesting Ksh 20,000
7/1/26, 09:10 - Catherine JBL: Good morning team"""

        result = process_spin_batch_export(config, export, telegram_message_id='102', sender='Tester')

        self.assertEqual(result['processed'], 1)
        self.assertEqual(result['spin_candidates'], 2)
        self.assertEqual(result['valid_requests'], 1)
        self.assertEqual(result['incomplete_requests'], 1)
        self.assertEqual(result['ambiguous_messages'], 1)
        self.assertEqual(result['skipped'], 1)

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
    @override_settings(SPIN_WEBAPP_REQUIRE_TELEGRAM_AUTH=False, ALLOWED_HOSTS=['testserver'])
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



    @override_settings(SPIN_WEBAPP_REQUIRE_TELEGRAM_AUTH=False, ALLOWED_HOSTS=['testserver'])
    @patch('core.api.views._post_telegram_reply')
    @patch('core.services.order_approval.store_uploaded_files_for_order')
    @patch('core.services.spin_credit.append_spin_requests_to_sheet')
    def test_form_submission_uploads_laf_docs_and_writes_media_urls(self, mock_append, mock_store, mock_reply):
        mock_append.return_value = {'success': True, 'row_numbers': [6]}
        mock_store.return_value = SimpleNamespace(links=['https://drive.google.com/file/d/laf-doc/view', 'https://drive.google.com/file/d/id-photo/view'], stored_count=2, skipped_count=0, warnings=[])
        GroupSheetConfiguration.objects.create(group_id='-100spinmedia', display_name='Nakuru SPIN Requests', sheet_id='sheet-id', sheet_name='SPIN Requests', enabled=True, workflow={'type': 'spin_credit_analysis', 'header_row': 1, 'branches': ['Nakuru', 'Embu']})
        from core.services.group_config import GroupRegistry
        GroupRegistry._instance = None
        response = self.client.post('/api/spin/submit/', data={
            'group_id': '-100spinmedia', 'request_type': 'spin_crb', 'customer_name': 'Peter Mwangi', 'national_id': '12345678',
            'primary_phone': '0712345678', 'requested_amount': '54000', 'tenor': '12 months', 'branch': 'Nakuru',
            'supporting_docs': SimpleUploadedFile('laf.pdf', b'%PDF-1.4 test', content_type='application/pdf'),
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['files_stored'], 2)
        self.assertEqual(response.json()['request_id'], 'SPIN-2026-0001')
        uploaded_files = mock_store.call_args.kwargs['uploaded_files']
        self.assertEqual(uploaded_files[0].file_type, 'laf_doc')
        record = SpinCreditRequest.objects.get(group_id='-100spinmedia')
        self.assertEqual(record.attachment_names, ['laf.pdf'])
        self.assertEqual(record.parsed_fields['branch'], 'Nakuru')
        self.assertEqual(record.parsed_fields['media_urls'], 'https://drive.google.com/file/d/laf-doc/view\nhttps://drive.google.com/file/d/id-photo/view')
        mock_append.assert_called_once()
        mock_reply.assert_called_once()
        reply_text = mock_reply.call_args.kwargs['text']
        self.assertIn('SPIN request received', reply_text)
        self.assertIn('The credit team can now review it', reply_text)
        self.assertNotIn('REQUEST SUBMITTED', reply_text)


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
            code='012340',
            parsed_fields={'media_urls': 'https://example.test/one\nhttps://example.test/two', 'branch': 'Nakuru'},
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
        code_idx = list(DEFAULT_FIELD_HEADERS.keys()).index('code')
        media_idx = list(DEFAULT_FIELD_HEADERS.keys()).index('media_urls')
        branch_idx = list(DEFAULT_FIELD_HEADERS.keys()).index('branch')
        self.assertEqual(rows[0][customer_name_idx], 'TEST FARMER')
        self.assertEqual(rows[0][requested_amount_idx], 25000.50)
        self.assertIsInstance(rows[0][requested_amount_idx], float)
        self.assertEqual(rows[0][request_month_idx], 'Jun-2026')
        self.assertEqual(rows[0][code_idx], "'012340")
        self.assertEqual(rows[0][media_idx], 'https://example.test/one\nhttps://example.test/two')
        self.assertEqual(rows[0][branch_idx], 'Nakuru')
        mock_sheet.format.assert_called()
        mock_sheet.conditional_format.assert_called()


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
            self.assertEqual(len(res_data['requests']), 1)

    @patch('core.services.spin_credit.validate_spin_telegram_webapp_init_data')
    def test_spin_form_requests_stays_in_current_group_for_analyst(self, mock_validate):
        import json
        mock_validate.return_value = (True, None, {'user': json.dumps({'username': 'analyst1', 'id': '12345'})})
        SpinCreditRequest.objects.create(
            group_id='-100other_spin',
            request_type='spin',
            customer_name='OTHER GROUP',
            national_id='99999999',
            primary_phone='254700000000',
            requested_amount=10000,
            tenor='6 weeks',
        )

        from django.test import override_settings
        with override_settings(SPIN_ANALYSTS=['analyst1']):
            response = self.client.get(f"/api/spin/requests/?group_id={self.config.group_id}&init_data=mock_data")

        self.assertEqual(response.status_code, 200)
        names = [item['customer_name'] for item in response.json()['requests']]
        self.assertIn('JOHN DOE', names)
        self.assertNotIn('OTHER GROUP', names)
            self.assertTrue(res_data['is_analyst'])
            self.assertEqual(len(res_data['requests']), 1)
            self.assertEqual(res_data['requests'][0]['customer_name'], 'JOHN DOE')

    def test_spin_form_renders_from_start_param(self):
        from core.services.spin_credit import create_spin_start_param

        start_param = create_spin_start_param(self.config.group_id)
        response = self.client.get(f'/api/spin/?tgWebAppStartParam={start_param}')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'spin-form-data')

    @patch('core.services.spin_credit.validate_spin_telegram_webapp_init_data')
    @patch('core.services.spin_credit.update_spin_request_in_sheet')
    def test_spin_review_update_saves_django_and_updates_existing_sheet_row(self, mock_update_sheet, mock_validate):
        mock_validate.return_value = (True, None, {'user': json.dumps({'username': 'officer1', 'id': '12345'})})
        mock_update_sheet.return_value = True
        self.record.import_status = 'review_needed'
        self.record.customer_name = ''
        self.record.national_id = ''
        self.record.primary_phone = ''
        self.record.requested_amount = None
        self.record.tenor = ''
        self.record.missing_fields = ['Customer Name', 'National ID', 'Primary Phone', 'Requested Amount', 'Tenor']
        self.record.parsed_fields = {'branch': 'Nakuru'}
        self.record.save()

        payload = {
            'request_id': str(self.record.id),
            'group_id': self.config.group_id,
            'init_data': 'mock_data',
            'fields': {
                'customer_name': 'Jane Wanjiku',
                'national_id': '23456789',
                'primary_phone': '0712345678',
                'requested_amount': '20k',
                'tenor': '8 weeks',
                'branch': 'Nakuru',
                'code': '0655290',
            },
        }
        response = self.client.post(
            '/api/spin/review/update/',
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'imported')
        self.assertTrue(result['sheet_synced'])
        self.record.refresh_from_db()
        self.assertEqual(self.record.import_status, 'imported')
        self.assertEqual(self.record.customer_name, 'JANE WANJIKU')
        self.assertEqual(self.record.primary_phone, '254712345678')
        self.assertEqual(str(self.record.requested_amount), '20000.00')
        self.assertEqual(self.record.code, '0655290')
        self.assertEqual(self.record.missing_fields, [])
        mock_update_sheet.assert_called_once()
        sheet_updates = mock_update_sheet.call_args.args[2]
        self.assertEqual(sheet_updates['parse_status'], 'Imported')
        self.assertEqual(sheet_updates['missing_fields'], '')
        self.assertEqual(sheet_updates['code'], "'0655290")

    @patch('core.services.spin_credit.validate_spin_telegram_webapp_init_data')
    @patch('core.services.spin_credit.update_spin_request_in_sheet')
    def test_spin_review_update_keeps_review_needed_when_required_fields_missing(self, mock_update_sheet, mock_validate):
        mock_validate.return_value = (True, None, {'user': json.dumps({'username': 'officer1', 'id': '12345'})})
        mock_update_sheet.return_value = True
        self.record.import_status = 'review_needed'
        self.record.national_id = ''
        self.record.primary_phone = ''
        self.record.missing_fields = ['National ID', 'Primary Phone']
        self.record.parsed_fields = {'branch': 'Nakuru'}
        self.record.save()

        payload = {
            'request_id': str(self.record.id),
            'group_id': self.config.group_id,
            'init_data': 'mock_data',
            'fields': {
                'customer_name': 'John Doe',
                'requested_amount': '15000',
                'tenor': '6 weeks',
            },
        }
        response = self.client.post(
            '/api/spin/review/update/',
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.record.refresh_from_db()
        self.assertEqual(self.record.import_status, 'review_needed')
        self.assertEqual(self.record.missing_fields, ['National ID', 'Primary Phone'])
        mock_update_sheet.assert_called_once()

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
