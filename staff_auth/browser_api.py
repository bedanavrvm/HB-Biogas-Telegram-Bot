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
from allauth.headless.mfa.views import AuthenticateView
from allauth.mfa.models import Authenticator
from allauth.mfa.stages import AuthenticateStage
from django.conf import settings
from django.contrib.auth import HASH_SESSION_KEY, get_user_model
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.utils.crypto import constant_time_compare

from core.services.compliance_audit import record_event
from core.services.request_throttling import consume_identity, consume_ip

from .assurance import MAX_LOGIN_SECONDS, clear_assurance, require_browser_user
from .models import StaffBrowserAdmission
from .session_protection import CHANNEL_KEY, clear_browser_context, protected_browser_session


_login = LoginView.as_api_view(client=Client.BROWSER)
_mfa = AuthenticateView.as_api_view(client=Client.BROWSER)


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
                response = protected(request, *args, **kwargs)
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
    if not isinstance(context, dict) or type(context.get('user_id')) is not int:
        return None, None
    stamp = context.get('started_at')
    if type(stamp) not in (int, float) or not math.isfinite(stamp) or not 0 <= time.time() - stamp <= MAX_LOGIN_SECONDS:
        return None, None
    row = _admission(context['user_id'])
    if (
        row is None or str(row.pk) != context.get('admission_id')
        or type(context.get('revision')) is not int or row.revision != context['revision']
        or stamp < row.updated_at.timestamp() or not _verified(row.user_id)
    ):
        return None, None
    return context, row


def _state(request):
    context, row = _channel(request)
    if context is None:
        return 'signed_out'
    if request.user.is_authenticated:
        if request.user.pk != row.user_id:
            return 'signed_out'
        try:
            require_browser_user(request)
            if context.get('audit_event_id'):
                return 'authenticated'
        except PermissionDenied:
            pass
        records = get_authentication_records(request)
        password = next((entry for entry in reversed(records) if isinstance(entry, dict) and entry.get('method') == 'password'), None) if isinstance(records, list) else None
        if (
            password and type(password.get('at')) in (int, float)
            and context['started_at'] <= password['at'] <= time.time()
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
    network = consume_ip(request, scope=f'staff-browser-{scope}', limit=30, window_seconds=600)
    actor = consume_identity(scope=f'staff-browser-{scope}', kind='staff-auth', value=identity, limit=10, window_seconds=600)
    if not network.allowed or not actor.allowed:
        response = _response('rate_limited', 429)
        response['Retry-After'] = str(max(network.retry_after, actor.retry_after))
        return response
    return None


def _discard(request):
    clear_assurance(request)
    clear_browser_context(request)
    clear_login(request)


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
        return _response(_state(request), 409)
    _discard(request)
    user = get_user_model().objects.filter(username=data['username'], is_active=True).first()
    row = _admission(user.pk) if user else None
    if row is None or not _verified(user.pk):
        return _response('invalid_credentials', 400)
    request.session[CHANNEL_KEY] = {
        'user_id': user.pk, 'admission_id': str(row.pk), 'revision': row.revision,
        'started_at': time.time(), 'attempt_id': str(uuid.uuid4()),
    }
    request.session.pop(AUTHENTICATION_METHODS_SESSION_KEY, None)
    with protected_browser_session(request):
        response = _login(request)
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
    with protected_browser_session(request):
        response = _mfa(request)
    if response.status_code >= 400:
        return _response('mfa_required', 400)
    return _complete(request)


@browser_endpoint(('POST',))
def browser_logout(request):
    context, _row = _channel(request)
    if context is not None:
        # Only this client-owned session, never every session for the employee.
        with protected_browser_session(request):
            get_adapter(request).logout(request)
    _discard(request)
    return _response('signed_out')
