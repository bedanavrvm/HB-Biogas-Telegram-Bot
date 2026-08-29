from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.contrib.admin import helpers
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.models import (
    AccessControlCheckerAssignment,
    AccessControlPolicyState,
    AccessGrant,
    ComplianceAuditEvent,
    DeletedUserIdentity,
    GroupSheetConfiguration,
    StaffLifecycleChangePlan,
    StaffTelegramOnboarding,
    TatResponsibilityAssignment,
    UserHardDeletionBatch,
    UserProfile,
)
from core.services.compliance_audit import record_event, verify_integrity
from core.services.access_grant_governance import governed_access_grant_mutation
from core.services.user_hard_delete import (
    _relation_action,
    execute_user_hard_delete,
    preview_user_hard_delete,
)


@override_settings(TELEGRAM_BOT_TOKEN='')
class UserHardDeleteServiceTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.root = User.objects.create_superuser('root-maintainer', 'root@example.test', 'password')
        self.other_root = User.objects.create_superuser('other-root', 'other@example.test', 'password')
        self.target = User.objects.create_user('departed-officer', is_active=True, is_staff=True)
        UserProfile.objects.create(user=self.target, telegram_username='departed_officer')
        AccessControlPolicyState.current()

    def test_relationship_registry_covers_every_user_reverse_relation(self):
        for relation in get_user_model()._meta.related_objects:
            self.assertIn(
                _relation_action(relation),
                {
                    'retain_original_id', 'preserve_via_tombstone',
                    'detach_reference', 'delete_personal_state',
                },
            )

    def test_hard_delete_removes_account_and_preserves_compliance_hash(self):
        audit, _ = record_event(
            workflow=ComplianceAuditEvent.WORKFLOW_ACCESS_CONTROL,
            action='test.action',
            subject_type='user',
            subject_id=str(self.target.pk),
            actor=self.target,
            deduplication_key='hard-delete-test-audit',
        )
        assignment = AccessControlCheckerAssignment.objects.create(
            user=self.target,
            appointed_by=self.root,
            appointment_reason='Test historical protected relation.',
        )
        target_session = SessionStore()
        target_session[SESSION_KEY] = str(self.target.pk)
        target_session[BACKEND_SESSION_KEY] = 'django.contrib.auth.backends.ModelBackend'
        target_session[HASH_SESSION_KEY] = self.target.get_session_auth_hash()
        target_session.save()
        target_session_key = target_session.session_key
        original_target_id = self.target.pk
        preview = preview_user_hard_delete(actor=self.root, users=[self.target])

        batch = execute_user_hard_delete(
            actor=self.root,
            users=[self.target],
            reason_category=UserHardDeletionBatch.REASON_DEPARTED,
            reason_note='Employment ended and the account is no longer required.',
            request_id='hard-delete-test-1',
            expected_fingerprint=preview.fingerprint,
        )

        self.assertFalse(get_user_model().objects.filter(pk=original_target_id).exists())
        self.assertFalse(Session.objects.filter(session_key=target_session_key).exists())
        audit.refresh_from_db()
        self.assertEqual(audit.actor_id, original_target_id)
        self.assertEqual(audit.actor_label, 'departed-officer')
        self.assertTrue(verify_integrity().ok)
        orphaned_audit = ComplianceAuditEvent.objects.select_related('actor').get(pk=audit.pk)
        self.assertIsNone(orphaned_audit.actor)
        identity = DeletedUserIdentity.objects.get(batch=batch, original_user_id=original_target_id)
        self.assertEqual(identity.username, 'departed-officer')
        assignment.refresh_from_db()
        self.assertTrue(assignment.user.username.startswith('__deleted_user_'))
        self.assertIsNotNone(assignment.revoked_at)

        self.client.force_login(self.root)
        audit_page = self.client.get(reverse('admin:core_complianceauditevent_change', args=[audit.pk]))
        self.assertEqual(audit_page.status_code, 200)
        self.assertContains(audit_page, f'historical user ID {original_target_id}')

    def test_hard_delete_discards_telegram_delivery_state_but_preserves_lifecycle_plan(self):
        plan = StaffLifecycleChangePlan.objects.create(
            action=StaffLifecycleChangePlan.ACTION_ONBOARD,
            target_user=self.target,
            status=StaffLifecycleChangePlan.STATUS_APPLIED,
            reason='Completed onboarding whose delivery state is no longer operational.',
            requested_by=self.root,
        )
        onboarding = StaffTelegramOnboarding.objects.create(
            plan=plan,
            user=self.target,
            status=StaffTelegramOnboarding.STATUS_COMPLETE,
        )
        onboarding_id = onboarding.pk
        preview = preview_user_hard_delete(actor=self.root, users=[self.target])

        self.assertIn(
            {
                'model': 'core.StaffTelegramOnboarding',
                'field': 'user',
                'action': 'delete_personal_state',
                'count': 1,
            },
            preview.relationships,
        )
        execute_user_hard_delete(
            actor=self.root,
            users=[self.target],
            reason_category=UserHardDeletionBatch.REASON_DEPARTED,
            request_id='hard-delete-telegram-onboarding',
            expected_fingerprint=preview.fingerprint,
        )

        self.assertFalse(StaffTelegramOnboarding.objects.filter(pk=onboarding_id).exists())
        plan.refresh_from_db()
        self.assertTrue(plan.target_user.username.startswith('__deleted_user_'))

    def test_batch_delete_uses_distinct_tombstones_for_unique_protected_relations(self):
        second = get_user_model().objects.create_user('second-departed', is_staff=True)
        first_assignment = AccessControlCheckerAssignment.objects.create(
            user=self.target, appointed_by=self.root, appointment_reason='First checker record.',
        )
        second_assignment = AccessControlCheckerAssignment.objects.create(
            user=second, appointed_by=self.root, appointment_reason='Second checker record.',
        )
        preview = preview_user_hard_delete(actor=self.root, users=[self.target, second])

        execute_user_hard_delete(
            actor=self.root, users=[self.target, second],
            reason_category=UserHardDeletionBatch.REASON_DEPARTED,
            request_id='hard-delete-two-checkers', expected_fingerprint=preview.fingerprint,
        )

        first_assignment.refresh_from_db()
        second_assignment.refresh_from_db()
        self.assertNotEqual(first_assignment.user_id, second_assignment.user_id)
        self.assertTrue(first_assignment.user.username.startswith('__deleted_user_'))
        self.assertTrue(second_assignment.user.username.startswith('__deleted_user_'))

    def test_request_id_is_idempotent(self):
        preview = preview_user_hard_delete(actor=self.root, users=[self.target])
        first = execute_user_hard_delete(
            actor=self.root, users=[self.target],
            reason_category=UserHardDeletionBatch.REASON_TEST,
            request_id='hard-delete-idempotent', expected_fingerprint=preview.fingerprint,
        )
        second = execute_user_hard_delete(
            actor=self.root, users=[self.target.pk],
            reason_category=UserHardDeletionBatch.REASON_TEST,
            request_id='hard-delete-idempotent', expected_fingerprint=preview.fingerprint,
        )
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(UserHardDeletionBatch.objects.count(), 1)

    def test_self_delete_and_non_superuser_are_denied(self):
        with self.assertRaises(ValidationError):
            preview_user_hard_delete(actor=self.root, users=[self.root])
        with self.assertRaises(PermissionDenied):
            preview_user_hard_delete(actor=self.target, users=[self.other_root])

    def test_direct_model_delete_is_rejected(self):
        with self.assertRaises(PermissionDenied):
            with transaction.atomic():
                self.target.delete()
        self.assertTrue(get_user_model().objects.filter(pk=self.target.pk).exists())

    def test_changed_preview_is_rejected_without_deleting_account(self):
        preview = preview_user_hard_delete(actor=self.root, users=[self.target])
        UserProfile.objects.filter(user=self.target).delete()
        with self.assertRaises(ValidationError):
            execute_user_hard_delete(
                actor=self.root, users=[self.target],
                reason_category=UserHardDeletionBatch.REASON_OTHER,
                request_id='hard-delete-stale', expected_fingerprint=preview.fingerprint,
            )
        self.assertTrue(get_user_model().objects.filter(pk=self.target.pk).exists())

    def test_live_tat_owner_is_force_unassigned_and_gap_is_reported(self):
        group = GroupSheetConfiguration.objects.create(
            group_id='-100-hard-delete-tat',
            display_name='Hard delete TAT',
            workflow={
                'type': 'tat_tracker', 'tat_notification_mode': 'shadow',
                'branches': ['Nakuru'], 'products': ['business'],
            },
        )
        with governed_access_grant_mutation('hard-delete test setup'):
            AccessGrant.objects.create(
                user=self.target, workflow='tat_tracker', role='BRO',
                group_configuration=group,
            )
        assignment = TatResponsibilityAssignment.objects.create(
            group_configuration=group, branch='Nakuru', role='BRO',
            primary_user=self.target,
        )
        preview = preview_user_hard_delete(actor=self.root, users=[self.target])

        with CaptureQueriesContext(connection) as captured_queries:
            batch = execute_user_hard_delete(
                actor=self.root, users=[self.target],
                reason_category=UserHardDeletionBatch.REASON_DEPARTED,
                request_id='hard-delete-tat-owner', expected_fingerprint=preview.fingerprint,
            )

        assignment.refresh_from_db()
        self.assertFalse(assignment.active)
        self.assertTrue(assignment.primary_user.username.startswith('__deleted_user_'))
        self.assertTrue(any(row['code'] == 'tat-responsibility-missing' for row in batch.coverage_gaps))
        task_queries = [
            row['sql'] for row in captured_queries.captured_queries
            if 'FROM "core_tatactiontask"' in row['sql']
        ]
        self.assertTrue(task_queries)
        self.assertTrue(all('SELECT DISTINCT' not in sql.upper() for sql in task_queries))


