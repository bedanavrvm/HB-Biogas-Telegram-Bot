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
