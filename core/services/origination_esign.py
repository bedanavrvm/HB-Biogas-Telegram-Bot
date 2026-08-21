"""Verified Origination signing sessions and Africa's Talking OTP delivery."""

from __future__ import annotations

from datetime import timedelta
import hashlib
import hmac
import json
import logging
import secrets
from typing import Any
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models, transaction
from django.utils import timezone

from core.models import (
    IntegrationOperation,
    LoanOriginationApplication,
    OriginationOtpChallenge,
    OriginationSignerSession,
    OriginationSigningAction,
    OriginationSigningPackage,
    OriginationSigningRequestEvent,
    OriginationStampAsset,
)
from core.services.identifiers import normalize_kenyan_phone
from core.services.loan_origination import OriginationConflict, OriginationError, _record_event, _require_request_id
from core.services.origination_signing import _slot_catalog, _validated_signature_capture, render_verified_package


logger = logging.getLogger(__name__)
CONSENT_VERSION = 'origination_packet_v1'
OTP_TTL = timedelta(minutes=10)
LOCKOUT_WINDOW = timedelta(minutes=30)
SESSION_TTL_DEFAULT_HOURS = 48
STAFF_SIGNER_ROLES = {'bro_1', 'bro_2', 'loan_officer', 'officer', 'branch_manager'}


class OriginationSigningRateLimited(OriginationError):
    def __init__(self, message: str, *, retry_after: int):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))


def esign_enabled() -> bool:
    if not bool(getattr(settings, 'ORIGINATION_ESIGN_ENABLED', False)):
        return False
    provider_environment = str(getattr(settings, 'AFRICASTALKING_SMS_ENVIRONMENT', '') or '').strip().casefold()
    application_environment = str(getattr(settings, 'SENTRY_ENVIRONMENT', '') or '').strip().casefold()
    username = str(getattr(settings, 'AFRICASTALKING_USERNAME', '') or '').strip()
    api_key = str(getattr(settings, 'AFRICASTALKING_API_KEY', '') or '')
    if not api_key or provider_environment not in {'sandbox', 'production'}:
        return False
    if provider_environment == 'sandbox':
        return username == 'sandbox' and application_environment in {'development', 'dev', 'local', 'test', 'testing', 'staging'}
    return bool(username and username != 'sandbox' and application_environment == 'production')


def _digest(value: str) -> str:
    return hmac.new(
        str(settings.SECRET_KEY).encode(), str(value).encode(), hashlib.sha256,
    ).hexdigest()


def _session_token(package_id, signer_role: str, request_id: str) -> str:
    material = f'origination-signing:{package_id}:{signer_role}:{request_id}'
    return hmac.new(str(settings.SECRET_KEY).encode(), material.encode(), hashlib.sha256).hexdigest()


def _masked_phone(phone: str) -> str:
    return f'+254•••••{phone[-4:]}' if len(phone) >= 4 else '••••'


