"""Synthetic abuse boundaries: proxy trust, native limits, privacy and outages."""
import json
import re
import time
import warnings
from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.mfa.totp.internal.auth import TOTP, generate_totp_secret
from django.conf import global_settings, settings
from django.contrib.auth import SESSION_KEY, get_user_model
from django.core.cache import CacheKeyWarning, cache
from django.core.cache.backends.base import default_key_func
from django.core.cache.backends.locmem import LocMemCache
from django.db import OperationalError
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings

from core.models import ComplianceAuditEvent, PublicEndpointThrottleBucket
from .abuse import consume_network
from .assurance import ASSURANCE_KEY
from .browser_api import _throttle
from .cache_keys import PRIVACY_KEY_FUNCTION, SHARED_CACHE_BACKENDS, native_cache_key
from .checks import staff_browser_checks
from .lifecycle import apply_change
from .session_protection import CHANNEL_KEY
from .tests import PASSWORD, TEST_KEY, admit_synthetic_user
from .tests_enrollment import EnrollmentJourney, key


class NativeCachePrivacyTests(SimpleTestCase):
    def test_default_cache_changes_only_the_native_key_hook(self):
        configured = dict(settings.CACHES['default'])
        self.assertEqual(configured.pop('KEY_FUNCTION'), PRIVACY_KEY_FUNCTION)
        self.assertEqual(configured, global_settings.CACHES['default'])

    def test_only_native_namespaces_change_and_prefix_version_secret_are_bound(self):
        for key in ('origination:template:one', 'daraja_access_token', 'diagnostics:test', 123):
            self.assertEqual(native_cache_key(key, 'prefix', 3), default_key_func(key, 'prefix', 3))
        raw = 'allauth.mfa.totp.used?user=123&code=12 34-56'
        first = native_cache_key(raw, 'prefix', 1)
        self.assertRegex(first, r'^staff-auth:v1:[a-f0-9]{64}$')
        self.assertNotIn('12 34-56', first)
        self.assertEqual(first, native_cache_key(raw, 'prefix', 1))
        self.assertNotEqual(first, native_cache_key(raw, 'other', 1))
        self.assertNotEqual(first, native_cache_key(raw, 'prefix', 2))
        with override_settings(SECRET_KEY='synthetic-rotated-key'):
            self.assertNotEqual(first, native_cache_key(raw, 'prefix', 1))

    def test_real_native_formatted_totp_has_no_raw_key_or_cache_warning(self):
        local = LocMemCache('synthetic-privacy-boundary', {'KEY_FUNCTION': PRIVACY_KEY_FUNCTION})
        local.clear()
        self.addCleanup(local.clear)
        factor = type('SyntheticFactor', (), {'user_id': 123})()
        with warnings.catch_warnings(record=True) as captured, patch('allauth.mfa.totp.internal.auth.cache', local):
            self.assertTrue(TOTP(factor)._mark_code_used('12 34-56'))
            self.assertFalse(TOTP(factor)._mark_code_used('12 34-56'))
        self.assertFalse(any(issubclass(item.category, CacheKeyWarning) for item in captured))
        self.assertTrue(all(re.fullmatch(r'staff-auth:v1:[a-f0-9]{64}', key) for key in local._cache))

    @override_settings(STAFF_BROWSER_AUTH_ENABLED=True, STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY], DEBUG=True)
    def test_activation_requires_shared_backend_and_privacy_without_connecting(self):
        with patch('socket.socket.connect', side_effect=AssertionError('No readiness network access')):
            self.assertEqual({issue.id for issue in staff_browser_checks(None)}, {'staff_auth.E006', 'staff_auth.E007'})
            for backend in SHARED_CACHE_BACKENDS:
                with self.subTest(backend=backend), override_settings(CACHES={'default': {
                    'BACKEND': backend, 'LOCATION': 'synthetic-not-contacted', 'KEY_FUNCTION': PRIVACY_KEY_FUNCTION,
                }}):
                    self.assertEqual([issue.id for issue in staff_browser_checks(None)], ['staff_auth.E006'])
            for backend in ('django.core.cache.backends.dummy.DummyCache', 'django.core.cache.backends.filebased.FileBasedCache',
                            'django.core.cache.backends.db.DatabaseCache', 'unreviewed.CustomCache'):
                with self.subTest(backend=backend), override_settings(CACHES={'default': {'BACKEND': backend}}):
                    self.assertEqual({issue.id for issue in staff_browser_checks(None)},
                                     {'staff_auth.E006', 'staff_auth.E007', 'staff_auth.E008'})


