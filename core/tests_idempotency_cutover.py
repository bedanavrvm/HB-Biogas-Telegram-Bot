"""Executable contracts for the Mini App request-key cutover."""

from types import SimpleNamespace

from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from core.miniapp_write_inventory import WRITE_ROUTE_INVENTORY
from core.models import MiniAppLegacyWriteDailyAggregate
from core.production import (
    MINIAPP_AUTH_SETTINGS,
    TELEGRAM_AUTH_AGE_SETTINGS,
    production_security_readiness_issues,
)
from core.services.miniapp_idempotency import record_legacy_write
from core.services.miniapp_requests import (
    IdempotencyKeyRequired,
    bind_miniapp_write_request,
    miniapp_idempotency_boundary,
)


class WriteRouteInventoryTests(SimpleTestCase):
    def test_every_discovered_write_route_has_a_complete_reviewed_policy(self):
        from scripts.check_miniapp_write_inventory import inventory_errors

        self.assertEqual(inventory_errors(), [])
        self.assertGreater(len(WRITE_ROUTE_INVENTORY), 100)
        for route_name, policy in WRITE_ROUTE_INVENTORY.items():
            with self.subTest(route=route_name):
                self.assertTrue(policy.authentication)
                self.assertTrue(policy.capability)
                self.assertTrue(policy.scope)
                self.assertTrue(policy.request_key_binding)
                self.assertTrue(policy.domain_replay)


class CanonicalRequestKeyTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True)
    def test_header_key_reaches_service_payload_without_overwriting_domain_id(self):
        request = self.factory.post(
            '/write/',
            data='{}',
            content_type='application/json',
            HTTP_IDEMPOTENCY_KEY='transport-12345678',
            HTTP_X_REQUEST_ID='transport-12345678',
        )
        payload = {
            'client_request_id': 'stale-body-12345678',
            'request_id': 'SPIN-DOMAIN-0001',
        }

        identity = bind_miniapp_write_request(request, payload)

        self.assertEqual(identity.key, 'transport-12345678')
        self.assertEqual(payload['client_request_id'], 'transport-12345678')
        self.assertEqual(payload['request_id'], 'SPIN-DOMAIN-0001')

    def test_mismatched_transport_headers_are_rejected(self):
        request = self.factory.post(
            '/write/',
            data='{}',
            content_type='application/json',
            HTTP_IDEMPOTENCY_KEY='transport-12345678',
            HTTP_X_REQUEST_ID='transport-87654321',
        )

        with self.assertRaisesRegex(ValueError, 'do not match'):
            bind_miniapp_write_request(request, {})

    @override_settings(REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True)
    def test_domain_request_id_cannot_bypass_strict_transport_identity(self):
        request = self.factory.post(
            '/write/', data='{}', content_type='application/json',
        )

        with self.assertRaises(IdempotencyKeyRequired):
            bind_miniapp_write_request(request, {'request_id': 'SPIN-DOMAIN-0001'})


class LegacyWriteAggregateTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_diagnostic_is_anonymous_daily_aggregate(self):
        record_legacy_write(route_name='tat_tracker_create', method='POST', outcome='accepted')
        record_legacy_write(route_name='tat_tracker_create', method='POST', outcome='accepted')

        row = MiniAppLegacyWriteDailyAggregate.objects.get()
        self.assertEqual(row.date, timezone.localdate())
        self.assertEqual(row.route_name, 'tat_tracker_create')
        self.assertEqual(row.method, 'POST')
        self.assertEqual(row.outcome, 'accepted')
        self.assertEqual(row.request_count, 2)
        field_names = {field.name for field in row._meta.fields}
        self.assertFalse({'request_body', 'actor', 'user', 'path'} & field_names)

    @override_settings(REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True)
    def test_strict_missing_key_is_rejected_and_counted_without_running_view(self):
        request = self.factory.post('/write/', data='{}', content_type='application/json')
        request.resolver_match = SimpleNamespace(url_name='tat_tracker_create')
        calls = []

        @miniapp_idempotency_boundary
        def write_view(_request):
            calls.append(True)
            return JsonResponse({'ok': True})

        response = write_view(request)

        self.assertEqual(response.status_code, 428)
        self.assertEqual(response['X-Idempotency-Status'], 'strict-rejected')
        self.assertEqual(calls, [])
        row = MiniAppLegacyWriteDailyAggregate.objects.get()
        self.assertEqual((row.route_name, row.outcome, row.request_count), (
            'tat_tracker_create', 'rejected', 1,
        ))

    def test_readiness_warns_when_the_observation_window_is_not_clear(self):
        MiniAppLegacyWriteDailyAggregate.objects.create(
            date=timezone.localdate(),
            route_name='spin_form_complete',
            method='POST',
            outcome='accepted',
            request_count=3,
        )
        values = {name: True for _surface, name in MINIAPP_AUTH_SETTINGS}
        values.update({name: 86400 for _surface, name in TELEGRAM_AUTH_AGE_SETTINGS})
        values.update({
            'REQUIRE_MINIAPP_IDEMPOTENCY_KEY': True,
            'MINIAPP_IDEMPOTENCY_OBSERVATION_DAYS': 14,
            'TELEGRAM_WEBHOOK_SECRET': 'real-webhook-secret',
            'TAT_TRACKER_SIGNATURES_ENABLED': False,
            'ORIGINATION_ESIGN_ENABLED': False,
            'ORIGINATION_CONDITIONAL_APPROVAL_ENABLED': False,
            'ACCESS_GRANT_GOVERNANCE_ENFORCED': True,
        })

        issues = production_security_readiness_issues(
            SimpleNamespace(**values), check_database=True,
        )

        warning = next(
            issue for issue in issues
            if issue.code == 'miniapp-idempotency-legacy-observed'
        )
        self.assertEqual(warning.severity, 'warning')
        self.assertIn('3 legacy Mini App write attempt', warning.message)
