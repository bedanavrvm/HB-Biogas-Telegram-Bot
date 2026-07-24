import hashlib
import hmac
import io
import json
import time
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.contrib import admin
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import (
    AccessGrant, ComplaintCaseStaffMember, GroupSheetConfiguration,
    JawabuPortalStaffMember, LegacyStaffUserMapping, StaffIdentityReview, UserProfile,
)


def signed_init_data(telegram_id='12345', token='test-token'):
    payload = {
        'auth_date': str(int(time.time())),
        'query_id': 'identity-test',
        'user': json.dumps({
            'id': int(telegram_id), 'first_name': 'Unified', 'last_name': 'User',
            'username': 'unified_user',
        }, separators=(',', ':')),
    }
    check = '\n'.join(f'{key}={value}' for key, value in sorted(payload.items()))
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    payload['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(payload)


@override_settings(SECURE_SSL_REDIRECT=False)
class LegacyStaffMigrationCommandTests(TestCase):
    def setUp(self):
        self.config = GroupSheetConfiguration.objects.create(
            group_id='-100-identity', sheet_id='sheet-test', sheet_name='Cases', enabled=True,
        )
        self.portal = JawabuPortalStaffMember.objects.create(
            telegram_id='12345', display_name='Unified User', roles=['admin'], branches=['Nairobi'],
        )
        self.complaint = ComplaintCaseStaffMember.objects.create(
            group_configuration=self.config, name='Unified User', telegram_user_id='12345', role='MANAGER',
        )
        ComplaintCaseStaffMember.objects.create(
            group_configuration=self.config, name='Name Only', telegram_username='name_only', role='OFFICER',
        )

    def test_dry_run_does_not_write(self):
        output = io.StringIO()
        call_command('migrate_legacy_staff', stdout=output)

        self.assertIn('Dry run only', output.getvalue())
        self.assertFalse(UserProfile.objects.exists())
        self.assertFalse(LegacyStaffUserMapping.objects.exists())

    def test_user_admin_is_the_only_staff_management_surface(self):
        from core.models import TatTrackerStaffMember

        self.assertIn(get_user_model(), admin.site._registry)
        self.assertNotIn(JawabuPortalStaffMember, admin.site._registry)
        self.assertNotIn(ComplaintCaseStaffMember, admin.site._registry)
        self.assertNotIn(TatTrackerStaffMember, admin.site._registry)

    def test_superuser_can_preview_and_apply_migration_from_user_admin(self):
        superuser = get_user_model().objects.create_superuser(
            username='identity-admin', email='admin@example.test', password='test-password',
        )
        self.client.force_login(superuser)
        url = reverse('admin:auth_user_migrate_legacy_staff')

        user_list = self.client.get(reverse('admin:auth_user_changelist'))
        self.assertContains(user_list, 'Migrate existing staff')

        preview = self.client.get(url)
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, 'Dry-run preview')
        self.assertContains(preview, 'High-confidence users: 1')
        self.assertFalse(UserProfile.objects.filter(telegram_id='12345').exists())

        applied = self.client.post(url, {'confirmation': 'MIGRATE'})
        self.assertEqual(applied.status_code, 200)
        self.assertContains(applied, 'Migration result')
        self.assertTrue(UserProfile.objects.filter(telegram_id='12345').exists())

    def test_non_superuser_cannot_open_admin_migration_panel(self):
        staff_user = get_user_model().objects.create_user(
            username='ordinary-admin', password='test-password', is_staff=True,
        )
        self.client.force_login(staff_user)

        response = self.client.get(reverse('admin:auth_user_migrate_legacy_staff'))
        self.assertEqual(response.status_code, 403)

    def test_apply_merges_exact_telegram_id_and_routes_name_only_to_review(self):
        call_command('migrate_legacy_staff', '--apply', stdout=io.StringIO())

        user = get_user_model().objects.get(username='tg_12345')
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.staff_profile.telegram_id, '12345')
        self.assertEqual(LegacyStaffUserMapping.objects.filter(user=user).count(), 2)
        self.assertTrue(AccessGrant.objects.filter(user=user, workflow='jawabu_portal', role='admin').exists())
        self.assertTrue(AccessGrant.objects.filter(user=user, workflow='complaint_cases', role='MANAGER').exists())
        self.assertEqual(self.portal.as_user, user)
        self.assertEqual(self.complaint.as_user, user)
        self.assertTrue(StaffIdentityReview.objects.filter(identity_key='nameonly', status='pending').exists())

        call_command('migrate_legacy_staff', '--apply', stdout=io.StringIO())
        self.assertEqual(get_user_model().objects.filter(username='tg_12345').count(), 1)
        self.assertEqual(AccessGrant.objects.filter(user=user).count(), 2)

    def test_parity_check_fails_before_migration_and_passes_after_review_override(self):
        with self.assertRaises(CommandError):
            call_command('check_staff_identity_parity', stdout=io.StringIO())

        call_command('migrate_legacy_staff', '--apply', stdout=io.StringIO())

        call_command(
            'check_staff_identity_parity', '--allow-pending-reviews',
            stdout=io.StringIO(),
        )

    def test_parity_check_detects_missing_grant(self):
        call_command('migrate_legacy_staff', '--apply', stdout=io.StringIO())
        AccessGrant.objects.filter(workflow='jawabu_portal').delete()

        with self.assertRaises(CommandError):
            call_command(
                'check_staff_identity_parity', '--allow-pending-reviews',
                stdout=io.StringIO(),
            )


