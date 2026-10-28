"""Production URL/asset and invitation checks with synthetic identities and mail."""
import hashlib
import json
from pathlib import Path
import tempfile
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from core.models import ComplianceAuditChainState, ComplianceAuditEvent
from .crypto import decrypt_secret
from .initial_setup import prepare_setup, preview_setup
from .invitations import send_invitation
from .lifecycle import apply_change
from .models import StaffBrowserAdmission, StaffBrowserSetupGrant
from .production import load_build, release_errors
from .tests import PASSWORD, TEST_KEY


@override_settings(ROOT_URLCONF='config.urls',STAFF_BROWSER_AUTH_ENABLED=True,STAFF_BROWSER_COMPLAINTS_ENABLED=True)
class BrowserProductionAssetsTests(SimpleTestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        self.override=override_settings(BASE_DIR=self.root)
        self.override.enable();self.addCleanup(self.override.disable)
        load_build.cache_clear();self.addCleanup(load_build.cache_clear)
        self.build=self.root/'browser/dist-production';self.build.mkdir(parents=True)
        source=self.root/'browser/src/entry.ts';source.parent.mkdir();source.write_text('/* synthetic native entry */')
        lock=self.root/'browser/package-lock.json';lock.write_text('{}')
        files={'complaints-operations.html':b'<html><script src="/staff/assets/app.js"></script></html>',
            'app.js':b'/* synthetic native app */','THIRD_PARTY_NOTICES.txt':b'Synthetic notice'}
        vendors=[]
        for suffix in ('js','css','LICENSE.txt'):
            name='vendor-leaflet-1.9.4.'+suffix
            vendor=self.root/'core/static/miniapp'/name
            vendor.parent.mkdir(parents=True,exist_ok=True)
            raw=b'/* synthetic vendored map asset */'
            vendor.write_bytes(raw);files[name]=raw
            vendors.append({'path':'core/static/miniapp/'+name,'sha256':hashlib.sha256(raw).hexdigest()})
        for name,raw in files.items(): (self.build/name).write_bytes(raw)
        self.manifest={'schemaVersion':1,'mode':'production','demoOnly':False,'localComplaintsDemo':False,
            'closedAuthentication':True,'closedComplaintOperations':True,'productionBrowser':True,'assetPrefix':'/staff/assets/',
            'dependencyLock':hashlib.sha256(lock.read_bytes()).hexdigest(),
            'vendorSources':vendors,
            'sources':[{'path':'browser/src/entry.ts','sha256':hashlib.sha256(source.read_bytes()).hexdigest()}],
            'files':[{'name':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()} for name,raw in files.items()]}
        self.save_manifest()

    def save_manifest(self):
        (self.build/'build-manifest.json').write_text(json.dumps(self.manifest));load_build.cache_clear()

    def test_real_routes_and_deep_links_serve_only_the_native_build(self):
        for path in ['/staff/login/','/staff/app/complaints/','/staff/app/complaints/reports/',
                     '/staff/app/complaints/cases/00000000-0000-4000-8000-000000000001/']:
            response=self.client.get(path)
            self.assertEqual(response.status_code,200,path)
            self.assertIn("frame-ancestors 'none'",response['Content-Security-Policy'])
            self.assertEqual(response['Cache-Control'],'no-store, private')
            self.assertEqual(response['Referrer-Policy'],'no-referrer')
        self.assertRedirects(self.client.get('/staff/'),'/staff/app/complaints/',fetch_redirect_response=False)
        self.assertEqual(self.client.get('/staff/assets/app.js').status_code,200)
        self.assertEqual(self.client.get('/THIRD_PARTY_NOTICES.txt').status_code,200)
        for path in ['/staff/assets/build-manifest.json','/staff/assets/complaints-operations.html','/_review/','/staff/app/origination/']:
            self.assertEqual(self.client.get(path).status_code,404,path)

    def test_disabled_channel_or_workflow_hides_pages_and_assets(self):
        for flags in [{'STAFF_BROWSER_AUTH_ENABLED':False},{'STAFF_BROWSER_COMPLAINTS_ENABLED':False}]:
            with override_settings(**flags):
                for path in ['/staff/','/staff/login/','/staff/app/complaints/','/staff/assets/app.js','/THIRD_PARTY_NOTICES.txt']:
                    self.assertEqual(self.client.get(path).status_code,404,path)

    def test_stale_demo_and_modified_artifacts_are_rejected(self):
        for key,value in [('demoOnly',True),('productionBrowser',False),('mode','development'),('assetPrefix','/')]:
            original=self.manifest[key];self.manifest[key]=value;self.save_manifest()
            with self.assertRaises(ImproperlyConfigured): load_build()
            self.manifest[key]=original
        self.save_manifest();(self.build/'app.js').write_bytes(b'changed')
        with self.assertRaises(ImproperlyConfigured): load_build()

    def test_release_requires_verified_build_origin_sender_and_postgresql(self):
        config=SimpleNamespace(STAFF_BROWSER_AUTH_ENABLED=True,APP_BASE_URL='https://staff.example.invalid',
            STAFF_BROWSER_INVITATIONS_ENABLED=True,STAFF_BROWSER_EMAIL_FROM='staff@example.invalid',RESEND_API_KEY='synthetic',
            DATABASES={'default':{'ENGINE':'django.db.backends.postgresql'}},
            CACHES={'default':{'BACKEND':'staff_auth.security_cache.PostgresSecurityCache'}})
        self.assertEqual(release_errors(config),[])
        config.APP_BASE_URL='http://staff.example.invalid/path'
        config.STAFF_BROWSER_INVITATIONS_ENABLED=False
        config.DATABASES['default']['ENGINE']='django.db.backends.sqlite3'
        self.assertEqual({code for code,_ in release_errors(config)}, {'staff_auth.E010','staff_auth.E011','staff_auth.E012'})
        config.STAFF_BROWSER_AUTH_ENABLED=False
        self.assertEqual(release_errors(config),[])

    def test_unknown_inline_script_and_source_traversal_are_rejected(self):
        self.manifest['sources'][0]['path']='browser/src/../../secret.ts';self.save_manifest()
        with self.assertRaises(ImproperlyConfigured): load_build()
        self.manifest['sources'][0]['path']='browser/src/entry.ts'
        raw=b'<script>alert(1)</script>'
        (self.build/'complaints-operations.html').write_bytes(raw)
        self.manifest['files'][0].update(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest());self.save_manifest()
        with self.assertRaises(ImproperlyConfigured): load_build()


@override_settings(ROOT_URLCONF='config.urls',STAFF_BROWSER_AUTH_ENABLED=True,STAFF_BROWSER_COMPLAINTS_ENABLED=True,
    STAFF_BROWSER_INVITATIONS_ENABLED=True,STAFF_BROWSER_EMAIL_FROM='JBL <staff@example.invalid>',
    RESEND_API_KEY='synthetic-not-a-secret',STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY],
    APP_BASE_URL='https://staff.example.invalid',EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class BrowserProductionOnboardingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        cls.root=get_user_model().objects.create_superuser('synthetic-browser-owner','owner@example.invalid',PASSWORD)
        cls.user=get_user_model().objects.create_user('synthetic-browser-staff','staff@example.invalid')
        apply_change(actor=cls.root,target_user_id=cls.user.pk,action='authorize',expected_revision=0,
            request_key='synthetic-browser-admit',reason='Explicit synthetic staff browser admission')

    def setUp(self):
        self.client=Client(enforce_csrf_checks=True)

    def prepare(self,user=None,purpose=StaffBrowserSetupGrant.INITIAL_PASSWORD):
        user=user or self.user
        preview=preview_setup(actor=self.root,target_user_id=user.pk,purpose=purpose)
        receipt=prepare_setup(actor=self.root,target_user_id=user.pk,purpose=purpose,
            expected_revision=preview['revision'],snapshot_fingerprint=preview['snapshot_fingerprint'],
            request_key=uuid.uuid4().hex,reason='Prepare reviewed synthetic staff invitation')
        return StaffBrowserSetupGrant.objects.get(pk=receipt['setup_id'])

    def verify(self,grant):
        self.client.get('/api/staff/auth/v1/setup/session/')
        return self.client.post('/api/staff/auth/v1/setup/verify-email/',content_type='application/json',
            data=json.dumps({'setup_id':str(grant.pk),'request_key':str(uuid.uuid4()),
                'confirmation_key':decrypt_secret(grant.confirmation_cipher)}),
            HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)

    def test_private_invitation_is_provider_idempotent_and_never_logged_in_audit(self):
        grant=self.prepare();proof=decrypt_secret(grant.confirmation_cipher)
        with patch('staff_auth.invitations.submit_email',return_value='synthetic-provider-id') as sender:
            first=send_invitation(actor=self.root,setup_id=grant.pk)
            replay=send_invitation(actor=self.root,setup_id=grant.pk)
        self.assertEqual(sender.call_count,1)
        payload=sender.call_args.args[0]
        self.assertEqual(payload['to'],[self.user.email])
        self.assertIn('/staff/login/#setup=',payload['text'])
        self.assertEqual(first['audit_event_id'],replay['audit_event_id'])
        self.assertNotIn(proof,json.dumps(list(ComplianceAuditEvent.objects.values('metadata','after_values')),default=str))
        self.assertEqual(self.verify(grant).json()['state'],'password_required')

    def test_existing_superuser_mailbox_proof_preserves_password_and_grants_no_login(self):
        apply_change(actor=self.root,target_user_id=self.root.pk,action='authorize',expected_revision=0,
            request_key='synthetic-owner-admission',reason='Supervised synthetic owner browser check')
        before=self.root.password
        grant=self.prepare(self.root,StaffBrowserSetupGrant.VERIFY_EMAIL)
        response=self.verify(grant)
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['state'],'reauthentication_required')
        self.root.refresh_from_db();grant.refresh_from_db()
        self.assertEqual(self.root.password,before)
        self.assertEqual(grant.state,StaffBrowserSetupGrant.COMPLETED)
        self.assertEqual(grant.confirmation_cipher,'')
        self.assertTrue(EmailAddress.objects.get(user=self.root).verified)
        self.assertFalse(self.client.get('/api/staff/auth/v1/session/').json()['is_authenticated'])
        denied=self.client.post('/api/staff/auth/v1/setup/password/',content_type='application/json',
            data=json.dumps({'setup_id':str(grant.pk),'request_key':str(uuid.uuid4()),'password1':PASSWORD+'changed','password2':PASSWORD+'changed'}),
            HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)
        self.assertEqual(denied.status_code,409)
        self.root.refresh_from_db();self.assertEqual(self.root.password,before)

    def test_schema_reversal_refuses_to_drop_mailbox_verification_meaning(self):
        import importlib
        from django.apps import apps
        from django.db import connection
        guard=importlib.import_module('staff_auth.migrations.0005_browser_setup_purpose').guard_purpose_reversal
        editor=SimpleNamespace(connection=connection)
        guard(apps,editor)
        self.user.set_password(PASSWORD);self.user.save(update_fields=['password'])
        self.prepare(self.user,StaffBrowserSetupGrant.VERIFY_EMAIL)
        with self.assertRaises(RuntimeError): guard(apps,editor)

    def test_ambiguous_invitation_retry_keeps_identical_payload_and_provider_key(self):
        from .invitations import SubmissionError
        grant=self.prepare()
        with patch('staff_auth.invitations.submit_email',side_effect=[SubmissionError('synthetic-timeout',ambiguous=True), 'synthetic-provider-id']) as sender:
            with self.assertRaises(SubmissionError): send_invitation(actor=self.root,setup_id=grant.pk)
            send_invitation(actor=self.root,setup_id=grant.pk)
        self.assertEqual(sender.call_args_list[0],sender.call_args_list[1])
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='staff_browser.invitation_accepted').count(),1)

    def test_unauthorized_or_suspended_sender_cannot_send(self):
        grant=self.prepare()
        with patch('staff_auth.invitations.submit_email') as sender:
            with override_settings(STAFF_BROWSER_COMPLAINTS_ENABLED=False), self.assertRaises(ValidationError):
                send_invitation(actor=self.root,setup_id=grant.pk)
            with self.assertRaises(PermissionDenied): send_invitation(actor=self.user,setup_id=grant.pk)
            get_user_model().objects.filter(pk=self.root.pk).update(is_active=False)
            with self.assertRaises(PermissionDenied): send_invitation(actor=self.root,setup_id=grant.pk)
        sender.assert_not_called()

    def test_admin_requires_superuser_and_raw_model_edits_are_disabled(self):
        from django.contrib import admin
        model_admin=admin.site._registry[StaffBrowserAdmission]
        self.client.force_login(self.root)
        response=self.client.get('/admin/staff_auth/staffbrowseradmission/manage/')
        self.assertEqual(response.status_code,200,response.content[:300])
        request=response.wsgi_request
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))
        session=self.client.get('/api/staff/auth/v1/session/').json()
        self.assertFalse(session['is_authenticated'])
        self.assertTrue(session['separate_session_required'])
        self.client.force_login(self.user)
        self.assertNotEqual(self.client.get('/admin/staff_auth/staffbrowseradmission/manage/').status_code,200)

    def test_expired_changed_or_suspended_invitation_never_sends(self):
        from .setup_api import _Rejected
        grant=self.prepare()
        with patch('staff_auth.invitations.submit_email') as sender:
            get_user_model().objects.filter(pk=self.user.pk).update(email='changed@example.invalid')
            with self.assertRaises(_Rejected): send_invitation(actor=self.root,setup_id=grant.pk)
            get_user_model().objects.filter(pk=self.user.pk).update(email=self.user.email)
            StaffBrowserSetupGrant.objects.filter(pk=grant.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
            with self.assertRaises(_Rejected): send_invitation(actor=self.root,setup_id=grant.pk)
            admission=StaffBrowserAdmission.objects.get(user=self.user)
            apply_change(actor=self.root,target_user_id=self.user.pk,action='suspend',expected_revision=admission.revision,
                request_key='synthetic-suspend-invitation',reason='Suspend synthetic invitation before delivery')
            with self.assertRaises(_Rejected): send_invitation(actor=self.root,setup_id=grant.pk)
        sender.assert_not_called()

    def test_setup_requires_csrf_and_wrong_proof_grants_no_verified_email(self):
        grant=self.prepare()
        body={'setup_id':str(grant.pk),'request_key':str(uuid.uuid4()),'confirmation_key':'wrong-proof'}
        self.assertEqual(self.client.post('/api/staff/auth/v1/setup/verify-email/',data=json.dumps(body),
            content_type='application/json').status_code,403)
        self.client.get('/api/staff/auth/v1/setup/session/')
        response=self.client.post('/api/staff/auth/v1/setup/verify-email/',data=json.dumps(body),
            content_type='application/json',HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)
        self.assertNotEqual(response.status_code,200)
        self.assertFalse(EmailAddress.objects.get(user=self.user).verified)

    def test_admin_review_confirmation_and_retry_deliver_once(self):
        self.client.force_login(self.root)
        path='/admin/staff_auth/staffbrowseradmission/manage/'
        self.client.get(path)
        token=self.client.cookies['csrftoken'].value
        response=self.client.post(path,{'user':self.user.pk,'action':'invite','reason':'Synthetic reviewed staff invitation'},HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code,200)
        review=response.context['review_token']
        self.assertTrue(review)
        with patch('staff_auth.invitations.submit_email',return_value='synthetic-provider-id') as sender:
            for _ in range(2):
                response=self.client.post(path,{'review':review},HTTP_X_CSRFTOKEN=token)
                self.assertEqual(response.status_code,302,response.content)
        self.assertEqual(sender.call_count,1)
        self.assertEqual(StaffBrowserSetupGrant.objects.filter(admission__user=self.user).count(),1)
