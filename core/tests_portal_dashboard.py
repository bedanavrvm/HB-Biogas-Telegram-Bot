from datetime import date

from django.test import TestCase

from core.models import InvoiceIdentityReview, InvoiceUploadBatch, JawabuFarmerMaster, ParsedInvoice
from core.services.portal_dashboard import dashboard_payload


class PortalActionDashboardTests(TestCase):
    def farmer(self, name, branch, **overrides):
        values = {
            'customer_name': name,
            'national_id': overrides.pop('national_id', ''),
            'primary_phone': overrides.pop('primary_phone', ''),
            'branch': branch,
            'status': 'active',
            'hbg_visit_date': date(2026, 8, 1),
        }
        values.update(overrides)
        return JawabuFarmerMaster.objects.create(**values)

    def test_dashboard_counts_and_recent_cases_are_branch_scoped(self):
        allowed = self.farmer('Allowed farmer', 'Nakuru', national_id='11111111')
        self.farmer('Other branch farmer', 'Ruiru', national_id='22222222')

        payload = dashboard_payload(None, access={'branches': ['Nakuru']})

        self.assertEqual(payload['counts']['jbl_queue'], 1)
        self.assertEqual(payload['counts']['total'], 1)
        self.assertEqual([item['customer_name'] for item in payload['recent_cases']], [allowed.customer_name])
        self.assertEqual(payload['scope']['branches'], ['Nakuru'])

    def test_invoice_identity_attention_does_not_cross_branch_scope(self):
        allowed = self.farmer('Allowed farmer', 'Nakuru', national_id='11111111')
        other = self.farmer('Other farmer', 'Ruiru', national_id='22222222')
        batch = InvoiceUploadBatch.objects.create(original_filename='invoices.pdf')
        for index, farmer in enumerate((allowed, other), start=1):
            invoice = ParsedInvoice.objects.create(
                batch=batch,
                invoice_no=f'INV-{index}',
                customer_name='Different person',
                customer_id=f'9000000{index}',
                matched_farmer=farmer,
                matched_order_number=farmer.order_number,
                status='matched',
            )
            InvoiceIdentityReview.objects.create(invoice=invoice, farmer=farmer)

        payload = dashboard_payload(None, access={'branches': ['Nakuru']})
        attention = {item['key']: item for item in payload['attention']}

        self.assertEqual(attention['invoice_identity']['count'], 1)

    def test_dashboard_keeps_legacy_counts_and_adds_action_contract(self):
        self.farmer('Farmer', 'Nakuru')
        payload = dashboard_payload(None, access={})

        self.assertIn('counts', payload)
        self.assertIn('queues', payload)
        self.assertIn('attention', payload)
        self.assertIn('activity_7d', payload)
        self.assertIn('pipeline_distribution', payload)
        self.assertIn('recent_cases', payload)
