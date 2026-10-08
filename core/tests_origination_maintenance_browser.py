"""Real admin requests against an isolated live server; all documents are synthetic."""
import os
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
        self.assertEqual(definition.events.filter(action='maintenance_applied').count(), 2)
