"""Synthetic native browser MFA replay, outage, expiry and database races."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
import json
from threading import Barrier
import time
from unittest import skipUnless
from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.mfa.recovery_codes.internal.auth import RecoveryCodes
from allauth.mfa.totp.internal.auth import TOTP, format_hotp_value, generate_totp_secret, hotp_value
from django.contrib.auth import SESSION_KEY, get_user_model
from django.core.cache import cache
from django.core.cache import CacheKeyWarning
from django.core.cache.backends.locmem import LocMemCache
from django.core.management import call_command, CommandError
from django.db import close_old_connections, connection, OperationalError
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from core.models import ComplianceAuditEvent

from .assurance import ASSURANCE_KEY
from .models import StaffTOTPReplayState
from .replay import reserve_totp_use
from .session_protection import CHANNEL_KEY
from .tests import PASSWORD, SECOND_KEY, TEST_KEY, admit_synthetic_user


@override_settings(
    ROOT_URLCONF='staff_auth.test_browser_urls', STAFF_BROWSER_AUTH_ENABLED=True,
    STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY], EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    SECURE_SSL_REDIRECT=False,
)
class BrowserTOTPReplayTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('replay_staff', 'replay@example.invalid', PASSWORD)
        admit_synthetic_user(cls.user)
        EmailAddress.objects.create(user=cls.user, email=cls.user.email, verified=True, primary=True)
        cls.secret = generate_totp_secret()
        cls.factor = TOTP.activate(cls.user, cls.secret).instance

    def setUp(self):
        cache.clear()
        network = patch('socket.socket.connect', side_effect=AssertionError('External network forbidden'))
        network.start()
        self.addCleanup(network.stop)
        self.at = time.time()
        frozen = patch('time.time', return_value=self.at)
        frozen.start()
        self.addCleanup(frozen.stop)
        self.code = format_hotp_value(hotp_value(self.secret, int(self.at) // 30))

    def post(self, client, action, data):
        return client.post(
            f'/test-staff-auth/v1/{action}/', data=json.dumps(data), content_type='application/json',
            HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value,
        )

    def pending(self):
        client = Client(enforce_csrf_checks=True)
        client.get('/test-staff-auth/v1/session/')
        result = self.post(client, 'login', {'username': self.user.username, 'password': PASSWORD})
        self.assertEqual(result.json()['state'], 'mfa_required')
        return client

    def complete_in_worker(self, client, code, worker):
        # Distinct native cache instances represent independent workers. This
        # is boundary evidence, not a claim of a real deployed worker test.
        local = LocMemCache(f'synthetic-totp-worker-{worker}', {})
        local.clear()
        with patch('allauth.mfa.totp.internal.auth.cache', local):
            return self.post(client, 'mfa', {'code': code})

    def test_independent_native_caches_admit_one_login_and_preserve_first_session_retry(self):
        first, second = self.pending(), self.pending()
        self.assertEqual(self.complete_in_worker(first, self.code, 'one').status_code, 200)
        self.assertEqual(self.complete_in_worker(second, self.code, 'two').status_code, 400)
        self.assertNotIn(ASSURANCE_KEY, second.session)
        self.assertNotIn(SESSION_KEY, second.session)
        self.assertEqual(StaffTOTPReplayState.objects.count(), 1)
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='staff_browser.login_completed').count(), 1)
        self.assertEqual(self.post(first, 'mfa', {'code': self.code}).json()['state'], 'authenticated')
        self.assertEqual(StaffTOTPReplayState.objects.count(), 1)

    def test_native_punctuation_and_whitespace_variants_share_one_claim(self):
        first, second = self.pending(), self.pending()
        self.assertEqual(self.complete_in_worker(first, self.code, 'plain').status_code, 200)
        variant = f'{self.code[:2]}- {self.code[2:4]}.{self.code[4:]}'
        # The pinned native local cache warns about whitespace in its raw key.
        # Capture that known warning so even synthetic codes stay out of logs;
        # runtime native cache/log handling remains an explicit M1 gate.
        with self.assertWarns(CacheKeyWarning):
            response = self.complete_in_worker(second, variant, 'formatted')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(StaffTOTPReplayState.objects.count(), 1)
        self.assertNotIn(ASSURANCE_KEY, second.session)

    def test_invalid_code_never_creates_a_replay_claim(self):
        client = self.pending()
        response = self.complete_in_worker(client, 'incorrect', 'invalid')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(StaffTOTPReplayState.objects.exists())
        self.assertNotIn(ASSURANCE_KEY, client.session)

    def test_replay_store_outage_returns_safe_503_and_persists_context_cleanup(self):
        client = self.pending()
        with patch('staff_auth.replay.StaffTOTPReplayState.objects.filter', side_effect=OperationalError('synthetic storage outage')):
            response = self.complete_in_worker(client, self.code, 'outage')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'state': 'authentication_unavailable', 'is_authenticated': False})
        self.assertNotIn(CHANNEL_KEY, client.session)
        self.assertNotIn(ASSURANCE_KEY, client.session)
        self.assertNotIn(SESSION_KEY, client.session)
        self.assertFalse(ComplianceAuditEvent.objects.filter(action='staff_browser.login_completed').exists())
        self.assertEqual(client.get('/test-staff-auth/v1/session/').json()['state'], 'signed_out')

    def test_audit_failure_leaves_code_consumed_without_business_session(self):
        first, second = self.pending(), self.pending()
        with patch('staff_auth.browser_api.record_event', side_effect=RuntimeError('synthetic audit outage')):
            self.assertEqual(self.complete_in_worker(first, self.code, 'audit-outage').status_code, 503)
        self.assertEqual(StaffTOTPReplayState.objects.count(), 1)
        self.assertNotIn(ASSURANCE_KEY, first.session)
        self.assertEqual(self.complete_in_worker(second, self.code, 'after-outage').status_code, 400)

    def test_outage_with_unavailable_session_cleanup_never_reports_authenticated(self):
        from django.contrib.sessions.backends.db import SessionStore
        client = self.pending()
        with (
            patch('staff_auth.replay.reserve_totp_use', side_effect=OperationalError('synthetic replay outage')),
            patch.object(SessionStore, 'save', side_effect=OperationalError('synthetic session outage')),
        ):
            response = self.complete_in_worker(client, self.code, 'session-outage')
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()['is_authenticated'])
        self.assertNotIn(ASSURANCE_KEY, client.session)
        self.assertNotIn(SESSION_KEY, client.session)

    def test_unavailable_native_factor_key_returns_safe_503(self):
        client = self.pending()
        with override_settings(STAFF_MFA_ENCRYPTION_KEYS=[]):
            response = self.complete_in_worker(client, self.code, 'factor-key-outage')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['state'], 'authentication_unavailable')
        self.assertNotIn(ASSURANCE_KEY, client.session)
        self.assertFalse(StaffTOTPReplayState.objects.exists())

    def test_native_recovery_code_is_consumed_without_a_totp_claim(self):
        code = RecoveryCodes.activate(self.user).get_unused_codes()[0]
        first, second = self.pending(), self.pending()
        self.assertEqual(self.complete_in_worker(first, code, 'recovery-one').status_code, 200)
        self.assertEqual(self.complete_in_worker(second, code, 'recovery-two').status_code, 400)
        self.assertFalse(StaffTOTPReplayState.objects.exists())

    def test_next_native_time_step_can_use_a_fresh_code(self):
        first = self.pending()
        self.assertEqual(self.complete_in_worker(first, self.code, 'previous-step').status_code, 200)
        next_time = time.time() + 31
        next_code = format_hotp_value(hotp_value(self.secret, int(next_time) // 30))
        self.assertNotEqual(self.code, next_code)
        second = self.pending()
        with patch('allauth.mfa.totp.internal.auth.time.time', return_value=next_time):
            self.assertEqual(self.complete_in_worker(second, next_code, 'next-step').status_code, 200)
        self.assertEqual(StaffTOTPReplayState.objects.count(), 2)

    def test_claim_is_private_stable_across_key_rotation_and_not_shared_between_factors(self):
        self.assertTrue(reserve_totp_use(self.factor, self.code))
        row = StaffTOTPReplayState.objects.get()
        self.assertEqual(len(row.pk), 64)
        self.assertNotEqual(row.pk, self.secret)
        self.assertEqual(set(row.__dict__) - {'_state'}, {'key_digest', 'expires_at'})
        with override_settings(SECRET_KEY='synthetic-rotated-django-key', STAFF_MFA_ENCRYPTION_KEYS=[SECOND_KEY, TEST_KEY]):
            self.assertFalse(reserve_totp_use(self.factor, self.code))
        other = get_user_model().objects.create_user('other_replay_staff')
        other_factor = TOTP.activate(other, self.secret).instance
        self.assertTrue(reserve_totp_use(other_factor, self.code))

    @override_settings(MFA_TOTP_PERIOD=60, MFA_TOTP_TOLERANCE=2)
    def test_expiry_covers_tolerance_and_only_an_expired_claim_can_be_renewed(self):
        now = timezone.now()
        with patch('staff_auth.replay.timezone.now', return_value=now):
            self.assertTrue(reserve_totp_use(self.factor, self.code))
        row = StaffTOTPReplayState.objects.get()
        self.assertEqual(row.expires_at, now + timedelta(seconds=300))
        with patch('staff_auth.replay.timezone.now', return_value=row.expires_at - timedelta(microseconds=1)):
            self.assertFalse(reserve_totp_use(self.factor, self.code))
        with patch('staff_auth.replay.timezone.now', return_value=row.expires_at):
            self.assertTrue(reserve_totp_use(self.factor, self.code))
            self.assertFalse(reserve_totp_use(self.factor, self.code))
        self.assertEqual(StaffTOTPReplayState.objects.count(), 1)


class ReplayExpiryMaintenanceTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.expired = StaffTOTPReplayState.objects.create(key_digest='a' * 64, expires_at=now - timedelta(seconds=1))
        self.live = StaffTOTPReplayState.objects.create(key_digest='b' * 64, expires_at=now + timedelta(minutes=1))

    def test_cleanup_previews_by_default_and_apply_preserves_live_claims(self):
        output = StringIO()
        call_command('purge_staff_totp_replays', stdout=output)
        self.assertIn('Preview: 1', output.getvalue())
        self.assertEqual(StaffTOTPReplayState.objects.count(), 2)
        call_command('purge_staff_totp_replays', apply=True, stdout=StringIO())
        self.assertEqual(list(StaffTOTPReplayState.objects.values_list('pk', flat=True)), [self.live.pk])

    def test_cleanup_is_bounded_and_rejects_unbounded_batch_sizes(self):
        StaffTOTPReplayState.objects.create(key_digest='c' * 64, expires_at=self.expired.expires_at)
        call_command('purge_staff_totp_replays', apply=True, batch_size=1, stdout=StringIO())
        self.assertEqual(StaffTOTPReplayState.objects.count(), 2)
        for size in (0, -1, 10001):
            with self.assertRaises(CommandError):
                call_command('purge_staff_totp_replays', apply=True, batch_size=size, stdout=StringIO())

    def test_expired_selection_renewed_before_delete_survives(self):
        from django.db.models.query import QuerySet
        original = QuerySet.delete

        def renewed_delete(queryset):
            StaffTOTPReplayState.objects.filter(pk=self.expired.pk).update(expires_at=self.live.expires_at)
            return original(queryset)

        with patch.object(QuerySet, 'delete', renewed_delete):
            call_command('purge_staff_totp_replays', apply=True, stdout=StringIO())
        self.assertEqual(StaffTOTPReplayState.objects.count(), 2)


@skipUnless(connection.vendor == 'postgresql', 'Requires actual PostgreSQL unique-key and conditional-update races.')
@override_settings(STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY])
class BrowserReplayConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('pg_replay_staff')
        self.factor = TOTP.activate(self.user, generate_totp_secret()).instance

    def race(self):
        barrier = Barrier(2)

        def reserve(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return reserve_totp_use(self.factor, '123456')
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(reserve, range(2)))

    def test_parallel_first_reservation_admits_one_worker(self):
        self.assertEqual(sorted(self.race()), [False, True])
        self.assertEqual(StaffTOTPReplayState.objects.count(), 1)

    def test_parallel_expired_claim_renewal_admits_one_worker(self):
        reserve_totp_use(self.factor, '123456')
        StaffTOTPReplayState.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(sorted(self.race()), [False, True])
        self.assertEqual(StaffTOTPReplayState.objects.count(), 1)
