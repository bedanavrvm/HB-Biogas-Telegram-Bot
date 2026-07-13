from unittest.mock import patch

from django.test import TestCase, override_settings

from core.models import GroupSheetConfiguration, TatTrackerCase, TatTrackerStaffMember
from core.api.views import _process_telegram_message
from core.services.group_config import GroupRegistry
from core.services.tat_tracker import (
    build_tat_tracker_url,
    create_tat_start_param,
    decode_tat_start_param,
    product_by_key,
    tat_days_formula,
    tat_hours_formula,
    create_case,
    is_tat_tracker_workflow,
    staff_user_for_payload,
    update_case,
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

    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_create_case_assigns_sequential_case_id(self, sync_mock):
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
    def test_stage_updates_are_role_and_sequence_controlled(self, sync_mock):
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
