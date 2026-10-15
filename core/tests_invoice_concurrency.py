"""Real database locks: intentionally not represented as SQLite validation."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.db import connection, connections
from django.test import TransactionTestCase

from core.models import ComplianceAuditChainState, InvoiceNameChangeItem, ParsedInvoice
from core.services.invoice_identity import confirm_replacement
from core.services.invoice_parser import unmatch_invoice
from core.tests_invoice_identity import InvoiceIdentityWorkflowTests


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL row locks.')
class InvoiceCorrectionConcurrencyTests(TransactionTestCase):
    invoice = InvoiceIdentityWorkflowTests.invoice
    correction = InvoiceIdentityWorkflowTests.correction

    def setUp(self):
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        InvoiceIdentityWorkflowTests.setUp(self)
        self.original, self.item = self.correction()
        self.original.refresh_from_db()
        self.item.refresh_from_db()
        self.replacement = self.invoice(invoice_no='SYNTHETIC-CORRECTED', customer_id='12345678',
            customer_name='M. Wanjiku', status='unmatched', matched_farmer=None)

    def race(self, actions):
        barrier = Barrier(2)

        def run(action):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                action()
                return 'saved'
            except ValueError:
                return 'conflict'
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(run, action) for action in actions]
            return [future.result(timeout=20) for future in futures]

    def test_two_confirmations_complete_once(self):
        action = lambda: confirm_replacement(self.item, self.replacement, actor='Synthetic Operations')
        self.assertEqual(self.race([action, action]), ['saved', 'saved'])
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, 'completed')
        self.assertEqual(self.replacement.events.filter(action='matched').count(), 1)

    def test_confirmation_and_unmatch_have_one_winner(self):
        actions = [lambda: confirm_replacement(self.item, self.replacement, actor='Synthetic Operations'),
                   lambda: unmatch_invoice(self.original, actor='Synthetic Operations', expected_revision=self.original.revision)]
        outcomes = self.race(actions)
        self.assertEqual(sorted(outcomes), ['conflict', 'saved'])
        item = InvoiceNameChangeItem.objects.get(pk=self.item.pk)
        original = ParsedInvoice.objects.get(pk=self.original.pk)
        self.assertIn((item.status, original.status), [('completed', 'superseded'), ('withdrawn', 'unmatched')])
