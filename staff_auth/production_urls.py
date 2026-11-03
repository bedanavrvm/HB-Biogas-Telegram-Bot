"""Explicit first-production-workflow routes; each boundary retains its own gate."""
from django.urls import include, path, re_path
from . import production
from complaint_legacy.views import browser_page as complaint_legacy_page

urlpatterns = [
    path('staff/app/complaints/legacy-import/', complaint_legacy_page, name='staff_complaint_legacy'),
    path('api/staff/auth/',include('staff_auth.browser_urls')),
    path('api/staff/complaints/v1/',include('core.api.browser_complaint_urls')),
    path('api/staff/complaints/operations/v1/groups/<int:group_key>/',include('core.api.browser_complaint_operations_urls')),
    path('staff/',production.home,name='staff_browser_home'),
    path('staff/login/',production.entry,name='staff_browser_signin'),
    path('staff/assets/<str:filename>',production.asset,name='staff_browser_asset'),
    path('THIRD_PARTY_NOTICES.txt',production.asset,{'filename':'THIRD_PARTY_NOTICES.txt'},name='staff_browser_notices'),
    re_path(r'^staff/app/complaints/(?:new/|reports/|settings/|cases/[a-f0-9-]{36}/)?$',production.entry,name='staff_browser_complaints'),
]
