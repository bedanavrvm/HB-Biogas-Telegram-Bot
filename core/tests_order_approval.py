from datetime import datetime, timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from core.models import GroupSheetConfiguration, MediaAttachment, OrderApprovalUpdate
from core.services.order_approval import (
    SheetMatch,
    TelegramMediaItem,
    UploadedFileItem,
    GoogleDriveMediaStorage,
    clean_form_fields,
    collect_order_approval_uploaded_files,
    create_order_approval_form_token,
    create_order_approval_start_param,
    decode_order_approval_start_param,
    create_order_approval_row,
    find_order_approval_matches,
    format_order_success_reply,
    handle_order_approval_message,
    handle_order_webapp_command,
    lookup_order_approval_form_record,
    looks_like_non_order_command,
    order_approval_fields_fingerprint,
    parse_order_approval_message,
    process_order_approval_form_submission,
    store_media_for_order,
    store_uploaded_files_for_order,
    suggest_order_approval_form_records,
    update_order_approval_row,
    validate_order_approval_form_token,
    validate_order_approval_uploaded_files,
    validate_telegram_webapp_init_data,
    visible_field_changes,
)


class FakeSheet:
    def __init__(self, values):
        self.values = values
        self.batch_update_calls = []

    def get_all_values(self):
        return self.values

    def batch_update(self, data, raw=True):
        self.batch_update_calls.append((data, raw))


class FakeService:
    def __init__(self, values):
        self._sheet = FakeSheet(values)
        self.update_calls = []
        self.batch_update_calls = self._sheet.batch_update_calls

    def is_available(self):
        return True

    def _update_range(self, range_name, values, value_input_option='RAW'):
        self.update_calls.append((range_name, values, value_input_option))


class OrderApprovalParserTest(TestCase):
    def test_parser_extracts_supported_bro_labels(self):
        parsed = parse_order_approval_message(
            """
ID: 113650221
DATE VISITED: 09/05/2026
CUSTOMER NAME: PATRICK MWANGI MAINA
BRANCH: MURANGA
PRIMARY PHONE: 0740614990
SECONDARY PHONE:
COUNTY: MURANGA
SUB-COUNTY: KIHARU
LANDMARK: GITURI NEAR KAGANDA CENTRE
VISITED BY: JOHN & KIBINGE
HB STAFF: THOMAS
HB DEPOSIT: 5000
JBL DEPOSIT: 0
COMMENT: Approved
IMAB CREATED: CREATED
CUSTOMER NO: 15118
CREDIT ANALYSIS: Pending
FINAL DECISION: Under Review
""".strip()
        )

        self.assertEqual(parsed.id_number, '113650221')
        self.assertEqual(parsed.fields['date_visited'], '09/05/2026')
        self.assertEqual(parsed.fields['customer_name'], 'PATRICK MWANGI MAINA')
        self.assertEqual(parsed.fields['branch'], 'MURANGA')
        self.assertEqual(parsed.fields['primary_phone'], '254740614990')
        self.assertEqual(parsed.fields['county'], 'MURANGA')
        self.assertEqual(parsed.fields['sub_county'], 'KIHARU')
        self.assertEqual(parsed.fields['deposit_hb'], '5000')
        self.assertEqual(parsed.fields['deposit_jbl'], '0')
        self.assertEqual(parsed.fields['credit_analysis'], 'Pending')
        self.assertEqual(parsed.fields['final_decision'], 'Under Review')


