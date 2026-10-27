"""Unmounted initial mailbox/password setup; never a login or recovery API."""
from contextlib import contextmanager

from allauth.account import app_settings as account_settings, signals as account_signals
from allauth.account.adapter import get_adapter
from allauth.account.forms import SetPasswordForm
from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from allauth.core import context
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.contrib.sessions.backends.base import UpdateError
from django.core import signing
from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, transaction
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.debug import sensitive_variables

from core.models import ComplianceAuditEvent
from core.services.compliance_audit import record_event

from .abuse import AbuseControlUnavailable, consume_network
from .browser_api import _body, _rate_limited, _response, _throttle, browser_endpoint
from .crypto import MFASecretUnavailable, decrypt_secret
from .enrollment_state import request_uuid
from .initial_setup import PROOF_SALT, SETUP_SECONDS, InitialSetupError, binding_digest, canonical_address, require_setup_account
from .models import StaffBrowserAdmission, StaffBrowserSetupGrant
from .session_protection import SETUP_CONTEXT_KEY


class _Rejected(Exception):
    def __init__(self, state='setup_invalid', status=409):
        self.state, self.status = state, status


class _AuditUnavailable(Exception):
    pass


def _ready():
    # Native verification emits these synchronously. A new receiver requires
    # review before it may run within this credential/audit transaction.
    return not (
        settings.ACCOUNT_ADAPTER != 'staff_auth.adapters.StaffAccountAdapter'
        or account_settings.EMAIL_NOTIFICATIONS or account_settings.CHANGE_EMAIL
        or account_signals.email_confirmed.has_listeners(EmailAddress)
        or account_signals.email_added.has_listeners(EmailAddress)
        or account_signals.password_set.has_listeners(get_user_model())
    )


def _receipt(grant, action, event_id, actor_id=None):
    query = ComplianceAuditEvent.objects.filter(
        pk=event_id, action=f'staff_browser.setup_{action}',
        subject_type='staff_browser_setup', subject_id=str(grant.pk),
        source_model='staff_auth.StaffBrowserSetupGrant', source_event_id=str(grant.pk),
    )
    if actor_id is not None:
        query = query.filter(actor_id=actor_id)
    return query.first()


def _audit(grant, user, action, key):
    try:
        return record_event(
            workflow='access_control', action=f'staff_browser.setup_{action}', category='identity',
            subject_type='staff_browser_setup', subject_id=str(grant.pk), actor=user,
            request_id=key, deduplication_key=f'staff-browser-setup-{action}:{grant.pk}',
            source_model='staff_auth.StaffBrowserSetupGrant', source_event_id=str(grant.pk),
            metadata={'admission_revision': grant.admission_revision, 'channel': 'browser'}, sensitive=True,
        )[0]
    except Exception:
        raise _AuditUnavailable from None


@contextmanager
def _locked_setup(setup_id):
    initial = StaffBrowserSetupGrant.objects.filter(pk=setup_id).select_related('admission').first()
    if initial is None or initial.admission.user_id is None:
        raise _Rejected()
    with transaction.atomic():
        user = get_user_model().objects.select_for_update().filter(pk=initial.admission.user_id).first()
        admission = StaffBrowserAdmission.objects.select_for_update().filter(pk=initial.admission_id).first()
        grant = StaffBrowserSetupGrant.objects.select_for_update().filter(pk=setup_id).first()
        if (
            user is None or admission is None or grant is None or not user.is_active
            or (grant.purpose == StaffBrowserSetupGrant.INITIAL_PASSWORD and (user.is_staff or user.is_superuser)) or not admission.enabled
            or grant.admission_id != admission.pk
            or admission.user_id != user.pk or admission.revision != grant.admission_revision
            or grant.expires_at <= timezone.now()
        ):
            raise _Rejected()
        preparation = _receipt(grant, 'prepared', grant.prepared_audit_id)
        expected = {
            'setup_id': str(grant.pk), 'target_user_id': user.pk,
            'admission_id': str(admission.pk), 'revision': grant.admission_revision,
            'email_address_id': grant.email_address_id, 'email_fingerprint': grant.email_fingerprint,
            'password_fingerprint': grant.password_fingerprint, 'expires_at': grant.expires_at.isoformat(),
        }
        if grant.purpose != StaffBrowserSetupGrant.INITIAL_PASSWORD: expected['purpose']=grant.purpose
        if preparation is None or preparation.after_values != expected:
            raise _Rejected()
        email = canonical_address(user)
        if not constant_time_compare(binding_digest('email', email), grant.email_fingerprint):
            raise _Rejected()
        address = EmailAddress.objects.select_for_update().filter(
            pk=grant.email_address_id, user_id=user.pk, primary=True,
        ).first()
        if address is None or address.email.lower() != email:
            raise _Rejected()
        if grant.state != StaffBrowserSetupGrant.COMPLETED:
            require_setup_account(user, admission,grant.purpose)
            if not constant_time_compare(binding_digest('password-state', user.password), grant.password_fingerprint):
                raise _Rejected()
            if EmailAddress.objects.filter(user_id=user.pk).exclude(pk=address.pk).exists():
                raise _Rejected()
        yield grant, user, address


