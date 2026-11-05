"""Opt-in actual Django/PostgreSQL/Playwright customer-prefill journey."""
import json
import os
from pathlib import Path
import socket
import subprocess
from unittest import skipUnless
from unittest.mock import patch
from allauth.account.models import EmailAddress
from allauth.mfa.totp.internal.auth import TOTP, generate_totp_secret
from allauth.mfa.recovery_codes.internal.auth import RecoveryCodes
from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings
from core.tests_complaint_customer_lookup import DirectoryFixture
from core.tests_telegram_authentication import BOT_TOKEN
from core.models import ComplaintCategory, ComplaintCaseEvent, ParsedMessage, ComplianceAuditChainState
from staff_auth.tests import PASSWORD, TEST_KEY, admit_synthetic_user
from complaint_legacy.test_support import ComplaintBook


@skipUnless(os.environ.get('RUN_COMPLAINT_CUSTOMER_E2E')=='1','Opt-in native browser verification')
@override_settings(ROOT_URLCONF='config.urls',DEBUG=True,TELEGRAM_BOT_TOKEN=BOT_TOKEN,
    STAFF_BROWSER_AUTH_ENABLED=True,STAFF_BROWSER_COMPLAINTS_ENABLED=True,STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY],
    SECURE_SSL_REDIRECT=False,SESSION_COOKIE_SECURE=False,CSRF_COOKIE_SECURE=False,
    ACCOUNT_EMAIL_NOTIFICATIONS=False,ACCOUNT_CHANGE_EMAIL=False,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    CACHES={'default':{'BACKEND':'staff_auth.security_cache.PostgresSecurityCache','KEY_FUNCTION':'staff_auth.cache_keys.native_cache_key'}})
class ComplaintCustomerBrowser(DirectoryFixture,StaticLiveServerTestCase):
    def test_real_forms_select_prefill_restore_and_save(self):
        cache.clear();ComplianceAuditChainState.objects.get_or_create(singleton=1)
        ComplaintCategory.objects.get_or_create(key='synthetic-customer-review',defaults={'label':'Synthetic system issue'})
        self.user.set_password(PASSWORD);self.user.email='customer-review@example.invalid';self.user.save()
        admit_synthetic_user(self.user);EmailAddress.objects.create(user=self.user,email=self.user.email,primary=True,verified=True)
        TOTP.activate(self.user,generate_totp_secret());code=RecoveryCodes.activate(self.user).get_unused_codes()[0]
        boundary=ComplaintBook();boundary.register.cells.pop(2)
        boundary.register.col_values=lambda column:[row[column-1] if len(row)>=column else '' for row in boundary.register.get_all_values()]
        original=socket.socket.connect
        def local_only(sock,address):
            if not isinstance(address,tuple) or address[0] not in {'127.0.0.1','localhost','::1'}:raise AssertionError('External IO blocked')
            return original(sock,address)
        root=Path(settings.BASE_DIR);folder=root/'test-results/complaint-customer-lookup';folder.mkdir(exist_ok=True)
        with patch('socket.socket.connect',local_only),patch('core.services.complaint_cases.get_sheets_service',return_value=boundary.service_instance),patch('core.services.sheets.get_sheets_service',return_value=boundary.service_instance):
            result=subprocess.run(['node',str(root/'scripts/test_complaint_customer_lookup.cjs')],input=json.dumps({
                'origin':self.live_server_url,'group':self.owner.group_id,'key':self.owner.pk,'initData':self.headers['HTTP_X_TELEGRAM_INIT_DATA'],
                'username':self.user.username,'password':PASSWORD,'code':code,'sourceKey':str(self.farmer.pk),
                'reference':f'JBL-{self.farmer.case_reference_number}','legacyKey':str(self.legacy.pk),'place':self.place}),
                cwd=root,text=True,capture_output=True,timeout=240)
            self.assertEqual(result.returncode,0,(result.stdout+result.stderr)[-7000:])
            call_command('drain_complaint_publications',apply=True,limit=10,max_seconds=50)
        cases=ParsedMessage.objects.filter(group_id=self.owner.group_id)
        self.assertEqual(cases.count(),2)
        self.assertEqual(set(cases.values_list('customer_id',flat=True)),{'90123456'})
        self.assertEqual(ComplaintCaseEvent.objects.filter(action='created',after_values__portal_biodata_source=str(self.farmer.pk)).count(),2)
        self.assertEqual(cases.filter(synced_to_sheets=True).count(),2)
        self.assertEqual(len([r for r in boundary.register.get_all_values()[1:] if len(r)>1 and r[1]]),2)
        from openpyxl import Workbook
        book=Workbook();sheet=book.active;sheet.title='Projected Complaints'
        for row in boundary.register.get_all_values():sheet.append(row)
        book.save(folder/'projected-complaints.xlsx');book.close()
        print(result.stdout)
