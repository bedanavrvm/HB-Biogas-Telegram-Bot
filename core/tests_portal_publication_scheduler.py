"""Portal publication pacing and scheduled-drainer contracts; no Google calls."""

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import IntegrationOperation, JawabuFarmerMaster
from core.services.external_resilience import execute_operation, reserve_operation, retry_after_seconds
from core.services.portal_publication import MASTER_OPERATION, SOURCE_MODEL, attempt_publication


class QuotaRetryTests(TestCase):
    def test_429_waits_at_least_one_minute(self):
        error = type('QuotaError', (RuntimeError,), {'status_code': 429})('quota')
        self.assertGreaterEqual(retry_after_seconds(error, attempt=1, random_value=lambda: 0), 60)

    @override_settings(PORTAL_PUBLICATION_MIN_SPACING_SECONDS=10)
    def test_publication_operations_are_paced_without_consuming_attempts(self):
        def operation(key):
            return reserve_operation(
                integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
                operation_type=MASTER_OPERATION,
                deduplication_key=key,
                max_attempts=4,
            )[0]

        first, second = operation('pace-one'), operation('pace-two')
        kwargs = {'attempt_budget': 1, 'min_spacing_seconds': 10,
                  'paced_operation_types': (MASTER_OPERATION,)}
        self.assertEqual(execute_operation(first, lambda: {'action': 'first'}, **kwargs), {'action': 'first'})
        action = []
        self.assertIsNone(execute_operation(second, lambda: action.append(True), **kwargs))
        second.refresh_from_db()
        self.assertEqual(action, [])
        self.assertEqual(second.attempts, 0)
        self.assertGreater(second.next_retry_at, timezone.now())


class DrainPortalPublicationsTests(TestCase):
    def setUp(self):
        self.farmer = JawabuFarmerMaster.objects.create(customer_name='Synthetic Scheduler Case')
        self.operation = reserve_operation(
            integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
            operation_type=MASTER_OPERATION,
            deduplication_key='scheduler-case',
            source_model=SOURCE_MODEL,
            source_id=str(self.farmer.pk),
            metadata={'workflow_revision': self.farmer.workflow_revision},
            max_attempts=4,
        )[0]

    @patch('core.management.commands.drain_portal_publications.attempt_publication')
    def test_dry_run_never_calls_google(self, attempt):
        output = StringIO()
        call_command('drain_portal_publications', stdout=output)
        self.assertIn('DRY RUN: 1 due', output.getvalue())
        attempt.assert_not_called()

    @patch('core.management.commands.drain_portal_publications.attempt_publication')
    def test_apply_only_uses_due_operations(self, attempt):
        self.operation.next_retry_at = timezone.now() + timedelta(minutes=2)
        self.operation.save(update_fields=['next_retry_at', 'updated_at'])
        call_command('drain_portal_publications', '--apply', stdout=StringIO())
        attempt.assert_not_called()

    @patch('core.management.commands.drain_portal_publications.attempt_publication')
    def test_apply_drains_and_reports_attempt(self, attempt):
        def complete(operation):
            operation.status = IntegrationOperation.STATUS_SUCCEEDED
            operation.attempts += 1
            operation.save(update_fields=['status', 'attempts', 'updated_at'])
            return {'operation': operation, 'error': False}

        attempt.side_effect = complete
        output = StringIO()
        call_command('drain_portal_publications', '--apply', stdout=output)
        self.assertEqual(attempt.call_count, 1)
        self.assertIn('1 Google attempt(s), 1 synchronized', output.getvalue())

    @patch('core.management.commands.drain_portal_publications.attempt_publication')
    def test_open_circuit_does_not_spin_or_consume_attempt(self, attempt):
        attempt.return_value = {'operation': self.operation, 'error': True}
        output = StringIO()
        call_command('drain_portal_publications', '--apply', '--max-seconds', '1', stdout=output)
        self.assertEqual(attempt.call_count, 1)
        self.assertIn('0 Google attempt(s)', output.getvalue())

    def test_missing_case_is_dead_lettered_without_google_call(self):
        self.farmer.delete()
        output = StringIO()
        call_command('drain_portal_publications', '--apply', stdout=output)
        self.operation.refresh_from_db()
        self.assertEqual(self.operation.status, IntegrationOperation.STATUS_DEAD_LETTER)
        self.assertEqual(self.operation.last_error_code, 'source_missing')

    @patch('core.services.jawabu_pipeline.sync_farmer_to_master_sheet')
    def test_master_429_uses_quota_backoff(self, publisher):
        def quota_failure(_farmer, *, failure_context):
            failure_context['provider_status'] = 429
            return False

        publisher.side_effect = quota_failure
        attempt_publication(self.operation)
        self.operation.refresh_from_db()
        self.assertEqual(self.operation.status, IntegrationOperation.STATUS_RETRYABLE)
        self.assertEqual(self.operation.last_error_code, 'http_429')
        self.assertGreaterEqual((self.operation.next_retry_at - timezone.now()).total_seconds(), 58)
