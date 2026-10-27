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
from .crypto import decrypt_secret
from .initial_setup import prepare_setup, preview_setup
from .lifecycle import apply_change
from .models import StaffBrowserAdmission
from .tests import PASSWORD, TEST_KEY, admit_synthetic_user


class TransportClosureTests(SimpleTestCase):
    def test_json_feedback_does_not_queue_native_flash_messages(self):
        from django.contrib import messages
        from django.contrib.messages.storage.fallback import FallbackStorage
        from .adapters import StaffAccountAdapter
        request = RequestFactory().post('/')
        request.session = {}
        request._messages = FallbackStorage(request)
        request._staff_browser_json_feedback = True
        StaffAccountAdapter(request).add_message(request, messages.SUCCESS, message='Synthetic native feedback')
        self.assertEqual(list(messages.get_messages(request)), [])

    def test_other_requests_retain_native_flash_messages(self):
        from django.contrib import messages
        from django.contrib.messages.storage.fallback import FallbackStorage
        from .adapters import StaffAccountAdapter
        request = RequestFactory().get('/')
        request.session = {}
        request._messages = FallbackStorage(request)
        StaffAccountAdapter(request).add_message(request, messages.SUCCESS, message='Synthetic native feedback')
        self.assertEqual([str(item) for item in messages.get_messages(request)], ['Synthetic native feedback'])

    @override_settings(ROOT_URLCONF='config.urls',STAFF_BROWSER_AUTH_ENABLED=False)
    def test_production_routes_remain_closed_with_flag_off(self):
        for url in ('/staff/', '/api/staff/auth/v1/session/',
                    '/api/staff/auth/v1/setup/session/', '/api/staff/auth/v1/setup/verify-email/',
                    '/api/staff/auth/v1/setup/password/', '/api/staff/auth/v1/enrollment/session/',
                    '/api/staff/auth/v1/enrollment/begin/', '/api/staff/auth/v1/enrollment/confirm/',
                    '/api/staff/auth/v1/enrollment/recovery-codes/'):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code,404)
        for url in ('/access.html','/test-context/identity/'):
            with self.assertRaises(Resolver404): resolve(url,urlconf='config.urls')

    def test_harness_refuses_non_test_configuration(self):
        from .transport_test_urls import _guard
        from django.core.exceptions import ImproperlyConfigured
        with override_settings(STAFF_BROWSER_TRANSPORT_TEST=False), self.assertRaises(ImproperlyConfigured):
            _guard()

    def test_every_test_auth_handler_rejects_non_test_configuration(self):
        from django.core.exceptions import ImproperlyConfigured
        for action in ('session', 'login', 'mfa', 'logout', 'setup/session', 'setup/verify-email', 'setup/password',
                       'enrollment/session', 'enrollment/begin', 'enrollment/confirm', 'enrollment/recovery-codes'):
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
    ACCOUNT_EMAIL_NOTIFICATIONS=False, ACCOUNT_CHANGE_EMAIL=False,
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
        self.new_user = get_user_model().objects.create_user('onboarding_staff', 'onboarding@example.invalid')
        apply_change(actor=self.root, target_user_id=self.new_user.pk, action='authorize', expected_revision=0,
                     request_key='synthetic-onboarding-admission', reason='Synthetic explicit onboarding admission')
        preview = preview_setup(actor=self.root, target_user_id=self.new_user.pk)
        self.setup_receipt = prepare_setup(actor=self.root, target_user_id=self.new_user.pk,
                                          expected_revision=preview['revision'], snapshot_fingerprint=preview['snapshot_fingerprint'],
                                          request_key='synthetic-transport-setup', reason='Synthetic guided onboarding test')
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
        from .models import StaffBrowserSetupGrant
        grant = StaffBrowserSetupGrant.objects.get(pk=self.setup_receipt['setup_id'])
        config = {'origin': self.live_server_url, 'username': self.user.username, 'password': PASSWORD,
                  'secret': self.secret, 'recovery': self.recovery, 'build': settings.STAFF_BROWSER_TRANSPORT_BUILD,
                  'setup': {'id': str(grant.pk), 'proof': decrypt_secret(grant.confirmation_cipher), 'username': self.new_user.username}}
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
        self.new_user.refresh_from_db()
        self.assertTrue(self.new_user.check_password(PASSWORD))
        self.assertTrue(EmailAddress.objects.get(user=self.new_user).verified)
        self.assertEqual(Authenticator.objects.filter(user=self.new_user).count(), 2)
        grant.refresh_from_db()
        self.assertEqual(grant.state, StaffBrowserSetupGrant.COMPLETED)
        self.assertEqual(grant.confirmation_cipher, '')
        print(f"Closed React/Django integration: {result['checks']} checks, {result['captures']} synthetic captures; no grants or external delivery.")


@override_settings(STAFF_BROWSER_TRANSPORT_BUILD='dist-authentication-development')
class BrowserTransportDevelopmentTests(BrowserTransportTests):
    """Repeat the native boundary with the separate development/StrictMode build."""
