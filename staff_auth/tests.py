"""Synthetic-only MFA contracts; no business URLs or external services."""
import time
from datetime import timedelta
from unittest.mock import patch

from allauth.account.adapter import get_adapter as get_account_adapter
from allauth.account.internal.flows.login import (
    AUTHENTICATION_METHODS_SESSION_KEY,
    record_authentication,
)
from allauth.account.models import EmailAddress
from allauth.account.signals import user_logged_in as allauth_logged_in
from allauth.mfa.models import Authenticator
from allauth.mfa.recovery_codes.internal.auth import RecoveryCodes
from allauth.mfa.totp.internal.auth import (
    TOTP,
    format_hotp_value,
    generate_totp_secret,
    hotp_value,
)
from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import (
    HASH_SESSION_KEY,
    SESSION_KEY,
    get_user_model,
    login,
    logout,
)
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import Resolver404, resolve
from django.utils import timezone

from core.production import production_security_readiness_issues

from .assurance import ASSURANCE_KEY, issue_assurance, require_browser_user
from .checks import staff_browser_checks
from .crypto import PREFIX, MFASecretUnavailable, decrypt_secret, encrypt_secret
from .lifecycle import apply_change


def admit_synthetic_user(user):
    """Explicit opt-in, never a production data backfill or a workflow grant."""
    root = get_user_model().objects.create_superuser('synthetic_admission_root', 'root@example.invalid', None)
    return apply_change(
        actor=root, target_user_id=user.pk, action='authorize', expected_revision=0,
        request_key=f'initial-admission-{user.pk}', reason='Synthetic test opt-in only',
    )


# Ephemeral test-only keys; never actual deployment credentials.
TEST_KEY = Fernet.generate_key().decode('ascii')
SECOND_KEY = Fernet.generate_key().decode('ascii')
PASSWORD = 'synthetic-auth-only-password-217'


@override_settings(STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY])
class MFAEncryptionTests(SimpleTestCase):
    def test_ciphertext_is_versioned_randomized_and_round_trips(self):
        first = encrypt_secret('synthetic-secret')
        second = encrypt_secret('synthetic-secret')
        self.assertTrue(first.startswith(PREFIX))
        self.assertNotIn('synthetic-secret', first)
        self.assertNotEqual(first, second)
        self.assertEqual(decrypt_secret(first), 'synthetic-secret')

    def test_rotation_reads_old_and_writes_new_key(self):
        old = encrypt_secret('rotation-test')
        with override_settings(STAFF_MFA_ENCRYPTION_KEYS=[SECOND_KEY, TEST_KEY]):
            self.assertEqual(decrypt_secret(old), 'rotation-test')
            new = encrypt_secret('rotation-test')
        with override_settings(STAFF_MFA_ENCRYPTION_KEYS=[SECOND_KEY]):
            self.assertEqual(decrypt_secret(new), 'rotation-test')
            with self.assertRaises(MFASecretUnavailable):
                decrypt_secret(old)

    def test_plaintext_tampered_wrong_key_and_empty_material_are_rejected(self):
        encrypted = encrypt_secret('no-plaintext-fallback')
        for value in ('no-plaintext-fallback', '', None, PREFIX + 'malformed', encrypted[:-9] + 'corrupt!!'):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(MFASecretUnavailable):
                    decrypt_secret(value)
        with override_settings(STAFF_MFA_ENCRYPTION_KEYS=[SECOND_KEY]):
            with self.assertRaises(MFASecretUnavailable):
                decrypt_secret(encrypted)
        for value in ('', None, 123):
            with self.assertRaises(MFASecretUnavailable):
                encrypt_secret(value)

    def test_missing_malformed_duplicate_and_django_secret_keys_fail_safely(self):
        for keys in ([], 'not-a-key-list', ['malformed'], [TEST_KEY, TEST_KEY], [settings.SECRET_KEY], [None], ['non-ascii-\u00e9']):
            with self.subTest(keys_type=type(keys).__name__), override_settings(STAFF_MFA_ENCRYPTION_KEYS=keys):
                with self.assertRaises(ImproperlyConfigured) as raised:
                    encrypt_secret('never-disclose-this')
                self.assertNotIn('never-disclose-this', str(raised.exception))
                self.assertNotIn(TEST_KEY, str(raised.exception))


@override_settings(CACHES={'default':{'BACKEND':'django.core.cache.backends.locmem.LocMemCache',
    'KEY_FUNCTION':'staff_auth.cache_keys.native_cache_key'}})
