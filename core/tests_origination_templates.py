import hashlib
import json
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader, PdfWriter
from unfold.widgets import UnfoldAdminFileFieldWidget, UnfoldAdminSelectWidget

from core.models import (
    LoanOriginationApplication,
    OriginationDocumentTemplate,
    OriginationDocumentTemplateEvent,
    OriginationProductDefinition,
    OriginationTemplateConfigurationRevision,
)
from core.services.origination_templates import (
    OriginationTemplateError,
    activate_template,
    clone_product_version,
    create_template,
    initial_template_configuration,
    load_active_template,
    publish_calibration,
    publish_product_template,
    replace_draft_template,
    save_calibration_draft,
    validate_template_configuration,
    validate_template_files,
    validate_template_pdf,
)
from core.services.partnership_laf_preview import (
    PartnershipLafPreviewError,
    render_pdf_page,
    render_template,
)
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

    def test_renderer_uses_global_formatting_when_field_has_no_override(self):
        config = json.loads(synthetic_config())
        config['field_overlay_manifest']['defaults'] = {
            'font': 'Helvetica',
            'font_size': 12,
            'min_font_size': 6,
            'text_case': 'uppercase',
            'align': 'center',
            'vertical_align': 'center',
            'fit': 'shrink',
            'padding': {'x': 1, 'y': 1},
        }

        rendered = render_template(
            synthetic_pdf(), config, {'applicant_first_name': 'Mixed Case'},
        )
        text = PdfReader(BytesIO(rendered)).pages[0].extract_text()

        self.assertIn('MIXED CASE', text)

    def test_renderer_populates_repeatable_asset_table_and_decimal_values(self):
        config = json.loads(synthetic_config())
        config['field_overlay_manifest']['fields'] = {
            'secured_assets': {
                'context_key': 'secured_assets', 'render_as': 'repeating_table',
                'page_number': 1, 'units': 'pt',
                'box': {'x': 40, 'y': 120, 'width': 520, 'height': 220},
                'rows': 11,
                'columns': [
                    {'key': 'description', 'x_ratio': 0, 'width_ratio': .5},
                    {'key': 'estimated_value', 'x_ratio': .5, 'width_ratio': .5, 'value_format': 'money'},
                ],
            },
        }
        rendered = render_template(synthetic_pdf(), config, {'secured_assets': [
            {'description': 'Synthetic cooker', 'estimated_value': '12500'},
            {'description': 'Synthetic television', 'estimated_value': '8000.50'},
        ]})
        text = PdfReader(BytesIO(rendered)).pages[0].extract_text()
        self.assertIn('Synthetic cooker', text)
        self.assertIn('12,500.00', text)
        self.assertIn('Synthetic television', text)


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

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_calibration_request_id_replays_once_and_rejects_changed_content(self, storage_class):
        storage_class.return_value.upload.return_value = (
            'drive-idempotent-template', 'https://drive.test/idempotent-template',
        )
        storage_class.return_value.download.return_value = self.pdf
        pdf_file = BytesIO(self.pdf); pdf_file.name = 'idempotent.pdf'
        config_file = BytesIO(synthetic_config()); config_file.name = 'config.json'
        template = create_template(
            pdf_file=pdf_file, config_file=config_file,
            name='Idempotent Template', actor=self.maker,
        )
        configuration = json.loads(synthetic_config())

        first = save_calibration_draft(
            template=template, configuration=configuration, actor=self.maker,
            expected_revision=1, client_request_id='save-request-1',
        )
        replay = save_calibration_draft(
            template=template, configuration=configuration, actor=self.maker,
            expected_revision=1, client_request_id='save-request-1',
        )

        self.assertEqual(replay.pk, first.pk)
        events = template.events.filter(action='calibration_saved')
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.get().metadata['request_id'], 'save-request-1')
        changed = json.loads(synthetic_config())
        changed['field_overlay_manifest']['fields']['applicant']['box']['x'] = 55
        with self.assertRaisesMessage(OriginationTemplateError, 'already used for different content'):
            save_calibration_draft(
                template=template, configuration=changed, actor=self.maker,
                expected_revision=first.revision, client_request_id='save-request-1',
            )

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_publish_request_id_creates_one_published_event(self, storage_class):
        storage_class.return_value.upload.return_value = (
            'drive-idempotent-publish', 'https://drive.test/idempotent-publish',
        )
        storage_class.return_value.download.return_value = self.pdf
        pdf_file = BytesIO(self.pdf); pdf_file.name = 'publish.pdf'
        config_file = BytesIO(synthetic_config()); config_file.name = 'config.json'
        template = create_template(
            pdf_file=pdf_file, config_file=config_file,
            name='Publish Once', actor=self.maker,
        )

        first = publish_calibration(
            template=template, revision=1, actor=self.maker,
            client_request_id='publish-request-1',
        )
        replay = publish_calibration(
            template=template, revision=1, actor=self.maker,
            client_request_id='publish-request-1',
        )

        self.assertEqual(replay.pk, first.pk)
        events = template.events.filter(action='calibration_published')
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.get().metadata['request_id'], 'publish-request-1')

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


