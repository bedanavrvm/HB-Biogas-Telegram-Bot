"""Synthetic JSON browser authentication, never a production URL mount."""
import json
import time
from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.core import context
from allauth.mfa.models import Authenticator
from allauth.mfa.recovery_codes.internal.auth import RecoveryCodes
from allauth.mfa.totp.forms import ActivateTOTPForm
from allauth.mfa.totp.internal.auth import (
    SECRET_SESSION_KEY, TOTP, clear_totp_secret, format_hotp_value,
    generate_totp_secret, hotp_value,
)
from django.contrib.auth import SESSION_KEY, get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import Resolver404, resolve

from core.models import ComplianceAuditEvent

from .assurance import ASSURANCE_KEY
from .browser_api import _channel, require_company_browser_user
from .crypto import PREFIX, MFASecretUnavailable, encrypt_secret
from .lifecycle import apply_change
from .session_protection import CHANNEL_KEY, protected_browser_session
from .tests import PASSWORD, TEST_KEY, admit_synthetic_user


@override_settings(
    ROOT_URLCONF='staff_auth.test_browser_urls', STAFF_BROWSER_AUTH_ENABLED=True,
    STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY], EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    SECURE_SSL_REDIRECT=False,
)
class BrowserJSONAuthenticationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('json_browser_staff', 'staff@example.invalid', PASSWORD)
        admit_synthetic_user(cls.user)
        EmailAddress.objects.create(user=cls.user, email=cls.user.email, verified=True, primary=True)
        cls.secret = generate_totp_secret()
        TOTP.activate(cls.user, cls.secret)

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client = Client(enforce_csrf_checks=True)
        self.network = patch('socket.socket.connect', side_effect=AssertionError('External network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.bootstrap()

    def bootstrap(self):
        return self.client.get('/test-staff-auth/v1/session/')

    def post(self, action, data, **headers):
        return self.client.post(
            f'/test-staff-auth/v1/{action}/', data=json.dumps(data), content_type='application/json',
            HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value, **headers,
        )

    def password(self):
        return self.post('login', {'username': self.user.username, 'password': PASSWORD})

    def code(self):
        return format_hotp_value(hotp_value(self.secret, int(time.time()) // 30))

    def complete(self):
        self.assertEqual(self.password().json()['state'], 'mfa_required')
        response = self.post('mfa', {'code': self.code()})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['state'], 'authenticated')
        return response

    def test_password_mfa_audit_and_lost_response_retry(self):
        response = self.password()
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertFalse(response.json()['is_authenticated'])
        response = self.post('mfa', {'code': self.code()})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn(ASSURANCE_KEY, self.client.session)
        self.assertEqual(self.bootstrap().json()['state'], 'authenticated')
        repeated = self.post('mfa', {'code': self.code()})
        self.assertEqual(repeated.json()['state'], 'authenticated')
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='staff_browser.login_completed').count(), 1)
        for forbidden in ('email', 'display', 'methods', 'session_token', 'access_token', 'password'):
            self.assertNotIn(forbidden, response.json())
            self.assertNotIn(forbidden, response.json().get('user', {}))
        self.assertEqual(response['Cache-Control'], 'no-store, private')

    def test_csrf_wrong_origin_mixed_credentials_and_extra_fields_denied(self):
        data = {'username': self.user.username, 'password': PASSWORD}
        response = self.client.post('/test-staff-auth/v1/login/', data=json.dumps(data), content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.post('login', data, HTTP_ORIGIN='https://untrusted.example.invalid').status_code, 403)
        for header in ('HTTP_X_TELEGRAM_INIT_DATA', 'HTTP_X_SESSION_TOKEN', 'HTTP_AUTHORIZATION'):
            self.assertEqual(self.post('login', data, **{header: 'untrusted'}).status_code, 403)
        self.assertEqual(self.post('login', {**data, 'initData': 'untrusted'}).status_code, 400)
        self.assertEqual(self.post('login', {'username': self.user.username, 'password': ['wrong-type']}).status_code, 400)

    def test_wrong_code_and_direct_mfa_without_password_do_not_admit(self):
        self.assertEqual(self.post('mfa', {'code': self.code()}).status_code, 401)
        self.password()
        result = self.post('mfa', {'code': 'not-a-code'})
        self.assertEqual(result.status_code, 400)
        self.assertNotIn(ASSURANCE_KEY, self.client.session)
        self.assertEqual(self.bootstrap().json()['state'], 'mfa_required')

    def test_unenrolled_password_session_is_not_business_authentication(self):
        Authenticator.objects.filter(user=self.user).delete()
        result = self.password()
        self.assertEqual(result.status_code, 202, result.content)
        self.assertEqual(result.json()['state'], 'enrollment_required')
        self.assertFalse(result.json()['is_authenticated'])
        self.assertIn(SESSION_KEY, self.client.session)
        self.assertNotIn(ASSURANCE_KEY, self.client.session)
        request = RequestFactory().get('/')
        request.user, request.session = self.user, self.client.session
        with self.assertRaises(PermissionDenied):
            require_company_browser_user(request)

    def test_unverified_unadmitted_and_wrong_password_fail_without_mail(self):
        self.assertEqual(self.post('login', {'username': self.user.username, 'password': 'wrong'}).status_code, 400)
        EmailAddress.objects.filter(user=self.user).update(verified=False)
        self.assertEqual(self.password().status_code, 400)
        EmailAddress.objects.filter(user=self.user).update(verified=True)
        root = get_user_model().objects.get(username='synthetic_admission_root')
        apply_change(actor=root, target_user_id=self.user.pk, action='suspend', expected_revision=1,
                     request_key='json-suspend-before-login', reason='Synthetic admission denial')
        self.assertEqual(self.password().status_code, 400)
        self.assertEqual(len(mail.outbox), 0)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_revocation_between_password_and_mfa_denies_and_does_not_consume_factor(self):
        self.password()
        root = get_user_model().objects.get(username='synthetic_admission_root')
        apply_change(actor=root, target_user_id=self.user.pk, action='revoke_sessions', expected_revision=1,
                     request_key='json-revoke-before-mfa', reason='Synthetic pending login revocation')
        self.assertEqual(self.post('mfa', {'code': self.code()}).status_code, 401)
        self.assertNotIn(ASSURANCE_KEY, self.client.session)
        self.assertFalse(ComplianceAuditEvent.objects.filter(action='staff_browser.login_completed').exists())

    def test_audit_failure_cannot_leave_usable_browser_session(self):
        self.password()
        with patch('staff_auth.browser_api.record_event', side_effect=RuntimeError('Synthetic ledger outage')):
            response = self.post('mfa', {'code': self.code()})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(ASSURANCE_KEY, self.client.session)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertNotIn(CHANNEL_KEY, self.client.session)

    def test_recovery_code_native_login_is_single_use(self):
        codes = RecoveryCodes.activate(self.user)
        recovery_code = codes.get_unused_codes()[0]
        self.password()
        self.assertEqual(self.post('mfa', {'code': recovery_code}).json()['state'], 'authenticated')
        self.post('logout', {})
        self.bootstrap()
        self.password()
        self.assertEqual(self.post('mfa', {'code': recovery_code}).status_code, 400)

    def test_ordinary_cookie_does_not_qualify_and_browser_logout_preserves_it(self):
        self.client.force_login(self.user)
        self.bootstrap()
        self.assertEqual(self.bootstrap().json()['state'], 'signed_out')
        self.assertEqual(self.post('logout', {}).status_code, 200)
        self.assertIn(SESSION_KEY, self.client.session)
        self.assertEqual(self.password().status_code, 409)

    def test_expired_browser_context_can_explicitly_logout_its_own_session(self):
        self.complete()
        stored = self.client.session
        channel = dict(stored[CHANNEL_KEY])
        channel['started_at'] = 0
        stored[CHANNEL_KEY] = channel
        stored.save()
        self.assertEqual(self.bootstrap().json()['state'], 'signed_out')
        self.assertEqual(self.post('logout', {}).status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_expired_owned_session_can_start_a_new_password_login(self):
        self.complete()
        session = self.client.session
        marker = session[ASSURANCE_KEY]
        session[ASSURANCE_KEY] = {**marker, 'at': time.time() - 86401}
        session.save()
        self.assertEqual(self.bootstrap().json()['state'], 'signed_out')
        self.assertEqual(self.password().json()['state'], 'mfa_required')
        self.assertNotIn(ASSURANCE_KEY, self.client.session)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_mismatched_browser_context_does_not_replace_an_ordinary_cookie(self):
        self.client.force_login(self.user)
        stored = self.client.session
        stored[CHANNEL_KEY] = {'user_id': self.user.pk + 1}
        stored.save()
        self.assertEqual(self.password().status_code, 409)
        self.assertIn(SESSION_KEY, self.client.session)

    def test_removed_factor_does_not_downgrade_completed_login_to_enrollment(self):
        self.complete()
        Authenticator.objects.filter(user=self.user).delete()
        self.assertEqual(self.bootstrap().json()['state'], 'signed_out')

    def test_channel_context_cannot_be_used_by_different_cookie_identity(self):
        self.complete()
        other = get_user_model().objects.create_user('other_json_browser_actor')
        request = RequestFactory().get('/')
        request.user, request.session = other, self.client.session
        self.assertEqual(_channel(request), (None, None))
        with self.assertRaises(PermissionDenied):
            require_company_browser_user(request)

    def test_identity_rate_limit_is_durable_and_cannot_be_silent_fallback(self):
        denied = {'allowed': False, 'retry_after': 27}
        from types import SimpleNamespace
        with patch('staff_auth.browser_api.consume_identity', return_value=SimpleNamespace(**denied)):
            result = self.password()
        self.assertEqual(result.status_code, 429)
        self.assertEqual(result['Retry-After'], '27')
        self.assertNotIn(SESSION_KEY, self.client.session)

    @override_settings(STAFF_BROWSER_AUTH_ENABLED=False)
    def test_disabled_boundary_and_production_routes_are_unavailable(self):
        self.assertEqual(self.bootstrap().status_code, 404)
        for url in ('/api/staff/auth/v1/login/', '/test-staff-auth/v1/login/', '/accounts/login/'):
            with self.assertRaises(Resolver404):
                resolve(url, urlconf='config.urls')


@override_settings(STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY], EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PendingEnrollmentSecretTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('pending_secret_staff', 'pending@example.invalid')
        admit_synthetic_user(self.user)
        EmailAddress.objects.create(user=self.user, email=self.user.email, primary=True, verified=True)
        self.request = RequestFactory().get('/')
        self.request.user = self.user
        self.request.session = SessionStore()

    def test_native_form_get_post_secret_is_encrypted_in_the_persisted_session(self):
        with protected_browser_session(self.request), context.request_context(self.request):
            form = ActivateTOTPForm(user=self.user)
            secret = form.secret
            original = self.request.session.wrapped
            self.assertTrue(original[SECRET_SESSION_KEY].startswith(PREFIX))
            self.assertNotIn(secret, original[SECRET_SESSION_KEY])
            original.save()
            restored = SessionStore(session_key=original.session_key)
            self.assertTrue(restored[SECRET_SESSION_KEY].startswith(PREFIX))
            code = format_hotp_value(hotp_value(secret, int(time.time()) // 30))
            form = ActivateTOTPForm(user=self.user, data={'code': code})
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.secret, secret)
            clear_totp_secret(self.request)
            self.assertNotIn(SECRET_SESSION_KEY, original)
        self.assertIs(self.request.session, original)

    def test_expiry_plaintext_tamper_and_wrong_purpose_fail_closed_and_clear_material(self):
        for raw in ('plaintext-not-adopted', PREFIX + 'tampered', encrypt_secret('[]')):
            self.request.session[SECRET_SESSION_KEY] = raw
            with protected_browser_session(self.request):
                with self.assertRaises(MFASecretUnavailable):
                    self.request.session.get(SECRET_SESSION_KEY)
            self.assertNotIn(SECRET_SESSION_KEY, self.request.session)
        with protected_browser_session(self.request):
            self.request.session[SECRET_SESSION_KEY] = 'synthetic-pending-secret'
        now = time.time()
        with patch('staff_auth.session_protection.time.time', return_value=now + 601), protected_browser_session(self.request):
            with self.assertRaises(MFASecretUnavailable):
                self.request.session.get(SECRET_SESSION_KEY)
        self.assertNotIn(SECRET_SESSION_KEY, self.request.session)

    def test_revocation_cannot_reuse_pending_secret_and_discard_never_needs_decryption(self):
        with protected_browser_session(self.request):
            self.request.session[SECRET_SESSION_KEY] = 'synthetic-pending-secret'
        root = get_user_model().objects.get(username='synthetic_admission_root')
        apply_change(actor=root, target_user_id=self.user.pk, action='revoke_sessions', expected_revision=1,
                     request_key='pending-secret-revocation', reason='Synthetic pending enrollment invalidation')
        with protected_browser_session(self.request):
            with self.assertRaises(MFASecretUnavailable):
                self.request.session.get(SECRET_SESSION_KEY)
            self.request.session.wrapped[SECRET_SESSION_KEY] = 'unreadable-material'
            clear_totp_secret(self.request)
        self.assertNotIn(SECRET_SESSION_KEY, self.request.session)
