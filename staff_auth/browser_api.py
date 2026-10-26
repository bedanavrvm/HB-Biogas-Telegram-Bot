"""Constrained JSON authentication adapter; production URLs remain unmounted."""
import json
import math
import time
import uuid
from functools import wraps

from allauth.account.adapter import get_adapter
from allauth.account.authentication import get_authentication_records
from allauth.account.internal.flows.login import AUTHENTICATION_METHODS_SESSION_KEY
from allauth.account.internal.stagekit import clear_login, get_pending_stage
from allauth.account.models import EmailAddress
from allauth.headless.account.views import LoginView
from allauth.headless.constants import Client
from allauth.mfa.models import Authenticator
from allauth.mfa.stages import AuthenticateStage
from django.conf import settings
from django.contrib.auth import HASH_SESSION_KEY, get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.sessions.backends.base import UpdateError
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.db import DatabaseError
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.utils.crypto import constant_time_compare

from core.services.compliance_audit import record_event
from core.models import ComplianceAuditEvent
from core.services.request_throttling import consume_identity

from .assurance import MAX_LOGIN_SECONDS, clear_assurance, require_browser_user
from .abuse import AbuseControlUnavailable, AuthenticationUnavailable, consume_network, native_authentication
from .enrollment_state import enrollment_progress
from .models import StaffBrowserAdmission
from .replay import BrowserAuthenticateView
from .session_protection import CHANNEL_KEY, clear_browser_context, protected_browser_session


_login = LoginView.as_api_view(client=Client.BROWSER)
_mfa = BrowserAuthenticateView.as_api_view(client=Client.BROWSER)


def _response(state, status=200, **extra):
    return JsonResponse({'state': state, 'is_authenticated': state == 'authenticated', **extra}, status=status)


def browser_endpoint(methods):
    """Separate cookie/CSRF boundary; never a session fallback on Telegram APIs."""
    def decorate(function):
        protected = csrf_protect(function)

        @wraps(function)
        @sensitive_post_parameters()
        def endpoint(request, *args, **kwargs):
            if not settings.STAFF_BROWSER_AUTH_ENABLED:
                response = _response('unavailable', 404)
            elif any(name in request.headers for name in ('X-Telegram-Init-Data', 'X-Session-Token', 'Authorization')):
                response = _response('invalid_credentials', 403)
            elif request.method not in methods:
                response = _response('method_not_allowed', 405)
                response['Allow'] = ', '.join(methods)
            else:
                # Native flows/callbacks use JSON feedback here. Keep this
                # request-local marker through commit; unused flash cookies
                # must not retain staff data or reappear in another page.
                request._staff_browser_json_feedback = True
                try:
                    response = protected(request, *args, **kwargs)
                except AbuseControlUnavailable:
                    response = _response('authentication_unavailable', 503)
                except AuthenticationUnavailable:
                    response = _authentication_unavailable(request)
            response['Cache-Control'] = 'no-store, private'
            response['Pragma'] = 'no-cache'
            return response
        return endpoint
    return decorate


def _admission(user_id):
    return StaffBrowserAdmission.objects.select_related('user').filter(
        user_id=user_id, enabled=True, user__is_active=True,
    ).first()


def _verified(user_id):
    return EmailAddress.objects.filter(user_id=user_id, primary=True, verified=True).exists()


def _channel(request):
    context = request.session.get(CHANNEL_KEY)
    if not isinstance(context, dict) or type(context.get('user_id')) is not int or not 0 < context['user_id'] <= 9223372036854775807:
        return None, None
    if request.user.is_authenticated and request.user.pk != context['user_id']:
        return None, None
    stamp = context.get('started_at')
    age_limit = settings.STAFF_BROWSER_SESSION_AGE_SECONDS if context.get('audit_event_id') else MAX_LOGIN_SECONDS
    if type(stamp) not in (int, float) or not math.isfinite(stamp) or not 0 <= time.time() - stamp <= age_limit:
        return None, None
    row = _admission(context['user_id'])
    if (
        row is None or str(row.pk) != context.get('admission_id')
        or type(context.get('revision')) is not int or row.revision != context['revision']
        or stamp < row.updated_at.timestamp() or not _verified(row.user_id)
    ):
        return None, None
    return context, row


