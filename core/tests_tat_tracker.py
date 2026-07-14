from unittest.mock import patch
from decimal import Decimal
import json

from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import GroupSheetConfiguration, TatTrackerCase, TatTrackerStaffMember
from core.api.views import _process_telegram_message
from core.services.group_config import GroupRegistry
from core.services.tat_tracker import (
    build_tat_tracker_url,
    calculated_tat_days,
    calculated_tat_hours,
    create_tat_start_param,
    decode_tat_start_param,
    product_by_key,
    tat_days_formula,
    tat_hours_formula,
    create_case,
    is_tat_tracker_workflow,
    next_role_alert,
    staff_user_for_payload,
    sync_case_to_sheet,
    update_case,
    workflow_branches,
)


class TatTrackerWorkflowTest(TestCase):
    def setUp(self):
        self.config = GroupSheetConfiguration.objects.create(
            group_id='-100tat',
            display_name='TAT Test',
            sheet_id='sheet123',
            sheet_name='TRACKER-SME',
            workflow={
                'type': 'tat_tracker',
                'products': ['sme', 'logbook'],
                'branches': ['Nakuru', 'Embu'],
                'staff': [
                    {
                        'telegram_user_id': '111',
                        'telegram_username': 'bro_user',
                        'name': 'BRO User',
                        'roles': ['BRO'],
                        'branches': ['Nakuru'],
                        'products': ['sme'],
                        'active': True,
                    },
                    {
                        'telegram_user_id': '222',
                        'telegram_username': 'admin_user',
                        'name': 'Admin User',
                        'roles': ['ADMIN'],
                        'branches': ['Nakuru'],
                        'products': ['sme'],
                        'active': True,
                    },
                ],
            },
        )

    def test_detects_tat_tracker_workflow(self):
        self.assertTrue(is_tat_tracker_workflow(self.config))

    @override_settings(APP_BASE_URL='https://example.test')
    def test_builds_secure_tracker_url(self):
        url = build_tat_tracker_url(self.config.group_id)
        self.assertIn('https://example.test/tat-tracker/', url)
        self.assertIn('group_id=-100tat', url)
        self.assertIn('token=', url)


    @override_settings(APP_BASE_URL='https://example.test', TELEGRAM_BOT_USERNAME='testbot', TAT_TRACKER_MINI_APP_SHORT_NAME='tattracker')
    def test_tat_command_routes_to_mini_app_button(self):
        GroupRegistry._instance = None
        result = _process_telegram_message({
            'message_id': 900,
            'chat': {'id': self.config.group_id, 'type': 'supergroup', 'title': 'TAT Test'},
            'from': {'id': 111, 'first_name': 'BRO', 'last_name': 'User', 'username': 'bro_user'},
            'text': '@testbot /tat',
            'date': 1783920000,
        })

        self.assertEqual(result['status'], 'command')
        self.assertIn('TAT Tracker', result['reply_text'])
        button = result['reply_markup']['inline_keyboard'][0][0]
        self.assertEqual(button['text'], 'Open TAT Tracker Mini App')
        self.assertIn('url', button)
        self.assertNotIn('web_app', button)
        self.assertTrue(button['url'].startswith('https://t.me/testbot/tattracker?startapp='))

    @override_settings(STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    def test_tat_app_preserves_signed_token_from_start_param(self):
        start_param = create_tat_start_param(self.config.group_id)
        token = decode_tat_start_param(start_param)['token']

        response = self.client.get('/tat-tracker/', {'tgWebAppStartParam': start_param})

        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn(f'data-token="{token}"', html)
        self.assertNotIn('\\u003A', html)



    def test_workflow_branches_replace_stale_default_branch_list(self):
        stale_workflow = {
            'branches': ['Corporate', 'Thika Road', 'East Nairobi', 'West Nairobi', 'Nakuru', 'Embu', 'Limuru'],
        }

        self.assertEqual(workflow_branches(stale_workflow), ['Biogas Unit', 'Embu', 'Nakuru', 'West Nairobi'])

    def test_tat_formula_helpers_match_tracker_columns(self):
        sme = product_by_key('sme')
        logbook = product_by_key('logbook')

        self.assertEqual(tat_hours_formula(sme, 5), '=IF(OR($F5="",$P5=""),"",ROUND(($P5-$F5)*24,2))')
        self.assertEqual(tat_days_formula(sme, 5), '=IF(S5="","",ROUND(S5/24,2))')
        self.assertEqual(tat_hours_formula(logbook, 5), '=IF(OR($F5="",$X5=""),"",ROUND(($X5-$F5)*24,2))')
        self.assertEqual(tat_days_formula(logbook, 5), '=IF(AA5="","",ROUND(AA5/24,2))')
    def test_group_config_merges_gui_staff_rows_into_workflow(self):
        TatTrackerStaffMember.objects.create(
            group_configuration=self.config,
            name='GUI Staff',
            telegram_user_id='333',
            telegram_username='gui_staff',
            roles='CA,BM',
            branches='ALL',
            products='sme,logbook',
        )
        TatTrackerStaffMember.objects.create(
            group_configuration=self.config,
            name='Inactive Staff',
            telegram_user_id='444',
            roles='BRO',
            active=False,
        )

        workflow = self.config.as_group_config_kwargs()['workflow']
        self.assertEqual(len(workflow['staff']), 1)
        self.assertEqual(workflow['staff'][0]['name'], 'GUI Staff')
        self.assertEqual(workflow['staff'][0]['roles'], ['CA', 'BM'])
        self.assertEqual(workflow['staff'][0]['branches'], ['ALL'])
        self.assertEqual(workflow['staff'][0]['products'], ['sme', 'logbook'])


    def test_gui_staff_rows_override_legacy_workflow_staff_even_when_inactive(self):
        self.config.workflow['staff'] = [{
            'telegram_user_id': '999',
            'name': 'Legacy JSON Staff',
            'roles': ['IT'],
            'branches': ['ALL'],
            'products': ['ALL'],
            'active': True,
        }]
        self.config.save()
        TatTrackerStaffMember.objects.create(
            group_configuration=self.config,
            name='Disabled GUI Staff',
            telegram_user_id='555',
            roles='BRO',
            active=False,
        )

        workflow = self.config.as_group_config_kwargs()['workflow']

        self.assertEqual(workflow['staff'], [])
    def test_staff_user_matches_gui_staff_row(self):
        TatTrackerStaffMember.objects.create(
            group_configuration=self.config,
            name='GUI Staff',
            telegram_user_id='333',
            telegram_username='gui_staff',
            roles='CA',
            branches='ALL',
            products='ALL',
        )
        group_config = type('GroupConfigLike', (), self.config.as_group_config_kwargs())()

        user = staff_user_for_payload(group_config, {'id': 333, 'username': 'gui_staff'})

        self.assertTrue(user['authorized'])
        self.assertEqual(user['name'], 'GUI Staff')
        self.assertEqual(user['roles'], ['CA'])
        self.assertEqual(user['branches'], ['ALL'])
        self.assertEqual(user['products'], ['ALL'])
    def test_staff_user_matches_telegram_id(self):
        user = staff_user_for_payload(self.config, {'id': 111, 'username': 'someone_else'})
        self.assertTrue(user['authorized'])
        self.assertEqual(user['name'], 'BRO User')
        self.assertEqual(user['roles'], ['BRO'])

    @staticmethod
    def mark_case_synced(_group_config, case):
        case.row_number = case.row_number or 5
        case.sheet_name = case.sheet_name or 'TRACKER-SME'
        case.sync_error = ''
        case.save(update_fields=['row_number', 'sheet_name', 'sync_error', 'updated_at'])

    @override_settings(TAT_TRACKER_SYNC_SECONDARY_SHEETS=True)
    def test_sync_case_to_sheet_writes_django_calculated_tat_values(self):
        class FakeSheet:
            def __init__(self):
                self.updates = []

            def row_values(self, _row):
                return [''] * 20

            def update(self, a1_range, values, value_input_option=None):
                self.updates.append((a1_range, values, value_input_option))

        class FakeService:
            def __init__(self, sheet):
                self._sheet = sheet

            def is_available(self):
                return True

        sheet = FakeSheet()
        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-SME',
            row_number=5,
            case_id='JBL-SME-2026-001',
            product_key='sme',
            product_label='SME',
            client_name='Test Client',
            branch='Nakuru',
            bro_name='BRO User',
            amount='10000',
            stage_values={
                'created': timezone.make_aware(timezone.datetime(2026, 7, 14, 8, 0)).isoformat(),
                'disbursement': timezone.make_aware(timezone.datetime(2026, 7, 15, 14, 0)).isoformat(),
            },
            status='Active',
        )

        with patch('core.services.tat_tracker.get_sheets_service', return_value=FakeService(sheet)), \
             patch('core.services.tat_tracker.sync_case_index'), \
             patch('core.services.tat_tracker.sync_audit_log'):
            sync_case_to_sheet(self.config, case)

        self.assertEqual(sheet.updates[0][0], 'A5:T5')
        self.assertEqual(len(sheet.updates[0][1][0]), 20)
        self.assertEqual(sheet.updates[0][1][0][18], 30.0)
        self.assertEqual(sheet.updates[0][1][0][19], 1.25)
        self.assertFalse(any(str(value).startswith('=IF(') for value in sheet.updates[0][1][0]))

    def test_sync_case_to_sheet_skips_secondary_sheets_by_default(self):
        class FakeSheet:
            def row_values(self, _row):
                return [''] * 20

            def update(self, *_args, **_kwargs):
                return None

        class FakeService:
            _sheet = FakeSheet()

            def is_available(self):
                return True

        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-SME',
            row_number=5,
            case_id='JBL-SME-2026-003',
            product_key='sme',
            product_label='SME',
            client_name='Test Client',
            branch='Nakuru',
            bro_name='BRO User',
            amount='10000',
            stage_values={'created': timezone.now().isoformat()},
            status='Active',
        )

        with patch('core.services.tat_tracker.get_sheets_service', return_value=FakeService()), \
             patch('core.services.tat_tracker.sync_case_index') as index_mock, \
             patch('core.services.tat_tracker.sync_audit_log') as audit_mock:
            sync_case_to_sheet(self.config, case)

        index_mock.assert_not_called()
        audit_mock.assert_not_called()

    def test_sync_case_to_sheet_appends_new_rows_without_scanning_existing_ids(self):
        class FakeSheet:
            def __init__(self):
                self.appended = []
                self.row_values_called = False
                self.col_values_called = False

            def row_values(self, _row):
                self.row_values_called = True
                return [''] * 20

            def col_values(self, _col):
                self.col_values_called = True
                return ['Case ID']

            def append_row(self, row, value_input_option=None):
                self.appended.append((row, value_input_option))
                return {'updates': {'updatedRange': 'TRACKER-SME!A6:T6'}}

        class FakeService:
            def __init__(self, sheet):
                self._sheet = sheet

            def is_available(self):
                return True

        sheet = FakeSheet()
        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-SME',
            case_id='JBL-SME-2026-005',
            product_key='sme',
            product_label='SME',
            client_name='Test Client',
            branch='Nakuru',
            bro_name='BRO User',
            amount='10000',
            stage_values={'created': timezone.now().isoformat()},
            status='Active',
        )

        with patch('core.services.tat_tracker.get_sheets_service', return_value=FakeService(sheet)):
            sync_case_to_sheet(self.config, case)

        self.assertEqual(case.row_number, 6)
        self.assertEqual(len(sheet.appended), 1)
        self.assertFalse(sheet.row_values_called)
        self.assertFalse(sheet.col_values_called)

    @override_settings(TAT_TRACKER_SYNC_SECONDARY_SHEETS=False)
    def test_sync_case_to_sheet_allows_workflow_secondary_sheet_override(self):
        class FakeSheet:
            def row_values(self, _row):
                return [''] * 20

            def update(self, *_args, **_kwargs):
                return None

        class FakeService:
            _sheet = FakeSheet()

            def is_available(self):
                return True

        self.config.workflow['sync_secondary_sheets'] = True
        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-SME',
            row_number=5,
            case_id='JBL-SME-2026-004',
            product_key='sme',
            product_label='SME',
            client_name='Test Client',
            branch='Nakuru',
            bro_name='BRO User',
            amount='10000',
            stage_values={'created': timezone.now().isoformat()},
            status='Active',
        )

        with patch('core.services.tat_tracker.get_sheets_service', return_value=FakeService()), \
             patch('core.services.tat_tracker.sync_case_index') as index_mock, \
             patch('core.services.tat_tracker.sync_audit_log') as audit_mock:
            sync_case_to_sheet(self.config, case)

        index_mock.assert_called_once_with(self.config, case)
        audit_mock.assert_called_once_with(self.config, case)

    def test_calculated_tat_values_use_aware_datetimes_and_ongoing_now(self):
        case = TatTrackerCase(
            group_id=self.config.group_id,
            case_id='JBL-SME-2026-002',
            product_key='sme',
            client_name='Ongoing Client',
            stage_values={'created': timezone.make_aware(timezone.datetime(2026, 7, 14, 8, 0)).isoformat()},
        )
        now = timezone.make_aware(timezone.datetime(2026, 7, 14, 20, 0))

        self.assertEqual(calculated_tat_hours(case, now=now), Decimal('12.00'))
        self.assertEqual(calculated_tat_days(case, now=now), Decimal('0.50'))

    def test_next_role_alert_targets_pending_stage_role(self):
        data = {
            'summary': {
                'case_id': 'JBL-SME-2026-001',
                'product_key': 'sme',
                'client_name': 'Test Client',
                'branch': 'Nakuru',
                'next_stage_key': 'mpesa_to_admin',
            }
        }

        alert = next_role_alert(self.config, data)

        self.assertEqual(alert['role'], 'BRO')
        self.assertIn('TAT action needed: BRO', alert['text'])
        self.assertIn('Next step: MPESA sent to Admin', alert['text'])

    def test_next_role_alert_can_be_disabled_in_workflow(self):
        self.config.workflow['stage_alerts_enabled'] = False
        data = {'summary': {'product_key': 'sme', 'next_stage_key': 'mpesa_to_admin'}}

        self.assertEqual(next_role_alert(self.config, data), {})

    @patch('core.api.views._post_telegram_reply')
    @patch('core.services.tat_tracker.sync_case_to_sheet')
    @patch('core.services.tat_tracker.validate_tat_telegram_webapp_init_data')
    def test_create_endpoint_alerts_next_stage_role(self, mock_auth, sync_mock, mock_reply):
        mock_auth.return_value = (True, '', {'id': 111, 'username': 'bro_user'})
        sync_mock.side_effect = self.mark_case_synced
        GroupRegistry._instance = None

        response = self.client.post(
            '/api/tat-tracker/create/',
            data=json.dumps({
                'group_id': self.config.group_id,
                'init_data': 'mock',
                'product_key': 'sme',
                'branch': 'Nakuru',
                'client_name': 'Test Client',
                'bro_name': 'BRO User',
                'amount': '10000',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        mock_reply.assert_called_once()
        self.assertIn('TAT action needed: BRO', mock_reply.call_args.kwargs['text'])

    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_create_case_assigns_sequential_case_id(self, sync_mock):
        sync_mock.side_effect = self.mark_case_synced
        user = staff_user_for_payload(self.config, {'id': 111, 'username': 'bro_user'})
        first = create_case(self.config, user, {
            'product_key': 'sme',
            'branch': 'Nakuru',
            'client_name': 'Test Client',
            'bro_name': 'BRO User',
            'amount': '10000',
        })
        second = create_case(self.config, user, {
            'product_key': 'sme',
            'branch': 'Nakuru',
            'client_name': 'Second Client',
            'bro_name': 'BRO User',
            'amount': '10000',
        })
        self.assertEqual(first['summary']['case_id'], 'JBL-SME-2026-001')
        self.assertEqual(second['summary']['case_id'], 'JBL-SME-2026-002')
        self.assertEqual(TatTrackerCase.objects.count(), 2)
        self.assertEqual(sync_mock.call_count, 2)

    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_create_case_retry_with_same_request_id_returns_existing_case(self, sync_mock):
        sync_mock.side_effect = self.mark_case_synced
        user = staff_user_for_payload(self.config, {'id': 111, 'username': 'bro_user'})
        payload = {
            'product_key': 'sme',
            'branch': 'Nakuru',
            'client_name': 'Test Client',
            'bro_name': 'BRO User',
            'amount': '10000',
            'client_request_id': 'req-123',
        }

        first = create_case(self.config, user, payload)
        second = create_case(self.config, user, payload)

        self.assertEqual(first['summary']['case_id'], second['summary']['case_id'])
        self.assertEqual(TatTrackerCase.objects.count(), 1)
        self.assertEqual(sync_mock.call_count, 1)

    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_create_case_retry_does_not_resync_existing_unsynced_case(self, sync_mock):
        sync_mock.side_effect = self.mark_case_synced
        user = staff_user_for_payload(self.config, {'id': 111, 'username': 'bro_user'})
        payload = {
            'product_key': 'sme',
            'branch': 'Nakuru',
            'client_name': 'Test Client',
            'bro_name': 'BRO User',
            'amount': '10000',
            'client_request_id': 'req-unsynced-retry',
        }

        first = create_case(self.config, user, payload)
        case = TatTrackerCase.objects.get(case_id=first['summary']['case_id'])
        case.row_number = None
        case.sync_error = 'response lost after sheet append'
        case.save(update_fields=['row_number', 'sync_error', 'updated_at'])

        second = create_case(self.config, user, payload)

        self.assertEqual(first['summary']['case_id'], second['summary']['case_id'])
        self.assertEqual(TatTrackerCase.objects.count(), 1)
        self.assertEqual(sync_mock.call_count, 1)

    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_create_case_rolls_back_when_primary_sheet_sync_fails(self, sync_mock):
        sync_mock.side_effect = RuntimeError('Primary sheet write failed')
        user = staff_user_for_payload(self.config, {'id': 111, 'username': 'bro_user'})

        with self.assertRaises(RuntimeError):
            create_case(self.config, user, {
                'product_key': 'sme',
                'branch': 'Nakuru',
                'client_name': 'Test Client',
                'bro_name': 'BRO User',
                'amount': '10000',
                'client_request_id': 'req-fail',
            })

        self.assertEqual(TatTrackerCase.objects.count(), 0)

    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_stage_updates_are_role_and_sequence_controlled(self, sync_mock):
        sync_mock.side_effect = self.mark_case_synced
        bro = staff_user_for_payload(self.config, {'id': 111, 'username': 'bro_user'})
        admin = staff_user_for_payload(self.config, {'id': 222, 'username': 'admin_user'})
        detail = create_case(self.config, bro, {
            'product_key': 'sme',
            'branch': 'Nakuru',
            'client_name': 'Test Client',
            'bro_name': 'BRO User',
            'amount': '10000',
        })
        case_id = detail['summary']['case_id']

        with self.assertRaises(ValueError):
            update_case(self.config, admin, case_id, [{'field': 'mpesa_verified', 'value': 'STAMP'}])

        update_case(self.config, bro, case_id, [{'field': 'mpesa_to_admin', 'value': 'STAMP'}])
        updated = update_case(self.config, admin, case_id, [{'field': 'mpesa_verified', 'value': 'STAMP'}])
        self.assertEqual(updated['summary']['next_stage_key'], 'ca_analysis_sent')
