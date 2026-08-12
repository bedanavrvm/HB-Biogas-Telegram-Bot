import hashlib
import json
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from pypdf import PdfWriter

from core.models import OriginationDocumentTemplate, OriginationDocumentTemplateEvent
from core.services.origination_templates import (
    OriginationTemplateError,
    activate_template,
    create_template,
    load_active_template,
    validate_template_files,
)
from core.services.partnership_laf_preview import PartnershipLafPreviewError, render_pdf_page


def synthetic_pdf() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    writer.write(output)
    return output.getvalue()


def synthetic_config() -> bytes:
    return json.dumps({
        'document_type': 'partnership_loan_application',
        'version': 1,
        'field_overlay_manifest': {'fields': {
            'applicant': {
                'context_key': 'applicant_first_name', 'page_number': 1,
                'box': {'x': 10, 'y': 10, 'width': 120, 'height': 20},
            },
        }},
    }).encode()


class OriginationTemplateValidationTests(SimpleTestCase):
    def test_validates_pdf_and_placement_manifest(self):
        pdf = synthetic_pdf()
        config, digest, pages = validate_template_files(pdf, synthetic_config())
        self.assertEqual(config['document_type'], 'partnership_loan_application')
        self.assertEqual(digest, hashlib.sha256(pdf).hexdigest())
        self.assertEqual(pages, 1)

    def test_rejects_manifest_page_outside_pdf(self):
        config = json.loads(synthetic_config())
        config['field_overlay_manifest']['fields']['applicant']['page_number'] = 2
        with self.assertRaises(OriginationTemplateError):
            validate_template_files(synthetic_pdf(), json.dumps(config).encode())

    def test_renders_webview_safe_preview_page(self):
        rendered, page_count = render_pdf_page(synthetic_pdf(), page_number=1)
        self.assertEqual(page_count, 1)
        self.assertTrue(rendered.startswith(b'\xff\xd8\xff'))

    def test_rejects_preview_page_outside_document(self):
        with self.assertRaises(PartnershipLafPreviewError):
            render_pdf_page(synthetic_pdf(), page_number=2)


@override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='shared-drive-root')
class OriginationTemplateLifecycleTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.maker = user_model.objects.create_superuser('template-maker', 'maker@example.test', 'x')
        self.checker = user_model.objects.create_superuser('template-checker', 'checker@example.test', 'x')
        self.pdf = synthetic_pdf()

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_upload_activate_and_load_are_drive_backed_and_audited(self, storage_class):
        storage = storage_class.return_value
        storage.upload.return_value = ('drive-template-1', 'https://drive.test/template-1')
        storage.download.return_value = self.pdf
        pdf_file = BytesIO(self.pdf)
        pdf_file.name = 'Jawabu Partnership LAF.pdf'
        config_file = BytesIO(synthetic_config())
        config_file.name = 'partnership_laf_template_config.json'

        template = create_template(
            pdf_file=pdf_file, config_file=config_file,
            name='Jawabu Partnership LAF', actor=self.maker,
        )
        self.assertEqual(template.status, OriginationDocumentTemplate.STATUS_READY)
        self.assertEqual(template.drive_file_id, 'drive-template-1')
        activated = activate_template(template, actor=self.maker)
        self.assertEqual(activated.status, OriginationDocumentTemplate.STATUS_ACTIVE)
        source, config = load_active_template(
            activated.document_type, version=1, expected_sha256=activated.source_sha256,
        )
        self.assertEqual(source, self.pdf)
        self.assertEqual(config['version'], 1)
        self.assertEqual(
            list(OriginationDocumentTemplateEvent.objects.filter(template=template).values_list('action', flat=True)),
            ['created', 'uploaded', 'activated'],
        )

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_activation_rejects_changed_drive_content(self, storage_class):
        storage = storage_class.return_value
        storage.upload.return_value = ('drive-template-1', 'https://drive.test/template-1')
        storage.download.return_value = b'%PDF-changed'
        pdf_file = BytesIO(self.pdf)
        pdf_file.name = 'template.pdf'
        config_file = BytesIO(synthetic_config())
        config_file.name = 'config.json'
        template = create_template(
            pdf_file=pdf_file, config_file=config_file, name='Template', actor=self.maker,
        )
        with self.assertRaises(OriginationTemplateError):
            activate_template(template, actor=self.checker)
