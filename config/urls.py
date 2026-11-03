"""biogas_bot URL Configuration"""
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include
from complaint_legacy.views import telegram_page as complaint_legacy_page

urlpatterns = [
    path('favicon.ico', lambda request: HttpResponse(status=204)),
    path('admin/', admin.site.urls),
    path('ops/health/', include('health_check.urls')),
    path('ui-lab/', include('ui_review.urls')),
    path('complaints/legacy-import/', complaint_legacy_page, name='complaint_legacy_page'),
    path('', include('staff_auth.production_urls')),
    path('api/', include('core.api.urls')),
    path('', include('core.api.browser_urls')),
    path('', include('core.api.legacy_urls')),
]
