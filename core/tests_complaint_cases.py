import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import (
    ComplaintCaseEvidence,
    ComplaintCaseStaffMember,
    GroupSheetConfiguration,
    ParsedMessage,
    ProcessedMessage,
    RawMessage,
)
from core.services.complaint_cases import ComplaintCaseError, list_cases, staff_actor_for_payload, update_case
from core.services.group_config import GroupConfig
from core.services.telegram_auth import validate_telegram_init_data


class ComplaintCaseServiceTests(TestCase):
    def setUp(self):
        self.group = GroupSheetConfiguration.objects.create(
            group_id='-100100', sheet_id='test-sheet', sheet_name='Complaints', workflow={'type': 'case'}
        )
        self.config = GroupConfig(group_id=self.group.group_id, sheet_id='test-sheet', sheet_name='Complaints', workflow={'type': 'case'})
        self.case = self.create_case('-100100', 'CASE-1')
        self.other_case = self.create_case('-100200', 'CASE-2')
        ComplaintCaseStaffMember.objects.create(
            group_configuration=self.group, name='Officer One', telegram_user_id='100', role='OFFICER'
        )
        ComplaintCaseStaffMember.objects.create(
            group_configuration=self.group, name='Manager One', telegram_user_id='200', role='MANAGER'
        )

    def create_case(self, group_id, message_id):
        raw = RawMessage.objects.create(telegram_message_id=message_id, content='raw complaint')
        processed = ProcessedMessage.objects.create(message_hash=f'hash-{message_id}', raw_message=raw)
        return ParsedMessage.objects.create(
            processed_message=processed, message_id=message_id, group_id=group_id,
            timestamp=timezone.now(), raw_message='raw complaint', customer_name='Client',
            customer_phone='0712345678', complaint_description='System is not working', complaint_status='Open',
        )

    def actor(self, telegram_id):
        return staff_actor_for_payload(self.config, {'user': json.dumps({'id': telegram_id})})

    def test_list_is_group_scoped(self):
        cases = list_cases(self.config)
        self.assertEqual([case['case_id'] for case in cases], ['CASE-1'])

    def test_officer_can_progress_case_once_with_retry_idempotency(self):
        actor = self.actor('100')
        fields = {'client_request_id': 'request-1', 'status': 'In Progress', 'resolution_text': 'Called the client.'}
        with patch('core.services.complaint_cases.get_sheets_service') as get_service:
            get_service.return_value.update_case_row.return_value = True
            update_case(self.config, actor, 'CASE-1', fields, [])
            update_case(self.config, actor, 'CASE-1', fields, [])
        self.case.refresh_from_db()
        self.assertEqual(self.case.complaint_status, 'In Progress')
        self.assertEqual(self.case.case_updates.count(), 1)

    def test_officer_cannot_close_case(self):
        with self.assertRaisesMessage(ComplaintCaseError, 'Only a case manager can close a complaint.'):
            update_case(
                self.config, self.actor('100'), 'CASE-1',
                {'client_request_id': 'request-2', 'status': 'Closed', 'resolution_text': 'Done'}, [],
            )

    def test_failed_drive_upload_is_recorded_without_losing_case_update(self):
        evidence = SimpleUploadedFile('photo.jpg', b'image-bytes', content_type='image/jpeg')
        with patch('core.services.complaint_cases.get_sheets_service') as get_service, patch(
            'core.services.complaint_cases.GoogleDriveMediaStorage.upload', side_effect=RuntimeError('offline')
        ):
            get_service.return_value.update_case_row.return_value = True
            update_case(
                self.config, self.actor('100'), 'CASE-1',
                {'client_request_id': 'request-3', 'status': 'Open', 'resolution_text': 'Photo collected'}, [evidence],
            )
        self.assertEqual(ComplaintCaseEvidence.objects.get().upload_status, 'failed')
        self.assertEqual(self.case.case_updates.count(), 1)


class TelegramInitDataTests(TestCase):
    @override_settings(TELEGRAM_BOT_TOKEN='test-bot-token')
    def test_valid_signed_init_data_is_accepted(self):
        pairs = {'auth_date': str(int(time.time())), 'user': json.dumps({'id': 1})}
        check = '\n'.join(f'{key}={value}' for key, value in sorted(pairs.items()))
        secret = hmac.new(b'WebAppData', b'test-bot-token', hashlib.sha256).digest()
        pairs['hash'] = hmac.new(secret, check.encode('utf-8'), hashlib.sha256).hexdigest()
        valid, error, payload = validate_telegram_init_data(urlencode(pairs))
        self.assertTrue(valid, error)
        self.assertEqual(payload['user'], json.dumps({'id': 1}))

    @override_settings(TELEGRAM_BOT_TOKEN='test-bot-token')
    def test_bad_or_expired_init_data_is_rejected(self):
        valid, _, _ = validate_telegram_init_data('auth_date=1&hash=bad')
        self.assertFalse(valid)
