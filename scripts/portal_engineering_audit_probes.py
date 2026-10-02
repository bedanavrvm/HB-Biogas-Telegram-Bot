"""Synthetic characterization probes, not desired acceptance contracts.

Run only on an isolated local test database. These assertions demonstrate
current risks; passing them does not mean the behaviors are correct.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from core.models import IntegrationOperation
from core.services.external_resilience import (
    _mark_attempt, _mark_failure, _mark_success, reserve_operation,
)
from core.services.portal_publication import MASTER_OPERATION, SOURCE_MODEL, queued_publication_operations
from core.services.invoice_parser import ingest_invoice_upload_batch


class PortalEngineeringAuditProbes(TestCase):
    def operation(self, key):
        return reserve_operation(
            integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
            operation_type=MASTER_OPERATION, deduplication_key=f'synthetic-engineering-{key}',
            source_model=SOURCE_MODEL, source_id=key, max_attempts=4,
        )[0]

    def test_stale_claim_can_reopen_a_succeeded_operation(self):
        operation = self.operation('completed')
        _mark_attempt(operation.pk, now=timezone.now())
        _mark_success(operation.pk, now=timezone.now(), result={'action': 'first'})
        # Interleaving: another caller's earlier pending-status read is stale.
        claimed = _mark_attempt(operation.pk, now=timezone.now())
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.status, IntegrationOperation.STATUS_RUNNING)
        self.assertEqual(claimed.attempts, 2)

    def test_old_attempt_failure_can_overwrite_new_attempt_success(self):
        operation = self.operation('late-failure')
        _mark_attempt(operation.pk, now=timezone.now())
        IntegrationOperation.objects.filter(pk=operation.pk).update(
            last_attempt_at=timezone.now() - timedelta(minutes=5),
        )
        replacement = _mark_attempt(operation.pk, now=timezone.now())
        self.assertEqual(replacement.attempts, 2)
        _mark_success(operation.pk, now=timezone.now(), result={'action': 'new-worker-success'})
        # No claim token/attempt fence is passed to the completion methods.
        _mark_failure(operation.pk, RuntimeError('synthetic old timeout'), now=timezone.now(), retryable=True)
        operation.refresh_from_db()
        self.assertEqual(operation.status, IntegrationOperation.STATUS_RETRYABLE)
        self.assertIsNotNone(operation.completed_at)

    def test_retry_delay_blocks_unrelated_master_publication(self):
        first = self.operation('destination-a')
        second = self.operation('destination-b')
        IntegrationOperation.objects.filter(pk=first.pk).update(
            status=IntegrationOperation.STATUS_RETRYABLE,
            next_retry_at=timezone.now() + timedelta(minutes=10),
        )
        self.assertEqual(second.status, IntegrationOperation.STATUS_PENDING)
        self.assertFalse(queued_publication_operations().exists())

    def test_interrupted_invoice_upload_replays_an_unfinished_batch(self):
        # Simulate process termination, rather than an ordinary caught API error.
        # The storage gateway is mocked; no Google request is made.
        with patch('core.services.order_approval.GoogleDriveMediaStorage') as storage:
            storage.return_value.upload.side_effect = SystemExit('synthetic process stop')
            arguments = dict(
                pdf_bytes=b'%PDF synthetic audit fixture', filename='synthetic-audit.pdf',
                client_request_id='synthetic-interrupted-invoice-upload',
            )
            with self.assertRaises(SystemExit):
                ingest_invoice_upload_batch(**arguments)
            replay = ingest_invoice_upload_batch(**arguments)
            self.assertEqual(replay.status, 'uploaded')
            self.assertEqual(replay.drive_file_id, '')
            self.assertEqual(storage.return_value.upload.call_count, 1)
