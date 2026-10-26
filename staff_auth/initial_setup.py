"""Audited existing-account preparation, never signup, recovery or dispatch."""
from datetime import timedelta
import hashlib
import json
import re
import uuid

from allauth.account.fields import EmailField
from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from allauth.mfa.models import Authenticator
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models.functions import Lower, Trim
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.views.decorators.debug import sensitive_variables

from core.models import ComplianceAuditEvent
from core.services.compliance_audit import record_event

from .crypto import encrypt_secret
from .governance import admission_mutation
from .models import StaffBrowserAdmission, StaffBrowserSetupGrant


SETUP_SECONDS = 3600  # Security default, not an operational delivery objective.
PROOF_SALT = 'staff-browser-initial-mailbox-proof-v1'


class InitialSetupError(ValidationError):
    pass


def binding_digest(purpose, value):
    return salted_hmac(f'staff-browser-initial-setup-v1:{purpose}', str(value), algorithm='sha256').hexdigest()


def canonical_address(user):
    try:
        return EmailField(max_length=254).clean(user.email)
    except ValidationError:
        raise InitialSetupError('Set a valid canonical staff email through the existing staff lifecycle first.') from None


def require_initial_account(user, admission):
    if user is None or not user.is_active or user.is_staff or user.is_superuser:
        raise InitialSetupError('Initial setup requires an active existing non-Admin staff account.')
    if user.has_usable_password() or Authenticator.objects.filter(user_id=user.pk).exists():
        raise InitialSetupError('Existing credentials require their separate verified support procedure.')
    if admission is None or not admission.enabled or admission.user_id != user.pk:
        raise InitialSetupError('Explicit current browser admission is required before initial setup.')
    email = canonical_address(user)
    if (
        get_user_model().objects.exclude(pk=user.pk).annotate(_setup_email=Lower(Trim('email'))).filter(_setup_email=email).exists()
        or EmailAddress.objects.exclude(user_id=user.pk).annotate(_setup_email=Lower(Trim('email'))).filter(_setup_email=email).exists()
    ):
        raise InitialSetupError('The canonical address has conflicting account ownership; resolve it without merging identities.')
    return email


def _address_rows(user, email):
    rows = list(EmailAddress.objects.filter(user_id=user.pk).order_by('pk'))
    if rows and (len(rows) != 1 or rows[0].email.lower() != email or rows[0].verified):
        raise InitialSetupError('Existing native addresses require their separate verified support procedure.')
    return rows