def _client_ip_hash(request) -> str:
    forwarded = str(request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    address = forwarded or str(request.META.get('REMOTE_ADDR') or '').strip()
    return _digest(f'ip:{address}') if address else ''


def _binding(session: OriginationSignerSession) -> str:
    return hashlib.sha256(json.dumps({
        'package_id': str(session.package_id),
        'unsigned_document_hash': session.package.unsigned_document_hash,
        'signer_role': session.signer_role,
        'identity': session.identity_snapshot,
        'consent_version': session.consent_version,
        'signature_capture_sha256': session.signature_capture_sha256,
    }, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _participant(package: OriginationSigningPackage, signer_role: str) -> dict[str, Any]:
    participant = next((
        dict(item) for item in package.participants_snapshot or []
        if isinstance(item, dict) and str(item.get('role') or '') == signer_role
    ), None)
    if not participant:
        raise OriginationError('Choose a configured signer from this package.')
    signature_slots = [
        item for item in _slot_catalog(package)
        if item['role'] == signer_role and item['type'] == OriginationSigningAction.TYPE_SIGNATURE
    ]
    if not signature_slots:
        raise OriginationError('This signer has no configured signature slots.')
    participant['signature_slots'] = signature_slots
    return participant


def _resolved_identity(
    package: OriginationSigningPackage, participant: dict[str, Any],
) -> dict[str, Any]:
    identity = dict(participant.get('identity') or {})
    role = str(participant.get('role') or '').strip()
    application_rule = next((
        item for item in (package.application.signer_rules_snapshot or [])
        if isinstance(item, dict) and str(item.get('role') or '').strip() == role
    ), {})
    bindings = {
        **(
            application_rule.get('identity_fields')
            if isinstance(application_rule.get('identity_fields'), dict) else {}
        ),
        **(
            participant.get('identity_fields')
            if isinstance(participant.get('identity_fields'), dict) else {}
        ),
    }
    context = package.context_snapshot if isinstance(package.context_snapshot, dict) else {}
    for identity_kind, field_key in bindings.items():
        field_key = str(field_key or '').strip()
        if identity_kind in {'name', 'phone', 'national_id'} and field_key and not identity.get(identity_kind):
            value = context.get(field_key)
            if value not in (None, ''):
                identity[identity_kind] = str(value).strip()
    return identity


def _identity_for(
    package: OriginationSigningPackage, participant: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    identity = _resolved_identity(package, participant)
    role = str(participant.get('role') or '').strip()
    phone = normalize_kenyan_phone(identity.get('phone'))
    if not phone:
        label = role.replace('_', ' ').title() or 'This signer'
        raise OriginationError(
            f'{label} requires a mapped Kenyan mobile phone before dispatch. '
            'Check the signer OTP phone mapping and its saved application value.'
        )
    identity['phone'] = phone
    return identity, phone


def _duplicate_external_phones(package: OriginationSigningPackage) -> dict[str, list[str]]:
    roles_by_phone: dict[str, list[str]] = {}
    for participant in package.participants_snapshot or []:
        if not isinstance(participant, dict):
            continue
        role = str(participant.get('role') or '')
        if role in STAFF_SIGNER_ROLES:
            continue
        phone = normalize_kenyan_phone(_resolved_identity(package, participant).get('phone'))
        if phone:
            roles_by_phone.setdefault(phone, []).append(role)
    return {phone: roles for phone, roles in roles_by_phone.items() if len(set(roles)) > 1}


@transaction.atomic
def create_signer_session(
    *, package_id, signer_role: str, actor, request_id: str,
    access_mode: str = OriginationSignerSession.MODE_SELF_SERVICE,
    shared_phone_override_reason: str = '',
    approved_shared_phone_by=None,
) -> tuple[OriginationSignerSession, str, bool]:
    request_id = _require_request_id(request_id)
    if not esign_enabled():
        raise OriginationError('Verified Origination e-signing is not configured for this environment.')
    package = OriginationSigningPackage.objects.select_for_update().select_related('application').get(pk=package_id)
    replay = package.signer_sessions.filter(request_id=request_id).first()
    if replay:
        return replay, _session_token(package.pk, replay.signer_role, request_id), True
    if package.test_mode:
        raise OriginationError('Create a verified package; test packages cannot dispatch signing sessions.')
    if package.status not in {package.STATUS_PENDING, package.STATUS_IN_PROGRESS}:
        raise OriginationError('This signing package no longer accepts signer sessions.')
    if signer_role in STAFF_SIGNER_ROLES:
        raise OriginationError('Staff signer roles use authenticated staff signing, not an OTP session.')
    participant = _participant(package, signer_role)
    identity, phone = _identity_for(package, participant)
    duplicates = _duplicate_external_phones(package)
    override_reason = str(shared_phone_override_reason or '').strip()
    shared_phone_approver = approved_shared_phone_by or (
        actor if getattr(actor, 'is_superuser', False) else None
    )
    if phone in duplicates and not (shared_phone_approver and override_reason):
        raise OriginationError('This phone is mapped to more than one external signer. A Superuser override with a reason is required.')
    if access_mode not in dict(OriginationSignerSession.MODE_CHOICES):
        raise OriginationError('Choose self-service or assisted signing.')
    now = timezone.now()
    package.signer_sessions.filter(signer_role=signer_role, is_active=True).update(
        is_active=False, status=OriginationSignerSession.STATUS_CANCELLED,
        invalidated_at=now, updated_at=now,
    )
    raw_token = _session_token(package.pk, signer_role, request_id)
    ttl = max(1, min(168, int(getattr(settings, 'ORIGINATION_SIGNING_LINK_TTL_HOURS', SESSION_TTL_DEFAULT_HOURS) or SESSION_TTL_DEFAULT_HOURS)))
    session = OriginationSignerSession.objects.create(
        package=package, signer_role=signer_role, identity_snapshot=identity,
        phone_normalized=phone, phone_hash=_digest(f'phone:{phone}'), phone_last4=phone[-4:],
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        token_expires_at=now + timedelta(hours=ttl), access_mode=access_mode,
        created_by=actor, assisted_by=actor if access_mode == OriginationSignerSession.MODE_ASSISTED else None,
        request_id=request_id,
        shared_phone_override_reason=override_reason if phone in duplicates else '',
        shared_phone_approved_by=shared_phone_approver if phone in duplicates else None,
        shared_phone_approved_at=now if phone in duplicates else None,
    )
    _record_event(package.application, 'signer_session_created', actor=actor, request_id=request_id, after={
        'package_id': str(package.pk), 'session_id': str(session.pk), 'signer_role': signer_role,
        'access_mode': access_mode, 'shared_phone_override': bool(phone in duplicates),
    })
    return session, raw_token, False


def signing_url(raw_token: str) -> str:
    base = str(getattr(settings, 'APP_BASE_URL', '') or '').rstrip('/')
    if not base:
        raise OriginationError('APP_BASE_URL is required before signing links can be sent.')
    # Keep the bearer secret in the URL fragment. Browsers do not send the
    # fragment to Django, reverse proxies, access logs, or Referrer headers.
    return f'{base}/origination/sign/#{quote(raw_token)}'


def _send_sms(message: str, phone: str) -> dict[str, str]:
    import africastalking
    africastalking.initialize(
        str(settings.AFRICASTALKING_USERNAME), str(settings.AFRICASTALKING_API_KEY),
    )
    sender = str(getattr(settings, 'AFRICASTALKING_SENDER_ID', '') or '').strip() or None
    response = africastalking.SMS.send(message, [f'+{phone}'], sender_id=sender, enqueue=False)
    recipients = ((response or {}).get('SMSMessageData') or {}).get('Recipients') or []
    recipient = recipients[0] if recipients else {}
    status = str(recipient.get('status') or recipient.get('statusCode') or 'Accepted')
    message_id = str(recipient.get('messageId') or recipient.get('message_id') or '')
    return {'id': message_id, 'status': status}


def send_signing_invitation(session: OriginationSignerSession, raw_token: str, *, request_id: str) -> dict[str, str]:
    from core.services.external_resilience import execute_operation, reserve_operation
    url = signing_url(raw_token)
    operation, _ = reserve_operation(
        integration=IntegrationOperation.INTEGRATION_AFRICAS_TALKING,
        operation_type='origination_signing_invitation',
        deduplication_key=f'origination-signing-invite:{session.pk}',
        source_model='core.OriginationSignerSession', source_id=str(session.pk),
        request_id=request_id, requested_by=session.created_by,
        operation_payload=(str(session.pk), session.phone_hash), max_attempts=1,
    )
    result = execute_operation(operation, lambda: _send_sms(
        f'JBL signing request {session.package.external_reference}. Review the complete loan packet: {url}',
        session.phone_normalized,
    ), attempt_budget=1)
    return dict(result or {})


def resolve_session(raw_token: str, *, for_update: bool = False) -> OriginationSignerSession:
    token_hash = hashlib.sha256(str(raw_token or '').encode()).hexdigest()
    queryset = OriginationSignerSession.objects.select_related('package__application')
    if for_update:
        queryset = queryset.select_for_update()
    session = queryset.filter(token_hash=token_hash, is_active=True).first()
    if not session or not hmac.compare_digest(session.token_hash, token_hash):
        raise OriginationError('This signing link is invalid or has been replaced.')
    now = timezone.now()
    if session.token_expires_at <= now:
        if session.status not in {session.STATUS_VERIFIED, session.STATUS_EXPIRED}:
            session.status = session.STATUS_EXPIRED
            session.is_active = False
            session.invalidated_at = now
            session.save(update_fields=['status', 'is_active', 'invalidated_at', 'updated_at'])
        raise OriginationError('This signing link has expired. Ask JBL Operations to reissue it.')
    return session


def _throttle(
    session: OriginationSignerSession, *, action: str, ip_hash: str,
    request_id: str, payload_digest: str,
) -> bool:
    request_id = _require_request_id(request_id)
    replay = OriginationSigningRequestEvent.objects.filter(
        session=session, action=action, request_id=request_id,
    ).first()
    if replay:
        if not hmac.compare_digest(replay.payload_digest, payload_digest):
            raise OriginationError('This request key was already used with different signing data.')
        return True
    now = timezone.now()
    token_limit = 10
    if OriginationSigningRequestEvent.objects.filter(
        token_hash=session.token_hash, created_at__gte=now - timedelta(minutes=1),
    ).count() >= token_limit:
        raise OriginationSigningRateLimited('Too many signing requests. Wait one minute and try again.', retry_after=60)
    ip_limit = 10 if action == OriginationSigningRequestEvent.ACTION_SEND else 30
    if ip_hash and OriginationSigningRequestEvent.objects.filter(
        action=action, source_ip_hash=ip_hash, created_at__gte=now - timedelta(minutes=10),
    ).count() >= ip_limit:
        raise OriginationSigningRateLimited('Too many signing requests from this connection. Wait and try again.', retry_after=600)
    OriginationSigningRequestEvent.objects.create(
        session=session, action=action, request_id=request_id,
        payload_digest=payload_digest, token_hash=session.token_hash, source_ip_hash=ip_hash,
    )
    return False


@transaction.atomic
def record_consent_and_signature(
    *, raw_token: str, signature_capture: Any, consent: bool,
    access_mode: str, ip_hash: str, reviewed_pages: Any, request_id: str,
) -> OriginationSignerSession:
    session = resolve_session(raw_token, for_update=True)
    if session.status == session.STATUS_VERIFIED:
        return session
    if not consent:
        raise OriginationError('Review and accept the complete document packet before signing.')
    if access_mode != session.access_mode:
        raise OriginationError('This signing session was opened in a different access mode.')
    total_pages = sum(
        max(0, int(item.get('page_count') or 0))
        for item in session.package.document_manifest_snapshot or []
        if isinstance(item, dict)
    )
    try:
        reviewed = sorted({int(item) for item in (reviewed_pages or [])})
    except (TypeError, ValueError) as exc:
        raise OriginationError('The reviewed packet pages are invalid.') from exc
    if total_pages < 1 or reviewed != list(range(1, total_pages + 1)):
        raise OriginationError('Review every page of the complete packet before signing.')
    capture = _validated_signature_capture(signature_capture)
    request_digest = _digest(json.dumps({
        'capture': capture, 'consent': consent, 'access_mode': access_mode,
        'reviewed_pages': reviewed,
    }, sort_keys=True, separators=(',', ':')))
    if _throttle(
        session, action=OriginationSigningRequestEvent.ACTION_MUTATE,
        ip_hash=ip_hash, request_id=request_id, payload_digest=request_digest,
    ):
        return session
    capture_hash = hashlib.sha256(json.dumps(capture, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    changed = capture_hash != session.signature_capture_sha256 or session.consent_version != CONSENT_VERSION
    session.consent_version = CONSENT_VERSION
    session.consented_at = timezone.now()
    session.reviewed_pages = reviewed
    session.signature_capture = capture
    session.signature_capture_sha256 = capture_hash
    session.status = session.STATUS_PENDING
    session.save(update_fields=[
        'consent_version', 'consented_at', 'reviewed_pages', 'signature_capture',
        'signature_capture_sha256', 'status', 'updated_at',
    ])
    if changed:
        session.otp_challenges.filter(verified_at__isnull=True, invalidated_at__isnull=True).update(
            invalidated_at=timezone.now(),
        )
    return session


def _otp_send_limits(session: OriginationSignerSession) -> None:
    now = timezone.now()
    challenges = OriginationOtpChallenge.objects.filter(session=session)
    latest = challenges.order_by('-created_at').first()
    if latest and latest.created_at > now - timedelta(seconds=60):
        raise OriginationError('Wait 60 seconds before requesting another code.')
    if challenges.filter(created_at__gte=now - timedelta(minutes=30)).count() >= 3:
        raise OriginationError('The OTP send limit is reached. Try again after 30 minutes or ask Operations to reset the session.')
    phone_sessions = OriginationSignerSession.objects.filter(phone_hash=session.phone_hash).values('pk')
    phone_challenges = OriginationOtpChallenge.objects.filter(session_id__in=phone_sessions)
    if phone_challenges.filter(created_at__gte=now - timedelta(hours=1)).count() >= 5:
        raise OriginationError('This phone has received too many codes. Try again later.')
    if phone_challenges.filter(created_at__gte=now - timedelta(days=1)).count() >= 10:
        raise OriginationError('This phone has reached its daily signing-code limit.')


@transaction.atomic
def issue_otp(*, raw_token: str, request_id: str, ip_hash: str) -> tuple[OriginationOtpChallenge, str, bool]:
    request_id = _require_request_id(request_id)
    session = resolve_session(raw_token, for_update=True)
    _throttle(
        session, action=OriginationSigningRequestEvent.ACTION_SEND, ip_hash=ip_hash,
        request_id=request_id, payload_digest=_digest('otp-send'),
    )
    replay = session.otp_challenges.filter(request_id=request_id).first()
    if replay:
        return replay, '', True
    if session.status == session.STATUS_VERIFIED:
        raise OriginationError('This signer has already completed the packet.')
    if not session.consented_at or not session.signature_capture_sha256:
        raise OriginationError('Capture the signature and accept the packet before requesting an OTP.')
    now = timezone.now()
    if session.locked_until and session.locked_until > now:
        raise OriginationError('This signer is temporarily locked. Wait until the lock expires or ask Operations to reset it.')
    _otp_send_limits(session)
    session.otp_challenges.filter(verified_at__isnull=True, invalidated_at__isnull=True).update(invalidated_at=now)
    code = f'{secrets.randbelow(1_000_000):06d}'
    challenge = OriginationOtpChallenge.objects.create(
        session=session, code_hash=make_password(code), binding_sha256=_binding(session),
        send_sequence=(session.otp_challenges.count() + 1), attempts_remaining=5,
        request_id=request_id, source_ip_hash=ip_hash, expires_at=now + OTP_TTL,
    )
    session.status = session.STATUS_OTP_SENT
    session.save(update_fields=['status', 'updated_at'])
    return challenge, code, False


def dispatch_otp(challenge: OriginationOtpChallenge, code: str) -> OriginationOtpChallenge:
    from core.services.external_resilience import execute_operation, reserve_operation
    session = challenge.session
    operation, _ = reserve_operation(
        integration=IntegrationOperation.INTEGRATION_AFRICAS_TALKING,
        operation_type='origination_signing_otp',
        deduplication_key=f'origination-otp:{challenge.pk}',
        source_model='core.OriginationOtpChallenge', source_id=str(challenge.pk),
        request_id=challenge.request_id, requested_by=session.created_by,
        operation_payload=(str(challenge.pk), session.phone_hash), max_attempts=1,
    )
    try:
        result = execute_operation(operation, lambda: _send_sms(
            f'JBL verification code: {code}. It expires in 10 minutes. Do not share it with anyone except when you are personally signing on an assisted JBL device.',
            session.phone_normalized,
        ), attempt_budget=1) or {}
    except Exception:
        challenge.delivery_status = OriginationOtpChallenge.DELIVERY_UNKNOWN
        challenge.provider_status = 'send_error'
        challenge.save(update_fields=['delivery_status', 'provider_status'])
        raise
    challenge.provider_message_id = str(result.get('id') or '')
    challenge.provider_status = str(result.get('status') or 'Accepted')[:80]
    challenge.delivery_status = OriginationOtpChallenge.DELIVERY_ACCEPTED
    challenge.save(update_fields=['provider_message_id', 'provider_status', 'delivery_status'])
    return challenge


def record_delivery_report(*, provider_message_id: str, provider_status: str) -> bool:
    """Store an Africa's Talking delivery receipt without changing signing state."""
    message_id = str(provider_message_id or '').strip()[:255]
    status = str(provider_status or '').strip()[:80]
    if not message_id:
        return False
    normalized = status.casefold().replace(' ', '')
    if normalized in {'success', 'delivered', 'sent'}:
        delivery_status = OriginationOtpChallenge.DELIVERY_DELIVERED
    elif normalized in {
        'failed', 'rejected', 'expired', 'undeliverable', 'insufficientbalance',
    }:
        delivery_status = OriginationOtpChallenge.DELIVERY_FAILED
    else:
        delivery_status = OriginationOtpChallenge.DELIVERY_UNKNOWN
    # Deliberately updates delivery evidence only. A provider callback can never
    # verify an OTP, create a signature action, or advance a package/application.
    queryset = OriginationOtpChallenge.objects.filter(provider_message_id=message_id)
    if delivery_status != OriginationOtpChallenge.DELIVERY_DELIVERED:
        queryset = queryset.exclude(delivery_status=OriginationOtpChallenge.DELIVERY_DELIVERED)
    return bool(queryset.update(provider_status=status, delivery_status=delivery_status))


def _update_package_status(package: OriginationSigningPackage) -> None:
    required = {
        (item['document_key'], item['key']) for item in _slot_catalog(package) if item['required']
    }
    complete = set(package.actions.filter(mode=OriginationSigningAction.MODE_VERIFIED).values_list('document_key', 'slot_key'))
    application = package.application
    if required and required <= complete:
        signed = render_verified_package(package)
        package.signed_document_hash = hashlib.sha256(signed).hexdigest()
        package.pending_signed_document = signed
        package.status = package.STATUS_FULLY_SIGNED
        package.archive_status = 'pending'
        package.finalized_at = timezone.now()
        application.status = LoanOriginationApplication.STATUS_FULLY_SIGNED
    elif complete:
        package.status = package.STATUS_IN_PROGRESS
        application.status = LoanOriginationApplication.STATUS_PARTIALLY_SIGNED
    package.save()
    application.revision += 1
    application.save(update_fields=['status', 'revision', 'updated_at'])


def verify_otp(*, raw_token: str, code: str, request_id: str, ip_hash: str) -> OriginationSignerSession:
    request_id = _require_request_id(request_id)
    error_message = ''
    verified_session = None
    with transaction.atomic():
        session = resolve_session(raw_token, for_update=True)
        package = OriginationSigningPackage.objects.select_for_update().select_related('application').get(pk=session.package_id)
        session.package = package
        replayed_request = _throttle(
            session, action=OriginationSigningRequestEvent.ACTION_VERIFY, ip_hash=ip_hash,
            request_id=request_id, payload_digest=_digest(f'otp-verify:{str(code or "").strip()}'),
        )
        if session.status == session.STATUS_VERIFIED:
            return session
        if replayed_request:
            error_message = 'This verification request was already processed. Retry with the current code.'
        now = timezone.now()
        if error_message:
            pass
        elif session.locked_until and session.locked_until > now:
            error_message = 'This signer is temporarily locked. Wait or ask Operations to reset the session.'
        else:
            challenge = session.otp_challenges.select_for_update().filter(
                invalidated_at__isnull=True, verified_at__isnull=True,
            ).order_by('-created_at').first()
            if not challenge or challenge.expires_at <= now:
                error_message = 'The verification code has expired. Request a new code.'
            elif challenge.binding_sha256 != _binding(session):
                challenge.invalidated_at = now
                challenge.save(update_fields=['invalidated_at'])
                error_message = 'The packet, consent, or signature changed. Request a new code.'
            elif not check_password(str(code or '').strip(), challenge.code_hash):
                challenge.last_attempt_at = now
                challenge.attempts_remaining = max(0, challenge.attempts_remaining - 1)
                if challenge.attempts_remaining == 0:
                    challenge.invalidated_at = now
                    challenge.save(update_fields=['attempts_remaining', 'last_attempt_at', 'invalidated_at'])
                    session.status = session.STATUS_LOCKED
                    session.locked_until = now + LOCKOUT_WINDOW
                    session.save(update_fields=['status', 'locked_until', 'updated_at'])
                    error_message = 'Too many incorrect codes. This signing session is locked for 30 minutes.'
                else:
                    challenge.save(update_fields=['attempts_remaining', 'last_attempt_at'])
                    error_message = f'Incorrect verification code. {challenge.attempts_remaining} attempt(s) remain.'
            else:
                challenge.last_attempt_at = now
                challenge.verified_at = now
                challenge.save(update_fields=['verified_at', 'last_attempt_at'])
                capture = dict(session.signature_capture or {})
                for slot in _participant(package, session.signer_role)['signature_slots']:
                    OriginationSigningAction.objects.get_or_create(
                        package=package, document_key=slot['document_key'], slot_key=slot['key'],
                        defaults={
                            'signer_role': session.signer_role,
                            'action_type': OriginationSigningAction.TYPE_SIGNATURE,
                            'mode': OriginationSigningAction.MODE_VERIFIED,
                            'signer_session': session,
                            'request_id': f'otp:{challenge.pk}:{slot["document_key"]}:{slot["key"]}'[:128],
                            'metadata': {
                                'signature_capture': capture,
                                'capture_sha256': session.signature_capture_sha256,
                                'consent_version': session.consent_version,
                                'consented_at': session.consented_at.isoformat(),
                                'otp_verified_at': now.isoformat(),
                                'access_mode': session.access_mode,
                                'phone_last4': session.phone_last4,
                            },
                        },
                    )
                session.status = session.STATUS_VERIFIED
                session.verified_at = now
                session.save(update_fields=['status', 'verified_at', 'updated_at'])
                _update_package_status(package)
                _record_event(package.application, 'external_signer_verified', actor=None, request_id=request_id, after={
                    'package_id': str(package.pk), 'session_id': str(session.pk),
                    'signer_role': session.signer_role, 'access_mode': session.access_mode,
                    'shared_phone_override': bool(session.shared_phone_approved_by_id),
                })
                verified_session = session
    if error_message:
        raise OriginationError(error_message)
    return verified_session


@transaction.atomic
def reset_signer_session(*, session_id, actor, reason: str, request_id: str) -> tuple[OriginationSignerSession, str]:
    request_id = _require_request_id(request_id)
    reason = str(reason or '').strip()
    if not reason:
        raise OriginationError('Give the audited reason for resetting this signer session.')
    old = OriginationSignerSession.objects.select_for_update().select_related('package').get(pk=session_id)
    if old.status == old.STATUS_VERIFIED:
        raise OriginationError('A verified signer session cannot be reset. The signed action is immutable.')
    old.is_active = False
    old.status = old.STATUS_CANCELLED
    old.invalidated_at = timezone.now()
    old.save(update_fields=['is_active', 'status', 'invalidated_at', 'updated_at'])
    return create_signer_session(
        package_id=old.package_id, signer_role=old.signer_role, actor=actor,
        request_id=request_id, access_mode=old.access_mode,
        shared_phone_override_reason=old.shared_phone_override_reason,
        approved_shared_phone_by=old.shared_phone_approved_by,
    )[:2]


def serialize_public_session(session: OriginationSignerSession) -> dict[str, Any]:
    documents = [
        {'key': item.get('key'), 'name': item.get('name'), 'page_count': item.get('page_count')}
        for item in session.package.document_manifest_snapshot or []
    ]
    latest = session.otp_challenges.order_by('-created_at').first()
    return {
        'reference': session.package.external_reference,
        'signer_role': session.signer_role,
        'signer_name': str((session.identity_snapshot or {}).get('name') or ''),
        'phone_masked': _masked_phone(session.phone_normalized),
        'access_mode': session.access_mode,
        'status': session.status,
        'expires_at': session.token_expires_at.isoformat(),
        'consented': bool(session.consented_at),
        'reviewed_pages': list(session.reviewed_pages or []),
        'capture_method': str((session.signature_capture or {}).get('method') or ''),
        'shared_phone_override': bool(session.shared_phone_approved_by_id),
        'documents': documents,
        'otp': {
            'delivery_status': latest.delivery_status if latest else '',
            'expires_at': latest.expires_at.isoformat() if latest else '',
            'attempts_remaining': latest.attempts_remaining if latest else 5,
            'resend_available_at': (latest.created_at + timedelta(seconds=60)).isoformat() if latest else '',
        },
    }


def serialize_verified_signing(package: OriginationSigningPackage) -> dict[str, Any]:
    actions = {
        (item.document_key, item.slot_key): item
        for item in package.actions.filter(mode=OriginationSigningAction.MODE_VERIFIED)
    }
    sessions = {
        item.signer_role: item
        for item in package.signer_sessions.filter(is_active=True).order_by('signer_role', '-created_at')
    }
    participants = []
    for raw in package.participants_snapshot or []:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get('role') or '')
        slots = [item for item in _slot_catalog(package) if item['role'] == role]
        session = sessions.get(role)
        participants.append({
            'role': role,
            'label': role.replace('_', ' ').title(),
            'staff': role in STAFF_SIGNER_ROLES,
            'phone_mapped': (
                True if role in STAFF_SIGNER_ROLES
                else bool(normalize_kenyan_phone(_resolved_identity(package, raw).get('phone')))
            ),
            'session_id': str(session.pk) if session else '',
            'session_status': session.status if session else '',
            'access_mode': session.access_mode if session else '',
            'locked_until': session.locked_until.isoformat() if session and session.locked_until else '',
            'slots': [{
                **slot,
                'completed': (slot['document_key'], slot['key']) in actions,
            } for slot in slots],
        })
    stamps = OriginationStampAsset.objects.filter(
        active=True, environment=OriginationStampAsset.ENV_PRODUCTION,
    ).filter(models.Q(branch__isnull=True) | models.Q(branch=package.application.branch_ref))
    return {
        'enabled': esign_enabled(), 'test_mode': package.test_mode,
        'participants': participants,
        'production_stamps': [{
            'id': str(item.pk), 'name': item.name, 'version': item.version,
            'scope': item.branch.name if item.branch_id else 'Organization',
        } for item in stamps.select_related('branch').distinct().order_by('name', '-version')],
        'archive_status': package.archive_status,
        'archive_error': package.archive_error,
    }


@transaction.atomic
def complete_staff_signatures(
    *, package_id, signer_role: str, actor, signature_capture: Any,
    expected_revision: int, request_id: str,
) -> OriginationSigningPackage:
    request_id = _require_request_id(request_id)
    if signer_role not in STAFF_SIGNER_ROLES:
        raise OriginationError('This role must sign through its external signer session.')
    package = OriginationSigningPackage.objects.select_for_update().select_related('application').get(pk=package_id)
    if package.test_mode:
        raise OriginationError('Staff verified signing is unavailable on a test package.')
    if package.application.revision != int(expected_revision):
        raise OriginationConflict('This application changed. Refresh before signing.')
    participant = _participant(package, signer_role)
    capture = _validated_signature_capture(signature_capture)
    capture_hash = hashlib.sha256(json.dumps(capture, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    created_any = False
    for slot in participant['signature_slots']:
        action, created = OriginationSigningAction.objects.get_or_create(
            package=package, document_key=slot['document_key'], slot_key=slot['key'],
            defaults={
                'signer_role': signer_role, 'action_type': OriginationSigningAction.TYPE_SIGNATURE,
                'mode': OriginationSigningAction.MODE_VERIFIED, 'actor': actor,
                'request_id': f'{request_id}:{slot["document_key"]}:{slot["key"]}'[:128],
                'metadata': {
                    'signature_capture': capture, 'capture_sha256': capture_hash,
                    'consent_version': CONSENT_VERSION, 'consented_at': timezone.now().isoformat(),
                    'staff_authenticated': True,
                },
            },
        )
        if not created and (action.actor_id != actor.pk or (action.metadata or {}).get('capture_sha256') != capture_hash):
            raise OriginationError('A different verified action already completed this signature slot.')
        created_any = created_any or created
    if not created_any:
        return package
    _update_package_status(package)
    _record_event(package.application, 'staff_signer_verified', actor=actor, request_id=request_id, after={
        'package_id': str(package.pk), 'signer_role': signer_role,
    })
    return package


@transaction.atomic
def apply_production_stamp(
    *, package_id, document_key: str, slot_key: str, signer_role: str,
    stamp_asset_id, actor, expected_revision: int, request_id: str,
) -> OriginationSigningPackage:
    request_id = _require_request_id(request_id)
    package = OriginationSigningPackage.objects.select_for_update().select_related('application').get(pk=package_id)
    if package.test_mode:
        raise OriginationError('Production stamps cannot be applied to a test package.')
    if package.application.revision != int(expected_revision):
        raise OriginationConflict('This application changed. Refresh before stamping.')
    selected = next((item for item in _slot_catalog(package) if (
        item['document_key'] == document_key and item['key'] == slot_key
        and item['role'] == signer_role and item['type'] == OriginationSigningAction.TYPE_STAMP
    )), None)
    if not selected:
        raise OriginationError('Choose a configured stamp slot from this package.')
    stamp = OriginationStampAsset.objects.filter(
        pk=stamp_asset_id, active=True, environment=OriginationStampAsset.ENV_PRODUCTION,
    ).select_related('branch').first()
    if not stamp:
        raise OriginationError('Choose an active production stamp.')
    if stamp.branch_id and stamp.branch_id != package.application.branch_ref_id:
        raise OriginationError('This stamp is not approved for the application branch.')
    action, created = OriginationSigningAction.objects.get_or_create(
        package=package, document_key=document_key, slot_key=slot_key,
        defaults={
            'signer_role': signer_role, 'action_type': OriginationSigningAction.TYPE_STAMP,
            'mode': OriginationSigningAction.MODE_VERIFIED, 'actor': actor,
            'stamp_asset': stamp, 'request_id': request_id,
            'metadata': {'staff_authenticated': True, 'stamp_sha256': stamp.content_sha256},
        },
    )
    if not created and action.stamp_asset_id != stamp.pk:
        raise OriginationError('A different production stamp already completed this slot.')
    if not created:
        return package
    _update_package_status(package)
    _record_event(package.application, 'production_stamp_applied', actor=actor, request_id=request_id, after={
        'package_id': str(package.pk), 'document_key': document_key,
        'slot_key': slot_key, 'signer_role': signer_role, 'stamp_asset_id': str(stamp.pk),
    })
    return package


def archive_signed_package(*, package_id, actor, request_id: str) -> OriginationSigningPackage:
    request_id = _require_request_id(request_id)
    package = OriginationSigningPackage.objects.select_related('application').get(pk=package_id)
    if package.archive_status == 'uploaded' and package.final_drive_file_id:
        return package
    if package.status != package.STATUS_FULLY_SIGNED or not package.signed_document_hash:
        raise OriginationError('Only a fully signed package can be archived.')
    content = bytes(package.pending_signed_document or b'')
    if not content:
        content = render_verified_package(package)
    if hashlib.sha256(content).hexdigest() != package.signed_document_hash:
        raise OriginationError('The signed packet does not match its immutable final hash.')
    try:
        from core.services.order_approval import GoogleDriveMediaStorage
        file_id, url = GoogleDriveMediaStorage().upload(
            content,
            f'{package.application.reference_number}-SIGNED.pdf',
            'application/pdf', package.application.reference_number,
            package.finalized_at or timezone.now(), workflow_key='origination',
            record_type='signing-package', record_key=str(package.pk), attempt_budget=1,
        )
    except Exception as exc:
        logger.exception('Origination signed packet archival failed for package %s.', package.pk)
        OriginationSigningPackage.objects.filter(pk=package.pk).update(
            archive_status='failed', archive_error='Drive archival failed; retry required.',
        )
        raise OriginationError('The signed packet is complete, but restricted Drive archival failed. Retry archival.') from exc
    with transaction.atomic():
        locked = OriginationSigningPackage.objects.select_for_update().select_related('application').get(pk=package.pk)
        if locked.signed_document_hash != package.signed_document_hash:
            raise OriginationConflict('The signed package changed before archival completed.')
        locked.final_drive_file_id = file_id
        locked.final_document_reference = url
        locked.archive_status = 'uploaded'
        locked.archive_error = ''
        locked.archived_at = timezone.now()
        locked.pending_signed_document = b''
        locked.save(update_fields=[
            'final_drive_file_id', 'final_document_reference', 'archive_status',
            'archive_error', 'archived_at', 'pending_signed_document', 'updated_at',
        ])
        _record_event(locked.application, 'signed_packet_archived', actor=actor, request_id=request_id, after={
            'package_id': str(locked.pk), 'signed_document_hash': locked.signed_document_hash,
        })
        return locked


def client_ip_hash(request) -> str:
    return _client_ip_hash(request)
