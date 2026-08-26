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
    OriginationDataField,
    OriginationDocumentTemplate,
    OriginationDocumentTemplateEvent,
    OriginationProductDocumentAssignment,
    OriginationProductDefinition,
    OriginationTemplateConfigurationRevision,
)
from core.services.origination_templates import (
    OriginationTemplateError,
    activate_template,
    assignment_template_compatibility_errors,
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
from core.services.origination_fields import (
    OriginationFieldConflict,
    consolidate_data_field,
    create_data_field,
    mark_data_field_terminology_distinct,
    terminology_audit_candidates,
)
from core.services.origination_terminology import terminology_signature
from core.services.partnership_laf_preview import (
    PartnershipLafPreviewError,
    _checkbox_is_checked,
    _overlay_page,
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
    def test_choice_samples_keep_display_label_and_canonical_checkbox_value(self):
        config = initial_template_configuration(None, form_schema={'fields': [{
            'key': 'applicant_marital_status', 'label': 'Marital Status', 'type': 'choice',
            'options': [
                {'code': 'single', 'label': 'Single'},
                {'code': 'married', 'label': 'Married'},
            ],
        }]})

        self.assertEqual(config['sample_context']['applicant_marital_status'], 'Single')
        self.assertEqual(
            config['sample_context']['_canonical_values']['applicant_marital_status'],
            'single',
        )

    def test_checkbox_matches_canonical_code_and_legacy_display_label(self):
        self.assertTrue(_checkbox_is_checked('married', 'married', display_value='Married'))
        self.assertTrue(_checkbox_is_checked('married', 'Married', display_value='Married'))
        self.assertFalse(_checkbox_is_checked('single', 'married', display_value='Single'))

    def test_checkbox_overlay_draws_tick_only_for_matching_choice(self):
        spec = {
            'render_as': 'checkbox', 'checked_when': 'married',
            'box': {'x': 10, 'y': 10, 'width': 12, 'height': 12},
        }
        checked = PdfReader(BytesIO(
            _overlay_page(100, 100, [(spec, 'Married', 'married')], {}),
        )).pages[0].get_contents().get_data()
        unchecked = PdfReader(BytesIO(
            _overlay_page(100, 100, [(spec, 'Single', 'single')], {}),
        )).pages[0].get_contents().get_data()

        self.assertEqual(checked.count(b' l'), 2)
        self.assertEqual(unchecked.count(b' l'), 0)

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

    def test_filled_preview_renders_custom_signature_and_stamp_appearance(self):
        config = {
            'field_overlay_manifest': {'fields': {}},
            'signature_overlay_manifest': {'slots': {
                'borrower.signature': {
                    'slot_type': 'signature', 'label': 'Borrower signature',
                    'page_number': 1, 'units': 'pt',
                    'box': {'x': 40, 'y': 80, 'width': 180, 'height': 40},
                    'padding': {'x': 4, 'y': 3}, 'rotation': -4,
                    'align': 'right', 'vertical_align': 'top',
                    'ink_color': 'blue', 'typed_font': 'Times-Italic', 'font_size': 18,
                },
                'officer.stamp': {
                    'slot_type': 'stamp', 'label': 'Branch stamp',
                    'page_number': 1, 'units': 'pt',
                    'box': {'x': 280, 'y': 70, 'width': 120, 'height': 55},
                    'padding': {'x': 3, 'y': 3}, 'rotation': 5,
                    'align': 'left', 'vertical_align': 'bottom', 'stamp_fit': 'contain',
                },
            }},
        }

        rendered = render_template(
            synthetic_pdf(), config, {'_show_signature_slots': True},
        )
        text = PdfReader(BytesIO(rendered)).pages[0].extract_text()
        self.assertIn('Sample signature', text)
        self.assertIn('STAMP PREVIEW', text)

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

    def test_latest_family_compatibility_rejects_removed_required_signer_slot(self):
        baseline = OriginationDocumentTemplate(
            document_type='shared_guarantor', document_role='supporting',
            signer_rules=[{'role': 'witness', 'required': True, 'slots': [
                {'key': 'signature', 'type': 'signature'},
            ]}],
        )
        candidate = OriginationDocumentTemplate(
            document_type='shared_guarantor', document_role='supporting',
            status='active', signer_rules=[{'role': 'witness', 'required': True, 'slots': []}],
            published_configuration_revision_id='00000000-0000-0000-0000-000000000001',
        )

        errors = assignment_template_compatibility_errors(baseline, candidate)

        self.assertIn('required signer slot witness.signature was removed', errors)


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
    def test_activation_retires_global_family_without_locking_nullable_product_join(self, storage_class):
        """Global supporting templates must activate on PostgreSQL as well as SQLite."""
        digest = hashlib.sha256(self.pdf).hexdigest()
        previous = OriginationDocumentTemplate.objects.create(
            product_definition=None, document_key='guarantor_consent', document_role='supporting',
            inclusion_mode='required', document_type='shared-guarantor-consent',
            name='Guarantee consent', version=1, status=OriginationDocumentTemplate.STATUS_ACTIVE,
            source_filename='consent-v1.pdf', source_sha256=digest,
            source_byte_size=len(self.pdf), page_count=1, placement_config={},
            drive_file_id='drive-consent-v1', created_by=self.maker,
        )
        previous_revision = OriginationTemplateConfigurationRevision.objects.create(
            template=previous, revision=1, configuration={}, is_published=True,
            created_by=self.maker, published_at=timezone.now(),
        )
        previous.published_configuration_revision = previous_revision
        previous.save(update_fields=['published_configuration_revision'])
        candidate = OriginationDocumentTemplate.objects.create(
            product_definition=None, document_key='guarantor_consent', document_role='supporting',
            inclusion_mode='required', document_type='shared-guarantor-consent',
            name='Guarantee consent', version=2, status=OriginationDocumentTemplate.STATUS_READY,
            source_filename='consent-v2.pdf', source_sha256=digest,
            source_byte_size=len(self.pdf), page_count=1, placement_config={},
            drive_file_id='drive-consent-v2', created_by=self.maker,
        )
        candidate_revision = OriginationTemplateConfigurationRevision.objects.create(
            template=candidate, revision=1, configuration={}, is_published=True,
            created_by=self.maker, published_at=timezone.now(),
        )
        candidate.published_configuration_revision = candidate_revision
        candidate.save(update_fields=['published_configuration_revision'])
        storage_class.return_value.download.return_value = self.pdf

        activated = activate_template(candidate, actor=self.maker)

        previous.refresh_from_db()
        self.assertEqual(activated.status, OriginationDocumentTemplate.STATUS_ACTIVE)
        self.assertEqual(previous.status, OriginationDocumentTemplate.STATUS_RETIRED)
        self.assertTrue(previous.events.filter(action='retired').exists())
        self.assertTrue(candidate.events.filter(action='activated').exists())

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
    def test_submitted_review_preview_preserves_the_submitted_configuration(self, published, renderer):
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
        self.assertEqual(application.template_configuration_snapshot, {'old': True})
        self.assertEqual(renderer.call_args.kwargs['configuration'], {'old': True})
        published.assert_not_called()


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

    @patch('core.services.origination_templates.load_template_source')
    def test_signer_slot_appearance_is_validated_without_raw_json(self, load_source):
        load_source.return_value = self.pdf
        self.product.signer_rules[0]['slots'].append({
            'key': 'branch_stamp', 'label': 'Branch stamp',
            'type': 'stamp', 'required': False,
        })
        self.product.save(update_fields=['signer_rules'])
        template = OriginationDocumentTemplate.objects.create(
            product_definition=self.product, document_key='primary',
            document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
            inclusion_mode=OriginationDocumentTemplate.INCLUDE_REQUIRED,
            document_type=self.product.document_type, name='Dairy Capital LAF', version=1,
            status=OriginationDocumentTemplate.STATUS_READY,
            source_filename='dairy.pdf', source_sha256='f' * 64,
            source_byte_size=len(self.pdf), page_count=1,
            placement_config={}, drive_file_id='synthetic-dairy-template', created_by=self.user,
        )
        config = self.calibrated_configuration()
        slot = config['signature_overlay_manifest']['slots']['borrower.acceptance']
        slot.update({
            'align': 'right', 'vertical_align': 'top',
            'padding': {'x': 4, 'y': 3}, 'rotation': -5,
            'ink_color': 'blue', 'typed_font': 'Times-Italic',
            'font_size': 18, 'stroke_width': 2.5, 'stamp_fit': 'contain',
        })
        config['signature_overlay_manifest']['slots']['borrower.branch_stamp'] = {
            'role': 'borrower', 'slot_key': 'branch_stamp', 'slot_type': 'stamp',
            'label': 'Branch stamp', 'page_number': 1, 'units': 'pt',
            'box': {'x': 250, 'y': 70, 'width': 120, 'height': 55},
            'align': 'center', 'vertical_align': 'center',
            'padding': {'x': 2, 'y': 2}, 'rotation': 3, 'stamp_fit': 'stretch',
        }

        normalized = validate_template_configuration(
            config, template=template, require_complete=True,
        )
        self.assertEqual(
            normalized['signature_overlay_manifest']['slots']['borrower.acceptance']['ink_color'],
            'blue',
        )
        self.assertEqual(
            normalized['signature_overlay_manifest']['slots']['borrower.branch_stamp']['stamp_fit'],
            'stretch',
        )

        invalid = json.loads(json.dumps(config))
        invalid['signature_overlay_manifest']['slots']['borrower.acceptance']['rotation'] = 181
        with self.assertRaisesRegex(OriginationTemplateError, 'between -180 and 180'):
            validate_template_configuration(invalid, template=template, require_complete=True)

        source = (
            Path(settings.BASE_DIR) / 'core/static/admin/origination_calibration.js'
        ).read_text(encoding='utf-8')
        builder = (
            Path(settings.BASE_DIR)
            / 'core/templates/admin/core/originationdocumenttemplate/calibrate.html'
        ).read_text(encoding='utf-8')
        self.assertIn('function updateSelectedSignature()', source)
        self.assertIn('cal-signature-ink', builder)
        self.assertIn('cal-signature-font', builder)
        self.assertIn('cal-signature-stroke-width', builder)
        self.assertIn('cal-stamp-fit', builder)

    def test_shared_assignment_admin_derives_document_identity_from_template(self):
        from core.admin import OriginationProductDocumentAssignmentForm

        template = OriginationDocumentTemplate.objects.create(
            product_definition=None, document_key='guarantor_form',
            document_role=OriginationDocumentTemplate.ROLE_SUPPORTING,
            inclusion_mode=OriginationDocumentTemplate.INCLUDE_REQUIRED,
            document_type='guarantor_form', name='Guarantor Form', version=1,
            status=OriginationDocumentTemplate.STATUS_ACTIVE,
            source_filename='guarantor.pdf', source_sha256='c' * 64,
            source_byte_size=100, page_count=1, placement_config={},
            created_by=self.user,
        )
        form = OriginationProductDocumentAssignmentForm(data={
            'product_definition': str(self.product.pk), 'template': str(template.pk),
            'version_policy': OriginationProductDocumentAssignment.VERSION_LATEST_COMPATIBLE,
            'inclusion_mode': OriginationDocumentTemplate.INCLUDE_REQUIRED,
            'display_order': 10,
        })

        self.assertNotIn('document_key', form.fields)
        self.assertNotIn('name', form.fields)
        self.assertTrue(form.is_valid(), form.errors)
        assignment = form.save(commit=False)
        assignment.created_by = self.user
        assignment.save()

        self.assertEqual(assignment.document_key, template.document_key)
        self.assertEqual(assignment.name, template.name)
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('admin:core_originationproductdocumentassignment_add'),
            {'product_definition': str(self.product.pk)},
        )
        self.assertContains(response, 'Only include this document when')
        self.assertContains(response, 'origination_document_conditions.js')

    def test_shared_assignment_admin_stores_simple_rule_from_form_controls(self):
        from core.admin import OriginationProductDocumentAssignmentForm

        template = OriginationDocumentTemplate.objects.create(
            product_definition=None, document_key='guarantor_form',
            document_role=OriginationDocumentTemplate.ROLE_SUPPORTING,
            inclusion_mode=OriginationDocumentTemplate.INCLUDE_REQUIRED,
            document_type='guarantor_form', name='Guarantor Form', version=1,
            status=OriginationDocumentTemplate.STATUS_ACTIVE,
            source_filename='guarantor.pdf', source_sha256='d' * 64,
            source_byte_size=100, page_count=1, placement_config={},
            created_by=self.user,
        )
        form = OriginationProductDocumentAssignmentForm(data={
            'product_definition': str(self.product.pk), 'template': str(template.pk),
            'version_policy': OriginationProductDocumentAssignment.VERSION_LATEST_COMPATIBLE,
            'inclusion_mode': OriginationDocumentTemplate.INCLUDE_CONDITIONAL,
            'display_order': 10,
            'condition_field': 'farmer_name',
            'condition_operator': 'truthy',
            'condition_value': '',
        })

        self.assertTrue(form.is_valid(), form.errors)
        assignment = form.save(commit=False)
        self.assertEqual(assignment.applicability_rule, {
            'field': 'farmer_name', 'operator': 'truthy',
        })

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
        self.assertIn('origination_calibration.js\' %}?v=15', template)

    def test_checkbox_builder_uses_canonical_selectors_and_sample_control(self):
        source = (
            Path(settings.BASE_DIR) / 'core/static/admin/origination_calibration.js'
        ).read_text(encoding='utf-8')
        template = (
            Path(settings.BASE_DIR)
            / 'core/templates/admin/core/originationdocumenttemplate/calibrate.html'
        ).read_text(encoding='utf-8')

        self.assertIn('function checkboxOptions(spec)', source)
        self.assertIn('function normalizeChoiceSamples()', source)
        self.assertIn('cal-sample-value', template)
        self.assertIn('<select id="cal-checked-when">', template)
        self.assertNotIn('id="cal-checked-when" type="text"', template)

    def test_readiness_and_field_catalogue_are_bounded_collapsible_panels(self):
        source = (
            Path(settings.BASE_DIR) / 'core/static/admin/origination_calibration.js'
        ).read_text(encoding='utf-8')
        styles = (
            Path(settings.BASE_DIR) / 'core/static/admin/origination_calibration.css'
        ).read_text(encoding='utf-8')
        template = (
            Path(settings.BASE_DIR)
            / 'core/templates/admin/core/originationdocumenttemplate/calibrate.html'
        ).read_text(encoding='utf-8')

        self.assertIn('<details id="calibration-readiness"', template)
        self.assertIn('id="calibration-field-browser"', template)
        self.assertIn('calibration-field-summary-count', template)
        self.assertIn('max-height: min(180px, 26vh)', styles)
        self.assertIn('height: clamp(220px, 36vh, 420px)', styles)
        self.assertIn("$('calibration-readiness').open = true", source)

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

    def test_unsaved_product_builder_can_create_an_audited_canonical_field_inline(self):
        self.client.force_login(self.user)
        url = reverse('admin:core_originationproductdefinition_create_canonical_field')
        payload = {
            'label': 'Applicant residence type',
            'key': 'applicant_residence_type',
            'type': 'choice',
            'sensitivity': 'pii',
            'category': 'Applicant',
            'choice_options': [
                {'code': 'owned', 'label': 'Owned'},
                {'code': 'rented', 'label': 'Rented'},
            ],
        }

        response = self.client.post(
            url, data=json.dumps(payload), content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['ok'])
        self.assertFalse(body['replayed'])
        self.assertEqual(body['field']['key'], 'applicant_residence_type')
        field = OriginationDataField.objects.get(key='applicant_residence_type')
        self.assertEqual(field.source_type, OriginationDataField.SOURCE_USER_INPUT)
        self.assertEqual(field.choice_options[0]['code'], 'owned')
        self.assertEqual(field.events.count(), 1)

        replay = self.client.post(
            url, data=json.dumps(payload), content_type='application/json',
        )
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()['replayed'])
        self.assertEqual(OriginationDataField.objects.filter(key=field.key).count(), 1)
        self.assertEqual(field.events.count(), 1)

    def test_canonical_field_creation_rejects_person_term_synonym_duplicate(self):
        preferred, _ = create_data_field(
            payload={
                'label': 'Applicant preferred phone',
                'key': 'applicant_preferred_phone',
                'type': 'phone',
                'category': 'Applicant',
            },
            actor=self.user,
        )

        with self.assertRaisesMessage(
            OriginationFieldConflict,
            'Reuse that canonical field',
        ):
            create_data_field(
                payload={
                    'label': 'Customer preferred phone',
                    'key': 'customer_preferred_phone',
                    'type': 'phone',
                    'category': 'Applicant',
                },
                actor=self.user,
            )

        self.assertTrue(preferred.active)
        self.assertFalse(
            OriginationDataField.objects.filter(key='customer_preferred_phone').exists(),
        )

    def test_terminology_consolidation_preserves_historical_product_schema(self):
        preferred = OriginationDataField.objects.create(
            key='applicant_preferred_mobile', label='Applicant preferred mobile',
            data_type=OriginationDataField.TYPE_PHONE, category='Applicant',
            created_by=self.user,
        )
        duplicate = OriginationDataField.objects.create(
            key='farmer_preferred_mobile', label='Farmer preferred mobile',
            data_type=OriginationDataField.TYPE_PHONE, category='Applicant',
            created_by=self.user,
        )
        original_schema = json.loads(json.dumps(self.product.form_schema))

        consolidate_data_field(
            duplicate=duplicate, preferred=preferred, actor=self.user,
        )

        duplicate.refresh_from_db()
        preferred.refresh_from_db()
        self.product.refresh_from_db()
        self.assertFalse(duplicate.active)
        self.assertEqual(duplicate.preferred_field, preferred)
        self.assertIn('Farmer preferred mobile', preferred.aliases)
        self.assertIn('farmer_preferred_mobile', preferred.aliases)
        self.assertEqual(self.product.form_schema, original_schema)
        self.assertTrue(duplicate.events.filter(action='terminology_consolidated').exists())

    def test_terminology_audit_can_confirm_a_similar_field_is_distinct(self):
        OriginationDataField.objects.create(
            key='applicant_contact_email', label='Applicant contact email',
            data_type=OriginationDataField.TYPE_TEXT, category='Applicant',
            created_by=self.user,
        )
        duplicate = OriginationDataField.objects.create(
            key='client_contact_email', label='Client contact email',
            data_type=OriginationDataField.TYPE_TEXT, category='Applicant',
            created_by=self.user,
        )
        self.assertTrue(any(
            row['duplicate'].pk == duplicate.pk for row in terminology_audit_candidates()
        ))

        mark_data_field_terminology_distinct(data_field=duplicate, actor=self.user)

        self.assertFalse(any(
            row['duplicate'].pk == duplicate.pk for row in terminology_audit_candidates()
        ))
        duplicate.refresh_from_db()
        self.assertTrue(duplicate.terminology_reviewed_distinct)

    def test_terminology_audit_admin_is_superuser_only(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('admin:core_originationdatafield_terminology_audit'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Applicant is the standard Origination term')
        self.assertContains(response, 'Approved vocabulary')

        staff = get_user_model().objects.create_user(
            'terminology-staff', 'terminology-staff@example.test', 'x', is_staff=True,
        )
        self.client.force_login(staff)
        forbidden = self.client.get(
            reverse('admin:core_originationdatafield_terminology_audit'),
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_terminology_audit_admin_consolidates_duplicate_idempotently(self):
        preferred = OriginationDataField.objects.create(
            key='applicant_contact_phone', label='Applicant contact phone',
            data_type=OriginationDataField.TYPE_PHONE, category='Applicant',
            created_by=self.user,
        )
        duplicate = OriginationDataField.objects.create(
            key='customer_contact_phone', label='Customer contact phone',
            data_type=OriginationDataField.TYPE_PHONE, category='Applicant',
            created_by=self.user,
        )
        self.client.force_login(self.user)
        url = reverse('admin:core_originationdatafield_terminology_audit')
        payload = {
            'action': 'consolidate',
            'preferred_id': str(preferred.pk),
            'duplicate_id': str(duplicate.pk),
        }

        first = self.client.post(url, payload)
        replay = self.client.post(url, payload)

        self.assertRedirects(first, url)
        self.assertRedirects(replay, url)
        duplicate.refresh_from_db()
        self.assertFalse(duplicate.active)
        self.assertEqual(duplicate.preferred_field, preferred)
        self.assertEqual(
            duplicate.events.filter(action='terminology_consolidated').count(), 1,
        )

    def test_technical_client_request_name_is_not_reclassified_as_applicant(self):
        self.assertEqual(terminology_signature('client_request_id'), 'client_request_id')
        self.assertEqual(terminology_signature('borrower_signature'), 'borrower_signature')
        self.assertEqual(terminology_signature('customer_phone'), 'applicant_phone')

    def test_product_builder_field_creation_rejects_non_superuser(self):
        staff = get_user_model().objects.create_user(
            'field-builder-staff', 'field-builder@example.test', 'x', is_staff=True,
        )
        self.client.force_login(staff)

        response = self.client.post(
            reverse('admin:core_originationproductdefinition_create_canonical_field'),
            data=json.dumps({'label': 'Forbidden field', 'key': 'forbidden_field', 'type': 'text'}),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(OriginationDataField.objects.filter(key='forbidden_field').exists())

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
        self.assertContains(response, 'Upload a primary LAF or shared supporting form')
        self.assertContains(response, 'Loan form definition')
        self.assertContains(response, 'Dairy Working Capital - loan form v1')
        self.assertContains(response, f'value="{self.product.pk}" selected')
        self.assertEqual(
            tuple(response.context['adminform'].form.fields),
            (
                'product_definition', 'document_key', 'name', 'document_role',
                'inclusion_mode', 'display_order', 'officer_selectable',
                'default_selected', 'condition_field', 'condition_operator',
                'condition_value', 'applicability_rule', 'form_schema',
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
        self.assertContains(response, 'Supporting document form builder')
        self.assertContains(response, 'Create canonical field')
        self.assertContains(response, 'type="hidden" name="form_schema"')
        self.assertContains(response, 'type="hidden" name="signer_rules"')

    def test_admin_template_add_links_to_definition_builder_when_no_draft_is_eligible(self):
        self.product.lifecycle_status = OriginationProductDefinition.STATUS_PUBLISHED
        self.product.save(update_fields=['lifecycle_status'])
        self.client.force_login(self.user)

        response = self.client.get(reverse('admin:core_originationdocumenttemplate_add'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No draft loan form is ready for a primary LAF')
        self.assertContains(response, 'You may still upload a global supporting form')
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
        change_response = self.client.get(reverse(
            'admin:core_originationdocumenttemplate_change', args=[template.pk],
        ))
        self.assertContains(change_response, 'Upload next family version')
        self.assertContains(change_response, 'document_key=shared_guarantor')

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

    @patch('core.services.compliance_audit.record_event')
    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_published_reusable_primary_activates_assigned_product(self, storage_class, audit):
        storage_class.return_value.download.return_value = self.pdf
        template = OriginationDocumentTemplate.objects.create(
            product_definition=None,
            document_key='primary',
            document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
            inclusion_mode=OriginationDocumentTemplate.INCLUDE_REQUIRED,
            display_order=0,
            document_type=self.product.document_type,
            name='Reusable Dairy LAF',
            version=1,
            status=OriginationDocumentTemplate.STATUS_ACTIVE,
            source_filename='reusable-dairy.pdf',
            source_sha256=hashlib.sha256(self.pdf).hexdigest(),
            source_byte_size=len(self.pdf),
            page_count=1,
            drive_file_id='drive-reusable-dairy',
            form_schema=self.product.form_schema,
            signer_rules=self.product.signer_rules,
            created_by=self.user,
        )
        revision = OriginationTemplateConfigurationRevision.objects.create(
            template=template,
            revision=1,
            configuration=self.calibrated_configuration(),
            is_published=True,
            created_by=self.user,
            published_at=timezone.now(),
        )
        template.published_configuration_revision = revision
        template.save(update_fields=['published_configuration_revision', 'updated_at'])
        OriginationProductDocumentAssignment.objects.create(
            product_definition=self.product,
            template=template,
            version_policy=OriginationProductDocumentAssignment.VERSION_PINNED,
            document_key='primary',
            name=template.name,
            inclusion_mode=OriginationDocumentTemplate.INCLUDE_REQUIRED,
            display_order=0,
            created_by=self.user,
        )

        product, resolved_template, published = publish_product_template(
            template=template,
            revision=revision.revision,
            product_definition=self.product,
            actor=self.user,
        )

        product.refresh_from_db()
        self.assertTrue(product.is_active)
        self.assertEqual(product.lifecycle_status, product.STATUS_PUBLISHED)
        self.assertEqual(product.document_template_name, template.name)
        self.assertEqual(product.document_template_sha256, template.source_sha256)
        self.assertEqual(resolved_template, template)
        self.assertEqual(published, revision)
        self.assertTrue(product.events.filter(action='published').exists())
        audit.assert_called_once()

    @patch('core.services.compliance_audit.record_event')
    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_publish_uses_configured_borrower_identity_field_mappings(self, storage_class, audit):
        storage = storage_class.return_value
        storage.upload.return_value = ('drive-mapped-identity', 'https://drive.test/mapped-identity')
        storage.download.return_value = self.pdf
        self.product.form_schema = {
            'identity_contract': 'applicant_v1',
            'sections': [{'key': 'application', 'label': 'Application'}],
            'fields': [
                {
                    'key': 'applicant_first_name', 'label': 'Applicant First Name',
                    'type': 'text', 'section_key': 'application', 'required': False,
                },
                {
                    'key': 'applicant_id', 'label': 'Applicant ID',
                    'type': 'national_id', 'section_key': 'application', 'required': False,
                },
                {
                    'key': 'applicant_phone_no', 'label': 'Applicant Phone No',
                    'type': 'phone', 'section_key': 'application', 'required': True,
                },
            ],
        }
        self.product.signer_rules = [{
            'role': 'borrower', 'required': True,
            'identity_fields': {
                'name': 'applicant_first_name',
                'national_id': 'applicant_id',
                'phone': 'applicant_phone_no',
            },
            'slots': [{
                'key': 'signature', 'label': 'Borrower signature',
                'type': 'signature', 'required': True,
            }],
        }]
        self.product.save(update_fields=['form_schema', 'signer_rules'])
        pdf_file = BytesIO(self.pdf)
        pdf_file.name = 'mapped-identity.pdf'
        template = create_template(
            pdf_file=pdf_file, product_definition=self.product,
            name='Mapped Identity LAF', actor=self.user,
        )
        configuration = initial_template_configuration(self.product)
        configuration['field_overlay_manifest']['fields'] = {
            key: {
                'context_key': key, 'page_number': 1, 'units': 'pt',
                'box': {'x': 20, 'y': 700 - index * 30, 'width': 180, 'height': 16},
            }
            for index, key in enumerate(
                ('applicant_first_name', 'applicant_id', 'applicant_phone_no')
            )
        }
        configuration['signature_overlay_manifest']['slots'] = {
            'borrower.signature': {
                'role': 'borrower', 'slot_key': 'signature', 'slot_type': 'signature',
                'label': 'Borrower signature', 'page_number': 1, 'units': 'pt',
                'box': {'x': 20, 'y': 80, 'width': 180, 'height': 35},
            },
        }
        draft = save_calibration_draft(
            template=template, configuration=configuration,
            actor=self.user, expected_revision=1,
        )

        product, published_template, _published = publish_product_template(
            template=template, revision=draft.revision, actor=self.user,
        )

        self.assertEqual(product.lifecycle_status, product.STATUS_PUBLISHED)
        self.assertTrue(all(item['required'] for item in product.form_schema['fields']))
        self.assertTrue(all(item['required'] for item in published_template.form_schema['fields']))
        self.assertTrue(
            published_template.events.filter(
                action='applicant_identity_contract_normalized',
            ).exists(),
        )
        audit.assert_called_once()

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
