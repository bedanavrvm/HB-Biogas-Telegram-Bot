from django.test import SimpleTestCase, override_settings

from core.api.views import _looks_like_origination_command, _process_origination_command


class OriginationTelegramCommandTests(SimpleTestCase):
    def test_command_match_is_bounded_and_supports_bot_suffix(self):
        self.assertTrue(_looks_like_origination_command('/origination'))
        self.assertTrue(_looks_like_origination_command('/origination@jbl_bot'))
        self.assertFalse(_looks_like_origination_command('/originationextra'))

    @override_settings(
        TELEGRAM_BOT_USERNAME='jbl_bot',
        ORIGINATION_MINI_APP_SHORT_NAME='origination',
        APP_BASE_URL='https://app.example.test',
    )
    def test_command_returns_named_mini_app_link(self):
        result = _process_origination_command()
        self.assertEqual(result['status'], 'command')
        self.assertEqual(
            result['reply_markup']['inline_keyboard'][0][0]['url'],
            'https://t.me/jbl_bot/origination',
        )
