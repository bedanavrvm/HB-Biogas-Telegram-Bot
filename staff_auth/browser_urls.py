"""Reviewed narrow contract; intentionally not included by config.urls yet."""
from django.urls import path

from . import browser_api, enrollment, setup_api


urlpatterns = [
    path('v1/setup/session/', setup_api.setup_session, name='staff_browser_setup_session'),
    path('v1/setup/verify-email/', setup_api.verify_setup_email, name='staff_browser_setup_verify'),
    path('v1/setup/password/', setup_api.set_initial_password, name='staff_browser_setup_password'),
    path('v1/session/', browser_api.session_state, name='staff_browser_session'),
    path('v1/login/', browser_api.password_login, name='staff_browser_login'),
    path('v1/mfa/', browser_api.authenticate_mfa, name='staff_browser_mfa'),
    path('v1/logout/', browser_api.browser_logout, name='staff_browser_logout'),
    path('v1/enrollment/begin/', enrollment.begin_enrollment, name='staff_browser_enrollment_begin'),
    path('v1/enrollment/session/', enrollment.enrollment_session, name='staff_browser_enrollment_session'),
    path('v1/enrollment/confirm/', enrollment.confirm_enrollment, name='staff_browser_enrollment_confirm'),
    path('v1/enrollment/recovery-codes/', enrollment.enrollment_recovery_codes, name='staff_browser_enrollment_recovery'),
]
