"""Opt-in isolated LiveServer only. Never include from production URLs."""
from django.urls import path, re_path
from django.views.decorators.http import require_GET

from core.api.browser_complaint_urls import urlpatterns as read_patterns
from .transport_test_urls import asset_response, auth_patterns, test_only


@require_GET
def asset(request, filename='complaints.html'):
    return asset_response(request, filename, complaints=True)


urlpatterns = [
    *auth_patterns,
    *[path('api/staff/complaints/v1/' + str(route.pattern), test_only(route.callback)) for route in read_patterns],
    path('', asset),
    re_path(r'^(?P<filename>[A-Za-z0-9][A-Za-z0-9._-]*\.(?:html|js|css|txt))$', asset),
]
