import hashlib
import hmac
import json
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import (
    AccessGrant,
    CaseUpdate,
    ComplaintCaseEvidence,
    ComplaintCaseControl,
    ComplaintCaseEvent,
    ComplaintCaseImportBatch,
    ComplaintCaseImportItem,
    ComplaintCategory,
    ComplaintCaseSequence,
    GroupSheetConfiguration,
    ParsedMessage,
    ProcessedMessage,
    RawMessage,
    UserProfile,
)
from core.services.complaint_cases import (
    ComplaintCaseConflict,
    ComplaintCaseError,
    create_complaint_case,
    bootstrap_data,
    evidence_filename,
    list_cases,
    list_cases_page,
    reopen_case,
    resolve_case,
    staff_actor_for_payload,
    update_case,
    ensure_case_control,
)
from core.services.group_config import GroupConfig, GroupRegistry
from core.services.telegram_auth import validate_telegram_init_data


class ComplaintCaseServiceTests(TestCase):
    def setUp(self):
        self.group = GroupSheetConfiguration.objects.create(
            group_id='-100100', sheet_id='test-sheet', sheet_name='Complaints', workflow={'type': 'case'}
        )
        self.config = GroupConfig(group_id=self.group.group_id, sheet_id='test-sheet', sheet_name='Complaints', workflow={'type': 'case'})
        self.category = ComplaintCategory.objects.create(
            key='product-issue', label='Product issue', default_priority='normal', default_sla_hours=72,
        )
        self.case = self.create_case('-100100', 'CASE-1')
        self.other_case = self.create_case('-100200', 'CASE-2')
        User = get_user_model()
        self.officer = User.objects.create_user(username='officer-one', first_name='Officer', last_name='One', is_active=True)
        self.officer.set_unusable_password()
        self.officer.save(update_fields=['password'])
        UserProfile.objects.create(user=self.officer, telegram_id='100', telegram_username='officer_one')
        AccessGrant.objects.create(
            user=self.officer, workflow='complaint_cases', role='OFFICER',
            group_configuration=self.group,
        )
        self.manager = User.objects.create_user(username='manager-one', first_name='Manager', last_name='One', is_active=True)
        self.manager.set_unusable_password()
        self.manager.save(update_fields=['password'])
        UserProfile.objects.create(user=self.manager, telegram_id='200', telegram_username='manager_one')
        AccessGrant.objects.create(
            user=self.manager, workflow='complaint_cases', role='MANAGER',
            group_configuration=self.group,
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

    def test_legacy_status_filter_remains_compatible_but_branch_filter_is_ignored(self):
        self.case.branch_region = 'Nakuru'
        self.case.save(update_fields=['branch_region'])
        embu_case = self.create_case('-100100', 'CASE-3')
        embu_case.branch_region = 'Embu'
        embu_case.complaint_status = 'In Progress'
        embu_case.save(update_fields=['branch_region', 'complaint_status'])
        nakuru_case = self.create_case('-100100', 'CASE-4')
        nakuru_case.branch_region = 'Nakuru'
        nakuru_case.complaint_status = 'In Progress'
        nakuru_case.save(update_fields=['branch_region', 'complaint_status'])

        cases = list_cases(self.config, status='In Progress', branch='Embu')

        self.assertEqual({case['case_id'] for case in cases}, {'CASE-3', 'CASE-4'})

    def test_numbered_pages_are_limited_to_ten_and_report_totals(self):
        for index in range(11):
            self.create_case('-100100', f'CASE-PAGE-{index:02d}')

        first = list_cases_page(self.config, self.actor('100'), page=1, page_size=50)
        second = list_cases_page(self.config, self.actor('100'), page=2, page_size=50)

        self.assertEqual(len(first['items']), 10)
        self.assertEqual(len(second['items']), 2)
        self.assertEqual(first['pagination'], {'page': 1, 'pages': 2, 'total': 12, 'page_size': 10})
        self.assertEqual(first['start_index'], 1)
        self.assertEqual(second['start_index'], 11)
        self.assertFalse({item['case_id'] for item in first['items']} & {item['case_id'] for item in second['items']})

    def test_two_state_counts_are_group_scoped(self):
        self.case.complaint_status = 'In Progress'
        self.case.save(update_fields=['complaint_status'])
        control = ensure_case_control(self.case)
        control.sla_due_at = timezone.now() - timedelta(hours=1)
        control.save(update_fields=['sla_due_at'])

        counts = bootstrap_data(self.config, self.actor('100'))['counts']

        self.assertEqual(counts['pending'], 1)
        self.assertEqual(counts['resolved'], 0)
        self.assertEqual(counts['total'], 1)

    def test_branch_scoped_grant_still_sees_the_shared_group_queue(self):
        AccessGrant.objects.filter(user=self.officer, workflow='complaint_cases').update(branch='Nakuru')
        self.case.branch_region = 'Nakuru'
        self.case.save(update_fields=['branch_region'])
        embu_case = self.create_case('-100100', 'CASE-3')
        embu_case.branch_region = 'Embu'
        embu_case.save(update_fields=['branch_region'])

        cases = list_cases(self.config, self.actor('100'))

        self.assertEqual([case['case_id'] for case in cases], ['CASE-1', 'CASE-3'])

    def test_branch_scoped_officer_can_reopen_any_resolved_case_in_the_group(self):
        AccessGrant.objects.filter(user=self.officer, workflow='complaint_cases').update(branch='Nakuru')
        self.case.branch_region = 'Embu'
        self.case.complaint_status = 'Closed'
        self.case.save(update_fields=['branch_region', 'complaint_status'])

        with patch('core.services.complaint_cases.get_sheets_service') as get_service:
            get_service.return_value.update_case_row.return_value = True
            reopened = reopen_case(
                self.config, self.actor('100'), 'CASE-1',
                {'client_request_id': 'cross-branch-reopen-1', 'expected_revision': 1, 'reason': 'Resolution was insufficient.'},
            )

        self.assertEqual(reopened['status'], 'Pending')

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
        self.assertContains(response, 'CASE-3')

    @override_settings(TELEGRAM_BOT_TOKEN='test-bot-token', SECURE_SSL_REDIRECT=False)
    def test_list_endpoint_returns_numbered_pagination_contract(self):
        response = self.client.post(
            reverse('complaint_cases_list'),
            data=json.dumps({'group_id': self.group.group_id, 'status': 'all', 'page': 1}),
            content_type='application/json',
            HTTP_X_TELEGRAM_INIT_DATA=self.signed_init_data('100'),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['pagination']['page_size'], 10)
        self.assertEqual(payload['pagination']['total'], 1)
        self.assertEqual(payload['start_index'], 1)

    @override_settings(TELEGRAM_BOT_TOKEN='test-bot-token', SECURE_SSL_REDIRECT=False)
    def test_manager_resolves_and_any_officer_reopens_through_dedicated_endpoints(self):
        with patch('core.services.complaint_cases.get_sheets_service') as get_service:
            get_service.return_value.update_case_row.return_value = True
            resolved = self.client.post(
                reverse('complaint_cases_resolve', args=['CASE-1']),
                data=json.dumps({
                    'group_id': self.group.group_id, 'client_request_id': 'api-resolve-1',
                    'expected_revision': 1, 'resolution_text': 'Customer remedy completed.',
                }), content_type='application/json', HTTP_X_TELEGRAM_INIT_DATA=self.signed_init_data('200'),
            )
            reopened = self.client.post(
                reverse('complaint_cases_reopen', args=['CASE-1']),
                data=json.dumps({
                    'group_id': self.group.group_id, 'client_request_id': 'api-reopen-1',
                    'expected_revision': 2, 'reason': 'The remedy was incomplete.',
                }), content_type='application/json', HTTP_X_TELEGRAM_INIT_DATA=self.signed_init_data('100'),
            )

        self.assertEqual(resolved.status_code, 200)
        self.assertEqual(resolved.json()['case']['status'], 'Resolved')
        self.assertEqual(reopened.status_code, 200)
        self.assertEqual(reopened.json()['case']['status'], 'Pending')

    @override_settings(TELEGRAM_BOT_TOKEN='test-bot-token', SECURE_SSL_REDIRECT=False)
    def test_stale_resolution_response_includes_the_winning_resolution(self):
        with patch('core.services.complaint_cases.get_sheets_service') as get_service:
            get_service.return_value.update_case_row.return_value = True
            self.client.post(
                reverse('complaint_cases_resolve', args=['CASE-1']),
                data=json.dumps({
                    'group_id': self.group.group_id, 'client_request_id': 'api-winner-1',
                    'expected_revision': 1, 'resolution_text': 'Winning resolution.',
                }), content_type='application/json', HTTP_X_TELEGRAM_INIT_DATA=self.signed_init_data('200'),
            )
            conflict = self.client.post(
                reverse('complaint_cases_resolve', args=['CASE-1']),
                data=json.dumps({
                    'group_id': self.group.group_id, 'client_request_id': 'api-loser-1',
                    'expected_revision': 1, 'resolution_text': 'Losing draft.',
                }), content_type='application/json', HTTP_X_TELEGRAM_INIT_DATA=self.signed_init_data('200'),
            )

        self.assertEqual(conflict.status_code, 409)
        payload = conflict.json()
        self.assertEqual(payload['code'], 'revision_conflict')
        self.assertEqual(payload['current_case']['latest_resolution']['note'], 'Winning resolution.')

    def test_registry_resolves_a_group_added_after_the_initial_cache(self):
        GroupRegistry._instance = None
        GroupRegistry.get_instance()
        added = GroupSheetConfiguration.objects.create(
            group_id='-100101', sheet_id='later-sheet', sheet_name='Later', workflow={'type': 'case'},
        )

        resolved = GroupRegistry.get_instance().get_group(added.group_id)

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.group_id, added.group_id)
        self.assertEqual(resolved.sheet_id, 'later-sheet')

    def test_officer_cannot_mutate_a_pending_case(self):
        with self.assertRaisesMessage(ComplaintCaseError, 'does not permit this complaint transition'):
            update_case(self.config, self.actor('100'), 'CASE-1', {
                'client_request_id': 'request-1', 'status': 'Open',
                'resolution_text': 'Called the client.', 'expected_revision': 1,
            }, [])

    def test_officer_cannot_close_case(self):
        with self.assertRaisesMessage(ComplaintCaseError, 'does not permit this complaint transition'):
            resolve_case(
                self.config, self.actor('100'), 'CASE-1',
                {'client_request_id': 'request-2', 'expected_revision': 1, 'resolution_text': 'Done'}, [],
            )

    def test_failed_drive_upload_is_recorded_without_losing_case_update(self):
        evidence = SimpleUploadedFile('photo.jpg', b'\xff\xd8\xff\xe0synthetic-image', content_type='image/jpeg')
        with patch('core.services.complaint_cases.get_sheets_service') as get_service, patch(
            'core.services.complaint_cases.GoogleDriveMediaStorage.upload', side_effect=RuntimeError('offline')
        ):
            get_service.return_value.update_case_row.return_value = True
            resolve_case(
                self.config, self.actor('200'), 'CASE-1',
                {'client_request_id': 'request-3', 'resolution_text': 'Resolved with photo.', 'expected_revision': 1}, [evidence],
            )
        self.assertEqual(ComplaintCaseEvidence.objects.get().upload_status, 'failed')
        self.assertEqual(self.case.case_updates.count(), 1)

    def test_sheet_failure_does_not_roll_back_local_case_update(self):
        with patch('core.services.complaint_cases.get_sheets_service') as get_service:
            get_service.return_value.update_case_row.return_value = False
            result = resolve_case(
                self.config, self.actor('200'), 'CASE-1',
                {'client_request_id': 'local-first-1', 'expected_revision': 1, 'resolution_text': 'Resolved locally.'}, [],
            )
        self.case.refresh_from_db()
        self.assertEqual(self.case.complaint_status, 'Closed')
        self.assertEqual(result['sync_status'], 'failed')
        self.assertEqual(self.case.case_updates.get().sync_status, 'failed')

    def test_spoofed_image_extension_is_rejected(self):
        evidence = SimpleUploadedFile('photo.jpg', b'not-an-image', content_type='image/jpeg')
        with self.assertRaisesMessage(ComplaintCaseError, 'genuine JPEG'):
            resolve_case(
                self.config, self.actor('200'), 'CASE-1',
                {'client_request_id': 'spoofed-file-1', 'expected_revision': 1, 'resolution_text': 'Evidence.'}, [evidence],
            )

    def test_evidence_filename_does_not_expose_customer_id(self):
        self.case.customer_id = 'ID 123/456'
        self.case.save(update_fields=['customer_id'])

        filename = evidence_filename(self.case, 'site photo.jpg', 1)
        self.assertNotIn('ID_123456', filename)
        self.assertTrue(filename.endswith('-01-site_photo.jpg'))

    def test_stale_revision_is_rejected_without_overwriting_the_first_update(self):
        actor = self.actor('200')
        with patch('core.services.complaint_cases.get_sheets_service') as get_service:
            get_service.return_value.update_case_row.return_value = True
            resolve_case(self.config, actor, 'CASE-1', {
                'client_request_id': 'revision-first', 'expected_revision': 1,
                'resolution_text': 'First resolution.',
            }, [])
            with self.assertRaises(ComplaintCaseConflict):
                resolve_case(self.config, actor, 'CASE-1', {
                    'client_request_id': 'revision-stale', 'expected_revision': 1,
                    'resolution_text': 'Stale resolution.',
                }, [])
        self.case.refresh_from_db()
        self.assertEqual(self.case.complaint_status, 'Closed')
        self.assertEqual(ComplaintCaseEvent.objects.filter(case__parsed_message=self.case).count(), 1)

    def test_any_authorized_officer_can_reopen_a_resolved_case(self):
        with patch('core.services.complaint_cases.get_sheets_service') as get_service:
            get_service.return_value.update_case_row.return_value = True
            resolve_case(self.config, self.actor('200'), 'CASE-1', {
                'client_request_id': 'resolve-before-reopen', 'expected_revision': 1,
                'resolution_text': 'Initial remedy.',
            }, [])
            result = reopen_case(self.config, self.actor('100'), 'CASE-1', {
                'client_request_id': 'officer-reopen', 'expected_revision': 2,
                'reason': 'The remedy did not address the reported fault.',
            })
        self.case.refresh_from_db()
        self.assertEqual(self.case.complaint_status, 'Open')
        self.assertEqual(result['latest_resolution']['note'], 'Initial remedy.')
        self.assertEqual(result['latest_reopen']['note'], 'The remedy did not address the reported fault.')

    def test_resolution_retry_returns_the_first_result_without_a_second_event(self):
        fields = {
            'client_request_id': 'resolve-retry-1', 'expected_revision': 1,
            'resolution_text': 'Resolved once.',
        }
        with patch('core.services.complaint_cases.get_sheets_service') as get_service:
            get_service.return_value.update_case_row.return_value = True
            first = resolve_case(self.config, self.actor('200'), 'CASE-1', fields, [])
            replay = resolve_case(self.config, self.actor('200'), 'CASE-1', fields, [])

        self.assertEqual(first['revision'], replay['revision'])
        self.assertEqual(self.case.case_updates.filter(client_request_id='resolve-retry-1').count(), 1)
        self.assertEqual(ComplaintCaseEvent.objects.filter(case__parsed_message=self.case).count(), 1)

    def test_imported_case_exposes_audited_batch_attribution(self):
        batch = ComplaintCaseImportBatch.objects.create(
            group_id=self.config.group_id, source_telegram_message_id='telegram-batch-1',
            initiated_by=self.manager, actor_label='Manager One', telegram_user_id_snapshot='200',
            source_hash='a' * 64, status='complete', source_count=1, created_count=1,
        )
        ComplaintCaseImportItem.objects.create(batch=batch, parsed_message=self.case, source_index=0)

        item = list_cases(self.config, self.actor('100'))[0]

        self.assertEqual(item['source_attribution']['type'], 'batch')
        self.assertEqual(item['source_attribution']['actor'], 'Manager One')

    def test_legacy_import_never_guesses_an_uploader(self):
        self.case.source = 'whatsapp_export'
        self.case.save(update_fields=['source'])

        item = list_cases(self.config, self.actor('100'))[0]

        self.assertEqual(item['source_attribution']['type'], 'legacy_batch')
        self.assertIn('uploader not recorded', item['source_attribution']['label'])

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
    def test_compact_two_state_workspace_has_only_supported_actions(self):
        root = Path(__file__).resolve().parent
        template = (root / 'templates' / 'complaint_cases' / 'app.html').read_text(encoding='utf-8')
        script = (root / 'static' / 'miniapp' / 'complaint_cases.js').read_text(encoding='utf-8')

        for expected in ('class="app-top"', 'class="status-tabs"', 'id="createCaseForm"', 'name="client_name"', 'name="customer_phone"', 'name="customer_id"', 'name="branch_region"', 'name="complaint_category"', 'name="complaint_description"', 'id="createEvidenceInput"', 'data-status="pending"', 'data-status="resolved"', 'data-status="all"', 'id="resolveForm"', 'id="reopenForm"', 'id="conflictPanel"', 'id="queuePagination"'):
            self.assertIn(expected, template)
        self.assertIn("miniapp/utils.js", template)
        self.assertIn("data.set('expected_revision'", script)
        self.assertIn("submitTransition(event, 'resolve')", script)
        self.assertIn("submitTransition(event, 'reopen')", script)
        self.assertIn('function showConflict(error)', script)
        self.assertIn("telegram?.BackButton?.onClick", script)
        for retired in ('priorityFilter', 'assignmentFilter', 'slaFilter', 'claimBtn', 'Settings', 'In Progress'):
            self.assertNotIn(retired, template)


class ComplaintCaseAdminTests(TestCase):
    def test_group_admin_has_no_legacy_staff_inlines(self):
        complaint_group = GroupSheetConfiguration.objects.create(
            group_id='-100complaints', workflow={'type': 'case'}
        )
        tat_group = GroupSheetConfiguration.objects.create(
            group_id='-100tat', workflow={'type': 'tat_tracker'}
        )
        model_admin = admin.site._registry[GroupSheetConfiguration]
        request = RequestFactory().get('/admin/core/groupsheetconfiguration/')

        self.assertEqual(model_admin.get_inlines(request, complaint_group), [])
        self.assertEqual(model_admin.get_inlines(request, tat_group), [])


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
