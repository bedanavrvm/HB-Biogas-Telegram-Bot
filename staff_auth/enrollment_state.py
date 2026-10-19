"""Read-only, nonprivileged enrollment progress. Never issues MFA assurance."""
import math
import time
import uuid

from allauth.account import app_settings as account_settings
from allauth.account.authentication import get_authentication_records
from allauth.mfa.models import Authenticator
from django.contrib.auth import HASH_SESSION_KEY
from django.utils.crypto import constant_time_compare

from core.models import ComplianceAuditEvent

from .session_protection import ENROLLMENT_CONTEXT_KEY, ENROLLMENT_SECONDS


def request_uuid(value):
    try:
        return str(uuid.UUID(value)) if isinstance(value, str) else None
    except (ValueError, AttributeError):
        return None


def receipt(user, row, action, key, event_id=None, *, current_revision=True):
    events = ComplianceAuditEvent.objects.filter(
        actor_id=user.pk, action=f'staff_browser.enrollment_{action}',
        subject_type='staff_browser_admission', subject_id=str(row.pk),
        deduplication_key=f'staff-browser-enrollment-{action}:{user.pk}:{key}',
    )
    if event_id is not None:
        if request_uuid(event_id) is None:
            return None
        events = events.filter(pk=event_id)
    event = events.first()
    return event if event and (not current_revision or event.metadata.get('admission_revision') == row.revision) else None


def enrollment_context(request, channel, row):
    """Require the same password session and a still-fresh native recheck."""
    saved = request.session.get(ENROLLMENT_CONTEXT_KEY)
    if (
        not isinstance(saved, dict) or not request.user.is_authenticated
        or request.user.pk != row.user_id or not row.user.is_active or not row.enabled
        or channel.get('audit_event_id')
        or saved.get('admission_id') != str(row.pk) or saved.get('revision') != row.revision
        or saved.get('attempt_id') != channel.get('attempt_id')
        or not request.session.session_key or saved.get('session_key') != request.session.session_key
        or request_uuid(saved.get('begin_key')) is None
        or request_uuid(saved.get('start_event_id')) is None
        or not constant_time_compare(request.session.get(HASH_SESSION_KEY, ''), row.user.get_session_auth_hash())
    ):
        return None
    now, stamp = time.time(), saved.get('started_at')
    if type(stamp) not in (int, float) or not math.isfinite(stamp) or not 0 <= now - stamp < ENROLLMENT_SECONDS:
        return None
    records = get_authentication_records(request)
    if not isinstance(records, list):
        return None
    passwords = [item for item in records if isinstance(item, dict) and item.get('method') == 'password' and item.get('reauthenticated') is True]
    last = passwords[-1].get('at') if passwords else None
    if (
        type(last) not in (int, float) or not math.isfinite(last)
        or last < max(stamp, channel['started_at'], row.updated_at.timestamp())
        or not 0 <= now - last < account_settings.REAUTHENTICATION_TIMEOUT
    ):
        return None
    if receipt(row.user, row, 'started', saved['begin_key'], saved.get('start_event_id')) is None:
        return None
    return saved


def activation_receipt(request, row, saved):
    key = saved.get('confirm_key')
    if request_uuid(key) is None or request_uuid(saved.get('activation_event_id')) is None:
        return None
    event = receipt(row.user, row, 'activated', key, saved.get('activation_event_id'))
    if event is None or event.metadata.get('begin_key') != saved['begin_key']:
        return None
    ids = event.metadata.get('authenticator_ids')
    if not isinstance(ids, dict) or set(ids) != {'totp', 'recovery_codes'} or any(type(value) is not int for value in ids.values()):
        return None
    factors = list(Authenticator.objects.filter(user_id=row.user_id, pk__in=ids.values()))
    if {factor.type: factor.pk for factor in factors} != ids:
        return None
    return event


def enrollment_progress(request, channel, row):
    saved = enrollment_context(request, channel, row)
    if saved is None:
        return None
    event = activation_receipt(request, row, saved)
    if event is None:
        return None
    recovery = Authenticator.objects.filter(pk=event.metadata['authenticator_ids']['recovery_codes']).first()
    if recovery is None:
        return None
    return 'reauthentication_required' if recovery.data.get('viewed_at') else 'recovery_codes_required'
