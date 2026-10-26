"""LiveServer-only React integration; never import from a production URLconf."""
import hashlib
import json
from functools import wraps
from pathlib import Path
import re

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.urls import path, re_path
from django.views.decorators.http import require_GET

from core.models import GroupSheetConfiguration
from core.services.complaint_cases import ComplaintCaseError, staff_actor_for_user
from scripts.serve_ads_browser_preview import importmap_hashes, TYPES

from . import browser_api, enrollment, setup_api
from .browser_api import require_company_browser_user


def _guard():
    if not settings.RUNNING_TESTS or not getattr(settings, 'STAFF_BROWSER_TRANSPORT_TEST', False):
        raise ImproperlyConfigured('This URLconf is restricted to isolated transport tests.')


def assets(*, complaints=False, operations=False):
    _guard()
    builds = ('dist-complaints-operations', 'dist-complaints-operations-development') if operations else ('dist-complaints', 'dist-complaints-development') if complaints else ('dist-authentication', 'dist-authentication-development')
    if settings.STAFF_BROWSER_TRANSPORT_BUILD not in builds:
        raise ValueError('Only isolated authentication build directories are supported.')
    directory = Path(settings.BASE_DIR) / 'browser' / settings.STAFF_BROWSER_TRANSPORT_BUILD
    manifest = json.loads((directory / 'build-manifest.json').read_bytes())
    if manifest.get('schemaVersion') != 1 or manifest.get('demoOnly') is not False or manifest.get('closedAuthentication') is not True:
        raise ValueError('Expected a separately built closed authentication client.')
    if bool(manifest.get('closedComplaints')) != complaints:
        raise ValueError('Wrong isolated workflow build kind.')
    if bool(manifest.get('closedComplaintOperations')) != operations:
        raise ValueError('Wrong isolated operations build kind.')
    routes = {}
    for row in manifest['sources']:
        if not row['path'].startswith('browser/src/') or '..' in Path(row['path']).parts:
            raise ValueError('Unexpected source path.')
        raw = (settings.BASE_DIR / row['path']).read_bytes().replace(b'\r\n', b'\n')
        if hashlib.sha256(raw).hexdigest() != row['sha256']:
            raise ValueError('Reject stale authentication source/build evidence.')
    for row in manifest['files']:
        name = row['name']
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*\.(html|js|css|txt)', name):
            raise ValueError('Unexpected asset path.')
        source = directory / name
        if source.is_symlink() or source.resolve().parent != directory.resolve():
            raise ValueError('Unexpected asset location.')
        raw = source.read_bytes()
        if len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256'] or '/' + name in routes:
            raise ValueError('Reject changed or duplicate authentication assets.')
        routes['/' + name] = raw, TYPES[source.suffix] + '; charset=utf-8'
    if ('/complaints-operations.html' if operations else '/complaints.html' if complaints else '/access.html') not in routes or '/THIRD_PARTY_NOTICES.txt' not in routes:
        raise ValueError('Missing entry or notices.')
    return routes


@require_GET
def asset(request, filename='access.html'):
    return asset_response(request, filename)


def asset_response(request, filename, *, complaints=False):
    routes = assets(complaints=complaints)
    if request.GET or '/' + filename not in routes:
        raise Http404
    raw, content_type = routes['/' + filename]
    response = HttpResponse(raw, content_type=content_type)
    hashes = ' '.join(importmap_hashes(routes))
    response['Cache-Control'] = 'no-store, private'
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = (
        "default-src 'none'; script-src 'self' " + hashes + "; style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; img-src data:; font-src 'none'; form-action 'none'; "
        "base-uri 'none'; object-src 'none'; frame-ancestors 'none'"
    )
    return response


@require_GET
def identity(request):
    _guard()
    require_company_browser_user(request)
    return JsonResponse({'identity_confirmed': True})


@require_GET
def complaints(request):
    _guard()
    user = require_company_browser_user(request)
    group = GroupSheetConfiguration.objects.get(group_id='synthetic-browser-complaints')
    try:
        staff_actor_for_user(group, user)
    except ComplaintCaseError:
        raise PermissionDenied('Workflow authority is required.') from None
    return JsonResponse({'workflow_authorized': True})


urlpatterns = [
    path('test-context/identity/', identity),
    path('test-context/complaints/', complaints),
    path('', asset),
    re_path(r'^(?P<filename>[A-Za-z0-9][A-Za-z0-9._-]*\.(?:html|js|css|txt))$', asset),
]


def test_only(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        _guard()
        return view(request, *args, **kwargs)
    return guarded


auth_patterns = [
    path(f'api/staff/auth/v1/{action}/', test_only(view))
    for action, view in (
        ('session', browser_api.session_state), ('login', browser_api.password_login),
        ('mfa', browser_api.authenticate_mfa), ('logout', browser_api.browser_logout),
        ('setup/session', setup_api.setup_session), ('setup/verify-email', setup_api.verify_setup_email),
        ('setup/password', setup_api.set_initial_password), ('enrollment/session', enrollment.enrollment_session),
        ('enrollment/begin', enrollment.begin_enrollment), ('enrollment/confirm', enrollment.confirm_enrollment),
        ('enrollment/recovery-codes', enrollment.enrollment_recovery_codes),
    )
]
urlpatterns += auth_patterns
