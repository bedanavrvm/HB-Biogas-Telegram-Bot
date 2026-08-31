"""Phase 6 canonical routing, configuration, and focused abuse controls."""

from pathlib import Path

from django.conf import settings
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.models import PublicEndpointThrottleBucket
from core.services.request_throttling import consume_ip
from core.services.telegram_launchers import _pipeline_portal_url


class CanonicalRouteSurfaceTests(TestCase):
    def test_browser_names_reverse_only_to_intentional_root_routes(self):
        self.assertEqual(reverse('staff_telegram_activation_page'), '/staff/activate/')
        self.assertEqual(reverse('spin_form'), '/spin/')
        self.assertEqual(reverse('tat_tracker_app'), '/tat-tracker/')
        self.assertEqual(reverse('complaint_cases_app'), '/complaints/')
        self.assertEqual(reverse('portal_home'), '/portal/')
        self.assertEqual(reverse('loan_origination_signing_short_app'), '/s/')

    def test_api_names_reverse_to_canonical_api_prefix(self):
        self.assertEqual(reverse('telegram_session_login'), '/api/auth/telegram/')
        self.assertEqual(reverse('spin_form_submit'), '/api/spin/submit/')
        self.assertEqual(
            reverse('loan_origination_signer_session'),
            '/api/origination/sign/api/session/',
        )
        self.assertEqual(reverse('telegram_webhook'), '/api/webhook/telegram/')

    def test_historical_api_browser_route_is_get_only_redirect(self):
        with self.assertLogs('core.legacy_routes', level='WARNING') as captured:
            response = self.client.get('/api/spin/?tgWebAppStartParam=private-value')
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response['Location'], '/spin/?tgWebAppStartParam=private-value')
        self.assertNotIn('private-value', '\n'.join(captured.output))
        self.assertEqual(self.client.post('/api/spin/').status_code, 405)

    def test_blanket_root_api_alias_is_removed(self):
        self.assertEqual(self.client.post('/spin/submit/').status_code, 404)

    def test_credential_route_legacy_alias_calls_directly_and_logs_safely(self):
        with self.assertLogs('core.legacy_routes', level='WARNING') as captured:
            response = self.client.get(
                '/origination/sign/api/session/?token=do-not-log',
                HTTP_AUTHORIZATION='Bearer do-not-log-either',
            )
        self.assertNotIn(response.status_code, {301, 302, 307, 308})
        logs = '\n'.join(captured.output)
        self.assertNotIn('do-not-log', logs)
        self.assertIn('/api/origination/sign/api/session/', logs)

    @override_settings(
        TELEGRAM_BOT_USERNAME='', PORTAL_MINI_APP_SHORT_NAME='',
        APP_BASE_URL='https://workflow.example',
    )
    def test_portal_launcher_targets_root_browser_entry(self):
        self.assertEqual(_pipeline_portal_url(), 'https://workflow.example/portal/')


@override_settings(
    PUBLIC_RATE_LIMIT_WINDOW_SECONDS=600,
    REQUIRE_MINIAPP_IDEMPOTENCY_KEY=False,
    SECURE_SSL_REDIRECT=False,
)
class FocusedRateLimitingTests(TestCase):
    request_headers = {
        'HTTP_IDEMPOTENCY_KEY': 'phase6-key-0001',
        'HTTP_X_REQUEST_ID': 'phase6-key-0001',
    }

    @override_settings(STAFF_ACTIVATION_RATE_LIMIT=1)
    def test_staff_activation_attempts_are_limited(self):
        first = self.client.post(
            '/api/staff/activate/submit/', data='{}',
            content_type='application/json', **self.request_headers,
        )
        second = self.client.post(
            '/api/staff/activate/submit/', data='{}',
            content_type='application/json', **self.request_headers,
        )
        self.assertEqual(first.status_code, 403)
        self.assertEqual(second.status_code, 429)
        self.assertIn('Retry-After', second)

    @override_settings(TELEGRAM_SESSION_LOGIN_RATE_LIMIT=1)
    def test_telegram_login_attempts_are_limited(self):
        first = self.client.post('/api/auth/telegram/', **self.request_headers)
        second = self.client.post('/api/auth/telegram/', **self.request_headers)
        self.assertEqual(first.status_code, 403)
        self.assertEqual(second.status_code, 429)

    @override_settings(SIGNING_TOKEN_RATE_LIMIT=1)
    def test_signing_link_attempts_are_limited_by_token_and_network(self):
        first = self.client.get(
            '/api/origination/sign/api/session/',
            HTTP_AUTHORIZATION='Bearer invalid-phase6-token',
        )
        second = self.client.get(
            '/api/origination/sign/api/session/',
            HTTP_AUTHORIZATION='Bearer invalid-phase6-token',
        )
        self.assertNotEqual(first.status_code, 429)
        self.assertEqual(second.status_code, 429)

    @override_settings(MINIAPP_DIAGNOSTICS_RATE_LIMIT=1)
    def test_diagnostic_ingestion_attempts_are_limited(self):
        first = self.client.post(
            '/api/miniapp-diagnostics/sessions/start/', data='{}',
            content_type='application/json', **self.request_headers,
        )
        second = self.client.post(
            '/api/miniapp-diagnostics/sessions/start/', data='{}',
            content_type='application/json', **self.request_headers,
        )
        self.assertEqual(first.status_code, 400)
        self.assertEqual(second.status_code, 429)

    @override_settings(API_AUTH_TOKEN='valid-manual-token', MANUAL_API_AUTH_FAILURE_RATE_LIMIT=1)
    def test_only_failed_manual_credentials_consume_failure_limit(self):
        first = self.client.get('/api/readiness/', HTTP_AUTHORIZATION='Bearer wrong')
        second = self.client.get('/api/readiness/', HTTP_AUTHORIZATION='Bearer wrong')
        self.assertEqual(first.status_code, 403)
        self.assertEqual(second.status_code, 429)

    @override_settings(TELEGRAM_WEBHOOK_SECRET='webhook-secret', STAFF_ACTIVATION_RATE_LIMIT=1)
    def test_telegram_webhook_retries_are_not_rate_limited(self):
        for _ in range(3):
            response = self.client.post(
                '/api/webhook/telegram/', data='{"update_id": 1}',
                content_type='application/json',
                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='webhook-secret',
            )
            self.assertNotEqual(response.status_code, 429)

    def test_persisted_throttle_key_cannot_reveal_network_address(self):
        request = RequestFactory().get('/', REMOTE_ADDR='203.0.113.55')
        decision = consume_ip(request, scope='phase6-test', limit=2)
        self.assertTrue(decision.allowed)
        bucket = PublicEndpointThrottleBucket.objects.get(scope='phase6-test')
        self.assertEqual(len(bucket.key_hash), 64)
        self.assertNotIn('203.0.113.55', bucket.key_hash)


class ReconciledConfigurationTests(TestCase):
    def test_order_approval_limit_is_reviewed_30_mb_value(self):
        self.assertEqual(settings.ORDER_APPROVAL_MAX_TOTAL_UPLOAD_MB, 30)
        env_text = (Path(settings.BASE_DIR) / '.env.example').read_text(encoding='utf-8')
        self.assertIn('ORDER_APPROVAL_MAX_TOTAL_UPLOAD_MB=30', env_text)
        self.assertNotIn('RATELIMIT_ENABLE=', env_text)
