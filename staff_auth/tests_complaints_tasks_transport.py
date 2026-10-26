"""Native-session recovery of settings, schedules and one-off report requests."""
import json
import os
from pathlib import Path
import subprocess
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings

from core.models import AccessGrant
from .tests import PASSWORD
from . import tests_complaints_operations_transport as transport


class ComplaintsTasksTransportTests(transport.ComplaintsOperationsTransportTests):
    test_native_authenticated_complaints_workspace = None

    def test_settings_and_report_tasks_survive_session_loss(self):
        AccessGrant.objects.create(user=self.user, workflow='complaint_cases', role='IT', group_configuration=self.group)
        root = Path(settings.BASE_DIR)
        with patch('report_delivery.dispatch.wake_deliveries'), override_settings(
            REPORT_EMAIL_DELIVERY_ENABLED=True, RESEND_API_KEY='synthetic-only',
            REPORT_EMAIL_FROM='Synthetic <reports@example.invalid>',
        ):
            result = subprocess.run([os.environ.get('STAFF_BROWSER_TEST_NODE', 'node'),
                str(root / 'scripts/test_complaints_tasks_transport.js')],
                input=json.dumps({'origin': self.live_server_url, 'username': self.user.username,
                    'password': PASSWORD, 'codes': self.codes[:5], 'group': str(self.group.pk),
                    'build': settings.STAFF_BROWSER_TRANSPORT_BUILD}),
                cwd=root, capture_output=True, text=True, encoding='utf-8', timeout=180)
        self.assertEqual(result.returncode, 0, result.stderr[-5000:])
        self.assertTrue(json.loads(result.stdout)['passed'])


@override_settings(STAFF_BROWSER_TRANSPORT_BUILD='dist-complaints-operations-development')
class ComplaintsTasksDevelopmentTransportTests(ComplaintsTasksTransportTests):
    """The same native recovery checks under StrictMode."""
