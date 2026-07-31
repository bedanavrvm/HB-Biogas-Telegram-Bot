from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core.models import UserProfile
from core.services.miniapp_settings import account_summary_payload


class MiniAppSettingsAccountSummaryTests(TestCase):
    @override_settings(APP_RELEASE='settings-test-release')
    def test_account_summary_is_read_only_safe_and_scoped(self):
        user = get_user_model().objects.create_user(
            username='settings-user', first_name='Settings', last_name='User',
            email='settings@example.test',
        )
        UserProfile.objects.create(
            user=user,
            telegram_id='12345',
            telegram_username='settings_user',
            phone_number='254700000000',
        )

        summary = account_summary_payload(
            user,
            'jawabu_portal',
            roles=['BUSINESS_ADMIN'],
            branches=['EMBU'],
            products=['HomeBiogas'],
        )

        self.assertEqual(summary['display_name'], 'Settings User')
        self.assertTrue(summary['telegram_linked'])
        self.assertEqual(summary['telegram_username'], 'settings_user')
        self.assertEqual(summary['roles'], [{'key': 'BUSINESS_ADMIN', 'label': 'Business Admin'}])
        self.assertEqual(summary['branches'], ['EMBU'])
        self.assertEqual(summary['app_release'], 'settings-test-release')
        self.assertNotIn('telegram_id', summary)
