"""Audited, request-keyed browser-only identity administration. No dispatch."""
import hashlib
import json
import re

from allauth.mfa.models import Authenticator
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.crypto import constant_time_compare

from core.models import ComplianceAuditEvent
from core.services.compliance_audit import record_event

from .governance import admission_mutation
from .models import StaffBrowserAdmission


ACTIONS = ('authorize', 'suspend', 'revoke_sessions', 'reset_mfa')


class BrowserAdmissionError(ValidationError):
    """A stale or invalid staff browser lifecycle request."""


def _actor_id(actor):
    if not actor or not actor.is_authenticated or not actor.pk:
        raise PermissionDenied('An active Django Superuser must authorize this operation.')
    return actor.pk


def _validate_target(action, target_user_id):
    if action not in ACTIONS:
        raise BrowserAdmissionError('Choose an allowed browser lifecycle action.')
    if type(target_user_id) is not int or not 0 < target_user_id <= 9223372036854775807:
        raise BrowserAdmissionError('Choose an existing staff user ID.')


def _snapshot(admission):
    if admission is None:
        return {'admission_id': None, 'revision': 0, 'enabled': False}
    return {
        'admission_id': str(admission.pk),
        'revision': admission.revision,
        'enabled': admission.enabled,
    }


def preview_change(*, actor, target_user_id, action):
    """Read-only impact summary; never enroll, verify email or create a user."""
    _validate_target(action, target_user_id)
    User = get_user_model()
    if not User.objects.filter(pk=_actor_id(actor), is_active=True, is_superuser=True).exists():
        raise PermissionDenied('Only a currently active Django Superuser may manage browser admission.')
    target = User.objects.filter(pk=target_user_id).first()
    if target is None:
        raise BrowserAdmissionError('The selected staff account no longer exists.')
    if action == 'authorize' and not target.is_active:
        raise BrowserAdmissionError('An inactive staff account cannot be admitted.')
    admission = StaffBrowserAdmission.objects.filter(user_id=target.pk).first()
    if admission is None and action != 'authorize':
        raise BrowserAdmissionError('The staff account has no browser admission to change.')
    return {
        **_snapshot(admission), 'target_user_id': target.pk, 'action': action,
        'factors_to_remove': Authenticator.objects.filter(user_id=target.pk).count() if action == 'reset_mfa' else 0,
        'verification_reference_required': action == 'reset_mfa',
        'changes_password_or_telegram_or_grants': False,
    }


def apply_change(*, actor, target_user_id, action, expected_revision, request_key, reason, verification_reference=''):
    """Apply one explicit action, preserving audit and exactly-once retry semantics.

    Infrastructure/CLI access is not authentication for a browser endpoint. A
    future caller must authenticate the actor and use protected operator UX.
    """
    _validate_target(action, target_user_id)
    actor_id = _actor_id(actor)
    if type(expected_revision) is not int or not 0 <= expected_revision < 9223372036854775807:
        raise BrowserAdmissionError('Supply the reviewed browser admission revision.')
    if not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', request_key):
        raise BrowserAdmissionError('Supply a stable 8-80 character request key.')
    if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 500:
        raise BrowserAdmissionError('Supply a concise 8-500 character administrative reason without secrets.')
    reason = reason.strip()
    if not isinstance(verification_reference, str):
        raise BrowserAdmissionError('Use a support verification reference, not credential material.')
    if action == 'reset_mfa':
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{2,79}', verification_reference):
            raise BrowserAdmissionError('MFA reset requires an identity-verification support reference.')
    elif verification_reference:
        raise BrowserAdmissionError('Verification references apply only to MFA reset.')
    payload = {
        'actor_id': actor_id, 'target_user_id': target_user_id, 'action': action,
        'expected_revision': expected_revision, 'reason': reason,
        'verification_reference': verification_reference,
    }
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    deduplication_key = f'staff-browser:{actor_id}:{request_key}'
    with transaction.atomic(), admission_mutation():
        User = get_user_model()
        # Match governed hard-delete's roots-first order. These rare technical
        # operations serialize deliberately; the existing staff row also locks
        # first admission creation when no admission row exists yet.
        roots = list(User.objects.select_for_update().filter(is_active=True, is_superuser=True).order_by('pk'))
        current_actor = next((user for user in roots if user.pk == actor_id), None)
        if current_actor is None:
            raise PermissionDenied('The authorizing Superuser is no longer active.')
        target = User.objects.select_for_update().filter(pk=target_user_id).first()
        if target is None:
            raise BrowserAdmissionError('The selected staff account no longer exists.')
        existing = ComplianceAuditEvent.objects.filter(deduplication_key=deduplication_key).first()
        if existing:
            if not constant_time_compare(str(existing.metadata.get('request_fingerprint', '')), fingerprint):
                raise BrowserAdmissionError('This request key was used for a different browser lifecycle action.')
            return {**existing.after_values, 'audit_event_id': str(existing.pk), 'replayed': True}
        admission = StaffBrowserAdmission.objects.select_for_update().filter(user_id=target.pk).first()
        before = _snapshot(admission)
        if before['revision'] != expected_revision:
            raise BrowserAdmissionError('Browser admission changed. Review the current revision before retrying.')
        if action == 'authorize' and not target.is_active:
            raise BrowserAdmissionError('An inactive staff account cannot be admitted.')
        if admission is None:
            if action != 'authorize':
                raise BrowserAdmissionError('The staff account has no browser admission to change.')
            admission = StaffBrowserAdmission(user=target, subject_user_id=target.pk)
        else:
            admission.revision += 1
        if action in ('authorize', 'suspend'):
            admission.enabled = action == 'authorize'
        removed = 0
        if action == 'reset_mfa':
            removed, _details = Authenticator.objects.filter(user_id=target.pk).delete()
        admission.save()
        after = {**_snapshot(admission), 'target_user_id': target.pk, 'action': action, 'factors_removed': removed}
        event, _created = record_event(
            workflow=ComplianceAuditEvent.WORKFLOW_ACCESS_CONTROL,
            action=f'staff_browser.{action}', category='identity',
            subject_type='staff_browser_admission', subject_id=str(admission.pk),
            actor=current_actor, request_id=request_key,
            source_model='staff_auth.StaffBrowserAdmission', source_event_id=str(admission.pk),
            deduplication_key=deduplication_key, before_values=before, after_values=after,
            metadata={'request_fingerprint': fingerprint, 'reason': reason, 'verification_reference': verification_reference},
            sensitive=True,
        )
        return {**after, 'audit_event_id': str(event.pk), 'replayed': False}