def require_company_browser_user(request):
    """Future browser business APIs use this AND owning workflow authorization."""
    if any(name in request.headers for name in ('X-Telegram-Init-Data', 'X-Session-Token', 'Authorization')):
        raise PermissionDenied('Company browser authentication is required.')
    context, row = _channel(request)
    if context is None:
        raise PermissionDenied('Company browser authentication is required.')
    user = require_browser_user(request)
    try:
        audit_id = uuid.UUID(context.get('audit_event_id', ''))
    except (ValueError, TypeError, AttributeError):
        raise PermissionDenied('Company browser authentication is required.') from None
    if not ComplianceAuditEvent.objects.filter(
        pk=audit_id, actor_id=user.pk, action='staff_browser.login_completed',
        subject_id=str(row.pk), deduplication_key=f"staff-browser-login:{context.get('attempt_id', '')}",
    ).exists():
        raise PermissionDenied('Company browser authentication is required.')
    from core.services.channel_context import bind_verified_channel
    bind_verified_channel('browser', 'company_mfa_session')
    return user


def _state(request):
    context, row = _channel(request)
    if context is None:
        return 'signed_out'
    if request.user.is_authenticated:
        if request.user.pk != row.user_id:
            return 'signed_out'
        try:
            require_company_browser_user(request)
            return 'authenticated'
        except PermissionDenied:
            pass
        progress = enrollment_progress(request, context, row)
        if progress is not None:
            return progress
        records = get_authentication_records(request)
        password = next((entry for entry in reversed(records) if isinstance(entry, dict) and entry.get('method') == 'password'), None) if isinstance(records, list) else None
        if (
            not context.get('audit_event_id')
            and password and type(password.get('at')) in (int, float)
            and context['started_at'] <= password['at'] <= time.time()
            and 0 <= time.time() - password['at'] <= MAX_LOGIN_SECONDS
            and constant_time_compare(request.session.get(HASH_SESSION_KEY, ''), row.user.get_session_auth_hash())
            and not Authenticator.objects.filter(user_id=row.user_id, type='totp').exists()
        ):
            return 'enrollment_required'
        return 'signed_out'
    stage = get_pending_stage(request)
    if stage and stage.key == AuthenticateStage.key and stage.login.user.pk == row.user_id:
        return 'mfa_required'
    return 'signed_out'


def _body(request, fields):
    if request.content_type != 'application/json' or len(request.body) > 8192:
        return None
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeError):
        return None
    if not isinstance(data, dict) or set(data) != set(fields):
        return None
    if any(not isinstance(data[key], str) or not 1 <= len(data[key]) <= limit for key, limit in fields.items()):
        return None
    return data


def _throttle(request, scope, identity):
    # These are initial abuse-control limits, not measured service objectives.
    try:
        network = consume_network(request, scope=f'staff-browser-{scope}')
        actor = consume_identity(scope=f'staff-browser-{scope}', kind='staff-auth', value=identity, limit=10, window_seconds=600)
    except (DatabaseError, ImproperlyConfigured):
        raise AbuseControlUnavailable from None
    if not network.allowed or not actor.allowed:
        return _rate_limited(max(network.retry_after, actor.retry_after))
    return None


def _rate_limited(retry_after=60):
    response = _response('rate_limited', 429)
    # Native allauth supplies no reset time; 60 seconds is a retry hint, not
    # a promise that its independent sliding window has already reopened.
    response['Retry-After'] = str(retry_after)
    return response


def _native_rate_limited(response):
    if response.status_code == 429:
        return True
    if response.status_code != 400:
        return False
    # Pinned headless forms also return throttle errors as HTTP 400. Inspect
    # only stable error codes; never return/log native messages or user data.
    try:
        data = json.loads(response.content)
        return any(error.get('code') in ('rate_limited', 'too_many_login_attempts') for error in data.get('errors', []))
    except (ValueError, TypeError, AttributeError):
        return False


def _authentication_unavailable(request):
    owned = _owns_browser_session(request)
    if owned:
        try:
            with protected_browser_session(request):
                get_adapter(request).logout(request)
        except (DatabaseError, UpdateError):
            pass  # Persisted cleanup cannot be promised with a failed store.
    _discard(request)
    # SessionMiddleware skips 5xx saves. Persist cleanup if its store is
    # healthy; failure never produces assurance or a successful response.
    try:
        request.session.save()
    except (DatabaseError, UpdateError):
        pass
    return _response('authentication_unavailable', 503)


def _discard(request):
    clear_assurance(request)
    clear_browser_context(request)
    clear_login(request)


