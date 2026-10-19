"""MFA completion issues assurance; any ordinary Django login clears it."""
from allauth.account.signals import user_logged_in as allauth_logged_in
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from .assurance import clear_assurance, issue_assurance


@receiver(user_logged_in, dispatch_uid='staff_auth.clear_on_django_login')
@receiver(user_logged_out, dispatch_uid='staff_auth.clear_on_logout')
def clear_on_login_boundary(sender, request, **kwargs):
    clear_assurance(request)


@receiver(allauth_logged_in, dispatch_uid='staff_auth.issue_after_allauth_login')
def completed_company_login(sender, request, user, **kwargs):
    issue_assurance(request, user)
