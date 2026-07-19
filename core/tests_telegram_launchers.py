from io import StringIO
from urllib.parse import parse_qs, urlsplit
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from core.models import GroupSheetConfiguration
from core.services.telegram_launchers import preview_group_launcher, publish_group_launcher


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
            'TAT Tracker', 'SPIN / CRB', 'Order Approval', 'Pipeline Portal',
        ])
        self.assertEqual(len(preview['reply_markup']['inline_keyboard']), 2)

        from core.services.order_approval import decode_order_approval_start_param
        from core.services.spin_credit import decode_spin_start_param
        from core.services.tat_tracker import decode_tat_start_param

        decoders = [decode_tat_start_param, decode_spin_start_param, decode_order_approval_start_param]
        for button, decoder in zip(buttons[:3], decoders):
            start_param = parse_qs(urlsplit(button['url']).query)['startapp'][0]
            self.assertEqual(decoder(start_param), {'group_id': '-100launcher', 'token': ''})

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
            'mini_app_launchers': ['tat_tracker', 'pipeline_portal'],
        }
        form = GroupSheetConfigurationAdminForm(data=data, instance=self.config)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.generated_workflow()['mini_app_launchers'],
            ['tat_tracker', 'pipeline_portal'],
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
