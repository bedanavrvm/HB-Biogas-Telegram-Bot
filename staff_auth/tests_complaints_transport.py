"""Opt-in real React -> native company login -> owning Complaints reads."""
import json
import os
from pathlib import Path
from queue import Queue
import socket
import subprocess
import threading
from unittest import skipUnless
from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.mfa.recovery_codes.internal.auth import RecoveryCodes
from allauth.mfa.totp.internal.auth import TOTP, generate_totp_secret
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import LiveServerTestCase, override_settings

from core.models import AccessGrant, CaseUpdate, ComplianceAuditChainState, GroupSheetConfiguration, ParsedMessage
from core.services.access_grant_governance import governed_access_grant_mutation
from core.tests_browser_complaints import seed_complaint_policy, synthetic_case
from .lifecycle import apply_change
from .models import StaffBrowserAdmission
from .tests import PASSWORD, TEST_KEY, admit_synthetic_user


@skipUnless(os.environ.get('RUN_STAFF_BROWSER_E2E') == '1', 'Opt-in isolated browser integration.')
@override_settings(ROOT_URLCONF='staff_auth.complaints_transport_test_urls', STAFF_BROWSER_TRANSPORT_TEST=True,
    STAFF_BROWSER_TRANSPORT_BUILD='dist-complaints', STAFF_BROWSER_AUTH_ENABLED=True,
    STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY], EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
    ACCOUNT_EMAIL_NOTIFICATIONS=False, ACCOUNT_CHANGE_EMAIL=False)
class ComplaintsTransportTests(LiveServerTestCase):
    def setUp(self):
        cache.clear()
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        seed_complaint_policy()
        self.enterContext(governed_access_grant_mutation('Synthetic closed Complaints browser fixture'))
        self.user = get_user_model().objects.create_user('complaints_transport', 'complaints@example.invalid', PASSWORD)
        admit_synthetic_user(self.user)
        EmailAddress.objects.create(user=self.user, email=self.user.email, primary=True, verified=True)
        TOTP.activate(self.user, generate_totp_secret())
        self.codes = RecoveryCodes.activate(self.user).get_unused_codes()
        self.group = GroupSheetConfiguration.objects.create(group_id='synthetic-complaints-transport',
            display_name='Synthetic Complaints', workflow={'type': 'case'}, complaint_sheet_projection_enabled=False)
        self.other = GroupSheetConfiguration.objects.create(group_id='synthetic-other-transport',
            display_name='EXCLUDED_OTHER_GROUP', workflow={'type': 'case'}, complaint_sheet_projection_enabled=False)
        self.grant = AccessGrant.objects.create(user=self.user, workflow='complaint_cases', role='OFFICER', group_configuration=self.group)
        self.cases = [synthetic_case(self.group, index) for index in range(7)]
        self.closed = synthetic_case(self.group, 8, complaint_status='Closed')
        self.foreign = synthetic_case(self.other, 0)
        CaseUpdate.objects.create(parsed_message=self.cases[0], group_id=self.group.group_id, old_status='Open',
            new_status='Open', source='mini_app_comment', updated_by='Synthetic Resolver',
            resolution_text='EXCLUDED_HISTORY_NOTE', raw_update_text='EXCLUDED_RAW_UPDATE')
        original = socket.socket.connect

        def loopback_only(sock, address):
            if not isinstance(address, tuple) or address[0] not in ('localhost', '127.0.0.1', '::1'):
                raise AssertionError('External network forbidden in closed Complaints tests.')
            return original(sock, address)
        self.enterContext(patch('socket.socket.connect', loopback_only))

    def control(self, command):
        if command == 'revoke_browser':
            row = StaffBrowserAdmission.objects.get(user=self.user)
            apply_change(actor=get_user_model().objects.get(username='synthetic_admission_root'), target_user_id=self.user.pk,
                action='revoke_sessions', expected_revision=row.revision, request_key='synthetic-read-revoke', reason='Synthetic browser boundary')
        elif command == 'revoke_workflow':
            self.grant.delete()
        else:
            raise AssertionError('Unknown synthetic test command')

    def test_native_authenticated_complaints_workspace(self):
        from .transport_test_urls import assets
        assets(complaints=True)
        root = Path(settings.BASE_DIR)
        child = subprocess.Popen([os.environ.get('STAFF_BROWSER_TEST_NODE', 'node'), str(root / 'scripts/test_complaints_browser_transport.js')],
            cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        queue = Queue()

        def read_output():
            for line in child.stdout:
                queue.put(line)
            queue.put(None)
        threading.Thread(target=read_output, daemon=True).start()
        child.stdin.write(json.dumps({'origin': self.live_server_url, 'username': self.user.username, 'password': PASSWORD,
            'codes': self.codes[:2], 'build': settings.STAFF_BROWSER_TRANSPORT_BUILD,
            'group': str(self.group.pk), 'other': str(self.other.pk), 'foreign': str(self.foreign.pk)}) + '\n')
        child.stdin.flush()
        result = None
        try:
            while result is None:
                line = queue.get(timeout=100)
                if line is None:
                    self.fail('Complaints runner exited before result: ' + child.stderr.read()[-3000:])
                message = json.loads(line)
                if 'control' in message:
                    self.control(message['control'])
                    child.stdin.write('{"ok":true}\n'); child.stdin.flush()
                else:
                    result = message
            child.stdin.close(); child.wait(timeout=15)
            self.assertEqual(child.returncode, 0, child.stderr.read()[-3000:])
            self.assertTrue(result.get('passed'), result)
        finally:
            if child.poll() is None:
                child.kill(); child.wait(timeout=5)
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream and not stream.closed:
                    stream.close()
        self.assertEqual(ParsedMessage.objects.filter(group_id=self.group.group_id, complaint_status='Open').count(), 7)
        self.assertEqual(CaseUpdate.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 0)
        print(f"Closed Complaints {settings.STAFF_BROWSER_TRANSPORT_BUILD}: {result['checks']} checks, {result['captures']} captures")


@override_settings(STAFF_BROWSER_TRANSPORT_BUILD='dist-complaints-development')
class ComplaintsDevelopmentTransportTests(ComplaintsTransportTests):
    """Same native boundary under development / React StrictMode."""
