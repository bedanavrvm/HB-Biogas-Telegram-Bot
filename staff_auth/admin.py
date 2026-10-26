"""Do not expose vendor credential/email editors as a recovery workflow."""
from allauth.account.models import EmailAddress, EmailConfirmation
from allauth.mfa.models import Authenticator
from django.contrib import admin

from .models import StaffBrowserAdmission, StaffBrowserSetupGrant, StaffTOTPReplayState


# Django's admin autodiscovery imports the vendor registrations first. Future
# staff provisioning/recovery must use reviewed actions, not raw JSON secrets,
# a generic delete, or a bulk "verified email" checkbox.
for model in (EmailAddress, EmailConfirmation, Authenticator, StaffBrowserAdmission, StaffBrowserSetupGrant, StaffTOTPReplayState):
    if admin.site.is_registered(model):
        admin.site.unregister(model)
