"""Dormant, closed TOTP setup; no provisioning, replacement or business login."""
import time
from contextlib import contextmanager

from allauth.account import app_settings as account_settings
from allauth.account.forms import ReauthenticateForm
from allauth.account.internal.flows.reauthentication import reauthenticate_by_password
from allauth.core import context
from allauth.mfa.adapter import get_adapter as get_mfa_adapter
from allauth.mfa.internal.flows.add import validate_can_add_authenticator
from allauth.mfa.models import Authenticator
from allauth.mfa.recovery_codes.internal.flows import view_recovery_codes
from allauth.mfa.totp.forms import ActivateTOTPForm
from allauth.mfa.totp.internal.auth import SECRET_SESSION_KEY
from allauth.mfa.totp.internal.flows import activate_totp
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import DatabaseError, transaction
from django.views.decorators.debug import sensitive_variables

from core.services.compliance_audit import record_event

from .browser_api import _body, _channel, _response, _state, _throttle, browser_endpoint
from .crypto import MFASecretUnavailable
from .enrollment_state import activation_receipt, enrollment_context, receipt, request_uuid
from .models import StaffBrowserAdmission
from .session_protection import ENROLLMENT_CONTEXT_KEY, ENROLLMENT_SECONDS, protected_browser_session


class _Rejected(Exception):
    def __init__(self, state, status=409):
        self.state, self.status = state, status


class _AuditUnavailable(Exception):
    pass


def _discard_draft(request):
    request.session.pop(ENROLLMENT_CONTEXT_KEY, None)
    request.session.pop(SECRET_SESSION_KEY, None)


def _discard_failed_draft(request):
    _discard_draft(request)
    # SessionMiddleware intentionally skips saving on 5xx. Persist this client's
    # cleanup explicitly after the credential transaction has rolled back.
    try:
        request.session.save()
    except DatabaseError:
        # If session storage is also unavailable, no cleanup can be promised.
        # The response still discloses no credentials or business assurance.
        pass


def _audit(request, row, action, key, **metadata):
    try:
        return record_event(
            workflow='access_control', action=f'staff_browser.enrollment_{action}', category='identity',
            subject_type='staff_browser_admission', subject_id=str(row.pk), actor=row.user,
            request_id=key, deduplication_key=f'staff-browser-enrollment-{action}:{row.user_id}:{key}',
            metadata={'channel': 'browser', 'admission_revision': row.revision, **metadata}, sensitive=True,
        )[0]
    except Exception:
        # Outer transaction must roll back native factor/view mutations too.
        raise _AuditUnavailable from None


@contextmanager
def _locked_channel(request):
    channel, row = _channel(request)
    if channel is None or not request.user.is_authenticated or channel.get('audit_event_id'):
        raise _Rejected('signed_out', 401)
    with transaction.atomic():
        # Same target-user -> admission order as lifecycle changes. No lock on
        # audit-chain state is acquired until after these owner locks.
        user = get_user_model().objects.select_for_update().filter(pk=row.user_id).first()
        locked = StaffBrowserAdmission.objects.select_for_update().filter(pk=row.pk).first()
        if user is None or locked is None:
            raise _Rejected('signed_out', 401)
        request.user = user
        current, fresh = _channel(request)
        if current is None or fresh.pk != locked.pk or fresh.revision != locked.revision:
            raise _Rejected('signed_out', 401)
        with protected_browser_session(request), context.request_context(request):
            yield current, fresh


@sensitive_variables()
def _execute(request, fields, scope, operation):
    data = _body(request, {'request_key': 36, **fields})
    if data is None or request_uuid(data['request_key']) is None:
        return _response('invalid_request', 400)
    data['request_key'] = request_uuid(data['request_key'])
    channel, row = _channel(request)
    if channel is None or not request.user.is_authenticated:
        return _response('signed_out', 401)
    limited = _throttle(request, scope, row.user_id)
    if limited is not None:
        return limited
    # Native activation schedules notification callbacks on commit. Until an
    # operational mail path is accepted, hold instead of sending/suppressing it.
    if account_settings.EMAIL_NOTIFICATIONS:
        return _response('enrollment_unavailable', 503)
    try:
        with _locked_channel(request) as (channel, row):
            return operation(request, data, channel, row)
    except _Rejected as exc:
        return _response(exc.state, exc.status)
    except _AuditUnavailable:
        _discard_failed_draft(request)
        return _response('audit_unavailable', 503)
    except MFASecretUnavailable:
        _discard_draft(request)
        return _response('enrollment_restart_required', 409)
    except ImproperlyConfigured:
        _discard_failed_draft(request)
        return _response('enrollment_unavailable', 503)


