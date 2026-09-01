from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from core.models import (
    AccessControlPolicyState,
    AccessGrant,
    GroupSheetConfiguration,
    StaffLifecycleChangePlan,
    StaffTelegramGroupInvitation,
    StaffTelegramOnboarding,
    TatEscalationRule,
    TatResponsibilityAssignment,
    TatResponsibilityBackup,
    TelegramStaffActivation,
    UserProfile,
)
from core.services.access_control import appoint_access_control_checker
from core.services.access_grant_governance import governed_access_grant_mutation
from core.services.staff_lifecycle import (
    apply_pending_lifecycle_plan_as_superuser,
    approve_lifecycle_plan,
    create_lifecycle_plan,
    generate_telegram_activation,
    submit_lifecycle_change,
)
from core.services.telegram_identity import TelegramIdentity, resolve_or_bind_telegram_user
from core.services.staff_telegram_onboarding import (
    deliver_staff_telegram_onboarding,
    record_governed_group_join,
    staff_activation_launcher_url,
)


class StaffLifecycleServiceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.root = User.objects.create_superuser('lifecycle-root', 'root@example.test', 'password')
        self.checker = User.objects.create_user('lifecycle-checker', is_active=True, is_staff=True)
        appoint_access_control_checker(
            actor=self.root, user=self.checker,
            reason='Establish an independent lifecycle reviewer.',
            confirmation_phrase='APPOINT FIRST CHECKER',
        )
        self.target = User.objects.create_user('field-officer', is_active=True)
        UserProfile.objects.create(user=self.target, telegram_username='field_officer')

    def test_plan_has_no_live_effect_until_independent_approval(self):
        plan = create_lifecycle_plan(
            requester=self.root, target_user=self.target,
            action=StaffLifecycleChangePlan.ACTION_ACCESS,
            reason='Assign the field officer to the approved Portal workflow.',
            desired_grants=[{'workflow': 'jawabu_portal', 'role': 'JBL_OFFICER'}],
            request_key='lifecycle-access-1',
        )
        self.assertFalse(AccessGrant.objects.filter(user=self.target, active=True).exists())

        with self.assertRaises(PermissionDenied):
            approve_lifecycle_plan(plan_id=plan.pk, approver=self.root)

        applied = approve_lifecycle_plan(plan_id=plan.pk, approver=self.checker)
        self.assertEqual(applied.status, StaffLifecycleChangePlan.STATUS_APPLIED)
        self.assertTrue(AccessGrant.objects.filter(
            user=self.target, workflow='jawabu_portal', role='JBL_OFFICER', active=True,
        ).exists())

    def test_only_one_open_plan_is_allowed_for_a_target(self):
        create_lifecycle_plan(
            requester=self.root, target_user=self.target,
            action=StaffLifecycleChangePlan.ACTION_ACCESS,
            reason='First pending access change for this staff member.',
            desired_grants=[{'workflow': 'jawabu_portal', 'role': 'JBL_OFFICER'}],
        )
        with self.assertRaises(ValidationError):
            create_lifecycle_plan(
                requester=self.root, target_user=self.target,
                action=StaffLifecycleChangePlan.ACTION_TRANSFER,
                reason='A conflicting transfer should not be accepted concurrently.',
                desired_grants=[{'workflow': 'tat_tracker', 'role': 'BRO'}],
            )

    def test_review_fingerprint_changes_when_current_staff_state_changes(self):
        from core.services.staff_lifecycle import lifecycle_submission_preview

        arguments = {
            'action': StaffLifecycleChangePlan.ACTION_ACCESS,
            'reason': 'Review an exact access change before direct application.',
            'desired_grants': [{'workflow': 'tat_tracker', 'role': 'BRO'}],
            'target_user': self.target,
        }
        first = lifecycle_submission_preview(**arguments)
        self.target.first_name = 'Updated concurrently'
        self.target.save(update_fields=['first_name'])
        second = lifecycle_submission_preview(**arguments)

        self.assertNotEqual(first['fingerprint'], second['fingerprint'])

    def test_unrelated_policy_change_marks_plan_stale_without_partial_effect(self):
        plan = create_lifecycle_plan(
            requester=self.root, target_user=self.target,
            action=StaffLifecycleChangePlan.ACTION_ACCESS,
            reason='Pending change whose policy version will become stale.',
            desired_grants=[{'workflow': 'jawabu_portal', 'role': 'JBL_OFFICER'}],
        )
        state = AccessControlPolicyState.current()
        state.version += 1
        state.save(update_fields=['version', 'updated_at'])

        result = approve_lifecycle_plan(plan_id=plan.pk, approver=self.checker)

        self.assertEqual(result.status, StaffLifecycleChangePlan.STATUS_STALE)
        self.assertFalse(AccessGrant.objects.filter(user=self.target, active=True).exists())

    def test_superuser_accounts_are_outside_the_workspace(self):
        with self.assertRaises(ValidationError):
            create_lifecycle_plan(
                requester=self.root, target_user=self.root,
                action=StaffLifecycleChangePlan.ACTION_OFFBOARD,
                reason='This must use the separate god-mode lifecycle procedure.',
            )

    def test_onboarding_activates_only_after_checker_approval(self):
        pending = get_user_model().objects.create_user('pending-officer', is_active=False)
        UserProfile.objects.create(user=pending, telegram_username='pending_officer')
        plan = create_lifecycle_plan(
            requester=self.root, target_user=pending,
            action=StaffLifecycleChangePlan.ACTION_ONBOARD,
            reason='Onboard the approved Telegram field officer.',
            desired_grants=[{'workflow': 'jawabu_portal', 'role': 'JBL_OFFICER'}],
            identity={'login_method': 'telegram', 'telegram_username': 'pending_officer'},
        )
        pending.refresh_from_db()
        self.assertFalse(pending.is_active)

        approve_lifecycle_plan(plan_id=plan.pk, approver=self.checker)
        pending.refresh_from_db()
        pending.staff_profile.refresh_from_db()
        self.assertTrue(pending.is_active)
        self.assertTrue(pending.staff_profile.telegram_metadata['activation_required'])

    def test_superuser_can_directly_apply_an_existing_pending_plan(self):
        plan = create_lifecycle_plan(
            requester=self.root, target_user=self.target,
            action=StaffLifecycleChangePlan.ACTION_ACCESS,
            reason='Apply this existing optional review directly after reconsideration.',
            desired_grants=[{'workflow': 'jawabu_portal', 'role': 'JBL_OFFICER'}],
            request_key='pending-direct-apply',
        )

        applied = apply_pending_lifecycle_plan_as_superuser(
            plan_id=plan.pk, actor=self.root, current_password='password',
            review_comment='The Superuser reviewed the exact impact and applied it directly.',
        )

        self.assertEqual(applied.status, StaffLifecycleChangePlan.STATUS_APPLIED)
        self.assertEqual(applied.decision_mode, StaffLifecycleChangePlan.DECISION_SUPERUSER)
        self.assertEqual(applied.reviewed_by, self.root)


    def test_future_leave_is_approved_without_applying_early(self):
        start = timezone.now() + timedelta(days=1)
        replacement = get_user_model().objects.create_user('leave-replacement', is_active=True)
        plan = create_lifecycle_plan(
            requester=self.root, target_user=self.target,
            action=StaffLifecycleChangePlan.ACTION_LEAVE,
            reason='Schedule the approved temporary staff leave period.',
            replacement_user=replacement, leave_from=start,
            leave_until=start + timedelta(days=2),
        )
        result = approve_lifecycle_plan(plan_id=plan.pk, approver=self.checker)
        self.assertEqual(result.status, StaffLifecycleChangePlan.STATUS_SCHEDULED)
        self.target.refresh_from_db()
        self.assertTrue(self.target.is_active)

    def test_early_return_restores_backup_routing_from_leave_snapshot(self):
        group = GroupSheetConfiguration.objects.create(
            group_id='-100-lifecycle-return', display_name='Lifecycle return',
            sheet_id='sheet-lifecycle', sheet_name='TRACKER-Business',
            workflow={'type': 'tat_tracker'},
        )
        primary = get_user_model().objects.create_user('routing-primary', is_active=True)
        replacement = get_user_model().objects.create_user('routing-replacement', is_active=True)
        for user in (self.target, primary, replacement):
            AccessGrant.objects.create(
                user=user, workflow='tat_tracker', role='BRO',
                group_configuration=group,
            )
        TatEscalationRule.objects.create(
            group_configuration=group, branch='Nakuru', threshold_percent=100,
            routing_role=TatEscalationRule.ROUTE_RESPONSIBLE,
        )
        assignment = TatResponsibilityAssignment.objects.create(
            group_configuration=group, branch='Nakuru', role='BRO',
            primary_user=primary,
        )
        original_backup = TatResponsibilityBackup.objects.create(
            assignment=assignment, user=self.target, rank=1, threshold_percent=100,
        )
        leave = create_lifecycle_plan(
            requester=self.root, target_user=self.target,
            action=StaffLifecycleChangePlan.ACTION_LEAVE,
            reason='Temporarily move backup responsibility during approved leave.',
            replacement_user=replacement,
            leave_until=timezone.now() + timedelta(days=2),
        )
        approve_lifecycle_plan(plan_id=leave.pk, approver=self.checker)
        original_backup.refresh_from_db()
        self.assertEqual(original_backup.user, replacement)

        return_plan = create_lifecycle_plan(
            requester=self.root, target_user=self.target,
            action=StaffLifecycleChangePlan.ACTION_RETURN,
            reason='Restore the staff member after returning from temporary leave.',
        )
        approve_lifecycle_plan(plan_id=return_plan.pk, approver=self.checker)
        original_backup.refresh_from_db()
        self.assertEqual(original_backup.user, self.target)

    def test_checker_is_redirected_to_the_dedicated_review_queue_and_cannot_create_plans(self):
        plan = create_lifecycle_plan(
            requester=self.root, target_user=self.target,
            action=StaffLifecycleChangePlan.ACTION_ACCESS,
            reason='Show this access change in the independent review queue.',
            desired_grants=[{'workflow': 'jawabu_portal', 'role': 'JBL_OFFICER'}],
        )
        self.client.force_login(self.checker)
        response = self.client.get(reverse('admin:auth_user_staff_lifecycle'))
        self.assertRedirects(response, reverse('admin:auth_user_staff_approvals'))
        queue = self.client.get(reverse('admin:auth_user_staff_approvals'))
        self.assertContains(queue, str(plan.target_user))
        self.assertEqual(
            self.client.post(reverse('admin:auth_user_staff_lifecycle'), {}).status_code,
            403,
        )


class DirectSuperuserLifecycleTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.root = User.objects.create_superuser('direct-root', 'root@example.test', 'password')
        AccessControlPolicyState.current()
        self.identity = {
            'display_name': 'Direct Officer',
            'login_method': 'django',
            'django_username': 'direct-officer',
            'telegram_username': '',
            'email': 'direct@example.test',
            'django_admin_login': True,
        }
        self.grants = [{'workflow': 'jawabu_portal', 'role': 'JBL_OFFICER'}]

    def _submit(self, **overrides):
        values = {
            'requester': self.root,
            'action': StaffLifecycleChangePlan.ACTION_ONBOARD,
            'reason': 'Create the approved field officer directly and atomically.',
            'desired_grants': self.grants,
            'request_key': 'direct-onboard-1',
            'identity': self.identity,
            'new_user_password': 'initial-password',
            'current_password': '',
            'decision_mode': StaffLifecycleChangePlan.DECISION_SUPERUSER,
        }
        values.update(overrides)
        return submit_lifecycle_change(**values)

    def test_direct_onboarding_needs_no_checker_and_applies_atomically(self):
        plan, created = self._submit()
        plan.target_user.refresh_from_db()
        self.assertTrue(created)
        self.assertEqual(plan.status, StaffLifecycleChangePlan.STATUS_APPLIED)
        self.assertEqual(plan.decision_mode, StaffLifecycleChangePlan.DECISION_SUPERUSER)
        self.assertEqual(plan.reviewed_by, self.root)
        self.assertTrue(plan.target_user.is_active)
        self.assertTrue(plan.target_user.is_staff)
        self.assertTrue(AccessGrant.objects.filter(
            user=plan.target_user, workflow='jawabu_portal', role='JBL_OFFICER', active=True,
        ).exists())

    def test_repeated_request_returns_original_user_and_plan(self):
        first, first_created = self._submit()
        second, second_created = self._submit()
        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.target_user_id, second.target_user_id)
        self.assertEqual(get_user_model().objects.filter(username='direct-officer').count(), 1)

    def test_request_key_reuse_with_changed_details_is_rejected(self):
        self._submit()
        with self.assertRaises(ValidationError):
            self._submit(reason='A different lifecycle operation must not reuse the same request key.')
        self.assertEqual(get_user_model().objects.filter(username='direct-officer').count(), 1)

    def test_direct_onboarding_uses_authenticated_superuser_session_without_password(self):
        plan, created = self._submit(current_password='')
        self.assertTrue(created)
        self.assertEqual(plan.status, plan.STATUS_APPLIED)
        self.assertTrue(get_user_model().objects.filter(username='direct-officer').exists())

    def test_launcher_repair_opens_with_current_exact_grants_preloaded(self):
        plan, _ = self._submit(current_password='')
        self.client.force_login(self.root)

        response = self.client.get(
            reverse('admin:auth_user_staff_lifecycle'),
            {
                'action': StaffLifecycleChangePlan.ACTION_ACCESS,
                'target_user': plan.target_user_id,
                'repair': 'launcher',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Launcher-access repair')
        initial = response.context['grant_formset'].initial
        self.assertEqual(initial[0]['workflow'], 'jawabu_portal')
        self.assertEqual(initial[0]['role'], 'JBL_OFFICER')
        self.assertTrue(initial[0]['all_groups'])

    def test_authenticated_superuser_scope_change_does_not_require_password_reentry(self):
        target = get_user_model().objects.create_user('existing-officer', is_active=True)
        plan, created = self._submit(
            action=StaffLifecycleChangePlan.ACTION_ACCESS,
            target_user=target,
            identity={},
            new_user_password='',
            request_key='direct-access-session-authorized',
            current_password='incorrect',
        )

        self.assertTrue(created)
        self.assertEqual(plan.status, plan.STATUS_APPLIED)
        self.assertTrue(AccessGrant.objects.filter(
            user=target, workflow='jawabu_portal', role='JBL_OFFICER', active=True,
        ).exists())

    def test_admin_direct_onboarding_without_checker_uses_preview_then_applies(self):
        self.client.force_login(self.root)
        url = reverse('admin:auth_user_staff_lifecycle')
        payload = {
            'action': StaffLifecycleChangePlan.ACTION_ONBOARD,
            'display_name': 'Admin Direct Officer',
            'login_method': 'django',
            'django_username': 'admin-direct-officer',
            'email': 'admin-direct@example.test',
            'password': 'initial-password',
            'reason': 'Create this ordinary staff account directly as Superuser.',
            'request_key': 'admin-direct-onboard-1',
            'grants-TOTAL_FORMS': '1',
            'grants-INITIAL_FORMS': '0',
            'grants-MIN_NUM_FORMS': '0',
            'grants-MAX_NUM_FORMS': '20',
            'grants-0-include': 'on',
            'grants-0-workflow': 'jawabu_portal',
            'grants-0-role': 'JBL_OFFICER',
            'grants-0-all_branches': 'on',
            'grants-0-all_products': 'on',
            'grants-0-all_groups': 'on',
            'lifecycle_action': 'apply_now',
        }
        preview = self.client.post(url, payload)
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, 'Confirm exact direct change')
        self.assertFalse(get_user_model().objects.filter(username='admin-direct-officer').exists())

        fingerprint = preview.context['direct_preview']['fingerprint']
        confirmed = self.client.post(url, {
            **payload,
            # Credentials are intentionally excluded from the visible review
            # fingerprint and may be re-entered after PasswordInput clears.
            'password': 'replacement-initial-password',
            'lifecycle_action': 'confirm_direct',
            'preview_fingerprint': fingerprint,
        })
        self.assertEqual(confirmed.status_code, 302)
        user = get_user_model().objects.get(username='admin-direct-officer')
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password('replacement-initial-password'))
        plan = StaffLifecycleChangePlan.objects.get(request_key='admin-direct-onboard-1')
        self.assertEqual(plan.status, plan.STATUS_APPLIED)
        self.assertEqual(plan.decision_mode, plan.DECISION_SUPERUSER)

        replay = self.client.post(url, {
            **payload,
            'password': 'replacement-initial-password',
            'lifecycle_action': 'confirm_direct',
            'preview_fingerprint': fingerprint,
        })
        self.assertRedirects(
            replay, reverse('admin:auth_user_staff_lifecycle_plan', args=[plan.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(
            get_user_model().objects.filter(username='admin-direct-officer').count(), 1,
        )

    def test_direct_preview_does_not_conflict_when_credential_is_reentered(self):
        from core.services.staff_lifecycle import lifecycle_submission_preview

        values = {
            'action': StaffLifecycleChangePlan.ACTION_ONBOARD,
            'reason': 'Create a Django staff user after reviewing the non-secret lifecycle details.',
            'desired_grants': [{'workflow': 'jawabu_portal', 'role': 'JBL_OFFICER'}],
            'identity': {
                'display_name': 'Credential Review Officer',
                'login_method': 'django',
                'django_username': 'credential-review-officer',
            },
        }

        first = lifecycle_submission_preview(**values, new_user_password='first-entry')
        second = lifecycle_submission_preview(**values, new_user_password='reentered-value')

        self.assertEqual(first['fingerprint'], second['fingerprint'])


class StaffApprovalQueueAdminTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.root = User.objects.create_superuser('queue-root', 'root@example.test', 'password')
        self.checker = User.objects.create_user('queue-checker', is_active=True, is_staff=True)
        appoint_access_control_checker(
            actor=self.root, user=self.checker,
            reason='Create the reviewer used by the staff approval queue test.',
            confirmation_phrase='APPOINT FIRST CHECKER',
        )
        self.target = User.objects.create_user('queue-target', is_active=True)
        UserProfile.objects.create(user=self.target)
        AccessControlPolicyState.current()
        self.plan = create_lifecycle_plan(
            requester=self.root, target_user=self.target,
            action=StaffLifecycleChangePlan.ACTION_ACCESS,
            reason='Queue this optional access change for independent review.',
            desired_grants=[{'workflow': 'jawabu_portal', 'role': 'JBL_OFFICER'}],
            request_key='queue-review-1',
        )

    def test_checker_has_a_dedicated_pending_approval_queue(self):
        self.client.force_login(self.checker)
        response = self.client.get(reverse('admin:auth_user_staff_approvals'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Staff approvals')
        self.assertContains(response, '1 pending')
        self.assertContains(response, str(self.target))
        self.assertContains(
            response,
            reverse('admin:auth_user_staff_lifecycle_plan', args=[self.plan.pk]),
        )


class TelegramStaffActivationTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.root = User.objects.create_superuser('activation-root', 'root@example.test', 'password')
        self.user = User.objects.create_user('tg_pending_person', is_active=True)
        self.profile = UserProfile.objects.create(
            user=self.user, telegram_username='intended_person',
            telegram_metadata={'activation_required': True},
        )
        self.identity = TelegramIdentity(
            telegram_id='998877', username='intended_person', first_name='Intended',
            last_name='Person', payload={'id': 998877, 'username': 'intended_person'},
        )

    def test_activation_requires_matching_single_use_code(self):
        challenge, code = generate_telegram_activation(user=self.user, actor=self.root)
        self.assertFalse(resolve_or_bind_telegram_user(self.identity, activation_code='00000000'))
        self.assertEqual(resolve_or_bind_telegram_user(self.identity, activation_code=code), self.user)
        self.profile.refresh_from_db()
        challenge.refresh_from_db()
        self.assertEqual(self.profile.telegram_id, '998877')
        self.assertFalse(self.profile.telegram_metadata['activation_required'])
        self.assertIsNotNone(challenge.consumed_at)

    def test_new_code_invalidates_the_previous_code(self):
        first, first_code = generate_telegram_activation(user=self.user, actor=self.root)
        _second, second_code = generate_telegram_activation(user=self.user, actor=self.root)
        first.refresh_from_db()
        self.assertIsNotNone(first.invalidated_at)
        self.assertFalse(resolve_or_bind_telegram_user(self.identity, activation_code=first_code))
        self.assertEqual(resolve_or_bind_telegram_user(self.identity, activation_code=second_code), self.user)


@override_settings(TELEGRAM_BOT_TOKEN='test-token')
class StaffTelegramOnboardingTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.root = User.objects.create_superuser('telegram-onboard-root', 'root@example.test', 'password')
        AccessControlPolicyState.current()
        self.group = GroupSheetConfiguration.objects.create(
            group_id='-100staffgroup', display_name='Nakuru TAT', enabled=True,
            workflow={'type': 'tat_tracker', 'mini_app_launchers': ['tat_tracker']},
        )
        self.identity = {
            'display_name': 'Telegram Officer', 'login_method': 'telegram',
            'telegram_username': 'telegram_officer', 'django_username': '',
            'email': '', 'django_admin_login': False,
        }

    def _onboard(self, **overrides):
        values = {
            'requester': self.root,
            'action': StaffLifecycleChangePlan.ACTION_ONBOARD,
            'reason': 'Create and activate the Telegram staff member directly.',
            'desired_grants': [{'workflow': 'tat_tracker', 'role': 'BRO'}],
            'telegram_group_ids': [self.group.pk],
            'request_key': 'telegram-onboard-1',
            'identity': self.identity,
            'current_password': 'password',
            'decision_mode': StaffLifecycleChangePlan.DECISION_SUPERUSER,
        }
        values.update(overrides)
        return submit_lifecycle_change(**values)

    def test_direct_onboarding_projects_selected_group_once(self):
        first, created = self._onboard()
        second, replay_created = self._onboard()

        self.assertTrue(created)
        self.assertFalse(replay_created)
        self.assertEqual(first.pk, second.pk)
        onboarding = StaffTelegramOnboarding.objects.get(plan=first)
        self.assertEqual(onboarding.status, onboarding.STATUS_PENDING)
        self.assertEqual(
            list(onboarding.group_invitations.values_list('group_configuration_id', flat=True)),
            [self.group.pk],
        )

    @override_settings(
        APP_BASE_URL='https://example.test',
        TELEGRAM_BOT_USERNAME='jbl_bot',
        SPIN_MINI_APP_SHORT_NAME='spin-credit',
    )
    @patch('core.services.staff_telegram_onboarding.publish_group_launcher')
    @patch('core.services.staff_telegram_onboarding.telegram_api_call')
    def test_verified_staff_can_receive_additional_workflow_access_and_welcome_once(
        self, telegram_call, publish_launcher,
    ):
        user = get_user_model().objects.create_user(
            username='existing-telegram-staff', first_name='Existing', last_name='Staff',
            is_active=True,
        )
        UserProfile.objects.create(
            user=user, telegram_id='776655', telegram_username='existing_staff',
        )
        existing_grant = AccessGrant.objects.create(
            user=user, workflow='tat_tracker', role='BRO', group_configuration=self.group,
        )
        spin_group = GroupSheetConfiguration.objects.create(
            group_id='-100spinstaffgroup', display_name='JBL SPIN', enabled=True,
            workflow={
                'type': 'spin_credit_analysis',
                'mini_app_launchers': ['spin_credit'],
            },
        )

        def api_result(method, payload):
            if method == 'createChatInviteLink':
                self.assertEqual(payload['chat_id'], spin_group.group_id)
                self.assertEqual(payload['member_limit'], 1)
                return {'ok': True, 'result': {'invite_link': 'https://t.me/+spin-one-use'}}
            self.assertEqual(method, 'sendMessage')
            self.assertEqual(payload['chat_id'], '776655')
            self.assertIn('Additional JBL Tools Are Ready, Existing Staff!', payload['text'])
            self.assertIn('Your existing account remains active.', payload['text'])
            self.assertNotIn('Mini App', payload['text'])
            buttons = [
                button
                for row in payload['reply_markup']['inline_keyboard']
                for button in row
            ]
            self.assertIn('SPIN / CRB', {button['text'] for button in buttons})
            self.assertIn('Join JBL SPIN', {button['text'] for button in buttons})
            return {'ok': True, 'result': {'message_id': 91}}

        telegram_call.side_effect = api_result
        values = {
            'requester': self.root,
            'target_user': user,
            'action': StaffLifecycleChangePlan.ACTION_ADD_WORKFLOW_ACCESS,
            'reason': 'Add the verified staff member to the SPIN workflow and group.',
            'desired_grants': [{
                'workflow': 'spin_credit_analysis', 'role': 'CREDIT_ANALYST',
                'group_configuration': spin_group,
            }],
            'telegram_group_ids': [spin_group.pk],
            'request_key': 'add-spin-access-1',
            'decision_mode': StaffLifecycleChangePlan.DECISION_SUPERUSER,
        }
        with self.captureOnCommitCallbacks(execute=True):
            plan, created = submit_lifecycle_change(**values)
        replay, replay_created = submit_lifecycle_change(**values)

        self.assertTrue(created)
        self.assertFalse(replay_created)
        self.assertEqual(replay.pk, plan.pk)
        self.assertTrue(AccessGrant.objects.filter(pk=existing_grant.pk, active=True).exists())
        self.assertTrue(AccessGrant.objects.filter(
            user=user, workflow='spin_credit_analysis', role='CREDIT_ANALYST',
            group_configuration=spin_group, active=True,
        ).exists())
        self.assertFalse(TelegramStaffActivation.objects.filter(user=user).exists())
        onboarding = StaffTelegramOnboarding.objects.get(plan=plan)
        self.assertEqual(onboarding.status, onboarding.STATUS_COMPLETE)
        self.assertIsNotNone(onboarding.activated_at)
        self.assertEqual(onboarding.group_invitations.get().status, StaffTelegramGroupInvitation.STATUS_SENT)
        self.assertEqual(telegram_call.call_count, 2)
        publish_launcher.assert_called_once_with(
            spin_group,
            operation_key_suffix=f'staff-{onboarding.pk}-{onboarding.revision}',
        )

    def test_additional_workflow_onboarding_requires_verified_identity_and_group(self):
        user = get_user_model().objects.create_user(username='unverified-existing', is_active=True)
        UserProfile.objects.create(user=user, telegram_username='unverified_existing')

        with self.assertRaisesMessage(
            ValidationError, 'Additional workflow onboarding requires an existing verified Telegram identity.',
        ):
            submit_lifecycle_change(
                requester=self.root,
                target_user=user,
                action=StaffLifecycleChangePlan.ACTION_ADD_WORKFLOW_ACCESS,
                reason='Add another workflow for this existing staff member.',
                desired_grants=[{'workflow': 'tat_tracker', 'role': 'BRO'}],
                telegram_group_ids=[self.group.pk],
                request_key='add-unverified-access-1',
            )

        user.staff_profile.telegram_id = '112233'
        user.staff_profile.save(update_fields=['telegram_id', 'updated_at'])
        with self.assertRaisesMessage(
            ValidationError, 'Select at least one Telegram group for the additional workflow welcome.',
        ):
            submit_lifecycle_change(
                requester=self.root,
                target_user=user,
                action=StaffLifecycleChangePlan.ACTION_ADD_WORKFLOW_ACCESS,
                reason='Add another workflow for this verified staff member.',
                desired_grants=[{'workflow': 'tat_tracker', 'role': 'BRO'}],
                telegram_group_ids=[],
                request_key='add-without-group-1',
            )

    def test_admin_exposes_additive_workflow_action_with_current_access_read_only(self):
        user = get_user_model().objects.create_user(username='existing-admin-target', is_active=True)
        UserProfile.objects.create(
            user=user, telegram_id='445566', telegram_username='existing_admin_target',
        )
        AccessGrant.objects.create(
            user=user, workflow='tat_tracker', role='BRO', group_configuration=self.group,
        )
        self.client.force_login(self.root)

        response = self.client.get(
            reverse('admin:auth_user_staff_lifecycle'),
            {'action': StaffLifecycleChangePlan.ACTION_ADD_WORKFLOW_ACCESS, 'target_user': user.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add workflow or group access')
        self.assertContains(response, 'Additive access only')
        self.assertContains(response, 'Existing grants remain active and will not be removed.')
        self.assertContains(response, 'tat_tracker')
        self.assertContains(response, 'BRO')

    def test_global_tat_grant_covers_selected_onboarding_group(self):
        from core.services.staff_access_readiness import onboarding_readiness
        from core.services.telegram_identity import user_access

        plan, _ = self._onboard()
        profile = plan.target_user.staff_profile
        profile.telegram_id = '998877'
        profile.save(update_fields=['telegram_id', 'updated_at'])

        access = user_access(plan.target_user, 'tat_tracker', group_configuration=self.group)
        self.assertTrue(access['authorized'])
        self.assertEqual([grant.group_configuration_id for grant in access['grants']], [None])
        readiness = onboarding_readiness(plan.telegram_onboarding)
        self.assertTrue(readiness['ready'])
        self.assertEqual(readiness['rows'][0]['reason_code'], 'access_ready')

    @patch('core.services.staff_telegram_onboarding.publish_group_launcher')
    @patch('core.services.staff_telegram_onboarding.telegram_api_call')
    def test_delivery_stops_before_side_effects_when_runtime_group_scope_fails(
        self, telegram_call, publish_launcher,
    ):
        from core.services.staff_access_readiness import onboarding_readiness

        plan, _ = self._onboard()
        other_group = GroupSheetConfiguration.objects.create(
            group_id='-100otherstaffgroup', display_name='Other TAT', enabled=True,
            workflow={'type': 'tat_tracker', 'mini_app_launchers': ['tat_tracker']},
        )
        AccessGrant.objects.filter(user=plan.target_user, workflow='tat_tracker').update(
            group_configuration=other_group,
        )
        profile = plan.target_user.staff_profile
        profile.telegram_id = '998877'
        profile.save(update_fields=['telegram_id', 'updated_at'])

        readiness = onboarding_readiness(plan.telegram_onboarding)
        self.assertFalse(readiness['ready'])
        self.assertEqual(readiness['reason_code'], 'group_scope_mismatch')
        result = deliver_staff_telegram_onboarding(onboarding=plan.telegram_onboarding)

        self.assertEqual(result['status'], StaffTelegramOnboarding.STATUS_ATTENTION)
        self.assertEqual(result['readiness']['reason_code'], 'group_scope_mismatch')
        self.assertEqual(
            result['message'],
            'Your account has been verified, but your assigned tools are not ready yet. '
            'Please contact your administrator to check your access.',
        )
        telegram_call.assert_not_called()
        publish_launcher.assert_not_called()

    def test_scope_set_expands_multiple_groups_into_exact_grants(self):
        from core.admin import StaffLifecycleGrantFormSet

        second_group = GroupSheetConfiguration.objects.create(
            group_id='-100secondstaffgroup', display_name='Second TAT', enabled=True,
            workflow={'type': 'tat_tracker', 'mini_app_launchers': ['tat_tracker']},
        )
        formset = StaffLifecycleGrantFormSet(data={
            'grants-TOTAL_FORMS': '1', 'grants-INITIAL_FORMS': '0',
            'grants-MIN_NUM_FORMS': '0', 'grants-MAX_NUM_FORMS': '20',
            'grants-0-include': 'on', 'grants-0-workflow': 'tat_tracker',
            'grants-0-role': 'BRO', 'grants-0-all_branches': 'on',
            'grants-0-all_products': 'on',
            'grants-0-groups': [str(self.group.pk), str(second_group.pk)],
        }, prefix='grants')

        self.assertTrue(formset.is_valid(), formset.errors)
        expanded = formset.forms[0].cleaned_data['expanded_grants']
        self.assertEqual(len(expanded), 2)
        self.assertEqual(
            {row['group_configuration_id'] for row in expanded},
            {self.group.pk, second_group.pk},
        )

    def test_launcher_readiness_command_is_diagnostic_only(self):
        plan, _ = self._onboard()
        profile = plan.target_user.staff_profile
        profile.telegram_id = '998877'
        profile.save(update_fields=['telegram_id', 'updated_at'])
        before_grants = list(AccessGrant.objects.filter(
            user=plan.target_user,
        ).values_list('pk', 'active', 'group_configuration_id'))
        output = StringIO()

        call_command('audit_staff_launcher_readiness', '--json', stdout=output)

        payload = output.getvalue()
        self.assertIn('"mode": "read_only"', payload)
        self.assertIn('"ready": true', payload)
        self.assertEqual(
            list(AccessGrant.objects.filter(user=plan.target_user).values_list(
                'pk', 'active', 'group_configuration_id',
            )),
            before_grants,
        )

    @override_settings(
        TELEGRAM_BOT_USERNAME='jbl_bot',
        STAFF_ACTIVATION_MINI_APP_SHORT_NAME='staff-activation',
    )
    def test_activation_pack_uses_botfather_miniapp_link(self):
        self.assertEqual(
            staff_activation_launcher_url(fallback_url='https://example.test/api/staff/activate/'),
            'https://t.me/jbl_bot/staff-activation',
        )

    def test_incompatible_group_is_rejected_before_user_creation(self):
        complaint_group = GroupSheetConfiguration.objects.create(
            group_id='-100complaints', display_name='Complaints', enabled=True,
            workflow={'type': 'case', 'mini_app_launchers': ['complaint_cases']},
        )
        with self.assertRaises(ValidationError):
            self._onboard(telegram_group_ids=[complaint_group.pk])
        self.assertFalse(get_user_model().objects.filter(username='tg_telegram_officer').exists())

    @override_settings(
        TELEGRAM_BOT_USERNAME='jbl_bot',
        STAFF_ACTIVATION_MINI_APP_SHORT_NAME='staff-activation',
    )
    def test_admin_direct_onboarding_shows_one_time_activation_pack(self):
        self.client.force_login(self.root)
        url = reverse('admin:auth_user_staff_lifecycle')
        payload = {
            'action': StaffLifecycleChangePlan.ACTION_ONBOARD,
            'display_name': 'Admin Telegram Officer',
            'login_method': 'telegram',
            'telegram_username': 'admin_telegram_officer',
            'reason': 'Create this Telegram staff account directly as Superuser.',
            'request_key': 'admin-telegram-onboard-1',
            'telegram_groups': [str(self.group.pk)],
            'grants-TOTAL_FORMS': '1', 'grants-INITIAL_FORMS': '0',
            'grants-MIN_NUM_FORMS': '0', 'grants-MAX_NUM_FORMS': '20',
            'grants-0-include': 'on', 'grants-0-workflow': 'tat_tracker',
            'grants-0-role': 'BRO', 'grants-0-all_branches': 'on',
            'grants-0-all_products': 'on', 'grants-0-all_groups': 'on',
            'lifecycle_action': 'apply_now',
        }
        preview = self.client.post(url, payload)
        self.assertEqual(preview.status_code, 200)
        fingerprint = preview.context['direct_preview']['fingerprint']
        confirmed = self.client.post(url, {
            **payload, 'lifecycle_action': 'confirm_direct',
            'preview_fingerprint': fingerprint, 'superuser_password': 'password',
        })
        plan = StaffLifecycleChangePlan.objects.get(request_key='admin-telegram-onboard-1')
        self.assertRedirects(
            confirmed, reverse('admin:auth_user_staff_lifecycle_plan', args=[plan.pk]),
            fetch_redirect_response=False,
        )
        result = self.client.get(reverse('admin:auth_user_staff_lifecycle_plan', args=[plan.pk]))
        self.assertContains(result, 'Copy and send this activation pack privately')
        self.assertContains(result, 'Copy activation pack')
        self.assertContains(result, 'Time remaining:')
        self.assertContains(result, 'data-expires-at=')
        self.assertContains(result, 'data-server-now=')
        self.assertContains(result, 'miniapp/runtime.js')
        self.assertContains(result, 'https://t.me/jbl_bot/staff-activation')
        self.assertContains(
            result,
            'href="https://t.me/jbl_bot/staff-activation"',
        )
        self.assertContains(result, 'target="_blank"')
        self.assertContains(result, self.group.display_name)

        second_view = self.client.get(reverse('admin:auth_user_staff_lifecycle_plan', args=[plan.pk]))
        self.assertNotContains(second_view, 'Copyable activation pack')

    @patch('core.services.staff_telegram_onboarding.publish_group_launcher')
    @patch('core.services.staff_telegram_onboarding.telegram_api_call')
    def test_delivery_publishes_launcher_sends_one_use_invite_and_private_welcome(
        self, telegram_call, publish_launcher,
    ):
        plan, _ = self._onboard()
        onboarding = plan.telegram_onboarding
        self.group.display_name = self.group.group_id
        self.group.save(update_fields=['display_name', 'updated_at'])
        profile = plan.target_user.staff_profile
        profile.telegram_id = '998877'
        profile.save(update_fields=['telegram_id', 'updated_at'])

        def api_result(method, payload):
            if method == 'createChatInviteLink':
                self.assertEqual(payload['member_limit'], 1)
                return {'ok': True, 'result': {'invite_link': 'https://t.me/+one-use'}}
            self.assertEqual(method, 'sendMessage')
            self.assertEqual(payload['chat_id'], '998877')
            self.assertIn('Welcome to JBL Field Workflow', payload['text'])
            self.assertIn('Your staff account has been verified', payload['text'])
            buttons = [button for row in payload['reply_markup']['inline_keyboard'] for button in row]
            self.assertIn('Join assigned JBL group', {button['text'] for button in buttons})
            self.assertNotIn(self.group.group_id, str(buttons))
            return {'ok': True, 'result': {'message_id': 77}}

        telegram_call.side_effect = api_result
        result = deliver_staff_telegram_onboarding(onboarding=onboarding)

        self.assertEqual(result['status'], onboarding.STATUS_COMPLETE)
        publish_launcher.assert_called_once_with(
            self.group,
            operation_key_suffix=f'staff-{onboarding.pk}-{onboarding.revision}',
        )
        invitation = StaffTelegramGroupInvitation.objects.get(onboarding=onboarding)
        self.assertEqual(invitation.status, invitation.STATUS_SENT)
        self.assertTrue(invitation.invite_digest)
        self.assertEqual(invitation.pending_invite_url, '')
        self.assertEqual(telegram_call.call_count, 2)

    @patch('core.services.staff_telegram_onboarding.publish_group_launcher')
    def test_governed_join_is_recorded_and_fresh_launcher_is_pinned(self, publish_launcher):
        plan, _ = self._onboard()
        onboarding = plan.telegram_onboarding
        profile = plan.target_user.staff_profile
        profile.telegram_id = '998877'
        profile.save(update_fields=['telegram_id', 'updated_at'])
        invitation = onboarding.group_invitations.get()
        invitation.status = invitation.STATUS_SENT
        invitation.save(update_fields=['status', 'updated_at'])

        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(record_governed_group_join(
                telegram_id='998877', group_id=self.group.group_id,
            ))
        invitation.refresh_from_db()
        self.assertEqual(invitation.status, invitation.STATUS_JOINED)
        publish_launcher.assert_called_once_with(
            self.group,
            operation_key_suffix=f'staff-join:{invitation.pk}',
            force_new_message=True,
        )

        with self.captureOnCommitCallbacks(execute=True):
            self.assertFalse(record_governed_group_join(
                telegram_id='998877', group_id=self.group.group_id,
            ))
        publish_launcher.assert_called_once()

    def test_governed_join_suppresses_duplicate_public_welcome(self):
        from core.api.views import _process_new_chat_members

        plan, _ = self._onboard()
        profile = plan.target_user.staff_profile
        profile.telegram_id = '998877'
        profile.save(update_fields=['telegram_id', 'updated_at'])
        invitation = plan.telegram_onboarding.group_invitations.get()
        invitation.status = invitation.STATUS_SENT
        invitation.save(update_fields=['status', 'updated_at'])

        result = _process_new_chat_members({
            'chat': {'id': self.group.group_id},
            'new_chat_members': [{'id': 998877, 'first_name': 'Telegram', 'is_bot': False}],
        })

        self.assertEqual(result['status'], 'ignored')
        self.assertIn('private welcome', result['reason'])


class AccessGrantGovernanceTests(TestCase):
    @override_settings(ACCESS_GRANT_GOVERNANCE_ENFORCED=True)
    def test_direct_runtime_write_is_rejected_but_governed_service_context_works(self):
        user = get_user_model().objects.create_user('guarded-user', is_active=True)
        with self.assertRaises(PermissionDenied):
            AccessGrant.objects.create(user=user, workflow='jawabu_portal', role='JBL_OFFICER')
        with governed_access_grant_mutation('focused governance test'):
            grant = AccessGrant.objects.create(
                user=user, workflow='jawabu_portal', role='JBL_OFFICER',
            )
        self.assertTrue(grant.active)

        with self.assertRaises(PermissionDenied):
            AccessGrant.objects.filter(pk=grant.pk).update(active=False)
        with self.assertRaises(PermissionDenied):
            AccessGrant.objects.filter(pk=grant.pk).delete()

        with governed_access_grant_mutation('focused governed bulk update'):
            AccessGrant.objects.filter(pk=grant.pk).update(active=False)
        grant.refresh_from_db()
        self.assertFalse(grant.active)


class CheckerBootstrapTests(TestCase):
    def test_first_checker_requires_the_bootstrap_confirmation_phrase(self):
        User = get_user_model()
        root = User.objects.create_superuser('bootstrap-root', 'root@example.test', 'password')
        checker = User.objects.create_user('bootstrap-checker', is_active=True, is_staff=True)
        with self.assertRaises(ValidationError):
            appoint_access_control_checker(
                actor=root, user=checker, reason='Create the first independent checker.',
            )
        assignment, created = appoint_access_control_checker(
            actor=root, user=checker, reason='Create the first independent checker.',
            confirmation_phrase='APPOINT FIRST CHECKER',
        )
        self.assertTrue(created)
        self.assertEqual(assignment.source, assignment.SOURCE_BOOTSTRAP)
