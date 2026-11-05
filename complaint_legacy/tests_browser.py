"""Real production routes, signed Telegram and native password/MFA, on loopback."""
import json
import os
from pathlib import Path
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest import skipUnless
from unittest.mock import patch

from allauth.account.models import EmailAddress
from allauth.mfa.recovery_codes.internal.auth import RecoveryCodes
from allauth.mfa.totp.internal.auth import TOTP, generate_totp_secret
from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.urls import reverse
import requests
from core.models import ParsedMessage, IntegrationOperation, ComplaintCaseControl
from core.tests_telegram_authentication import BOT_TOKEN
from staff_auth.tests import PASSWORD, TEST_KEY, admit_synthetic_user
from .tests import ImportFixture, source


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN, COMPLAINT_CASES_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, SECURE_SSL_REDIRECT=False)
class ComplaintLegacyConcurrentTests(ImportFixture, StaticLiveServerTestCase):
    @skipUnless(connection.vendor=='postgresql','Independent publishers require PostgreSQL')
    def test_two_import_sync_requests_cannot_allocate_the_same_rows(self):
        from .test_support import ComplaintBook
        book=ComplaintBook();book.register.cells.pop(2)
        first=self.commit(self.stage(source([[i+2,f'FIFO {i}','OPEN','24-May-2025'] for i in range(61)])))
        second=self.commit(self.stage(source([[500,'NEXT IMPORT','OPEN','24-May-2025']])))
        reached,release=Event(),Event()
        def gated():
            if not reached.is_set():
                reached.set()
                if not release.wait(10): raise TimeoutError('Synthetic first publisher gate')
        book.before_read=gated
        def send(upload):
            url=self.live_server_url+reverse('complaint_legacy_action',kwargs={'upload_id':upload['id'],'action':'sync'})
            return requests.post(url,json={'group_id':self.owner.group_id,'revision':upload['revision']},
                headers={'X-Telegram-Init-Data':self.headers['HTTP_X_TELEGRAM_INIT_DATA']},timeout=25)
        with patch('core.services.complaint_cases.get_sheets_service',return_value=book.service_instance),ThreadPoolExecutor(max_workers=2) as pool:
            one=pool.submit(send,first)
            try:
                self.assertTrue(reached.wait(10))
                two=pool.submit(send,second)
            finally: release.set()
            for future in (one,two):
                response=future.result();self.assertEqual(response.status_code,200,response.text)
        rows=[r for r in book.register.get_all_values()[1:] if len(r)>1 and r[1]]
        self.assertEqual(len(rows),62);self.assertEqual(len({r[1] for r in rows}),62)
        self.assertEqual([r[0] for r in rows],list(map(str,range(1,63))))
        self.assertEqual(rows[-1][4],'NEXT IMPORT')

    @skipUnless(connection.vendor=='postgresql','Independent workers require PostgreSQL')
    def test_only_one_worker_can_commit_a_saved_selection(self):
        from . import services
        upload=self.stage();upload=self.call('select',{'all':True,'approved':True},upload=upload)['upload']
        upload=self.call('commit',upload=upload)['upload']
        reached,release=Event(),Event();original=services.commit_row
        def gated(*args,**kwargs):
            reached.set()
            if not release.wait(15):raise TimeoutError('Synthetic worker gate')
            return original(*args,**kwargs)
        url=self.live_server_url+reverse('complaint_legacy_action',kwargs={'upload_id':upload['id'],'action':'advance'})
        body={'group_id':self.owner.group_id,'revision':upload['revision']}
        headers={'X-Telegram-Init-Data':self.headers['HTTP_X_TELEGRAM_INIT_DATA']}
        with patch('complaint_legacy.services.commit_row',side_effect=gated),ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(requests.post,url,json=body,headers=headers,timeout=25)
            try:
                self.assertTrue(reached.wait(10))
                second=requests.post(url,json=body,headers=headers,timeout=10)
                self.assertEqual(second.status_code,409,second.text)
            finally:release.set()
            self.assertEqual(first.result().status_code,200)
        self.assertEqual(ParsedMessage.objects.filter(source='complaint_legacy').count(),1)


@skipUnless(os.environ.get('RUN_COMPLAINT_LEGACY_E2E') == '1', 'Opt-in actual Django/Playwright import')
@override_settings(ROOT_URLCONF='config.urls', DEBUG=True, TELEGRAM_BOT_TOKEN=BOT_TOKEN,
    COMPLAINT_CASES_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, STAFF_BROWSER_AUTH_ENABLED=True,
    STAFF_BROWSER_COMPLAINTS_ENABLED=True, STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY],
    SECURE_SSL_REDIRECT=False, SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False,
    ACCOUNT_EMAIL_NOTIFICATIONS=False, ACCOUNT_CHANGE_EMAIL=False,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    CACHES={'default': {'BACKEND':'staff_auth.security_cache.PostgresSecurityCache',
                       'KEY_FUNCTION':'staff_auth.cache_keys.native_cache_key'}})
