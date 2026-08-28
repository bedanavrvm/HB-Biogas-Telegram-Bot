from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from core.models import (
    AccessControlPolicyState,
    AccessGrant,
    GroupSheetConfiguration,
    StaffLifecycleChangePlan,
    TatEscalationRule,
    TatResponsibilityAssignment,
    TatResponsibilityBackup,
    TelegramStaffActivation,
    UserProfile,
)
from core.services.access_control import appoint_access_control_checker
from core.services.access_grant_governance import governed_access_grant_mutation
from core.services.staff_lifecycle import (
    approve_lifecycle_plan,
    create_lifecycle_plan,
    generate_telegram_activation,
)
from core.services.telegram_identity import TelegramIdentity, resolve_or_bind_telegram_user


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

    def test_checker_has_a_pending_review_queue_but_cannot_create_plans(self):
        plan = create_lifecycle_plan(
            requester=self.root, target_user=self.target,
            action=StaffLifecycleChangePlan.ACTION_ACCESS,
            reason='Show this access change in the independent review queue.',
            desired_grants=[{'workflow': 'jawabu_portal', 'role': 'JBL_OFFICER'}],
        )
        self.client.force_login(self.checker)
        response = self.client.get(reverse('admin:auth_user_staff_lifecycle'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, str(plan.pk))
        self.assertContains(response, 'Pending independent reviews')
        self.assertNotContains(response, 'Submit complete plan for checker approval')
        self.assertEqual(
            self.client.post(reverse('admin:auth_user_staff_lifecycle'), {}).status_code,
            403,
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
