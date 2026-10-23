"""Public native-cache contract on isolated PostgreSQL, including real workers."""
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest import skipUnless

from django.conf import settings
from django.db import connection
from django.test import TransactionTestCase, SimpleTestCase, override_settings


class BrowserSecurityConfigurationTests(SimpleTestCase):
    @override_settings(STAFF_BROWSER_AUTH_ENABLED=True,DEBUG=True)
    def test_postgresql_adapter_satisfies_store_check_but_never_opens_release_gate(self):
        from .checks import staff_browser_checks
        from .tests import TEST_KEY
        cache={'default':{'BACKEND':'staff_auth.security_cache.PostgresSecurityCache',
                          'KEY_FUNCTION':'staff_auth.cache_keys.native_cache_key'}}
        with override_settings(STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY],CACHES=cache,
                               DATABASES={'default':{'ENGINE':'django.db.backends.postgresql'}}):
            self.assertEqual({issue.id for issue in staff_browser_checks(None)},{'staff_auth.E006'})
        with override_settings(STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY],CACHES=cache,
                               DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3'}}):
            self.assertEqual({issue.id for issue in staff_browser_checks(None)},{'staff_auth.E006','staff_auth.E007'})


@skipUnless(connection.vendor == 'postgresql', 'Requires real PostgreSQL atomic state, not SQLite emulation.')
class BrowserSecurityCacheTests(TransactionTestCase):
    def setUp(self):
        from core.models import ComplianceAuditChainState
        ComplianceAuditChainState.objects.get_or_create(singleton=1)

    def backend(self):
        from .security_cache import PostgresSecurityCache
        return PostgresSecurityCache('synthetic-security', {'KEY_FUNCTION':'staff_auth.cache_keys.native_cache_key'})

    def test_cache_instances_share_native_state_but_clear_preserves_live_security(self):
        first, second = self.backend(), self.backend()
        self.assertTrue(first.add('allauth.mfa.totp.used?user=synthetic&code=123456', 'y', 60))
        first.clear()
        self.assertFalse(second.add('allauth.mfa.totp.used?user=synthetic&code=123456', 'y', 60))
        first.set('ordinary-workflow-key', 'local', 60)
        self.assertEqual(second.get('ordinary-workflow-key'), 'local')

    def test_expired_lock_owner_cannot_delete_or_overwrite_successor(self):
        first, second = self.backend(), self.backend()
        key = 'allauth:rl:synthetic:key'
        self.assertTrue(first.add(key + ':lock', True, 0.05))
        import time
        time.sleep(0.06)
        self.assertTrue(second.add(key + ':lock', True, 60))
        second.set(key, [10.0], 60)
        with self.assertRaises(RuntimeError):
            first.set(key, [1.0], 60)
        self.assertFalse(first.delete(key + ':lock'))
        self.assertEqual(second.get(key), [10.0])
        self.assertTrue(second.delete(key + ':lock'))

    def workers(self, action, details=None, count=5):
        root = Path(settings.BASE_DIR)
        workers = [subprocess.Popen([sys.executable, '-m', 'staff_auth.security_cache_worker', 'test'],
            cwd=root, env={**os.environ, 'DJANGO_SETTINGS_MODULE':'staff_auth.acceptance_test_settings',
                          'BROWSER_ACCEPTANCE_WORKER_DB':connection.settings_dict['NAME']},
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(count)]
        try:
            for worker in workers:
                worker.stdin.write(json.dumps({'action':action, **(details or {})})+'\n'); worker.stdin.flush()
            results=[]
            for worker in workers:
                output, error=worker.communicate(timeout=45)
                self.assertEqual(worker.returncode, 0, error[-1500:])
                results.append(json.loads(output)['accepted'])
            return results
        finally:
            for worker in workers:
                if worker.poll() is None:
                    worker.kill(); worker.wait(timeout=5)

    def test_atomic_add_admits_exactly_one_of_five_independent_processes(self):
        self.assertEqual(sum(self.workers('add')), 1)

    def test_native_rate_limit_is_shared_by_five_independent_processes(self):
        self.assertEqual(sum(self.workers('rate')), 3)

    def test_two_native_password_mfa_processes_accept_the_same_totp_only_once(self):
        import time
        from allauth.account.models import EmailAddress
        from allauth.mfa.totp.internal.auth import TOTP, format_hotp_value, generate_totp_secret, hotp_value
        from django.contrib.auth import get_user_model
        from django.test import override_settings
        from .tests import PASSWORD, TEST_KEY, admit_synthetic_user
        with override_settings(STAFF_MFA_ENCRYPTION_KEYS=[TEST_KEY]):
            user = get_user_model().objects.create_user('synthetic_process_staff','process@example.invalid',PASSWORD)
            admit_synthetic_user(user)
            EmailAddress.objects.create(user=user,email=user.email,primary=True,verified=True)
            secret = generate_totp_secret()
            TOTP.activate(user,secret)
            at = time.time()
            code = format_hotp_value(hotp_value(secret,int(at)//30))
        self.assertEqual(sum(self.workers('authenticate',{'username':user.username,'password':PASSWORD,'code':code,'mfa_key':TEST_KEY,'totp_at':at},count=2)),1)

    def test_native_store_failure_never_falls_back_to_local_memory(self):
        from unittest.mock import patch
        from django.db import OperationalError
        cache = self.backend()
        with patch('staff_auth.security_cache.connection.cursor',side_effect=OperationalError('synthetic outage')):
            with self.assertRaises(OperationalError):
                cache.add('allauth.mfa.totp.used?user=synthetic&code=000000','y',60)

    def test_database_retains_only_digested_keys_and_bounded_native_values(self):
        from .models import StaffBrowserSecurityState as State
        cache=self.backend()
        cache.add('allauth.mfa.totp.used?user=987654&code=12 34-56','y',60)
        row=State.objects.get()
        self.assertRegex(row.pk,r'^[a-f0-9]{64}$')
        self.assertEqual(row.payload,'y')
        self.assertNotIn('987654',row.pk)
        self.assertNotIn('12 34-56',row.pk)
        with self.assertRaises(ValueError):
            cache.add('allauth.mfa.totp.used?user=synthetic&code=other','y',None)
        with self.assertRaises(ValueError):
            cache.set('allauth:rl:synthetic',{'credential':'not permitted'},60)

    def test_bounded_cleanup_previews_and_preserves_live_rows(self):
        from datetime import timedelta
        from io import StringIO
        from django.core.management import call_command, CommandError
        from django.utils import timezone
        from .models import StaffBrowserSecurityState as State
        State.objects.create(key_digest='a'*64,payload='y',expires_at=timezone.now()-timedelta(minutes=1))
        self.backend().add('allauth.mfa.totp.used?user=synthetic&code=000000','y',60)
        output=StringIO()
        call_command('purge_staff_browser_security',stdout=output)
        self.assertIn('Preview: 1',output.getvalue())
        self.assertEqual(State.objects.count(),2)
        call_command('purge_staff_browser_security',apply=True,batch_size=1,stdout=StringIO())
        self.assertEqual(State.objects.count(),1)
        for size in (0,10001):
            with self.assertRaises(CommandError):
                call_command('purge_staff_browser_security',batch_size=size,stdout=StringIO())