@override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='shared-drive-root')
class MultiProductOriginationTemplateTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            'product-builder', 'builder@example.test', 'x',
        )
        self.pdf = synthetic_pdf()
        self.product = OriginationProductDefinition.objects.create(
            product_key='dairy-capital', name='Dairy Working Capital', version=1,
            form_schema={
                'sections': [
                    {'key': 'farm', 'label': 'Farm', 'help_text': 'Farm details'},
                    {'key': 'facility', 'label': 'Facility', 'help_text': 'Loan request'},
                ],
                'fields': [
                    {
                        'key': 'farmer_name', 'label': 'Farmer name', 'type': 'text',
                        'section_key': 'farm', 'required': True, 'width': 'full',
                    },
                    {
                        'key': 'requested_amount', 'label': 'Requested amount', 'type': 'money',
                        'section_key': 'facility', 'required': True, 'width': 'half',
                    },
                ],
            },
            signer_rules=[{
                'role': 'borrower', 'required': True,
                'slots': [{'key': 'acceptance', 'label': 'Borrower acceptance', 'type': 'signature', 'required': True}],
            }],
            document_type='dairy-capital', document_template_version=1,
            lifecycle_status=OriginationProductDefinition.STATUS_DRAFT,
            created_by=self.user,
        )

    def calibrated_configuration(self):
        config = initial_template_configuration(self.product)
        config['field_overlay_manifest']['fields'] = {
            'farmer_name': {
                'context_key': 'farmer_name', 'page_number': 1, 'units': 'pt',
                'box': {'x': 20, 'y': 700, 'width': 180, 'height': 16},
            },
            'requested_amount': {
                'context_key': 'requested_amount', 'page_number': 1, 'units': 'pt',
                'box': {'x': 20, 'y': 660, 'width': 100, 'height': 16},
            },
        }
        config['signature_overlay_manifest']['slots'] = {
            'borrower.acceptance': {
                'role': 'borrower', 'slot_key': 'acceptance', 'slot_type': 'signature',
                'label': 'Borrower acceptance', 'page_number': 1, 'units': 'pt',
                'box': {'x': 20, 'y': 80, 'width': 180, 'height': 35},
            },
        }
        return config

    def test_calibration_new_items_use_page_center_instead_of_bottom_corner(self):
        source = (
            Path(settings.BASE_DIR) / 'core/static/admin/origination_calibration.js'
        ).read_text(encoding='utf-8')

        self.assertIn('const centeredBox = (width, height) =>', source)
        self.assertIn('x: rounded((pageWidth - boxWidth) / 2)', source)
        self.assertIn('y: rounded((pageHeight - boxHeight) / 2)', source)
        self.assertNotIn('box: { x: 40, y: 40', source)

    def test_global_formatting_applies_to_current_and_future_fields_with_preview(self):
        source = (
            Path(settings.BASE_DIR) / 'core/static/admin/origination_calibration.js'
        ).read_text(encoding='utf-8')
        template = (
            Path(settings.BASE_DIR)
            / 'core/templates/admin/core/originationdocumenttemplate/calibrate.html'
        ).read_text(encoding='utf-8')

        self.assertIn('const globalFieldFormatting = () =>', source)
        self.assertIn("render_as: 'text', ...globalFieldFormatting()", source)
        self.assertIn('configuration.field_overlay_manifest.defaults = copy(values)', source)
        self.assertIn("mode = 'filled'", source)
        self.assertIn('await renderPage()', source)
        self.assertIn('default for fields added later', template)
        self.assertIn('origination_calibration.js\' %}?v=11', template)

    def test_pdf_only_onboarding_derives_product_contract(self):
        digest, pages = validate_template_pdf(self.pdf)
        config = initial_template_configuration(self.product)

        self.assertEqual(pages, 1)
        self.assertEqual(digest, hashlib.sha256(self.pdf).hexdigest())
        self.assertEqual(config['document_type'], self.product.document_type)
        self.assertEqual(config['version'], self.product.version)
        self.assertEqual(config['field_overlay_manifest']['fields'], {})
        self.assertIn('farmer_name', config['sample_context'])

    def test_admin_creates_visual_product_draft_without_raw_template_identifiers(self):
        self.client.force_login(self.user)
        add_url = reverse('admin:core_originationproductdefinition_add')
        response = self.client.get(add_url)
        self.assertContains(response, 'id="origination-product-builder"')
        self.assertEqual(response.context['adminform'].readonly_fields, ())
        self.assertIsInstance(
            response.context['adminform'].form.fields['product_version'].widget,
            UnfoldAdminSelectWidget,
        )
        self.assertIsInstance(
            response.context['adminform'].form.fields['laf_pdf'].widget,
            UnfoldAdminFileFieldWidget,
        )
        self.assertContains(response, 'LAF PDF template')
        self.assertContains(response, 'Product and LAF')
        self.assertContains(response, 'Assign and align fields on the LAF')
        response = self.client.post(add_url, {
            'product_key': 'solar-upgrade',
            'name': 'Solar Upgrade Loan',
            'form_schema': json.dumps({
                'sections': [{'key': 'customer', 'label': 'Customer'}],
                'fields': [{
                    'key': 'customer_name', 'label': 'Customer name', 'type': 'text',
                    'section_key': 'customer', 'required': True, 'width': 'full',
                }],
            }),
            'signer_rules': json.dumps([{
                'role': 'borrower', 'required': True,
                'slots': [{'key': 'signature', 'label': 'Signature', 'type': 'signature', 'required': True}],
            }]),
            '_save': 'Save',
        })
        self.assertEqual(response.status_code, 302)
        product = OriginationProductDefinition.objects.get(product_key='solar-upgrade')
        self.assertEqual(product.document_type, 'solar-upgrade')
        self.assertEqual(product.lifecycle_status, product.STATUS_DRAFT)
        self.assertEqual(product.document_template_sha256, '')

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_admin_product_builder_uploads_laf_and_opens_alignment_workspace(self, storage_class):
        storage_class.return_value.upload.return_value = (
            'drive-integrated-laf', 'https://drive.test/integrated-laf',
        )
        storage_class.return_value.download.return_value = self.pdf
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('admin:core_originationproductdefinition_add'),
            {
                'product_key': 'integrated-laf',
                'name': 'Integrated LAF Loan',
                'form_schema': json.dumps({
                    'sections': [{'key': 'customer', 'label': 'Customer'}],
                    'fields': [{
                        'key': 'customer_name', 'label': 'Customer name', 'type': 'text',
                        'section_key': 'customer', 'required': True, 'width': 'full',
                    }],
                }),
                'signer_rules': json.dumps([{
                    'role': 'borrower', 'required': True,
                    'slots': [{
                        'key': 'signature', 'label': 'Signature',
                        'type': 'signature', 'required': True,
                    }],
                }]),
                'laf_pdf': SimpleUploadedFile(
                    'integrated-laf.pdf', self.pdf, content_type='application/pdf',
                ),
                '_save': 'Save',
            },
        )

        product = OriginationProductDefinition.objects.get(product_key='integrated-laf')
        template = product.document_templates.get()
        self.assertRedirects(
            response,
            reverse(
                'admin:core_originationdocumenttemplate_calibrate', args=[template.pk],
            ),
            fetch_redirect_response=False,
        )
        self.assertEqual(template.drive_file_id, 'drive-integrated-laf')
        self.assertEqual(
            template.placement_config['sample_context']['customer_name'],
            'Customer name',
        )
        self.assertEqual(
            list(template.events.values_list('action', flat=True)),
            ['created', 'uploaded'],
        )
        state_response = self.client.get(reverse(
            'admin:core_originationdocumenttemplate_calibration_state',
            args=[template.pk],
        ))
        state = state_response.json()
        self.assertEqual(state_response.status_code, 200)
        self.assertIn('customer_name', {item['key'] for item in state['context_keys']})
        customer_field = next(item for item in state['context_keys'] if item['key'] == 'customer_name')
        self.assertTrue(customer_field['required'])
        self.assertEqual(customer_field['section_key'], 'customer')
        self.assertIn(
            'borrower.signature',
            {
                f"{item['role']}.{item['slot_key']}"
                for item in state['signature_slots']
            },
        )

    def test_admin_product_builder_allows_audited_draft_laf_replacement(self):
        template = OriginationDocumentTemplate.objects.create(
            product_definition=self.product,
            document_type=self.product.document_type,
            name='Dairy LAF',
            version=self.product.version,
            source_filename='dairy-laf.pdf',
            source_sha256='f' * 64,
            source_byte_size=100,
            page_count=1,
            placement_config=initial_template_configuration(self.product),
            drive_file_id='drive-existing-laf',
            drive_url='https://drive.test/existing-laf',
            created_by=self.user,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse(
            'admin:core_originationproductdefinition_change', args=[self.product.pk],
        ))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['adminform'].form.fields['laf_pdf'].disabled)
        self.assertContains(
            response,
            'current draft template is retained as immutable history',
        )
        self.assertContains(response, 'Open alignment builder')
        self.assertContains(response, reverse(
            'admin:core_originationdocumenttemplate_calibrate', args=[template.pk],
        ))

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_existing_draft_product_can_upload_laf_from_its_builder(self, storage_class):
        storage_class.return_value.upload.return_value = (
            'drive-existing-draft', 'https://drive.test/existing-draft',
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse(
                'admin:core_originationproductdefinition_change', args=[self.product.pk],
            ),
            {
                'product_version': '',
                'product_key': self.product.product_key,
                'name': self.product.name,
                'form_schema': json.dumps(self.product.form_schema),
                'signer_rules': json.dumps(self.product.signer_rules),
                'laf_pdf': SimpleUploadedFile(
                    'dairy-laf.pdf', self.pdf, content_type='application/pdf',
                ),
                '_save': 'Save',
            },
        )

        template = self.product.document_templates.get()
        self.assertRedirects(
            response,
            reverse(
                'admin:core_originationdocumenttemplate_calibrate', args=[template.pk],
            ),
            fetch_redirect_response=False,
        )
        self.assertEqual(template.drive_file_id, 'drive-existing-draft')

    def test_admin_template_add_is_compact_and_explains_eligible_drafts(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('admin:core_originationdocumenttemplate_add'),
            {'product_definition': str(self.product.pk)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Upload the PDF for a draft loan form')
        self.assertContains(response, 'Loan form definition')
        self.assertContains(response, 'Dairy Working Capital - loan form v1')
        self.assertContains(response, f'value="{self.product.pk}" selected')
        self.assertEqual(
            tuple(response.context['adminform'].form.fields),
            (
                'product_definition', 'document_key', 'name', 'document_role',
                'inclusion_mode', 'display_order', 'officer_selectable',
                'default_selected', 'applicability_rule', 'form_schema',
                'signer_rules', 'pdf_file',
            ),
        )
        self.assertEqual(response.context['adminform'].readonly_fields, ())
        self.assertIsInstance(
            response.context['adminform'].form.fields['product_definition'].widget,
            UnfoldAdminSelectWidget,
        )
        self.assertIsInstance(
            response.context['adminform'].form.fields['pdf_file'].widget,
            UnfoldAdminFileFieldWidget,
        )
        self.assertContains(response, 'file_upload')

    def test_admin_template_add_links_to_definition_builder_when_no_draft_is_eligible(self):
        self.product.lifecycle_status = OriginationProductDefinition.STATUS_PUBLISHED
        self.product.save(update_fields=['lifecycle_status'])
        self.client.force_login(self.user)

        response = self.client.get(reverse('admin:core_originationdocumenttemplate_add'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No draft loan form is ready for a PDF')
        self.assertContains(response, reverse('admin:core_originationproductdefinition_add'))
        self.assertFalse(
            response.context['adminform'].form.fields['product_definition'].queryset.exists(),
        )

    def test_admin_template_dropdown_allows_supporting_document_after_primary_template(self):
        template = OriginationDocumentTemplate.objects.create(
            product_definition=self.product,
            document_type=self.product.document_type,
            name='Existing PDF',
            version=self.product.version,
            source_filename='existing.pdf',
            source_sha256='e' * 64,
            source_byte_size=100,
            page_count=1,
            placement_config=initial_template_configuration(self.product),
            created_by=self.user,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('admin:core_originationdocumenttemplate_add'))

        self.assertContains(response, 'Dairy Working Capital - loan form v1')
        self.assertTrue(response.context['adminform'].form.fields['product_definition'].queryset.exists())

        change_response = self.client.get(
            reverse('admin:core_originationdocumenttemplate_change', args=[template.pk]),
        )
        self.assertEqual(change_response.status_code, 200)
        self.assertContains(change_response, 'Source PDF')
        self.assertContains(change_response, 'Published calibration')

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_admin_template_upload_requires_only_draft_product_and_pdf(self, storage_class):
        storage_class.return_value.upload.return_value = ('drive-admin-pdf', 'https://drive.test/admin-pdf')
        self.client.force_login(self.user)
        response = self.client.post(reverse('admin:core_originationdocumenttemplate_add'), {
            'product_definition': str(self.product.pk),
            'name': 'Dairy Admin PDF',
            'pdf_file': SimpleUploadedFile('dairy-admin.pdf', self.pdf, content_type='application/pdf'),
            '_save': 'Save',
        })

        self.assertEqual(response.status_code, 302)
        template = OriginationDocumentTemplate.objects.get(product_definition=self.product)
        self.assertEqual(template.document_type, self.product.document_type)
        self.assertEqual(template.version, self.product.version)
        self.assertEqual(template.placement_config['field_overlay_manifest']['fields'], {})

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_admin_uploads_global_supporting_template_without_product_owner(self, storage_class):
        storage_class.return_value.upload.return_value = ('drive-shared-guarantor', 'https://drive.test/shared')
        self.client.force_login(self.user)

        response = self.client.post(reverse('admin:core_originationdocumenttemplate_add'), {
            'product_definition': '',
            'document_key': 'shared_guarantor',
            'document_role': OriginationDocumentTemplate.ROLE_SUPPORTING,
            'inclusion_mode': OriginationDocumentTemplate.INCLUDE_REQUIRED,
            'display_order': 20,
            'name': 'Shared guarantor form',
            'pdf_file': SimpleUploadedFile('guarantor.pdf', self.pdf, content_type='application/pdf'),
            '_save': 'Save',
        })

        template = OriginationDocumentTemplate.objects.get(document_key='shared_guarantor')
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(template.product_definition_id)
        self.assertEqual(template.document_type, 'shared_guarantor')
        self.assertEqual(template.document_role, template.ROLE_SUPPORTING)
        self.assertEqual(template.form_schema, {'_revision': 0, 'sections': [], 'fields': []})

    @patch('core.services.compliance_audit.record_event')
    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_publish_action_binds_template_and_activates_product_atomically(self, storage_class, audit):
        storage = storage_class.return_value
        storage.upload.return_value = ('drive-dairy-v1', 'https://drive.test/dairy-v1')
        storage.download.return_value = self.pdf
        pdf_file = BytesIO(self.pdf); pdf_file.name = 'dairy-capital.pdf'
        template = create_template(
            pdf_file=pdf_file, product_definition=self.product,
            name='Dairy Capital Agreement', actor=self.user,
        )
        draft = save_calibration_draft(
            template=template, configuration=self.calibrated_configuration(),
            actor=self.user, expected_revision=1,
        )

        with CaptureQueriesContext(connection) as queries:
            product, template, published = publish_product_template(
                template=template, revision=draft.revision, actor=self.user,
            )

        product.refresh_from_db(); template.refresh_from_db()
        self.assertTrue(product.is_active)
        self.assertEqual(product.lifecycle_status, product.STATUS_PUBLISHED)
        self.assertEqual(product.document_template_sha256, hashlib.sha256(self.pdf).hexdigest())
        self.assertEqual(template.status, template.STATUS_ACTIVE)
        self.assertEqual(template.published_configuration_revision_id, published.pk)
        audit.assert_called_once()
        template_reads = [
            item['sql'] for item in queries.captured_queries
            if 'FROM "core_originationdocumenttemplate"' in item['sql']
        ]
        self.assertTrue(template_reads)
        self.assertNotIn(
            'JOIN "core_originationproductdefinition"', template_reads[0],
            'The locked template query must not outer-join its nullable product relation.',
        )

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_draft_save_allows_incomplete_mapping_but_publish_validation_does_not(self, storage_class):
        storage_class.return_value.upload.return_value = ('drive-dairy-draft', 'https://drive.test/draft')
        storage_class.return_value.download.return_value = self.pdf
        pdf_file = BytesIO(self.pdf); pdf_file.name = 'draft.pdf'
        template = create_template(
            pdf_file=pdf_file, product_definition=self.product,
            name='Draft', actor=self.user,
        )
        incomplete = initial_template_configuration(self.product)
        saved = save_calibration_draft(
            template=template, configuration=incomplete,
            actor=self.user, expected_revision=1,
        )

        self.assertEqual(saved.revision, 2)
        with self.assertRaisesRegex(OriginationTemplateError, 'At least one calibrated field'):
            validate_template_configuration(incomplete, template=template, require_complete=True)

    def test_clone_creates_editable_successor_without_mutating_source(self):
        self.product.lifecycle_status = self.product.STATUS_PUBLISHED
        self.product.is_active = True
        self.product.document_template_name = 'Dairy Capital Agreement'
        self.product.document_template_sha256 = 'a' * 64
        self.product.save()

        clone = clone_product_version(self.product, actor=self.user)

        self.assertEqual(clone.version, 2)
        self.assertEqual(clone.lifecycle_status, clone.STATUS_DRAFT)
        self.assertEqual(clone.supersedes_id, self.product.pk)
        self.assertEqual(clone.form_schema, self.product.form_schema)
        self.assertFalse(clone.is_active)
        self.product.refresh_from_db()
        self.assertTrue(self.product.is_active)

    def test_clone_inherits_published_pdf_and_alignment_idempotently(self):
        config = self.calibrated_configuration()
        template = OriginationDocumentTemplate.objects.create(
            product_definition=self.product,
            document_type=self.product.document_type,
            name='Dairy v1',
            version=1,
            status=OriginationDocumentTemplate.STATUS_ACTIVE,
            source_filename='dairy-v1.pdf',
            source_sha256='a' * 64,
            source_byte_size=len(self.pdf),
            page_count=1,
            placement_config=config,
            drive_file_id='drive-shared-pdf',
            drive_url='https://drive.test/shared-pdf',
            created_by=self.user,
        )
        source_revision = OriginationTemplateConfigurationRevision.objects.create(
            template=template,
            revision=1,
            configuration=config,
            is_published=True,
            created_by=self.user,
            published_at=timezone.now(),
        )
        template.published_configuration_revision = source_revision
        template.save(update_fields=['published_configuration_revision'])
        self.product.lifecycle_status = self.product.STATUS_PUBLISHED
        self.product.is_active = True
        self.product.document_template_version = 1
        self.product.document_template_sha256 = template.source_sha256
        self.product.save()

        clone = clone_product_version(self.product, actor=self.user)
        replay = clone_product_version(self.product, actor=self.user)

        self.assertEqual(replay.pk, clone.pk)
        self.assertEqual(clone.document_templates.count(), 1)
        inherited = clone.document_templates.get()
        self.assertEqual(inherited.status, inherited.STATUS_READY)
        self.assertEqual(inherited.drive_file_id, template.drive_file_id)
        self.assertEqual(inherited.source_sha256, template.source_sha256)
        self.assertEqual(inherited.placement_config['version'], 2)
        self.assertEqual(
            inherited.placement_config['field_overlay_manifest']['fields'],
            config['field_overlay_manifest']['fields'],
        )
        self.assertIsNone(inherited.published_configuration_revision_id)
        self.assertEqual(inherited.configuration_revisions.get().revision, 1)
        self.assertEqual(
            list(inherited.events.values_list('action', flat=True)),
            ['version_inherited'],
        )

    def test_compact_admin_list_and_history_keep_old_versions_accessible(self):
        self.product.lifecycle_status = self.product.STATUS_PUBLISHED
        self.product.is_active = True
        self.product.save(update_fields=['lifecycle_status', 'is_active'])
        clone = clone_product_version(self.product, actor=self.user)
        self.client.force_login(self.user)

        response = self.client.get(reverse(
            'admin:core_originationproductdefinition_changelist',
        ))

        self.assertEqual(response.status_code, 200)
        product_rows = list(response.context['cl'].queryset.filter(
            product_key=self.product.product_key,
        ))
        self.assertEqual(product_rows, [clone])
        self.assertContains(response, 'Draft v2 · Live v1')
        history = self.client.get(reverse(
            'admin:core_originationproductdefinition_version_history',
            args=[clone.pk],
        ))
        self.assertEqual(history.status_code, 200)
        self.assertEqual(len(history.context['rows']), 2)
        self.assertContains(history, 'v2')
        self.assertContains(history, 'v1')
        historical = self.client.get(reverse(
            'admin:core_originationproductdefinition_change', args=[self.product.pk],
        ))
        self.assertEqual(historical.status_code, 200)

    def test_direct_successor_action_is_post_only_and_opens_inherited_alignment(self):
        config = self.calibrated_configuration()
        template = OriginationDocumentTemplate.objects.create(
            product_definition=self.product,
            document_type=self.product.document_type,
            name='Dairy v1', version=1,
            status=OriginationDocumentTemplate.STATUS_ACTIVE,
            source_filename='dairy.pdf', source_sha256='c' * 64,
            source_byte_size=len(self.pdf), page_count=1,
            placement_config=config, drive_file_id='drive-current',
            drive_url='https://drive.test/current', created_by=self.user,
        )
        revision = OriginationTemplateConfigurationRevision.objects.create(
            template=template, revision=1, configuration=config,
            is_published=True, created_by=self.user, published_at=timezone.now(),
        )
        template.published_configuration_revision = revision
        template.save(update_fields=['published_configuration_revision'])
        self.product.lifecycle_status = self.product.STATUS_PUBLISHED
        self.product.is_active = True
        self.product.document_template_sha256 = template.source_sha256
        self.product.save()
        self.client.force_login(self.user)
        url = reverse(
            'admin:core_originationproductdefinition_create_next_version',
            args=[self.product.pk],
        )

        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url)

        clone = OriginationProductDefinition.objects.get(
            product_key=self.product.product_key, lifecycle_status='draft',
        )
        inherited = clone.document_templates.get()
        self.assertRedirects(
            response,
            reverse(
                'admin:core_originationdocumenttemplate_calibrate',
                args=[inherited.pk],
            ),
            fetch_redirect_response=False,
        )

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_replacing_inherited_pdf_retires_old_only_after_upload(self, storage_class):
        inherited = OriginationDocumentTemplate.objects.create(
            product_definition=self.product,
            document_type=self.product.document_type,
            name='Inherited', version=1,
            source_filename='old.pdf', source_sha256='d' * 64,
            source_byte_size=100, page_count=1,
            placement_config=self.calibrated_configuration(),
            drive_file_id='drive-old', drive_url='https://drive.test/old',
            created_by=self.user,
        )
        storage_class.return_value.upload.return_value = (
            'drive-new', 'https://drive.test/new',
        )
        replacement_pdf = BytesIO(synthetic_pdf())
        replacement_pdf.name = 'replacement.pdf'

        replacement = replace_draft_template(
            product_definition=self.product, pdf_file=replacement_pdf,
            name='Replacement', actor=self.user,
        )

        inherited.refresh_from_db()
        self.assertEqual(inherited.status, inherited.STATUS_RETIRED)
        self.assertEqual(replacement.status, replacement.STATUS_READY)
        self.assertEqual(replacement.drive_file_id, 'drive-new')
        self.assertEqual(
            replacement.placement_config['field_overlay_manifest']['fields'], {},
        )
        self.client.force_login(self.user)
        history = self.client.get(reverse(
            'admin:core_originationproductdefinition_version_history',
            args=[self.product.pk],
        ))
        self.assertContains(history, 'Inherited')
        self.assertContains(history, 'Replacement')
        self.assertContains(history, 'Retired')

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_failed_replacement_keeps_inherited_pdf_ready(self, storage_class):
        inherited = OriginationDocumentTemplate.objects.create(
            product_definition=self.product,
            document_type=self.product.document_type,
            name='Inherited', version=1,
            source_filename='old.pdf', source_sha256='e' * 64,
            source_byte_size=100, page_count=1,
            placement_config=self.calibrated_configuration(),
            drive_file_id='drive-old', drive_url='https://drive.test/old',
            created_by=self.user,
        )
        storage_class.return_value.upload.side_effect = RuntimeError('Drive unavailable')
        replacement_pdf = BytesIO(synthetic_pdf())
        replacement_pdf.name = 'replacement.pdf'

        failed = replace_draft_template(
            product_definition=self.product, pdf_file=replacement_pdf,
            name='Replacement', actor=self.user,
        )

        inherited.refresh_from_db()
        self.assertEqual(inherited.status, inherited.STATUS_READY)
        self.assertEqual(failed.status, failed.STATUS_UPLOAD_FAILED)
        self.assertIn('current draft template remains available', failed.upload_error)

    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_replacement_does_not_retire_template_if_product_changes_during_upload(self, storage_class):
        inherited = OriginationDocumentTemplate.objects.create(
            product_definition=self.product,
            document_type=self.product.document_type,
            name='Inherited', version=1,
            source_filename='old.pdf', source_sha256='f' * 64,
            source_byte_size=100, page_count=1,
            placement_config=self.calibrated_configuration(),
            drive_file_id='drive-old', drive_url='https://drive.test/old',
            created_by=self.user,
        )

        def publish_while_uploading(*_args, **_kwargs):
            OriginationProductDefinition.objects.filter(pk=self.product.pk).update(
                lifecycle_status=OriginationProductDefinition.STATUS_PUBLISHED,
            )
            return 'drive-candidate', 'https://drive.test/candidate'

        storage_class.return_value.upload.side_effect = publish_while_uploading
        replacement_pdf = BytesIO(synthetic_pdf())
        replacement_pdf.name = 'replacement.pdf'

        abandoned = replace_draft_template(
            product_definition=self.product, pdf_file=replacement_pdf,
            name='Replacement', actor=self.user,
        )

        inherited.refresh_from_db()
        self.assertEqual(inherited.status, inherited.STATUS_READY)
        self.assertEqual(abandoned.status, abandoned.STATUS_UPLOAD_FAILED)
        self.assertIn('published template was left unchanged', abandoned.upload_error)
        self.assertTrue(abandoned.events.filter(action='replacement_abandoned').exists())

    @patch('core.services.compliance_audit.record_event')
    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_retired_template_remains_available_to_exact_pinned_application_contract(self, storage_class, _audit):
        storage = storage_class.return_value
        storage.upload.side_effect = [
            ('drive-dairy-v1', 'https://drive.test/dairy-v1'),
            ('drive-dairy-v2', 'https://drive.test/dairy-v2'),
        ]
        storage.download.return_value = self.pdf

        first_file = BytesIO(self.pdf); first_file.name = 'dairy-v1.pdf'
        first_template = create_template(
            pdf_file=first_file, product_definition=self.product,
            name='Dairy v1', actor=self.user,
        )
        first_draft = save_calibration_draft(
            template=first_template, configuration=self.calibrated_configuration(),
            actor=self.user, expected_revision=1,
        )
        first_product, first_template, _published = publish_product_template(
            template=first_template, revision=first_draft.revision, actor=self.user,
        )
        successor = clone_product_version(first_product, actor=self.user)
        second_file = BytesIO(self.pdf); second_file.name = 'dairy-v2.pdf'
        second_template = replace_draft_template(
            pdf_file=second_file, product_definition=successor,
            name='Dairy v2', actor=self.user,
        )
        successor_config = self.calibrated_configuration()
        successor_config['version'] = successor.version
        second_draft = save_calibration_draft(
            template=second_template, configuration=successor_config,
            actor=self.user, expected_revision=1,
        )
        publish_product_template(
            template=second_template, revision=second_draft.revision, actor=self.user,
        )

        first_template.refresh_from_db(); first_product.refresh_from_db()
        self.assertEqual(first_template.status, first_template.STATUS_RETIRED)
        self.assertEqual(first_product.lifecycle_status, first_product.STATUS_RETIRED)
        source, config = load_active_template(
            first_product.document_type,
            version=first_product.document_template_version,
            expected_sha256=first_product.document_template_sha256,
        )
        self.assertEqual(source, self.pdf)
        self.assertEqual(config['version'], 1)