@override_settings(ALLAUTH_TRUSTED_PROXY_COUNT=0, ALLAUTH_TRUSTED_CLIENT_IP_HEADER=None)
class BrowserNetworkPolicyTests(TestCase):
    def test_spoofed_forwarded_addresses_share_one_durable_network_limit(self):
        for index in range(31):
            request = RequestFactory().post('/', REMOTE_ADDR='192.0.2.20', HTTP_X_FORWARDED_FOR=f'198.51.100.{index}')
            response = _throttle(request, 'synthetic-network', f'distinct-actor-{index}')
            self.assertEqual(response is None, index < 30)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(PublicEndpointThrottleBucket.objects.filter(scope='staff-browser-synthetic-network').count(), 32)
        stored = list(PublicEndpointThrottleBucket.objects.values_list('key_hash', flat=True))
        self.assertTrue(all(re.fullmatch(r'[a-f0-9]{64}', key) for key in stored))

    def test_ipv6_rotation_within_native_prefix_shares_a_bucket(self):
        for address in ('2001:db8:1234:5678::1', '2001:db8:1234:5678::9'):
            decision = consume_network(RequestFactory().post('/', REMOTE_ADDR=address), scope='synthetic-v6', limit=1)
        self.assertFalse(decision.allowed)
        self.assertEqual(PublicEndpointThrottleBucket.objects.filter(scope='synthetic-v6').count(), 1)

    @override_settings(ALLAUTH_TRUSTED_PROXY_COUNT=1)
    def test_explicit_native_proxy_policy_uses_last_trusted_hop(self):
        for forwarded in ('198.51.100.1, 192.0.2.20', '198.51.100.2, 192.0.2.20'):
            request = RequestFactory().post('/', REMOTE_ADDR='192.0.2.99', HTTP_X_FORWARDED_FOR=forwarded)
            decision = consume_network(request, scope='synthetic-proxy', limit=1)
        self.assertFalse(decision.allowed)


