"""Real Mini App/Admin shell with isolated sessions and synthetic storage."""
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings

from origination import tests_identity_copies as fixtures
from origination.tests_workflow_improvements import pdf
from core.tests_jbl_visit_documents import photo


@override_settings(ORIGINATION_WEBAPP_REQUIRE_TELEGRAM_AUTH=False,
    ALLOWED_HOSTS=['localhost','127.0.0.1','testserver'], GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic')
class OriginationImprovementsBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        fixtures.IdentityEvidenceTests.setUp(self)
        self.client.force_login(self.actor)
        storage=patch('core.services.order_approval.GoogleDriveMediaStorage')
        storage.start().return_value.upload.return_value=('synthetic-private-file','https://example.test/private')
        self.addCleanup(storage.stop)

    def test_camera_multi_upload_and_delete_in_real_shell(self):
        output=Path(settings.BASE_DIR)/'test-results/origination-improvements-live'
        output.mkdir(parents=True,exist_ok=True)
        (output/'synthetic-id.jpg').write_bytes(photo('id.jpg',1).read())
        (output/'synthetic-id.pdf').write_bytes(pdf().read())
        result=subprocess.run(['node',str(Path(settings.BASE_DIR)/'scripts/test_origination_improvements_browser.js'),
            self.live_server_url,str(output)],cwd=settings.BASE_DIR,
            env={**os.environ,'QA_SESSION_ID':self.client.cookies[settings.SESSION_COOKIE_NAME].value},
            capture_output=True,text=True,timeout=120)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertFalse(type(self.app).objects.filter(pk=self.app.pk).exists())

    def test_setup_footer_explains_remaining_task_after_autosave(self):
        from core import tests_origination_setup as setup
        from origination.models import OriginationProductDefinition
        from django.urls import reverse
        setup.OriginationSetupWorkspaceTests.setUp(self)
        setup.OriginationSetupWorkspaceTests.test_terms_can_save_without_forcing_optional_repeatable_rows(self)
        definition=OriginationProductDefinition.objects.get(product_key='optional_rows_loan')
        url=self.live_server_url+reverse('admin:origination_origination_setup_step',args=[definition.pk,'identity'])
        output=Path(settings.BASE_DIR)/'test-results/origination-improvements-live'
        output.mkdir(parents=True,exist_ok=True)
        result=subprocess.run(['node',str(Path(settings.BASE_DIR)/'scripts/test_origination_improvements_browser.js'),
            url,str(output),'setup'],cwd=settings.BASE_DIR,
            env={**os.environ,'QA_SESSION_ID':self.client.cookies[settings.SESSION_COOKIE_NAME].value},
            capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