def _session_matches(request, grant):
    saved = request.session.get(SETUP_CONTEXT_KEY)
    return bool(
        isinstance(saved, dict) and saved.get('setup_id') == str(grant.pk)
        and saved.get('verify_audit_id') == str(grant.verify_audit_id)
        and request.session.session_key
        and constant_time_compare(binding_digest('session', request.session.session_key), grant.session_digest)
    )


def _cleanup_failure(request):
    request.session.pop(SETUP_CONTEXT_KEY, None)
    list(messages.get_messages(request))  # Do not retain a native success message after rollback.
    try:
        request.session.save()  # SessionMiddleware skips 5xx saves.
    except (DatabaseError, UpdateError):
        pass


@sensitive_variables()
def _execute(request, fields, operation):
    if request.user.is_authenticated:
        return _response('sign_out_required', 409)
    data = _body(request, {'setup_id': 36, 'request_key': 36, **fields})
    if data is None or request_uuid(data['setup_id']) is None or request_uuid(data['request_key']) is None:
        return _response('invalid_request', 400)
    data['setup_id'], data['request_key'] = request_uuid(data['setup_id']), request_uuid(data['request_key'])
    limited = _throttle(request, f'initial-setup-{operation.__name__}', data['setup_id'])
    if limited is not None:
        return limited
    if not request.session.session_key:
        return _response('setup_session_required', 409)
    if not _ready():
        return _response('setup_unavailable', 503)
    try:
        with _locked_setup(data['setup_id']) as (grant, user, address), context.request_context(request):
            return operation(request, data, grant, user, address)
    except _Rejected as exc:
        return _response(exc.state, exc.status)
    except InitialSetupError:
        return _response('setup_invalid', 409)
    except _AuditUnavailable:
        _cleanup_failure(request)
        return _response('audit_unavailable', 503)
    except (DatabaseError, MFASecretUnavailable, ImproperlyConfigured):
        _cleanup_failure(request)
        return _response('setup_unavailable', 503)


@sensitive_variables()
def _verify(request, data, grant, user, address):
    if grant.state == StaffBrowserSetupGrant.COMPLETED:
        if (grant.purpose == StaffBrowserSetupGrant.VERIFY_EMAIL and _session_matches(request,grant)
                and grant.completed_request_key == data['request_key']
                and _receipt(grant,'completed',grant.completed_audit_id,user.pk)):
            return _response('reauthentication_required',username=user.username,replayed=True)
        raise _Rejected('setup_completed')
    if not constant_time_compare(decrypt_secret(grant.confirmation_cipher), data['confirmation_key']):
        raise _Rejected('setup_invalid', 400)
    session_digest = binding_digest('session', request.session.session_key)
    if grant.state == StaffBrowserSetupGrant.VERIFIED:
        if (
            not address.verified or grant.verify_request_key != data['request_key']
            or not constant_time_compare(session_digest, grant.session_digest)
            or _receipt(grant, 'verified', grant.verify_audit_id, user.pk) is None
        ):
            raise _Rejected()
        replayed = True
    else:
        if address.verified:
            raise _Rejected()
        try:
            envelope = signing.loads(data['confirmation_key'], salt=PROOF_SALT, max_age=SETUP_SECONDS)
        except signing.BadSignature:
            raise _Rejected('setup_invalid', 400) from None
        if not isinstance(envelope, dict) or set(envelope) != {'setup_id', 'native_key'} or envelope['setup_id'] != str(grant.pk):
            raise _Rejected('setup_invalid', 400)
        proof = EmailConfirmationHMAC.from_key(envelope['native_key'])
        if proof is None or proof.email_address.pk != address.pk or proof.confirm(request) is None:
            raise _Rejected('setup_invalid', 400)
        # The prepared address is already primary and CHANGE_EMAIL is false,
        # so native confirmation does not rewrite canonical User.email.
        event = _audit(grant, user, 'verified', data['request_key'])
        grant.state, grant.verify_request_key = StaffBrowserSetupGrant.VERIFIED, data['request_key']
        grant.session_digest, grant.verify_audit_id = session_digest, event.pk
        grant.save(update_fields=['state', 'verify_request_key', 'session_digest', 'verify_audit_id'])
        replayed = False
    request.session[SETUP_CONTEXT_KEY] = {'setup_id': str(grant.pk), 'verify_audit_id': str(grant.verify_audit_id)}
    if grant.purpose == StaffBrowserSetupGrant.VERIFY_EMAIL:
        event=_audit(grant,user,'completed',data['request_key'])
        grant.state=StaffBrowserSetupGrant.COMPLETED
        grant.completed_request_key=data['request_key']
        grant.completed_audit_id=event.pk
        grant.confirmation_cipher=''
        grant.save(update_fields=['state','completed_request_key','completed_audit_id','confirmation_cipher'])
        return _response('reauthentication_required',username=user.username,replayed=False)
    return _response('password_required', receipt_id=str(grant.verify_audit_id), replayed=replayed)