class DormantConfigurationTests(SimpleTestCase):
    def test_generic_admin_registration_cannot_reexpose_identity_editors(self):
        from core.admin_utils import auto_register_unregistered_models
        from .models import StaffBrowserAdmission
        for app_label in ('staff_auth', 'account', 'mfa'):
            self.assertEqual(auto_register_unregistered_models(app_label=app_label), [])
        self.assertTrue(admin.site.is_registered(StaffBrowserAdmission))
        for model in (Authenticator, EmailAddress):
            self.assertFalse(admin.site.is_registered(model))

    def test_vendor_credential_editors_are_not_exposed_in_admin(self):
        self.assertFalse(admin.site.is_registered(Authenticator))
        self.assertFalse(admin.site.is_registered(EmailAddress))

    def test_closed_signup_and_no_production_account_routes(self):
        self.assertFalse(get_account_adapter().is_open_for_signup(RequestFactory().get('/')))
        for enabled in (False, True):
            with override_settings(STAFF_BROWSER_AUTH_ENABLED=enabled):
                for url in ('/accounts/login/', '/staff-browser/login/', '/test-accounts/login/'):
                    with self.subTest(enabled=enabled, url=url), self.assertRaises(Resolver404):
                        resolve(url, urlconf='config.urls')

    @override_settings(STAFF_BROWSER_AUTH_ENABLED=False, STAFF_MFA_ENCRYPTION_KEYS=[])
    def test_dormant_foundation_does_not_require_live_encryption_keys(self):
        self.assertEqual(staff_browser_checks(None), [])

    @override_settings(STAFF_BROWSER_AUTH_ENABLED=True, STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY], DEBUG=True)
    def test_even_safe_configuration_cannot_activate_incomplete_browser_product(self):
        self.assertEqual([issue.id for issue in staff_browser_checks(None)], ['staff_auth.E006', 'staff_auth.E007'])
        issues = production_security_readiness_issues(settings, check_database=False)
        self.assertTrue(any(issue.code.startswith('staff-browser-') for issue in issues))

    @override_settings(STAFF_BROWSER_AUTH_ENABLED=True, STAFF_MFA_ENCRYPTION_KEYS=[])
    def test_unsafe_configuration_has_explicit_failures(self):
        with override_settings(
            MFA_ADAPTER='allauth.mfa.adapter.DefaultMFAAdapter',
            MFA_TRUST_ENABLED=True, STAFF_BROWSER_SESSION_AGE_SECONDS=True,
            DEBUG=False, SESSION_COOKIE_SECURE=False,
        ):
            self.assertEqual(
                {issue.id for issue in staff_browser_checks(None)},
                {f'staff_auth.E00{index}' for index in range(1, 8)},
            )


