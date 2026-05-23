from datetime import datetime, timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from core.models import MediaAttachment, OrderApprovalUpdate
from core.services.order_approval import (
    SheetMatch,
    TelegramMediaItem,
    find_order_approval_matches,
    parse_order_approval_message,
    store_media_for_order,
    update_order_approval_row,
)


class FakeSheet:
    def __init__(self, values):
        self.values = values

    def get_all_values(self):
        return self.values


class FakeService:
    def __init__(self, values):
        self._sheet = FakeSheet(values)
        self.update_calls = []

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
""".strip()
        )

        self.assertEqual(parsed.id_number, '113650221')
        self.assertEqual(parsed.fields['date_visited'], '09/05/2026')
        self.assertEqual(parsed.fields['customer_name'], 'PATRICK MWANGI MAINA')
        self.assertEqual(parsed.fields['primary_phone'], '0740614990')
        self.assertEqual(parsed.fields['deposit_hb'], '5000')
        self.assertEqual(parsed.fields['deposit_jbl'], '0')
        self.assertEqual(parsed.fields['credit_analysis'], 'Pending')


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
        self.assertEqual(service.update_calls[0], ('A4:A4', [['113650221']], 'RAW'))
        self.assertEqual(service.update_calls[1], ('B4:B4', [['09/05/2026']], 'USER_ENTERED'))
        self.assertEqual(service.update_calls[2][0], 'C4:F4')
        self.assertEqual(
            service.update_calls[2][1],
            [[
                'PATRICK',
                '0740614990',
                'https://old.example/file\nhttps://drive.example/new',
                'Approved',
            ]],
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
