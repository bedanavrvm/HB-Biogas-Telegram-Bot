"""Advisory IT-only phone/ID evidence. No application or signing state writes."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from core.models import IntegrationOperation
from core.services.external_resilience import (
    ExternalCircuitOpen, execute_operation, external_call_budget, reserve_operation,
)
from core.services.identifiers import normalize_kenyan_phone, validate_kenyan_national_id
from origination.models import (
    LoanOriginationApplication, OriginationPhoneIdentityCheck as Check,
    OriginationPhoneIdentityDailyUsage as Usage, OriginationPhoneIdentitySubject as Subject,
)
from . import daraja_phone_identity as provider

CAPABILITY = 'origination.identity.phone.verify'
EVENT_PREFIX = 'phone_id_check_'
LEASE_SECONDS = 120
NAIROBI = ZoneInfo('Africa/Nairobi')
MESSAGES = {
    'disabled': 'Phone checks are currently disabled.',
    'configuration_required': 'Phone checks need administrator configuration.',
    'daily_limit': 'The daily phone-check allowance has been reached. Try after the Nairobi reset.',
    'operator_rate_limited': 'Too many check requests. Please wait before trying again.',
    'circuit_open': 'Safaricom verification is temporarily unavailable.',
    'unknown': 'The result is uncertain. No automatic retry was made.',
    'provider_unavailable': 'Safaricom could not verify these details. This is not a mismatch.',
}


class PhoneIdentityError(Exception):
    def __init__(self, code, message=None, status=400, retry_after=0):
        self.code, self.status, self.retry_after = code, status, retry_after
        super().__init__(message or MESSAGES.get(code, 'This phone check could not complete.'))


def allowed(application, actor, access=None) -> bool:
    from core.services.telegram_identity import user_access
    from core.services.workflow_access import workflow_access_decision
    from .origination_access import FULL, application_presentation_mode
    if not actor or not actor.is_active:
        return False
    access = access if access is not None else user_access(actor, 'loan_origination')
    if actor.is_superuser:
        return application_presentation_mode(application, user=actor, access=access) == FULL
    # Do not flatten roles/scopes: one IT grant must encompass the resource.
    grants = [grant for grant in (access or {}).get('grants', []) if grant.role == 'IT']
    if not grants:
        return False
    pilot_access = {**(access or {}), 'grants': grants}
    return (workflow_access_decision(actor, 'loan_origination', CAPABILITY,
                                    access=pilot_access, resource=application).allowed
            and application_presentation_mode(application, user=actor, access=pilot_access) == FULL)


def require_access(application, actor, access=None):
    if not allowed(application, actor, access):
        raise PhoneIdentityError('forbidden', 'This action is outside your authorized Origination IT scope.', 403)


def targets(application) -> dict:
    from .loan_origination import _applicant_identity_field_keys
    from .origination_value_contracts import application_input_schema, form_projection_enabled
    schema = application_input_schema(application) if form_projection_enabled(application) else application.schema_snapshot
    fields = {item.get('key'): item for item in (schema or {}).get('fields', [])}
    resolved = _applicant_identity_field_keys(schema or {}, application.signer_rules_snapshot)
    id_key = next(iter(resolved['national_id']), '')
    primary = next(iter(resolved['phone']), '')
    if not id_key:
        return {}
    result = {}
    if primary:
        result['primary'] = {'field_key': primary, 'id_field_key': id_key}
    alternate = fields.get('applicant_other_phone', {})
    meaning = alternate.get('value_contract') or {}
    if (alternate.get('type') == 'phone' and primary != 'applicant_other_phone'
            and meaning.get('subject', 'applicant') == 'applicant'):
        result['alternate'] = {'field_key': 'applicant_other_phone', 'id_field_key': id_key}
    return result


def pair(application, target):
    mapping = targets(application).get(target)
    if not mapping:
        raise PhoneIdentityError('invalid_target', 'This Applicant phone field is not available.')
    payload = application.form_payload or {}
    phone = normalize_kenyan_phone(payload.get(mapping['field_key']))
    national_id = str(payload.get(mapping['id_field_key']) or '').strip()
    if not phone or not national_id.isascii() or not validate_kenyan_national_id(national_id):
        raise PhoneIdentityError('invalid_identity', 'Save a valid Applicant phone and National ID before checking.')
    return phone, national_id


def binding(application, target, phone, national_id):
    message = [str(application.pk), application.revision, target, provider.provider_context(), phone, national_id]
    return hmac.new(str(settings.DARAJA_PHONE_ID_HMAC_KEY).encode(),
                    json.dumps(message, separators=(',', ':')).encode(), hashlib.sha256).hexdigest()


def _reset_at(when):
    local = when.astimezone(NAIROBI)
    return datetime.combine(local.date() + timedelta(days=1), time.min, tzinfo=NAIROBI)


def _receipt(event, application, current_pair=None):
    check = Check.objects.select_related('subject').get(pk=event.metadata['check_id'])
    now = timezone.now()
    state = 'unavailable' if check.state == 'failed' else check.state
    if state in {'pending', 'running'}:
        state = 'unknown' if check.created_at + timedelta(seconds=LEASE_SECONDS) <= now else 'checking'
    applies = bool(current_pair and check.subject.provider_context == provider.provider_context()
                   and constant_time_compare(check.subject.subject_hmac, provider.subject_digest(*current_pair)))
    freshness = 'changed' if not applies else (
        'expired' if check.reusable_until and check.reusable_until <= now else 'current'
    )
    code = check.error_code or ('unknown' if state == 'unknown' else '')
    message = MESSAGES.get(code, MESSAGES['provider_unavailable']) if state in {'unknown', 'unavailable'} else ''
    retry = max(0, int((_reset_at(check.completed_at or now) - now).total_seconds())) if code == 'daily_limit' else 0
    return {
        'receipt_id': str(event.pk), 'target': event.metadata['target'], 'status': state,
        'freshness': freshness, 'applies_to_current_values': applies,
        'reused': bool(event.metadata.get('reused')),
        'checked_at': check.completed_at.isoformat() if check.completed_at else None,
        'reusable_until': check.reusable_until.isoformat() if check.reusable_until else None,
        'code': code, 'message': message, 'retry_after': retry,
    }


def projection(application, actor, access=None):
    """Current application's receipts only; no external calls or state repair."""
    if not allowed(application, actor, access):
        return None
    error = provider.configuration_error()
    result = {'allowed': True, 'enabled': not error, 'reason': error, 'revision': application.revision, 'targets': []}
    for target, mapping in targets(application).items():
        item = {**mapping, 'target': target, 'can_check': False, 'subject_token': '',
                'status': 'not_checked', 'freshness': 'none'}
        try:
            values = pair(application, target)
        except PhoneIdentityError:
            values = None
        if values and len(str(settings.DARAJA_PHONE_ID_HMAC_KEY)) >= 32:
            item.update(can_check=not error, subject_token=binding(application, target, *values),
                        phone_suffix=values[0][-4:], id_suffix=values[1][-4:])
        event = application.events.filter(action__startswith=EVENT_PREFIX, metadata__target=target).order_by('-occurred_at').first()
        if event:
            item.update(_receipt(event, application, values))
        result['targets'].append(item)
    return result


