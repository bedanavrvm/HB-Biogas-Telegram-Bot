"""Explicit, loopback test host for human review; never application settings."""
import os
from uuid import uuid4

if os.environ.get('RUN_COMPLAINTS_LOCAL_REVIEW') != '1':
    raise RuntimeError('Local review requires explicit opt-in.')

from .transport_test_settings import *  # noqa: F403

# Never share the automated test DB or an operational connection. The normal
# test runner still creates the full schema before the fixture server starts.
review_directory = test_directory / 'complaints-local-review'  # noqa: F405
review_directory.mkdir(exist_ok=True)
STAFF_BROWSER_LOCAL_REVIEW_DATABASE = str(review_directory / f'review-{uuid4().hex}.sqlite3')
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:',
    'TEST': {'NAME': STAFF_BROWSER_LOCAL_REVIEW_DATABASE},
}}
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', 'testserver']
CSRF_TRUSTED_ORIGINS = []
# This review DB is SQLite; suppress only unsupported schema-comment notices,
# not browser security, configuration or model validation checks.
SILENCED_SYSTEM_CHECKS = [*globals().get('SILENCED_SYSTEM_CHECKS', []), 'fields.W163', 'models.W046']

