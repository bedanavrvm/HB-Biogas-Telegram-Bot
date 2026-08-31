from datetime import timedelta
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import (
    ComplaintCaseImportBatch,
    ComplaintCaseImportItem,
    DurableJobRunnerHeartbeat,
    GroupSheetConfiguration,
    IntegrationOperation,
    ParsedMessage,
    ProcessedMessage,
    RawMessage,
    TatRepairJob,
    TatTrackerCase,
)
from core.services.complaint_imports import (
    cancel_complaint_import_batch,
    claim_complaint_import_batch,
    deliver_complaint_import_notifications,
    process_complaint_import_batch_chunk,
    reserve_complaint_import_batch,
    retry_complaint_import_batch,
)
from core.production import (
    MINIAPP_AUTH_SETTINGS,
    TELEGRAM_AUTH_AGE_SETTINGS,
    production_security_readiness_issues,
)
from core.services.durable_jobs import durable_job_health, finish_runner
from core.services.tat_repair_jobs import (
    cancel_repair_job,
    claim_repair_job,
    create_repair_job,
    run_repair_job,
)


def import_entries(count):
    return [
        {
            'sender': f'Officer {index}',
            'content': f'Routine operational note {index}',
            'received_at': timezone.now(),
            'raw_header': f'header {index}',
        }
        for index in range(count)
    ]


class DurableComplaintImportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='durable-import-admin', password='test-password',
        )

    def reserve(self, count=3, message_id='durable-import-1'):
        entries = import_entries(count)
        reservation = reserve_complaint_import_batch(
            actor=self.user, group_id='-100-durable-import',
            source_telegram_message_id=message_id,
            telegram_user_id='9001', source_hash=('a' * 64),
            source_count=len(entries), entries=entries,
            analysis_snapshot={'format': 'android', 'system_lines': 0},
        )
        return reservation.batch

    def test_reservation_is_atomic_hash_bound_and_duplicate_safe(self):
        batch = self.reserve(count=4)
        snapshots = list(
            batch.items.order_by('source_index').values_list('normalized_entry_snapshot', flat=True)
        )
        replay = reserve_complaint_import_batch(
            actor=self.user, group_id=batch.group_id,
            source_telegram_message_id=batch.source_telegram_message_id,
            telegram_user_id='9001', source_hash='a' * 64, source_count=4,
            entries=snapshots,
        )

        self.assertFalse(replay.created)
        self.assertEqual(batch.items.count(), 4)
        self.assertTrue(all(len(item.content_hash) == 64 for item in batch.items.all()))

        snapshots[0]['content'] = 'Materially different replay'
        with self.assertRaisesMessage(ValueError, 'source position changed'):
            reserve_complaint_import_batch(
                actor=self.user, group_id=batch.group_id,
                source_telegram_message_id=batch.source_telegram_message_id,
                telegram_user_id='9001', source_hash='a' * 64, source_count=4,
                entries=snapshots,
            )

    def test_bounded_chunks_resume_without_loss_or_duplicate_processing(self):
        batch = self.reserve(count=5)
        claimed, token = claim_complaint_import_batch()
        first = process_complaint_import_batch_chunk(claimed.pk, lease_token=token, item_limit=2)

        self.assertEqual(first['processed_items'], 2)
        batch.refresh_from_db()
        self.assertEqual(batch.status, ComplaintCaseImportBatch.STATUS_QUEUED)
        self.assertEqual(batch.items.filter(status=ComplaintCaseImportItem.STATUS_SKIPPED).count(), 2)

        claimed, token = claim_complaint_import_batch()
        second = process_complaint_import_batch_chunk(claimed.pk, lease_token=token, item_limit=10)
        batch.refresh_from_db()
        self.assertEqual(second['processed_items'], 3)
        self.assertEqual(batch.status, ComplaintCaseImportBatch.STATUS_COMPLETED)
        self.assertEqual(batch.items.count(), 5)
        self.assertEqual(batch.items.filter(status=ComplaintCaseImportItem.STATUS_SKIPPED).count(), 5)
        self.assertEqual(IntegrationOperation.objects.filter(
            operation_type='complaint_import_completion', source_id=str(batch.pk),
        ).count(), 1)

    @patch('core.api.views._batch_append_case_results', return_value={'status': 'success'})
    @patch('core.api.views._process_single_message')
    @patch('core.services.parser.detect_message_intent')
    def test_created_case_is_checkpointed_once(self, detect_intent, process_message, _append):
        from core.services.parser import MessageIntent

        raw = RawMessage.objects.create(
            telegram_message_id='durable-created-case', sender='Officer',
            content='CUSTOMER COMPLAINT: no gas',
        )
        processed = ProcessedMessage.objects.create(
            message_hash='d' * 64, raw_message=raw,
        )
        case = ParsedMessage.objects.create(
            processed_message=processed, message_id='CMP-DURABLE-1',
            raw_message=raw.content, complaint_description='No gas',
            group_id='-100-durable-import',
        )
        detect_intent.return_value = MessageIntent.COMPLAINT
        process_message.return_value = {
            'status': 'success', 'parsed_message_id': case.pk,
        }
        batch = self.reserve(count=1, message_id='durable-created-source')

        claimed, token = claim_complaint_import_batch()
        process_complaint_import_batch_chunk(claimed.pk, lease_token=token, item_limit=1)
        process_complaint_import_batch_chunk(claimed.pk, lease_token=token, item_limit=1)

        item = batch.items.get()
        self.assertEqual(item.status, ComplaintCaseImportItem.STATUS_CREATED)
        self.assertEqual(item.parsed_message_id, case.pk)
        self.assertEqual(item.outcome_reference, str(case.pk))
        process_message.assert_called_once()

    def test_stale_lease_recovers_running_item_and_concurrent_claim_is_denied(self):
        batch = self.reserve(count=2)
        claimed, first_token = claim_complaint_import_batch()
        item = batch.items.order_by('source_index').first()
        item.status = ComplaintCaseImportItem.STATUS_RUNNING
        item.save(update_fields=['status'])

        other, other_token = claim_complaint_import_batch()
        self.assertIsNone(other)
        self.assertIsNone(other_token)

        ComplaintCaseImportBatch.objects.filter(pk=claimed.pk).update(
            heartbeat_at=timezone.now() - timedelta(minutes=10),
        )
        recovered, recovered_token = claim_complaint_import_batch(lease_seconds=60)
        item.refresh_from_db()
        self.assertEqual(recovered.pk, claimed.pk)
        self.assertNotEqual(recovered_token, first_token)
        self.assertEqual(item.status, ComplaintCaseImportItem.STATUS_QUEUED)
        self.assertEqual(item.last_error_code, 'stale_lease_recovered')

    @patch('core.api.views._process_single_message', side_effect=requests.Timeout('synthetic timeout'))
    @patch('core.services.parser.detect_message_intent')
    def test_partial_external_failure_is_retryable_without_raw_error(self, detect_intent, _process):
        from core.services.parser import MessageIntent
        detect_intent.return_value = MessageIntent.COMPLAINT
        batch = self.reserve(count=1)
        claimed, token = claim_complaint_import_batch()
        process_complaint_import_batch_chunk(claimed.pk, lease_token=token, item_limit=1)

        batch.refresh_from_db()
        item = batch.items.get()
        self.assertEqual(batch.status, ComplaintCaseImportBatch.STATUS_PARTIAL)
        self.assertEqual(batch.last_error_code, 'timeout')
        self.assertEqual(item.status, ComplaintCaseImportItem.STATUS_FAILED)
        self.assertEqual(item.last_error_code, 'timeout')
        self.assertNotIn('synthetic', item.last_error_code)

        retry_complaint_import_batch(batch=batch)
        item.refresh_from_db()
        self.assertEqual(item.status, ComplaintCaseImportItem.STATUS_QUEUED)

    def test_explicit_cancellation_preserves_completed_item_checkpoints(self):
        batch = self.reserve(count=2)
        first = batch.items.order_by('source_index').first()
        first.status = ComplaintCaseImportItem.STATUS_SKIPPED
        first.completed_at = timezone.now()
        first.save(update_fields=['status', 'completed_at'])

        cancel_complaint_import_batch(batch=batch)
        batch.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual(batch.status, ComplaintCaseImportBatch.STATUS_CANCELLED)
        self.assertEqual(first.status, ComplaintCaseImportItem.STATUS_SKIPPED)
        self.assertEqual(batch.items.exclude(pk=first.pk).get().status, ComplaintCaseImportItem.STATUS_CANCELLED)

    @override_settings(TELEGRAM_BOT_TOKEN='test-token')
    def test_completion_notification_failure_remains_durable_and_retries(self):
        batch = self.reserve(count=1)
        claimed, token = claim_complaint_import_batch()
        process_complaint_import_batch_chunk(claimed.pk, lease_token=token, item_limit=1)
        operation = IntegrationOperation.objects.get(operation_type='complaint_import_completion')

        with patch('core.services.complaint_imports.requests.post', side_effect=requests.Timeout('network timeout')):
            self.assertEqual(deliver_complaint_import_notifications(), 0)
        operation.refresh_from_db()
        self.assertEqual(operation.status, IntegrationOperation.STATUS_RETRYABLE)
        operation.next_retry_at = timezone.now() - timedelta(seconds=1)
        operation.save(update_fields=['next_retry_at'])

        response = MagicMock()
        response.content = b'{}'
        response.json.return_value = {'ok': True, 'result': {'message_id': 42}}
        response.raise_for_status.return_value = None
        with patch('core.services.complaint_imports.requests.post', return_value=response):
            self.assertEqual(deliver_complaint_import_notifications(), 1)
        operation.refresh_from_db()
        self.assertEqual(operation.status, IntegrationOperation.STATUS_SUCCEEDED)

    @override_settings(
        DURABLE_JOB_RUNNERS_SHADOW_MODE=False,
        COMPLAINT_IMPORT_RUNNER_MAX_ITEMS=2,
        TELEGRAM_BOT_TOKEN='',
    )
    def test_management_runner_chunks_large_import_and_records_freshness(self):
        self.reserve(count=5)
        output = StringIO()
        call_command('process_complaint_imports', '--max-batches=1', stdout=output)
        self.assertIn('Processed 2 complaint item(s)', output.getvalue())
        heartbeat = DurableJobRunnerHeartbeat.objects.get(runner_key='complaint_imports')
        self.assertEqual(heartbeat.status, DurableJobRunnerHeartbeat.STATUS_SUCCEEDED)
        self.assertTrue(durable_job_health()['runners']['complaint_imports']['fresh'])


