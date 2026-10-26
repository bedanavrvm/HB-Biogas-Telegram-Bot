"""Trusted attribution, isolation and log redaction without workflow writes."""
from uuid import UUID
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import Resolver404, resolve

from core.services.channel_context import ChannelRequestMiddleware, audit_context, bind_verified_channel
from staff_auth.checks import staff_browser_checks


class ChannelContextTests(SimpleTestCase):
    @override_settings(ROOT_URLCONF='config.urls', STAFF_BROWSER_AUTH_ENABLED=False, STAFF_BROWSER_COMPLAINTS_ENABLED=False)
    def test_production_routes_remain_unmounted(self):
        for url in ('/staff/app/complaints/', '/api/staff/auth/v1/session/',
                    '/api/staff/complaints/operations/v1/groups/1/bootstrap/'):
            with self.assertRaises(Resolver404):
                resolve(url)

    def request(self, view, **headers):
        request = RequestFactory().get('/api/staff/complaints/operations/v1/?q=PRIVATE_CUSTOMER', **headers)
        return ChannelRequestMiddleware(view)(request)

    def test_client_cannot_claim_verified_channel(self):
        def view(request):
            self.assertEqual(audit_context()['attempted_channel'], 'browser')
            self.assertEqual(audit_context()['channel'], 'unknown')
            return HttpResponse(status=403)
        response = self.request(view, HTTP_X_REQUEST_CHANNEL='telegram', HTTP_X_CORRELATION_ID='PRIVATE_ID',
                                HTTP_X_CLIENT_BUILD='PRIVATE CUSTOMER')
        UUID(response['X-Correlation-ID'])
        self.assertEqual(response['X-Request-Channel'], 'unknown')
        self.assertEqual(audit_context(), {})

    def test_successful_authentication_binds_and_logs_only_safe_context(self):
        def view(request):
            bind_verified_channel('browser', 'company_mfa_session')
            self.assertEqual(audit_context()['authentication'], 'company_mfa_session')
            return HttpResponse()
        with self.assertLogs('core.channel_requests', level='INFO') as records:
            response = self.request(view, HTTP_X_CLIENT_BUILD='PRIVATE_CUSTOMER_SECRET')
        self.assertEqual(response['X-Request-Channel'], 'browser')
        self.assertNotIn('PRIVATE_CUSTOMER', str(records.output))
        self.assertNotIn('operations/v1', str(records.output))
        self.assertEqual(audit_context(), {})

    def test_exception_does_not_leak_context_into_following_request(self):
        def broken(request):
            bind_verified_channel('browser', 'company_mfa_session')
            raise RuntimeError('synthetic failure')
        with self.assertRaises(RuntimeError):
            self.request(broken)
        self.assertEqual(audit_context(), {})
        self.assertEqual(self.request(lambda request: HttpResponse())['X-Request-Channel'], 'unknown')

    def test_parallel_requests_keep_independent_verified_context(self):
        barrier = Barrier(2)
        def execute(channel):
            def view(request):
                bind_verified_channel(channel, 'synthetic-verified-auth')
                barrier.wait(timeout=5)
                self.assertEqual(audit_context()['channel'], channel)
                return HttpResponse()
            request = RequestFactory().get('/api/staff/complaints/' if channel == 'browser' else '/api/tat-tracker/')
            response = ChannelRequestMiddleware(view)(request)
            self.assertEqual(audit_context(), {})
            return response['X-Request-Channel']
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(set(pool.map(execute, ['browser', 'telegram'])), {'browser', 'telegram'})

    def test_telegram_auth_still_requires_a_valid_signature_and_is_not_disabled_by_browser_switch(self):
        from core.services.telegram_identity import TelegramAuthenticationError, validate_telegram_init_data
        token = 'synthetic-test-token'
        fields = {'auth_date': str(int(time.time())), 'user': json.dumps({'id': '999000001'})}
        secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
        digest = hmac.new(secret, '\n'.join(f'{key}={value}' for key, value in sorted(fields.items())).encode(), hashlib.sha256).hexdigest()
        def view(request):
            with self.assertRaises(TelegramAuthenticationError):
                validate_telegram_init_data(urlencode({**fields, 'hash': 'invalid'}), bot_token=token)
            self.assertEqual(audit_context()['channel'], 'unknown')
            validate_telegram_init_data(urlencode({**fields, 'hash': digest}), bot_token=token)
            return HttpResponse()
        with self.settings(STAFF_BROWSER_AUTH_ENABLED=False, STAFF_BROWSER_COMPLAINTS_ENABLED=False):
            request = RequestFactory().post('/api/tat-tracker/tasks/')
            response = ChannelRequestMiddleware(view)(request)
        self.assertEqual(response['X-Request-Channel'], 'telegram')

    @override_settings(STAFF_BROWSER_AUTH_ENABLED=False, STAFF_BROWSER_DEMO_ENABLED=True, RELEASE_ENVIRONMENT='production')
    def test_demo_flag_is_rejected_in_production_even_when_browser_off(self):
        self.assertEqual([error.id for error in staff_browser_checks(None)], ['staff_auth.E009'])
