"""Explicit operator delivery; proofs never appear in Admin output or audit data."""
from email.utils import parseaddr
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from core.models import ComplianceAuditEvent
from core.services.compliance_audit import record_event
from report_delivery.resend import SubmissionError, submit_email
from .crypto import decrypt_secret
from .initial_setup import canonical_address
from .models import StaffBrowserSetupGrant
from .setup_api import _locked_setup


@sensitive_variables()
def send_invitation(*,actor,setup_id):
    if actor is None or not get_user_model().objects.filter(pk=actor.pk,is_active=True,is_superuser=True).exists():
        raise PermissionDenied('Only an active Django Superuser may send browser setup invitations.')
    if (not settings.STAFF_BROWSER_AUTH_ENABLED or not settings.STAFF_BROWSER_COMPLAINTS_ENABLED or not settings.STAFF_BROWSER_INVITATIONS_ENABLED
            or not settings.RESEND_API_KEY):
        raise ValidationError('Browser invitation delivery is not configured.')
    origin=urlsplit(settings.APP_BASE_URL)
    if origin.scheme!='https' or not origin.hostname or origin.username or origin.password or origin.query or origin.fragment or origin.path not in ('','/'):
        raise ValidationError('Configure the exact HTTPS browser origin before sending invitations.')
    sender=settings.STAFF_BROWSER_EMAIL_FROM
    validate_email(parseaddr(sender)[1])
    with _locked_setup(setup_id) as (grant,user,_address):
        key=f'staff-browser-invitation:{grant.pk}'
        receipt=ComplianceAuditEvent.objects.filter(deduplication_key=key).first()
        if receipt:
            return {'accepted':True,'replayed':True,'audit_event_id':str(receipt.pk)}
        if grant.state!=StaffBrowserSetupGrant.PREPARED or grant.expires_at<=timezone.now():
            raise ValidationError('This setup invitation is no longer pending. Review the current account state.')
        link=settings.APP_BASE_URL.rstrip('/')+'/staff/login/#'+urlencode({
            'setup':str(grant.pk),'key':decrypt_secret(grant.confirmation_cipher)})
        text=('Your JBL staff browser access is ready for setup.\n\n'
              'Open this private link to verify your email address and continue:\n'+link+
              '\n\nThis link expires one hour after it was prepared. Do not forward it. '
              'Your existing password, if any, will not be changed. '
              'You will sign in and set up an authenticator before accessing work.\n'
              'If you are signed in to Django Admin, open this link in a private browser window.\n'
              'If you did not expect this invitation, contact your IT administrator.')
        provider_id=submit_email({'from':sender,'to':[canonical_address(user)],
            'subject':'Set up your JBL staff browser access','text':text},key=key)
        event,_=record_event(workflow='access_control',action='staff_browser.invitation_accepted',category='identity',
            subject_type='staff_browser_setup',subject_id=str(grant.pk),actor=actor,
            request_id=str(grant.pk),deduplication_key=key,
            source_model='staff_auth.StaffBrowserSetupGrant',source_event_id=str(grant.pk),
            after_values={'setup_id':str(grant.pk),'target_user_id':user.pk,'provider_accepted':True},
            metadata={'provider_message_id':provider_id,'purpose':grant.purpose},sensitive=True)
        return {'accepted':True,'replayed':False,'audit_event_id':str(event.pk)}
