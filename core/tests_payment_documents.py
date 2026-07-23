from datetime import date
from decimal import Decimal
import io
import json
import tempfile
from unittest.mock import patch

from django.core.files import File
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from core.models import (
    InvoiceUploadBatch,
    JawabuFarmerMaster,
    ParsedInvoice,
    PaymentDocument,
    PaymentDocumentTemplate,
)
from core.services.invoice_parser import ingest_invoice_upload_batch
from core.services.payment_documents import (
    generate_payment_workbook,
    payment_readiness,
    payment_template_layout,
)


@override_settings(
    ALLOWED_HOSTS=['testserver'],
    PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False,
    SECURE_SSL_REDIRECT=False,
)
class InvoicePoolAndPaymentDocumentTests(TestCase):
    def farmer(self, **overrides):
        data = {
            'customer_name': 'Mary Wanjiku',
            'national_id': '12345678',
            'primary_phone': '254712345678',
            'secondary_phone': '254700000001',
            'branch': 'Nakuru',
            'jbl_officer': 'Officer Jane',
            'final_decision': 'Approved',
            'customer_no': '15357',
            'imab_customer_name': 'MARY WANJIKU',
            'system_branch': 'Nakuru Branch',
            'system_loan_officer': 'Officer Jane',
            'system_deposit_paid_jbl': Decimal('0'),
            'requisition_date': date(2026, 7, 23),
            'order_number': 'ORDER-001',
            'invoice_number': '9505',
            'invoice_date': date(2026, 7, 20),
            'invoice_amount': Decimal('54000'),
            'discount': Decimal('4500'),
            'payment': Decimal('6000'),
            'balance_due': Decimal('43500'),
            'actual_receipts': '6000',
            'lead_source': 'HomeBiogas',
            'repayment_date': '10TH',
            'repayment_tenor': '6',
            'payment_product': 'BIOGAS PREMIUM',
        }
        data.update(overrides)
        return JawabuFarmerMaster.objects.create(**data)

    def invoice_batch(self, farmer=None):
        batch = InvoiceUploadBatch.objects.create(
            original_filename='invoices.pdf',
            content_type='application/pdf',
            size=100,
            uploaded_by='Tester',
            drive_file_id='drive-pdf',
            drive_url='https://drive.test/invoices',
            status='parsed',
            total_pages=1,
            total_parsed=1,
            unmatched_count=1,
        )
        ParsedInvoice.objects.create(
            batch=batch,
            page=1,
            invoice_no='9505',
            invoice_date=date(2026, 7, 20),
            customer_name='Mary Wanjiku',
            customer_id='12345678',
            customer_phone='254712345678',
            invoice_amount=Decimal('54000'),
            discount=Decimal('4500'),
            payment=Decimal('6000'),
            balance_due=Decimal('43500'),
            status='matched' if farmer else 'unmatched',
            matched_farmer=farmer,
            matched_order_number=farmer.order_number if farmer else '',
        )
        return batch

    @patch('core.services.invoice_parser.parse_invoice_pdf_bytes')
    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_invoice_pool_upload_stores_drive_batch_and_parsed_rows(self, storage, parse_pdf):
        storage.return_value.upload.return_value = ('drive-id', 'https://drive.test/pdf')
        parse_pdf.return_value = ([
            {
                'page': 1,
                'invoice_no': '9505',
                'invoice_date': '20/07/2026',
                'customer_name': 'Mary Wanjiku',
                'customer_id': '12345678',
                'customer_phone': '254712345678',
                'invoice_amount': '54,000.00',
                'total_after_discount': '49,500.00',
                'discount': '4,500.00',
                'payment': '6,000.00',
                'balance_due': '43,500.00',
                'balance_due_check': 'OK',
            }
        ], 1)

        batch = ingest_invoice_upload_batch(
            pdf_bytes=b'%PDF-1.4',
            filename='invoices.pdf',
            uploaded_by='Tester',
        )

        self.assertEqual(batch.drive_file_id, 'drive-id')
        self.assertEqual(batch.total_parsed, 1)
        self.assertEqual(batch.unmatched_count, 1)
        parsed = batch.invoices.get()
        self.assertEqual(parsed.invoice_no, '9505')
        self.assertEqual(parsed.status, 'unmatched')

    def test_invoice_pool_endpoint_lists_batches_and_invoices_with_filters(self):
        farmer = self.farmer(order_number='ORDER-MATCHED')
        batch = self.invoice_batch(farmer)
        unmatched_batch = self.invoice_batch()

        response = self.client.get(reverse('portal_invoice_pool'), {'status': 'matched', 'search': '9505'})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['summary']['batch_count'], 2)
        self.assertEqual(data['summary']['invoice_count'], 2)
        self.assertEqual(data['summary']['matched_count'], 1)
        self.assertEqual(data['summary']['unmatched_count'], 1)
        self.assertEqual(len(data['invoices']), 1)
        self.assertEqual(data['invoices'][0]['status'], 'matched')
        self.assertEqual(data['invoices'][0]['matched_order_number'], 'ORDER-MATCHED')
        self.assertEqual(data['invoices'][0]['payment_readiness']['ready_count'], 1)
        self.assertEqual(data['invoices'][0]['payment_readiness']['blocked_count'], 0)
        batch_ids = {item['id'] for item in data['batches']}
        self.assertIn(str(batch.id), batch_ids)
        self.assertIn(str(unmatched_batch.id), batch_ids)

    def test_invoice_farmer_candidate_search(self):
        farmer = self.farmer(customer_name='Searchable Client', national_id='99887766')

        response = self.client.get(reverse('portal_invoice_farmer_candidates'), {'search': '99887766'})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['farmers'][0]['id'], str(farmer.id))
        self.assertTrue(data['farmers'][0]['has_invoice'])
        self.assertIn('Existing invoice', data['farmers'][0]['invoice_conflict_label'])

    def test_invoice_farmer_candidates_are_ranked_from_invoice_identity(self):
        id_match = self.farmer(customer_name='Different Name', national_id='11112222', primary_phone='254700000100')
        phone_match = self.farmer(customer_name='Other Name', national_id='33334444', primary_phone='254799888777')
        batch = self.invoice_batch()
        invoice = batch.invoices.get()
        invoice.customer_id = '11112222'
        invoice.customer_phone = '0799888777'
        invoice.save(update_fields=['customer_id', 'customer_phone', 'updated_at'])

        response = self.client.get(reverse('portal_invoice_farmer_candidates'), {
            'invoice_id': str(invoice.id),
            'search': 'different',
        })

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['farmers'][0]['id'], str(id_match.id))
        self.assertIn('ID match', data['farmers'][0]['match_reasons'])
        ids = {farmer['id'] for farmer in data['farmers']}
        self.assertIn(str(phone_match.id), ids)

    @patch('core.services.invoice_parser.sync_farmer_to_master_sheet', return_value=True)
    def test_manual_invoice_match_endpoint_links_invoice_to_farmer(self, mock_sync):
        farmer = self.farmer(
            order_number='ORDER-MANUAL',
            invoice_number='',
            invoice_date=None,
            invoice_amount=None,
            discount=None,
            payment=None,
            balance_due=None,
        )
        batch = self.invoice_batch()
        invoice = batch.invoices.get()

        response = self.client.post(
            reverse('portal_invoice_match', args=[str(invoice.id)]),
            data=json.dumps({'farmer_id': str(farmer.id), 'note': 'Verified by phone'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        invoice.refresh_from_db()
        farmer.refresh_from_db()
        self.assertEqual(invoice.status, 'matched')
        self.assertEqual(invoice.matched_farmer_id, farmer.id)
        self.assertEqual(invoice.matched_order_number, 'ORDER-MANUAL')
        self.assertEqual(farmer.invoice_number, '9505')
        self.assertEqual(farmer.balance_due, Decimal('43500'))
        self.assertIn('Verified by phone', invoice.review_notes)
        mock_sync.assert_called_once_with(farmer)

    @patch('core.services.invoice_parser.sync_farmer_to_master_sheet', return_value=True)
    def test_manual_invoice_unmatch_endpoint_clears_linked_farmer_invoice_fields(self, mock_sync):
        farmer = self.farmer(order_number='ORDER-MATCHED')
        batch = self.invoice_batch(farmer)
        invoice = batch.invoices.get()

        response = self.client.post(
            reverse('portal_invoice_unmatch', args=[str(invoice.id)]),
            data=json.dumps({'note': 'Wrong household'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        invoice.refresh_from_db()
        farmer.refresh_from_db()
        self.assertEqual(invoice.status, 'unmatched')
        self.assertIsNone(invoice.matched_farmer)
        self.assertEqual(invoice.matched_order_number, '')
        self.assertEqual(farmer.invoice_number, '')
        self.assertIsNone(farmer.balance_due)
        self.assertIn('Wrong household', invoice.review_notes)
        mock_sync.assert_called_once_with(farmer)

    def test_manual_invoice_ignore_endpoint_marks_invoice_ignored(self):
        batch = self.invoice_batch()
        invoice = batch.invoices.get()

        response = self.client.post(
            reverse('portal_invoice_ignore', args=[str(invoice.id)]),
            data=json.dumps({'note': 'Duplicate PDF page'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        invoice.refresh_from_db()
        batch.refresh_from_db()
        self.assertEqual(invoice.status, 'ignored')
        self.assertIn('Duplicate PDF page', invoice.review_notes)
        self.assertEqual(batch.unmatched_count, 0)

    def test_payment_template_layout_uses_visible_sheet_when_config_is_stale(self):
        workbook = load_workbook('requisition/HB_PAYMENT__89__7__machine_ready (1).xlsx')
        layout = payment_template_layout(workbook)

        self.assertEqual(layout.sheet_name, '#89')
        self.assertEqual(layout.header_row, 7)
        self.assertEqual(layout.data_start_row, 8)
        self.assertEqual(layout.totals_row, 12)
        self.assertEqual(layout.columns['cust_no'], 5)
        self.assertIn('header_row config=5 visible=7', layout.config_warnings)

    def test_payment_workbook_generation_uses_active_admin_uploaded_template(self):
        farmer = self.farmer(order_number='ORDER-UPLOADED')
        self.invoice_batch(farmer)

        with tempfile.TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                template = PaymentDocumentTemplate.objects.create(
                    name='Uploaded payment template',
                    is_active=True,
                )
                with open('requisition/HB_PAYMENT__89__7__machine_ready (1).xlsx', 'rb') as handle:
                    template.file.save('uploaded_payment_template.xlsx', File(handle), save=True)

                xlsx, summary = generate_payment_workbook('ORDER-UPLOADED')

        self.assertTrue(xlsx)
        self.assertEqual(summary['ready_count'], 1)

    def test_payment_workbook_generation_uses_drive_backed_template_when_local_file_is_missing(self):
        farmer = self.farmer(order_number='ORDER-DRIVE-TEMPLATE')
        self.invoice_batch(farmer)
        template = PaymentDocumentTemplate.objects.create(
            name='Drive payment template',
            is_active=True,
            drive_file_id='drive-template-id',
        )
        template_bytes = open('requisition/HB_PAYMENT__89__7__machine_ready (1).xlsx', 'rb').read()

        with patch(
            'core.services.payment_documents.workbook_source_from_template',
            return_value=io.BytesIO(template_bytes),
        ) as source:
            xlsx, summary = generate_payment_workbook('ORDER-DRIVE-TEMPLATE')

        source.assert_called_once()
        self.assertTrue(xlsx)
        self.assertEqual(summary['ready_count'], 1)

    def test_payment_readiness_blocks_missing_repayment_terms(self):
        farmer = self.farmer(repayment_date='', repayment_tenor='')
        self.invoice_batch(farmer)

        readiness = payment_readiness('ORDER-001')

        self.assertEqual(readiness['ready_count'], 0)
        self.assertEqual(readiness['blocked_count'], 1)
        self.assertIn('Repayment Dates', readiness['blocked'][0]['missing'])
        self.assertIn('Tenor', readiness['blocked'][0]['missing'])

    def test_payment_workbook_generation_uses_ready_farmer_and_preserves_signatures(self):
        farmer = self.farmer()
        self.invoice_batch(farmer)

        xlsx, summary = generate_payment_workbook('ORDER-001')
        path = 'tmp_payment_output.xlsx'
        self.addCleanup(lambda: __import__('pathlib').Path(path).exists() and __import__('pathlib').Path(path).unlink())
        with open(path, 'wb') as handle:
            handle.write(xlsx)
        ws = load_workbook(path, data_only=False)['#89']

        self.assertEqual(summary['ready_count'], 1)
        self.assertEqual(ws['C8'].value.date(), date(2026, 7, 23))
        self.assertEqual(ws['D8'].value, 'ORDER-001')
        self.assertEqual(ws['E8'].value, '15357')
        self.assertEqual(ws['G8'].value, 'MARY WANJIKU')
        self.assertEqual(ws['H8'].value, 'Mary Wanjiku')
        self.assertEqual(ws['K8'].value, 'Nakuru Branch')
        self.assertEqual(ws['L8'].value, 'Officer Jane')
        self.assertEqual(ws['M8'].value, 54000)
        self.assertTrue(str(ws['N8'].value or '').startswith('='))
        self.assertEqual(ws['O8'].value, 4500)
        self.assertEqual(ws['P8'].value, 6000)
        self.assertIsNone(ws['R8'].value)
        self.assertEqual(ws['S8'].value, '10TH')
        self.assertEqual(ws['T8'].value, '6')
        self.assertEqual(ws['U8'].value, 'BIOGAS PREMIUM')
        prepared_rows = [row for row in range(1, ws.max_row + 1) if ws.cell(row=row, column=3).value == 'PREPARED BY:']
        self.assertTrue(prepared_rows)
        self.assertGreater(prepared_rows[0], summary['totals_row'])

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_payment_preview_endpoint_returns_drive_document(self, storage):
        farmer = self.farmer()
        self.invoice_batch(farmer)
        storage.return_value.upload.return_value = ('drive-xlsx', 'https://drive.test/payment')

        response = self.client.post(reverse('portal_payment_document_preview', args=['ORDER-001']))

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['document']['drive_url'], 'https://drive.test/payment')
        self.assertEqual(PaymentDocument.objects.get().status, 'preview')

    def test_payment_preview_endpoint_returns_readiness_when_blocked(self):
        self.farmer(repayment_date='')

        response = self.client.post(reverse('portal_payment_document_preview', args=['ORDER-001']))

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['ok'])
        self.assertEqual(data['readiness']['blocked_count'], 1)

    def test_requisition_assignment_saves_payment_prerequisites(self):
        farmer = self.farmer(order_number='', repayment_date='', repayment_tenor='', payment_product='')

        response = self.client.post(
            reverse('portal_assign_order', args=[str(farmer.id)]),
            data=json.dumps({
                'order_number': 'ORDER-009',
                'requisition_date': '2026-07-23',
                'repayment_date': '15TH',
                'repayment_tenor': '9',
                'payment_product': 'BIOGAS',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        farmer.refresh_from_db()
        self.assertEqual(farmer.order_number, 'ORDER-009')
        self.assertEqual(farmer.repayment_date, '15TH')
        self.assertEqual(farmer.repayment_tenor, '9')
        self.assertEqual(farmer.payment_product, 'BIOGAS')
