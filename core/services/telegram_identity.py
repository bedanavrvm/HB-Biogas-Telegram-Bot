"""Canonical Telegram authentication and User access resolution."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction


class TelegramAuthenticationError(ValueError):
    pass


@dataclass(frozen=True)
class TelegramIdentity:
    telegram_id: str
    username: str
    first_name: str
    last_name: str
    payload: dict


def identity_from_user_payload(user_payload: dict) -> TelegramIdentity:
    return TelegramIdentity(
        telegram_id=str(user_payload.get('id') or '').strip(),
        username=str(user_payload.get('username') or '').strip().lstrip('@'),
        first_name=str(user_payload.get('first_name') or '').strip(),
        last_name=str(user_payload.get('last_name') or '').strip(),
        payload=user_payload,
    )


def validate_telegram_init_data(
    init_data: str, *, bot_token: str | None = None, max_age_seconds: int | None = None,
) -> tuple[dict, TelegramIdentity]:
    """Validate Telegram initData once, including signature and freshness."""
    token = bot_token if bot_token is not None else getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    if not token:
        raise TelegramAuthenticationError('Telegram bot authentication is not configured.')
    if not init_data:
        raise TelegramAuthenticationError('Telegram Mini App authentication data is missing.')
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop('hash', '')
    if not received_hash:
        raise TelegramAuthenticationError('Telegram Mini App hash is missing.')
    data_check_string = '\n'.join(f'{key}={value}' for key, value in sorted(pairs.items()))
    secret_key = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise TelegramAuthenticationError('Telegram Mini App authentication failed.')
    max_age = max_age_seconds if max_age_seconds is not None else 86400
    try:
        auth_date = int(pairs.get('auth_date') or '0')
    except ValueError as exc:
        raise TelegramAuthenticationError('Telegram Mini App auth_date is invalid.') from exc
    now = time.time()
    if auth_date > now + 60:
        raise TelegramAuthenticationError('Telegram Mini App auth_date is in the future.')
    if max_age > 0 and (not auth_date or now - auth_date > max_age):
        raise TelegramAuthenticationError('Telegram Mini App authentication expired.')
    try:
        user_payload = json.loads(pairs.get('user') or '{}')
    except (TypeError, ValueError) as exc:
        raise TelegramAuthenticationError('Telegram Mini App user data is malformed.') from exc
    telegram_id = str(user_payload.get('id') or '').strip()
    if not telegram_id:
        raise TelegramAuthenticationError('Telegram Mini App user ID is missing.')
    return pairs, identity_from_user_payload(user_payload)


def resolve_user_by_telegram_id(telegram_id: str):
    """Resolve the canonical active User by immutable Telegram ID."""
    from core.models import UserProfile
    profile = UserProfile.objects.select_related('user').filter(telegram_id=str(telegram_id)).first()
    return profile.user if profile and profile.user.is_active else None


@transaction.atomic
def resolve_or_bind_telegram_user(identity: TelegramIdentity, *, activation_code: str = ''):
    """Resolve by immutable ID, or bind an enrolled user with activation proof.

    Legacy enrolled profiles without an activation challenge retain their
    existing username-matched binding path.  Newly onboarded staff receive a
    challenge and therefore cannot bind until the single-use code is supplied.
    """
    from core.models import UserProfile
    user = resolve_user_by_telegram_id(identity.telegram_id)
    if user:
        return user
    if not identity.username:
        return None
    profile = UserProfile.objects.select_for_update().select_related('user').filter(
        telegram_id='', telegram_username__iexact=identity.username,
    ).first()
    if not profile or not profile.user.is_active:
        return None
    if UserProfile.objects.filter(telegram_id=identity.telegram_id).exclude(pk=profile.pk).exists():
        return None
    activation_required = bool((profile.telegram_metadata or {}).get('activation_required'))
    if activation_required or profile.user.telegram_staff_activations.exists():
        from core.services.staff_lifecycle import consume_telegram_activation

        if not consume_telegram_activation(user=profile.user, code=activation_code):
            return None
    profile.telegram_id = identity.telegram_id
    profile.telegram_username = identity.username
    profile.telegram_metadata = {
        **(profile.telegram_metadata or {}),
        'first_name': identity.first_name,
        'last_name': identity.last_name,
        'bound_from_signed_init_data': True,
        'activation_required': False,
    }
    profile.save(update_fields=['telegram_id', 'telegram_username', 'telegram_metadata', 'updated_at'])
    return profile.user


def user_access(user, workflow: str, *, group_configuration=None) -> dict:
    """Return canonical Mini App roles and scopes from active AccessGrants.

    Django Groups remain available for Django Admin permission bundles and
    never grant Mini App access. Active AccessGrants are the normal authority
    path. An active Django Superuser is the explicitly approved technical
    break-glass exception and receives every code-owned role without branch or
    product limits; callers still receive the real actor identity for audit.
    """
    from core.models import AccessGrant, EmergencyAccessGrant
    from django.utils import timezone
    from core.services.access_policies import WORKFLOW_ROLES, canonical_access_role
    if not user or not user.is_active:
        return {'authorized': False, 'roles': [], 'branches': [], 'products': [], 'grants': []}
    if user.is_superuser:
        return {
            'authorized': True,
            'roles': [role for role, _label in WORKFLOW_ROLES.get(workflow, ())],
            'branches': [],
            'products': [],
            'grants': [],
            'emergency_grants': [],
            'technical_override': True,
        }
    grants = AccessGrant.objects.filter(user=user, workflow=workflow, active=True)
    database_group = database_group_configuration(group_configuration)
    if group_configuration is not None:
        if database_group is None:
            grants = grants.filter(group_configuration__isnull=True)
        else:
            grants = grants.filter(group_configuration__in=[None, database_group])
    grants = list(grants.select_related('group_configuration'))
    emergency_grants = EmergencyAccessGrant.objects.filter(
        user=user, workflow=workflow, revoked_at__isnull=True, expires_at__gt=timezone.now(),
    )
    if group_configuration is not None:
        if database_group is None:
            emergency_grants = emergency_grants.filter(group_configuration__isnull=True)
        else:
            emergency_grants = emergency_grants.filter(group_configuration__in=[None, database_group])
    emergency_grants = list(emergency_grants.select_related('group_configuration'))
    grant_roles = {
        canonical_access_role(workflow, grant.role)
        for grant in [*grants, *emergency_grants]
        if grant.role
    }
    roles = grant_roles
    return {
        'authorized': bool(grants or emergency_grants),
        'roles': sorted(roles),
        'branches': sorted({grant.branch for grant in [*grants, *emergency_grants] if grant.branch}),
        'products': sorted({grant.product for grant in [*grants, *emergency_grants] if grant.product}),
        'grants': [*grants, *emergency_grants],
        'emergency_grants': emergency_grants,
    }


def database_group_configuration(group_configuration):
    """Resolve runtime GroupConfig values to their database configuration row."""
    if group_configuration is None:
        return None
    from core.models import GroupSheetConfiguration
    if isinstance(group_configuration, GroupSheetConfiguration):
        return group_configuration
    group_id = str(getattr(group_configuration, 'group_id', '') or '').strip()
    if not group_id:
        return None
    return GroupSheetConfiguration.objects.filter(group_id=group_id).first()


def username_for_telegram_id(telegram_id: str) -> str:
    return f'tg_{telegram_id}'
