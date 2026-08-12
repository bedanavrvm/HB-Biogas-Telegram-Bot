import hashlib
import json
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from pypdf import PdfWriter

from core.models import (
    LoanOriginationApplication,
    OriginationDocumentTemplate,
    OriginationDocumentTemplateEvent,
    OriginationProductDefinition,
)
from core.services.origination_templates import (
    OriginationTemplateError,
    activate_template,
    create_template,
    load_active_template,
    publish_calibration,
    save_calibration_draft,
    validate_template_files,
)
from core.services.partnership_laf_preview import PartnershipLafPreviewError, render_pdf_page
from core.services.loan_origination import render_application_preview


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
        published = publish_calibration(template=template, revision=1, actor=self.maker)
        activated = activate_template(template, actor=self.maker)
        self.assertEqual(activated.status, OriginationDocumentTemplate.STATUS_ACTIVE)
        source, config = load_active_template(
            activated.document_type, version=1, expected_sha256=activated.source_sha256,
        )
        self.assertEqual(source, self.pdf)
        self.assertEqual(config['version'], 1)
        self.assertEqual(
            list(OriginationDocumentTemplateEvent.objects.filter(template=template).values_list('action', flat=True)),
            ['created', 'uploaded', 'calibration_published', 'activated'],
        )

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_activation_rejects_changed_drive_content(self, storage_class):
        storage = storage_class.return_value
        storage.upload.return_value = ('drive-template-1', 'https://drive.test/template-1')
        storage.download.return_value = self.pdf
        pdf_file = BytesIO(self.pdf)
        pdf_file.name = 'template.pdf'
        config_file = BytesIO(synthetic_config())
        config_file.name = 'config.json'
        template = create_template(
            pdf_file=pdf_file, config_file=config_file, name='Template', actor=self.maker,
        )
        publish_calibration(template=template, revision=1, actor=self.maker)
        storage.download.return_value = b'%PDF-changed'
        with self.assertRaises(OriginationTemplateError):
            activate_template(template, actor=self.checker)

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_draft_does_not_replace_published_configuration_until_publish(self, storage_class):
        storage = storage_class.return_value
        storage.upload.return_value = ('drive-template-2', 'https://drive.test/template-2')
        storage.download.return_value = self.pdf
        pdf_file = BytesIO(self.pdf); pdf_file.name = 'template.pdf'
        config_file = BytesIO(synthetic_config()); config_file.name = 'config.json'
        template = create_template(pdf_file=pdf_file, config_file=config_file, name='Template', actor=self.maker)
        first = publish_calibration(template=template, revision=1, actor=self.maker)
        changed = synthetic_config()
        changed_config = json.loads(changed)
        changed_config['field_overlay_manifest']['fields']['applicant']['box']['x'] = 25
        draft = save_calibration_draft(template=template, configuration=changed_config, actor=self.maker, expected_revision=first.revision)
        replayed = save_calibration_draft(template=template, configuration=changed_config, actor=self.maker, expected_revision=first.revision)
        self.assertEqual(replayed.pk, draft.pk)
        template.refresh_from_db()
        self.assertNotEqual(template.placement_config, draft.configuration)
        published = publish_calibration(template=template, revision=draft.revision, actor=self.maker)
        replayed_publish = publish_calibration(template=template, revision=draft.revision, actor=self.maker)
        self.assertEqual(replayed_publish.pk, published.pk)
        template.refresh_from_db()
        self.assertEqual(template.placement_config, published.configuration)

    def test_calibration_workspace_is_superuser_only(self):
        template = OriginationDocumentTemplate.objects.create(
            document_type='partnership_loan_application', name='Template', version=8,
            source_filename='template.pdf', source_sha256='a' * 64,
            source_byte_size=100, page_count=1, placement_config=json.loads(synthetic_config()),
            drive_file_id='drive-template-admin', created_by=self.maker,
        )
        url = reverse('admin:core_originationdocumenttemplate_calibrate', args=[template.pk])
        self.client.force_login(self.maker)
        self.assertEqual(self.client.get(url).status_code, 200)
        ordinary_staff = get_user_model().objects.create_user(
            'ordinary-staff', 'staff@example.test', 'x', is_staff=True,
        )
        self.client.force_login(ordinary_staff)
        self.assertIn(self.client.get(url).status_code, {302, 403})

    @patch('core.services.partnership_laf_preview.render_partnership_laf', return_value=b'%PDF-preview')
    def test_editable_application_preview_refreshes_published_calibration(self, renderer):
        digest = hashlib.sha256(self.pdf).hexdigest()
        product = OriginationProductDefinition.objects.create(
            product_key='calibration-refresh', name='Calibration refresh', version=1,
            form_schema={'fields': [{'key': 'applicant_first_name', 'label': 'Name'}]},
            signer_rules=[{'role': 'borrower'}], document_type='partnership_loan_application',
            document_template_name='template.pdf', document_template_version=1,
            document_template_sha256=digest, is_active=True,
        )
        template = OriginationDocumentTemplate.objects.create(
            document_type=product.document_type, name='Template', version=1,
            source_filename='template.pdf', source_sha256=digest,
            source_byte_size=len(self.pdf), page_count=1,
            placement_config=json.loads(synthetic_config()), drive_file_id='drive-refresh',
            status=OriginationDocumentTemplate.STATUS_ACTIVE, created_by=self.maker,
        )
        published_config = json.loads(synthetic_config())
        published_config['field_overlay_manifest']['fields']['applicant']['box']['x'] = 44
        published = template.configuration_revisions.create(
            revision=1, configuration=published_config, is_published=True, created_by=self.maker,
        )
        template.published_configuration_revision = published
        template.save(update_fields=['published_configuration_revision'])
        application = LoanOriginationApplication.objects.create(
            reference_number='ORG-SYNTHETIC-REFRESH', product_definition=product,
            officer=self.maker, status=LoanOriginationApplication.STATUS_DRAFT,
            template_configuration_snapshot=json.loads(synthetic_config()),
        )

        render_application_preview(application)

        application.refresh_from_db()
        self.assertEqual(application.template_configuration_snapshot, published_config)
        self.assertEqual(renderer.call_args.kwargs['configuration'], published_config)

    @patch('core.services.partnership_laf_preview.render_partnership_laf', return_value=b'%PDF-updated')
    @patch('core.services.loan_origination._published_template_configuration')
    def test_pre_signing_review_preview_refreshes_published_configuration(self, published, renderer):
        product = OriginationProductDefinition.objects.create(
            product_key='review-calibration-refresh', name='Review calibration refresh', version=1,
            form_schema={'fields': [{'key': 'applicant_first_name', 'label': 'Name'}]},
            signer_rules=[{'role': 'borrower'}], document_type='partnership_loan_application',
            document_template_name='template.pdf', document_template_version=1,
            document_template_sha256='b' * 64, is_active=True,
        )
        application = LoanOriginationApplication.objects.create(
            reference_number='ORG-SYNTHETIC-REVIEW', product_definition=product,
            officer=self.maker, branch='Synthetic Branch',
            schema_snapshot=product.form_schema, signer_rules_snapshot=product.signer_rules,
            template_configuration_snapshot={'old': True},
            status=LoanOriginationApplication.STATUS_READY_FOR_REVIEW,
            client_request_id='synthetic-review-refresh',
        )
        published.return_value = {'new': True}

        render_application_preview(application)

        application.refresh_from_db()
        self.assertEqual(application.template_configuration_snapshot, {'new': True})
        self.assertEqual(renderer.call_args.kwargs['configuration'], {'new': True})