@override_settings(TAT_REPAIR_CASE_DELAY_SECONDS=0)
class DurableTatRepairTests(TestCase):
    def setUp(self):
        self.config = GroupSheetConfiguration.objects.create(
            group_id='-100-durable-tat', display_name='Durable TAT',
            sheet_id='sheet-durable-tat', sheet_name='TRACKER-Business',
            workflow={'type': 'tat_tracker', 'products': ['business']},
        )
        for index in range(3):
            TatTrackerCase.objects.create(
                group_id=self.config.group_id, sheet_id=self.config.sheet_id,
                sheet_name=self.config.sheet_name, row_number=5 + index,
                case_id=f'JBL-BS-DURABLE-{index}', product_key='business',
                product_label='Business', client_name=f'Client {index}', branch='Nakuru',
            )
        self.job = TatRepairJob.objects.create(
            group_configuration=self.config,
            case_ids=[f'JBL-BS-DURABLE-{index}' for index in range(3)],
            total_cases=3,
        )

    @patch('core.services.tat_tracker.resync_tat_tracker_cases', return_value={'synced': 1, 'failed': []})
    def test_bounded_runner_resumes_after_case_commit_without_duplication(self, resync):
        first = run_repair_job(self.job.pk, max_cases=1)
        self.job.refresh_from_db()
        self.assertEqual(first['processed_cases'], 1)
        self.assertEqual(self.job.status, 'queued')
        self.assertEqual(self.job.cursor, 1)

        second = run_repair_job(self.job.pk, max_cases=10)
        self.job.refresh_from_db()
        self.assertEqual(second['processed_cases'], 2)
        self.assertEqual(self.job.status, 'completed')
        self.assertEqual(self.job.cursor, 3)
        self.assertEqual(resync.call_count, 3)

    def test_concurrent_claim_is_denied_and_stale_lease_is_recovered(self):
        claimed, first_token = claim_repair_job()
        other, other_token = claim_repair_job()
        self.assertIsNone(other)
        self.assertIsNone(other_token)

        TatRepairJob.objects.filter(pk=claimed.pk).update(
            heartbeat_at=timezone.now() - timedelta(minutes=10),
        )
        recovered, recovered_token = claim_repair_job(lease_seconds=60)
        self.assertEqual(recovered.pk, claimed.pk)
        self.assertNotEqual(recovered_token, first_token)

    def test_duplicate_job_creation_resumes_the_existing_queue_entry(self):
        replay = create_repair_job(self.config)

        self.assertEqual(replay.pk, self.job.pk)
        self.assertEqual(TatRepairJob.objects.count(), 1)

    def test_explicit_cancellation_releases_the_lease_and_preserves_cursor(self):
        claimed, _token = claim_repair_job()
        claimed.cursor = 1
        claimed.save(update_fields=['cursor'])

        cancelled = cancel_repair_job(job=claimed)

        self.assertEqual(cancelled.status, 'cancelled')
        self.assertEqual(cancelled.cursor, 1)
        self.assertIsNone(cancelled.worker_token)
        self.assertEqual(claim_repair_job(), (None, None))

    @override_settings(DURABLE_JOB_RUNNERS_SHADOW_MODE=False, TAT_REPAIR_RUNNER_MAX_CASES=2)
    @patch('core.services.tat_tracker.resync_tat_tracker_cases', return_value={'synced': 1, 'failed': []})
    def test_scheduled_command_is_bounded_and_records_heartbeat(self, _resync):
        output = StringIO()
        call_command('process_tat_repairs', '--max-jobs=1', stdout=output)
        self.job.refresh_from_db()
        self.assertEqual(self.job.cursor, 2)
        self.assertEqual(self.job.status, 'queued')
        self.assertIn('Processed 2 TAT repair case(s)', output.getvalue())
        self.assertTrue(durable_job_health()['runners']['tat_repairs']['fresh'])

    def test_no_request_path_contains_daemon_thread_startup(self):
        root = Path(__file__).resolve().parent.parent
        for relative in ('core/api/views.py', 'core/services/tat_repair_jobs.py'):
            source = (root / relative).read_text(encoding='utf-8')
            self.assertNotIn('threading.Thread', source)
            self.assertNotIn('daemon=True', source)

    def test_missing_heartbeat_jobs_are_reported_as_stalled(self):
        self.job.status = 'running'
        self.job.heartbeat_at = None
        self.job.save(update_fields=['status', 'heartbeat_at'])
        health = durable_job_health()
        self.assertEqual(health['tat_repairs']['stalled'], 1)


