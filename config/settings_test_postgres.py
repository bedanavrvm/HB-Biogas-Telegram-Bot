"""Guarded PostgreSQL settings for production-parity database tests."""
from __future__ import annotations

import os
from urllib.parse import urlparse

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403


TEST_DATABASE_URL = str(os.environ.get('TEST_DATABASE_URL') or '').strip()
if not TEST_DATABASE_URL:
    raise ImproperlyConfigured(
        'TEST_DATABASE_URL is required for the PostgreSQL parity test profile.'
    )

parsed = urlparse(TEST_DATABASE_URL)
database_name = parsed.path.lstrip('/')
if parsed.scheme not in {'postgres', 'postgresql'}:
    raise ImproperlyConfigured('TEST_DATABASE_URL must use PostgreSQL, not SQLite.')
if parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}:
    raise ImproperlyConfigured('PostgreSQL parity tests may only use a local database host.')
if 'test' not in database_name.casefold():
    raise ImproperlyConfigured('The local PostgreSQL database name must contain "test".')

DATABASES = {  # noqa: F405
    'default': dj_database_url.parse(TEST_DATABASE_URL, conn_max_age=0),
}
DATABASES['default']['CONN_MAX_AGE'] = 0

