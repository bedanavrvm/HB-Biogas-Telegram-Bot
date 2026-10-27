"""Real admin requests against an isolated live server; all documents are synthetic."""
import os
import base64
import shutil
import subprocess
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from core import tests_origination_setup as setup_tests
from core.tests_origination_templates import synthetic_pdf
from origination.models import OriginationProductDefinition


@skipUnless(shutil.which('node'), 'Node is required for the local browser journey.')
@override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic-folder', ALLOWED_HOSTS=['localhost', '127.0.0.1', 'testserver'])
class OriginationMaintenanceBrowserTests(StaticLiveServerTestCase):
    _ready_document = setup_tests.OriginationSetupWorkspaceTests._ready_document
    _publish_guided = setup_tests.OriginationSetupWorkspaceTests._publish_guided
    _documents_url = setup_tests.OriginationSetupWorkspaceTests._documents_url

    def setUp(self):
        from core.models import ComplianceAuditChainState
        # TransactionTestCase flush removes migration-seeded singletons.
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        setup_tests.OriginationSetupWorkspaceTests.setUp(self)
        storage = patch('core.services.order_approval.GoogleDriveMediaStorage')
        mock_storage = storage.start()
        mock_storage.return_value.download.return_value = synthetic_pdf()
        self.addCleanup(storage.stop)
        upload=patch('origination.services.origination_templates._upload_template_bytes',return_value=('synthetic-custom','https://example.test/synthetic.pdf'))
        upload.start();self.addCleanup(upload.stop)

    def test_real_admin_edit_review_apply_and_withdraw(self):
        setup_tests.OriginationSetupWorkspaceTests.test_terms_can_save_without_forcing_optional_repeatable_rows(self)
        definition = OriginationProductDefinition.objects.get(product_key='optional_rows_loan')
        definition.signer_rules = [{'role':'officer', 'required':True}]
        definition.save(update_fields=['signer_rules'])
        self._ready_document(definition)
        response = self._publish_guided(definition)
        self.assertEqual(response.status_code, 302, response.context.get('step_error') if response.context else response.content[:500])
        definition.refresh_from_db()
        destination = self.live_server_url + self._documents_url(definition)
        env = {**os.environ, 'QA_SESSION_ID':self.client.cookies[settings.SESSION_COOKIE_NAME].value}
        output = Path(settings.BASE_DIR) / 'test-results' / 'origination-maintenance-live'
        output.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(['node', str(Path(settings.BASE_DIR) / 'scripts' / 'test_origination_maintenance_browser.js'),
                                 destination, str(output)], cwd=settings.BASE_DIR, env=env,
                                capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        definition.refresh_from_db()
        self.assertEqual(definition.product_version.product.versions.count(), 1)
        self.assertEqual(definition.events.filter(action='maintenance_applied').count(), 1)

    def test_published_unassigned_document_attachment(self):
        from origination.models import OriginationDocumentProductEligibility, OriginationDocumentTemplate
        setup_tests.OriginationSetupWorkspaceTests.test_terms_can_save_without_forcing_optional_repeatable_rows(self)
        definition = OriginationProductDefinition.objects.get(product_key='optional_rows_loan')
        definition.signer_rules = [{'role': 'officer', 'required': True}]
        definition.save(update_fields=['signer_rules'])
        document = self._ready_document(definition)
        OriginationDocumentProductEligibility.objects.filter(template=document).delete()
        output = Path(settings.BASE_DIR) / 'test-results' / 'origination-attachment-live'
        output.mkdir(parents=True, exist_ok=True)
        result = subprocess.run([
            'node', str(Path(settings.BASE_DIR) / 'scripts' / 'test_origination_attachment_browser.js'),
            self.live_server_url + self._documents_url(definition), str(output),
        ], cwd=settings.BASE_DIR, env={
            **os.environ, 'QA_SESSION_ID': self.client.cookies[settings.SESSION_COOKIE_NAME].value,
            'QA_DOCUMENT_ID': str(document.pk),
        }, capture_output=True, text=True, timeout=120)
        print(result.stdout)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        definition.refresh_from_db()
        document.refresh_from_db()
        self.assertEqual(definition.lifecycle_status, 'published')
        self.assertEqual(document.status, 'active')
        self.assertEqual(document.configuration_revisions.count(), 1)
        self.assertEqual(OriginationDocumentTemplate.objects.count(), 1)
        self.assertTrue(document.product_eligibilities.filter(product=definition.product_version.product).exists())

    def test_custom_pdf_authoring_journey(self):
        from origination.models import OriginationDocumentTemplate
        from origination.services.origination_templates import initial_template_configuration
        self.client.force_login(self.superuser)
        template = OriginationDocumentTemplate.objects.create(
            document_type='synthetic-custom', version=1, name='Synthetic custom PDF',
            document_role='primary', status='ready', drive_file_id='synthetic-custom',
            page_count=1, source_byte_size=len(synthetic_pdf()), source_sha256=__import__('hashlib').sha256(synthetic_pdf()).hexdigest(),
            form_schema={'fields': [], 'sections': []}, signer_rules=[],
            placement_config=initial_template_configuration(None, form_schema={'fields': []}),
            created_by=self.superuser,
        )
        mode=os.environ.get('ORIGINATION_AUTHORING_MODE', 'final')
        product_url = ''
        if mode != 'baseline':
            setup_tests.OriginationSetupWorkspaceTests.test_terms_can_save_without_forcing_optional_repeatable_rows(self)
            definition = OriginationProductDefinition.objects.get(product_key='optional_rows_loan')
            product_url = self.live_server_url + self._documents_url(definition)
        url = self.live_server_url + (reverse('admin:origination_originationdocumenttemplate_calibrate', args=[template.pk])
                                    if mode == 'baseline' else reverse('admin:origination_document_new')+'?product='+str(definition.product_version.product_id))
        output = Path(settings.BASE_DIR) / 'test-results' / 'origination-authoring'
        output.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(['node', str(Path(settings.BASE_DIR) / 'scripts/test_origination_authoring_browser.js'),
                                 url, str(output), mode],
            cwd=settings.BASE_DIR, env={**os.environ, 'QA_SESSION_ID': self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                                       'QA_PRODUCT_URL':product_url,
                                       'QA_PDF_BASE64':base64.b64encode(synthetic_pdf()).decode('ascii')},
            capture_output=True, text=True, timeout=180)
        print(result.stdout)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if mode != 'baseline':
            self.assertTrue(OriginationDocumentTemplate.objects.filter(name='Synthetic custom loan document',status='active').exists())
            definition.refresh_from_db()
            self.assertEqual(definition.lifecycle_status,'published')
            self.assertTrue(definition.product_version.product.active)

    def test_document_removal_and_shared_identity_are_persistent(self):
        from origination.models import OriginationDocumentTemplate, OriginationDataField
        from origination.services.origination_templates import save_calibration_draft, initial_template_configuration
        from origination.services.origination_fields import template_form_contract
        self.client.force_login(self.superuser)
        for key, label, kind in [('synthetic_main_name', 'Main applicant', 'text'),
                                  ('synthetic_main_phone', 'Main phone', 'phone')]:
            OriginationDataField.objects.create(key=key, label=label, data_type=kind)
        rules = [{'role': 'borrower', 'label': 'Borrower', 'required': True,
            'identity_fields': {'name': 'synthetic_main_name', 'phone': 'synthetic_main_phone', 'national_id': None},
            'slots': [{'key': 'signature', 'type': 'signature', 'required': True}]},
            {'role': 'officer', 'label': 'Officer', 'required': True,
             'slots': [{'key': 'signature', 'type': 'signature', 'required': True}]}]
        configuration = initial_template_configuration(None, form_schema={'fields': []})
        configuration.update(document_type='synthetic-shared-visit', version=1)
        configuration['signature_overlay_manifest']['slots'] = {role + '.signature': {
            'role': role, 'slot_key': 'signature', 'slot_type': 'signature', 'label': role + ' signature',
            'page_number': 1, 'box': {'x': 30, 'y': 100 + index * 60, 'width': 120, 'height': 30}}
            for index, role in enumerate(['borrower', 'officer'])}
        pdf = synthetic_pdf()
        from core.models import Product
        from origination import tests_configuration_isolation as packet_fixtures
        self.actor, self.pdf = self.superuser, pdf
        self.digest = __import__('hashlib').sha256(pdf).hexdigest()
        self.product = Product.objects.create(code='synthetic_shared_main', name='Synthetic shared Main LAF')
        packet_fixtures.SelectedPacketTests.template(self, 'synthetic-main-borrower', [
            {'key': 'synthetic_main_name', 'type': 'text'}, {'key': 'synthetic_main_phone', 'type': 'phone'}],
            [{**rules[0], 'participant_key': 'joint_borrower', 'label': 'Joint borrower'}])
        document = OriginationDocumentTemplate.objects.create(document_type='synthetic-shared-visit',
            version=1, name='Synthetic Home visit', document_role='supporting', document_key='home_visit',
            status='ready', form_schema={'fields': [], 'sections': [], 'required_signer_roles': ['asset_owner', 'officer']},
            signer_rules=rules, drive_file_id='synthetic', source_filename='synthetic.pdf',
            page_count=1, source_byte_size=len(pdf), source_sha256=__import__('hashlib').sha256(pdf).hexdigest(),
            placement_config=configuration, created_by=self.superuser)
        document.product_eligibilities.create(product=self.product, created_by=self.superuser)
        save_calibration_draft(template=document, configuration=configuration, actor=self.superuser,
            expected_revision=0, client_request_id='synthetic-contract-initial')
        output = Path(settings.BASE_DIR) / 'test-results/origination-configuration-browser'
        output.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(['node', str(Path(settings.BASE_DIR) / 'scripts/test_origination_document_configuration_browser.js'),
            self.live_server_url + reverse('admin:origination_originationdocumenttemplate_calibrate', args=[document.pk]), str(output)],
            cwd=settings.BASE_DIR, env={**os.environ, 'QA_SESSION_ID': self.client.cookies[settings.SESSION_COOKIE_NAME].value},
            capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout)
        document.refresh_from_db()
        self.assertEqual([rule['role'] for rule in document.signer_rules], ['borrower'])
        self.assertEqual(template_form_contract(document)[1][0]['identity_fields']['phone'], 'synthetic_main_phone')
        self.assertEqual(document.signer_rules[0]['participant_key'], 'joint_borrower')
        self.assertEqual(document.form_schema['fields'], [])
