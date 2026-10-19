"""Synthetic-only integration harness, not a deployed authentication mount."""
from django.urls import include, path


urlpatterns = [path('test-staff-auth/', include('staff_auth.browser_urls'))]
