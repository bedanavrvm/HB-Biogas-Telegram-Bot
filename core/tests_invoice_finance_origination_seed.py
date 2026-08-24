"""Focused regression tests for the reviewed Invoice Finance LAF seed."""

from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from pypdf import PdfWriter

from core.models import (
    AccessGrant,
    LoanOriginationApplication,
    OriginationDataField,
    OriginationDocumentTemplate,
    OriginationProductDefinition,
    OriginationSigningAction,
    OriginationSigningPackage,
    Product,
    ProductVersion,
)
from core.services.invoice_finance_origination_seed import (
    FIELD_SPECS,
    InvoiceFinanceSeedError,
    apply_seed,
)
from core.services.loan_origination import OriginationError
from core.services.origination_access import DENIED, FULL, application_presentation_mode, scope_application_queryset
from core.services.origination_esign import authorize_staff_signer, complete_staff_signatures
from core.services.telegram_identity import user_access


class InvoiceFinanceOriginationSeedTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser(
            username='invoice-seed-admin', email='invoice-seed@example.test', password='password',
        )
        self.product = Product.objects.create(name='Invoice Finance', code='invoice_finance')
        self.terms = ProductVersion.objects.create(
            product=self.product, version=1, status=ProductVersion.STATUS_DRAFT,
            created_by=self.actor,
        )
        for spec in FIELD_SPECS:
            if spec['create']:
                continue
            field, _created = OriginationDataField.objects.get_or_create(
                key=spec['key'], defaults={
                    'label': spec['label'], 'data_type': spec['type'],
                    'source_type': spec['source'], 'sensitivity': spec['sensitivity'],
                    'masking_policy': spec['masking'], 'reporting_use': spec['reporting'],
                    'choice_options': spec['options'], 'created_by': self.actor,
                },
            )
            self.assertEqual(field.data_type, spec['type'])
        self.initial_field_count = OriginationDataField.objects.count()
        self.initial_definition_count = OriginationProductDefinition.objects.count()
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pdf_path = Path(self.temp.name) / 'INVOICE FINANCE.pdf'
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        with self.pdf_path.open('wb') as output:
            writer.write(output)

    def _command(self, *, apply=False):
        output = StringIO()
        arguments = [
            '--actor', self.actor.username, '--pdf', str(self.pdf_path),
            '--product-code', self.product.code,
        ]
        if apply:
            arguments.append('--apply')
        call_command('seed_invoice_finance_origination', *arguments, stdout=output)
        return output.getvalue()

    def test_dry_run_validates_without_writing(self):
        message = self._command()

        self.assertIn('Dry run:', message)
        self.assertIn('ATTACH section is intentionally ignored', message)
        self.assertEqual(OriginationProductDefinition.objects.count(), self.initial_definition_count)
        self.assertEqual(OriginationDataField.objects.count(), self.initial_field_count)

    def test_direct_apply_rejects_an_inactive_superuser(self):
        self.actor.is_active = False
        self.actor.save(update_fields=['is_active'])

        with self.assertRaisesRegex(InvoiceFinanceSeedError, 'active Django Superuser'):
            apply_seed(
                product_code=self.product.code,
                pdf_path=self.pdf_path,
                actor=self.actor,
            )

    @override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic-drive-folder')
    @patch('core.services.origination_templates._upload_template_bytes', return_value=('drive-file', 'https://drive.example.test/file'))
    def test_apply_builds_an_unpublished_calibration_ready_contract(self, _upload):
        message = self._command(apply=True)

        definition = OriginationProductDefinition.objects.get(product_key='invoice_finance')
        template = definition.document_templates.get(document_role=OriginationDocumentTemplate.ROLE_PRIMARY)
        self.assertIn('Prepared Invoice Finance v1', message)
        self.assertEqual(definition.lifecycle_status, definition.STATUS_DRAFT)
        self.assertFalse(definition.is_active)
        self.assertEqual(definition.product_version, self.terms)
        self.assertEqual(
            len(definition.form_schema['fields']),
            len([item for item in FIELD_SPECS if item['source'] != OriginationDataField.SOURCE_SYSTEM]),
        )
        self.assertNotIn('application_date', {item['key'] for item in definition.form_schema['fields']})
        self.assertEqual(
            [item['key'] for item in definition.form_schema['sections']],
            ['applicant_details', 'business_details', 'banking_details', 'invoice_details', 'signer_details', 'acknowledgement'],
        )
        self.assertEqual(
            {item['role'] for item in definition.signer_rules},
            {'borrower', 'invoice_payer_representative', 'bro_1', 'management_approver'},
        )
        self.assertEqual(definition.document_assignments.count(), 0)
        self.assertEqual(template.status, template.STATUS_READY)
        self.assertEqual(template.drive_file_id, 'drive-file')
        self.assertIsNone(template.published_configuration_revision)
        self.assertEqual(
            OriginationDataField.objects.filter(
                key__in=[item['key'] for item in FIELD_SPECS], active=True,
            ).count(),
            len(FIELD_SPECS),
        )
        self.assertNotIn('invoice_copy', {item['key'] for item in definition.form_schema['fields']})

    @override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic-drive-folder')
    @patch('core.services.origination_templates._upload_template_bytes', return_value=('drive-file', 'https://drive.example.test/file'))
    def test_apply_is_idempotent_for_same_draft_and_pdf(self, upload):
        self._command(apply=True)
        definition = OriginationProductDefinition.objects.get(product_key='invoice_finance')
        template = definition.document_templates.get()
        event_counts = (
            definition.events.count(), template.events.count(),
            sum(field.events.count() for field in OriginationDataField.objects.filter(
                key__in=[item['key'] for item in FIELD_SPECS],
            )),
        )
        self._command(apply=True)

        self.assertEqual(OriginationProductDefinition.objects.filter(product_key='invoice_finance').count(), 1)
        self.assertEqual(OriginationDocumentTemplate.objects.filter(document_type='invoice_finance').count(), 1)
        self.assertEqual(upload.call_count, 1)
        definition.refresh_from_db()
        template.refresh_from_db()
        self.assertEqual(event_counts, (
            definition.events.count(), template.events.count(),
            sum(field.events.count() for field in OriginationDataField.objects.filter(
                key__in=[item['key'] for item in FIELD_SPECS],
            )),
        ))

    @override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic-drive-folder')
    @patch('core.services.origination_templates._upload_template_bytes', return_value=('drive-file', 'https://drive.example.test/file'))
    def test_published_contract_gets_a_draft_successor(self, _upload):
        published = OriginationProductDefinition.objects.create(
            product_version=self.terms, product_key='invoice_finance', name='Invoice Finance',
            version=1, form_schema={'fields': []}, signer_rules=[], document_type='invoice_finance',
            document_template_name='Historical.pdf', document_template_version=1,
            document_template_sha256='a' * 64, lifecycle_status=OriginationProductDefinition.STATUS_PUBLISHED,
            is_active=True, created_by=self.actor,
        )

        self._command(apply=True)

        successor = OriginationProductDefinition.objects.get(
            product_key='invoice_finance', lifecycle_status=OriginationProductDefinition.STATUS_DRAFT,
        )
        published.refresh_from_db()
        self.assertEqual(successor.version, 2)
        self.assertEqual(successor.supersedes, published)
        self.assertTrue(published.is_active)
        self.assertEqual(published.lifecycle_status, published.STATUS_PUBLISHED)

    def test_staff_signer_role_authorization_is_scoped_and_not_interchangeable(self):
        definition = OriginationProductDefinition.objects.create(
            product_version=self.terms, product_key='invoice_finance', name='Invoice Finance',
            version=1, form_schema={'fields': []}, signer_rules=[], document_type='invoice_finance',
            created_by=self.actor,
        )
        application = LoanOriginationApplication.objects.create(
            reference_number='ORG-TEST-INVOICE-ROLE', product_definition=definition,
            product_version=self.terms, officer=self.actor, branch='EMBU',
        )
        manager = get_user_model().objects.create_user(username='invoice-branch-manager')
        officer = get_user_model().objects.create_user(username='invoice-bro')
        operations = get_user_model().objects.create_user(username='invoice-operations')
        AccessGrant.objects.create(
            user=manager, workflow='jawabu_portal', role='BM',
            branch='EMBU', product='invoice_finance',
        )
        AccessGrant.objects.create(
            user=officer, workflow='jawabu_portal', role='JBL_OFFICER',
            branch='EMBU', product='invoice_finance',
        )
        AccessGrant.objects.create(
            user=operations, workflow='jawabu_portal', role='OPERATIONS_ADMIN',
            branch='EMBU', product='invoice_finance',
        )

        authorize_staff_signer(
            actor=manager, application=application, signer_role='management_approver',
        )
        authorize_staff_signer(
            actor=officer, application=application, signer_role='bro_1',
        )
        with self.assertRaisesRegex(OriginationError, 'not authorized'):
            authorize_staff_signer(
                actor=manager, application=application, signer_role='bro_1',
            )
        with self.assertRaisesRegex(OriginationError, 'not authorized'):
            authorize_staff_signer(
                actor=operations, application=application, signer_role='management_approver',
            )

    def test_staff_signing_capability_does_not_expose_other_officers_drafts(self):
        definition = OriginationProductDefinition.objects.create(
            product_version=self.terms, product_key='invoice_finance', name='Invoice Finance',
            version=1, form_schema={'fields': []}, signer_rules=[], document_type='invoice_finance',
            created_by=self.actor,
        )
        manager = get_user_model().objects.create_user(username='scoped-signing-manager')
        AccessGrant.objects.create(
            user=manager, workflow='jawabu_portal', role='BM',
            branch='EMBU', product='invoice_finance',
        )
        draft = LoanOriginationApplication.objects.create(
            reference_number='ORG-TEST-INVOICE-DRAFT', product_definition=definition,
            product_version=self.terms, officer=self.actor, branch='EMBU',
        )
        signing = LoanOriginationApplication.objects.create(
            reference_number='ORG-TEST-INVOICE-SIGNING', product_definition=definition,
            product_version=self.terms, officer=self.actor, branch='EMBU',
            status=LoanOriginationApplication.STATUS_SIGNING_PENDING,
        )
        access = user_access(manager, 'jawabu_portal')

        self.assertEqual(application_presentation_mode(draft, user=manager, access=access), DENIED)
        self.assertEqual(application_presentation_mode(signing, user=manager, access=access), FULL)
        visible = scope_application_queryset(
            LoanOriginationApplication.objects.all(), user=manager, access=access,
        )
        self.assertEqual(list(visible.values_list('pk', flat=True)), [signing.pk])

    @patch('core.services.origination_esign.render_verified_package', return_value=b'synthetic-signed-pdf')
    def test_staff_signature_atomically_completes_its_signing_date_slot(self, _render):
        definition = OriginationProductDefinition.objects.create(
            product_version=self.terms, product_key='invoice_finance', name='Invoice Finance',
            version=1, form_schema={'fields': []}, signer_rules=[], document_type='invoice_finance',
            created_by=self.actor,
        )
        manager = get_user_model().objects.create_user(username='invoice-signing-manager')
        AccessGrant.objects.create(
            user=manager, workflow='jawabu_portal', role='MANAGEMENT',
            branch='EMBU', product='invoice_finance',
        )
        application = LoanOriginationApplication.objects.create(
            reference_number='ORG-TEST-INVOICE-DATE', product_definition=definition,
            product_version=self.terms, officer=self.actor, branch='EMBU',
            status=LoanOriginationApplication.STATUS_SIGNING_PENDING,
        )
        package = OriginationSigningPackage.objects.create(
            application=application, application_revision=application.revision,
            external_reference='ESIGN-INVOICE-DATE', document_type='invoice_finance',
            unsigned_document_hash='a' * 64, review_scope_sha256='b' * 64,
            approved_unsigned_document_hash='a' * 64,
            approved_review_scope_sha256='b' * 64,
            reviewed_at=self.terms.created_at,
            participants_snapshot=[{
                'role': 'management_approver', 'required': True,
                'slots': [
                    {'key': 'approval_signature', 'document_key': 'primary', 'type': 'signature', 'required': True},
                    {'key': 'approval_date', 'document_key': 'primary', 'type': 'date_signed', 'required': True},
                ],
            }],
        )

        completed = complete_staff_signatures(
            package_id=package.pk, signer_role='management_approver', actor=manager,
            signature_capture={'method': 'typed', 'name': 'Synthetic Manager'},
            expected_revision=application.revision, request_id='staff-signature-with-date',
        )

        actions = completed.actions.order_by('slot_key')
        self.assertEqual(actions.count(), 2)
        self.assertEqual(
            set(actions.values_list('action_type', flat=True)),
            {OriginationSigningAction.TYPE_SIGNATURE, OriginationSigningAction.TYPE_DATE_SIGNED},
        )
        date_action = actions.get(action_type=OriginationSigningAction.TYPE_DATE_SIGNED)
        self.assertRegex(date_action.metadata['signed_date'], r'^\d{4}-\d{2}-\d{2}$')
        completed.refresh_from_db()
        application.refresh_from_db()
        self.assertEqual(completed.status, OriginationSigningPackage.STATUS_FULLY_SIGNED)
        self.assertEqual(application.status, LoanOriginationApplication.STATUS_FULLY_SIGNED)
