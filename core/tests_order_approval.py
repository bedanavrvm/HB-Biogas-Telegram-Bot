from datetime import datetime, timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from core.models import GroupSheetConfiguration, MediaAttachment, OrderApprovalUpdate
from core.services.order_approval import (
    SheetMatch,
    TelegramMediaItem,
    clean_form_fields,
    create_order_approval_form_token,
    create_order_approval_row,
    find_order_approval_matches,
    handle_order_approval_message,
    handle_order_webapp_command,
    lookup_order_approval_form_record,
    looks_like_non_order_command,
    order_approval_fields_fingerprint,
    parse_order_approval_message,
    process_order_approval_form_submission,
    store_media_for_order,
    update_order_approval_row,
    validate_telegram_webapp_init_data,
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
        self.assertEqual(parsed.fields['primary_phone'], '0740614990')
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
                'COMMENT',
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
                            '0740614990',
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
                'COMMENT',
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
                            '0712345678',
                            'https://drive.example/new',
                            'Created from form',
                        ]],
                    },
                ],
                True,
            ),
        )

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
                'FINAL DECISION',
                'Media URLs',
            ],
            ['24/05/2026', 'PATRICK', 'MURANGA', '113650221', 'MURANGA', 'Under Review', ''],
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
        self.assertEqual(result['fields']['final_decision'], 'Under Review')
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
                'comment': 'Keep this',
            },
            include_blank_fields=True,
        )

        self.assertEqual(fields['id_number'], '113650221')
        self.assertEqual(fields['customer_name'], '')
        self.assertEqual(fields['branch'], '')
        self.assertEqual(fields['comment'], 'Keep this')

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
        self.assertIn('Reload this ID', result['message'])
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
        self.assertIn('Reload this ID', result['message'])
        self.assertEqual(service.update_calls, [])


class OrderApprovalMediaTest(TestCase):
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

    @override_settings(APP_BASE_URL='https://example.onrender.com')
    def test_order_command_returns_telegram_webapp_button(self):
        result = handle_order_webapp_command(self._group_config(), '/order')

        self.assertEqual(result['status'], 'command')
        button = result['reply_markup']['inline_keyboard'][0][0]
        self.assertEqual(button['text'], 'Open Order Approval Form')
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

    @override_settings(ORDER_APPROVAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False)
    def test_webapp_auth_can_be_disabled_for_server_testing(self):
        is_valid, error, payload = validate_telegram_webapp_init_data('')

        self.assertTrue(is_valid)
        self.assertEqual(error, '')
        self.assertEqual(payload, {})

    def test_order_approval_form_renders(self):
        response = self.client.get('/api/order-approval/?group_id=-100222')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Order Approval')
        self.assertContains(response, 'name="id_number"')
        self.assertContains(response, 'name="branch"')
        self.assertContains(response, 'name="final_decision"')
        self.assertContains(response, 'id="lookup-button"')
        self.assertContains(response, 'name="write_blank_fields"')
        self.assertContains(response, 'name="edit_id_number"')
        self.assertContains(response, 'name="edit_fingerprint"')
        self.assertContains(response, 'name="attachments"')

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
            'message': 'Order approval updated.',
            'sheet': 'Pending',
            'row': 2,
            'files_stored': 0,
        }

        response = self.client.post(
            '/api/order-approval/webapp/submit/',
            data={
                'group_id': '-100222',
                'id_number': '113650221',
                'customer_name': 'PATRICK',
                'branch': 'MURANGA',
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
        self.assertEqual(kwargs['fields']['final_decision'], 'Under Review')
        self.assertTrue(kwargs['include_blank_fields'])
        self.assertEqual(kwargs['edit_context']['sheet'], 'Orders')
        self.assertEqual(kwargs['edit_context']['row'], '4')
        self.assertEqual(kwargs['edit_context']['fingerprint'], 'abc123')
        mock_post_telegram_reply.assert_called_once()
        self.assertEqual(mock_post_telegram_reply.call_args.kwargs['chat_id'], '-100222')
        self.assertIn(
            'Order approval updated',
            mock_post_telegram_reply.call_args.kwargs['text'],
        )

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
            'message': 'Existing order row loaded.',
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
        self.assertEqual(payload['fields']['branch'], 'MURANGA')

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