def _notify_password_set(request, user):
    get_adapter(request).send_notification_mail('account/email/password_set', user)
    account_signals.password_set.send(sender=user.__class__, request=request, user=user)


@sensitive_variables()
def _password(request, data, grant, user, address):
    if grant.purpose != StaffBrowserSetupGrant.INITIAL_PASSWORD: raise _Rejected()
    if not address.verified or not _session_matches(request, grant):
        raise _Rejected()
    if _receipt(grant, 'verified', grant.verify_audit_id, user.pk) is None:
        raise _Rejected()
    if grant.state == StaffBrowserSetupGrant.COMPLETED:
        if (
            grant.completed_request_key != data['request_key']
            or data['password1'] != data['password2']
            or not check_password(data['password1'], user.password)
            or _receipt(grant, 'completed', grant.completed_audit_id, user.pk) is None
        ):
            raise _Rejected('setup_completed')
        return _response('reauthentication_required', receipt_id=str(grant.completed_audit_id), replayed=True)
    if grant.state != StaffBrowserSetupGrant.VERIFIED:
        raise _Rejected()
    form = SetPasswordForm(user=user, data={'password1': data['password1'], 'password2': data['password2']})
    if not form.is_valid():
        return _response('invalid_password', 400, field_errors=form.errors.get_json_data())
    form.save()
    event = _audit(grant, user, 'completed', data['request_key'])
    grant.state, grant.completed_request_key = StaffBrowserSetupGrant.COMPLETED, data['request_key']
    grant.completed_audit_id, grant.confirmation_cipher = event.pk, ''
    grant.save(update_fields=['state', 'completed_request_key', 'completed_audit_id', 'confirmation_cipher'])
    transaction.on_commit(lambda: _notify_password_set(request, user))
    return _response('reauthentication_required', receipt_id=str(event.pk), replayed=False)


@browser_endpoint(('GET',))
def setup_session(request):
    if request.user.is_authenticated:
        return _response('sign_out_required', 409)
    try:
        limited = consume_network(request, scope='staff-browser-setup-bootstrap')
    except (DatabaseError, ImproperlyConfigured):
        raise AbuseControlUnavailable from None
    if not limited.allowed:
        return _rate_limited(limited.retry_after)
    if not request.session.session_key:
        request.session.create()
    saved = request.session.get(SETUP_CONTEXT_KEY)
    setup_id = request_uuid(saved.get('setup_id')) if isinstance(saved, dict) else None
    if setup_id is not None:
        try:
            with _locked_setup(setup_id) as (grant, user, address):
                if _session_matches(request, grant) and address.verified and _receipt(grant, 'verified', grant.verify_audit_id, user.pk):
                    completed = grant.state == StaffBrowserSetupGrant.COMPLETED
                    if not completed or _receipt(grant, 'completed', grant.completed_audit_id, user.pk):
                        return _response('reauthentication_required' if completed else 'password_required',
                                         setup_id=str(grant.pk), username=user.username, csrf_token=get_token(request))
        except (_Rejected, InitialSetupError, DatabaseError, MFASecretUnavailable):
            # Stale/cross-session/revoked context exposes no account details.
            pass
    return _response('setup_required', csrf_token=get_token(request))


@browser_endpoint(('POST',))
@sensitive_variables()
def verify_setup_email(request):
    return _execute(request, {'confirmation_key': 2048}, _verify)


@browser_endpoint(('POST',))
@sensitive_variables()
def set_initial_password(request):
    return _execute(request, {'password1': 1024, 'password2': 1024}, _password)