@override_settings(
    STAFF_BROWSER_AUTH_ENABLED=True,
    STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY],
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    SECURE_SSL_REDIRECT=False,
)
class BrowserAssuranceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user('synthetic_browser_actor', password=PASSWORD)
        # datetime.now() and time.time() can straddle different Windows clock
        # ticks. This fixture requires admission strictly before authentication;
        # give it an explicit past instant instead of relaxing runtime checks.
        with patch('django.utils.timezone.now', return_value=timezone.now() - timedelta(seconds=1)):
            admit_synthetic_user(self.user)
        self.secret = generate_totp_secret()
        self.totp = TOTP.activate(self.user, self.secret).instance
        self.request = RequestFactory().get('/synthetic-probe/')
        SessionMiddleware(lambda request: None).process_request(self.request)
        self.request.user = AnonymousUser()

    def completed_login(self):
        # Each journey starts a new pre-authentication session, including after
        # deliberate corrupt-session tests. Do not feed invalid IDs to login().
        self.request.session.flush()
        self.request.user = AnonymousUser()
        record_authentication(self.request, self.user, method='password', username=self.user.username)
        record_authentication(self.request, self.user, method='mfa', id=self.totp.pk, type='totp')
        login(self.request, self.user, backend='django.contrib.auth.backends.ModelBackend')
        allauth_logged_in.send(sender=type(self.user), request=self.request, user=self.user)

    def assert_denied(self):
        with self.assertRaises(PermissionDenied):
            require_browser_user(self.request)
        self.assertNotIn(ASSURANCE_KEY, self.request.session)

    def test_completed_password_and_totp_login_admits_identity_without_grants(self):
        self.completed_login()
        self.assertEqual(require_browser_user(self.request).pk, self.user.pk)
        self.assertFalse(self.user.access_grants.exists())

    def test_password_only_and_ordinary_django_login_cannot_issue_assurance(self):
        record_authentication(self.request, self.user, method='password')
        login(self.request, self.user, backend='django.contrib.auth.backends.ModelBackend')
        self.assertFalse(issue_assurance(self.request, self.user))
        self.assert_denied()

    def test_anonymous_pending_and_mfa_only_records_do_not_admit(self):
        record_authentication(self.request, self.user, method='password')
        self.assertFalse(issue_assurance(self.request, self.user))
        self.assert_denied()
        login(self.request, self.user, backend='django.contrib.auth.backends.ModelBackend')
        self.request.session[AUTHENTICATION_METHODS_SESSION_KEY] = [{'method': 'mfa', 'at': time.time(), 'id': self.totp.pk, 'type': 'totp'}]
        self.assertFalse(issue_assurance(self.request, self.user))
        self.assert_denied()

    def test_ordinary_telegram_login_and_logout_clear_existing_assurance(self):
        self.completed_login()
        login(self.request, self.user, backend='core.auth_backends.TelegramMiniAppBackend')
        self.assert_denied()
        self.completed_login()
        logout(self.request)
        self.assert_denied()

    def test_switch_off_and_mixed_telegram_credentials_deny(self):
        self.completed_login()
        with override_settings(STAFF_BROWSER_AUTH_ENABLED=False):
            self.assert_denied()
            self.assertFalse(issue_assurance(self.request, self.user))
        self.completed_login()
        self.request.META['HTTP_X_TELEGRAM_INIT_DATA'] = 'synthetic-not-a-signed-payload'
        self.assert_denied()

    def test_current_deactivation_password_change_and_factor_deletion_revoke(self):
        self.completed_login()
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        self.assert_denied()
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=True)
        self.completed_login()
        changed = get_user_model().objects.get(pk=self.user.pk)
        changed.set_password('changed-synthetic-password')
        changed.save(update_fields=['password'])
        self.assert_denied()
        self.user.refresh_from_db()
        self.completed_login()
        self.totp.delete()
        self.assert_denied()

    def test_factor_replacement_invalidates_marker(self):
        self.completed_login()
        self.totp.data = {'secret': encrypt_secret(generate_totp_secret())}
        self.totp.save(update_fields=['data'])
        self.assert_denied()

    def test_malformed_or_expired_markers_deny_instead_of_error(self):
        for field, value in (
            ('at', time.time() - 90000), ('at', time.time() + 90000),
            ('at', 'nan'), ('at', 'bad'), ('user_id', 'different'),
            ('auth_hash', 'bad-\u00e9'), ('totp_id', []), ('totp_id', 10**100),
            ('totp_fingerprint', 'bad-\u00e9'),
        ):
            with self.subTest(field=field):
                self.completed_login()
                marker = dict(self.request.session[ASSURANCE_KEY])
                marker[field] = value
                self.request.session[ASSURANCE_KEY] = marker
                self.assert_denied()

    def test_invalid_authentication_records_never_issue(self):
        self.completed_login()
        for records in (
            None, {}, [None], [],
            [{'method': 'password', 'at': time.time()}, {'method': 'mfa', 'at': time.time(), 'id': [], 'type': 'totp'}],
            [{'method': 'password', 'at': 0}, {'method': 'mfa', 'at': time.time(), 'id': self.totp.pk, 'type': 'totp'}],
            [{'method': 'password', 'at': time.time()}, {'method': 'mfa', 'at': float('inf'), 'id': self.totp.pk, 'type': 'totp'}],
            [{'method': 'password', 'at': time.time()}, {'method': 'mfa', 'at': time.time(), 'id': self.totp.pk, 'type': 'webauthn'}],
        ):
            with self.subTest(records_type=type(records).__name__):
                self.request.session[AUTHENTICATION_METHODS_SESSION_KEY] = records
                self.assertFalse(issue_assurance(self.request, self.user))
                self.assert_denied()

    def test_session_user_and_hash_must_match_the_completed_actor(self):
        for field in (SESSION_KEY, HASH_SESSION_KEY):
            self.completed_login()
            self.request.session[field] = 'other-session'
            self.assertFalse(issue_assurance(self.request, self.user))
            self.assert_denied()

    def test_vendor_totp_and_recovery_material_use_encryption_and_recovery_is_single_use(self):
        self.assertNotIn(self.secret, str(self.totp.data))
        self.assertTrue(self.totp.data['secret'].startswith(PREFIX))
        recovery = RecoveryCodes.activate(self.user)
        self.assertTrue(recovery.instance.data['seed'].startswith(PREFIX))
        code = recovery.get_unused_codes()[0]
        self.assertTrue(recovery.validate_code(code))
        self.assertFalse(recovery.validate_code(code))
        record_authentication(self.request, self.user, method='password')
        record_authentication(self.request, self.user, method='mfa', id=recovery.instance.pk, type='recovery_codes')
        login(self.request, self.user, backend='django.contrib.auth.backends.ModelBackend')
        allauth_logged_in.send(sender=type(self.user), request=self.request, user=self.user)
        self.assertEqual(require_browser_user(self.request).pk, self.user.pk)


