"""Unit-test URLconf; no operational application mounts."""
from django.urls import include, path

urlpatterns = [
    path('test-staff-auth/', include('staff_auth.browser_urls')),
    path('api/staff/complaints/v1/', include('core.api.browser_complaint_urls')),
]
