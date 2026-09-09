from io import StringIO
from urllib.parse import parse_qs, urlsplit
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import GroupSheetConfiguration
from core.services.telegram_command_menu import bot_commands_for_workflow, private_chat_bot_commands
from core.services.telegram_launchers import (
    build_launcher_url,
    preview_group_launcher,
    publish_group_launcher,
)


def telegram_response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    return response


@override_settings(
    TELEGRAM_BOT_USERNAME='jbl_bot',
    TAT_TRACKER_MINI_APP_SHORT_NAME='tat',
    SPIN_MINI_APP_SHORT_NAME='spin',
    ORDER_APPROVAL_MINI_APP_SHORT_NAME='orders',
    PORTAL_MINI_APP_SHORT_NAME='portal',
    ORIGINATION_MINI_APP_SHORT_NAME='origination',
)
class TelegramLauncherTests(TestCase):
    def setUp(self):
        self.config = GroupSheetConfiguration.objects.create(
            group_id='-100launcher',
            display_name='Launcher group',
            enabled=True,
            sheet_id='sheet-launcher',
            sheet_name='Tracker',
            workflow={
                'type': 'tat_tracker',
                'mini_app_launchers': [
                    'tat_tracker',
                    'spin_credit',
                    'order_approval',
                    'pipeline_portal',
                    'loan_origination',
                ],
            },
        )

    def test_preview_uses_selected_generic_apps_and_durable_start_params(self):
        preview = preview_group_launcher(self.config)

        buttons = [
            button
            for row in preview['reply_markup']['inline_keyboard']
            for button in row
        ]
        self.assertEqual([button['text'] for button in buttons], [
            'TAT Tracker', 'SPIN / CRB', 'Pipeline Portal', 'Loan Origination',
        ])
        self.assertEqual(len(preview['reply_markup']['inline_keyboard']), 2)

        from core.services.spin_credit import decode_spin_start_param
        from core.services.tat_tracker import decode_tat_start_param

        decoders = [decode_tat_start_param, decode_spin_start_param]
        for button, decoder in zip(buttons[:2], decoders):
            start_param = parse_qs(urlsplit(button['url']).query)['startapp'][0]
            self.assertEqual(decoder(start_param), {'group_id': '-100launcher', 'token': ''})

        self.assertEqual(
            buttons[-1]['url'],
            'https://t.me/jbl_bot/origination',
        )

    def test_native_command_menus_are_archived(self):
        self.assertEqual(private_chat_bot_commands(), [])
        for workflow in ('jawabu_homebiogas', 'order_approval', 'spin_credit_analysis', 'tat_tracker'):
            self.assertEqual(bot_commands_for_workflow(workflow), [])

    def test_order_approval_is_removed_from_launcher_choices(self):
        self.assertNotIn('Order Approval', {
            button['text'] for row in preview_group_launcher(self.config)['reply_markup']['inline_keyboard']
            for button in row
        })
        self.assertEqual(build_launcher_url('order_approval', self.config.group_id), '')

    @override_settings(TELEGRAM_BOT_USERNAME='', ORIGINATION_MINI_APP_SHORT_NAME='', APP_BASE_URL='https://app.example.test')
    def test_origination_launcher_has_deployed_url_fallback(self):
        self.assertEqual(
            build_launcher_url('loan_origination', '-100launcher'),
            'https://app.example.test/origination/',
        )

    @override_settings(TELEGRAM_BOT_TOKEN='token', API_REQUEST_TIMEOUT=5)
    @patch('core.services.telegram_launchers.requests.post')
    def test_publish_sends_then_pins_and_records_message_state(self, mock_post):
        mock_post.side_effect = [
            telegram_response({'ok': True, 'result': {'message_id': 44}}),
            telegram_response({'ok': True, 'result': True}),
        ]

        result = publish_group_launcher(self.config)

        self.assertEqual(result['action'], 'sent')
        self.assertEqual(result['message_id'], 44)
        methods = [call.args[0].rsplit('/', 1)[-1] for call in mock_post.call_args_list]
        self.assertEqual(methods, ['sendMessage', 'pinChatMessage'])
        self.config.refresh_from_db()
        state = self.config.metadata['telegram_launcher']
        self.assertEqual(state['message_id'], 44)
        self.assertEqual(state['pin_status'], 'pinned')

    @override_settings(TELEGRAM_BOT_TOKEN='token', API_REQUEST_TIMEOUT=5)
    @patch('core.services.telegram_launchers.requests.post')
    def test_publish_replaces_missing_previous_launcher(self, mock_post):
        self.config.metadata = {'telegram_launcher': {'message_id': 21}}
        self.config.save(update_fields=['metadata', 'updated_at'])
        mock_post.side_effect = [
            telegram_response(
                {'ok': False, 'description': 'Bad Request: message to edit not found'},
                status_code=400,
            ),
            telegram_response({'ok': True, 'result': {'message_id': 45}}),
            telegram_response({'ok': True, 'result': True}),
        ]

        result = publish_group_launcher(self.config)

        self.assertEqual(result['action'], 'sent')
        methods = [call.args[0].rsplit('/', 1)[-1] for call in mock_post.call_args_list]
        self.assertEqual(methods, ['editMessageText', 'sendMessage', 'pinChatMessage'])

    @override_settings(TELEGRAM_BOT_TOKEN='token', API_REQUEST_TIMEOUT=5)
    @patch('core.services.telegram_launchers.requests.post')
    def test_force_new_launcher_sends_and_pins_without_editing_previous_message(self, mock_post):
        self.config.metadata = {'telegram_launcher': {'message_id': 21}}
        self.config.save(update_fields=['metadata', 'updated_at'])
        mock_post.side_effect = [
            telegram_response({'ok': True, 'result': {'message_id': 46}}),
            telegram_response({'ok': True, 'result': True}),
        ]

        result = publish_group_launcher(
            self.config,
            operation_key_suffix='staff-join:123',
            force_new_message=True,
        )

        self.assertEqual(result['action'], 'sent')
        self.assertEqual(result['message_id'], 46)
        methods = [call.args[0].rsplit('/', 1)[-1] for call in mock_post.call_args_list]
        self.assertEqual(methods, ['sendMessage', 'pinChatMessage'])
        self.config.refresh_from_db()
        self.assertEqual(self.config.metadata['telegram_launcher']['message_id'], 46)

    @override_settings(TELEGRAM_BOT_TOKEN='token', API_REQUEST_TIMEOUT=5)
    @patch('core.services.telegram_launchers.requests.post')
    def test_refresh_request_updates_an_unchanged_existing_launcher(self, mock_post):
        mock_post.side_effect = [
            telegram_response({'ok': True, 'result': {'message_id': 47}}),
            telegram_response({'ok': True, 'result': True}),
            telegram_response({'ok': True, 'result': True}),
            telegram_response({'ok': True, 'result': True}),
        ]
        publish_group_launcher(self.config, operation_key_suffix='admin:first-request')

        result = publish_group_launcher(
            self.config, operation_key_suffix='admin:refresh-request',
        )

        self.assertEqual(result['action'], 'updated')
        methods = [call.args[0].rsplit('/', 1)[-1] for call in mock_post.call_args_list]
        self.assertEqual(methods, [
            'sendMessage', 'pinChatMessage', 'editMessageText', 'pinChatMessage',
        ])

    @override_settings(TELEGRAM_BOT_TOKEN='token', API_REQUEST_TIMEOUT=5)
    @patch('core.services.telegram_launchers.requests.post')
    def test_publish_normalizes_durable_operation_failure_for_admin_action(self, mock_post):
        mock_post.return_value = telegram_response(
            {'ok': False, 'description': 'Forbidden: bot is not a member'},
            status_code=403,
        )

        from core.services.telegram_launchers import TelegramLauncherError
        with self.assertRaisesMessage(
            TelegramLauncherError,
            'Telegram could not publish the launcher.',
        ):
            publish_group_launcher(
                self.config, operation_key_suffix='admin:failed-request',
            )

    @override_settings(TELEGRAM_BOT_TOKEN='token')
    @patch('core.services.telegram_launchers.publish_group_launcher')
    def test_admin_publish_action_confirms_and_uses_one_request_id(self, publish):
        publish.return_value = {'action': 'updated', 'message_id': 48}
        superuser = get_user_model().objects.create_superuser(
            username='launcher-admin', password='test-password',
            email='launcher-admin@example.test',
        )
        self.client.force_login(superuser)
        url = reverse('admin:core_groupsheetconfiguration_changelist')

        confirmation = self.client.post(url, {
            'action': 'publish_jbl_apps_launchers',
            '_selected_action': [str(self.config.pk)],
        })
        request_id = confirmation.context['request_id']
        response = self.client.post(url, {
            'action': 'publish_jbl_apps_launchers',
            '_selected_action': [str(self.config.pk)],
            'confirm_launcher_publish': 'yes',
            'launcher_request_id': request_id,
        })

        self.assertEqual(confirmation.status_code, 200)
        self.assertContains(confirmation, 'Publish / refresh launcher')
        self.assertEqual(response.status_code, 302)
        publish.assert_called_once_with(
            self.config,
            operation_key_suffix=f'admin:{request_id}',
        )

    def test_group_admin_form_saves_selected_launcher_apps(self):
        from core.admin import GroupSheetConfigurationAdminForm

        data = {
            'workflow_preset': 'tat_tracker',
            'group_id': self.config.group_id,
            'display_name': self.config.display_name,
            'enabled': 'on',
            'sheet_id': self.config.sheet_id,
            'sheet_name': self.config.sheet_name,
            'sheet_schema': '{}',
            'workflow': '{}',
            'parser_rules': '{}',
            'metadata': '{}',
            'mini_app_launchers': ['tat_tracker', 'pipeline_portal', 'loan_origination'],
        }
        form = GroupSheetConfigurationAdminForm(data=data, instance=self.config)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.generated_workflow()['mini_app_launchers'],
            ['tat_tracker', 'pipeline_portal', 'loan_origination'],
        )

    def test_sync_command_dry_run_does_not_need_token(self):
        output = StringIO()

        call_command(
            'sync_telegram_launchers',
            '--dry-run',
            '--group-id=-100launcher',
            stdout=output,
        )

        self.assertIn('Would publish chat -100launcher', output.getvalue())
        self.assertIn('TAT Tracker', output.getvalue())

    @override_settings(TELEGRAM_BOT_TOKEN='token')
    @patch('core.management.commands.sync_telegram_launchers.publish_group_launcher')
    def test_sync_command_uses_explicit_refresh_request_id(self, publish):
        publish.return_value = {'action': 'updated', 'message_id': 49}

        call_command(
            'sync_telegram_launchers',
            '--group-id=-100launcher',
            '--request-id=launcher-command-request',
        )

        publish.assert_called_once_with(
            self.config,
            timeout=10,
            allow_disabled=False,
            operation_key_suffix='command:launcher-command-request',
        )
