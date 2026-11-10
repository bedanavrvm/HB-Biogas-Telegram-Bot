"""Opt-in synthetic evidence from the signed Portal shell; Google is simulated."""
import json
import os
from pathlib import Path
import subprocess
from unittest import skipUnless

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.utils import timezone

from core.models import JawabuFarmerMaster, JawabuPipelineEvent
from core.tests_telegram_authentication import BOT_TOKEN
from portal_legacy.models import LegacyBatch, LegacyRow
from portal_legacy.tests import LegacyHTTPMixin
from portal_legacy.workbook import propose


@skipUnless(os.environ.get('RUN_PORTAL_LEGACY_CREDIT_E2E') == '1', 'Opt-in real Portal/Playwright check')
@override_settings(
    TELEGRAM_BOT_TOKEN=BOT_TOKEN, PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
    SECURE_SSL_REDIRECT=False, DEBUG=True, SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
)
class PortalLegacyCreditBrowserTests(LegacyHTTPMixin, StaticLiveServerTestCase):
    def test_legacy_credit_labels_preserve_pipeline_and_native_decisions(self):
        self.clock.stop()
        batch = LegacyBatch.objects.create(
            group=self.group, namespace='synthetic-credit-labels', source_hash='a' * 64,
            created_by=self.actor,
        )
        cases = []
        examples = [
            ('HISTORICAL REJECTION', 'Rejected', 'rejected', '', 'Legacy'),
            ('HISTORICAL APPROVAL', 'Approved', 'order', '', 'Legacy'),
            ('RECORDED REJECTION', 'Rejected', 'rejected', 'credit_decision_recorded', 'Rejected'),
            ('FRESH CREDIT REVIEW', 'Pending', 'credit', 'jbl_visit_completed', 'Pending'),
        ]
        for number, (name, decision, state, action, label) in enumerate(examples, 2):
            farmer = JawabuFarmerMaster.objects.create(
                group_configuration=self.group, source='portal_legacy', customer_name=name,
                legacy_fulfillment_partner='HB', workflow_state=state, credit_decision=decision,
                final_decision='Approved' if state == 'order' else '',
            )
            values = {'customer_name': name, 'legacy_outcome': decision, 'decision_stage': 'credit'}
            LegacyRow.objects.create(
                batch=batch, source_sheet='Master Data', source_row=number, source_hash='a' * 64,
                values=values, proposal=propose(values), farmer=farmer, committed_at=timezone.now(),
                continuation_confirmed=True, publication_ready=True,
            )
            if action:
                JawabuPipelineEvent.objects.create(farmer=farmer, action=action, stage_key='credit')
            cases.append({'id': str(farmer.pk), 'name': name, 'decision': decision, 'label': label})
        root = Path(settings.BASE_DIR)
        result = subprocess.run(
            [os.environ.get('PORTAL_TEST_NODE', 'node'), str(root/'scripts/test_portal_legacy_credit_labels.js')],
            input=json.dumps({'origin': self.live_server_url,
                              'initData': self.headers['HTTP_X_TELEGRAM_INIT_DATA'], 'cases': cases,
                              'artifacts': str(root/'test-results/legacy-credit-labels')}),
            text=True, capture_output=True, timeout=180, cwd=root,
        )
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-6000:])
        for example in cases:
            farmer = JawabuFarmerMaster.objects.get(pk=example['id'])
            self.assertEqual(farmer.credit_decision, example['decision'])
            self.assertEqual(farmer.workflow_revision, 1)