def _owns_browser_session(request):
    context = request.session.get(CHANNEL_KEY)
    return (
        isinstance(context, dict) and request.user.is_authenticated
        and type(context.get('user_id')) is int and context['user_id'] == request.user.pk
    )


def _complete(request):
    """Do not report authenticated success without a durable login audit."""
    context, row = _channel(request)
    if context is None:
        _discard(request)
        return _response('signed_out', 401)
    try:
        user = require_browser_user(request)
    except PermissionDenied:
        state = _state(request)
        return _response(state, 202 if state == 'enrollment_required' else 401)
    try:
        event, _created = record_event(
            workflow='access_control', action='staff_browser.login_completed', category='identity',
            subject_type='staff_browser_admission', subject_id=str(row.pk), actor=user,
            request_id=context['attempt_id'], deduplication_key=f"staff-browser-login:{context['attempt_id']}",
            metadata={'channel': 'browser', 'admission_revision': row.revision}, sensitive=True,
        )
    except Exception:
        # No credential/session values are logged here. A failed audit cannot
        # leave a usable company-browser session or claim login success.
        _discard(request)
        get_adapter(request).logout(request)
        return _response('audit_unavailable', 503)
    request.session[CHANNEL_KEY] = {**context, 'audit_event_id': str(event.pk)}
    return _response('authenticated', user={'id': user.pk})


@browser_endpoint(('GET',))
def session_state(request):
    return _response(_state(request), csrf_token=get_token(request))


@browser_endpoint(('POST',))
@sensitive_variables('data')
def password_login(request):
    data = _body(request, {'username': 150, 'password': 1024})
    if data is None:
        return _response('invalid_request', 400)
    limited = _throttle(request, 'login', data['username'])
    if limited is not None:
        return limited
    if request.user.is_authenticated:
        state = _state(request)
        if state != 'signed_out' or not _owns_browser_session(request):
            return _response(state, 409)
        # An expired/revoked browser cookie must not trap a fresh sign-in.
        # Only its exact owned session is cleared; Admin/other-channel cookies
        # remain intact and cannot be converted by this password endpoint.
        with protected_browser_session(request):
            get_adapter(request).logout(request)
    _discard(request)
    user = get_user_model().objects.filter(username=data['username'], is_active=True).first()
    row = _admission(user.pk) if user else None
    if row is None or not _verified(user.pk):
        # Reduce the obvious fast-failure distinction for unknown/unadmitted
        # identities. This does not claim a constant-time end-to-end login.
        make_password(data['password'])
        return _response('invalid_credentials', 400)
    request.session[CHANNEL_KEY] = {
        'user_id': user.pk, 'admission_id': str(row.pk), 'revision': row.revision,
        'started_at': time.time(), 'attempt_id': str(uuid.uuid4()),
    }
    request.session.pop(AUTHENTICATION_METHODS_SESSION_KEY, None)
    with native_authentication(), protected_browser_session(request):
        response = _login(request)
    if _native_rate_limited(response):
        _discard(request)
        return _rate_limited()
    if response.status_code >= 500:
        raise AuthenticationUnavailable
    if response.status_code >= 400 and _state(request) != 'mfa_required':
        _discard(request)
        return _response('invalid_credentials', 400)
    if _state(request) == 'mfa_required':
        return _response('mfa_required', 401)
    return _complete(request)


@browser_endpoint(('POST',))
@sensitive_variables('data')
def authenticate_mfa(request):
    data = _body(request, {'code': 32})
    if data is None:
        return _response('invalid_request', 400)
    if _state(request) == 'authenticated':
        return _response('authenticated')  # Lost-response retry, not fresh MFA.
    context, row = _channel(request)
    if context is None or _state(request) != 'mfa_required':
        _discard(request)
        return _response('signed_out', 401)
    limited = _throttle(request, 'mfa', row.user_id)
    if limited is not None:
        return limited
    with native_authentication(), protected_browser_session(request):
        response = _mfa(request)
    if _native_rate_limited(response):
        return _rate_limited()
    if response.status_code >= 500:
        raise AuthenticationUnavailable
    if response.status_code >= 400:
        return _response('mfa_required', 400)
    return _complete(request)


@browser_endpoint(('POST',))
def browser_logout(request):
    context, _row = _channel(request)
    if context is not None or _owns_browser_session(request):
        # Only this client-owned session, never every session for the employee.
        with protected_browser_session(request):
            get_adapter(request).logout(request)
    _discard(request)
    return _response('signed_out')