def _snapshot(user, admission):
    email = require_initial_account(user, admission)
    rows = _address_rows(user, email)
    values = {
        'target_user_id': user.pk, 'admission_id': str(admission.pk), 'revision': admission.revision,
        'email_fingerprint': binding_digest('email', email),
        'password_fingerprint': binding_digest('password-state', user.password),
        'native_addresses': [{'id': row.pk, 'primary': row.primary, 'verified': row.verified} for row in rows],
    }
    return values, hashlib.sha256(json.dumps(values, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _actor_id(actor):
    if actor is None or not actor.is_authenticated or not actor.pk:
        raise PermissionDenied('An active Django Superuser must prepare initial setup.')
    return actor.pk


def _target_id(value):
    if type(value) is not int or not 0 < value <= 9223372036854775807:
        raise InitialSetupError('Choose the exact existing staff user ID.')


def preview_setup(*, actor, target_user_id):
    _target_id(target_user_id)
    User = get_user_model()
    if not User.objects.filter(pk=_actor_id(actor), is_active=True, is_superuser=True).exists():
        raise PermissionDenied('Only a currently active Django Superuser may prepare initial setup.')
    user = User.objects.filter(pk=target_user_id).first()
    admission = StaffBrowserAdmission.objects.filter(user_id=target_user_id).first()
    values, fingerprint = _snapshot(user, admission)
    return {
        'target_user_id': target_user_id, 'admission_id': values['admission_id'],
        'revision': values['revision'], 'snapshot_fingerprint': fingerprint,
        'changes_password_or_verified_status_or_grants': False, 'dispatches_mail': False,
    }


@sensitive_variables()
def prepare_setup(*, actor, target_user_id, expected_revision, snapshot_fingerprint, request_key, reason):
    _target_id(target_user_id)
    actor_id = _actor_id(actor)
    if type(expected_revision) is not int or not 1 <= expected_revision < 9223372036854775807:
        raise InitialSetupError('Supply the reviewed current browser admission revision.')
    if not isinstance(snapshot_fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', snapshot_fingerprint):
        raise InitialSetupError('Supply the reviewed setup snapshot fingerprint.')
    if not isinstance(request_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', request_key):
        raise InitialSetupError('Supply a stable 8-80 character request key.')
    if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 500:
        raise InitialSetupError('Supply an 8-500 character administrative reason without secrets.')
    reason = reason.strip()
    payload = dict(actor_id=actor_id, target_user_id=target_user_id, expected_revision=expected_revision,
                   snapshot_fingerprint=snapshot_fingerprint, reason=reason)
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    deduplication_key = f'staff-browser-setup-prepared:{actor_id}:{request_key}'
    with transaction.atomic(), admission_mutation():
        User = get_user_model()
        roots = list(User.objects.select_for_update().filter(is_active=True, is_superuser=True).order_by('pk'))
        current_actor = next((root for root in roots if root.pk == actor_id), None)
        if current_actor is None:
            raise PermissionDenied('The authorizing Superuser is no longer active.')
        user = User.objects.select_for_update().filter(pk=target_user_id).first()
        if user is None:
            raise InitialSetupError('The selected account no longer exists.')
        existing = ComplianceAuditEvent.objects.filter(deduplication_key=deduplication_key).first()
        if existing:
            if not constant_time_compare(str(existing.metadata.get('request_fingerprint', '')), fingerprint):
                raise InitialSetupError('This request key belongs to a different setup preparation.')
            return {**existing.after_values, 'audit_event_id': str(existing.pk), 'replayed': True}
        admission = StaffBrowserAdmission.objects.select_for_update().filter(user_id=user.pk).first()
        values, current_fingerprint = _snapshot(user, admission)
        if admission.revision != expected_revision or not constant_time_compare(current_fingerprint, snapshot_fingerprint):
            raise InitialSetupError('Staff setup changed; review a fresh preview before applying.')
        email = canonical_address(user)
        address = EmailAddress.objects.filter(user_id=user.pk).first()
        if address is None:
            address = EmailAddress.objects.create(user=user, email=email, primary=True, verified=False)
        elif not address.primary:
            address.primary = True
            address.save(update_fields=['primary'])
        grant_id = uuid.uuid4()
        # Native HMAC confirmation keys can repeat for the same address/second.
        # Django's signed envelope binds this proof to this exact preparation.
        confirmation = encrypt_secret(signing.dumps({
            'setup_id': str(grant_id), 'native_key': EmailConfirmationHMAC.create(address).key,
        }, salt=PROOF_SALT))
        admission.revision += 1
        admission.save()
        expires_at = timezone.now() + timedelta(seconds=SETUP_SECONDS)
        after = {
            'setup_id': str(grant_id), 'target_user_id': user.pk,
            'admission_id': str(admission.pk), 'revision': admission.revision,
            'email_address_id': address.pk, 'email_fingerprint': values['email_fingerprint'],
            'password_fingerprint': values['password_fingerprint'], 'expires_at': expires_at.isoformat(),
        }
        event, _ = record_event(
            workflow='access_control', action='staff_browser.setup_prepared', category='identity',
            subject_type='staff_browser_setup', subject_id=str(grant_id), actor=current_actor,
            request_id=request_key, deduplication_key=deduplication_key,
            source_model='staff_auth.StaffBrowserSetupGrant', source_event_id=str(grant_id),
            after_values=after, metadata={'request_fingerprint': fingerprint, 'reason': reason}, sensitive=True,
        )
        StaffBrowserSetupGrant.objects.create(
            id=grant_id, admission=admission, admission_revision=admission.revision,
            email_address_id=address.pk, email_fingerprint=values['email_fingerprint'],
            password_fingerprint=values['password_fingerprint'], confirmation_cipher=confirmation,
            prepared_audit_id=event.pk, expires_at=expires_at,
        )
        return {**after, 'audit_event_id': str(event.pk), 'replayed': False}
