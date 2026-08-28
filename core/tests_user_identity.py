import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib import admin
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.models import (
    AccessControlChangeRequest, AccessGrant, GroupSheetConfiguration,
    StaffLifecycleChangePlan, UserProfile,
)
from core.services.access_control import appoint_access_control_checker
from core.services.staff_lifecycle import approve_lifecycle_plan


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
class CanonicalStaffAdminTests(TestCase):

    def test_portal_action_policy_is_centralized_and_fails_closed(self):
        from core.services.portal_permissions import PORTAL_ACTION_ROLES, portal_action_roles

        self.assertIn('read', PORTAL_ACTION_ROLES)
        self.assertIn('payment.review', PORTAL_ACTION_ROLES)
        self.assertIn('BUSINESS_ADMIN', portal_action_roles('payment.review'))
        self.assertEqual(portal_action_roles('unrecognised.action'), frozenset())

    def test_user_admin_is_the_only_staff_management_surface(self):
        from core.admin import UserProfileAdminForm

        self.assertIn(get_user_model(), admin.site._registry)
        registered_labels = {model._meta.label for model in admin.site._registry}
        for removed_label in (
            'core.JawabuPortalStaffMember', 'core.ComplaintCaseStaffMember',
            'core.TatTrackerStaffMember', 'core.LegacyStaffUserMapping',
            'core.StaffIdentityReview',
        ):
            self.assertNotIn(removed_label, registered_labels)
        self.assertFalse(UserProfileAdminForm().fields['telegram_id'].required)
        self.assertTrue(UserProfileAdminForm().fields['telegram_id'].disabled)

    def test_user_admin_has_one_guided_staff_creation_action(self):
        superuser = get_user_model().objects.create_superuser(
            username='identity-admin', email='admin@example.test', password='test-password',
        )
        self.client.force_login(superuser)
        url = reverse('admin:auth_user_add_staff')

        user_list = self.client.get(reverse('admin:auth_user_changelist'))
        self.assertContains(user_list, 'Open staff lifecycle workspace')
        self.assertNotContains(user_list, 'Migrate existing staff')

        creation = self.client.get(url)
        self.assertEqual(creation.status_code, 200)
        self.assertContains(creation, 'Submit complete plan for checker approval')
        self.assertContains(creation, 'name="login_method"')
        self.assertNotContains(creation, 'Dry-run preview')

    def test_staff_creation_and_access_grants_present_role_tag_controls(self):
        from core.admin import AccessGrantAdminForm, StaffUserCreationForm

        self.assertEqual(StaffUserCreationForm.base_fields['role'].label, 'Role tag')
        self.assertIn('BRO', StaffUserCreationForm.base_fields['role'].help_text)
        self.assertEqual(AccessGrantAdminForm.base_fields['role'].label, 'Role tag')
        self.assertIn('workflow role tag', AccessGrantAdminForm.base_fields['role'].help_text)

    def test_default_user_add_redirects_to_guided_creation(self):
        superuser = get_user_model().objects.create_superuser(
            username='redirect-admin', email='admin@example.test', password='test-password',
        )
        self.client.force_login(superuser)

        response = self.client.get(reverse('admin:auth_user_add'))
        self.assertRedirects(
            response,
            reverse('admin:auth_user_staff_lifecycle'),
            fetch_redirect_response=False,
        )

    def test_non_superuser_cannot_open_staff_creation(self):
        staff_user = get_user_model().objects.create_user(
            username='ordinary-admin', password='test-password', is_staff=True,
        )
        self.client.force_login(staff_user)

        response = self.client.get(reverse('admin:auth_user_add_staff'))
        self.assertEqual(response.status_code, 403)

    def test_superuser_can_enroll_username_without_knowing_telegram_id(self):
        superuser = get_user_model().objects.create_superuser(
            username='enrollment-admin', email='admin@example.test', password='test-password',
        )
        self.client.force_login(superuser)
        checker = get_user_model().objects.create_user('enrollment-checker', is_active=True, is_staff=True)
        appoint_access_control_checker(
            actor=superuser, user=checker, reason='Independent enrollment reviewer.',
            confirmation_phrase='APPOINT FIRST CHECKER',
        )

        response = self.client.post(reverse('admin:auth_user_add_staff'), {
            'action': 'onboard',
            'login_method': 'telegram',
            'display_name': 'Pending Telegram User',
            'telegram_username': '@pending_user',
            'reason': 'Onboard the approved Telegram field officer.',
            'request_key': 'identity-onboard-telegram',
            'grants-TOTAL_FORMS': '3', 'grants-INITIAL_FORMS': '0',
            'grants-MIN_NUM_FORMS': '0', 'grants-MAX_NUM_FORMS': '8',
            'grants-0-include': 'on', 'grants-0-workflow': 'jawabu_portal',
            'grants-0-role': 'JBL_OFFICER', 'grants-0-branch': 'Nakuru',
        })

        self.assertEqual(response.status_code, 302)
        profile = UserProfile.objects.get(telegram_username='pending_user')
        self.assertEqual(profile.telegram_id, '')
        self.assertFalse(profile.user.is_active)
        self.assertFalse(profile.user.is_staff)
        self.assertFalse(profile.user.has_usable_password())
        self.assertFalse(AccessGrant.objects.filter(user=profile.user).exists())
        plan = StaffLifecycleChangePlan.objects.get(target_user=profile.user)
        self.assertEqual(plan.status, plan.STATUS_PENDING)
        approve_lifecycle_plan(plan_id=plan.pk, approver=checker)
        profile.user.refresh_from_db()
        self.assertTrue(profile.user.is_active)
        self.assertTrue(AccessGrant.objects.filter(user=profile.user, role='JBL_OFFICER').exists())

    def test_superuser_can_create_password_user_with_initial_access(self):
        superuser = get_user_model().objects.create_superuser(
            username='password-admin', email='admin@example.test', password='test-password',
        )
        self.client.force_login(superuser)
        checker = get_user_model().objects.create_user('password-checker', is_active=True, is_staff=True)
        appoint_access_control_checker(
            actor=superuser, user=checker, reason='Independent account reviewer.',
            confirmation_phrase='APPOINT FIRST CHECKER',
        )

        response = self.client.post(reverse('admin:auth_user_add_staff'), {
            'action': 'onboard',
            'login_method': 'django', 'display_name': 'Portal Administrator',
            'telegram_username': '', 'django_username': 'portal-admin',
            'email': 'portal-admin@example.test', 'password': 'secure-test-password',
            'reason': 'Onboard the approved Portal administrator.',
            'request_key': 'identity-onboard-django',
            'grants-TOTAL_FORMS': '3', 'grants-INITIAL_FORMS': '0',
            'grants-MIN_NUM_FORMS': '0', 'grants-MAX_NUM_FORMS': '8',
            'grants-0-include': 'on', 'grants-0-workflow': 'jawabu_portal',
            'grants-0-role': 'BUSINESS_ADMIN',
        })

        self.assertEqual(response.status_code, 302)
        user = get_user_model().objects.get(username='portal-admin')
        self.assertFalse(user.is_staff)
        self.assertTrue(user.check_password('secure-test-password'))
        plan = StaffLifecycleChangePlan.objects.get(target_user=user)
        approve_lifecycle_plan(plan_id=plan.pk, approver=checker)
        user.refresh_from_db()
        self.assertTrue(user.is_staff)
        self.assertTrue(AccessGrant.objects.filter(user=user, role='BUSINESS_ADMIN').exists())

        # The redirect target must render the canonical User form, including
        # dynamic AccessGrant choices, immediately after creation.
        change = self.client.get(reverse('admin:auth_user_change', args=(user.pk,)))
        self.assertEqual(change.status_code, 200)
        self.assertContains(change, 'Mini App access and lifecycle')

    def test_access_grant_inline_is_read_only_for_every_actor(self):
        from core.admin import AccessGrantInline, UnfoldUserAdmin

        root = get_user_model().objects.create_superuser(
            username='inline-root', email='inline-root@example.test', password='test-password',
        )
        target = get_user_model().objects.create_user(username='inline-target', is_active=True)
        ordinary_staff = get_user_model().objects.create_user(
            username='inline-staff', is_active=True, is_staff=True,
        )
        request = RequestFactory().post('/admin/auth/user/')
        request.session = {}
        request._messages = FallbackStorage(request)
        request.user = root
        inline = AccessGrantInline(get_user_model(), admin.site)
        self.assertFalse(inline.has_add_permission(request, target))
        self.assertFalse(inline.has_change_permission(request, target))
        self.assertFalse(inline.has_delete_permission(request, target))

        request.user = ordinary_staff
        self.assertFalse(inline.has_add_permission(request, target))
        self.assertFalse(inline.has_change_permission(request, target))
        self.assertFalse(inline.has_delete_permission(request, target))

        self.assertFalse(AccessGrant.objects.filter(user=target).exists())

    def test_user_change_view_recovers_an_unusable_persistent_connection(self):
        superuser = get_user_model().objects.create_superuser(
            username='connection-admin', email='admin@example.test', password='test-password',
        )
        user = get_user_model().objects.create_user(username='connection-target')
        self.client.force_login(superuser)

        with patch('core.admin.connections') as connections:
            connection = connections.__getitem__.return_value
            connection.connection = object()
            connection.in_atomic_block = False
            connection.is_usable.return_value = False

            response = self.client.get(reverse('admin:auth_user_change', args=(user.pk,)))

        self.assertEqual(response.status_code, 200)
        connection.close.assert_called_once_with()

    def test_user_change_view_recovers_an_aborted_postgres_transaction(self):
        superuser = get_user_model().objects.create_superuser(
            username='aborted-connection-admin', email='admin@example.test', password='test-password',
        )
        user = get_user_model().objects.create_user(username='aborted-connection-target')
        self.client.force_login(superuser)

        with patch('core.admin.connections') as connections:
            connection = connections.__getitem__.return_value
            connection.connection = SimpleNamespace(
                info=SimpleNamespace(transaction_status='INERROR'),
            )
            connection.in_atomic_block = False

            response = self.client.get(reverse('admin:auth_user_change', args=(user.pk,)))

        self.assertEqual(response.status_code, 200)
        connection.close.assert_called_once_with()

    def test_access_grant_forms_offer_choices_and_reject_scope_mismatches(self):
        from core.admin import StaffUserCreationForm

        tat_group = GroupSheetConfiguration.objects.create(
            group_id='-100-form-tat', sheet_id='tat-sheet', enabled=True,
            workflow={'type': 'tat_tracker'},
        )
        form = StaffUserCreationForm({
            'login_method': 'telegram',
            'display_name': 'Scoped User', 'telegram_username': 'scoped_user',
            'workflow': 'complaint_cases', 'role': 'OFFICER',
            'branch': '', 'product': 'business',
            'group_configuration': str(tat_group.pk),
        })

        self.assertFalse(form.is_valid())
        self.assertIn('product', form.errors)
        self.assertIn('group_configuration', form.errors)
        self.assertIn(('JBL_OFFICER', 'JBL Officer — Jawabu Portal'), form.fields['role'].choices)

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

    def test_tat_bro_dropdown_keeps_scoped_tags_in_legacy_single_group_mode(self):
        from core.services.group_config import GroupConfig
        from core.services.tat_tracker import configured_bro_users

        scoped_config = GroupSheetConfiguration.objects.create(
            group_id='-100-scoped-bro', sheet_id='scoped-sheet', sheet_name='TAT',
            workflow={'type': 'tat_tracker'},
        )
        AccessGrant.objects.create(
            user=self.user, workflow='tat_tracker', role='BRO',
            group_configuration=scoped_config,
        )

        users = configured_bro_users(
            {'type': 'tat_tracker'},
            GroupConfig(group_id='*', sheet_id='legacy-sheet', workflow={'type': 'tat_tracker'}),
        )

        self.assertIn(self.user.pk, {item['id'] for item in users})

    def test_tat_users_can_keep_multiple_active_role_tags(self):
        from core.services.telegram_identity import user_access

        self.user.groups.add(Group.objects.create(name='BRO'))
        AccessGrant.objects.create(user=self.user, workflow='tat_tracker', role='BRO')
        AccessGrant.objects.create(user=self.user, workflow='tat_tracker', role='FINANCE')

        active_roles = set(
            AccessGrant.objects.filter(
                user=self.user, workflow='tat_tracker', active=True,
            ).values_list('role', flat=True)
        )
        self.assertEqual(active_roles, {'BRO', 'FINANCE'})
        self.assertEqual(user_access(self.user, 'tat_tracker')['roles'], ['BRO', 'FINANCE'])

    def test_superuser_is_global_miniapp_break_glass_override(self):
        from core.services.telegram_identity import user_access
        from core.services.access_policies import WORKFLOW_ROLES

        superuser = get_user_model().objects.create_superuser(
            username='global-superuser', email='super@example.test', password='test-password',
        )

        access = user_access(superuser, 'jawabu_portal')
        self.assertTrue(access['authorized'])
        self.assertTrue(access['technical_override'])
        self.assertEqual(
            access['roles'],
            [role for role, _label in WORKFLOW_ROLES['jawabu_portal']],
        )
        self.assertEqual(access['branches'], [])
