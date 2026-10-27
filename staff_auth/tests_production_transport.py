"""Real native production build on isolated Django/PostgreSQL with synthetic staff."""
import json
import os
from pathlib import Path
import socket
import subprocess
from unittest import skipUnless
from unittest.mock import patch

from allauth.mfa.models import Authenticator
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import LiveServerTestCase, override_settings

from core.models import ComplianceAuditChainState, GroupSheetConfiguration
from core.tests_browser_complaints import seed_complaint_policy, synthetic_case
from .crypto import decrypt_secret
from .initial_setup import prepare_setup, preview_setup
from .lifecycle import apply_change
from .models import StaffBrowserSetupGrant
from .production import load_build
from .tests import PASSWORD, TEST_KEY
from . import tests_complaints_operations_transport as operations


@override_settings(ROOT_URLCONF='config.urls',STAFF_BROWSER_TRANSPORT_BUILD='dist-production')
class ProductionComplaintsOperationsTests(operations.ComplaintsOperationsTransportTests):
    """Reuse the complete native workflow against real routes, assets and CSP."""


@skipUnless(os.environ.get('RUN_STAFF_BROWSER_E2E')=='1','Explicit native production browser integration.')
@override_settings(ROOT_URLCONF='config.urls',STAFF_BROWSER_AUTH_ENABLED=True,STAFF_BROWSER_COMPLAINTS_ENABLED=True,
    STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY],EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    ACCOUNT_EMAIL_NOTIFICATIONS=False,ACCOUNT_CHANGE_EMAIL=False,
    SECURE_SSL_REDIRECT=False,SESSION_COOKIE_SECURE=False,CSRF_COOKIE_SECURE=False)
class ProductionBrowserTransportTests(LiveServerTestCase):
    def test_existing_owner_can_verify_email_enroll_mfa_and_use_real_routes(self):
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        seed_complaint_policy()
        user=get_user_model().objects.create_superuser('synthetic_production_owner','owner@example.invalid',PASSWORD)
        before=user.password
        apply_change(actor=user,target_user_id=user.pk,action='authorize',expected_revision=0,
            request_key='synthetic-prod-owner-admit',reason='Supervised synthetic production browser journey')
        purpose=StaffBrowserSetupGrant.VERIFY_EMAIL
        preview=preview_setup(actor=user,target_user_id=user.pk,purpose=purpose)
        receipt=prepare_setup(actor=user,target_user_id=user.pk,purpose=purpose,expected_revision=preview['revision'],
            snapshot_fingerprint=preview['snapshot_fingerprint'],request_key='synthetic-prod-owner-setup',reason='Synthetic production mailbox invitation')
        grant=StaffBrowserSetupGrant.objects.get(pk=receipt['setup_id'])
        group=GroupSheetConfiguration.objects.create(group_id='synthetic-production-complaints',workflow={'type':'case'},complaint_sheet_projection_enabled=False)
        synthetic_case(group,1)
        output=Path(settings.BASE_DIR)/'test-results/browser-production-native';output.mkdir(parents=True,exist_ok=True)
        original=socket.socket.connect
        def local_only(sock,address):
            if not isinstance(address,tuple) or address[0] not in {'127.0.0.1','localhost','::1'}:
                raise AssertionError('Native production tests permit loopback only.')
            return original(sock,address)
        load_build.cache_clear()
        self.addCleanup(load_build.cache_clear)
        with patch('socket.socket.connect',local_only):
            result=subprocess.run([os.environ['STAFF_BROWSER_TEST_NODE'],str(Path(settings.BASE_DIR)/'scripts/test_staff_browser_production.js')],
                input=json.dumps({'origin':self.live_server_url,'username':user.username,'password':PASSWORD,
                    'setupId':str(grant.pk),'proof':decrypt_secret(grant.confirmation_cipher),'group':group.pk,'output':str(output)}),
                capture_output=True,text=True,timeout=120,cwd=settings.BASE_DIR)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        user.refresh_from_db();grant.refresh_from_db()
        self.assertEqual(user.password,before)
        self.assertEqual(grant.state,StaffBrowserSetupGrant.COMPLETED)
        self.assertEqual(Authenticator.objects.filter(user=user,type='totp').count(),1)