class OrderApprovalSheetTest(TestCase):
    def _group_config(self):
        return MagicMock(
            group_id='-100222',
            sheet_id='sheet_123',
            workflow={
                'type': 'order_approval',
                'match_field': 'id_number',
                'search_sheet_names': ['Pending', '178'],
                'media_field': 'media_urls',
            },
        )

    def test_matching_finds_id_number_across_configured_tabs(self):
        pending = FakeService([
            ['ID NUMBER', 'CUSTOMER NAME', 'Media URLs'],
            ['111', 'Jane', ''],
        ])
        tab_178 = FakeService([
            ['CUSTOMER NAME', 'ID NUMBER', 'Media URLs'],
            ['Patrick', '113650221', ''],
        ])

        def get_service(sheet_id=None, sheet_name=None, sheet_schema=None):
            return {'Pending': pending, '178': tab_178}[sheet_name]

        with patch('core.services.order_approval.get_sheets_service', side_effect=get_service):
            matches = find_order_approval_matches(self._group_config(), '113650221')

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].sheet_name, '178')
        self.assertEqual(matches[0].row_number, 2)

    def test_suggestions_find_id_prefix_across_tabs(self):
        pending = FakeService([
            ['ORDER RECORD ID', 'ID NUMBER', 'CUSTOMER NAME', 'BRANCH', 'Media URLs'],
            ['JBL-7', '113650221', 'PATRICK', 'MURANGA', ''],
            ['JBL-8', '113777888', 'JANE', 'EMBU', ''],
        ])
        tab_178 = FakeService([
            ['CUSTOMER NAME', 'BRANCH', 'ID NUMBER', 'Media URLs'],
            ['PAUL', 'NYERI', '113999000', ''],
        ])

        with patch(
            'core.services.order_approval.get_sheets_service',
            side_effect=lambda sheet_id=None, sheet_name=None, sheet_schema=None: {
                'Pending': pending,
                '178': tab_178,
            }[sheet_name],
        ):
            result = suggest_order_approval_form_records(
                self._group_config(),
                '113',
                limit=2,
            )

        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(len(result['suggestions']), 2)
        self.assertEqual(result['suggestions'][0]['id_number'], '113650221')
        self.assertEqual(result['suggestions'][0]['customer_name'], 'PATRICK')
        self.assertEqual(result['suggestions'][0]['branch'], 'MURANGA')
        self.assertEqual(result['suggestions'][0]['order_record_id'], 'JBL-7')
        self.assertNotIn('sheet', result['suggestions'][0])
        self.assertNotIn('row', result['suggestions'][0])

    def test_suggestions_require_three_digits(self):
        result = suggest_order_approval_form_records(self._group_config(), '11')

        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'too_short')
        self.assertEqual(result['suggestions'], [])

    def test_matching_uses_configured_header_row(self):
        group_config = self._group_config()
        group_config.workflow = {
            'type': 'order_approval',
            'match_field': 'id_number',
            'search_sheet_names': ['Orders'],
            'media_field': 'media_urls',
            'header_row': 2,
        }
        orders = FakeService([
            ['ORDER APPROVAL FORM - BUSINESS RELATIONSHIP OFFICER', '', ''],
            ['DATE VISITED', 'CUSTOMER NAME', 'BRANCH', 'ID NUMBER', 'Media URLs'],
            ['', '', '', '', ''],
            ['23/05/2026', 'Patrick', 'Muranga', '113650221', ''],
        ])

        with patch('core.services.order_approval.get_sheets_service', return_value=orders):
            matches = find_order_approval_matches(group_config, '113650221')

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].sheet_name, 'Orders')
        self.assertEqual(matches[0].row_number, 4)
        self.assertEqual(matches[0].headers[3], 'ID NUMBER')

    def test_duplicate_matches_are_detected_across_tabs(self):
        pending = FakeService([
            ['ID NUMBER', 'CUSTOMER NAME', 'Media URLs'],
            ['113650221', 'Jane', ''],
        ])
        tab_178 = FakeService([
            ['ID NUMBER', 'CUSTOMER NAME', 'Media URLs'],
            ['113650221', 'Patrick', ''],
        ])

        with patch(
            'core.services.order_approval.get_sheets_service',
            side_effect=lambda sheet_id=None, sheet_name=None, sheet_schema=None: {
                'Pending': pending,
                '178': tab_178,
            }[sheet_name],
        ):
            matches = find_order_approval_matches(self._group_config(), '113650221')

        self.assertEqual(len(matches), 2)
        self.assertEqual(
            [(match.sheet_name, match.row_number) for match in matches],
            [('Pending', 2), ('178', 2)],
        )

    def test_update_writes_bro_fields_and_appends_media_urls(self):
        service = FakeService([])
        match = SheetMatch(
            sheet_name='Pending',
            row_number=4,
            headers=[
                'ID NUMBER',
                'DATE VISITED',
                'CUSTOMER NAME',
                'CONTACTS / PRIMARY',
                'Media URLs',
                'BRO COMMENT',
            ],
            row=['113650221', '', '', '', 'https://old.example/file', ''],
            service=service,
        )

        result = update_order_approval_row(
            match=match,
            workflow={'media_field': 'media_urls'},
            parsed_fields={
                'id_number': '113650221',
                'date_visited': '09/05/2026',
                'customer_name': 'PATRICK',
                'primary_phone': '0740614990',
                'comment': 'Approved',
            },
            media_links=['https://drive.example/new'],
        )

        self.assertTrue(result['success'])
        self.assertIn('date_visited', result['fields_updated'])
        self.assertEqual(service.update_calls, [])
        self.assertEqual(len(service.batch_update_calls), 1)
        self.assertEqual(
            service.batch_update_calls[0],
            (
                [
                    {
                        'range': 'A4:F4',
                        'values': [[
                            '113650221',
                            '09-May-2026',
                            'PATRICK',
                            '254740614990',
                            'https://old.example/file\nhttps://drive.example/new',
                            'Approved',
                        ]],
                    },
                ],
                True,
            ),
        )

    def test_update_requires_media_urls_column(self):
        service = FakeService([])
        match = SheetMatch(
            sheet_name='Pending',
            row_number=2,
            headers=['ID NUMBER', 'CUSTOMER NAME'],
            row=['113650221', 'Patrick'],
            service=service,
        )

        result = update_order_approval_row(
            match=match,
            workflow={'media_field': 'media_urls'},
            parsed_fields={'customer_name': 'PATRICK'},
            media_links=[],
        )

        self.assertFalse(result['success'])
        self.assertIn('Media URLs', result['error'])
        self.assertEqual(service.update_calls, [])
        self.assertEqual(service.batch_update_calls, [])

    def test_create_row_writes_to_pending_when_id_is_new(self):
        service = FakeService([
            [
                'ID NUMBER',
                'DATE VISITED',
                'CUSTOMER NAME',
                'CONTACTS / PRIMARY',
                'Media URLs',
                'BRO COMMENT',
            ],
            ['111', '01/05/2026', 'Existing', '', '', ''],
        ])

        with patch('core.services.order_approval.get_sheets_service', return_value=service):
            result = create_order_approval_row(
                group_config=self._group_config(),
                parsed_fields={
                    'id_number': '5655566',
                    'date_visited': '23/05/2026',
                    'customer_name': 'NEW CUSTOMER',
                    'primary_phone': '0712345678',
                    'comment': 'Created from form',
                },
                media_links=['https://drive.example/new'],
            )

        self.assertTrue(result['success'])
        self.assertEqual(result['sheet_name'], 'Pending')
        self.assertEqual(result['row_number'], 3)
        self.assertEqual(service.update_calls, [])
        self.assertEqual(len(service.batch_update_calls), 1)
        self.assertEqual(
            service.batch_update_calls[0],
            (
                [
                    {
                        'range': 'A3:F3',
                        'values': [[
                            '5655566',
                            '23-May-2026',
                            'NEW CUSTOMER',
                            '254712345678',
                            'https://drive.example/new',
                            'Created from form',
                        ]],
                    },
                ],
                True,
            ),
        )

    def test_create_row_writes_stable_order_record_id_when_column_exists(self):
        service = FakeService([
            ['ORDER RECORD ID', 'ID NUMBER', 'CUSTOMER NAME', 'Media URLs'],
        ])

        with patch('core.services.order_approval.get_sheets_service', return_value=service):
            result = create_order_approval_row(
                group_config=self._group_config(),
                parsed_fields={
                    'id_number': '5655566',
                    'customer_name': 'NEW CUSTOMER',
                },
                media_links=[],
            )

        self.assertTrue(result['success'])
        row_values = service.batch_update_calls[0][0][0]['values'][0]
        self.assertEqual(row_values[0], 'JBL-1')
        self.assertEqual(result['order_record_id'], 'JBL-1')
        self.assertEqual(row_values[1:], ['5655566', 'NEW CUSTOMER'])
        self.assertEqual(
            result['field_changes'][0],
            {
                'field': 'id_number',
                'header': 'ID NUMBER',
                'column': 'B',
                'action': 'added',
            },
        )
        self.assertEqual(result['field_changes'][-1]['header'], 'ORDER RECORD ID')
        self.assertEqual(result['field_changes'][-1]['action'], 'added')

    def test_create_row_uses_next_sequential_order_record_id(self):
        service = FakeService([
            ['ORDER RECORD ID', 'ID NUMBER', 'CUSTOMER NAME', 'Media URLs'],
            ['JBL-1', '111', 'EXISTING', ''],
            ['', '222', 'OLDER WITHOUT RECORD ID', ''],
        ])

        with patch('core.services.order_approval.get_sheets_service', return_value=service):
            result = create_order_approval_row(
                group_config=self._group_config(),
                parsed_fields={
                    'id_number': '5655566',
                    'customer_name': 'NEW CUSTOMER',
                },
                media_links=[],
            )

        self.assertTrue(result['success'])
        row_values = service.batch_update_calls[0][0][0]['values'][0]
        self.assertEqual(row_values[0], 'JBL-3')

    def test_update_adds_missing_order_record_id_without_overwriting_existing(self):
        service = FakeService([])
        match = SheetMatch(
            sheet_name='Orders',
            row_number=8,
            headers=['ORDER RECORD ID', 'ID NUMBER', 'BRO COMMENT', 'Media URLs'],
            row=['', '113650221', '', ''],
            service=service,
        )

        result = update_order_approval_row(
            match=match,
            workflow={'media_field': 'media_urls'},
            parsed_fields={'comment': 'Approved'},
            media_links=[],
        )

        self.assertTrue(result['success'])
        batch = service.batch_update_calls[0][0]
        self.assertEqual(batch[0]['range'], 'A8:A8')
        self.assertEqual(batch[1]['range'], 'C8:C8')
        self.assertEqual(batch[0]['values'][0][0], 'JBL-1')
        self.assertEqual(batch[1]['values'][0], ['Approved'])
        self.assertEqual(
            [change['header'] for change in result['field_changes']],
            ['BRO COMMENT', 'ORDER RECORD ID'],
        )
        self.assertEqual(result['order_record_id'], 'JBL-1')

    def test_staff_response_shows_only_changed_fields_without_column_letters(self):
        changes = [
            {
                'field': 'id_number',
                'header': 'ID NUMBER',
                'column': 'E',
                'action': 'confirmed',
            },
            {
                'field': 'customer_name',
                'header': 'CUSTOMER NAME',
                'column': 'C',
                'action': 'updated',
            },
            {
                'field': 'comment',
                'header': 'BRO COMMENT',
                'column': 'O',
                'action': 'cleared',
            },
            {
                'field': 'order_record_id',
                'header': 'ORDER RECORD ID',
                'column': 'A',
                'action': 'added',
            },
        ]

        self.assertEqual(
            [change['field'] for change in visible_field_changes(changes)],
            ['customer_name', 'comment'],
        )
        reply = format_order_success_reply(
            group_config=self._group_config(),
            id_number='113650221',
            order_record_id='JBL-7',
            customer_name='PATRICK',
            status='updated',
            field_changes=changes,
            files_stored=0,
            warnings=[],
        )

        self.assertIn('ENTRY UPDATED', reply)
        self.assertIn('Order record ID: JBL-7', reply)
        self.assertIn('- CUSTOMER NAME: updated', reply)
        self.assertIn('- BRO COMMENT: cleared', reply)
        self.assertNotIn('ID NUMBER: confirmed', reply)
        self.assertNotIn('ORDER RECORD ID: added', reply)
        self.assertNotIn('- C ', reply)
        self.assertNotIn('row ', reply.lower())

    def test_unchanged_blank_fields_are_not_reported_as_updates(self):
        service = FakeService([])
        match = SheetMatch(
            sheet_name='Orders',
            row_number=8,
            headers=['ID NUMBER', 'BRO COMMENT', 'Media URLs'],
            row=['113650221', '', ''],
            service=service,
        )

        result = update_order_approval_row(
            match=match,
            workflow={'media_field': 'media_urls'},
            parsed_fields={'id_number': '113650221', 'comment': ''},
            media_links=[],
        )

        self.assertTrue(result['success'])
        self.assertEqual(visible_field_changes(result['field_changes']), [])

    def test_create_row_uses_configured_header_row(self):
        group_config = self._group_config()
        group_config.workflow = {
            'type': 'order_approval',
            'match_field': 'id_number',
            'search_sheet_names': ['Orders'],
            'create_sheet_name': 'Orders',
            'media_field': 'media_urls',
            'header_row': 2,
        }
        service = FakeService([
            ['ORDER APPROVAL FORM - BUSINESS RELATIONSHIP OFFICER', '', ''],
            ['DATE VISITED', 'CUSTOMER NAME', 'BRANCH', 'ID NUMBER', 'Media URLs'],
            ['', '', '', '', ''],
            ['', '', '', '', ''],
        ])

        with patch('core.services.order_approval.get_sheets_service', return_value=service):
            result = create_order_approval_row(
                group_config=group_config,
                parsed_fields={
                    'date_visited': '24/05/2026',
                    'customer_name': 'NEW CUSTOMER',
                    'branch': 'MURANGA',
                    'id_number': '5655566',
                },
                media_links=['https://drive.example/file'],
            )

        self.assertTrue(result['success'])
        self.assertEqual(result['sheet_name'], 'Orders')
        self.assertEqual(result['row_number'], 3)
        self.assertEqual(service.update_calls, [])
        self.assertEqual(len(service.batch_update_calls), 1)
        self.assertEqual(
            service.batch_update_calls[0],
            (
                [
                    {
                        'range': 'A3:E3',
                        'values': [[
                            '24-May-2026',
                            'NEW CUSTOMER',
                            'MURANGA',
                            '5655566',
                            'https://drive.example/file',
                        ]],
                    },
                ],
                True,
            ),
        )

    def test_lookup_existing_row_returns_form_fields(self):
        group_config = self._group_config()
        group_config.workflow = {
            'type': 'order_approval',
            'match_field': 'id_number',
            'search_sheet_names': ['Orders'],
            'media_field': 'media_urls',
            'header_row': 2,
        }
        service = FakeService([
            ['ORDER APPROVAL FORM - BUSINESS RELATIONSHIP OFFICER', '', ''],
            [
                'DATE VISITED',
                'CUSTOMER NAME',
                'BRANCH',
                'ID NUMBER',
                'COUNTY',
                'SUB-COUNTY',
                'FINAL DECISION',
                'Media URLs',
            ],
            [
                '24/05/2026',
                'PATRICK',
                'MURANGA',
                '113650221',
                'MURANGA',
                'KIHARU',
                'Under Review',
                '',
            ],
        ])

        with patch('core.services.order_approval.get_sheets_service', return_value=service):
            result = lookup_order_approval_form_record(group_config, '113650221')

        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'found')
        self.assertEqual(result['sheet'], 'Orders')
        self.assertEqual(result['row'], 3)
        self.assertEqual(result['fields']['date_visited'], '2026-05-24')
        self.assertEqual(result['fields']['branch'], 'MURANGA')
        self.assertEqual(result['fields']['county'], 'MURANGA')
        self.assertEqual(result['fields']['sub_county'], 'KIHARU')
        self.assertEqual(result['fields']['final_decision'], 'Under Review')
        self.assertEqual(result['order_record_id'], '')
        self.assertEqual(
            result['fingerprint'],
            order_approval_fields_fingerprint(result['fields']),
        )

    def test_form_cleaning_can_include_blank_fields_for_true_edit(self):
        fields = clean_form_fields(
            {
                'id_number': '113650221',
                'customer_name': '',
                'branch': '',
                'sub_county': '',
                'comment': 'Keep this',
            },
            include_blank_fields=True,
        )

        self.assertEqual(fields['id_number'], '113650221')
        self.assertEqual(fields['customer_name'], '')
        self.assertEqual(fields['branch'], '')
        self.assertEqual(fields['sub_county'], '')
        self.assertEqual(fields['comment'], 'Keep this')

    def test_form_cleaning_normalizes_contacts_to_254_format(self):
        fields = clean_form_fields({
            'id_number': '113650221',
            'primary_phone': '0740 614 990',
            'secondary_phone': '+254 712 345 678',
            'imab_created': 'CREATED',
        })

        self.assertEqual(fields['primary_phone'], '254740614990')
        self.assertEqual(fields['secondary_phone'], '254712345678')
        self.assertEqual(fields['imab_created'], 'Yes')

    def test_update_rejects_invalid_contact_number(self):
        service = FakeService([])
        match = SheetMatch(
            sheet_name='Orders',
            row_number=2,
            headers=['ID NUMBER', 'CONTACTS / PRIMARY', 'Media URLs'],
            row=['113650221', '', ''],
            service=service,
        )

        result = update_order_approval_row(
            match=match,
            workflow={'media_field': 'media_urls'},
            parsed_fields={'primary_phone': '12345'},
            media_links=[],
        )

        self.assertFalse(result['success'])
        self.assertIn('254XXXXXXXXX', result['error'])
        self.assertEqual(service.batch_update_calls, [])

    def test_lookup_converts_excel_serial_date_for_html_date_input(self):
        group_config = self._group_config()
        group_config.workflow = {
            'type': 'order_approval',
            'match_field': 'id_number',
            'search_sheet_names': ['Orders'],
            'media_field': 'media_urls',
            'header_row': 2,
        }
        service = FakeService([
            ['ORDER APPROVAL FORM - BUSINESS RELATIONSHIP OFFICER', '', ''],
            ['DATE VISITED', 'ID NUMBER', 'Media URLs'],
            ['46151', '113650221', ''],
        ])

        with patch('core.services.order_approval.get_sheets_service', return_value=service):
            result = lookup_order_approval_form_record(group_config, '113650221')

        self.assertEqual(result['fields']['date_visited'], '2026-05-09')

    def test_lookup_normalizes_existing_contact_numbers_to_254_format(self):
        group_config = self._group_config()
        group_config.workflow = {
            'type': 'order_approval',
            'match_field': 'id_number',
            'search_sheet_names': ['Orders'],
            'media_field': 'media_urls',
        }
        service = FakeService([
            ['ID NUMBER', 'CONTACTS / PRIMARY', 'CONTACTS / SECONDARY', 'Media URLs'],
            ['113650221', '0740 614 990', '+254 712 345 678', ''],
        ])

        with patch('core.services.order_approval.get_sheets_service', return_value=service):
            result = lookup_order_approval_form_record(group_config, '113650221')

        self.assertTrue(result['success'])
        self.assertEqual(result['fields']['primary_phone'], '254740614990')
        self.assertEqual(result['fields']['secondary_phone'], '254712345678')

    @patch('core.services.order_approval.store_uploaded_files_for_order')
    @patch('core.services.order_approval.find_order_approval_matches')
    def test_true_edit_requires_matching_loaded_context(
        self,
        mock_find_matches,
        mock_store_files,
    ):
        service = FakeService([])
        mock_store_files.return_value = MagicMock(
            links=[],
            stored_count=0,
            warnings=[],
        )
        mock_find_matches.return_value = [
            SheetMatch(
                sheet_name='Orders',
                row_number=7,
                headers=['ID NUMBER', 'CUSTOMER NAME', 'Media URLs'],
                row=['113650221', 'PATRICK', ''],
                service=service,
            )
        ]

        result = process_order_approval_form_submission(
            group_config=self._group_config(),
            fields={'id_number': '113650221', 'customer_name': ''},
            uploaded_files=[],
            sender='Agent',
            include_blank_fields=True,
            edit_context={
                'id_number': '113650221',
                'sheet': 'Orders',
                'row': '8',
                'fingerprint': order_approval_fields_fingerprint({
                    'id_number': '113650221',
                    'customer_name': 'PATRICK',
                }),
            },
        )

        self.assertFalse(result['success'])
        self.assertIn('Reload this customer ID', result['message'])
        self.assertEqual(service.update_calls, [])

    @patch('core.services.order_approval.store_uploaded_files_for_order')
    @patch('core.services.order_approval.find_order_approval_matches')
    def test_true_edit_rejects_stale_row_fingerprint(
        self,
        mock_find_matches,
        mock_store_files,
    ):
        service = FakeService([])
        mock_store_files.return_value = MagicMock(
            links=[],
            stored_count=0,
            warnings=[],
        )
        mock_find_matches.return_value = [
            SheetMatch(
                sheet_name='Orders',
                row_number=7,
                headers=['ID NUMBER', 'CUSTOMER NAME', 'Media URLs'],
                row=['113650221', 'PATRICK CHANGED', ''],
                service=service,
            )
        ]

        result = process_order_approval_form_submission(
            group_config=self._group_config(),
            fields={'id_number': '113650221', 'customer_name': 'PATRICK'},
            uploaded_files=[],
            sender='Agent',
            include_blank_fields=True,
            edit_context={
                'id_number': '113650221',
                'sheet': 'Orders',
                'row': '7',
                'fingerprint': order_approval_fields_fingerprint({
                    'id_number': '113650221',
                    'customer_name': 'PATRICK',
                }),
            },
        )

        self.assertFalse(result['success'])
        self.assertIn('Reload this customer ID', result['message'])
        self.assertEqual(service.update_calls, [])

    @patch('core.services.order_approval.store_uploaded_files_for_order')
    @patch('core.services.order_approval.find_order_approval_matches')
    def test_true_edit_can_correct_id_without_creating_new_row(
        self,
        mock_find_matches,
        mock_store_files,
    ):
        service = FakeService([])
        loaded_match = SheetMatch(
            sheet_name='Orders',
            row_number=7,
            headers=['ID NUMBER', 'CUSTOMER NAME', 'Media URLs'],
            row=['113650221', 'PATRICK', ''],
            service=service,
        )
        mock_find_matches.side_effect = [
            [loaded_match],
            [],
        ]
        mock_store_files.return_value = MagicMock(
            links=[],
            stored_count=0,
            warnings=[],
        )

        result = process_order_approval_form_submission(
            group_config=self._group_config(),
            fields={'id_number': '113650222', 'customer_name': 'PATRICK'},
            uploaded_files=[],
            sender='Agent',
            include_blank_fields=True,
            edit_context={
                'id_number': '113650221',
                'sheet': 'Orders',
                'row': '7',
                'fingerprint': order_approval_fields_fingerprint({
                    'id_number': '113650221',
                    'customer_name': 'PATRICK',
                }),
            },
        )

        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['id_number'], '113650222')
        self.assertEqual(service.batch_update_calls[0][0][0]['range'], 'A7:B7')
        self.assertEqual(service.batch_update_calls[0][0][0]['values'][0][0], '113650222')

    @patch('core.services.order_approval.store_uploaded_files_for_order')
    @patch('core.services.order_approval.find_order_approval_matches')
    def test_true_edit_rejects_corrected_id_that_exists_on_another_row(
        self,
        mock_find_matches,
        mock_store_files,
    ):
        service = FakeService([])
        loaded_match = SheetMatch(
            sheet_name='Orders',
            row_number=7,
            headers=['ID NUMBER', 'CUSTOMER NAME', 'Media URLs'],
            row=['113650221', 'PATRICK', ''],
            service=service,
        )
        conflicting_match = SheetMatch(
            sheet_name='Orders',
            row_number=9,
            headers=['ID NUMBER', 'CUSTOMER NAME', 'Media URLs'],
            row=['113650222', 'OTHER CUSTOMER', ''],
            service=service,
        )
        mock_find_matches.side_effect = [
            [loaded_match],
            [conflicting_match],
        ]
        mock_store_files.return_value = MagicMock(
            links=[],
            stored_count=0,
            warnings=[],
        )

        result = process_order_approval_form_submission(
            group_config=self._group_config(),
            fields={'id_number': '113650222', 'customer_name': 'PATRICK'},
            uploaded_files=[],
            sender='Agent',
            include_blank_fields=True,
            edit_context={
                'id_number': '113650221',
                'sheet': 'Orders',
                'row': '7',
                'fingerprint': order_approval_fields_fingerprint({
                    'id_number': '113650221',
                    'customer_name': 'PATRICK',
                }),
            },
        )

        self.assertFalse(result['success'])
        self.assertEqual(result['status'], 'duplicate')
        self.assertIn('already uses this customer ID', result['message'])
        self.assertEqual(service.batch_update_calls, [])


