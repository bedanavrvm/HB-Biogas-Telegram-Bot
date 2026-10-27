"""Synthetic request resource bounds for selected Origination deletion."""
import time
import tracemalloc
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.models import ComplianceAuditEvent, IntegrationOperation
from origination.models import LoanOriginationApplication, OriginationProductDefinition, OriginationSigningPackage
from core.services.miniapp_deletion import CASCADE, DeletionError, SelectionChanged, _records, _row_fingerprint, delete_selection, preview_selection


@override_settings(MINIAPP_TEST_DELETION_ENABLED=True)
class DeletionResourceTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser('synthetic-delete-resources', password='synthetic-only')
        self.product = OriginationProductDefinition.objects.create(product_key='delete-resources', name='Synthetic resource loan')

    def applications(self, count, pdf_size=0):
        rows = LoanOriginationApplication.objects.bulk_create([
            LoanOriginationApplication(reference_number=f'SYNTHETIC-RESOURCE-{i}', officer=self.actor,
                product_definition=self.product, branch='Synthetic') for i in range(count)])
        OriginationSigningPackage.objects.bulk_create([
            OriginationSigningPackage(application=row, application_revision=1, external_reference=f'SYNTHETIC-PACKAGE-{i}',
                document_type='synthetic') for i, row in enumerate(rows)])
        if pdf_size:
            OriginationSigningPackage.objects.filter(application__in=rows).update(
                frozen_unsigned_document=b'u' * pdf_size, pending_signed_document=b's' * pdf_size)
        return rows

    def preview(self, rows):
        return preview_selection(model_label=LoanOriginationApplication._meta.label,
            ids=[row.pk for row in rows], actor=self.actor, mode=CASCADE)

    def delete(self, rows, plan):
        return delete_selection(model_label=LoanOriginationApplication._meta.label,
            ids=[row.pk for row in rows], actor=self.actor, mode=CASCADE,
            fingerprint=plan['fingerprint'], request_id='synthetic-resource-delete')

    def test_preview_does_not_retain_all_stored_pdf_bytes(self):
        rows = self.applications(12, pdf_size=1024 * 1024)
        tracemalloc.start()
        try:
            started = time.perf_counter()
            plan = self.preview(rows)
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        print(f'Synthetic delete preview: 24 MiB PDFs, peak={peak / 1024**2:.2f} MiB, seconds={time.perf_counter()-started:.3f}')
        self.assertEqual(len(plan['deleted']), 24)
        self.assertLess(peak, 8 * 1024 * 1024, 'The confirmation retains all frozen PDF bytes in the web worker.')

    def test_preview_queries_are_batched_across_selected_applications(self):
        rows = self.applications(32)
        with CaptureQueriesContext(connection) as queries:
            plan = self.preview(rows)
        print(f'Synthetic delete preview: 32 applications, 32 packages, queries={len(queries)}')
        self.assertEqual(len(plan['deleted']), 64)
        self.assertLess(len(queries), 180, 'Each selected application repeats relationship queries.')

    def test_confirmation_deletion_is_batched_and_retry_safe(self):
        rows = self.applications(32)
        plan = self.preview(rows)
        with CaptureQueriesContext(connection) as queries:
            result = self.delete(rows, plan)
        print(f'Synthetic confirmed deletion: 32 applications, 32 packages, queries={len(queries)}')
        self.assertEqual(result['deleted'], 64)
        self.assertFalse(LoanOriginationApplication.objects.exists())
        self.assertTrue(OriginationProductDefinition.objects.filter(pk=self.product.pk).exists())
        self.assertEqual(IntegrationOperation.objects.filter(operation_type='miniapp_record_deleted').count(), 64)
        self.assertEqual(ComplianceAuditEvent.objects.filter(deduplication_key='miniapp-delete:synthetic-resource-delete').count(), 1)
        self.assertTrue(self.delete(rows, plan)['replayed'])
        self.assertLess(len(queries), 240, 'Confirmation still makes individual lock, tombstone or delete queries.')

    def test_stored_pdf_change_still_invalidates_the_confirmation(self):
        rows = self.applications(1, pdf_size=1024)
        plan = self.preview(rows)
        OriginationSigningPackage.objects.filter(application=rows[0]).update(pending_signed_document=b'changed synthetic bytes')
        with self.assertRaises(SelectionChanged):
            self.delete(rows, plan)
        self.assertEqual(LoanOriginationApplication.objects.count(), 1)

    def test_deferred_and_full_records_have_identical_fingerprints(self):
        rows = self.applications(1, pdf_size=1024)
        complete = OriginationSigningPackage.objects.get(application=rows[0])
        deferred = _records(OriginationSigningPackage).get(pk=complete.pk)
        self.assertIn('frozen_unsigned_document', deferred.get_deferred_fields())
        self.assertEqual(_row_fingerprint(deferred), _row_fingerprint(complete))
        self.assertIn('frozen_unsigned_document', deferred.get_deferred_fields())

    def test_large_admin_confirmation_deletion_and_response_retry(self):
        rows = self.applications(96, pdf_size=1024 * 1024)
        outside = LoanOriginationApplication.objects.create(reference_number='SYNTHETIC-OUTSIDE-SELECTION',
            officer=self.actor, product_definition=self.product, branch='Synthetic')
        self.client.force_login(self.actor)
        url = reverse('admin:origination_loanoriginationapplication_changelist')
        data = {'action': 'delete_testing_selection', ACTION_CHECKBOX_NAME: [str(row.pk) for row in rows],
                'deletion_mode': CASCADE}
        tracemalloc.start()
        started = time.perf_counter()
        try:
            response = self.client.post(url, data)
            self.assertEqual(response.status_code, 200)
            token = response.context_data['deletion_token']
            response = self.client.post(url, {**data, 'deletion_token': token, 'confirm_deletion': '1'})
            self.assertEqual(response.status_code, 302)
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        print(f'Synthetic Admin deletion: 96 applications, 192 MiB PDFs, peak={peak / 1024**2:.2f} MiB, seconds={time.perf_counter()-started:.3f}')
        self.assertLess(peak, 24 * 1024 * 1024)
        self.assertEqual(list(LoanOriginationApplication.objects.values_list('pk', flat=True)), [outside.pk])
        response = self.client.post(url, {**data, 'deletion_token': token, 'confirm_deletion': '1'})
        self.assertEqual(response.status_code, 302, 'Retry after a lost response must return the saved deletion result.')
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='records.deleted').count(), 1)

    def test_admin_confirmation_cannot_add_an_unconfirmed_application(self):
        rows = self.applications(2)
        self.client.force_login(self.actor)
        url = reverse('admin:origination_loanoriginationapplication_changelist')
        data = {'action': 'delete_testing_selection', ACTION_CHECKBOX_NAME: [str(rows[0].pk)],
                'deletion_mode': CASCADE}
        preview = self.client.post(url, data)
        response = self.client.post(url, {**data, ACTION_CHECKBOX_NAME: [str(row.pk) for row in rows],
            'deletion_token': preview.context_data['deletion_token'], 'confirm_deletion': '1'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(LoanOriginationApplication.objects.count(), 2)

    def test_oversized_related_graph_stops_before_any_mutation(self):
        rows = self.applications(2)
        with patch('core.services.miniapp_deletion.MAX_RECORDS', 3):
            with self.assertRaisesMessage(DeletionError, 'more than 10,000'):
                self.preview(rows)
        self.assertEqual(LoanOriginationApplication.objects.count(), 2)
        self.assertEqual(OriginationSigningPackage.objects.count(), 2)