@override_settings(
    ROOT_URLCONF='staff_auth.test_urls',
    HEADLESS_ONLY=False,  # This historical fixture explicitly exercises headed views.
    STAFF_BROWSER_AUTH_ENABLED=True,
    STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY],
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    SECURE_SSL_REDIRECT=False,
    LOGIN_REDIRECT_URL='/test-browser/protected/',
)
class VendorPasswordMFAJourneyTests(TestCase):
    """Exercise real pinned vendor stages, not a homemade MFA implementation."""
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user('synthetic_vendor_actor', 'synthetic@example.invalid', PASSWORD)
        admit_synthetic_user(self.user)
        EmailAddress.objects.create(user=self.user, email=self.user.email, primary=True, verified=True)
        self.secret = generate_totp_secret()
        TOTP.activate(self.user, self.secret)
        self.client = Client(enforce_csrf_checks=True)
        # Detect unexpected network use without allowing calls to real services.
        self.network = patch('socket.socket.connect', side_effect=AssertionError('External network forbidden in MFA tests'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def post_with_csrf(self, url, data):
        data['csrfmiddlewaretoken'] = self.client.cookies['csrftoken'].value
        return self.client.post(url, data)

    def password_stage(self):
        self.assertEqual(self.client.get('/test-accounts/login/').status_code, 200)
        response = self.post_with_csrf('/test-accounts/login/', {'login': self.user.username, 'password': PASSWORD})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/test-accounts/2fa/authenticate/', response.url)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertNotIn(ASSURANCE_KEY, self.client.session)
        self.assertEqual(self.client.get('/test-browser/protected/').status_code, 403)

    def test_real_password_then_totp_and_csrf_journey(self):
        self.password_stage()
        code = format_hotp_value(hotp_value(self.secret, int(time.time()) // 30))
        self.assertEqual(self.client.post('/test-accounts/2fa/authenticate/', {'code': code}).status_code, 403)
        result = self.post_with_csrf('/test-accounts/2fa/authenticate/', {'code': code})
        self.assertEqual(result.status_code, 302)
        self.assertIn(ASSURANCE_KEY, self.client.session)
        self.assertEqual(self.client.get('/test-browser/protected/').json()['user_id'], self.user.pk)
        self.assertEqual(self.client.post('/test-browser/protected/', {}).status_code, 403)

    def test_wrong_factor_and_unenrolled_password_login_do_not_admit(self):
        self.password_stage()
        expected = format_hotp_value(hotp_value(self.secret, int(time.time()) // 30))
        wrong = str((int(expected) + 177) % 1000000).zfill(6)
        response = self.post_with_csrf('/test-accounts/2fa/authenticate/', {'code': wrong})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertEqual(self.client.get('/test-browser/protected/').status_code, 403)
        Authenticator.objects.filter(user=self.user).delete()
        self.client = Client(enforce_csrf_checks=True)
        self.client.get('/test-accounts/login/')
        response = self.post_with_csrf('/test-accounts/login/', {'login': self.user.username, 'password': PASSWORD})
        self.assertEqual(response.status_code, 302)
        # Vendor accounts without a factor can establish a Django login, but
        # our separate business boundary still cannot admit them.
        self.assertIn(SESSION_KEY, self.client.session)
        self.assertNotIn(ASSURANCE_KEY, self.client.session)
        self.assertEqual(self.client.get('/test-browser/protected/').status_code, 403)
