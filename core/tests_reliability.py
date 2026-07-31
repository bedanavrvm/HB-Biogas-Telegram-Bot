"""Focused tests for the bounded reliability release.

These tests deliberately use only the Django test database and mocked
integration calls. They must never contact Telegram, Google Sheets, or Drive.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.db import transaction
from django.core.management import call_command
from io import StringIO

from core.api.complaint_case_views import complaint_cases_create
from core.api.views import spin_form_submit, tat_tracker_create
from core.models import IntegrationCircuitState, IntegrationOperation, JawabuFarmerMaster
from core.api.portal_views import portal_publication_attempt
from core.services.external_resilience import (
    ExternalCircuitOpen,
    ExternalOperationError,
    execute_operation,
    reserve_operation,
)
from core.services.miniapp_requests import (
    IdempotencyKeyRequired,
    bind_miniapp_request_identity,
)
from core.services.portal_publication import (
    INTERNAL_ORDER_OPERATION,
    MASTER_OPERATION,
    publication_payload,
    reserve_farmer_publication,
)
from core.management.commands.probe_integrations import configuration_status


class TransientFailure(RuntimeError):
    status_code = 503


class PermanentFailure(RuntimeError):
    status_code = 400


class MiniAppRequestIdentityTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_header_key_is_bound(self):
        request = self.factory.post('/api/test/', HTTP_IDEMPOTENCY_KEY='retry-12345678')
        payload = {}

        identity = bind_miniapp_request_identity(request, payload)

        self.assertEqual(identity.key, 'retry-12345678')
        self.assertEqual(identity.source, 'idempotency_key')
        self.assertEqual(payload['client_request_id'], 'retry-12345678')

    @override_settings(REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True)
    def test_strict_mode_rejects_missing_key(self):
        request = self.factory.post('/api/test/')
        with self.assertRaises(IdempotencyKeyRequired):
            bind_miniapp_request_identity(request, {})


class MiniAppWritePolicyTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _json_request(self, path, payload, key='retry-12345678'):
        return self.factory.post(
            path,
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_IDEMPOTENCY_KEY=key,
        )

    def test_tat_update_accepts_header_retry_key(self):
        request = self._json_request('/api/tat-tracker/create/', {'group_id': 'group-1'})
        with patch('core.api.views._tat_context', return_value=('group-1', object(), {}, {'user_id': '1'}, None)), \
                patch('core.api.views._tat_capability_error', return_value=None), \
                patch('core.services.tat_tracker.create_case', return_value={'case_id': 'TAT-1'}) as create_case, \
                patch('core.api.views._send_tat_next_role_alert'):
            response = tat_tracker_create(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['X-Idempotency-Status'], 'keyed')
        self.assertEqual(create_case.call_args.args[2]['client_request_id'], 'retry-12345678')

    def test_tat_update_rejects_invalid_retry_key(self):
        request = self._json_request('/api/tat-tracker/create/', {'group_id': 'group-1'}, key='bad key')
        response = tat_tracker_create(request)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)['code'], 'invalid_idempotency_key')

    def test_complaint_and_spin_accept_legacy_clients(self):
        complaint_request = self._json_request('/api/complaints/cases/create/', {'group_id': 'group-1'}, key='')
        with patch('core.api.complaint_case_views._context', return_value=(type('Group', (), {'group_id': 'group-1'})(), type('Actor', (), {'capabilities': {'complaint.case.create'}, 'name': 'Officer'})(), None)), \
                patch('core.api.complaint_case_views._capability_error', return_value=None), \
                patch('core.api.complaint_case_views.create_complaint_case', return_value={'case': {}, 'created': True, 'synced_to_sheet': True}):
            complaint_response = complaint_cases_create(complaint_request)
        self.assertEqual(complaint_response.status_code, 201)
        self.assertEqual(complaint_response['X-Idempotency-Status'], 'legacy-client')

        spin_request = self._json_request('/api/spin/submit/', {'group_id': 'group-1', 'fields': {'client_name': 'Test'}}, key='')
        with patch('core.api.views._spin_webapp_context', return_value=('group-1', object(), {}, None)), \
                patch('core.api.views._spin_user_has_capability', return_value=True), \
                patch('core.api.views._sender_from_webapp_auth', return_value='Officer'), \
                patch('core.api.views._spin_canonical_user', return_value=None), \
                patch('core.services.spin_credit.process_spin_form_submission', return_value={'success': True, 'idempotent_replay': True}):
            spin_response = spin_form_submit(spin_request)
        self.assertEqual(spin_response.status_code, 200)
        self.assertEqual(spin_response['X-Idempotency-Status'], 'legacy-client')

    @override_settings(REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True)
    def test_strict_mode_rejects_legacy_client_for_each_workflow(self):
        tat_response = tat_tracker_create(self._json_request('/api/tat-tracker/create/', {'group_id': 'group-1'}, key=''))
        complaint_response = complaint_cases_create(self._json_request('/api/complaints/cases/create/', {'group_id': 'group-1'}, key=''))
        spin_response = spin_form_submit(self._json_request('/api/spin/submit/', {'group_id': 'group-1'}, key=''))
        self.assertEqual(tat_response.status_code, 428)
        self.assertEqual(complaint_response.status_code, 428)
        self.assertEqual(spin_response.status_code, 428)

    @override_settings(REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True, PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True)
    def test_portal_denial_does_not_attempt_strict_key_validation(self):
        response = self.client.post('/api/portal/dashboard/', data='{}', content_type='application/json')
        self.assertEqual(response.status_code, 403)


class ExternalResilienceTests(TestCase):
    def operation(self, key, *, attempts=3):
        return reserve_operation(
            integration='google_sheets',
            operation_type='test_write',
            deduplication_key=key,
            operation_payload={'test': key},
            max_attempts=attempts,
        )[0]

    def test_transient_failure_retries_then_succeeds(self):
        operation = self.operation('retry-success')
        calls = []

        def action():
            calls.append(True)
            if len(calls) == 1:
                raise TransientFailure('temporary')
            return {'id': 'safe-result'}

        result = execute_operation(operation, action, sleeper=lambda _: None, random_value=lambda: 0)
        operation.refresh_from_db()
        self.assertEqual(len(calls), 2)
        self.assertEqual(result, {'id': 'safe-result'})
        self.assertEqual(operation.status, IntegrationOperation.STATUS_SUCCEEDED)
        self.assertEqual(operation.attempts, 2)

    def test_terminal_failure_is_dead_lettered(self):
        operation = self.operation('terminal-failure', attempts=2)
        with self.assertRaises(ExternalOperationError):
            execute_operation(operation, lambda: (_ for _ in ()).throw(PermanentFailure('invalid')), sleeper=lambda _: None)
        operation.refresh_from_db()
        self.assertEqual(operation.status, IntegrationOperation.STATUS_DEAD_LETTER)
        self.assertEqual(operation.attempts, 1)

    def test_non_transient_error_is_not_retried(self):
        operation = self.operation('non-transient', attempts=3)
        calls = []
        with self.assertRaises(ExternalOperationError):
            execute_operation(operation, lambda: (calls.append(True), (_ for _ in ()).throw(PermanentFailure('invalid')))[1], sleeper=lambda _: None)
        self.assertEqual(len(calls), 1)

    def test_attempt_budget_persists_retry_without_sleeping_in_the_web_request(self):
        operation = self.operation('one-attempt-publication', attempts=3)
        calls = []

        def action():
            calls.append(True)
            raise TransientFailure('temporary')

        with self.assertRaises(ExternalOperationError):
            execute_operation(
                operation,
                action,
                sleeper=lambda _: self.fail('A one-attempt web follow-up must not sleep/retry.'),
                attempt_budget=1,
            )
        operation.refresh_from_db()
        self.assertEqual(calls, [True])
        self.assertEqual(operation.attempts, 1)
        self.assertEqual(operation.status, IntegrationOperation.STATUS_RETRYABLE)
        self.assertIsNotNone(operation.next_retry_at)

    def test_circuit_opens_and_blocks_calls(self):
        for index in range(5):
            operation = self.operation(f'circuit-{index}', attempts=1)
            with self.assertRaises(ExternalOperationError):
                execute_operation(operation, lambda: (_ for _ in ()).throw(TransientFailure('temporary')), sleeper=lambda _: None)
        circuit = IntegrationCircuitState.objects.get(integration='google_sheets')
        self.assertEqual(circuit.status, IntegrationCircuitState.STATUS_OPEN)

        blocked = self.operation('circuit-blocked', attempts=1)
        with self.assertRaises(ExternalCircuitOpen):
            execute_operation(blocked, lambda: {'id': 'must-not-run'}, sleeper=lambda _: None)
        blocked.refresh_from_db()
        self.assertEqual(blocked.attempts, 0)

    def test_transaction_rollback_leaves_no_orphan_operation(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.operation('rolled-back-operation')
                raise RuntimeError('rollback local workflow write')
        self.assertFalse(IntegrationOperation.objects.filter(deduplication_key='rolled-back-operation').exists())


class PortalPublicationReservationTests(TestCase):
    @patch('core.services.portal_publication._targets_for_farmer', return_value=[MASTER_OPERATION, INTERNAL_ORDER_OPERATION])
    def test_same_case_revision_reserves_one_durable_operation_per_register(self, _targets):
        farmer = SimpleNamespace(pk='case-opaque-1', workflow_revision=7)

        first = reserve_farmer_publication(farmer, request_id='portal-publication-test-001')
        second = reserve_farmer_publication(farmer, request_id='portal-publication-test-001')

        self.assertEqual(len(first), 2)
        self.assertEqual({row.pk for row in first}, {row.pk for row in second})
        self.assertEqual(IntegrationOperation.objects.count(), 2)
        payload = publication_payload(farmer)
        self.assertEqual(payload['status'], 'pending')
        self.assertEqual(len(payload['pending_operation_ids']), 2)


class PortalPublicationEndpointTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.farmer = JawabuFarmerMaster.objects.create(customer_name='Publication Test Case')
        self.operation = reserve_operation(
            integration='google_sheets',
            operation_type=MASTER_OPERATION,
            deduplication_key=f'endpoint-publication:{self.farmer.pk}',
            source_model='JawabuFarmerMaster',
            source_id=str(self.farmer.pk),
            operation_payload={'case': str(self.farmer.pk)},
            metadata={'workflow_revision': self.farmer.workflow_revision},
        )[0]

    def _request(self):
        request = self.factory.post(
            '/api/portal/publication/attempt/',
            data=json.dumps({'operation_id': str(self.operation.pk), 'automatic': True}),
            content_type='application/json',
        )
        request.portal_access = {}
        request.portal_user = None
        return request

    @patch('core.api.portal_views._portal_farmers_scope_error')
    @patch('core.services.portal_publication.attempt_publication')
    def test_publication_attempt_denies_out_of_scope_case_before_google_call(self, mocked_attempt, mocked_scope):
        from django.http import JsonResponse

        mocked_scope.return_value = JsonResponse({'ok': False, 'error': 'Forbidden.'}, status=403)
        response = portal_publication_attempt(self._request())

        self.assertEqual(response.status_code, 403)
        mocked_attempt.assert_not_called()

    @patch('core.services.portal_publication.attempt_publication')
    @patch('core.services.portal_publication.publication_payload', return_value={'status': 'synced', 'pending_operation_ids': []})
    @patch('core.api.portal_views._portal_farmers_scope_error', return_value=None)
    def test_publication_attempt_runs_one_authorized_operation(self, _scope, _payload, mocked_attempt):
        mocked_attempt.return_value = {'superseded': False}

        response = portal_publication_attempt(self._request())

        self.assertEqual(response.status_code, 202)
        mocked_attempt.assert_called_once()


class ReadinessTests(TestCase):
    @override_settings(GOOGLE_SHEET_ID='')
    @patch('core.management.commands.probe_integrations._configured_sheet_target', return_value=('', ''))
    def test_sheet_probe_reports_missing_configuration_when_no_sheet_is_available(self, _configured_sheet_target):
        configured, detail = configuration_status('google_sheets')

        self.assertFalse(configured)
        self.assertIn('missing', detail)

    def test_readiness_requires_manual_api_token(self):
        response = self.client.get(reverse('readiness_check'))
        self.assertEqual(response.status_code, 403)

    @override_settings(API_AUTH_TOKEN='manual-test-token')
    @patch('requests.get')
    def test_authorized_readiness_uses_no_outbound_call(self, mocked_get):
        response = self.client.get(reverse('readiness_check'), HTTP_X_API_AUTH_TOKEN='manual-test-token')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(json.loads(response.content)['data']['outbound_probes_performed'])
        mocked_get.assert_not_called()

    @patch('core.management.commands.probe_integrations.run_probe')
    @override_settings(GOOGLE_SHEET_ID='test-sheet', GOOGLE_DRIVE_MEDIA_FOLDER_ID='test-folder', TELEGRAM_BOT_TOKEN='test-token')
    def test_probe_command_is_configuration_only_without_execute(self, mocked_probe):
        output = StringIO()
        call_command('probe_integrations', stdout=output)
        mocked_probe.assert_not_called()
        self.assertIn('external call skipped', output.getvalue())
