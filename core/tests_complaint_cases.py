import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch

from django.contrib import admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.admin import ComplaintCaseStaffMemberInline, TatTrackerStaffMemberInline
from core.models import (
    CaseUpdate,
    ComplaintCaseEvidence,
    ComplaintCaseSequence,
    ComplaintCaseStaffMember,
    GroupSheetConfiguration,
    ParsedMessage,
    ProcessedMessage,
    RawMessage,
)
from core.services.complaint_cases import (
    ComplaintCaseError,
    create_complaint_case,
    evidence_filename,
    list_cases,
    staff_actor_for_payload,
    update_case,
)
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

    def signed_init_data(self, telegram_id='100'):
        pairs = {'auth_date': str(int(time.time())), 'user': json.dumps({'id': int(telegram_id)})}
        check = '\n'.join(f'{key}={value}' for key, value in sorted(pairs.items()))
        secret = hmac.new(b'WebAppData', b'test-bot-token', hashlib.sha256).digest()
        pairs['hash'] = hmac.new(secret, check.encode('utf-8'), hashlib.sha256).hexdigest()
        return urlencode(pairs)

    def test_list_is_group_scoped(self):
        cases = list_cases(self.config)
        self.assertEqual([case['case_id'] for case in cases], ['CASE-1'])
        self.assertTrue(cases[0]['recorded_at'])

    def test_list_can_filter_by_exact_status_and_branch(self):
        self.case.branch_region = 'Nakuru'
        self.case.save(update_fields=['branch_region'])
        embu_case = self.create_case('-100100', 'CASE-3')
        embu_case.branch_region = 'Embu'
        embu_case.complaint_status = 'In Progress'
        embu_case.save(update_fields=['branch_region', 'complaint_status'])

        cases = list_cases(self.config, status='In Progress', branch='Embu')

        self.assertEqual([case['case_id'] for case in cases], ['CASE-3'])

    @override_settings(TELEGRAM_BOT_TOKEN='test-bot-token', SECURE_SSL_REDIRECT=False)
    def test_list_fragment_renders_authorized_cases(self):
        self.case.branch_region = 'Nakuru'
        self.case.save(update_fields=['branch_region'])
        embu_case = self.create_case('-100100', 'CASE-3')
        embu_case.branch_region = 'Embu'
        embu_case.save(update_fields=['branch_region'])

        response = self.client.post(
            reverse('complaint_cases_list_fragment'),
            {'group_id': self.group.group_id, 'branch': 'Nakuru', 'status': 'active'},
            HTTP_X_TELEGRAM_INIT_DATA=self.signed_init_data('100'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'complaint_cases/partials/case_list.html')
        self.assertContains(response, 'CASE-1')
        self.assertNotContains(response, 'CASE-3')

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

    def test_evidence_filename_uses_customer_id_when_available(self):
        self.case.customer_id = 'ID 123/456'
        self.case.save(update_fields=['customer_id'])

        self.assertEqual(evidence_filename(self.case, 'site photo.jpg', 1), 'CASE-ID_123456-01-site_photo.jpg')

    @patch('core.services.complaint_cases.append_parsed_message_to_sheet', return_value=True)
    def test_officer_can_create_an_auditable_case_once_with_a_retry_identifier(self, append_to_sheet):
        def mark_case_synced(case, **_kwargs):
            case.synced_to_sheets = True
            case.last_sync_error = ''
            case.save(update_fields=['synced_to_sheets', 'last_sync_error'])
            return True

        append_to_sheet.side_effect = mark_case_synced
        fields = {
            'client_request_id': 'create-complaint-001',
            'client_name': 'New Client',
            'customer_phone': '0712345678',
            'customer_id': '',
            'branch_region': 'Nakuru',
            'complaint_category': 'Product issue',
            'complaint_description': 'The unit requires a field visit.',
            'latitude': '-1.286389',
            'longitude': '36.817223',
        }

        first = create_complaint_case(self.config, self.actor('100'), fields, [])
        second = create_complaint_case(self.config, self.actor('100'), fields, [])

        case = ParsedMessage.objects.get(message_id=first['case']['case_id'])
        self.assertEqual(first['case']['case_id'], second['case']['case_id'])
        self.assertRegex(first['case']['case_id'], r'^CMP-\d{4}-001$')
        sequence = ComplaintCaseSequence.objects.get(group_id=self.config.group_id)
        self.assertEqual(sequence.next_number, 2)
        self.assertEqual(case.customer_phone, '254712345678')
        self.assertEqual(case.complaint_status, 'Open')
        self.assertEqual(case.source, 'complaint_mini_app')
        self.assertTrue(case.raw_message)
        self.assertEqual(CaseUpdate.objects.filter(parsed_message=case).count(), 1)
        append_to_sheet.assert_called_once()

    def test_new_case_requires_a_phone_or_customer_id(self):
        with self.assertRaisesMessage(ComplaintCaseError, 'phone number or customer ID'):
            create_complaint_case(
                self.config,
                self.actor('100'),
                {
                    'client_request_id': 'create-complaint-002',
                    'client_name': 'New Client',
                    'branch_region': 'Nakuru',
                    'complaint_category': 'Product issue',
                    'complaint_description': 'The unit requires a field visit.',
                },
                [],
            )

    @patch('core.services.complaint_cases.append_parsed_message_to_sheet', return_value=False)
    def test_new_case_keeps_the_audit_record_when_sheet_sync_is_deferred(self, append_to_sheet):
        result = create_complaint_case(
            self.config,
            self.actor('100'),
            {
                'client_request_id': 'create-complaint-003',
                'client_name': 'Deferred Sync Client',
                'customer_id': 'ID-300',
                'branch_region': 'Nakuru',
                'complaint_category': 'Product issue',
                'complaint_description': 'Create locally and retry the Sheet sync later.',
            },
            [],
        )

        case = ParsedMessage.objects.get(message_id=result['case']['case_id'])
        self.assertTrue(result['created'])
        self.assertFalse(result['synced_to_sheet'])
        self.assertEqual(case.case_updates.count(), 1)
        append_to_sheet.assert_called_once()


class ComplaintCaseMiniAppAssetTests(TestCase):
    def test_cards_show_recorded_date_and_create_form_has_required_fields(self):
        root = Path(__file__).resolve().parent
        template = (root / 'templates' / 'complaint_cases' / 'app.html').read_text(encoding='utf-8')
        script = (root / 'static' / 'miniapp' / 'complaint_cases.js').read_text(encoding='utf-8')

        for expected in ('class="app-top"', 'class="overview-strip"', 'class="tabs"', 'class="form-card"', 'id="complaintTabs"', 'data-view="create"', 'id="createCaseForm"', 'name="client_name"', 'name="customer_phone"', 'name="customer_id"', 'name="branch_region"', 'name="complaint_category"', 'name="complaint_description"', 'id="createEvidenceInput"', 'id="branchFilter"', 'data-status-filter="Open"', 'data-status-filter="In Progress"', 'data-status-filter="Closed"', 'id="captureLocationBtn" class="secondary" type="button"', 'htmx.org'):
            self.assertIn(expected, template)
        self.assertIn('<div class="location-actions" hidden><button id="captureLocationBtn"', template)
        self.assertIn('caseItem.recorded_at', script)
        self.assertIn("api('cases/create/'", script)
        self.assertIn('function callHref(phone)', script)
        self.assertIn('class="call-button"', script)
        self.assertIn('branch: state.branch', script)
        self.assertIn('function applyStatusFilter(status)', script)
        self.assertIn('function configureHtmx()', script)
        self.assertIn("htmx.ajax('POST', '/api/complaints/cases/fragment/'", script)


class ComplaintCaseAdminTests(TestCase):
    def test_group_admin_shows_only_the_staff_inline_for_its_workflow(self):
        complaint_group = GroupSheetConfiguration.objects.create(
            group_id='-100complaints', workflow={'type': 'case'}
        )
        tat_group = GroupSheetConfiguration.objects.create(
            group_id='-100tat', workflow={'type': 'tat_tracker'}
        )
        model_admin = admin.site._registry[GroupSheetConfiguration]
        request = RequestFactory().get('/admin/core/groupsheetconfiguration/')

        self.assertEqual(
            model_admin.get_inlines(request, complaint_group),
            [ComplaintCaseStaffMemberInline],
        )
        self.assertEqual(
            model_admin.get_inlines(request, tat_group),
            [TatTrackerStaffMemberInline],
        )


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
