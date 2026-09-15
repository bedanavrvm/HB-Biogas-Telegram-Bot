import io
import hashlib
import json
import zipfile
from xml.etree import ElementTree as ET

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.signing import TimestampSigner
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from unittest.mock import patch

from decimal import Decimal
from pypdf import PdfReader

from core.models import (
    InvoiceNameChangeLetterTemplate, InvoiceUploadBatch,
    JawabuFarmerMaster, ParsedInvoice,
)
from core.services.invoice_identity import (
    correct_sent_name_change, create_name_change, decide_identity_review,
    ensure_identity_review, mark_name_change_sent,
)

from core.services.invoice_name_change_letters import (
    InvoiceNameChangeLetterError,
    formatted_nairobi_date,
    inspect_template,
    render_docx,
    validate_template_file,
)
from core.services.docx_pdf_preview import render_docx_pdf


W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def synthetic_letter(*, omit_token='') -> bytes:
    tokens = {
        'date': ('{DA', 'TE}'),
        'invoice_name': ('{INVOICE ', 'NAME}'),
        'related_phone': ('{SPOUSE MOBILE NO}', ''),
        'applicant_name': ('{APPLICANT NAME}', ''),
        'applicant_phone': ('{APPLICANT MOBILE NO}', ''),
        'applicant_id': ('{APPLICANT ID NO}', ''),
        'sales_person': ('{SALES PERSON}', ''),
        'signatory': ('{SIGN', 'ATORY}'),
    }
    if omit_token:
        tokens[omit_token] = ('not supplied', '')

    def paragraph(parts):
        return '<w:p>' + ''.join(f'<w:r><w:t>{part}</w:t></w:r>' for part in parts if part) + '</w:p>'

    cells = ''.join(
        '<w:tc>' + paragraph(tokens[field]) + '</w:tc>'
        for field in ('invoice_name', 'related_phone', 'applicant_name', 'applicant_phone', 'applicant_id', 'sales_person')
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}"><w:body>'
        + paragraph(('Letter date: ',) + tokens['date'])
        + '<w:tbl><w:tr><w:tc>' + paragraph(('Invoice name',)) + '</w:tc></w:tr>'
        + '<w:tr>' + cells + '</w:tr></w:tbl>'
        + paragraph(('Signed by ',) + tokens['signatory'])
        + '<w:sectPr/></w:body></w:document>'
    ).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types/>')
        archive.writestr('word/document.xml', document)
        archive.writestr('word/header1.xml', b'unchanged-header')
        archive.writestr('word/media/image1.jpg', b'unchanged-logo')
    return output.getvalue()


class InvoiceNameChangeDocxTests(SimpleTestCase):
    def test_validates_split_run_placeholders_and_repeatable_row(self):
        data = synthetic_letter()
        inspection = inspect_template(data)
        self.assertEqual(inspection.row_index, 1)
        upload = SimpleUploadedFile('letter.docx', data)
        self.assertEqual(validate_template_file(upload), data)

    def test_renders_multiple_rows_without_altering_other_docx_parts(self):
        source = synthetic_letter()
        rendered = render_docx(
            source,
            globals_={'date': '18th August 2026', 'signatory': 'Operations User'},
            rows=[
                {
                    'invoice_name': 'JANE DOE', 'related_phone': '254700000001',
                    'applicant_name': 'MARY DOE', 'applicant_phone': '254700000002',
                    'applicant_id': '12345678', 'sales_person': 'JAWABU SALES ONE',
                },
                {
                    'invoice_name': 'JOHN DOE', 'related_phone': '254700000003',
                    'applicant_name': 'PETER DOE', 'applicant_phone': '254700000004',
                    'applicant_id': '87654321', 'sales_person': 'JAWABU SALES TWO',
                },
            ],
        )
        with zipfile.ZipFile(io.BytesIO(rendered)) as archive:
            self.assertEqual(archive.read('word/header1.xml'), b'unchanged-header')
            self.assertEqual(archive.read('word/media/image1.jpg'), b'unchanged-logo')
            root = ET.fromstring(archive.read('word/document.xml'))
        text = ''.join(node.text or '' for node in root.iter(f'{{{W}}}t'))
        self.assertIn('18th August 2026', text)
        self.assertIn('Operations User', text)
        self.assertIn('JANE DOE', text)
        self.assertIn('JOHN DOE', text)
        self.assertNotIn('{', text)
        self.assertEqual(len(list(root.iter(f'{{{W}}}tr'))), 3)

    def test_populated_docx_renders_as_a_real_pdf_with_governed_values(self):
        values = {
            'invoice_name': 'JANE DOE', 'related_phone': '254700000001',
            'applicant_name': 'MARY DOE', 'applicant_phone': '254700000002',
            'applicant_id': '12345678', 'sales_person': 'JAWABU SALES ONE',
        }
        rendered = render_docx(
            synthetic_letter(),
            globals_={'date': '15th September 2026', 'signatory': 'Operations User'},
            rows=[values],
        )

        preview = render_docx_pdf(
            rendered,
            expected_values=['15th September 2026', 'Operations User', *values.values()],
        )

        self.assertTrue(preview.startswith(b'%PDF'))
        text = ' '.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(preview)).pages)
        self.assertIn('JANE', text)
        self.assertIn('MARY', text)
        self.assertIn('Operations User', text)

    def test_missing_required_placeholder_is_rejected(self):
        with self.assertRaisesMessage(InvoiceNameChangeLetterError, 'sales_person'):
            inspect_template(synthetic_letter(omit_token='sales_person'))

    def test_nairobi_date_has_ordinal_suffix(self):
        from datetime import date
        self.assertEqual(formatted_nairobi_date(date(2026, 8, 11)), '11th August 2026')
        self.assertEqual(formatted_nairobi_date(date(2026, 8, 21)), '21st August 2026')


