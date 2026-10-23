"""Pinned allauth security keys on PostgreSQL; unrelated workflow cache unchanged."""
from contextlib import contextmanager
import hashlib
import json
import math
import uuid

from django.core.cache.backends.base import DEFAULT_TIMEOUT
from django.core.cache.backends.locmem import LocMemCache
from django.core.exceptions import ImproperlyConfigured
from django.db import connection, transaction
from django.db.models.functions import Now
from django.views.decorators.debug import sensitive_variables


class PostgresSecurityCache(LocMemCache):
    def __init__(self, name, params):
        super().__init__(name, params)
        self._leases = {}

    @sensitive_variables()
    def _native(self, key):
        if not isinstance(key, str) or not key.startswith(('allauth:', 'allauth.')):
            return False
        if not key.startswith(('allauth:rl:', 'allauth.mfa.totp.used?')):
            raise ImproperlyConfigured('Unreviewed native security-cache namespace.')
        if connection.vendor != 'postgresql':
            raise ImproperlyConfigured('Native browser security state requires PostgreSQL.')
        return True

    @sensitive_variables()
    def _digest(self, key, version):
        from .cache_keys import native_cache_key
        return hashlib.sha256(native_cache_key(key, self.key_prefix, self.version if version is None else version).encode()).hexdigest()

    def _ttl(self, timeout):
        value = self.default_timeout if timeout is DEFAULT_TIMEOUT else timeout
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 86400:
            raise ValueError('Native security state requires a positive bounded expiry.')
        return value

    @contextmanager
    def _history(self, key, version):
        from .models import StaffBrowserSecurityState as State
        lock = self._digest(key + ':lock', version)
        owner = self._leases.get(lock)
        with transaction.atomic():
            if not owner or not State.objects.using('default').select_for_update().filter(
                pk=lock, expires_at__gt=Now(), payload={'lease': owner},
            ).exists():
                raise RuntimeError('Native security lock expired. Authentication must be retried.')
            yield

    @sensitive_variables()
    def add(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        if not self._native(key):
            return super().add(key, value, timeout, version)
        lock = key.startswith('allauth:rl:') and key.endswith(':lock')
        if (lock and value is not True) or (not lock and (not key.startswith('allauth.mfa.totp.used?') or value != 'y')):
            raise ValueError('Unsupported native security marker.')
        digest, owner = self._digest(key, version), uuid.uuid4().hex
        payload = {'lease': owner} if lock else 'y'
        with connection.cursor() as cursor:
            cursor.execute('''INSERT INTO staff_auth_browser_security_state (key_digest, payload, expires_at)
                VALUES (%s, %s::jsonb, statement_timestamp() + %s * interval '1 second')
                ON CONFLICT (key_digest) DO UPDATE SET payload=EXCLUDED.payload, expires_at=EXCLUDED.expires_at
                WHERE staff_auth_browser_security_state.expires_at <= statement_timestamp()
                RETURNING key_digest''', [digest, json.dumps(payload), self._ttl(timeout)])
            accepted = cursor.fetchone() is not None
        if accepted and lock:
            self._leases[digest] = owner
        return accepted

    @sensitive_variables()
    def get(self, key, default=None, version=None):
        if not self._native(key):
            return super().get(key, default, version)
        from .models import StaffBrowserSecurityState as State
        row = State.objects.using('default').filter(pk=self._digest(key, version), expires_at__gt=Now()).values_list('payload', flat=True).first()
        return default if row is None else row

    @sensitive_variables()
    def set(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        if not self._native(key):
            return super().set(key, value, timeout, version)
        if not key.startswith('allauth:rl:') or key.endswith(':lock') or not isinstance(value, list) or len(value) > 10000 or any(
            type(item) not in (float, int) or not math.isfinite(item) for item in value
        ):
            raise ValueError('Unsupported native rate-limit history.')
        with self._history(key, version), connection.cursor() as cursor:
            cursor.execute('''INSERT INTO staff_auth_browser_security_state (key_digest, payload, expires_at)
                VALUES (%s, %s::jsonb, statement_timestamp() + %s * interval '1 second')
                ON CONFLICT (key_digest) DO UPDATE SET payload=EXCLUDED.payload, expires_at=EXCLUDED.expires_at''',
                [self._digest(key, version), json.dumps(value), self._ttl(timeout)])

    @sensitive_variables()
    def delete(self, key, version=None):
        if not self._native(key):
            return super().delete(key, version)
        from .models import StaffBrowserSecurityState as State
        digest = self._digest(key, version)
        if key.endswith(':lock'):
            owner = self._leases.pop(digest, None)
            return bool(owner and State.objects.using('default').filter(pk=digest, payload={'lease':owner}).delete()[0])
        if key.startswith('allauth.mfa.totp.used?'):
            raise ValueError('Live native use markers cannot be cleared.')
        with self._history(key, version):
            return bool(State.objects.using('default').filter(pk=digest).delete()[0])

    def has_key(self, key, version=None):
        marker = object()
        return self.get(key, marker, version) is not marker

    def touch(self, key, timeout=DEFAULT_TIMEOUT, version=None):
        if self._native(key):
            raise ValueError('Native security expiry cannot be extended implicitly.')
        return super().touch(key, timeout, version)

    def incr(self, key, delta=1, version=None):
        if self._native(key):
            raise ValueError('Unreviewed native counter operation.')
        return super().incr(key, delta, version)

    # Inherited clear/culling affect only ordinary local entries. Live native
    # state has no global deletion API; only bounded expiry maintenance may purge.
