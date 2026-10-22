"""Native-download metadata at real views, with synthetic storage/authority I/O."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.signing import TimestampSigner
from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase

from core.api import portal_views


class PortalDownloadDeliveryTests(SimpleTestCase):
    def setUp(self):
        self.actor = SimpleNamespace(pk=1, is_active=True)
        users = MagicMock()
        users.objects.filter.return_value.first.return_value = self.actor
        self.enterContext(patch('django.contrib.auth.get_user_model', return_value=users))
        self.enterContext(patch('core.services.telegram_identity.user_access', return_value={'authorized': True}))
        self.enterContext(patch('core.api.portal_views._portal_capability_error', return_value=None))

    def token(self, salt, **payload):
        return TimestampSigner(salt=salt).sign(json.dumps({'user_id': '1', **payload}))

    def assert_delivery(self, view, token, filename, content):
        for method in ('GET', 'HEAD'):
            with self.subTest(method=method):
                response = view(RequestFactory().generic(method, '/synthetic-download/'), token)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Disposition'], f'attachment; filename="{filename}"')
                self.assertEqual(response['Content-Length'], str(len(content)))
                self.assertEqual(response['Access-Control-Allow-Origin'], 'https://web.telegram.org')
                self.assertIn('Content-Disposition', response['Access-Control-Expose-Headers'])
                self.assertEqual(response.content, content if method == 'GET' else b'')

    def test_report_download_get_and_head_have_named_web_compatible_metadata(self):
        self.enterContext(patch('core.services.workflow_capabilities.has_capability', return_value=True))
        self.enterContext(patch('core.services.portal_reporting.export_curated_report', return_value=b'synthetic-xlsx'))
        self.enterContext(patch('core.services.portal_reporting.record_curated_run'))
        token = self.token('portal-curated-report-download', preset='pipeline', filters={})
        self.assert_delivery(portal_views.portal_curated_report_download, token, 'portal-pipeline-report.xlsx', b'synthetic-xlsx')

    def payment_batch(self):
        batch = SimpleNamespace(current_document_id=1, payment_number='1', current_document=SimpleNamespace(
            filename='Payment-1.xlsx', file_content=b'synthetic-payment', content_type='application/octet-stream'))
        query = MagicMock()
        query.filter.return_value.select_related.return_value.first.return_value = batch
        self.enterContext(patch('core.api.portal_views._portal_payment_batch_queryset', return_value=query))
        return batch

    def test_payment_download_get_and_head_have_named_web_compatible_metadata(self):
        batch = self.payment_batch()
        self.assert_delivery(portal_views.portal_payment_workbook_download,
            self.token('portal-payment-workbook-download', batch_id='synthetic'),
            batch.current_document.filename, batch.current_document.file_content)

    def test_blank_retained_payment_filename_uses_a_named_workbook(self):
        batch = self.payment_batch()
        batch.current_document.filename = '  '
        self.assert_delivery(portal_views.portal_payment_workbook_download,
            self.token('portal-payment-workbook-download', batch_id='synthetic'),
            'Payment-1.xlsx', batch.current_document.file_content)

    def test_order_download_get_and_head_have_named_web_compatible_metadata(self):
        batch = SimpleNamespace(pk='synthetic', version=1, content_checksum='a'*64, order_number='HB-1',
            status='generated', farmer_ids=[], filename='Order-1.xlsx', file_content=b'synthetic-order')
        self.enterContext(patch('requisitions.services.resolve_order', return_value=batch))
        self.enterContext(patch('core.api.portal_views._farmers_for_batch', return_value=[]))
        self.enterContext(patch('core.api.portal_views._portal_farmers_scope_error', return_value=None))
        self.assert_delivery(portal_views.portal_requisition_download,
            self.token('portal-requisition-download', batch_id='synthetic', order_number='HB-1'),
            batch.filename, batch.file_content)

    def test_letter_download_get_and_head_have_named_web_compatible_metadata(self):
        artifact = SimpleNamespace(filename='Synthetic letter.docx', file_content=b'synthetic-letter',
            content_type='application/octet-stream', batch=SimpleNamespace(items=MagicMock()))
        artifact.batch.items.all.return_value = []
        query = self.enterContext(patch('core.models.InvoiceNameChangeLetterArtifact.objects'))
        query.select_related.return_value.prefetch_related.return_value.filter.return_value.first.return_value = artifact
        self.assert_delivery(portal_views.portal_invoice_name_change_download,
            self.token('portal-invoice-name-change-download', artifact_id='synthetic'), artifact.filename, artifact.file_content)

    def test_payment_permission_denial_has_no_attachment_or_bytes(self):
        self.payment_batch()
        with patch('core.api.portal_views._portal_capability_error', return_value=JsonResponse({'ok': False}, status=403)):
            response = portal_views.portal_payment_workbook_download(RequestFactory().get('/download/'),
                self.token('portal-payment-workbook-download', batch_id='synthetic'))
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('Content-Disposition', response)
        self.assertNotIn(b'synthetic-payment', response.content)
