"""Browser-only identity administration, rollback, retry and compatibility."""
import json
from datetime import timedelta
from io import StringIO
from unittest import skipUnless
from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from allauth.mfa.recovery_codes.internal.auth import RecoveryCodes
from allauth.mfa.totp.internal.auth import TOTP, generate_totp_secret
from django.contrib import admin
from django.contrib.auth import SESSION_KEY, get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from core.models import AccessGrant, ComplianceAuditChainState, ComplianceAuditEvent, UserHardDeletionBatch
from core.services.compliance_audit import verify_integrity
from core.services.user_hard_delete import execute_user_hard_delete, preview_user_hard_delete

from .assurance import ASSURANCE_KEY, issue_assurance, require_browser_user
from .governance import admission_mutation
from .lifecycle import BrowserAdmissionError, apply_change, preview_change
from .models import StaffBrowserAdmission
from . import tests as foundation_tests
from .tests import TEST_KEY


@override_settings(TELEGRAM_BOT_TOKEN='', STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY])
class BrowserLifecycleTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.root = User.objects.create_superuser('lifecycle_root', 'root@example.invalid', None)
        self.other_root = User.objects.create_superuser('lifecycle_second_root', 'second@example.invalid', None)
        self.target = User.objects.create_user('existing_telegram_staff')
        self.outsider = User.objects.create_user('admin_not_root', is_staff=True)
        self.network = patch('socket.socket.connect', side_effect=AssertionError('No network in identity lifecycle tests'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def apply(self, action='authorize', revision=0, key='synthetic-action-001', **kwargs):
        values = {
            'actor': self.root, 'target_user_id': self.target.pk,
            'action': action, 'expected_revision': revision, 'request_key': key,
            'reason': 'Synthetic lifecycle verification',
        }
        values.update(kwargs)
        return apply_change(**values)

    def test_preview_is_read_only_and_does_not_prepare_credentials_or_grants(self):
        before = self.target.password
        preview = preview_change(actor=self.root, target_user_id=self.target.pk, action='authorize')
        self.assertEqual(preview['revision'], 0)
        self.assertFalse(StaffBrowserAdmission.objects.exists())
        self.assertFalse(ComplianceAuditEvent.objects.filter(action__startswith='staff_browser.').exists())
        self.assertFalse(EmailAddress.objects.filter(user=self.target).exists())
        self.assertFalse(AccessGrant.objects.filter(user=self.target).exists())
        self.target.refresh_from_db()
        self.assertEqual(self.target.password, before)

    def test_explicit_admission_is_audited_and_payload_bound_replay_is_exact(self):
        first = self.apply()
        replay = self.apply()
        self.assertFalse(first['replayed'])
        self.assertTrue(replay['replayed'])
        self.assertEqual(first['audit_event_id'], replay['audit_event_id'])
        self.assertEqual(first['revision'], replay['revision'])
        self.assertEqual(StaffBrowserAdmission.objects.get(user=self.target).revision, 1)
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='staff_browser.authorize').count(), 1)
        with self.assertRaises(BrowserAdmissionError):
            self.apply(reason='Different payload cannot reuse the same request')
        self.assertTrue(verify_integrity().ok)
        self.assertFalse(self.target.access_grants.exists())
        self.assertFalse(self.target.has_usable_password())

    def test_replay_returns_original_receipt_after_later_changes(self):
        original = self.apply()
        self.apply('suspend', 1, 'suspend-synthetic-001')
        replay = self.apply()
        self.assertEqual(replay['revision'], original['revision'])
        self.assertTrue(replay['enabled'])
        current = StaffBrowserAdmission.objects.get(user=self.target)
        self.assertFalse(current.enabled)
        self.assertEqual(current.revision, 2)

    def test_current_superuser_required_even_for_replay_and_preview(self):
        self.apply()
        for actor in (None, self.outsider):
            with self.assertRaises(PermissionDenied):
                self.apply(actor=actor)
            with self.assertRaises(PermissionDenied):
                preview_change(actor=actor, target_user_id=self.target.pk, action='authorize')
        get_user_model().objects.filter(pk=self.root.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            self.apply()

    def test_inactive_targets_and_stale_revisions_cannot_be_authorized(self):
        get_user_model().objects.filter(pk=self.target.pk).update(is_active=False)
        with self.assertRaises(BrowserAdmissionError):
            self.apply()
        get_user_model().objects.filter(pk=self.target.pk).update(is_active=True)
        self.apply()
        with self.assertRaises(BrowserAdmissionError):
            self.apply('suspend', 0, 'stale-action-001')
        self.assertTrue(StaffBrowserAdmission.objects.get(user=self.target).enabled)

    def test_invalid_inputs_cannot_leave_admission_or_audit(self):
        for changes in (
            {'action': 'invented'}, {'expected_revision': True}, {'request_key': 'short'},
            {'reason': ''}, {'target_user_id': True}, {'verification_reference': 'not-a-reset'},
        ):
            with self.subTest(fields=list(changes)), self.assertRaises(BrowserAdmissionError):
                values = {
                    'actor': self.root, 'target_user_id': self.target.pk, 'action': 'authorize',
                    'expected_revision': 0, 'request_key': 'synthetic-valid-key', 'reason': 'Synthetic validation check',
                }
                values.update(changes)
                apply_change(**values)
        self.assertFalse(StaffBrowserAdmission.objects.exists())

    def test_audit_failure_rolls_back_admission_and_factor_reset(self):
        with patch('staff_auth.lifecycle.record_event', side_effect=RuntimeError('Synthetic audit outage')):
            with self.assertRaises(RuntimeError):
                self.apply()
        self.assertFalse(StaffBrowserAdmission.objects.exists())
        self.apply()
        TOTP.activate(self.target, generate_totp_secret())
        RecoveryCodes.activate(self.target)
        with patch('staff_auth.lifecycle.record_event', side_effect=RuntimeError('Synthetic audit outage')):
            with self.assertRaises(RuntimeError):
                self.apply('reset_mfa', 1, 'reset-rollback-001', verification_reference='SUPPORT-123')
        self.assertEqual(Authenticator.objects.filter(user=self.target).count(), 2)
        self.assertEqual(StaffBrowserAdmission.objects.get(user=self.target).revision, 1)

    def test_reset_requires_operator_verification_and_never_changes_shared_credentials(self):
        self.apply()
        TOTP.activate(self.target, generate_totp_secret())
        RecoveryCodes.activate(self.target)
        before_password = self.target.password
        session = SessionStore()
        session[SESSION_KEY] = str(self.target.pk)
        session.save()
        with self.assertRaises(BrowserAdmissionError):
            self.apply('reset_mfa', 1, 'reset-requires-reference')
        result = self.apply('reset_mfa', 1, 'reset-confirmed-001', verification_reference='SUPPORT-123')
        self.assertEqual(result['factors_removed'], 2)
        self.assertFalse(Authenticator.objects.filter(user=self.target).exists())
        self.assertEqual(SessionStore(session_key=session.session_key)[SESSION_KEY], str(self.target.pk))
        self.target.refresh_from_db()
        self.assertEqual(self.target.password, before_password)
        self.assertTrue(self.target.is_active)
        event = ComplianceAuditEvent.objects.get(pk=result['audit_event_id'])
        self.assertEqual(event.metadata['verification_reference'], 'SUPPORT-123')
        self.assertNotIn('secret', json.dumps(event.after_values))

    def test_unreviewed_orm_and_admin_edits_are_blocked(self):
        self.assertTrue(admin.site.is_registered(StaffBrowserAdmission))
        with self.assertRaises(PermissionDenied):
            StaffBrowserAdmission.objects.create(user=self.target, subject_user_id=self.target.pk)
        self.apply()
        admission = StaffBrowserAdmission.objects.get(user=self.target)
        for mutate in (
            lambda: admission.save(), lambda: admission.delete(),
            lambda: StaffBrowserAdmission.objects.all().update(enabled=False),
            lambda: StaffBrowserAdmission.objects.all().delete(),
            lambda: StaffBrowserAdmission.objects.bulk_create([StaffBrowserAdmission(subject_user_id=123)]),
        ):
            with self.assertRaises(PermissionDenied):
                mutate()

    def test_reset_retry_cannot_remove_factors_enrolled_after_the_original_reset(self):
        self.apply()
        TOTP.activate(self.target, generate_totp_secret())
        original = self.apply('reset_mfa', 1, 'reset-safe-replay-001', verification_reference='SUPPORT-456')
        replacement = TOTP.activate(self.target, generate_totp_secret()).instance
        replay = self.apply('reset_mfa', 1, 'reset-safe-replay-001', verification_reference='SUPPORT-456')
        self.assertTrue(replay['replayed'])
        self.assertEqual(original['audit_event_id'], replay['audit_event_id'])
        self.assertTrue(Authenticator.objects.filter(pk=replacement.pk).exists())

    def test_database_constraints_reject_rebinding_and_zero_revision(self):
        self.apply()
        for changes in ({'user_id': self.outsider.pk}, {'revision': 0}):
            with self.assertRaises(IntegrityError), transaction.atomic(), admission_mutation():
                StaffBrowserAdmission.objects.filter(user=self.target).update(**changes)

    def test_governed_hard_delete_removes_vendor_credentials_but_retains_identity_evidence(self):
        result = self.apply()
        TOTP.activate(self.target, generate_totp_secret())
        EmailAddress.objects.create(user=self.target, email='synthetic@example.invalid', verified=True)
        target_id = self.target.pk
        preview = preview_user_hard_delete(actor=self.root, users=[self.target])
        execute_user_hard_delete(
            actor=self.root, users=[self.target], reason_category=UserHardDeletionBatch.REASON_DUPLICATE,
            reason_note='Synthetic credential deletion compatibility', request_id='synthetic-hard-delete-001',
            expected_fingerprint=preview.fingerprint,
        )
        self.assertFalse(get_user_model().objects.filter(pk=target_id).exists())
        retained = StaffBrowserAdmission.objects.get(pk=result['admission_id'])
        self.assertIsNone(retained.user_id)
        self.assertEqual(retained.subject_user_id, target_id)
        self.assertFalse(Authenticator.objects.filter(user_id=target_id).exists())
        self.assertFalse(EmailAddress.objects.filter(user_id=target_id).exists())
        self.assertTrue(ComplianceAuditEvent.objects.filter(pk=result['audit_event_id']).exists())
        self.assertTrue(verify_integrity().ok)

    def test_management_command_defaults_to_preview_and_requires_write_metadata(self):
        output = StringIO()
        call_command('manage_staff_browser', 'authorize', actor=self.root.pk, user=self.target.pk, stdout=output)
        self.assertTrue(json.loads(output.getvalue())['dry_run'])
        self.assertFalse(StaffBrowserAdmission.objects.exists())
        with self.assertRaises(CommandError):
            call_command('manage_staff_browser', 'authorize', actor=self.root.pk, user=self.target.pk, apply=True)
        output = StringIO()
        call_command(
            'manage_staff_browser', 'authorize', actor=self.root.pk, user=self.target.pk, apply=True,
            expected_revision=0, request_key='command-synthetic-001', reason='Synthetic reviewed opt-in', stdout=output,
        )
        self.assertEqual(json.loads(output.getvalue())['revision'], 1)


class BrowserRevocationAssuranceTests(foundation_tests.BrowserAssuranceTests):
    """Reuse the identity boundary fixture; inherited P1a contracts also run."""
    def change(self, action, revision, key):
        root = get_user_model().objects.get(username='synthetic_admission_root')
        return apply_change(
            actor=root, target_user_id=self.user.pk, action=action, expected_revision=revision,
            request_key=key, reason='Synthetic revocation verification',
        )

    def test_browser_revocation_does_not_remove_shared_login_but_stales_assurance(self):
        self.completed_login()
        self.change('revoke_sessions', 1, 'revoke-browser-only-001')
        self.assert_denied()
        self.assertEqual(self.request.session[SESSION_KEY], str(self.user.pk))
        self.completed_login()
        self.assertEqual(require_browser_user(self.request).pk, self.user.pk)

    def test_suspend_does_not_disable_staff_or_allow_old_marker_on_readmission(self):
        self.completed_login()
        old = dict(self.request.session[ASSURANCE_KEY])
        self.change('suspend', 1, 'suspend-browser-only-001')
        self.assert_denied()
        self.assertFalse(issue_assurance(self.request, self.user))
        self.change('authorize', 2, 'readmit-browser-only-001')
        self.request.session[ASSURANCE_KEY] = old
        self.assert_denied()
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.completed_login()
        self.assertEqual(require_browser_user(self.request).pk, self.user.pk)

    def test_no_explicit_admission_and_pre_revocation_password_step_cannot_issue(self):
        self.completed_login()
        # This test exercises strictly earlier authentication timestamps.
        # Windows can give adjacent events the same coarse wall-clock value;
        # make their intended ordering explicit without sleeping/relaxing policy.
        with patch('django.utils.timezone.now', return_value=timezone.now() + timedelta(seconds=1)):
            self.change('revoke_sessions', 1, 'revoke-pending-login-001')
        self.assertFalse(issue_assurance(self.request, self.user))
        self.assert_denied()
        # A user with a factor but no explicit admission must fail as well.
        with admission_mutation():
            StaffBrowserAdmission.objects.filter(user=self.user).delete()
        self.completed_login()
        self.assertNotIn(ASSURANCE_KEY, self.request.session)
        self.assert_denied()


@skipUnless(connection.vendor == 'postgresql', 'Requires actual PostgreSQL row locks, not SQLite.')
class BrowserLifecycleConcurrencyTests(TransactionTestCase):
    def setUp(self):
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.root = get_user_model().objects.create_superuser('browser_pg_root', 'pg@example.invalid', None)
        self.target = get_user_model().objects.create_user('browser_pg_target')

    def race(self, actions):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier = Barrier(2)

        def run(action):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return action()
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, actions))

    def change(self, key, action='authorize', revision=0):
        try:
            return apply_change(
                actor=self.root, target_user_id=self.target.pk, action=action,
                expected_revision=revision, request_key=key, reason='Synthetic PostgreSQL race',
            )
        except BrowserAdmissionError:
            return 'conflict'

    def test_same_key_parallel_first_admission_produces_one_row_and_event(self):
        results = self.race([lambda: self.change('pg-same-request-001'), lambda: self.change('pg-same-request-001')])
        self.assertEqual(sorted(result['replayed'] for result in results), [False, True])
        self.assertEqual(StaffBrowserAdmission.objects.count(), 1)
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='staff_browser.authorize').count(), 1)
        self.assertTrue(verify_integrity().ok)

    def test_competing_revision_changes_cannot_both_commit(self):
        self.change('pg-initial-request-001')
        results = self.race([
            lambda: self.change('pg-revoke-request-001', 'revoke_sessions', 1),
            lambda: self.change('pg-suspend-request-001', 'suspend', 1),
        ])
        self.assertEqual(results.count('conflict'), 1)
        self.assertEqual(StaffBrowserAdmission.objects.get(user=self.target).revision, 2)