class OrderApprovalMediaTest(TestCase):
    def test_webapp_upload_slots_are_collected_with_categories(self):
        from django.utils.datastructures import MultiValueDict

        files = MultiValueDict({
            'id_photos': [
                SimpleUploadedFile('front.jpg', b'id-front', content_type='image/jpeg'),
                SimpleUploadedFile('back.jpg', b'id-back', content_type='image/jpeg'),
            ],
            'laf_documents': [
                SimpleUploadedFile('laf.pdf', b'laf', content_type='application/pdf'),
            ],
            'other_files': [
                SimpleUploadedFile('receipt.pdf', b'receipt', content_type='application/pdf'),
            ],
        })

        uploads = collect_order_approval_uploaded_files(files)

        self.assertEqual(
            [upload.file_type for upload in uploads],
            ['id_photo', 'id_photo', 'laf_doc', 'other_file'],
        )
        self.assertEqual([upload.file.name for upload in uploads], [
            'front.jpg',
            'back.jpg',
            'laf.pdf',
            'receipt.pdf',
        ])

    @override_settings(
        ORDER_APPROVAL_MAX_FILES_PER_SLOT=2,
        ORDER_APPROVAL_MAX_TOTAL_UPLOAD_MB=1,
    )
    def test_webapp_upload_batch_limits_are_validated(self):
        from django.utils.datastructures import MultiValueDict

        files = MultiValueDict({
            'id_photos': [
                SimpleUploadedFile('front.jpg', b'a', content_type='image/jpeg'),
                SimpleUploadedFile('back.jpg', b'b', content_type='image/jpeg'),
                SimpleUploadedFile('extra.jpg', b'c', content_type='image/jpeg'),
            ],
            'laf_documents': [
                SimpleUploadedFile(
                    'large.pdf',
                    b'x' * (1024 * 1024 + 1),
                    content_type='application/pdf',
                ),
            ],
        })

        errors = validate_order_approval_uploaded_files(files)

        self.assertIn('ID photos supports at most 2 file(s).', errors)
        self.assertIn('Total upload size is too large.', " ".join(errors))

    def test_oversize_attachment_is_skipped_and_audited(self):
        group_config = MagicMock(group_id='-100222')
        order_update = OrderApprovalUpdate.objects.create(
            group_id='-100222',
            sheet_id='sheet_123',
            id_number='113650221',
        )

        with override_settings(MEDIA_MAX_FILE_SIZE_MB=20):
            result = store_media_for_order(
                group_config=group_config,
                message_data={'message_id': 77},
                sender='Agent',
                received_at=datetime(2026, 5, 9, tzinfo=dt_timezone.utc),
                media_items=[
                    TelegramMediaItem(
                        telegram_file_id='file_1',
                        file_type='document',
                        original_filename='large.pdf',
                        mime_type='application/pdf',
                        size=21 * 1024 * 1024,
                    )
                ],
                business_key_value='113650221',
                order_update=order_update,
            )

        self.assertEqual(result.stored_count, 0)
        self.assertEqual(result.skipped_count, 1)
        attachment = MediaAttachment.objects.get()
        self.assertEqual(attachment.upload_status, 'skipped')
        self.assertEqual(attachment.business_key_type, 'id_number')
        self.assertEqual(attachment.business_key_value, '113650221')

    @override_settings(MEDIA_MAX_FILE_SIZE_MB=20, MEDIA_STORAGE_PROVIDER='google_drive')
    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_web_uploads_use_jbl_id_based_file_names(self, mock_storage_cls):
        group_config = MagicMock(group_id='-100222')
        storage = MagicMock()
        storage.upload.side_effect = [
            ('drive_1', 'https://drive.example/id-front'),
            ('drive_2', 'https://drive.example/laf'),
            ('drive_3', 'https://drive.example/other'),
        ]
        mock_storage_cls.return_value = storage

        result = store_uploaded_files_for_order(
            group_config=group_config,
            uploaded_files=[
                UploadedFileItem(
                    SimpleUploadedFile(
                        'front image.JPG',
                        b'id-front',
                        content_type='image/jpeg',
                    ),
                    'id_photo',
                ),
                UploadedFileItem(
                    SimpleUploadedFile(
                        'signed-laf.pdf',
                        b'laf',
                        content_type='application/pdf',
                    ),
                    'laf_doc',
                ),
                UploadedFileItem(
                    SimpleUploadedFile(
                        'receipt #1.PDF',
                        b'other',
                        content_type='application/pdf',
                    ),
                    'other_file',
                ),
            ],
            sender='Agent',
            received_at=datetime(2026, 5, 9, tzinfo=dt_timezone.utc),
            business_key_value='113650221',
        )

        self.assertEqual(result.stored_count, 3)
        filenames = [
            call.kwargs['filename']
            for call in storage.upload.call_args_list
        ]
        self.assertEqual(filenames, [
            '2026-05-09 KYC ID-113650221 01.jpg',
            '2026-05-09 LAF Biogas ID-113650221 01.pdf',
            '2026-05-09 FILE Biogas ID-113650221 01.pdf',
        ])
        self.assertTrue(
            all(
                hasattr(call.kwargs['data'], 'read')
                for call in storage.upload.call_args_list
            )
        )

    @override_settings(MEDIA_MAX_FILE_SIZE_MB=20, MEDIA_STORAGE_PROVIDER='google_drive')
    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_later_distinct_upload_continues_file_sequence(self, mock_storage_cls):
        group_config = MagicMock(group_id='-100222')
        storage = MagicMock()
        storage.upload.side_effect = [
            ('drive_1', 'https://drive.example/front'),
            ('drive_2', 'https://drive.example/back'),
        ]
        mock_storage_cls.return_value = storage

        store_uploaded_files_for_order(
            group_config=group_config,
            uploaded_files=[
                UploadedFileItem(
                    SimpleUploadedFile(
                        'front.jpg',
                        b'id-front',
                        content_type='image/jpeg',
                    ),
                    'id_photo',
                )
            ],
            sender='Agent',
            received_at=datetime(2026, 5, 9, tzinfo=dt_timezone.utc),
            business_key_value='113650221',
        )
        store_uploaded_files_for_order(
            group_config=group_config,
            uploaded_files=[
                UploadedFileItem(
                    SimpleUploadedFile(
                        'back.jpg',
                        b'id-back',
                        content_type='image/jpeg',
                    ),
                    'id_photo',
                )
            ],
            sender='Agent',
            received_at=datetime(2026, 5, 9, tzinfo=dt_timezone.utc),
            business_key_value='113650221',
        )

        filenames = [
            call.kwargs['filename']
            for call in storage.upload.call_args_list
        ]
        self.assertEqual(filenames, [
            '2026-05-09 KYC ID-113650221 01.jpg',
            '2026-05-09 KYC ID-113650221 02.jpg',
        ])

    @override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='root_folder')
    def test_drive_folder_path_uses_group_year_month_and_id_folder(self):
        storage = GoogleDriveMediaStorage()
        storage.ensure_child_folder = MagicMock(
            side_effect=['group_folder', 'year_folder', 'month_folder', 'id_folder']
        )
        group_config = MagicMock(
            display_name='Order Approval Group',
            group_id='-100222',
            metadata={},
            workflow={},
        )

        folder_id = storage.ensure_folder_path(
            '113650221',
            datetime(2026, 5, 9, tzinfo=dt_timezone.utc),
            group_config,
        )

        self.assertEqual(folder_id, 'id_folder')
        self.assertEqual(
            [call.args for call in storage.ensure_child_folder.call_args_list],
            [
                ('root_folder', 'Order Approval Group'),
                ('group_folder', '2026'),
                ('year_folder', 'May'),
                ('month_folder', 'ID_113650221'),
            ],
        )

    @override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='root_folder')
    def test_drive_folder_path_can_override_group_folder_from_workflow(self):
        storage = GoogleDriveMediaStorage()
        storage.ensure_child_folder = MagicMock(
            side_effect=['group_folder', 'year_folder', 'month_folder', 'id_folder']
        )
        group_config = MagicMock(
            display_name='Old Group Name',
            group_id='-100222',
            metadata={},
            workflow={'media_root_folder': 'BRO Order Approvals'},
        )

        storage.ensure_folder_path(
            '113650221',
            datetime(2026, 5, 9, tzinfo=dt_timezone.utc),
            group_config,
        )

        self.assertEqual(
            storage.ensure_child_folder.call_args_list[0].args,
            ('root_folder', 'BRO Order Approvals'),
        )

    @override_settings(MEDIA_MAX_FILE_SIZE_MB=20, MEDIA_STORAGE_PROVIDER='google_drive')
    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_reuploading_same_web_file_reuses_existing_drive_upload(self, mock_storage_cls):
        group_config = MagicMock(group_id='-100222')
        storage = MagicMock()
        storage.upload.return_value = ('drive_1', 'https://drive.example/file1')
        mock_storage_cls.return_value = storage
        uploaded = SimpleUploadedFile(
            'front.jpg',
            b'same-content',
            content_type='image/jpeg',
        )

        first = store_uploaded_files_for_order(
            group_config=group_config,
            uploaded_files=[uploaded],
            sender='Agent',
            received_at=datetime(2026, 5, 9, tzinfo=dt_timezone.utc),
            business_key_value='113650221',
        )
        second = store_uploaded_files_for_order(
            group_config=group_config,
            uploaded_files=[
                SimpleUploadedFile(
                    'front.jpg',
                    b'same-content',
                    content_type='image/jpeg',
                )
            ],
            sender='Agent',
            received_at=datetime(2026, 5, 9, tzinfo=dt_timezone.utc),
            business_key_value='113650221',
        )

        self.assertEqual(first.links, ['https://drive.example/file1'])
        self.assertEqual(second.links, ['https://drive.example/file1'])
        storage.upload.assert_called_once()
        attachments = list(MediaAttachment.objects.order_by('created_at'))
        self.assertEqual(len(attachments), 2)
        self.assertEqual(attachments[0].content_hash, attachments[1].content_hash)
        self.assertEqual(attachments[1].upload_error, 'Reused existing Drive upload.')


