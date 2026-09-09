"""Focused contracts for the reviewed Main LAF seed registry."""

from dataclasses import replace
import hashlib
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from pypdf import PdfWriter

from core.models import (
    LoanOriginationApplication,
    OriginationDataField,
    OriginationDocumentProductEligibility,
    OriginationDocumentTemplate,
    OriginationProductDefinition,
    Product,
    ProductVersion,
)
from core.services.origination_main_laf_seeds import (
    DEFINITIONS,
    MainLafDefinition,
    MainLafSeedError,
    _field,
    _signer,
    apply_seed,
    preflight_seed,
    source_path,
)
from core.services.loan_origination import _missing_application_requirements, preview_context


DOCUMENT_NAMES = {
    'invoice_finance': 'invoice-finance-laf-seed.md',
    'generic': 'generic-jawabu-laf-seed.md',
    'lipa_mdogo_mdogo': 'lipa-mdogo-mdogo-laf-seed.md',
    'micro_asset': 'micro-asset-laf-seed.md',
    'water_tank': 'water-tank-laf-seed.md',
    'sme_logbook': 'sme-logbook-laf-seed.md',
}


class MainLafRegistryDocumentationTests(SimpleTestCase):
    maxDiff = None

    def test_registry_has_six_unique_reviewed_main_lafs(self):
        self.assertEqual({item.key for item in DEFINITIONS}, set(DOCUMENT_NAMES))
        self.assertEqual(len({item.document_type for item in DEFINITIONS}), 6)
        self.assertEqual(len({item.filename for item in DEFINITIONS}), 6)
        for definition in DEFINITIONS:
            self.assertRegex(definition.sha256, r'^[0-9a-f]{64}$')
            self.assertGreater(definition.byte_size, 0)
            self.assertGreater(definition.page_count, 0)

    def test_every_seed_constant_is_documented_in_its_laf_reference(self):
        for definition in DEFINITIONS:
            path = Path(settings.BASE_DIR) / 'docs' / 'origination' / DOCUMENT_NAMES[definition.key]
            self.assertTrue(path.is_file(), f'Missing dedicated LAF reference: {path}')
            document = path.read_text(encoding='utf-8')
            self.assertIn(definition.filename, document)
            for token in (
                definition.sha256, definition.document_type,
                *(item[0] for item in definition.sections),
                *(item['key'] for item in definition.fields),
                *(item['type'] for item in definition.fields),
                *(item['role'] for item in definition.signers),
                *(slot['key'] for signer in definition.signers for slot in signer.get('slots', [])),
                *(slot.get('type', 'signature') for signer in definition.signers for slot in signer.get('slots', [])),
                *(item['key'] for item in definition.evidence),
            ):
                self.assertIn(f'`{token}`', document, f'{definition.key} does not document {token}')
            for field in definition.fields:
                for option in field.get('options') or []:
                    self.assertIn(f"`{option['code']}`", document)
                for column in (field.get('structure') or {}).get('columns', []):
                    self.assertIn(f"`{column['key']}`", document)
                    self.assertIn(f"`{column['type']}`", document)
            self.assertIn('human-owned', document.casefold())


class MainLafSeedTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser(
            username='main-laf-seed-admin', email='laf-seed@example.test', password='password',
        )
        self.product = Product.objects.create(name='Synthetic LAF Product', code='synthetic_laf')
        ProductVersion.objects.create(
            product=self.product, version=1, status=ProductVersion.STATUS_DRAFT,
            created_by=self.actor,
        )
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pdf = self.root / 'Synthetic Main LAF.pdf'
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        with self.pdf.open('wb') as stream:
            writer.write(stream)
        data = self.pdf.read_bytes()
        self.definition = MainLafDefinition(
            key='synthetic', filename=self.pdf.name,
            sha256=hashlib.sha256(data).hexdigest(), byte_size=len(data), page_count=1,
            document_type='synthetic_main_laf', name='Synthetic Main LAF',
            product_code=self.product.code,
            sections=(('applicant_details', 'Applicant Details', 'Identity.'),),
            fields=(
                _field('synthetic_applicant_name', 'Applicant Name', 'text', 'applicant_details', required=True),
                _field('synthetic_applicant_id', 'Applicant ID', 'national_id', 'applicant_details', required=True),
                _field('synthetic_applicant_phone', 'Applicant Phone', 'phone', 'applicant_details', required=True),
            ),
            signers=(_signer('borrower', 'Borrower', identity_fields={
                'name': 'synthetic_applicant_name', 'national_id': 'synthetic_applicant_id',
                'phone': 'synthetic_applicant_phone',
            }),),
        )

    def _uploaded(self, template, **_kwargs):
        template.status = template.STATUS_READY
        template.drive_file_id = 'synthetic-drive-file'
        template.drive_url = 'https://drive.example.test/synthetic'
        template.upload_error = ''
        template.save(update_fields=['status', 'drive_file_id', 'drive_url', 'upload_error'])
        return template

    def test_preflight_validates_without_writing(self):
        before = (OriginationDataField.objects.count(), OriginationDocumentTemplate.objects.count())
        plan = preflight_seed(self.definition, laf_root=self.root)
        self.assertEqual(plan['sha256'], self.definition.sha256)
        self.assertEqual(before, (
            OriginationDataField.objects.count(), OriginationDocumentTemplate.objects.count(),
        ))

    @patch('core.management.commands.seed_origination_main_lafs.selected_definitions')
    def test_command_is_dry_run_by_default(self, selected):
        selected.return_value = (self.definition,)
        output = StringIO()
        call_command(
            'seed_origination_main_lafs', '--laf-root', str(self.root),
            '--laf', 'invoice_finance', '--actor', self.actor.username, stdout=output,
        )
        self.assertIn('Dry run: Synthetic Main LAF', output.getvalue())
        self.assertIn('No database records or Drive files were changed.', output.getvalue())
        self.assertFalse(OriginationDocumentTemplate.objects.exists())

    def test_preflight_rejects_source_drift_and_missing_products(self):
        with self.assertRaisesRegex(MainLafSeedError, 'does not match the reviewed contract'):
            preflight_seed(replace(self.definition, sha256='0' * 64), laf_root=self.root)
        with self.assertRaisesRegex(MainLafSeedError, 'does not exist'):
            preflight_seed(replace(self.definition, product_code='missing_product'), laf_root=self.root)

    @override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic-folder')
    @patch('core.services.origination_main_laf_seeds.upload_template_record')
    def test_apply_is_idempotent_and_sets_exact_catalogue_eligibility(self, upload):
        upload.side_effect = self._uploaded
        first = apply_seed(self.definition, laf_root=self.root, actor=self.actor)
        second = apply_seed(self.definition, laf_root=self.root, actor=self.actor)

        self.assertEqual(first['template'].pk, second['template'].pk)
        self.assertEqual(upload.call_count, 1)
        template = first['template']
        self.assertIsNone(template.product_definition_id)
        self.assertEqual(template.document_role, OriginationDocumentTemplate.ROLE_PRIMARY)
        self.assertEqual(template.document_key, 'primary')
        self.assertEqual(template.status, OriginationDocumentTemplate.STATUS_READY)
        self.assertEqual(
            set(template.product_eligibilities.values_list('product__code', flat=True)),
            {'synthetic_laf'},
        )
        self.assertEqual(OriginationDocumentProductEligibility.objects.count(), 1)

    @override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic-folder')
    @patch('core.services.origination_main_laf_seeds.upload_template_record')
    def test_changed_contract_creates_successor_without_mutating_active_version(self, upload):
        upload.side_effect = self._uploaded
        first = apply_seed(self.definition, laf_root=self.root, actor=self.actor)['template']
        first.status = first.STATUS_ACTIVE
        first.save(update_fields=['status'])
        changed = replace(
            self.definition,
            fields=(*self.definition.fields, _field(
                'synthetic_optional_note', 'Optional Note', 'text', 'applicant_details',
            )),
        )

        successor = apply_seed(changed, laf_root=self.root, actor=self.actor)['template']

        first.refresh_from_db()
        self.assertEqual(first.status, first.STATUS_ACTIVE)
        self.assertEqual(first.version, 1)
        self.assertEqual(successor.version, 2)
        self.assertNotEqual(first.pk, successor.pk)

    @override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic-folder')
    @patch('core.services.origination_main_laf_seeds.upload_template_record')
    def test_manual_allowlist_widening_is_not_silently_accepted(self, upload):
        upload.side_effect = self._uploaded
        first = apply_seed(self.definition, laf_root=self.root, actor=self.actor)['template']
        extra = Product.objects.create(name='Other Product', code='other_product')
        OriginationDocumentProductEligibility.objects.create(
            template=first, product=extra, created_by=self.actor,
        )

        successor = apply_seed(self.definition, laf_root=self.root, actor=self.actor)['template']

        self.assertNotEqual(first.pk, successor.pk)
        self.assertEqual(
            set(successor.product_eligibilities.values_list('product__code', flat=True)),
            {'synthetic_laf'},
        )

    def test_inactive_superuser_is_rejected(self):
        self.actor.is_active = False
        self.actor.save(update_fields=['is_active'])
        with self.assertRaisesRegex(MainLafSeedError, 'active Django Superuser'):
            apply_seed(self.definition, laf_root=self.root, actor=self.actor)

    def test_source_path_accepts_main_parent_or_direct_main_directory(self):
        nested_root = self.root / 'nested'
        main = nested_root / 'MAIN'
        main.mkdir(parents=True)
        nested_pdf = main / self.definition.filename
        nested_pdf.write_bytes(self.pdf.read_bytes())
        self.assertEqual(source_path(self.definition, main), nested_pdf)
        self.assertEqual(source_path(self.definition, nested_root), nested_pdf)

    def _application(self, *, reference, applicant_id='12345678', payload=None, requirements=None):
        definition, _created = OriginationProductDefinition.objects.get_or_create(
            product_key='synthetic_laf', version=1,
            defaults={
                'name': 'Synthetic LAF Product',
                'product_version': self.product.versions.get(version=1),
                'form_schema': {'fields': []}, 'signer_rules': [],
                'document_type': 'synthetic_main_laf', 'created_by': self.actor,
            },
        )
        values = {'applicant_id_number': applicant_id, **(payload or {})}
        return LoanOriginationApplication.objects.create(
            reference_number=reference, product_definition=definition,
            product_version=self.product.versions.get(version=1), officer=self.actor,
            branch='EMBU', form_payload=values,
            product_terms_snapshot={'requirements': requirements or []},
        )

    def test_invoice_id_evidence_is_required_only_for_first_non_cancelled_application(self):
        requirement = {
            'key': 'applicant_id_copy', 'label': 'Applicant ID', 'type': 'document',
            'workflow': 'loan_origination', 'enforcement_stage': 'review', 'required': False,
            'validation': {'required_when': {'operator': 'first_origination_application'}},
        }
        first = self._application(reference='ORG-FIRST-ID', requirements=[requirement])
        self.assertEqual(
            [item['key'] for item in _missing_application_requirements(first, stage='review')],
            ['applicant_id_copy'],
        )
        second = self._application(reference='ORG-SECOND-ID', requirements=[requirement])
        self.assertEqual(_missing_application_requirements(second, stage='review'), [])
        first.status = first.STATUS_CANCELLED
        first.save(update_fields=['status'])
        self.assertEqual(
            [item['key'] for item in _missing_application_requirements(second, stage='review')],
            ['applicant_id_copy'],
        )

    def test_sme_totals_are_derived_in_preview_context(self):
        application = self._application(
            reference='ORG-SME-TOTALS',
            payload={
                'business_sales_amount': '100000',
                'business_other_income_lines': [{'amount': '5000'}],
                'business_purchases_amount': '40000', 'business_rent_expense': '10000',
                'business_payroll_expense': '5000', 'business_utilities_expense': '2500',
                'business_other_expense': '1500', 'net_monthly_salary': '20000',
                'household_spouse_net_salary': '10000', 'household_other_income': '5000',
                'household_rent_expense': '8000', 'household_food_expense': '7000',
            },
        )
        context = preview_context(application)
        self.assertEqual(context['business_total_income'], '105000')
        self.assertEqual(context['business_total_expenses'], '59000')
        self.assertEqual(context['business_net_surplus'], '46000')
        self.assertEqual(context['household_total_income'], '35000')
        self.assertEqual(context['household_total_expenses'], '15000')
        self.assertEqual(context['household_net_surplus'], '20000')
