"""Opt-in real React/native-session Complaints operations; synthetic only."""
import json
import os
from pathlib import Path
import subprocess
from unittest import skipUnless

from django.conf import settings
from django.test import override_settings

from core.models import AccessGrant, CaseUpdate
from . import tests_complaints_transport as transport
from .tests import PASSWORD


@skipUnless(os.environ.get('RUN_STAFF_BROWSER_E2E') == '1', 'Opt-in isolated browser integration.')
@override_settings(ROOT_URLCONF='staff_auth.complaints_operations_test_urls',
                   STAFF_BROWSER_TRANSPORT_BUILD='dist-complaints-operations',
                   STAFF_BROWSER_COMPLAINTS_ENABLED=True)
class ComplaintsOperationsTransportTests(transport.ComplaintsTransportTests):
    def test_native_authenticated_complaints_workspace(self):
        from .transport_test_urls import assets
        assets(operations=True)
        AccessGrant.objects.create(user=self.user, workflow='complaint_cases', role='IT', group_configuration=self.group)
        root = Path(settings.BASE_DIR)
        result = subprocess.run([os.environ.get('STAFF_BROWSER_TEST_NODE', 'node'),
            str(root / 'scripts/test_complaints_operations_transport.js')],
            input=json.dumps({'origin': self.live_server_url, 'username': self.user.username,
                'password': PASSWORD,
                'code': self.codes[0], 'group': str(self.group.pk), 'build': settings.STAFF_BROWSER_TRANSPORT_BUILD}),
            cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=240)
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        report = json.loads(result.stdout)
        self.assertTrue(report['passed'], report)
        self.assertEqual(CaseUpdate.objects.filter(resolution_text='Synthetic browser follow-up.').count(), 1)
        print(f"Closed operations: {report['captures']} captures, native comment/draft/export/history checks passed")


@override_settings(STAFF_BROWSER_TRANSPORT_BUILD='dist-complaints-operations-development')
class ComplaintsOperationsDevelopmentTransportTests(ComplaintsOperationsTransportTests):
    """Same native workflow under development and React StrictMode."""