class ComplaintLegacyBrowserTests(ImportFixture, StaticLiveServerTestCase):
    def test_both_channels_review_changeover_resume_and_verified_publication(self):
        cache.clear()
        from .test_support import ComplaintBook
        book_boundary=ComplaintBook()
        book_boundary.lose_next_publication_ack=True
        previous=self.commit(self.stage(source([[8000,'PREVIOUSLY IMPORTED','OPEN','24-May-2025']])))
        retained=ParsedMessage.objects.get(source='complaint_legacy')
        for i in range(3):
            case=ParsedMessage.objects.create(processed_message=retained.processed_message,group_id=self.owner.group_id,
                message_id=f'synthetic-reset-{i}',customer_name=f'OLD TEST {i}')
            ComplaintCaseControl.objects.create(parsed_message=case,reference_number=f'CMP-OLD-{i}')
        self.user.is_superuser=True;self.user.save(update_fields=['is_superuser'])
        self.user.set_password(PASSWORD); self.user.email='complaint-import@example.invalid'
        self.user.save(update_fields=['password','email'])
        admit_synthetic_user(self.user)
        EmailAddress.objects.create(user=self.user,email=self.user.email,primary=True,verified=True)
        TOTP.activate(self.user,generate_totp_secret())
        code=RecoveryCodes.activate(self.user).get_unused_codes()[0]
        root=Path(settings.BASE_DIR)
        book=Path(self.directory.name)/'synthetic-browser.xlsx'
        book.write_bytes(source([[i+2,f'SYNTHETIC {i}','CLOSED' if i%2 else 'OPEN','24-May-2025'] for i in range(61)]+
                                [[63,'SYNTHETIC BLOCKED','Closed with prose','bad date']]))
        native=Path(self.directory.name)/'synthetic-native.xlsx'
        native.write_bytes(source([[400,'SYNTHETIC NATIVE','REOPENED','24-May-2025']]))
        original=socket.socket.connect
        def local_only(sock,address):
            if not isinstance(address,tuple) or address[0] not in {'localhost','127.0.0.1','::1'}:
                raise AssertionError('No external network in synthetic import verification.')
            return original(sock,address)
        with patch('socket.socket.connect',local_only), patch('core.services.complaint_cases.get_sheets_service',return_value=book_boundary.service_instance):
            result=subprocess.run([os.environ.get('STAFF_BROWSER_TEST_NODE','node'),str(root/'scripts/test_complaint_legacy_transport.js')],
                input=json.dumps({'origin':self.live_server_url,'initData':self.headers['HTTP_X_TELEGRAM_INIT_DATA'],
                    'group':self.owner.group_id,'key':self.owner.pk,'other':self.other.pk,
                    'username':self.user.username,'password':PASSWORD,'code':code,
                    'workbook':str(book),'nativeWorkbook':str(native)}),
                cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=240)
        self.assertEqual(result.returncode,0,(result.stdout+result.stderr)[-7000:])
        self.assertEqual(ParsedMessage.objects.filter(source='complaint_legacy').count(),63)
        self.assertEqual(IntegrationOperation.objects.filter(operation_type='complaint_browser.sheet',status='succeeded').count(),63)
        self.assertFalse(ParsedMessage.objects.filter(message_id__startswith='synthetic-reset-').exists())
        projected=[r for r in book_boundary.register.get_all_values()[1:] if len(r)>1 and r[1]]
        self.assertEqual(len(projected),63)
        self.assertEqual([r[0] for r in projected],list(map(str,range(1,64))))
        self.assertEqual(projected[0][4],'PREVIOUSLY IMPORTED')
        from openpyxl import Workbook
        evidence=Workbook();sheet=evidence.active;sheet.title='Projected Complaints'
        for row in book_boundary.register.get_all_values():sheet.append(row)
        evidence.save(root/'test-results/complaints-legacy-browser/projected-complaints.xlsx');evidence.close()
        self.assertFalse(ParsedMessage.objects.filter(customer_name='SYNTHETIC BLOCKED').exists())
        report=json.loads(result.stdout);self.assertTrue(report['passed']);print(f"Complaints legacy real browser: {report['captures']} screenshots, both channels passed")