def _fingerprint(body, actor):
    value = [str(actor.pk), *[body.get(key) for key in (
        'target', 'revision', 'subject_token', 'confirmed', 'confirmation_version',
    )]]
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _event(application, actor, request_id, body, check, action, reused):
    from .loan_origination import _record_event
    _record_event(application, EVENT_PREFIX + action, actor=actor, request_id=request_id,
                  adopt_form_projection=False, metadata={
                      'check_id': str(check.pk), 'target': body['target'], 'reused': reused,
                      'confirmation_version': 1, 'confirmed_at': timezone.now().isoformat(),
                      'request_fingerprint': _fingerprint(body, actor),
                  })
    return application.events.get(request_id=request_id)


@transaction.atomic
def _admit(application_id, actor, request_id, body):
    from core.services.request_throttling import consume_identity
    application = LoanOriginationApplication.objects.select_for_update().get(pk=application_id)
    require_access(application, actor)
    existing = application.events.filter(request_id=request_id).first()
    if existing:
        if (not existing.action.startswith(EVENT_PREFIX)
                or existing.metadata.get('request_fingerprint') != _fingerprint(body, actor)):
            raise PhoneIdentityError('request_conflict', 'This request key was used for a different action.', 409)
        return application, existing, None
    error = provider.configuration_error()
    if error:
        raise PhoneIdentityError(error, status=503)
    if (type(body.get('revision')) is not int or body['revision'] != application.revision):
        raise PhoneIdentityError('revision_conflict', 'Refresh this application before checking.', 409)
    if body.get('confirmed') is not True or type(body.get('confirmation_version')) is not int or body['confirmation_version'] != 1:
        raise PhoneIdentityError('confirmation_required', 'Confirm the phone check before continuing.')
    values = pair(application, body.get('target'))
    if not constant_time_compare(str(body.get('subject_token') or ''), binding(application, body['target'], *values)):
        raise PhoneIdentityError('identity_changed', 'The saved Applicant details changed. Refresh before checking.', 409)
    throttle = consume_identity(scope='origination.phone_id', kind='user', value=actor.pk, limit=10, window_seconds=60)
    if not throttle.allowed:
        raise PhoneIdentityError('operator_rate_limited', status=429, retry_after=throttle.retry_after)
    subject, _ = Subject.objects.get_or_create(provider_context=provider.provider_context(), subject_hmac=provider.subject_digest(*values))
    subject = Subject.objects.select_for_update().get(pk=subject.pk)
    now = timezone.now()
    conclusive = subject.checks.filter(state__in=['matched', 'not_matched'], reusable_until__gt=now).order_by('-completed_at').first()
    if conclusive:
        return application, _event(application, actor, request_id, body, conclusive, 'reused', True), None
    active = subject.checks.filter(state__in=['pending', 'running']).first()
    if active and active.created_at + timedelta(seconds=LEASE_SECONDS) > now:
        return application, _event(application, actor, request_id, body, active, 'joined', True), None
    if active:
        active.state, active.error_code, active.completed_at = 'unknown', 'unknown', now
        active.save(update_fields=['state', 'error_code', 'completed_at'])
    check_id = uuid.uuid4()
    operation, _ = reserve_operation(
        integration=IntegrationOperation.INTEGRATION_DARAJA, operation_type='origination_phone_identity',
        deduplication_key=f'origination.phone-id:{check_id}', source_model=Check._meta.label,
        source_id=str(check_id), request_id=request_id, requested_by=actor, max_attempts=1,
    )
    check = Check.objects.create(id=check_id, subject=subject, operation=operation)
    return application, _event(application, actor, request_id, body, check, 'requested', False), check


