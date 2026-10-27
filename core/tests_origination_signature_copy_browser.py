"""Repeat one person's calibrated signature through the native Admin editor."""
import os
from pathlib import Path
import shutil
import subprocess
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse

from core import tests_origination_document_editor as editor_tests


@skipUnless(shutil.which('node'), 'Node required for native editor verification.')
@override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic-folder', ALLOWED_HOSTS=['localhost', '127.0.0.1', 'testserver'])
class OriginationSignatureCopyBrowserTests(StaticLiveServerTestCase):
    setUp = editor_tests.DocumentEditorTests.setUp
    save = editor_tests.DocumentEditorTests.save
    ready = editor_tests.DocumentEditorTests.ready

    def test_copy_signature_keeps_one_person_and_survives_reload(self):
        document = self.ready()
        destination = self.live_server_url + reverse(
            'admin:origination_originationdocumenttemplate_calibrate', args=[document.pk])
        result = subprocess.run(['node', str(Path(settings.BASE_DIR) / 'scripts/test_origination_signature_copy.js'), destination],
            cwd=settings.BASE_DIR, env={**os.environ, 'QA_SESSION_ID': self.client.cookies[settings.SESSION_COOKIE_NAME].value},
            capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        document.refresh_from_db()
        self.assertEqual(len(document.signer_rules), 1)
        self.assertEqual(document.signer_rules[0]['role'], 'borrower')
        self.assertIn('borrower.signature_copy', document.configuration_revisions.latest('revision').configuration['signature_overlay_manifest']['slots'])

    def test_numeric_placement_words_toggle_survives_reload(self):
        from copy import deepcopy
        from origination.services.origination_templates import save_calibration_draft
        document=self.ready()
        from origination.models import OriginationDataField
        OriginationDataField.objects.create(key='synthetic_amount',label='Synthetic amount',data_type='money',created_by=self.actor)
        document.form_schema['fields'].append({'key':'synthetic_amount','label':'Synthetic amount','type':'money','section_key':'applicant'})
        document.save(update_fields=['form_schema'])
        config=deepcopy(document.configuration_revisions.latest('revision').configuration)
        config['sample_context']={'synthetic_amount':'150000'}
        config['field_overlay_manifest']['fields']['synthetic_amount']={'context_key':'synthetic_amount','page_number':1,
            'box':{'x':10,'y':300,'width':500,'height':25}}
        save_calibration_draft(template=document,configuration=config,actor=self.actor,expected_revision=2,client_request_id='numeric-word-placement')
        result=subprocess.run(['node',str(Path(settings.BASE_DIR)/'scripts/test_origination_words_browser.js'),
            self.live_server_url+reverse('admin:origination_originationdocumenttemplate_calibrate',args=[document.pk])],
            cwd=settings.BASE_DIR,env={**os.environ,'QA_SESSION_ID':self.client.cookies[settings.SESSION_COOKIE_NAME].value},
            capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        document.refresh_from_db()
        self.assertEqual(document.configuration_revisions.latest('revision').configuration['field_overlay_manifest']['fields']['synthetic_amount']['value_format'],'number_words')