class InvoiceNameChangeArtifactTests(TestCase):
    def setUp(self):
        self.farmer = JawabuFarmerMaster.objects.create(
            customer_name='Mary Wanjiku', imab_customer_name='MARY WANJIKU',
            national_id='12345678', primary_phone='0712345678',
            hb_sales_person='Jawabu Sales One', customer_no='C-1',
            order_number='ORDER-1', status='active',
        )
        upload = InvoiceUploadBatch.objects.create(original_filename='invoice.pdf', status='parsed')
        invoice = ParsedInvoice.objects.create(
            batch=upload, invoice_no='INV-1', customer_name='Jane Wanjiku',
            customer_id='87654321', customer_phone='0700000000',
            balance_due=Decimal('43000'), status='matched', matched_farmer=self.farmer,
            matched_order_number=self.farmer.order_number,
        )
        review = ensure_identity_review(invoice, self.farmer)
        decide_identity_review(
            review, outcome='different_person_confirmed', actor='Operations',
            note='Confirmed spouse invoice.',
        )
        self.item = create_name_change(
            review, actor='Operations', relationship_type='spouse',
            related_name='Jane Wanjiku', related_national_id='87654321',
            related_phone='0700000000', attestation_note='Verified household relationship.',
            evidence_reference='approved-evidence-reference', client_request_id='batch-request-1',
        )
        self.template = InvoiceNameChangeLetterTemplate.objects.create(
            name='Approved letter', file='invoice_name_change_templates/letter.docx', is_active=True,
        )

    @override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='test-drive-root')
    @patch('core.services.invoice_name_change_letters.GoogleDriveMediaStorage.upload')
    @patch('core.services.invoice_name_change_letters._template_bytes')
    def test_generation_is_idempotent_versioned_and_sent_artifact_is_frozen(
        self, template_bytes, drive_upload,
    ):
        from core.services.invoice_name_change_letters import generate_letter_artifact
        template_bytes.return_value = synthetic_letter()
        drive_upload.return_value = ('drive-file-1', 'https://drive.example/letter-1')

        first, created = generate_letter_artifact(
            self.item.batch, actor='Operations User', client_request_id='generate-1',
        )
        replay, replay_created = generate_letter_artifact(
            self.item.batch, actor='Operations User', client_request_id='generate-1',
        )
        second, second_created = generate_letter_artifact(
            self.item.batch, actor='Operations User', client_request_id='generate-2',
        )

        self.assertTrue(created)
        self.assertFalse(replay_created)
        self.assertTrue(second_created)
        self.assertEqual(replay.id, first.id)
        self.assertEqual((first.version, second.version), (1, 2))
        self.assertEqual(first.payload_snapshot['signatory'], 'Operations User')
        self.assertEqual(len(first.payload_snapshot['rows']), 1)
        self.assertTrue(bytes(first.preview_file_content).startswith(b'%PDF'))
        self.assertEqual(first.preview_content_type, 'application/pdf')
        self.assertEqual(first.preview_checksum, hashlib.sha256(bytes(first.preview_file_content)).hexdigest())
        self.assertTrue(first.preview_filename.endswith('.pdf'))
        first.refresh_from_db()
        self.assertEqual(first.drive_file_id, 'drive-file-1')
        first.filename = 'tampered.docx'
        with self.assertRaisesMessage(Exception, 'artifacts are immutable'):
            first.save()
        first.refresh_from_db()
        first.preview_checksum = '0' * 64
        with self.assertRaisesMessage(Exception, 'artifacts are immutable'):
            first.save()
        first.refresh_from_db()

        batch = mark_name_change_sent(
            self.item.batch, actor='Operations User', artifact=second,
            sent_reference='HB-email-1',
        )
        self.assertEqual(batch.sent_artifact_id, second.id)
        self.assertEqual(batch.letter_checksum, second.checksum)
        self.assertEqual(batch.letter_file_reference, second.drive_url)
        self.assertEqual(batch.status, 'awaiting_replacements')

    def test_new_batch_rejects_manual_letter_reference(self):
        with self.assertRaisesMessage(ValueError, 'Generate the governed DOCX'):
            mark_name_change_sent(
                self.item.batch, actor='Operations',
                letter_reference='manual-drive-link', sent_reference='HB-email-1',
            )

    @override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False)
    @patch('core.services.invoice_name_change_letters._template_bytes')
    def test_protected_preview_endpoint_returns_webview_safe_document(self, template_bytes):
        from core.api.portal_views import portal_invoice_name_change_preview
        from core.services.invoice_name_change_letters import generate_letter_artifact

        template_bytes.return_value = synthetic_letter()
        artifact, _created = generate_letter_artifact(
            self.item.batch, actor='Operations User', client_request_id='preview-endpoint-1',
            publish_to_drive=False,
        )
        token = TimestampSigner(salt='portal-invoice-name-change-preview').sign(json.dumps({
            'artifact_id': str(artifact.id), 'user_id': '',
        }, separators=(',', ':')))

        response = portal_invoice_name_change_preview(
            RequestFactory().get(f'/api/portal/invoice-name-change-preview/{token}/'), token,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('text/html'))
        self.assertContains(response, 'data:image/jpeg;base64,')

    @patch('core.services.invoice_name_change_letters._template_bytes')
    def test_local_letter_can_be_sent_and_explicit_correction_preserves_old_artifact(self, template_bytes):
        from core.models import InvoiceNameChangeLetterArtifact
        from core.services.invoice_name_change_letters import generate_letter_artifact

        template_bytes.return_value = synthetic_letter()
        artifact, created = generate_letter_artifact(
            self.item.batch, actor='Operations User', client_request_id='local-letter-1',
            publish_to_drive=False,
        )
        self.assertTrue(created)
        self.assertFalse(artifact.drive_url)
        batch = mark_name_change_sent(
            self.item.batch, actor='Operations User', artifact=artifact,
            sent_reference='HB-email-local-1',
        )
        self.item.refresh_from_db()

        corrected = correct_sent_name_change(
            self.item, actor='Operations User', reason='Relationship was recorded incorrectly.',
            relationship_type='household_member', explanation='Applicant sibling.',
            expected_revision=self.item.revision,
            client_request_id='correct-sent-1',
        )
        replay = correct_sent_name_change(
            self.item, actor='Operations User', reason='Relationship was recorded incorrectly.',
            relationship_type='household_member', explanation='Applicant sibling.',
            expected_revision=self.item.revision,
            client_request_id='correct-sent-1',
        )

        batch.refresh_from_db()
        artifact.refresh_from_db()
        self.assertEqual(corrected.status, 'draft')
        self.assertEqual(replay.id, corrected.id)
        self.assertEqual(batch.status, 'draft')
        self.assertIsNone(batch.sent_artifact_id)
        self.assertEqual(batch.sent_reference, '')
        self.assertTrue(artifact.file_content)
        self.assertTrue(InvoiceNameChangeLetterArtifact.objects.filter(pk=artifact.pk).exists())
        self.assertTrue(
            self.farmer.pipeline_events.filter(action='invoice_name_change_sent_corrected').exists()
        )
