"""Desired recovery/concurrency contracts using synthetic records only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Barrier
from unittest import skipUnless
from unittest.mock import Mock, patch

from django.db import connection, close_old_connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from pypdf import PdfWriter

from core.models import IntegrationOperation, InvoiceUploadBatch, JawabuFarmerMaster, GroupSheetConfiguration
from core.services.external_resilience import _mark_attempt, _mark_success, _mark_failure, reserve_operation
from core.services.invoice_parser import ingest_invoice_upload_batch, InvoiceUploadRequestConflictError
from core.services.portal_publication import MASTER_OPERATION, SOURCE_MODEL, queued_publication_operations


def operation(key, destination='master'):
    return reserve_operation(
        integration='google_sheets', operation_type=MASTER_OPERATION,
        deduplication_key=f'engineering-test:{key}', source_model=SOURCE_MODEL, source_id=key,
        metadata={'destination_key': destination}, max_attempts=4,
    )[0]


class ExecutionOwnershipTests(TestCase):
    def test_live_final_attempt_is_not_exhausted_by_another_request(self):
        from core.services.external_resilience import execute_operation
        row = operation('live-final')
        row.max_attempts = 1
        row.save(update_fields=['max_attempts'])
        owner = _mark_attempt(row.pk, now=timezone.now())
        self.assertIsNone(_mark_attempt(row.pk, now=timezone.now()))
        row.refresh_from_db()
        self.assertEqual(row.status, IntegrationOperation.STATUS_RUNNING)
        duplicate = Mock()
        self.assertIsNone(execute_operation(row, duplicate))
        duplicate.assert_not_called()
        self.assertTrue(_mark_success(row.pk, now=timezone.now(), result={'action': 'done'},
                                      attempt_token=owner.metadata['attempt_token']))

    def test_expired_final_attempt_cannot_execute_again(self):
        from core.services.external_resilience import execute_operation, ExternalOperationError
        row = operation('expired-final')
        row.max_attempts = 1
        row.save(update_fields=['max_attempts'])
        _mark_attempt(row.pk, now=timezone.now() - timedelta(minutes=5))
        duplicate = Mock()
        with self.assertRaises(ExternalOperationError):
            execute_operation(row, duplicate)
        duplicate.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, IntegrationOperation.STATUS_DEAD_LETTER)

    def test_old_success_cannot_complete_a_replacement_claim(self):
        row = operation('late-success')
        first = _mark_attempt(row.pk, now=timezone.now())
        IntegrationOperation.objects.filter(pk=row.pk).update(last_attempt_at=timezone.now() - timedelta(minutes=5))
        second = _mark_attempt(row.pk, now=timezone.now())
        self.assertFalse(_mark_success(row.pk, now=timezone.now(), result={'action': 'old'},
                                       attempt_token=first.metadata['attempt_token']))
        row.refresh_from_db()
        self.assertEqual(row.status, IntegrationOperation.STATUS_RUNNING)
        self.assertEqual(row.metadata['attempt_token'], second.metadata['attempt_token'])

    def test_composed_gateway_budget_stops_new_calls(self):
        from core.services.external_resilience import external_call_budget, remaining_external_seconds
        with patch('core.services.external_resilience.time.monotonic', side_effect=[10, 11, 14]):
            with external_call_budget(3):
                self.assertEqual(remaining_external_seconds(10), 2)
                with self.assertRaises(TimeoutError):
                    remaining_external_seconds(10)
    def test_terminal_work_cannot_be_claimed(self):
        row = operation('completed')
        claimed = _mark_attempt(row.pk, now=timezone.now())
        self.assertTrue(_mark_success(row.pk, now=timezone.now(), result={'action': 'done'},
                                      attempt_token=claimed.metadata['attempt_token']))
        self.assertIsNone(_mark_attempt(row.pk, now=timezone.now()))
        row.refresh_from_db()
        self.assertEqual(row.attempts, 1)

    def test_old_failure_cannot_overwrite_new_success(self):
        row = operation('late')
        first = _mark_attempt(row.pk, now=timezone.now())
        IntegrationOperation.objects.filter(pk=row.pk).update(last_attempt_at=timezone.now() - timedelta(minutes=5))
        second = _mark_attempt(row.pk, now=timezone.now())
        self.assertTrue(_mark_success(row.pk, now=timezone.now(), result={'action': 'done'},
                                      attempt_token=second.metadata['attempt_token']))
        saved = _mark_failure(row.pk, RuntimeError('synthetic'), now=timezone.now(), retryable=True,
                              attempt_token=first.metadata['attempt_token'])
        self.assertFalse(saved.outcome_accepted)
        self.assertEqual(saved.status, 'succeeded')

    def test_active_future_and_exhausted_work_are_not_executed(self):
        row = operation('future')
        IntegrationOperation.objects.filter(pk=row.pk).update(next_retry_at=timezone.now() + timedelta(minutes=10))
        self.assertIsNone(_mark_attempt(row.pk, now=timezone.now()))
        IntegrationOperation.objects.filter(pk=row.pk).update(next_retry_at=None, attempts=4)
        self.assertIsNone(_mark_attempt(row.pk, now=timezone.now()))
        row.refresh_from_db()
        self.assertEqual(row.status, 'dead_letter')

    def test_destinations_progress_independently_but_keep_fifo(self):
        first = operation('first')
        later = operation('later')
        eco = operation('eco', 'eco')
        IntegrationOperation.objects.filter(pk=first.pk).update(status=IntegrationOperation.STATUS_RETRYABLE, next_retry_at=timezone.now() + timedelta(minutes=10))
        ids = set(queued_publication_operations().values_list('pk', flat=True))
        self.assertIn(eco.pk, ids)
        self.assertNotIn(first.pk, ids)
        self.assertNotIn(later.pk, ids)


@skipUnless(connection.vendor == 'postgresql', 'Real row locks require the PostgreSQL test profile.')
class PostgreSQLClaimTests(TransactionTestCase):
    def test_two_connections_receive_one_executable_claim(self):
        row = operation('concurrent')
        barrier = Barrier(2)

        def claim():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return _mark_attempt(row.pk, now=timezone.now()) is not None
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as workers:
            claims = list(workers.map(lambda _: claim(), range(2)))
        self.assertEqual(claims.count(True), 1)
        row.refresh_from_db()
        self.assertEqual(row.attempts, 1)

    def test_prior_payment_schema_upgrade_preserves_synthetic_batch(self):
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        previous = ('payments', '0003_payment_number_allocation_timing')
        try:
            executor.migrate([previous])
            state = executor.loader.project_state([previous]).apps
            group = GroupSheetConfiguration.objects.create(
                group_id='synthetic-upgrade', sheet_id='synthetic', enabled=True,
                workflow={'type': 'jawabu_homebiogas'},
            )
            batch = state.get_model('payments', 'PaymentBatch').objects.create(
                group_configuration_id=group.pk, status='draft',
            )
            batch_id = batch.pk
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            from payments.models import PaymentBatch
            restored = PaymentBatch.objects.get(pk=batch_id)
            self.assertEqual(restored.status, 'draft')
            self.assertEqual(restored.group_configuration_id, group.pk)
        finally:
            MigrationExecutor(connection).migrate(latest)


class InvoiceRecoveryTests(TestCase):
    @patch('core.services.invoice_parser.parse_invoice_pdf_bytes', return_value=([{'page': 1, 'invoice_no': 'synthetic-001'}], 1))
    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_row_and_event_failure_does_not_leave_partial_parse(self, storage, parser):
        from django.db import IntegrityError
        from core.models import ParsedInvoice, ParsedInvoiceEvent
        storage.return_value.upload.return_value = ('synthetic-id', 'https://drive.test/synthetic')
        values = dict(pdf_bytes=b'%PDF-synthetic-atomic', filename='synthetic.pdf', client_request_id='synthetic-atomic')
        with patch('core.services.invoice_parser.ParsedInvoiceEvent.objects.bulk_create', side_effect=IntegrityError('synthetic')):
            with self.assertRaises(IntegrityError):
                ingest_invoice_upload_batch(**values)
        self.assertEqual(ParsedInvoice.objects.count(), 0)
        self.assertEqual(ParsedInvoiceEvent.objects.count(), 0)
        batch = InvoiceUploadBatch.objects.get()
        self.assertEqual(batch.drive_file_id, 'synthetic-id')
        self.assertEqual(batch.status, 'uploaded')
        batch.metadata['processing_until'] = ''
        batch.save(update_fields=['metadata'])
        result = ingest_invoice_upload_batch(**values)
        self.assertEqual(result.total_parsed, 1)
        self.assertEqual(ParsedInvoice.objects.count(), 1)
        self.assertEqual(ParsedInvoiceEvent.objects.count(), 1)
        storage.return_value.upload.assert_called_once()
    @patch('core.services.invoice_parser.parse_invoice_pdf_bytes', return_value=([{'page': 1, 'invoice_no': 'synthetic-001'}], 1))
    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_new_request_can_resume_same_unfinished_hash(self, storage, parser):
        import hashlib
        content = b'%PDF-synthetic-new-request'
        batch = InvoiceUploadBatch.objects.create(
            client_request_id='old-request', content_sha256=hashlib.sha256(content).hexdigest(),
            original_filename='synthetic.pdf', status='parse_failed', drive_file_id='synthetic-drive-id',
        )
        result = ingest_invoice_upload_batch(pdf_bytes=content, filename='synthetic.pdf', client_request_id='new-request')
        self.assertEqual(result.pk, batch.pk)
        parser.assert_called_once()
        storage.return_value.upload.assert_not_called()
        with self.assertRaises(InvoiceUploadRequestConflictError):
            ingest_invoice_upload_batch(pdf_bytes=b'different PDF', filename='synthetic.pdf', client_request_id='new-request')

    @patch('core.services.invoice_parser.parse_invoice_pdf_bytes', return_value=([{'page': 1, 'invoice_no': 'synthetic-001'}], 1))
    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_existing_file_resumes_parse_without_reupload(self, storage, parser):
        import hashlib
        content = b'%PDF-synthetic-test'
        batch = InvoiceUploadBatch.objects.create(
            client_request_id='synthetic-resume', content_sha256=hashlib.sha256(content).hexdigest(),
            original_filename='synthetic.pdf', status='uploaded', drive_file_id='synthetic-drive-id',
        )
        result = ingest_invoice_upload_batch(pdf_bytes=content, filename='synthetic.pdf', client_request_id='synthetic-resume')
        self.assertEqual(result.pk, batch.pk)
        self.assertEqual(result.status, 'awaiting_confirmation')
        storage.return_value.upload.assert_not_called()
        parser.assert_called_once()
        replay = ingest_invoice_upload_batch(pdf_bytes=content, filename='synthetic.pdf', client_request_id='synthetic-resume')
        self.assertEqual(replay.pk, batch.pk)
        parser.assert_called_once()

    @patch('core.services.invoice_parser.parse_invoice_pdf_bytes', return_value=([{'page': 1, 'invoice_no': 'synthetic-001'}], 1))
    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_interrupted_live_upload_is_not_reported_as_complete(self, storage, parser):
        storage.return_value.upload.side_effect = SystemExit('synthetic interruption')
        kwargs = dict(pdf_bytes=b'%PDF-synthetic', filename='synthetic.pdf', client_request_id='synthetic-stop')
        with self.assertRaises(SystemExit):
            ingest_invoice_upload_batch(**kwargs)
        with self.assertRaises(InvoiceUploadRequestConflictError):
            ingest_invoice_upload_batch(**kwargs)
        self.assertEqual(storage.return_value.upload.call_count, 1)

    @patch('core.services.invoice_parser.parse_invoice_pdf_bytes', side_effect=ValueError('Upload one invoice per file.'))
    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_merged_invoice_rejection_happens_before_drive_acceptance(self, storage, parser):
        with self.assertRaisesRegex(ValueError, 'one invoice per file'):
            ingest_invoice_upload_batch(pdf_bytes=b'%PDF-synthetic-merged', filename='merged.pdf', client_request_id='synthetic-merged')
        result = InvoiceUploadBatch.objects.get(client_request_id='synthetic-merged')
        self.assertEqual(result.status, 'parse_failed')
        self.assertFalse(result.drive_file_id)
        storage.return_value.upload.assert_not_called()
        self.assertTrue(result.content_sha256)


class PDFBudgetTests(TestCase):
    def test_delivery_preview_worker_starts_at_the_requested_invoice_page(self):
        from core.services.secure_media_preview import pdf_preview_html
        writer = PdfWriter()
        for _ in range(10):
            writer.add_blank_page(width=100, height=100)
        stream = BytesIO()
        writer.write(stream)
        preview = pdf_preview_html(stream.getvalue(), 'synthetic.pdf', start_page=9)
        self.assertIn(b'<figcaption>Page 9</figcaption>', preview)
        self.assertIn(b'<figcaption>Page 10</figcaption>', preview)
        self.assertNotIn(b'<figcaption>Page 1</figcaption>', preview)
        single = pdf_preview_html(stream.getvalue(), 'synthetic.pdf', start_page=9, page_limit=1)
        self.assertIn(b'<figcaption>Page 9</figcaption>', single)
        self.assertNotIn(b'<figcaption>Page 10</figcaption>', single)

    def test_preview_runs_with_hard_worker_timeout(self):
        from core.services.secure_media_preview import pdf_preview_html
        import subprocess
        with patch('core.services.secure_media_preview.subprocess.run', side_effect=subprocess.TimeoutExpired('synthetic', 15)):
            with self.assertRaisesRegex(ValueError, 'took too long'):
                pdf_preview_html(b'%PDF-synthetic', 'synthetic.pdf')

    def test_oversized_delivery_is_rejected_before_processing(self):
        from core.services.invoice_processing_limits import validate_invoice_delivery
        with self.assertRaisesRegex(ValueError, 'at most 20'):
            validate_invoice_delivery([Mock(size=1)] * 21)
        with self.assertRaisesRegex(ValueError, '32 MB'):
            validate_invoice_delivery([Mock(size=33 * 1024 * 1024)])
    def test_page_allocation_is_checked_before_render(self):
        from core.services.secure_media_preview import _pdf_preview_html
        document = Mock()
        document.__len__ = Mock(return_value=1)
        page = Mock()
        page.get_size.return_value = (100000, 100000)
        document.__getitem__ = Mock(return_value=page)
        with patch('pypdfium2.PdfDocument', return_value=document):
            with self.assertRaisesRegex(ValueError, 'too detailed'):
                _pdf_preview_html(b'%PDF-synthetic', 'synthetic.pdf')
        page.render.assert_not_called()
        page.close.assert_called_once()
        document.close.assert_called_once()

    def test_real_synthetic_pdf_is_parsed_in_a_disposable_process(self):
        from core.services.invoice_parser import parse_invoice_pdf_bytes
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        stream = BytesIO()
        writer.write(stream)
        with self.assertRaisesRegex(ValueError, 'one invoice per file'):
            parse_invoice_pdf_bytes(stream.getvalue())
        from core.services.secure_media_preview import pdf_preview_html
        self.assertIn(b'data:image/jpeg', pdf_preview_html(stream.getvalue(), 'synthetic.pdf'))


class DestinationBindingTests(TestCase):
    def test_group_bound_case_uses_its_own_destination(self):
        from core.services.jawabu_pipeline import _jawabu_group_config
        one = GroupSheetConfiguration.objects.create(group_id='synthetic-one', sheet_id='one', enabled=True,
                                                     workflow={'type': 'jawabu_homebiogas', 'master_sync_enabled': True})
        two = GroupSheetConfiguration.objects.create(group_id='synthetic-two', sheet_id='two', enabled=True,
                                                     workflow={'type': 'jawabu_homebiogas', 'master_sync_enabled': True})
        farmer = JawabuFarmerMaster.objects.create(customer_name='Synthetic', group_configuration=two)
        self.assertEqual(_jawabu_group_config(farmer).sheet_id, 'two')
        farmer.group_configuration = None
        self.assertIsNone(_jawabu_group_config(farmer))
        self.assertNotEqual(one.sheet_id, two.sheet_id)

    def test_reconfigured_destination_is_superseded_without_publishing(self):
        from core.services.portal_publication import attempt_publication, reserve_farmer_publication
        group = GroupSheetConfiguration.objects.create(group_id='synthetic-route', sheet_id='old', enabled=True,
                                                      workflow={'type': 'jawabu_homebiogas', 'master_sync_enabled': True})
        farmer = JawabuFarmerMaster.objects.create(customer_name='Synthetic', group_configuration=group)
        row = reserve_farmer_publication(farmer)[0]
        group.sheet_id = 'new'
        group.save(update_fields=['sheet_id'])
        with patch('core.services.jawabu_pipeline.sync_farmer_to_master_sheet') as publish:
            result = attempt_publication(row)
        self.assertTrue(result['superseded'])
        publish.assert_not_called()
        replacement = IntegrationOperation.objects.exclude(pk=row.pk).get()
        self.assertEqual(replacement.metadata['destination']['spreadsheet'], 'new')