@sensitive_variables()
def _begin(request, data, channel, row):
    if _state(request) != 'enrollment_required' or Authenticator.objects.filter(user_id=row.user_id).exists():
        raise _Rejected('enrollment_unavailable')
    form = ReauthenticateForm(user=row.user, data={'password': data['password']})
    if not form.is_valid():
        raise _Rejected('invalid_credentials', 400)
    try:
        validate_can_add_authenticator(row.user)
    except ValidationError:
        raise _Rejected('enrollment_unavailable') from None
    saved = enrollment_context(request, channel, row)
    existing = receipt(row.user, row, 'started', data['request_key'], current_revision=False)
    if saved is not None:
        if saved['begin_key'] != data['request_key']:
            raise _Rejected('enrollment_in_progress')
        if existing is None or SECRET_SESSION_KEY not in request.session:
            raise _Rejected('enrollment_restart_required')
        # Do not instantiate an unbound vendor form on retry: it rotates seed.
        secret = request.session[SECRET_SESSION_KEY]
        reauthenticate_by_password(request)
    else:
        if existing is not None:
            raise _Rejected('enrollment_restart_required')
        _discard_draft(request)
        started = time.time()
        reauthenticate_by_password(request)
        secret = ActivateTOTPForm(user=row.user).secret
        event = _audit(request, row, 'started', data['request_key'])
        saved = {
            'begin_key': data['request_key'], 'started_at': started, 'start_event_id': str(event.pk),
            'admission_id': str(row.pk), 'revision': row.revision, 'attempt_id': channel['attempt_id'],
            'session_key': request.session.session_key,
        }
        request.session[ENROLLMENT_CONTEXT_KEY] = saved
    return _response(
        'enrollment_required', otpauth_uri=get_mfa_adapter().build_totp_url(row.user, secret),
        expires_at=saved['started_at'] + ENROLLMENT_SECONDS,
    )


@sensitive_variables()
def _confirm(request, data, channel, row):
    saved = enrollment_context(request, channel, row)
    if saved is None:
        raise _Rejected('enrollment_restart_required')
    previous = activation_receipt(request, row, saved)
    if previous is not None:
        if saved['confirm_key'] != data['request_key']:
            raise _Rejected('enrollment_already_completed')
        return _response(_state(request), receipt_id=str(previous.pk), replayed=True)
    if receipt(row.user, row, 'activated', data['request_key'], current_revision=False) is not None:
        raise _Rejected('enrollment_restart_required')
    if Authenticator.objects.filter(user_id=row.user_id).exists():
        raise _Rejected('enrollment_unavailable')
    if SECRET_SESSION_KEY not in request.session:
        raise _Rejected('enrollment_restart_required')
    # Read/decrypt first: a bound native form otherwise silently creates a seed
    # if no pending secret exists. Never confirm an unbegun/expired operation.
    request.session[SECRET_SESSION_KEY]
    form = ActivateTOTPForm(user=row.user, data={'code': data['code']})
    if not form.is_valid():
        raise _Rejected('invalid_code', 400)
    totp, recovery = activate_totp(request, form)
    if recovery is None:
        raise _Rejected('enrollment_unavailable')
    event = _audit(
        request, row, 'activated', data['request_key'], begin_key=saved['begin_key'],
        authenticator_ids={'totp': totp.pk, 'recovery_codes': recovery.pk},
    )
    request.session[ENROLLMENT_CONTEXT_KEY] = {
        **saved, 'confirm_key': data['request_key'], 'activation_event_id': str(event.pk),
    }
    return _response('recovery_codes_required', receipt_id=str(event.pk), replayed=False)


@sensitive_variables()
def _recovery(request, data, channel, row):
    saved = enrollment_context(request, channel, row)
    event = activation_receipt(request, row, saved) if saved else None
    if event is None:
        raise _Rejected('enrollment_restart_required')
    # The user lock serializes this flow; explicit native factor locks also
    # serialize it against native recovery-code consumption.
    factors = list(Authenticator.objects.select_for_update().filter(user_id=row.user_id).order_by('pk'))
    recovery = next((factor for factor in factors if factor.pk == event.metadata['authenticator_ids']['recovery_codes']), None)
    if recovery is None or recovery.data.get('viewed_at'):
        raise _Rejected('recovery_codes_already_viewed')
    if receipt(row.user, row, 'recovery_viewed', data['request_key'], current_revision=False) is not None:
        raise _Rejected('recovery_codes_already_viewed')
    wrapper, can_view = view_recovery_codes(request)
    if wrapper is None or not can_view or wrapper.instance.pk != event.metadata['authenticator_ids']['recovery_codes']:
        raise _Rejected('recovery_codes_already_viewed')
    codes = wrapper.get_unused_codes()
    viewed = _audit(
        request, row, 'recovery_viewed', data['request_key'], begin_key=saved['begin_key'],
        activation_event_id=str(event.pk), code_count=len(codes),
    )
    return _response('reauthentication_required', recovery_codes=codes, receipt_id=str(viewed.pk))


@browser_endpoint(('POST',))
@sensitive_variables()
def begin_enrollment(request):
    return _execute(request, {'password': 1024}, 'enrollment-password', _begin)


@browser_endpoint(('POST',))
@sensitive_variables()
def confirm_enrollment(request):
    return _execute(request, {'code': 32}, 'enrollment-code', _confirm)


@browser_endpoint(('POST',))
@sensitive_variables()
def enrollment_recovery_codes(request):
    return _execute(request, {}, 'enrollment-recovery', _recovery)
