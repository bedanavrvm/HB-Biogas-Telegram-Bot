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


def signed_init_data(telegram_id='12345', token='test-token', username='unified_user'):
    payload = {
        'auth_date': str(int(time.time())),
        'query_id': 'identity-test',
        'user': json.dumps({
            'id': int(telegram_id), 'first_name': 'Unified', 'last_name': 'User',
            'username': username,
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
            group_configuration=self.config, name='Name Only', telegram_username='', role='OFFICER',
        )
        ComplaintCaseStaffMember.objects.create(
            group_configuration=self.config, name='Username Only',
            telegram_username='username_only', role='OFFICER',
        )

    def test_dry_run_does_not_write(self):
        output = io.StringIO()
        call_command('migrate_legacy_staff', stdout=output)

        self.assertIn('Dry run only', output.getvalue())
        self.assertFalse(UserProfile.objects.exists())
        self.assertFalse(LegacyStaffUserMapping.objects.exists())

    def test_user_admin_is_the_only_staff_management_surface(self):
        from core.admin import UserProfileAdminForm
        from core.models import TatTrackerStaffMember

        self.assertIn(get_user_model(), admin.site._registry)
        self.assertNotIn(JawabuPortalStaffMember, admin.site._registry)
        self.assertNotIn(ComplaintCaseStaffMember, admin.site._registry)
        self.assertNotIn(TatTrackerStaffMember, admin.site._registry)
        self.assertFalse(UserProfileAdminForm().fields['telegram_id'].required)
        self.assertTrue(UserProfileAdminForm().fields['telegram_id'].disabled)

    def test_superuser_can_preview_and_apply_migration_from_user_admin(self):
        superuser = get_user_model().objects.create_superuser(
            username='identity-admin', email='admin@example.test', password='test-password',
        )
        self.client.force_login(superuser)
        url = reverse('admin:auth_user_migrate_legacy_staff')

        user_list = self.client.get(reverse('admin:auth_user_changelist'))
        self.assertContains(user_list, 'Migrate existing staff')
        self.assertContains(user_list, 'Add Django login user')

        preview = self.client.get(url)
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, 'Dry-run preview')
        self.assertContains(preview, 'High-confidence users: 1')
        self.assertFalse(UserProfile.objects.filter(telegram_id='12345').exists())

        applied = self.client.post(url, {'confirmation': 'MIGRATE'})
        self.assertEqual(applied.status_code, 200)
        self.assertContains(applied, 'Migration result')
        self.assertTrue(UserProfile.objects.filter(telegram_id='12345').exists())

    def test_default_user_add_redirects_to_telegram_enrollment(self):
        superuser = get_user_model().objects.create_superuser(
            username='redirect-admin', email='admin@example.test', password='test-password',
        )
        self.client.force_login(superuser)

        response = self.client.get(reverse('admin:auth_user_add'))
        self.assertRedirects(
            response,
            reverse('admin:auth_user_migrate_legacy_staff') + '#enroll-telegram-user',
            fetch_redirect_response=False,
        )

        django_user_form = self.client.get(
            reverse('admin:auth_user_add') + '?account_type=django',
        )
        self.assertEqual(django_user_form.status_code, 200)

    def test_non_superuser_cannot_open_admin_migration_panel(self):
        staff_user = get_user_model().objects.create_user(
            username='ordinary-admin', password='test-password', is_staff=True,
        )
        self.client.force_login(staff_user)

        response = self.client.get(reverse('admin:auth_user_migrate_legacy_staff'))
        self.assertEqual(response.status_code, 403)

    def test_superuser_can_enroll_username_without_knowing_telegram_id(self):
        superuser = get_user_model().objects.create_superuser(
            username='enrollment-admin', email='admin@example.test', password='test-password',
        )
        self.client.force_login(superuser)

        response = self.client.post(reverse('admin:auth_user_migrate_legacy_staff'), {
            'operation': 'enroll',
            'display_name': 'Pending Telegram User',
            'telegram_username': '@pending_user',
            'workflow': 'jawabu_portal',
            'role': 'JBL_OFFICER',
            'branch': 'Nairobi',
            'product': '',
            'group_configuration': '',
        })

        self.assertEqual(response.status_code, 200)
        profile = UserProfile.objects.get(telegram_username='pending_user')
        self.assertEqual(profile.telegram_id, '')
        self.assertTrue(profile.user.is_active)
        self.assertFalse(profile.user.is_staff)
        self.assertFalse(profile.user.has_usable_password())
        self.assertTrue(AccessGrant.objects.filter(user=profile.user, role='JBL_OFFICER').exists())

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
        pending_profile = UserProfile.objects.get(telegram_username='username_only')
        self.assertEqual(pending_profile.telegram_id, '')
        self.assertFalse(pending_profile.user.has_usable_password())

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

    def test_first_signed_login_binds_pre_enrolled_username_to_numeric_id(self):
        pending = get_user_model().objects.create(username='tg_pending_first_login', is_active=True)
        pending.set_unusable_password()
        pending.save()
        profile = UserProfile.objects.create(
            user=pending, telegram_username='first_login_user', telegram_id='',
        )
        AccessGrant.objects.create(user=pending, workflow='jawabu_portal', role='JBL_OFFICER')

        response = self.client.post(
            reverse('telegram_session_login'),
            HTTP_X_TELEGRAM_INIT_DATA=signed_init_data(
                telegram_id='98765', username='first_login_user',
            ),
        )

        self.assertEqual(response.status_code, 200)
        profile.refresh_from_db()
        self.assertEqual(profile.telegram_id, '98765')
        self.assertTrue(profile.telegram_metadata['bound_from_signed_init_data'])

    def test_unmatched_username_cannot_create_or_claim_an_account(self):
        response = self.client.post(
            reverse('telegram_session_login'),
            HTTP_X_TELEGRAM_INIT_DATA=signed_init_data(
                telegram_id='98765', username='not_enrolled',
            ),
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(UserProfile.objects.filter(telegram_id='98765').exists())

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

    def test_tat_runtime_group_config_resolves_to_database_scope(self):
        from core.services.group_config import GroupConfig
        from core.services.tat_tracker import configured_bro_names, staff_user_for_payload

        config = GroupSheetConfiguration.objects.create(
            group_id='-100-runtime', sheet_id='runtime-sheet', sheet_name='TAT', enabled=True,
        )
        AccessGrant.objects.create(
            user=self.user, workflow='tat_tracker', role='BRO', branch='Nairobi',
            product='business', group_configuration=config,
        )
        runtime_config = GroupConfig(
            group_id=config.group_id, sheet_id=config.sheet_id,
            sheet_name=config.sheet_name, workflow={'type': 'tat_tracker'},
        )

        resolved = staff_user_for_payload(runtime_config, {'id': 12345, 'username': 'unified_user'})
        names = configured_bro_names(runtime_config.workflow, runtime_config)

        self.assertTrue(resolved['authorized'])
        self.assertIn('BRO', resolved['roles'])
        self.assertIn(self.user.get_full_name() or self.user.get_username(), names)

    def test_superuser_receives_workflow_admin_roles_without_explicit_grants(self):
        from core.services.telegram_identity import user_access

        superuser = get_user_model().objects.create_superuser(
            username='global-superuser', email='super@example.test', password='test-password',
        )

        self.assertIn('ADMIN', user_access(superuser, 'jawabu_portal')['roles'])
        self.assertIn('MANAGER', user_access(superuser, 'complaint_cases')['roles'])
        self.assertIn('ADMIN', user_access(superuser, 'tat_tracker')['roles'])
