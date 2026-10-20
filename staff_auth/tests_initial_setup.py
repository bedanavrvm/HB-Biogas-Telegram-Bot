"""Synthetic existing-account setup. No production routes or mail delivery."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
import json
from threading import Barrier
import uuid
from unittest import skipUnless
from unittest.mock import patch

from allauth.account import signals
from allauth.account.models import EmailAddress
from allauth.mfa.totp.internal.auth import TOTP, generate_totp_secret
from django.contrib import admin
from django.contrib.auth import SESSION_KEY, get_user, get_user_model
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.db import close_old_connections, connection
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import Resolver404, resolve
from django.utils import timezone

from core.models import AccessGrant, ComplianceAuditChainState, ComplianceAuditEvent, UserHardDeletionBatch, UserProfile
from core.services.compliance_audit import verify_integrity
from core.services.user_hard_delete import execute_user_hard_delete, preview_user_hard_delete

from .assurance import ASSURANCE_KEY
from .crypto import PREFIX, decrypt_secret
from .initial_setup import InitialSetupError, prepare_setup, preview_setup
from .lifecycle import apply_change
from .models import StaffBrowserAdmission, StaffBrowserSetupGrant
from .session_protection import SETUP_CONTEXT_KEY
from .tests import PASSWORD, TEST_KEY


def key():
    return str(uuid.uuid4())


@override_settings(
    ROOT_URLCONF='staff_auth.test_browser_urls', STAFF_BROWSER_AUTH_ENABLED=True,
    STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY], EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    SECURE_SSL_REDIRECT=False, ACCOUNT_EMAIL_NOTIFICATIONS=False, ACCOUNT_CHANGE_EMAIL=False,
)
class InitialStaffSetupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.root = User.objects.create_superuser('setup_root', 'root@example.invalid', None)
        cls.user = User.objects.create_user('setup_staff', 'Staff.Setup@Example.invalid')
        cls.profile = UserProfile.objects.create(user=cls.user, telegram_id='123456789')
        apply_change(actor=cls.root, target_user_id=cls.user.pk, action='authorize', expected_revision=0,
                     request_key='synthetic-setup-admission', reason='Synthetic explicit browser admission')

    def setUp(self):
        network = patch('socket.socket.connect', side_effect=AssertionError('External network forbidden'))
        network.start()
        self.addCleanup(network.stop)
        self.client = Client(enforce_csrf_checks=True)

    def prepare(self, **overrides):
        preview = preview_setup(actor=self.root, target_user_id=self.user.pk)
        values = dict(actor=self.root, target_user_id=self.user.pk, expected_revision=preview['revision'],
                      snapshot_fingerprint=preview['snapshot_fingerprint'], request_key=key(),
                      reason='Synthetic initial staff setup')
        values.update(overrides)
        receipt = prepare_setup(**values)
        self.grant = StaffBrowserSetupGrant.objects.get(pk=receipt['setup_id'])
        self.proof = decrypt_secret(self.grant.confirmation_cipher)  # Synthetic mailbox material only.
        self.prepare_values = values
        return receipt

    def bootstrap(self, client=None):
        return (client or self.client).get('/test-staff-auth/v1/setup/session/')

    def post(self, action, data, client=None, **headers):
        client = client or self.client
        return client.post(
            f'/test-staff-auth/v1/setup/{action}/', data=json.dumps(data), content_type='application/json',
            HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value, **headers,
        )

    def verify(self, **overrides):
        self.verify_key = key()
        data = {'setup_id': str(self.grant.pk), 'request_key': self.verify_key, 'confirmation_key': self.proof}
        data.update(overrides)
        return self.post('verify-email', data)

    def password(self, request_key=None, password=PASSWORD, **overrides):
        data = {'setup_id': str(self.grant.pk), 'request_key': request_key or key(), 'password1': password, 'password2': password}
        data.update(overrides)
        return self.post('password', data)

    def prepared_verified(self):
        self.prepare()
        self.bootstrap()
        response = self.verify()
        self.assertEqual(response.status_code, 200, response.content)
        return response

    def test_preview_is_read_only_and_operator_output_exports_no_proof_or_address(self):
        count = ComplianceAuditEvent.objects.count()
        output = StringIO()
        call_command('prepare_staff_browser_setup', actor=self.root.pk, user=self.user.pk, stdout=output)
        self.assertTrue(json.loads(output.getvalue())['dry_run'])
        self.assertFalse(EmailAddress.objects.filter(user=self.user).exists())
        self.assertFalse(StaffBrowserSetupGrant.objects.exists())
        self.assertEqual(ComplianceAuditEvent.objects.count(), count)
        receipt = self.prepare()
        self.assertNotIn(self.proof, json.dumps(receipt))
        self.assertNotIn(self.user.email.lower(), json.dumps(receipt).lower())
        self.assertTrue(self.grant.confirmation_cipher.startswith(PREFIX))
        self.assertFalse(EmailAddress.objects.get(user=self.user).verified)
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())
        self.assertFalse(mail.outbox)
        self.assertFalse(admin.site.is_registered(StaffBrowserSetupGrant))

    def test_progress_resumes_only_the_verified_bound_session_without_writes(self):
        self.prepared_verified()
        count = ComplianceAuditEvent.objects.count()
        result = self.bootstrap().json()
        self.assertEqual(result['state'], 'password_required')
        self.assertEqual(result['setup_id'], str(self.grant.pk))
        self.assertEqual(result['username'], self.user.username)
        self.assertEqual(ComplianceAuditEvent.objects.count(), count)
        other = Client(enforce_csrf_checks=True)
        self.assertEqual(self.bootstrap(other).json()['state'], 'setup_required')
        copied = other.session
        copied[SETUP_CONTEXT_KEY] = self.client.session[SETUP_CONTEXT_KEY]
        copied.save()
        self.assertNotIn('username', self.bootstrap(other).json())
        self.assertEqual(self.password().json()['state'], 'reauthentication_required')
        self.assertEqual(self.bootstrap().json()['state'], 'reauthentication_required')

    def test_progress_hides_expired_or_revoked_setup(self):
        self.prepared_verified()
        StaffBrowserSetupGrant.objects.filter(pk=self.grant.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.bootstrap().json()['state'], 'setup_required')
        StaffBrowserSetupGrant.objects.filter(pk=self.grant.pk).update(expires_at=timezone.now() + timedelta(minutes=5))
        row = StaffBrowserAdmission.objects.get(user=self.user)
        apply_change(actor=self.root, target_user_id=self.user.pk, action='suspend', expected_revision=row.revision,
                     request_key='synthetic-progress-suspend', reason='Synthetic revoked progress denial')
        self.assertNotIn('username', self.bootstrap().json())

    def test_preparation_retry_is_payload_bound_and_has_one_receipt_and_generation_change(self):
        first = self.prepare()
        cipher = self.grant.confirmation_cipher
        replay = prepare_setup(**self.prepare_values)
        self.assertTrue(replay['replayed'])
        self.assertEqual(first['audit_event_id'], replay['audit_event_id'])
        self.assertEqual(StaffBrowserSetupGrant.objects.count(), 1)
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.confirmation_cipher, cipher)
        self.assertEqual(StaffBrowserAdmission.objects.get(user=self.user).revision, 2)
        with self.assertRaises(InitialSetupError):
            prepare_setup(**{**self.prepare_values, 'reason': 'Different preparation cannot reuse this request'})
        self.assertTrue(verify_integrity().ok)

    def test_stale_account_snapshot_and_stale_actor_are_denied(self):
        preview = preview_setup(actor=self.root, target_user_id=self.user.pk)
        get_user_model().objects.filter(pk=self.user.pk).update(email='changed@example.invalid')
        with self.assertRaises(InitialSetupError):
            prepare_setup(actor=self.root, target_user_id=self.user.pk, expected_revision=preview['revision'],
                          snapshot_fingerprint=preview['snapshot_fingerprint'], request_key=key(), reason='Synthetic stale preview')
        get_user_model().objects.filter(pk=self.root.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            preview_setup(actor=self.root, target_user_id=self.user.pk)
        self.assertFalse(StaffBrowserSetupGrant.objects.exists())

    def test_non_superuser_cannot_prepare_any_account(self):
        other = get_user_model().objects.create_user('setup_not_root', is_staff=True)
        with self.assertRaises(PermissionDenied):
            preview_setup(actor=other, target_user_id=self.user.pk)
        with self.assertRaises(PermissionDenied):
            self.prepare(actor=other)

    def test_existing_password_privileged_inactive_and_factor_accounts_are_excluded(self):
        User = get_user_model()
        scenarios = [dict(password='already-encoded-usable'), dict(is_staff=True), dict(is_superuser=True), dict(is_active=False)]
        original = {field: getattr(self.user, field) for field in ('password', 'is_staff', 'is_superuser', 'is_active')}
        for changes in scenarios:
            User.objects.filter(pk=self.user.pk).update(**changes)
            with self.assertRaises(InitialSetupError):
                preview_setup(actor=self.root, target_user_id=self.user.pk)
            User.objects.filter(pk=self.user.pk).update(**original)
        TOTP.activate(self.user, generate_totp_secret())
        with self.assertRaises(InitialSetupError):
            preview_setup(actor=self.root, target_user_id=self.user.pk)

    def test_missing_or_conflicting_canonical_address_never_links_another_identity(self):
        User = get_user_model()
        User.objects.filter(pk=self.user.pk).update(email='')
        with self.assertRaises(InitialSetupError):
            preview_setup(actor=self.root, target_user_id=self.user.pk)
        User.objects.filter(pk=self.user.pk).update(email=self.user.email)
        other = User.objects.create_user('conflicting_setup_identity', self.user.email.lower())
        with self.assertRaises(InitialSetupError):
            preview_setup(actor=self.root, target_user_id=self.user.pk)
        other.email = ''
        other.save(update_fields=['email'])
        EmailAddress.objects.create(user=other, email=self.user.email.lower(), verified=False)
        with self.assertRaises(InitialSetupError):
            preview_setup(actor=self.root, target_user_id=self.user.pk)
        self.assertFalse(EmailAddress.objects.filter(user=self.user).exists())

    def test_preparation_audit_outage_rolls_back_address_grant_and_revision(self):
        with patch('staff_auth.initial_setup.record_event', side_effect=RuntimeError('synthetic audit outage')):
            with self.assertRaises(RuntimeError):
                self.prepare()
        self.assertFalse(StaffBrowserSetupGrant.objects.exists())
        self.assertFalse(EmailAddress.objects.filter(user=self.user).exists())
        self.assertEqual(StaffBrowserAdmission.objects.get(user=self.user).revision, 1)

    def test_legacy_whitespace_on_another_accounts_address_does_not_hide_a_conflict(self):
        other = get_user_model().objects.create_user('legacy_setup_address')
        get_user_model().objects.filter(pk=other.pk).update(email=f' {self.user.email.upper()} ')
        with self.assertRaises(InitialSetupError):
            preview_setup(actor=self.root, target_user_id=self.user.pk)
        get_user_model().objects.filter(pk=other.pk).update(email='')
        EmailAddress.objects.create(user=other, email=f' {self.user.email.upper()} ', verified=False)
        with self.assertRaises(InitialSetupError):
            preview_setup(actor=self.root, target_user_id=self.user.pk)
        self.assertFalse(StaffBrowserSetupGrant.objects.exists())

    def test_mailbox_and_password_setup_never_authenticate_or_change_telegram_grants(self):
        user_count, grant_count = get_user_model().objects.count(), AccessGrant.objects.count()
        original_email = self.user.email
        self.prepared_verified()
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertNotIn(ASSURANCE_KEY, self.client.session)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.password()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['state'], 'reauthentication_required')
        self.assertFalse(response.json()['is_authenticated'])
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.grant.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))
        self.assertEqual(self.user.email, original_email)
        self.assertFalse(self.user.is_staff)
        self.assertEqual(self.profile.telegram_id, '123456789')
        self.assertEqual(self.grant.confirmation_cipher, '')
        self.assertTrue(EmailAddress.objects.get(user=self.user).verified)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertNotIn(ASSURANCE_KEY, self.client.session)
        self.assertEqual(get_user_model().objects.count(), user_count)
        self.assertEqual(AccessGrant.objects.count(), grant_count)
        self.assertTrue(verify_integrity().ok)
        self.assertFalse(mail.outbox)
        fresh = Client(enforce_csrf_checks=True)
        fresh.get('/test-staff-auth/v1/session/')
        result = fresh.post('/test-staff-auth/v1/login/', data=json.dumps({'username': self.user.username, 'password': PASSWORD}),
                            content_type='application/json', HTTP_X_CSRFTOKEN=fresh.cookies['csrftoken'].value)
        self.assertEqual(result.json()['state'], 'enrollment_required')
        self.assertNotIn(ASSURANCE_KEY, fresh.session)

    def test_initial_password_changes_the_shared_session_hash(self):
        bridge = Client()
        bridge.force_login(self.user, backend='core.auth_backends.TelegramMiniAppBackend')
        old_hash = self.user.get_session_auth_hash()
        self.prepared_verified()
        self.assertEqual(self.password().status_code, 200)
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.get_session_auth_hash(), old_hash)
        request = RequestFactory().get('/')
        request.session = bridge.session
        self.assertFalse(get_user(request).is_authenticated)
        self.assertNotIn(SESSION_KEY, request.session)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.telegram_id, '123456789')

    def test_verification_retry_is_bound_to_request_proof_and_anonymous_session(self):
        self.prepared_verified()
        payload = {'setup_id': str(self.grant.pk), 'request_key': self.verify_key, 'confirmation_key': self.proof}
        self.assertTrue(self.post('verify-email', payload).json()['replayed'])
        self.assertEqual(self.post('verify-email', {**payload, 'request_key': key()}).status_code, 409)
        other = Client(enforce_csrf_checks=True)
        self.bootstrap(other)
        self.assertEqual(self.post('verify-email', payload, other).status_code, 409)
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='staff_browser.setup_verified').count(), 1)

    def test_password_retry_is_exact_without_retaining_an_extra_password_verifier(self):
        self.prepared_verified()
        completion_key = key()
        self.assertEqual(self.password(completion_key).status_code, 200)
        self.assertTrue(self.password(completion_key).json()['replayed'])
        self.assertEqual(self.password(completion_key, password='different-valid-synthetic-password').status_code, 409)
        self.assertEqual(self.password(key()).status_code, 409)
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='staff_browser.setup_completed').count(), 1)

    def test_wrong_mailbox_proof_and_password_before_verification_are_denied(self):
        self.prepare()
        self.bootstrap()
        self.assertEqual(self.verify(confirmation_key='invalid-proof').status_code, 400)
        self.assertEqual(self.password().status_code, 409)
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())
        self.assertFalse(EmailAddress.objects.get(user=self.user).verified)

    def test_mailbox_proof_without_its_durable_preparation_receipt_cannot_verify(self):
        self.prepare()
        self.bootstrap()
        with patch('staff_auth.setup_api._receipt', return_value=None):
            self.assertEqual(self.verify().status_code, 409)
        self.assertFalse(EmailAddress.objects.get(user=self.user).verified)
        self.assertNotIn(SETUP_CONTEXT_KEY, self.client.session)

    @override_settings(ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION=True)
    def test_native_login_on_confirmation_setting_cannot_authenticate_this_setup_flow(self):
        self.prepared_verified()
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertNotIn(ASSURANCE_KEY, self.client.session)

    def test_superseding_preparation_rejects_old_grant_and_old_proof_even_in_same_second(self):
        self.prepare()
        old_grant, old_proof = self.grant, self.proof
        self.prepare()
        self.assertNotEqual(old_proof, self.proof)
        self.bootstrap()
        self.assertEqual(self.verify(setup_id=str(old_grant.pk), confirmation_key=old_proof).status_code, 409)
        self.assertEqual(self.verify(confirmation_key=old_proof).status_code, 400)
        self.assertEqual(self.verify().status_code, 200)

    def test_current_admission_address_password_and_expiry_are_rechecked(self):
        self.prepare()
        self.bootstrap()
        original = self.user.email
        get_user_model().objects.filter(pk=self.user.pk).update(email='different@example.invalid')
        self.assertEqual(self.verify().status_code, 409)
        get_user_model().objects.filter(pk=self.user.pk).update(email=original)
        StaffBrowserSetupGrant.objects.filter(pk=self.grant.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.verify().status_code, 409)
        self.assertFalse(EmailAddress.objects.get(user=self.user).verified)

    def test_revocation_after_verification_denies_password_and_preserves_unusable_state(self):
        self.prepared_verified()
        apply_change(actor=self.root, target_user_id=self.user.pk, action='revoke_sessions', expected_revision=2,
                     request_key='setup-revoke-after-proof', reason='Synthetic setup revocation')
        self.assertEqual(self.password().status_code, 409)
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())

    def test_externally_installed_password_cannot_be_replaced_by_initial_setup(self):
        self.prepared_verified()
        self.user.set_password('separate-verified-support-password')
        self.user.save(update_fields=['password'])
        self.assertEqual(self.password().status_code, 409)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('separate-verified-support-password'))

    def test_native_password_validation_rejects_weak_and_mismatched_values(self):
        self.prepared_verified()
        self.assertEqual(self.password(password='123').status_code, 400)
        self.assertEqual(self.password(password2='different').status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())

    def test_verification_audit_outage_rolls_back_native_verified_flag_and_session_context(self):
        self.prepare()
        self.bootstrap()
        with patch('staff_auth.setup_api.record_event', side_effect=RuntimeError('synthetic verification audit outage')):
            self.assertEqual(self.verify().status_code, 503)
        self.assertFalse(EmailAddress.objects.get(user=self.user).verified)
        self.assertNotIn(SETUP_CONTEXT_KEY, self.client.session)
        self.grant.refresh_from_db()
        self.assertEqual(self.grant.state, StaffBrowserSetupGrant.PREPARED)

    def test_password_audit_outage_rolls_back_password_and_completion_then_allows_verified_retry(self):
        self.prepared_verified()
        with patch('staff_auth.setup_api.record_event', side_effect=RuntimeError('synthetic password audit outage')):
            self.assertEqual(self.password().status_code, 503)
        self.user.refresh_from_db()
        self.grant.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())
        self.assertEqual(self.grant.state, StaffBrowserSetupGrant.VERIFIED)
        self.assertNotIn(SETUP_CONTEXT_KEY, self.client.session)
        self.assertEqual(self.post('verify-email', {'setup_id': str(self.grant.pk), 'request_key': self.verify_key,
                                                   'confirmation_key': self.proof}).status_code, 200)
        self.assertEqual(self.password().status_code, 200)

    def test_other_authenticated_cookie_is_preserved_without_account_switching(self):
        self.prepare()
        self.client.force_login(self.root)
        before = self.client.session[SESSION_KEY]
        self.client.get('/test-staff-auth/v1/session/')
        self.assertEqual(self.bootstrap().status_code, 409)
        self.assertEqual(self.verify().status_code, 409)
        self.assertEqual(self.client.session[SESSION_KEY], before)

    def test_csrf_mixed_credentials_extra_fields_and_rate_limit_are_enforced(self):
        self.prepare()
        self.bootstrap()
        payload = {'setup_id': str(self.grant.pk), 'request_key': key(), 'confirmation_key': self.proof}
        self.assertEqual(self.client.post('/test-staff-auth/v1/setup/verify-email/', data=json.dumps(payload),
                                         content_type='application/json').status_code, 403)
        self.assertEqual(self.post('verify-email', payload, HTTP_AUTHORIZATION='invalid').status_code, 403)
        self.assertEqual(self.post('verify-email', {**payload, 'email': 'not-an-input@example.invalid'}).status_code, 400)
        for _ in range(10):
            response = self.post('verify-email', {**payload, 'confirmation_key': 'wrong'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.post('verify-email', payload).status_code, 429)

    def test_unaccepted_native_notifications_and_new_signal_receivers_hold_without_mutation(self):
        self.prepare()
        self.bootstrap()
        with override_settings(ACCOUNT_EMAIL_NOTIFICATIONS=True):
            self.assertEqual(self.verify().status_code, 503)
        def receiver(**kwargs):
            raise AssertionError('An unreviewed callback must not execute')
        signals.email_confirmed.connect(receiver, sender=EmailAddress, weak=False)
        try:
            self.assertEqual(self.verify().status_code, 503)
        finally:
            signals.email_confirmed.disconnect(receiver, sender=EmailAddress)
        self.assertFalse(EmailAddress.objects.get(user=self.user).verified)
        self.assertFalse(mail.outbox)

    def test_setup_survives_governed_user_deletion_as_inert_expiring_state(self):
        self.prepare()
        preview = preview_user_hard_delete(actor=self.root, users=[self.user])
        execute_user_hard_delete(
            actor=self.root, users=[self.user], reason_category=UserHardDeletionBatch.REASON_DUPLICATE,
            reason_note='Synthetic initial setup deletion compatibility', request_id='delete-setup-synthetic-user',
            expected_fingerprint=preview.fingerprint,
        )
        self.bootstrap()
        self.assertEqual(self.verify().status_code, 409)
        self.grant.refresh_from_db()
        self.assertIsNone(self.grant.admission.user_id)
        self.assertFalse(EmailAddress.objects.filter(pk=self.grant.email_address_id).exists())
        self.assertTrue(verify_integrity().ok)

    def test_expired_cleanup_is_preview_first_and_preserves_native_rows_and_audit(self):
        self.prepare()
        StaffBrowserSetupGrant.objects.filter(pk=self.grant.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        audits = ComplianceAuditEvent.objects.count()
        call_command('purge_staff_browser_setups', stdout=StringIO())
        self.assertTrue(StaffBrowserSetupGrant.objects.exists())
        call_command('purge_staff_browser_setups', apply=True, stdout=StringIO())
        self.assertFalse(StaffBrowserSetupGrant.objects.exists())
        self.assertTrue(EmailAddress.objects.filter(user=self.user).exists())
        self.assertEqual(ComplianceAuditEvent.objects.count(), audits)

    @override_settings(ROOT_URLCONF='config.urls', STAFF_BROWSER_AUTH_ENABLED=False)
    def test_setup_paths_are_not_mounted_in_production(self):
        for path in ('/api/staff/v1/setup/session/', '/api/staff/v1/setup/verify-email/', '/api/staff/v1/setup/password/'):
            with self.assertRaises(Resolver404):
                resolve(path)


@skipUnless(connection.vendor == 'postgresql', 'Requires real PostgreSQL row locks, not SQLite.')
@override_settings(
    ROOT_URLCONF='staff_auth.test_browser_urls', STAFF_BROWSER_AUTH_ENABLED=True,
    STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY], SECURE_SSL_REDIRECT=False,
    ACCOUNT_EMAIL_NOTIFICATIONS=False, ACCOUNT_CHANGE_EMAIL=False,
)
class InitialSetupConcurrencyTests(TransactionTestCase):
    def setUp(self):
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.root = get_user_model().objects.create_superuser('setup_pg_root', 'root@example.invalid', None)
        self.user = get_user_model().objects.create_user('setup_pg_staff', 'setup-pg@example.invalid')
        apply_change(actor=self.root, target_user_id=self.user.pk, action='authorize', expected_revision=0,
                     request_key='pg-setup-admission', reason='Synthetic PostgreSQL admission')
        preview = preview_setup(actor=self.root, target_user_id=self.user.pk)
        self.values = dict(actor=self.root, target_user_id=self.user.pk, expected_revision=preview['revision'],
                           snapshot_fingerprint=preview['snapshot_fingerprint'], request_key='pg-setup-prepare',
                           reason='Synthetic PostgreSQL setup')

    def race(self, actions):
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

    def test_parallel_same_preparation_creates_one_grant_and_receipt(self):
        results = self.race([lambda: prepare_setup(**self.values), lambda: prepare_setup(**self.values)])
        self.assertEqual(sorted(row['replayed'] for row in results), [False, True])
        self.assertEqual(StaffBrowserSetupGrant.objects.count(), 1)
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='staff_browser.setup_prepared').count(), 1)

    def test_parallel_mailbox_claims_from_different_sessions_admit_one(self):
        prepared = prepare_setup(**self.values)
        grant = StaffBrowserSetupGrant.objects.get(pk=prepared['setup_id'])
        proof = decrypt_secret(grant.confirmation_cipher)
        clients = [Client(enforce_csrf_checks=True), Client(enforce_csrf_checks=True)]
        for client in clients:
            client.get('/test-staff-auth/v1/setup/session/')
        def verify(client):
            return client.post('/test-staff-auth/v1/setup/verify-email/', data=json.dumps({
                'setup_id': str(grant.pk), 'request_key': key(), 'confirmation_key': proof,
            }), content_type='application/json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value).status_code
        self.assertEqual(sorted(self.race([lambda: verify(clients[0]), lambda: verify(clients[1])])), [200, 409])
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='staff_browser.setup_verified').count(), 1)

    def test_parallel_first_password_submissions_cannot_both_change_credentials(self):
        from copy import copy
        prepared = prepare_setup(**self.values)
        grant = StaffBrowserSetupGrant.objects.get(pk=prepared['setup_id'])
        client = Client(enforce_csrf_checks=True)
        client.get('/test-staff-auth/v1/setup/session/')
        result = client.post('/test-staff-auth/v1/setup/verify-email/', data=json.dumps({
            'setup_id': str(grant.pk), 'request_key': key(), 'confirmation_key': decrypt_secret(grant.confirmation_cipher),
        }), content_type='application/json', HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(result.status_code, 200)
        other = Client(enforce_csrf_checks=True)
        other.cookies = copy(client.cookies)
        def password(browser):
            return browser.post('/test-staff-auth/v1/setup/password/', data=json.dumps({
                'setup_id': str(grant.pk), 'request_key': key(), 'password1': PASSWORD, 'password2': PASSWORD,
            }), content_type='application/json', HTTP_X_CSRFTOKEN=browser.cookies['csrftoken'].value).status_code
        self.assertEqual(sorted(self.race([lambda: password(client), lambda: password(other)])), [200, 409])
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='staff_browser.setup_completed').count(), 1)
