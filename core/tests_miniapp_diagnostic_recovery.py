"""Real PostgreSQL disconnects, atomic rollback and idempotent diagnostic replay."""
import json
import uuid
import os
import subprocess
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connection, OperationalError
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from core.models import MiniAppDiagnosticEvent, MiniAppDiagnosticSession
from core.services.miniapp_diagnostics import record_signals,start_session


class DiagnosticDisconnect:
    def __init__(self,count=1,late=False):
        self.remaining=count;self.late=late;self.pids=[]

    def __call__(self,**kwargs):
        self.pids.append(connection.connection.info.backend_pid)
        def execute(fn,sql,params,many,context):
            point=('UPDATE' in sql and MiniAppDiagnosticSession._meta.db_table in sql) if self.late else (
                MiniAppDiagnosticEvent._meta.db_table in sql and 'ORDER BY' in sql)
            if self.remaining and point:
                self.remaining-=1;connection.connection.close()
            return fn(sql,params,many,context)
        with connection.execute_wrapper(execute):return record_signals(**kwargs)


@skipUnless(connection.vendor=='postgresql','Native connection recovery requires PostgreSQL')
@override_settings(MINIAPP_DIAGNOSTICS_ENABLED=True,SECURE_SSL_REDIRECT=False,REQUIRE_MINIAPP_IDEMPOTENCY_KEY=False)
class DiagnosticConnectionRecoveryTests(TransactionTestCase):
    def setUp(self):
        self.actor=get_user_model().objects.create_user(username='synthetic-diagnostic-recovery')
        self.session_uuid=str(uuid.uuid4());self.client.raise_request_exception=False
        with patch('core.api.miniapp_diagnostic_views._authorized_actor',return_value=self.actor):
            result=self.client.post(reverse('miniapp_diagnostic_session_start'),json.dumps({'session_uuid':self.session_uuid,'surface':'portal'}),content_type='application/json')
        self.assertEqual(result.status_code,200,result.content[:500]);self.token=result.json()['signal_token']

    def signals(self,events):
        return self.client.post(reverse('miniapp_diagnostic_signals',args=[self.session_uuid]),
            json.dumps({'signal_token':self.token,'events':events}),content_type='application/json')

    def events(self):
        return [{'event_uuid':str(uuid.uuid4()),'event_type':'backgrounded','elapsed_ms':100,'visibility':'hidden'},
                {'event_uuid':str(uuid.uuid4()),'event_type':'resumed','elapsed_ms':200,'visibility':'visible'}]

    def test_dropped_connection_after_session_lock_is_reconnected_once(self):
        fault=DiagnosticDisconnect();events=self.events()
        with patch('core.api.miniapp_diagnostic_views.record_signals',side_effect=fault):response=self.signals(events)
        self.assertEqual(response.status_code,200,response.content[:500])
        self.assertEqual(len(fault.pids),2);self.assertNotEqual(fault.pids[0],fault.pids[1])
        self.assertEqual(set(response.json()['acknowledged']),{e['event_uuid'] for e in events})
        self.assertEqual(MiniAppDiagnosticEvent.objects.count(),2)

    def test_disconnect_after_event_inserts_rolls_back_before_replay(self):
        fault=DiagnosticDisconnect(late=True);events=self.events()
        with patch('core.api.miniapp_diagnostic_views.record_signals',side_effect=fault):response=self.signals(events)
        self.assertEqual(response.status_code,200,response.content[:500])
        self.assertEqual(len(fault.pids),2)
        self.assertEqual(MiniAppDiagnosticEvent.objects.count(),2)
        self.assertEqual(MiniAppDiagnosticSession.objects.get().classification,'active_visible')
        self.assertEqual(self.signals(events).status_code,200)
        self.assertEqual(MiniAppDiagnosticEvent.objects.count(),2)

    def test_repeated_disconnect_returns_retryable_503_without_false_ack(self):
        fault=DiagnosticDisconnect(count=2)
        with patch('core.api.miniapp_diagnostic_views.record_signals',side_effect=fault):response=self.signals(self.events())
        self.assertEqual(response.status_code,503,response.content[:500])
        self.assertEqual(response.json()['acknowledged'],[])
        self.assertEqual(response['Retry-After'],'5')
        self.assertEqual(len(fault.pids),2);self.assertEqual(MiniAppDiagnosticEvent.objects.count(),0)

    def test_unknown_start_commit_is_replayed_without_duplicate_session(self):
        session_uuid=str(uuid.uuid4());calls=[]
        def save_then_disconnect(**kwargs):
            saved=start_session(**kwargs);calls.append(saved[0].pk)
            if len(calls)==1:
                connection.connection.close();raise OperationalError('the connection is closed')
            return saved
        with patch('core.api.miniapp_diagnostic_views._authorized_actor',return_value=self.actor),patch('core.api.miniapp_diagnostic_views.start_session',side_effect=save_then_disconnect):
            response=self.client.post(reverse('miniapp_diagnostic_session_start'),json.dumps({'session_uuid':session_uuid,'surface':'portal'}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content[:500])
        self.assertEqual(len(calls),2);self.assertEqual(calls[0],calls[1])
        self.assertFalse(response.json()['created'])
        self.assertEqual(MiniAppDiagnosticSession.objects.filter(client_session_uuid=session_uuid).count(),1)

    def test_reconnect_rechecks_authorization_before_issuing_a_start_token(self):
        def save_then_disconnect(**kwargs):
            start_session(**kwargs);connection.connection.close();raise OperationalError('the connection is closed')
        with patch('core.api.miniapp_diagnostic_views._authorized_actor',side_effect=[self.actor,None]) as auth,patch('core.api.miniapp_diagnostic_views.start_session',side_effect=save_then_disconnect):
            response=self.client.post(reverse('miniapp_diagnostic_session_start'),json.dumps({'session_uuid':str(uuid.uuid4()),'surface':'portal'}),content_type='application/json')
        self.assertEqual(response.status_code,403,response.content[:500]);self.assertEqual(auth.call_count,2)
        self.assertNotIn('signal_token',response.json())


@skipUnless(os.environ.get('RUN_MINIAPP_DIAGNOSTICS_E2E')=='1' and connection.vendor=='postgresql','Opt-in native PostgreSQL/Playwright recovery')
@override_settings(MINIAPP_DIAGNOSTICS_ENABLED=True,SECURE_SSL_REDIRECT=False,DEBUG=True,
    REQUIRE_MINIAPP_IDEMPOTENCY_KEY=False,SESSION_COOKIE_SECURE=False,CSRF_COOKIE_SECURE=False)
class DiagnosticConnectionBrowserTests(StaticLiveServerTestCase):
    def test_real_client_retains_events_during_disconnect_and_honors_retry_after(self):
        from core.models import UserProfile,GroupSheetConfiguration,ComplianceAuditChainState,PortalMaintenanceState
        from core.tests_telegram_authentication import BOT_TOKEN,signed_init_data
        from types import SimpleNamespace
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        actor=get_user_model().objects.create_user(username='synthetic-browser-recovery',is_superuser=True)
        UserProfile.objects.create(user=actor,telegram_id='991007')
        group=GroupSheetConfiguration.objects.create(group_id='-100diagnostic-browser',workflow={'type':'jawabu_homebiogas'})
        from portal_legacy.models import LegacyBatch,LegacyUpload
        batch=LegacyBatch.objects.create(group=group,namespace='synthetic-recovery',source_hash='0'*64,created_by=actor)
        upload=LegacyUpload.objects.create(batch=batch,actor=actor,filename='synthetic.xlsx',digest='0'*64,size=1,frozen=True,phase='ready')
        PortalMaintenanceState.objects.create(singleton=1,mode='maintenance',reason='Synthetic reset recovery review')
        root=Path(settings.BASE_DIR);fault=DiagnosticDisconnect(count=2)
        with override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN),patch('core.api.miniapp_diagnostic_views.record_signals',side_effect=fault),patch('core.services.sheets.GoogleSheetsService.get_instance',return_value=SimpleNamespace(is_available=lambda:False)):
            result=subprocess.run([os.environ.get('PORTAL_TEST_NODE','node'),str(root/'scripts/test_miniapp_diagnostic_recovery.js')],
                input=json.dumps({'origin':self.live_server_url,'initData':signed_init_data(user={'id':991007}),
                    'artifacts':str(root/'test-results/diagnostics-connection-recovery-browser')}),
                capture_output=True,text=True,timeout=90,cwd=root)
        self.assertEqual(result.returncode,0,(result.stdout+result.stderr)[-5000:])
        self.assertEqual(fault.remaining,0);self.assertGreaterEqual(len(fault.pids),3)
        from django.db.models import Count
        self.assertEqual(MiniAppDiagnosticEvent.objects.values('session_id','client_event_uuid').annotate(n=Count('pk')).filter(n__gt=1).count(),0)
        self.assertEqual(PortalMaintenanceState.objects.get().mode,'live')
        self.assertTrue(LegacyUpload.objects.get(pk=upload.pk).frozen)
