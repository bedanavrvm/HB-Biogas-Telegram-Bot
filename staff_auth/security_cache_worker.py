"""Isolated acceptance subprocess. No production invocation or credentials."""
import json
import os
import sys


def main():
    if os.environ.get('RUN_STAFF_BROWSER_E2E') != '1' or os.environ.get('BROWSER_ACCEPTANCE_WORKER_DB') != 'test_browser_acceptance':
        raise RuntimeError('Only the explicit isolated acceptance database is supported.')
    import django
    django.setup()
    from django.conf import settings
    from django.core.cache import caches
    from django.db import connections
    settings.DATABASES['default']['NAME'] = os.environ['BROWSER_ACCEPTANCE_WORKER_DB']
    connections.close_all()
    settings.CACHES['default'] = {'BACKEND':'staff_auth.security_cache.PostgresSecurityCache',
        'KEY_FUNCTION':'staff_auth.cache_keys.native_cache_key'}
    data = json.loads(sys.stdin.readline())
    if data['action'] == 'add':
        accepted = caches['default'].add('allauth.mfa.totp.used?user=synthetic-worker&code=000000', 'y', 60)
    elif data['action'] == 'rate':
        from allauth.core.internal.ratelimit import consume
        from django.test import RequestFactory
        accepted = consume(RequestFactory().post('/'), action='synthetic-worker',
            config={'synthetic-worker':'3/1m/key'}, key='synthetic-identity') is not None
    elif data['action'] == 'authenticate':
        from django.test import Client, override_settings
        from types import SimpleNamespace
        from unittest.mock import patch
        with override_settings(ROOT_URLCONF='staff_auth.test_browser_urls',STAFF_BROWSER_AUTH_ENABLED=True,ALLOWED_HOSTS=['testserver'],
            STAFF_MFA_ENCRYPTION_KEYS=[data['mfa_key']],SECURE_SSL_REDIRECT=False,SESSION_COOKIE_SECURE=False,CSRF_COOKIE_SECURE=False):
            client=Client(enforce_csrf_checks=True)
            client.get('/test-staff-auth/v1/session/')
            def post(path,body):
                return client.post('/test-staff-auth/v1/'+path+'/',json.dumps(body),content_type='application/json',
                    HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
            result=post('login',{'username':data['username'],'password':data['password']})
            if result.json()['state']!='mfa_required':
                raise RuntimeError('Native password step did not reach MFA.')
            # Pin only the native TOTP clock, not session/admission/audit time.
            # Process startup must not turn a duplicate-use race into expiry.
            with patch('allauth.mfa.totp.internal.auth.time',SimpleNamespace(time=lambda:data['totp_at'])):
                result=post('mfa',{'code':data['code']})
            accepted=result.json()['state']=='authenticated'
            if not accepted and result.status_code!=400:
                raise RuntimeError('Native rejection state: '+result.json().get('state','unknown'))
    else:
        raise RuntimeError('Unsupported acceptance action.')
    print(json.dumps({'accepted':accepted}))
    connections.close_all()


if __name__ == '__main__':
    main()