@override_settings(TELEGRAM_BOT_TOKEN='')
class UserHardDeleteAdminTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.root = User.objects.create_superuser('admin-root', 'root@example.test', 'password')
        self.other_root = User.objects.create_superuser('admin-root-two', 'root2@example.test', 'password')
        self.target = User.objects.create_user('delete-through-admin', is_staff=True)
        AccessControlPolicyState.current()
        self.client.force_login(self.root)

    def test_delete_page_uses_governed_impact_preview(self):
        response = self.client.get(reverse('admin:auth_user_delete', args=[self.target.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Hard delete user accounts')
        self.assertContains(response, 'HARD DELETE delete-through-admin')
        self.assertNotContains(response, "doesn't have permission to delete")

    def test_correct_password_and_phrase_physically_delete_user(self):
        url = reverse('admin:auth_user_delete', args=[self.target.pk])
        preview_response = self.client.get(url)
        form = preview_response.context['form']
        response = self.client.post(url, {
            'reason_category': UserHardDeletionBatch.REASON_DUPLICATE,
            'reason_note': 'Duplicate account confirmed.',
            'password': 'password',
            'confirmation': 'HARD DELETE delete-through-admin',
            'request_id': form.initial['request_id'],
            'preview_fingerprint': form.initial['preview_fingerprint'],
        })
        self.assertRedirects(response, reverse('admin:auth_user_changelist'))
        self.assertFalse(get_user_model().objects.filter(pk=self.target.pk).exists())

    def test_wrong_password_keeps_user(self):
        url = reverse('admin:auth_user_delete', args=[self.target.pk])
        preview_response = self.client.get(url)
        form = preview_response.context['form']
        response = self.client.post(url, {
            'hard_delete_confirm': '1',
            'reason_category': UserHardDeletionBatch.REASON_OTHER,
            'password': 'wrong',
            'confirmation': 'HARD DELETE delete-through-admin',
            'request_id': form.initial['request_id'],
            'preview_fingerprint': form.initial['preview_fingerprint'],
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'password is incorrect')
        self.assertTrue(get_user_model().objects.filter(pk=self.target.pk).exists())

    def test_bulk_admin_action_confirms_and_deletes_selected_user(self):
        url = reverse('admin:auth_user_changelist')
        preview_response = self.client.post(url, {
            'action': 'hard_delete_selected',
            'index': '0',
            'select_across': '0',
            helpers.ACTION_CHECKBOX_NAME: [str(self.target.pk)],
        })
        self.assertEqual(preview_response.status_code, 200)
        self.assertContains(preview_response, 'HARD DELETE 1 USERS')
        self.assertContains(
            preview_response,
            '<input type="hidden" name="hard_delete_confirm" value="1">',
            html=True,
        )
        form = preview_response.context['form']

        response = self.client.post(url, {
            'action': 'hard_delete_selected',
            'select_across': '0',
            helpers.ACTION_CHECKBOX_NAME: [str(self.target.pk)],
            'reason_category': UserHardDeletionBatch.REASON_DUPLICATE,
            'reason_note': 'Duplicate account selected from the Users list.',
            'password': 'password',
            'confirmation': 'HARD DELETE 1 USERS',
            'request_id': form.initial['request_id'],
            'preview_fingerprint': form.initial['preview_fingerprint'],
        })

        self.assertRedirects(response, url)
        self.assertFalse(get_user_model().objects.filter(pk=self.target.pk).exists())
