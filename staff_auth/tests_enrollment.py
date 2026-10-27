"""Synthetic closed enrollment journeys. No production URLs or provider writes."""
import json
import time
import uuid
from unittest import skipUnless
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from allauth.mfa.totp.internal.auth import SECRET_SESSION_KEY, format_hotp_value, hotp_value
from django.contrib.auth import SESSION_KEY, get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import Resolver404, resolve

from core.models import ComplianceAuditChainState, ComplianceAuditEvent
from core.services.compliance_audit import verify_integrity

from .assurance import ASSURANCE_KEY
from .browser_api import require_company_browser_user
from .crypto import PREFIX
from .lifecycle import apply_change
from .session_protection import CHANNEL_KEY, ENROLLMENT_CONTEXT_KEY
from .tests import PASSWORD, TEST_KEY, admit_synthetic_user


def key():
    return str(uuid.uuid4())


class EnrollmentJourney:
    def bootstrap(self):
        return self.client.get('/test-staff-auth/v1/session/')

    def post(self, action, data, **headers):
        return self.client.post(
            f'/test-staff-auth/v1/{action}/', data=json.dumps(data), content_type='application/json',
            HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value, **headers,
        )

    def password(self):
        return self.post('login', {'username': self.user.username, 'password': PASSWORD})

    def begin(self, request_key=None):
        self.begin_key = request_key or key()
        result = self.post('enrollment/begin', {'request_key': self.begin_key, 'password': PASSWORD})
        self.assertEqual(result.status_code, 200, result.content)
        self.secret = parse_qs(urlparse(result.json()['otpauth_uri']).query)['secret'][0]
        return result

    def code(self):
        return format_hotp_value(hotp_value(self.secret, int(time.time()) // 30))

    def confirm(self):
        self.confirm_key = key()
        result = self.post('enrollment/confirm', {'request_key': self.confirm_key, 'code': self.code()})
        self.assertEqual(result.status_code, 200, result.content)
        return result

    def assert_not_business(self):
        self.assertNotIn(ASSURANCE_KEY, self.client.session)
        request = RequestFactory().get('/')
        request.user, request.session = self.user, self.client.session
        with self.assertRaises(PermissionDenied):
            require_company_browser_user(request)


@override_settings(
    ROOT_URLCONF='staff_auth.test_browser_urls', STAFF_BROWSER_AUTH_ENABLED=True,
    STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY], EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    SECURE_SSL_REDIRECT=False, ACCOUNT_EMAIL_NOTIFICATIONS=False,
)
class BrowserEnrollmentTests(EnrollmentJourney, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('enrollment_staff', 'enrollment@example.invalid', PASSWORD)
        admit_synthetic_user(cls.user)
        EmailAddress.objects.create(user=cls.user, email=cls.user.email, verified=True, primary=True)

    def setUp(self):
        cache.clear()
        network = patch('socket.socket.connect', side_effect=AssertionError('External network forbidden'))
        network.start()
        self.addCleanup(network.stop)
        self.client = Client(enforce_csrf_checks=True)
        self.bootstrap()
        self.assertEqual(self.password().json()['state'], 'enrollment_required')

    def test_begin_reuses_encrypted_seed_only_for_same_request_and_audits_once(self):
        first = self.begin()
        retry = self.post('enrollment/begin', {'request_key': self.begin_key, 'password': PASSWORD})
        self.assertEqual(retry.json()['otpauth_uri'], first.json()['otpauth_uri'])
        self.assertEqual(first['Cache-Control'], 'no-store, private')
        pending = self.client.session[SECRET_SESSION_KEY]
        self.assertTrue(pending.startswith(PREFIX))
        self.assertNotIn(self.secret, pending)
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='staff_browser.enrollment_started').count(), 1)
        self.assertEqual(self.post('enrollment/begin', {'request_key': key(), 'password': PASSWORD}).json()['state'], 'enrollment_in_progress')
        self.assert_not_business()

    def test_progress_resumes_the_same_draft_without_seed_or_audit_writes(self):
        self.assertNotIn('otpauth_uri', self.client.get('/test-staff-auth/v1/enrollment/session/').json())
        started = self.begin().json()
        count = ComplianceAuditEvent.objects.count()
        pending = self.client.session[SECRET_SESSION_KEY]
        progress = self.client.get('/test-staff-auth/v1/enrollment/session/')
        self.assertEqual(progress.json()['otpauth_uri'], started['otpauth_uri'])
        self.assertEqual(progress.json()['username'], self.user.username)
        self.assertTrue(progress.json()['qr_data'].startswith('data:image/svg+xml;base64,'))
        self.assertEqual(self.client.session[SECRET_SESSION_KEY], pending)
        self.assertEqual(ComplianceAuditEvent.objects.count(), count)
        self.assertEqual(progress['Cache-Control'], 'no-store, private')
        other = Client(enforce_csrf_checks=True)
        denied = other.get('/test-staff-auth/v1/enrollment/session/')
        self.assertEqual(denied.status_code, 401)
        self.assertNotIn('username', denied.json())
        self.confirm()
        self.assertNotIn('otpauth_uri', self.client.get('/test-staff-auth/v1/enrollment/session/').json())
        self.assert_not_business()

    def test_native_activation_recovery_handoff_and_new_mfa_login(self):
        self.begin()
        with self.captureOnCommitCallbacks(execute=True):
            result = self.confirm()
        self.assertEqual(result.json()['state'], 'recovery_codes_required')
        self.assertEqual(self.bootstrap().json()['state'], 'recovery_codes_required')
        self.assertEqual(Authenticator.objects.filter(user=self.user).count(), 2)
        self.assertNotIn(SECRET_SESSION_KEY, self.client.session)
        for factor in Authenticator.objects.filter(user=self.user):
            stored = factor.data.get('secret', factor.data.get('seed'))
            self.assertTrue(stored.startswith(PREFIX))
        self.assert_not_business()
        viewed = self.post('enrollment/recovery-codes', {'request_key': key()})
        self.assertEqual(viewed.status_code, 200, viewed.content)
        codes = viewed.json()['recovery_codes']
        self.assertTrue(codes)
        self.assertEqual(viewed.json()['state'], 'reauthentication_required')
        self.assertEqual(self.bootstrap().json()['state'], 'reauthentication_required')
        self.assert_not_business()
        self.assertEqual(len(mail.outbox), 0)
        records = json.dumps(list(ComplianceAuditEvent.objects.values('metadata', 'before_values', 'after_values')))
        session = json.dumps(dict(self.client.session))
        for forbidden in [self.secret, PASSWORD, *codes]:
            self.assertNotIn(forbidden, records)
            self.assertNotIn(forbidden, session)
        self.assertEqual(self.password().status_code, 409)
        self.post('logout', {})
        self.bootstrap()
        self.assertEqual(self.password().json()['state'], 'mfa_required')
        self.assertEqual(self.post('mfa', {'code': self.code()}).json()['state'], 'authenticated')
        self.assertTrue(verify_integrity().ok)

    def test_activation_retry_returns_only_receipt_without_replacement(self):
        self.begin()
        first = self.confirm()
        before = list(Authenticator.objects.filter(user=self.user).values('id', 'data'))
        retry = self.post('enrollment/confirm', {'request_key': self.confirm_key, 'code': 'not-a-code'})
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json()['receipt_id'], first.json()['receipt_id'])
        self.assertTrue(retry.json()['replayed'])
        self.assertNotIn('otpauth_uri', retry.json())
        self.assertNotIn('recovery_codes', retry.json())
        self.assertEqual(list(Authenticator.objects.filter(user=self.user).values('id', 'data')), before)
        self.assertEqual(self.post('enrollment/confirm', {'request_key': key(), 'code': self.code()}).status_code, 409)
        self.assertEqual(self.post('enrollment/begin', {'request_key': key(), 'password': PASSWORD}).status_code, 409)
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='staff_browser.enrollment_activated').count(), 1)

    def test_one_time_recovery_handoff_cannot_reshow_even_with_different_key(self):
        self.begin()
        self.confirm()
        request_key = key()
        first = self.post('enrollment/recovery-codes', {'request_key': request_key})
        self.assertEqual(first.status_code, 200)
        before = list(Authenticator.objects.filter(user=self.user).values('id', 'data'))
        for another in (request_key, key()):
            denied = self.post('enrollment/recovery-codes', {'request_key': another})
            self.assertEqual(denied.status_code, 409)
            self.assertNotIn('recovery_codes', denied.json())
        self.assertEqual(list(Authenticator.objects.filter(user=self.user).values('id', 'data')), before)
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='staff_browser.enrollment_recovery_viewed').count(), 1)

    @override_settings(MFA_RECOVERY_CODES_SHOW_ONCE=False)
    def test_misconfigured_vendor_show_once_cannot_allow_second_disclosure(self):
        self.begin()
        self.confirm()
        self.assertEqual(self.post('enrollment/recovery-codes', {'request_key': key()}).status_code, 200)
        self.assertEqual(self.post('enrollment/recovery-codes', {'request_key': key()}).status_code, 409)

    def test_invalid_code_does_not_rotate_seed_and_valid_retry_works(self):
        self.begin()
        encrypted = self.client.session[SECRET_SESSION_KEY]
        bad = self.post('enrollment/confirm', {'request_key': key(), 'code': 'not-a-code'})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.client.session[SECRET_SESSION_KEY], encrypted)
        self.assertFalse(Authenticator.objects.filter(user=self.user).exists())
        self.confirm()

    def test_missing_pending_secret_cannot_be_invented_by_bound_form(self):
        self.begin()
        stored = self.client.session
        stored.pop(SECRET_SESSION_KEY)
        stored.save()
        denied = self.post('enrollment/confirm', {'request_key': key(), 'code': self.code()})
        self.assertEqual(denied.json()['state'], 'enrollment_restart_required')
        self.assertNotIn(SECRET_SESSION_KEY, self.client.session)
        self.assertFalse(Authenticator.objects.filter(user=self.user).exists())

    def test_expired_pending_ciphertext_and_reauthentication_fail_closed(self):
        self.begin()
        now = time.time()
        with patch('staff_auth.session_protection.time.time', return_value=now + 601):
            self.assertEqual(self.post('enrollment/confirm', {'request_key': key(), 'code': self.code()}).status_code, 409)
        self.assertFalse(Authenticator.objects.filter(user=self.user).exists())

    def test_stale_native_password_recheck_requires_new_begin_key(self):
        self.begin()
        later = time.time() + 301
        with patch('staff_auth.enrollment_state.time.time', return_value=later):
            self.assertEqual(self.post('enrollment/confirm', {'request_key': key(), 'code': self.code()}).status_code, 409)
            self.assertEqual(self.post('enrollment/begin', {'request_key': self.begin_key, 'password': PASSWORD}).status_code, 409)
            self.begin()
            self.confirm()

    def test_plaintext_pending_seed_is_rejected_and_discarded(self):
        self.begin()
        stored = self.client.session
        stored[SECRET_SESSION_KEY] = self.secret
        stored.save()
        denied = self.post('enrollment/confirm', {'request_key': key(), 'code': self.code()})
        self.assertEqual(denied.status_code, 409)
        self.assertNotIn(SECRET_SESSION_KEY, self.client.session)
        self.assertNotIn(ENROLLMENT_CONTEXT_KEY, self.client.session)
        self.assertFalse(Authenticator.objects.filter(user=self.user).exists())

    def test_wrong_password_or_unverified_secondary_email_cannot_begin(self):
        denied = self.post('enrollment/begin', {'request_key': key(), 'password': 'not-the-password'})
        self.assertEqual(denied.status_code, 400)
        EmailAddress.objects.create(user=self.user, email='secondary@example.invalid', verified=False)
        self.assertEqual(self.post('enrollment/begin', {'request_key': key(), 'password': PASSWORD}).status_code, 409)
        self.assertNotIn(SECRET_SESSION_KEY, self.client.session)

    def test_ordinary_cookie_no_channel_cannot_enroll(self):
        self.client.logout()
        self.client.force_login(self.user)
        self.bootstrap()
        self.assertEqual(self.post('enrollment/begin', {'request_key': key(), 'password': PASSWORD}).status_code, 401)
        self.assertIn(SESSION_KEY, self.client.session)
        self.assertFalse(Authenticator.objects.filter(user=self.user).exists())

    def test_csrf_origin_mixed_credentials_methods_and_exact_body(self):
        payload = {'request_key': key(), 'password': PASSWORD}
        for action in ('enrollment/begin', 'enrollment/confirm', 'enrollment/recovery-codes'):
            self.assertEqual(self.client.get(f'/test-staff-auth/v1/{action}/').status_code, 405)
            self.assertEqual(self.client.post(f'/test-staff-auth/v1/{action}/', data=json.dumps(payload), content_type='application/json').status_code, 403)
            self.assertEqual(self.post(action, payload, HTTP_ORIGIN='https://untrusted.example.invalid').status_code, 403)
            for header in ('HTTP_X_TELEGRAM_INIT_DATA', 'HTTP_X_SESSION_TOKEN', 'HTTP_AUTHORIZATION'):
                self.assertEqual(self.post(action, payload, **{header: ''}).status_code, 403)
        for bad in ({**payload, 'extra': 'value'}, {**payload, 'request_key': 'not-a-uuid'}, {**payload, 'password': []}):
            self.assertEqual(self.post('enrollment/begin', bad).status_code, 400)

    def test_begin_audit_failure_leaves_no_pending_secret(self):
        with patch('staff_auth.enrollment.record_event', side_effect=RuntimeError('Synthetic outage')):
            result = self.post('enrollment/begin', {'request_key': key(), 'password': PASSWORD})
        self.assertEqual(result.status_code, 503)
        self.assertNotIn(SECRET_SESSION_KEY, self.client.session)
        self.assertNotIn(ENROLLMENT_CONTEXT_KEY, self.client.session)
        self.assertFalse(Authenticator.objects.filter(user=self.user).exists())

    def test_activation_audit_failure_rolls_back_both_factors(self):
        self.begin()
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with patch('staff_auth.enrollment.record_event', side_effect=RuntimeError('Synthetic outage')):
                result = self.post('enrollment/confirm', {'request_key': key(), 'code': self.code()})
        self.assertEqual(result.status_code, 503)
        self.assertEqual(callbacks, [])
        self.assertFalse(Authenticator.objects.filter(user=self.user).exists())
        self.assertFalse(ComplianceAuditEvent.objects.filter(action='staff_browser.enrollment_activated').exists())
        self.assertNotIn(SECRET_SESSION_KEY, self.client.session)
        self.assertNotIn(ENROLLMENT_CONTEXT_KEY, self.client.session)

    def test_recovery_audit_failure_rolls_back_view_mark_and_discloses_nothing(self):
        self.begin()
        self.confirm()
        with patch('staff_auth.enrollment.record_event', side_effect=RuntimeError('Synthetic outage')):
            result = self.post('enrollment/recovery-codes', {'request_key': key()})
        self.assertEqual(result.status_code, 503)
        self.assertNotIn('recovery_codes', result.json())
        recovery = Authenticator.objects.get(user=self.user, type='recovery_codes')
        self.assertNotIn('viewed_at', recovery.data)
        self.assertNotIn(ENROLLMENT_CONTEXT_KEY, self.client.session)
        self.assert_not_business()

    def test_admission_revocation_blocks_pending_enrollment(self):
        self.begin()
        root = get_user_model().objects.get(username='synthetic_admission_root')
        apply_change(actor=root, target_user_id=self.user.pk, action='revoke_sessions', expected_revision=1,
                     request_key='enrollment-revocation', reason='Synthetic enrollment revocation')
        result = self.post('enrollment/confirm', {'request_key': key(), 'code': self.code()})
        self.assertEqual(result.status_code, 401)
        self.assertFalse(Authenticator.objects.filter(user=self.user).exists())

    def test_password_change_and_deactivation_block_pending_enrollment(self):
        self.begin()
        self.user.set_password('different-synthetic-password')
        self.user.save(update_fields=['password'])
        self.assertEqual(self.post('enrollment/confirm', {'request_key': key(), 'code': self.code()}).status_code, 401)
        self.assertFalse(Authenticator.objects.filter(user=self.user).exists())

    def test_inactive_staff_cannot_activate_existing_pending_seed(self):
        self.begin()
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertEqual(self.post('enrollment/confirm', {'request_key': key(), 'code': self.code()}).status_code, 401)
        self.assertFalse(Authenticator.objects.filter(user=self.user).exists())

    @override_settings(ACCOUNT_EMAIL_NOTIFICATIONS=True)
    def test_unaccepted_mail_configuration_holds_before_secret_or_factor_creation(self):
        result = self.post('enrollment/begin', {'request_key': key(), 'password': PASSWORD})
        self.assertEqual(result.status_code, 503)
        self.assertNotIn(SECRET_SESSION_KEY, self.client.session)
        self.assertFalse(Authenticator.objects.filter(user=self.user).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_logout_clears_enrollment_without_erasing_credentials(self):
        self.begin()
        self.confirm()
        self.post('logout', {})
        self.assertNotIn(ENROLLMENT_CONTEXT_KEY, self.client.session)
        self.assertNotIn(CHANNEL_KEY, self.client.session)
        self.assertEqual(Authenticator.objects.filter(user=self.user).count(), 2)

    def test_request_key_from_lost_context_cannot_rotate_seed_under_old_receipt(self):
        self.begin()
        stored = self.client.session
        stored.pop(ENROLLMENT_CONTEXT_KEY)
        stored.save()
        denied = self.post('enrollment/begin', {'request_key': self.begin_key, 'password': PASSWORD})
        self.assertEqual(denied.status_code, 409)
        self.begin()

    @override_settings(STAFF_BROWSER_AUTH_ENABLED=False)
    def test_flag_and_production_url_mounts_remain_closed(self):
        self.assertEqual(self.post('enrollment/begin', {'request_key': key(), 'password': PASSWORD}).status_code, 404)
        for action in ('begin', 'confirm', 'recovery-codes'):
            with override_settings(ROOT_URLCONF='config.urls'):
                self.assertEqual(self.client.get(f'/api/staff/auth/v1/enrollment/{action}/').status_code,404)
            with self.assertRaises(Resolver404):
                resolve(f'/test-staff-auth/v1/enrollment/{action}/', urlconf='config.urls')


@override_settings(
    ROOT_URLCONF='staff_auth.test_browser_urls', STAFF_BROWSER_AUTH_ENABLED=True,
    STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY], EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    SECURE_SSL_REDIRECT=False, ACCOUNT_EMAIL_NOTIFICATIONS=False,
)
@skipUnless(connection.vendor == 'postgresql', 'Requires actual PostgreSQL row locks, not SQLite.')
class BrowserEnrollmentConcurrencyTests(EnrollmentJourney, TransactionTestCase):
    def setUp(self):
        cache.clear()
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.user = get_user_model().objects.create_user('pg_enrollment', 'pg-enrollment@example.invalid', PASSWORD)
        admit_synthetic_user(self.user)
        EmailAddress.objects.create(user=self.user, email=self.user.email, verified=True, primary=True)
        self.client = Client(enforce_csrf_checks=True)
        self.bootstrap()
        self.password()
        self.begin()

    def race_posts(self, action, payloads):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        barrier = Barrier(2)

        def run(payload):
            close_old_connections()
            try:
                client = Client(enforce_csrf_checks=True)
                client.cookies.update(self.client.cookies)
                barrier.wait(timeout=10)
                return client.post(
                    f'/test-staff-auth/v1/{action}/', data=json.dumps(payload), content_type='application/json',
                    HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value,
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(run, payloads))

    def test_parallel_confirmation_never_creates_replacement_factor(self):
        results = self.race_posts('enrollment/confirm', [
            {'request_key': key(), 'code': self.code()}, {'request_key': key(), 'code': self.code()},
        ])
        self.assertEqual(sorted(result.status_code for result in results), [200, 409])
        self.assertEqual(Authenticator.objects.filter(user=self.user).count(), 2)
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='staff_browser.enrollment_activated').count(), 1)
        self.assertTrue(verify_integrity().ok)

    def test_parallel_recovery_handoff_has_exactly_one_disclosure(self):
        self.confirm()
        results = self.race_posts('enrollment/recovery-codes', [{'request_key': key()}, {'request_key': key()}])
        self.assertEqual(sorted(result.status_code for result in results), [200, 409])
        self.assertEqual(sum('recovery_codes' in result.json() for result in results), 1)
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='staff_browser.enrollment_recovery_viewed').count(), 1)
        self.assertTrue(verify_integrity().ok)
