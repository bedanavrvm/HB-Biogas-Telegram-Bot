"""Portal publication pacing and scheduled-drainer contracts; no Google calls."""

from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from unittest.mock import MagicMock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import DurableJobRunnerHeartbeat, IntegrationOperation, JawabuFarmerMaster
from core.services.external_resilience import execute_operation, reserve_operation, retry_after_seconds
from core.services.portal_publication import (
    MASTER_OPERATION, PORTAL_PUBLICATION_RUNNER, SOURCE_MODEL,
    attempt_publication, publication_scheduler_health,
)
from core.management.commands.drain_portal_publications import due_portal_operations
from core.services.jawabu_master import ensure_master_system_headers


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
        self.assertTrue(publication_scheduler_health()['healthy'])

    @patch('core.management.commands.drain_portal_publications.attempt_publication')
    def test_scheduler_outage_warning_clears_after_recovery(self, attempt):
        self.assertFalse(publication_scheduler_health()['healthy'])
        self.assertEqual(publication_scheduler_health()['queued'], 1)
        heartbeat = DurableJobRunnerHeartbeat.objects.create(runner_key=PORTAL_PUBLICATION_RUNNER)
        DurableJobRunnerHeartbeat.objects.filter(pk=heartbeat.pk).update(
            heartbeat_at=timezone.now() - timedelta(minutes=4),
        )
        self.assertFalse(publication_scheduler_health()['healthy'])

        def complete(operation):
            operation.status = IntegrationOperation.STATUS_SUCCEEDED
            operation.attempts += 1
            operation.save(update_fields=['status', 'attempts', 'updated_at'])
            return {'operation': operation, 'error': False}

        attempt.side_effect = complete
        call_command('drain_portal_publications', '--apply', stdout=StringIO())
        self.assertTrue(publication_scheduler_health()['healthy'])
        self.assertEqual(publication_scheduler_health()['queued'], 0)

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

    def test_stale_running_master_operation_can_be_reclaimed(self):
        self.operation.status = IntegrationOperation.STATUS_RUNNING
        self.operation.last_attempt_at = timezone.now() - timedelta(minutes=2)
        self.operation.save(update_fields=['status', 'last_attempt_at', 'updated_at'])
        self.assertIn(self.operation.pk, list(due_portal_operations().values_list('pk', flat=True)))

    @patch('core.services.jawabu_pipeline.sync_farmer_to_master_sheet')
    def test_later_case_waits_for_earlier_master_publication(self, publisher):
        later_farmer = JawabuFarmerMaster.objects.create(customer_name='Synthetic Later Case')
        later = reserve_operation(
            integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
            operation_type=MASTER_OPERATION, deduplication_key='later-case',
            source_model=SOURCE_MODEL, source_id=str(later_farmer.pk),
            metadata={'workflow_revision': later_farmer.workflow_revision},
        )[0]
        self.operation.next_retry_at = timezone.now() + timedelta(minutes=2)
        self.operation.status = IntegrationOperation.STATUS_RETRYABLE
        self.operation.save(update_fields=['status', 'next_retry_at', 'updated_at'])
        self.assertNotIn(later.pk, list(due_portal_operations().values_list('pk', flat=True)))
        self.assertTrue(attempt_publication(later).get('deferred'))
        publisher.assert_not_called()


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

    @patch('core.services.jawabu_pipeline.sync_farmer_to_master_sheet')
    def test_identity_conflict_is_terminal_and_not_a_network_retry(self, publisher):
        def identity_failure(_farmer, *, failure_context):
            failure_context.update({'phase': 'identity', 'sheet_tab': 'Master Data',
                                    'detail': 'Identity review is required.'})
            return False

        publisher.side_effect = identity_failure
        attempt_publication(self.operation)
        self.operation.refresh_from_db()
        self.assertEqual(self.operation.status, IntegrationOperation.STATUS_DEAD_LETTER)
        self.assertEqual(self.operation.last_error_code, 'identity_conflict')
        self.assertEqual(self.operation.attempts, 1)
        self.assertIsNone(self.operation.next_retry_at)
        from core.services.portal_publication import publication_payload
        self.assertEqual(publication_payload(self.farmer)['operations'][0]['issue'], 'identity_review')


class MasterSheetLayoutTests(TestCase):
    def test_row_one_headers_never_write_descriptions_into_first_case_row(self):
        sheet = MagicMock()
        sheet.col_count = 100
        sheet.row_values.return_value = ['No.', 'Case ID', 'Customer Name']
        with patch('core.services.jawabu_master.update_sheet_cells') as update_cells:
            ensure_master_system_headers(sheet, 1)
        all_cells = update_cells.call_args.args[1]
        self.assertTrue(all(row == 1 for row, _col, _value in all_cells))
        self.assertFalse(any(call.args and call.args[0] == 2 for call in sheet.update_cell.call_args_list))