@transaction.atomic
def _before_dispatch(check, actor, application_id, target, values, operation):
    application = LoanOriginationApplication.objects.select_for_update().get(pk=application_id)
    # A user may be offboarded while OAuth is in flight. Do not trust its old object.
    actor.refresh_from_db()
    require_access(application, actor)
    if provider.configuration_error() or pair(application, target) != values:
        raise PhoneIdentityError('identity_changed', 'Saved details or provider configuration changed.', 409)
    Subject.objects.select_for_update().get(pk=check.subject_id)
    saved = Check.objects.select_for_update().get(pk=check.pk)
    current_op = IntegrationOperation.objects.select_for_update().get(pk=operation.pk)
    if (saved.state != 'pending' or saved.dispatched_at is not None
            or saved.created_at + timedelta(seconds=LEASE_SECONDS) <= timezone.now()
            or saved.subject.provider_context != provider.provider_context()
            or current_op.status != 'running'
            or current_op.metadata.get('attempt_token') != operation.metadata.get('attempt_token')):
        raise PhoneIdentityError('unknown', status=503)
    now = timezone.now()
    usage, _ = Usage.objects.get_or_create(environment=settings.DARAJA_ENVIRONMENT, business_date=now.astimezone(NAIROBI).date())
    usage = Usage.objects.select_for_update().get(pk=usage.pk)
    if usage.dispatch_count >= settings.ORIGINATION_PHONE_ID_CHECK_DAILY_LIMIT:
        raise PhoneIdentityError('daily_limit', status=429, retry_after=max(1, int((_reset_at(now) - now).total_seconds())))
    usage.dispatch_count += 1
    usage.save(update_fields=['dispatch_count'])
    saved.state, saved.dispatched_at = 'running', now
    saved.save(update_fields=['state', 'dispatched_at'])