@override_settings(
    ROOT_URLCONF='staff_auth.test_browser_urls', STAFF_BROWSER_AUTH_ENABLED=True,
    STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY], EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    SECURE_SSL_REDIRECT=False, ALLAUTH_TRUSTED_PROXY_COUNT=0, ALLAUTH_TRUSTED_CLIENT_IP_HEADER=None,
)
class BrowserNativeAbuseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('abuse_staff', 'abuse@example.invalid', PASSWORD)
        admit_synthetic_user(cls.user)
        EmailAddress.objects.create(user=cls.user, email=cls.user.email, verified=True, primary=True)
        TOTP.activate(cls.user, generate_totp_secret())

    def setUp(self):
        cache.clear()
        network = patch('socket.socket.connect', side_effect=AssertionError('No external access'))
        network.start()
        self.addCleanup(network.stop)
        self.client = Client(enforce_csrf_checks=True)
        self.client.get('/test-staff-auth/v1/session/')

    def post(self, action, data):
        return self.client.post(f'/test-staff-auth/v1/{action}/', data=json.dumps(data), content_type='application/json',
                                HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)

    def password(self, password=PASSWORD):
        return self.post('login', {'username': self.user.username, 'password': password})

    def assert_no_login(self):
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertNotIn(ASSURANCE_KEY, self.client.session)
        self.assertFalse(ComplianceAuditEvent.objects.filter(action='staff_browser.login_completed').exists())

    @override_settings(ACCOUNT_RATE_LIMITS={'login': '1/m/ip'})
    def test_native_view_429_is_not_an_incorrect_password(self):
        self.assertEqual(self.password().json()['state'], 'mfa_required')
        response = self.password()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()['state'], 'rate_limited')
        self.assertEqual(response['Retry-After'], '60')
        self.assert_no_login()

    @override_settings(ACCOUNT_RATE_LIMITS={'login_failed': '1/m/key'})
    def test_native_password_form_throttle_is_not_an_incorrect_password(self):
        self.assertEqual(self.password('incorrect').status_code, 400)
        response = self.password()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()['state'], 'rate_limited')
        self.assert_no_login()

    @override_settings(ACCOUNT_RATE_LIMITS={'login_failed': '1/m/key'})
    def test_native_mfa_form_throttle_is_not_an_incorrect_code(self):
        self.assertEqual(self.password().json()['state'], 'mfa_required')
        self.assertEqual(self.post('mfa', {'code': 'incorrect'}).status_code, 400)
        response = self.post('mfa', {'code': 'incorrect-again'})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()['state'], 'rate_limited')
        self.assertEqual(self.client.get('/test-staff-auth/v1/session/').json()['state'], 'mfa_required')
        self.assert_no_login()

    def test_native_cache_failure_has_safe_feedback_and_persisted_cleanup(self):
        for action in ('login', 'mfa'):
            with self.subTest(action=action):
                if action == 'mfa':
                    self.assertEqual(self.password().json()['state'], 'mfa_required')
                with (patch('allauth.core.internal.ratelimit.cache.get', side_effect=RuntimeError('sensitive-cache-key')),
                      self.assertLogs('staff_auth.abuse', level='ERROR') as captured):
                    response = self.password() if action == 'login' else self.post('mfa', {'code': 'incorrect'})
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json(), {'state': 'authentication_unavailable', 'is_authenticated': False})
                self.assertNotIn('sensitive-cache-key', '\n'.join(captured.output))
                self.assertNotIn(CHANNEL_KEY, self.client.session)
                self.assert_no_login()

    def test_database_throttle_failure_does_not_call_native_login_or_replace_admin_cookie(self):
        self.client.force_login(self.user)
        original_key = self.client.session.session_key
        with (patch('staff_auth.browser_api.consume_identity', side_effect=OperationalError('sensitive-storage-details')),
              patch('staff_auth.browser_api._login') as native):
            response = self.password()
        self.assertEqual(response.status_code, 503)
        native.assert_not_called()
        self.assertNotIn('sensitive-storage-details', response.content.decode())
        self.assertEqual(self.client.session.session_key, original_key)
        self.assertEqual(self.client.session[SESSION_KEY], str(self.user.pk))
        self.assertNotIn(ASSURANCE_KEY, self.client.session)

    def test_setup_bootstrap_uses_same_nonspoofable_network_limit(self):
        for index in range(31):
            response = self.client.get('/test-staff-auth/v1/setup/session/', HTTP_X_FORWARDED_FOR=f'198.51.100.{index}')
            self.assertEqual(response.status_code, 200 if index < 30 else 429)
        self.assertEqual(response.json()['state'], 'rate_limited')

    def test_same_clock_tick_revocation_denies_pending_native_login_by_generation(self):
        at = time.time() + 1
        with patch('time.time', return_value=at), patch('django.utils.timezone.now', return_value=datetime.fromtimestamp(at, dt_timezone.utc)):
            self.assertEqual(self.password().json()['state'], 'mfa_required')
            root = get_user_model().objects.get(username='synthetic_admission_root')
            apply_change(actor=root, target_user_id=self.user.pk, action='revoke_sessions', expected_revision=1,
                         request_key='synthetic-same-tick-revocation', reason='Synthetic same-tick revocation check')
            response = self.post('mfa', {'code': 'not-accepted'})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['state'], 'signed_out')
        self.assert_no_login()


