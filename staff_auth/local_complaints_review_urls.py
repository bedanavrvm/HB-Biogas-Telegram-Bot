"""Synthetic review instructions, only in the dedicated loopback test host."""
import os
from pathlib import Path

from django.conf import settings
from django.http import Http404, HttpResponse
from django.urls import include, path, re_path
from django.utils.html import format_html
from django.views.decorators.http import require_GET

from allauth.mfa.recovery_codes.internal.auth import RecoveryCodes
from allauth.mfa.models import Authenticator
from scripts.serve_ads_browser_preview import importmap_hashes
from .transport_test_urls import auth_patterns, test_only

review_user = None
review_password = ''
review_assets = {}


def review_guard(request):
    expected = Path(getattr(settings, 'STAFF_BROWSER_LOCAL_REVIEW_DATABASE', '.')).resolve()
    if (os.environ.get('RUN_COMPLAINTS_LOCAL_REVIEW') != '1' or review_user is None
            or expected.parent != (settings.BASE_DIR / 'test-results/complaints-local-review').resolve()
            or Path(settings.DATABASES['default']['NAME']).resolve() != expected
            or request.META.get('REMOTE_ADDR') not in {'127.0.0.1', '::1'}
            or request.get_host().split(':')[0] not in {'127.0.0.1', 'localhost'}):
        raise Http404


@test_only
@require_GET
def review(request):
    review_guard(request)
    authenticator = Authenticator.objects.get(user=review_user, type=Authenticator.Type.RECOVERY_CODES)
    unused = RecoveryCodes(authenticator).get_unused_codes()
    response = HttpResponse(format_html(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Local Complaints review</title><body><h1>Local Complaints review</h1>'
        '<p>Synthetic cases only. Nothing here changes production accounts or records. '
        'External services are blocked. This is the latest browser workspace, not the older simulator.</p>'
        '<p><a href="/staff/app/complaints/">Open Complaints</a></p>'
        '<h2>Local test sign-in</h2><dl><dt>Username</dt><dd><code>{}</code></dd>'
        '<dt>Password</dt><dd><code>{}</code></dd><dt>Unused recovery code</dt>'
        '<dd><code>{}</code></dd></dl><p>After the password, choose '
        '<strong>Use a recovery code</strong>. Refresh this page for another unused code if needed.</p>'
        '<p>Enter sample information only. Changes last until this local server stops or restarts.</p>'
        '</body></html>', review_user.username, review_password, unused[0] if unused else 'No codes remaining; restart the local review.'
    ))
    response['Cache-Control'] = 'no-store, private'
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    return response


@test_only
@require_GET
def asset(request, filename='complaints-operations.html'):
    # Startup verified these immutable bytes. Editing/building the next slice
    # must not interrupt the version the reviewer currently has open.
    review_guard(request)
    if not review_assets or '/' + filename not in review_assets:
        raise Http404
    raw, kind = review_assets['/' + filename]
    response = HttpResponse(raw, content_type=kind)
    response['Cache-Control'] = 'no-store, private'
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = (
        "default-src 'none'; script-src 'self' " + ' '.join(importmap_hashes(review_assets)) +
        "; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src blob: data:; "
        "frame-src blob:; font-src 'self'; form-action 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'"
    )
    return response


urlpatterns = [
    path('_review/', review), *auth_patterns,
    path('api/staff/complaints/v1/', include('core.api.browser_complaint_urls')),
    path('api/staff/complaints/operations/v1/groups/<int:group_key>/', include('core.api.browser_complaint_operations_urls')),
    path('', asset),
    re_path(r'^staff/app/complaints/(?:new/|reports/|settings/|cases/[a-f0-9-]{36}/)?$', asset),
    re_path(r'^(?P<filename>[A-Za-z0-9][A-Za-z0-9._-]*\.(?:html|js|css|txt|woff2))$', asset),
]