@transaction.atomic
def _finish(check, operation, *, outcome=None, code='', uncertain=False, provider_code=''):
    Subject.objects.select_for_update().get(pk=check.subject_id)
    saved = Check.objects.select_for_update().get(pk=check.pk)
    current_op = IntegrationOperation.objects.select_for_update().get(pk=operation.pk)
    if (saved.state in Check.TERMINAL or current_op.status != 'running'
            or current_op.metadata.get('attempt_token') != operation.metadata.get('attempt_token')):
        return
    saved.completed_at = timezone.now()
    if saved.created_at + timedelta(seconds=LEASE_SECONDS) <= saved.completed_at:
        outcome, code, uncertain = None, 'unknown', True
    if outcome:
        saved.state, saved.provider_code, saved.provider_response_ref = outcome.state, outcome.provider_code, outcome.response_ref
        saved.reusable_until = saved.completed_at + timedelta(days=30)
    else:
        saved.state = 'unknown' if uncertain else 'failed'
        saved.error_code, saved.provider_code = code, provider_code
    saved.save(update_fields=['state', 'provider_code', 'provider_response_ref', 'error_code', 'completed_at', 'reusable_until'])


def _execute(check, application, actor, target):
    operation = check.operation
    values = pair(application, target)

    def action():
        try:
            with external_call_budget(20):
                outcome = provider.validate(phone=values[0], national_id=values[1], request_ref=str(check.pk),
                    before_dispatch=lambda: _before_dispatch(check, actor, application.pk, target, values, operation))
            _finish(check, operation, outcome=outcome)
            return {'id': str(check.pk)}
        except provider.ProviderFailure as exc:
            _finish(check, operation, code=exc.code, uncertain=exc.uncertain, provider_code=exc.provider_code)
            raise
        except PhoneIdentityError as exc:
            _finish(check, operation, code=exc.code, uncertain=exc.code == 'unknown')
            raise
        except Exception:
            dispatched = Check.objects.filter(pk=check.pk, dispatched_at__isnull=False).exists()
            _finish(check, operation, code='unknown' if dispatched else 'provider_unavailable', uncertain=dispatched)
            raise PhoneIdentityError('provider_unavailable', status=503) from None

    try:
        execute_operation(operation, action, attempt_budget=1, claim_guard=lambda op: Check.objects.filter(
            pk=check.pk, state='pending', dispatched_at__isnull=True).exists())
    except Exception as exc:
        # A circuit-open claim never entered action. Close only an undispatched
        # reservation; never turn a dispatched/later attempt into a fresh call.
        with transaction.atomic():
            Subject.objects.select_for_update().get(pk=check.subject_id)
            saved = Check.objects.select_for_update().get(pk=check.pk)
            if saved.state == 'pending' and saved.dispatched_at is None:
                saved.state, saved.completed_at = 'failed', timezone.now()
                saved.error_code = 'circuit_open' if isinstance(exc, ExternalCircuitOpen) else 'provider_unavailable'
                saved.save(update_fields=['state', 'completed_at', 'error_code'])


def request_check(*, application_id, actor, request_id: str, body: dict):
    accepted = {'target', 'revision', 'subject_token', 'confirmed', 'confirmation_version', 'client_request_id', 'request_id'}
    if not isinstance(body, dict) or set(body) - accepted:
        raise PhoneIdentityError('invalid_request', 'Supply only the saved target, revision, confirmation and request identity.')
    if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128:
        raise PhoneIdentityError('request_id_required', 'A valid request key is required.')
    if not isinstance(body.get('target'), str) or body['target'] not in {'primary', 'alternate'}:
        raise PhoneIdentityError('invalid_target', 'Choose an Applicant phone target.')
    application, event, check = _admit(application_id, actor, request_id, body)
    if check:
        _execute(check, application, actor, body['target'])
    application.refresh_from_db()
    require_access(application, actor)
    try:
        values = pair(application, body['target'])
    except PhoneIdentityError:
        values = None
    result = _receipt(event, application, values)
    code = result['code']
    status = 202 if result['status'] == 'checking' else (
        429 if code == 'daily_limit' else 409 if code == 'identity_changed'
        else 503 if result['status'] in {'unknown', 'unavailable'} else 200
    )
    return result, status