class OrderApprovalWebAppTest(TestCase):
    def _group_config(self):
        return MagicMock(
            group_id='-100222',
            sheet_id='sheet_123',
            workflow={
                'type': 'order_approval',
                'match_field': 'id_number',
                'search_sheet_names': ['Pending'],
                'media_field': 'media_urls',
            },
        )

    @override_settings(
        APP_BASE_URL='https://example.onrender.com',
        TELEGRAM_BOT_USERNAME='hb_biogas_cases_bot',
        ORDER_APPROVAL_MINI_APP_SHORT_NAME='orderapproval',
    )
    def test_order_command_returns_group_safe_mini_app_direct_link(self):
        result = handle_order_webapp_command(self._group_config(), '/order')

        self.assertEqual(result['status'], 'command')
        button = result['reply_markup']['inline_keyboard'][0][0]
        self.assertEqual(button['text'], 'Open Order Approval Form')
        self.assertNotIn('web_app', button)
        self.assertIn('url', button)
        self.assertIn(
            'https://t.me/hb_biogas_cases_bot/orderapproval?startapp=',
            button['url'],
        )
        start_param = button['url'].split('startapp=', 1)[1]
        payload = decode_order_approval_start_param(start_param)
        self.assertEqual(payload['group_id'], '-100222')
        valid, error = validate_order_approval_form_token(
            token=payload['token'],
            group_id='-100222',
        )
        self.assertTrue(valid, error)

    @override_settings(
        APP_BASE_URL='https://example.onrender.com',
        TELEGRAM_BOT_USERNAME='hb_biogas_cases_bot',
        ORDER_APPROVAL_MINI_APP_SHORT_NAME='',
    )
    def test_order_command_falls_back_to_signed_form_url_without_mini_app_short_name(self):
        result = handle_order_webapp_command(self._group_config(), '/order')

        button = result['reply_markup']['inline_keyboard'][0][0]
        self.assertNotIn('web_app', button)
        self.assertIn(
            'https://example.onrender.com/order-approval/?',
            button['url'],
        )
        self.assertIn('group_id=-100222', button['url'])
        self.assertIn('token=', button['url'])

    def test_order_approval_group_keeps_standard_group_command(self):
        from core.services.group_config import GroupRegistry

        GroupSheetConfiguration.objects.create(
            group_id='-100222',
            display_name='Order Approval',
            sheet_id='sheet_123',
            sheet_name='Pending',
            workflow={
                'type': 'order_approval',
                'match_field': 'id_number',
                'search_sheet_names': ['Pending'],
                'media_field': 'media_urls',
            },
        )
        GroupRegistry._instance = None

        result = handle_order_approval_message(
            group_config=self._group_config(),
            message_data={'message_id': 99},
            content='/group',
            sender='Agent',
            received_at=datetime(2026, 5, 23, tzinfo=dt_timezone.utc),
        )

        self.assertEqual(result['status'], 'command')
        self.assertIn('Group: -100222', result['reply_text'])
        self.assertIn('Sheet ID: sheet_123', result['reply_text'])

    def test_non_order_slash_command_is_not_parsed_as_missing_id(self):
        self.assertTrue(looks_like_non_order_command('/group'))
        self.assertTrue(looks_like_non_order_command('/health'))
        self.assertFalse(looks_like_non_order_command('/order'))
        self.assertFalse(looks_like_non_order_command('ID: 113650221'))

    @override_settings(TELEGRAM_BOT_TOKEN='token', API_REQUEST_TIMEOUT=5)
    @patch('core.api.views.requests.post')
    def test_telegram_reply_retries_without_markup_when_button_rejected(self, mock_post):
        from core.api.views import _post_telegram_reply

        rejected = MagicMock()
        rejected.ok = False
        rejected.status_code = 400
        rejected.text = 'Bad Request: BUTTON_TYPE_INVALID'
        accepted = MagicMock()
        accepted.ok = True
        mock_post.side_effect = [rejected, accepted]

        _post_telegram_reply(
            chat_id='-100222',
            message_data={'message_id': 99},
            text='FCA upload ready for review',
            reply_markup={'inline_keyboard': [[{'text': 'Open', 'web_app': {'url': 'https://bot.example.com/fca/review/'}}]]},
        )

        self.assertEqual(mock_post.call_count, 2)
        first_data = mock_post.call_args_list[0].kwargs['data']
        second_data = mock_post.call_args_list[1].kwargs['data']
        self.assertIn('reply_markup', first_data)
        self.assertNotIn('reply_markup', second_data)
        self.assertEqual(second_data['text'], 'FCA upload ready for review')
    @override_settings(ORDER_APPROVAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False)
    def test_webapp_auth_can_be_disabled_for_server_testing(self):
        is_valid, error, payload = validate_telegram_webapp_init_data('')

        self.assertTrue(is_valid)
        self.assertEqual(error, '')
        self.assertEqual(payload, {})

    def test_order_webapp_fields_exclude_internal_sheet_fields(self):
        from core.services.order_approval import ORDER_APPROVAL_WEBAPP_FIELDS

        self.assertNotIn('order_no', ORDER_APPROVAL_WEBAPP_FIELDS)
        self.assertNotIn('requisition_date', ORDER_APPROVAL_WEBAPP_FIELDS)

    def test_order_approval_form_renders(self):
        response = self.client.get('/api/order-approval/?group_id=-100222')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Order Approval')
        self.assertContains(response, 'name="id_number"')
        self.assertContains(response, 'name="branch"')
        self.assertContains(response, 'name="sub_county"')
        self.assertContains(response, 'name="final_decision"')
        self.assertNotContains(response, 'name="order_no"')
        self.assertNotContains(response, 'name="requisition_date"')
        self.assertContains(response, 'id="lookup-button"')
        self.assertContains(response, 'id="id-suggestions"')
        self.assertContains(response, 'name="write_blank_fields"')
        self.assertContains(response, 'name="edit_id_number"')
        self.assertContains(response, 'name="edit_fingerprint"')
        self.assertContains(response, 'name="id_photos"')
        self.assertContains(response, 'name="laf_documents"')
        self.assertContains(response, 'name="other_files"')
        self.assertContains(response, 'data-file-preview="id_photos"')
        self.assertContains(response, 'data-file-preview="laf_documents"')
        self.assertContains(response, 'data-preview-toggle="id_photos"')
        self.assertContains(response, 'Show thumbnails')
        self.assertContains(response, 'maxTotalUploadMb')
        self.assertContains(response, 'imagePreviewsEnabled')
        self.assertContains(response, 'phoneSafeUploadMode')
        self.assertContains(response, 'phoneSafeMaxFilesPerSlot = 2')
        self.assertContains(response, 'id="browser-fallback"')
        self.assertContains(response, 'class="form-section"')
        self.assertContains(response, 'class="section-toggle"')

    @override_settings(ORDER_APPROVAL_BRANCH_CHOICES='Biogas Unit, Muranga, Thika Road')
    def test_order_approval_form_uses_configured_branch_choices(self):
        response = self.client.get('/api/order-approval/?group_id=-100222')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<option value="BIOGAS UNIT">BIOGAS UNIT</option>', html=True)
        self.assertContains(response, '<option value="MURANGA">MURANGA</option>', html=True)
        self.assertContains(response, '<option value="THIKA ROAD">THIKA ROAD</option>', html=True)
        self.assertContains(response, 'id="draft-banner"')
        self.assertContains(response, 'id="entry-mode-panel"')
        self.assertContains(response, 'id="start-new-entry"')
        self.assertContains(response, 'id="review-dialog"')
        self.assertContains(response, 'data-chip-group')
        self.assertContains(response, 'tg.MainButton')
        self.assertContains(response, 'Enter ID number')
        self.assertContains(response, 'select up to ${effectiveMaxFilesPerSlot} files')
        self.assertNotContains(response, "input.removeAttribute('multiple')")
        self.assertContains(response, 'pattern="254[0-9]{9}"')
        self.assertContains(response, 'placeholder="254740614990"')
        self.assertNotContains(response, '${suggestion.sheet} row ${suggestion.row}')
        self.assertNotContains(response, 'Created ${payload.sheet}, row ${payload.row}')

    def test_order_approval_form_accepts_mini_app_start_param(self):
        start_param = create_order_approval_start_param('-100222')

        response = self.client.get(
            f'/api/order-approval/?tgWebAppStartParam={start_param}'
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="group_id" value="-100222"')
        self.assertContains(response, 'name="form_token" value=')

    def test_invalid_mini_app_start_param_is_ignored(self):
        self.assertEqual(decode_order_approval_start_param('not-valid***'), {})

        response = self.client.get('/api/order-approval/?tgWebAppStartParam=not-valid***')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="group_id" value=""')

    @override_settings(ORDER_APPROVAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False)
    @patch('core.api.views._post_telegram_reply')
    @patch('core.services.order_approval.process_order_approval_form_submission')
    @patch('core.services.group_config.GroupRegistry.get_instance')
    def test_webapp_submit_uses_order_approval_processor(
        self,
        mock_registry_get_instance,
        mock_process,
        mock_post_telegram_reply,
    ):
        registry = MagicMock()
        registry.get_group.return_value = self._group_config()
        mock_registry_get_instance.return_value = registry
        mock_process.return_value = {
            'success': True,
            'status': 'success',
            'message': 'Entry updated.',
            'id_number': '113650221',
            'order_record_id': 'JBL-7',
            'customer_name': 'PATRICK',
            'field_changes': [
                {
                    'field': 'customer_name',
                    'header': 'CUSTOMER NAME',
                    'column': 'C',
                    'action': 'updated',
                },
            ],
            'files_stored': 0,
        }

        response = self.client.post(
            '/api/order-approval/webapp/submit/',
            data={
                'group_id': '-100222',
                'id_number': '113650221',
                'customer_name': 'PATRICK',
                'branch': 'MURANGA',
                'sub_county': 'KIHARU',
                'final_decision': 'Under Review',
                'write_blank_fields': '1',
                'edit_id_number': '113650221',
                'edit_sheet': 'Orders',
                'edit_row': '4',
                'edit_fingerprint': 'abc123',
                'init_data': '',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        _, kwargs = mock_process.call_args
        self.assertEqual(kwargs['fields']['branch'], 'MURANGA')
        self.assertEqual(kwargs['fields']['sub_county'], 'KIHARU')
        self.assertEqual(kwargs['fields']['final_decision'], 'Under Review')
        self.assertTrue(kwargs['include_blank_fields'])
        self.assertEqual(kwargs['edit_context']['sheet'], 'Orders')
        self.assertEqual(kwargs['edit_context']['row'], '4')
        self.assertEqual(kwargs['edit_context']['fingerprint'], 'abc123')
        mock_post_telegram_reply.assert_called_once()
        self.assertEqual(mock_post_telegram_reply.call_args.kwargs['chat_id'], '-100222')
        telegram_text = mock_post_telegram_reply.call_args.kwargs['text']
        self.assertIn('ENTRY UPDATED', telegram_text)
        self.assertIn('Order record ID: JBL-7', telegram_text)
        self.assertIn('- CUSTOMER NAME: updated', telegram_text)
        self.assertNotIn('- C CUSTOMER NAME', telegram_text)
        self.assertNotIn('row 2', telegram_text)

    @override_settings(TELEGRAM_BOT_TOKEN='token', API_REQUEST_TIMEOUT=5)
    @patch('core.api.views.requests.post')
    def test_webapp_chat_notification_omits_empty_reply_target(self, mock_post):
        from core.api.views import _post_telegram_reply

        _post_telegram_reply(
            chat_id='-100222',
            message_data={},
            text='OK. Order approval updated from form.',
        )

        data = mock_post.call_args.kwargs['data']
        self.assertEqual(data['chat_id'], '-100222')
        self.assertNotIn('reply_to_message_id', data)

    @override_settings(ORDER_APPROVAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False)
    @patch('core.services.order_approval.lookup_order_approval_form_record')
    @patch('core.services.group_config.GroupRegistry.get_instance')
    def test_webapp_lookup_loads_existing_row(
        self,
        mock_registry_get_instance,
        mock_lookup,
    ):
        registry = MagicMock()
        registry.get_group.return_value = self._group_config()
        mock_registry_get_instance.return_value = registry
        mock_lookup.return_value = {
            'success': True,
            'status': 'found',
            'message': 'Existing entry loaded.',
            'order_record_id': 'JBL-7',
            'sheet': 'Orders',
            'row': 4,
            'fields': {
                'id_number': '113650221',
                'customer_name': 'PATRICK',
                'branch': 'MURANGA',
            },
        }

        response = self.client.post(
            '/api/order-approval/webapp/lookup/',
            data={
                'group_id': '-100222',
                'id_number': '113650221',
                'init_data': '',
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['status'], 'found')
        self.assertEqual(payload['order_record_id'], 'JBL-7')
        self.assertEqual(payload['fields']['branch'], 'MURANGA')

    @override_settings(ORDER_APPROVAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False)
    @patch('core.services.order_approval.suggest_order_approval_form_records')
    @patch('core.services.group_config.GroupRegistry.get_instance')
    def test_webapp_suggest_returns_id_matches(
        self,
        mock_registry_get_instance,
        mock_suggest,
    ):
        registry = MagicMock()
        registry.get_group.return_value = self._group_config()
        mock_registry_get_instance.return_value = registry
        mock_suggest.return_value = {
            'success': True,
            'status': 'ok',
            'message': '1 match(es) found.',
            'suggestions': [
                {
                    'id_number': '113650221',
                    'order_record_id': 'JBL-7',
                    'customer_name': 'PATRICK',
                    'branch': 'MURANGA',
                }
            ],
        }

        response = self.client.post(
            '/api/order-approval/webapp/suggest/',
            data={
                'group_id': '-100222',
                'id_prefix': '113',
                'init_data': '',
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['suggestions'][0]['id_number'], '113650221')
        self.assertEqual(payload['suggestions'][0]['order_record_id'], 'JBL-7')
        self.assertNotIn('sheet', payload['suggestions'][0])
        self.assertNotIn('row', payload['suggestions'][0])
        mock_suggest.assert_called_once()

    @override_settings(ORDER_APPROVAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False)
    @patch('core.services.order_approval.store_uploaded_files_for_order')
    @patch('core.services.order_approval.find_order_approval_matches')
    @patch('core.services.order_approval.get_sheets_service')
    @patch('core.services.group_config.GroupRegistry.get_instance')
    def test_webapp_submit_creates_row_when_id_is_new(
        self,
        mock_registry_get_instance,
        mock_get_sheets_service,
        mock_find_matches,
        mock_store_files,
    ):
        registry = MagicMock()
        registry.get_group.return_value = self._group_config()
        mock_registry_get_instance.return_value = registry
        mock_find_matches.return_value = []
        mock_store_files.return_value = MagicMock(
            links=[],
            stored_count=0,
            warnings=[],
        )
        service = FakeService([
            ['ID NUMBER', 'CUSTOMER NAME', 'Media URLs'],
        ])
        mock_get_sheets_service.return_value = service

        response = self.client.post(
            '/api/order-approval/webapp/submit/',
            data={
                'group_id': '-100222',
                'id_number': '5655566',
                'customer_name': 'NEW CUSTOMER',
                'init_data': '',
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['status'], 'created')
        self.assertEqual(payload['row'], 2)
        self.assertEqual(service.update_calls, [])
        self.assertEqual(
            service.batch_update_calls[0],
            (
                [
                    {
                        'range': 'A2:B2',
                        'values': [['5655566', 'NEW CUSTOMER']],
                    },
                ],
                True,
            ),
        )

    @patch('core.services.order_approval.process_order_approval_form_submission')
    @patch('core.services.group_config.GroupRegistry.get_instance')
    def test_webapp_submit_accepts_signed_group_form_token(
        self,
        mock_registry_get_instance,
        mock_process,
    ):
        registry = MagicMock()
        registry.get_group.return_value = self._group_config()
        mock_registry_get_instance.return_value = registry
        mock_process.return_value = {
            'success': True,
            'status': 'success',
            'message': 'Order approval updated.',
        }

        response = self.client.post(
            '/api/order-approval/webapp/submit/',
            data={
                'group_id': '-100222',
                'form_token': create_order_approval_form_token('-100222'),
                'id_number': '113650221',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])

    @override_settings(ORDER_APPROVAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False)
    @patch('core.services.order_approval.find_order_approval_matches')
    @patch('core.services.group_config.GroupRegistry.get_instance')
    def test_webapp_submit_rejects_invalid_phone_before_sheet_write(
        self,
        mock_registry_get_instance,
        mock_find_matches,
    ):
        registry = MagicMock()
        registry.get_group.return_value = self._group_config()
        mock_registry_get_instance.return_value = registry

        response = self.client.post(
            '/api/order-approval/webapp/submit/',
            data={
                'group_id': '-100222',
                'id_number': '5655566',
                'primary_phone': '12345',
                'init_data': '',
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('254XXXXXXXXX', response.json()['message'])
        mock_find_matches.assert_not_called()