class DurableRunnerReadinessTests(TestCase):
    def settings(self):
        values = {name: True for _surface, name in MINIAPP_AUTH_SETTINGS}
        values.update({name: 86400 for _surface, name in TELEGRAM_AUTH_AGE_SETTINGS})
        values.update({
            'REQUIRE_MINIAPP_IDEMPOTENCY_KEY': True,
            'MINIAPP_IDEMPOTENCY_OBSERVATION_DAYS': 14,
            'TELEGRAM_WEBHOOK_SECRET': 'test-webhook-secret',
            'TAT_TRACKER_SIGNATURES_ENABLED': False,
            'ORIGINATION_ESIGN_ENABLED': False,
            'ORIGINATION_CONDITIONAL_APPROVAL_ENABLED': False,
            'ACCESS_GRANT_GOVERNANCE_ENFORCED': True,
            'DURABLE_JOB_LEASE_SECONDS': 300,
            'DURABLE_JOB_RUNNER_MAX_SILENCE_SECONDS': 900,
            'COMPLAINT_IMPORT_RUNNER_MAX_ITEMS': 10,
            'TAT_REPAIR_RUNNER_MAX_CASES': 5,
            'COMPLAINT_IMPORT_RUNNER_REQUIRED': True,
            'TAT_REPAIR_RUNNER_REQUIRED': True,
        })
        return SimpleNamespace(**values)

    def test_required_runner_freshness_is_a_production_error(self):
        missing_codes = {
            issue.code for issue in production_security_readiness_issues(
                self.settings(), check_database=True,
            )
        }
        self.assertIn('complaint-imports-runner-stale', missing_codes)
        self.assertIn('tat-repairs-runner-stale', missing_codes)

        finish_runner('complaint_imports')
        finish_runner('tat_repairs')
        ready_codes = {
            issue.code for issue in production_security_readiness_issues(
                self.settings(), check_database=True,
            )
        }
        self.assertNotIn('complaint-imports-runner-stale', ready_codes)
        self.assertNotIn('tat-repairs-runner-stale', ready_codes)

        finish_runner('tat_repairs', error_code='runner_failed')
        failed_codes = {
            issue.code for issue in production_security_readiness_issues(
                self.settings(), check_database=True,
            )
        }
        self.assertIn('tat-repairs-runner-failed', failed_codes)