@override_settings(
    ROOT_URLCONF='staff_auth.test_browser_urls', STAFF_BROWSER_AUTH_ENABLED=True,
    STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY], EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    SECURE_SSL_REDIRECT=False, ACCOUNT_EMAIL_NOTIFICATIONS=False,
)
class BrowserEnrollmentAbuseTests(EnrollmentJourney, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('enrollment_abuse_staff', 'enrollment-abuse@example.invalid', PASSWORD)
        admit_synthetic_user(cls.user)
        EmailAddress.objects.create(user=cls.user, email=cls.user.email, verified=True, primary=True)

    def setUp(self):
        cache.clear()
        network = patch('socket.socket.connect', side_effect=AssertionError('No external access'))
        network.start()
        self.addCleanup(network.stop)
        self.client = Client(enforce_csrf_checks=True)
        self.bootstrap()
        self.assertEqual(self.password().json()['state'], 'enrollment_required')

    @override_settings(ACCOUNT_RATE_LIMITS={'login_failed': '1/m/key'})
    def test_native_enrollment_code_limit_is_429_and_preserves_draft(self):
        self.begin()
        original = self.client.session['mfa.totp.secret']
        self.assertEqual(self.post('enrollment/confirm', {'request_key': key(), 'code': 'incorrect'}).status_code, 400)
        response = self.post('enrollment/confirm', {'request_key': key(), 'code': 'incorrect-again'})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()['state'], 'rate_limited')
        self.assertEqual(response['Retry-After'], '60')
        self.assertEqual(self.client.session['mfa.totp.secret'], original)
        self.assertFalse(self.user.authenticator_set.exists())
        self.assert_not_business()

    @override_settings(ACCOUNT_RATE_LIMITS={'login_failed': '1/m/key'})
    def test_native_enrollment_password_limit_is_429(self):
        data = {'request_key': key(), 'password': 'incorrect'}
        self.assertEqual(self.post('enrollment/begin', data).status_code, 400)
        response = self.post('enrollment/begin', {'request_key': key(), 'password': PASSWORD})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()['state'], 'rate_limited')
        self.assert_not_business()

    def test_native_enrollment_cache_failure_clears_owned_password_session(self):
        self.begin()
        with (patch('allauth.core.internal.ratelimit.cache.get', side_effect=RuntimeError('sensitive-native-key')),
              self.assertLogs('staff_auth.abuse', level='ERROR')):
            response = self.post('enrollment/confirm', {'request_key': key(), 'code': 'incorrect'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['state'], 'authentication_unavailable')
        self.assertNotIn(CHANNEL_KEY, self.client.session)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertNotIn('mfa.totp.secret', self.client.session)
        self.assertFalse(self.user.authenticator_set.exists())
        self.assertFalse(ComplianceAuditEvent.objects.filter(action='staff_browser.enrollment_activated').exists())

    def test_outer_limiter_outage_preserves_draft_for_explicit_retry(self):
        self.begin()
        original_key = self.client.session.session_key
        original_seed = self.client.session['mfa.totp.secret']
        with patch('staff_auth.browser_api.consume_identity', side_effect=OperationalError('synthetic limit-store outage')):
            response = self.post('enrollment/confirm', {'request_key': key(), 'code': 'incorrect'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['state'], 'authentication_unavailable')
        self.assertEqual(self.client.session.session_key, original_key)
        self.assertEqual(self.client.session['mfa.totp.secret'], original_seed)
        self.assert_not_business()
        self.assertEqual(self.confirm().json()['state'], 'recovery_codes_required')

    def test_failure_after_native_password_success_cannot_leave_a_trapped_session(self):
        from .browser_api import _login
        self.post('logout', {})

        def partially_complete(request):
            _login(request)
            raise RuntimeError('sensitive-backend-details')

        with (patch('staff_auth.browser_api._login', side_effect=partially_complete),
              self.assertLogs('staff_auth.abuse', level='ERROR')):
            response = self.password()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(SESSION_KEY, self.client.session)
        self.assertNotIn(CHANNEL_KEY, self.client.session)
        self.assertNotIn(ASSURANCE_KEY, self.client.session)
        self.assertEqual(self.password().json()['state'], 'enrollment_required')