@override_settings(
    TELEGRAM_BOT_TOKEN='test-token', TELEGRAM_AUTH_MAX_AGE_SECONDS=86400,
    PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, PORTAL_WEBAPP_AUTH_MAX_AGE_SECONDS=86400,
    SECURE_SSL_REDIRECT=False,
)
class TelegramUserAuthenticationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username='tg_12345', is_active=True, is_staff=False)
        self.user.set_unusable_password()
        self.user.save()
        UserProfile.objects.create(user=self.user, telegram_id='12345', telegram_username='unified_user')
        AccessGrant.objects.create(user=self.user, workflow='jawabu_portal', role='JBL_OFFICER')

    def test_signed_init_data_creates_django_session(self):
        response = self.client.post(
            reverse('telegram_session_login'),
            HTTP_X_TELEGRAM_INIT_DATA=signed_init_data(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)
        self.assertFalse(self.user.has_usable_password())

    def test_invalid_signature_is_rejected(self):
        response = self.client.post(
            reverse('telegram_session_login'),
            HTTP_X_TELEGRAM_INIT_DATA=signed_init_data() + 'tampered',
        )
        self.assertEqual(response.status_code, 403)

    def test_portal_uses_access_grants_and_server_filters_navigation(self):
        auth = signed_init_data()
        dashboard = self.client.get(reverse('portal_dashboard'), HTTP_X_TELEGRAM_INIT_DATA=auth)
        navigation = self.client.get(reverse('portal_navigation'), HTTP_X_TELEGRAM_INIT_DATA=auth)

        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(navigation, 'JBL Queue')
        self.assertNotContains(navigation, 'Credit')
        self.assertNotContains(navigation, 'Invoices')

    def test_complaint_and_tat_resolvers_use_canonical_scoped_grants(self):
        from core.services.complaint_cases import staff_actor_for_payload
        from core.services.tat_tracker import staff_user_for_payload

        config = GroupSheetConfiguration.objects.create(
            group_id='-100-canonical', sheet_id='canonical-sheet', sheet_name='Cases', enabled=True,
        )
        AccessGrant.objects.create(
            user=self.user, workflow='complaint_cases', role='MANAGER', group_configuration=config,
        )
        AccessGrant.objects.create(
            user=self.user, workflow='tat_tracker', role='CA', branch='Nairobi',
            product='business', group_configuration=config,
        )
        payload = {'id': 12345, 'username': 'unified_user'}

        complaint_actor = staff_actor_for_payload(config, {'user': json.dumps(payload)})
        tat_user = staff_user_for_payload(config, payload)

        self.assertTrue(complaint_actor.is_manager)
        self.assertTrue(tat_user['authorized'])
        self.assertIn('CA', tat_user['roles'])
        self.assertEqual(tat_user['branches'], ['Nairobi'])
        self.assertEqual(tat_user['products'], ['business'])
