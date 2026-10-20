"""Opt-in built React -> real Django/allauth, isolated database and loopback only."""
import json
import os
from pathlib import Path
from queue import Empty, Queue
import socket
import subprocess
import threading
import time
from unittest import skipUnless
from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from allauth.mfa.recovery_codes.internal.auth import RecoveryCodes
from allauth.mfa.totp.internal.auth import TOTP, generate_totp_secret
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core import mail
from django.core.cache import cache
from django.test import LiveServerTestCase, RequestFactory, SimpleTestCase, override_settings
from django.urls import Resolver404, resolve

from core.models import AccessGrant, ComplianceAuditChainState, ComplianceAuditEvent, GroupSheetConfiguration
from .assurance import ASSURANCE_KEY
from .lifecycle import apply_change
from .models import StaffBrowserAdmission
from .tests import PASSWORD, TEST_KEY, admit_synthetic_user


class TransportClosureTests(SimpleTestCase):
    def test_production_routes_stay_unmounted(self):
        for url in ('/staff/', '/access.html', '/api/staff/auth/v1/session/', '/test-context/identity/'):
            with self.subTest(url=url), self.assertRaises(Resolver404):
                resolve(url, urlconf='config.urls')

    def test_harness_refuses_non_test_configuration(self):
        from .transport_test_urls import _guard
        from django.core.exceptions import ImproperlyConfigured
        with override_settings(STAFF_BROWSER_TRANSPORT_TEST=False), self.assertRaises(ImproperlyConfigured):
            _guard()

    def test_every_test_auth_handler_rejects_non_test_configuration(self):
        from django.core.exceptions import ImproperlyConfigured
        for action in ('session', 'login', 'mfa', 'logout'):
            view = resolve(f'/api/staff/auth/v1/{action}/', urlconf='staff_auth.transport_test_urls').func
            with self.subTest(action=action), override_settings(RUNNING_TESTS=False), self.assertRaises(ImproperlyConfigured):
                view(RequestFactory().get('/'))


@skipUnless(os.environ.get('RUN_STAFF_BROWSER_E2E') == '1', 'Opt-in built client/Chromium integration; see browser/README.md.')
@override_settings(
    ROOT_URLCONF='staff_auth.transport_test_urls', STAFF_BROWSER_TRANSPORT_TEST=True,
    STAFF_BROWSER_TRANSPORT_BUILD=os.environ.get('STAFF_BROWSER_TEST_BUILD', 'dist-authentication'),
    STAFF_BROWSER_AUTH_ENABLED=True, STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY],
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
)
class BrowserTransportTests(LiveServerTestCase):
    def setUp(self):
        cache.clear()
        # LiveServer uses TransactionTestCase: flush removes migration seeds.
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.user = get_user_model().objects.create_user('transport_staff', 'staff@example.invalid', PASSWORD)
        admit_synthetic_user(self.user)
        self.root = get_user_model().objects.get(username='synthetic_admission_root')
        EmailAddress.objects.create(user=self.user, email=self.user.email, primary=True, verified=True)
        self.secret = generate_totp_secret()
        TOTP.activate(self.user, self.secret)
        self.recovery = RecoveryCodes.activate(self.user).get_unused_codes()
        GroupSheetConfiguration.objects.create(group_id='synthetic-browser-complaints', workflow={'type': 'case'}, complaint_sheet_projection_enabled=False)
        self.grant_count = AccessGrant.objects.count()
        original = socket.socket.connect

        def loopback_only(sock, address):
            if not isinstance(address, tuple) or address[0] not in ('localhost', '127.0.0.1', '::1'):
                raise AssertionError('External network forbidden in transport tests.')
            return original(sock, address)

        self.network = patch('socket.socket.connect', loopback_only)
        self.network.start()
        self.addCleanup(self.network.stop)

    def control(self, command):
        if command in ('revoke', 'authorize'):
            row = StaffBrowserAdmission.objects.get(user=self.user)
            apply_change(actor=self.root, target_user_id=self.user.pk, action='suspend' if command == 'revoke' else command,
                         expected_revision=row.revision, request_key=f'transport-{command}-{row.revision}',
                         reason='Synthetic end-to-end lifecycle test')
        elif command == 'expire':
            for session in Session.objects.all():
                data = session.get_decoded()
                if ASSURANCE_KEY in data:
                    from django.contrib.sessions.backends.db import SessionStore
                    store = SessionStore(session_key=session.session_key)
                    marker = store[ASSURANCE_KEY]
                    store[ASSURANCE_KEY] = {**marker, 'at': time.time() - settings.STAFF_BROWSER_SESSION_AGE_SECONDS - 1}
                    store.save()
        elif command == 'unenroll':
            Authenticator.objects.filter(user=self.user).delete()
        else:
            raise AssertionError('Unexpected test control command.')

    def test_real_browser_password_mfa_and_failure_boundaries(self):
        from .transport_test_urls import assets
        assets()  # Stale/missing builds fail before any credential is passed.
        root = Path(settings.BASE_DIR)
        node = os.environ.get('STAFF_BROWSER_TEST_NODE', 'node')
        child = subprocess.Popen([node, str(root / 'scripts/test_staff_browser_transport.js')], cwd=root,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8')
        queue = Queue()
        def read_output():
            for line in child.stdout:
                queue.put(line)
            queue.put(None)
        threading.Thread(target=read_output, daemon=True).start()
        config = {'origin': self.live_server_url, 'username': self.user.username, 'password': PASSWORD,
                  'secret': self.secret, 'recovery': self.recovery, 'build': settings.STAFF_BROWSER_TRANSPORT_BUILD}
        child.stdin.write(json.dumps(config) + '\n')
        child.stdin.flush()
        result = None
        try:
            while result is None:
                try:
                    line = queue.get(timeout=100)
                except Empty:
                    self.fail('Browser transport test timed out; no credentials are included in this error.')
                if line is None:
                    frames = '\n'.join(row for row in child.stderr.read().splitlines() if row.lstrip().startswith('at '))
                    self.fail('Browser runner exited before a result. Stack frames only:\n' + frames[-3000:])
                message = json.loads(line)
                if 'control' in message:
                    self.control(message['control'])
                    child.stdin.write('{"ok":true}\n')
                    child.stdin.flush()
                else:
                    result = message
            child.stdin.close()
            child.wait(timeout=15)
            self.assertEqual(child.returncode, 0, 'Closed browser integration failed: ' + child.stderr.read()[-4000:])
            self.assertTrue(result.get('passed'), result)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream and not stream.closed:
                    stream.close()
        self.assertEqual(AccessGrant.objects.count(), self.grant_count)
        self.assertGreaterEqual(ComplianceAuditEvent.objects.filter(action='staff_browser.login_completed', actor=self.user).count(), 2)
        self.assertEqual(len(mail.outbox), 0)
        print(f"Closed React/Django integration: {result['checks']} checks, {result['captures']} synthetic captures; no grants or external delivery.")


@override_settings(STAFF_BROWSER_TRANSPORT_BUILD='dist-authentication-development')
class BrowserTransportDevelopmentTests(BrowserTransportTests):
    """Repeat the native boundary with the separate development/StrictMode build."""
