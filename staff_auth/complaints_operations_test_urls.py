"""Real browser operations only in an explicitly opted-in isolated test server."""
from django.http import Http404, HttpResponse
from django.urls import include, path, re_path
from django.views.decorators.http import require_GET

from scripts.serve_ads_browser_preview import importmap_hashes
from .transport_test_urls import assets, auth_patterns, test_only


@test_only
@require_GET
def asset(request, filename='complaints-operations.html'):
    routes = assets(operations=True)
    if '/' + filename not in routes:
        raise Http404
    raw, kind = routes['/' + filename]
    response = HttpResponse(raw, content_type=kind)
    response['Cache-Control'] = 'no-store, private'
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = (
        "default-src 'none'; script-src 'self' " + ' '.join(importmap_hashes(routes)) +
        "; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src blob: data:; "
        "frame-src blob:; font-src 'self'; form-action 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'"
    )
    return response


urlpatterns = [
    *auth_patterns,
    path('api/staff/complaints/v1/', include('core.api.browser_complaint_urls')),
    path('api/staff/complaints/operations/v1/groups/<int:group_key>/', include('core.api.browser_complaint_operations_urls')),
    path('', asset),
    re_path(r'^staff/app/complaints/(?:new/|reports/|settings/|cases/[a-f0-9-]{36}/)?$', asset),
    re_path(r'^(?P<filename>[A-Za-z0-9][A-Za-z0-9._-]*\.(?:html|js|css|txt|woff2))$', asset),
]
