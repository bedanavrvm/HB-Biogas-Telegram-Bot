
"""TAT Tracker Mini App workflow."""
from __future__ import annotations

import base64
import binascii
import csv
import hmac
import hashlib
import io
import json
import logging
import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qsl, urlencode
from typing import Any

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
import openpyxl

from core.models import TatTrackerApprovalCertificate, TatTrackerCase, TatTrackerEvent, TatTrackerStaffMember
from core.services.branches import DEFAULT_WORKFLOW_BRANCHES, global_branch_choices, workflow_branches as configured_workflow_branches
from core.services.identifiers import normalize_kenyan_phone, normalize_national_id
from core.services.sheets import get_sheets_service

logger = logging.getLogger(__name__)

_TAT_HEADER_CACHE_TTL_SECONDS = 300
_TAT_HEADER_CACHE: dict[tuple[str, str, str], tuple[float, list[Any]]] = {}

TAT_TRACKER_WORKFLOW_TYPE = 'tat_tracker'
TAT_TRACKER_HEADER_ROW = 2
TAT_FORM_TOKEN_SALT = 'tat-tracker-mini-app'

BRANCHES = DEFAULT_WORKFLOW_BRANCHES
DECISION_OPTIONS = ['Approved', 'Rejected', 'Deferred']
SANCTIONS_OPTIONS = ['Pending', 'Met', 'Not Met']
REGISTER_OPTIONS = ['10:00am', '1:00pm', '3:30pm']
REGISTER_APPROVED_OPTIONS = ['Approved', 'Pending']
STATUS_VALUES = ['Active', 'Disbursed', 'Rejected', 'Declined', 'Deferred', 'Stalled', 'Pending Docs']
TAT_BATCH_FORMAT_TEXT = (
    "TAT batch upload format\n\n"
    "Attach an Excel .xlsx or CSV file and send @bot /batch.\n\n"
    "Required headers:\n"
    "Product, Client Name, National ID, Phone, Branch, Amount\n\n"
    "Example row:\n"
    "business, Mary Wanjiku, 12345678, 254712345678, Nakuru, 25000\n\n"
    "Accepted products: business, logbook, mjengo, kilimo, micro_asset.\n"
    "The uploader must be configured as a BRO for the selected branch/product."
)
DEFAULT_TAT_TARGETS_MINUTES = {
    'business': {'total': 20160, 'stages': {}},
    'logbook': {'total': 20160, 'stages': {}},
    'mjengo': {'total': 20160, 'stages': {}},
    'kilimo': {'total': 20160, 'stages': {}},
    'micro_asset': {'total': 20160, 'stages': {}},
}
NEAR_SLA_RATIO = Decimal('0.8')
TAT_TARGET_MANAGER_ROLES = frozenset({'IT'})
TAT_HOME_PAGE_SIZE = 10


@dataclass(frozen=True)
class StageConfig:
    key: str
    label: str
    column: int
    role: str
    kind: str = 'timestamp'
    options: tuple[str, ...] = ()
    auto_timestamp_key: str = ''
    requires_signature_certificate: bool = False


@dataclass(frozen=True)
class ProductConfig:
    key: str
    label: str
    sheet_name: str
    case_prefix: str
    min_amount: Decimal
    max_amount: Decimal | None
    remarks_col: int
    status_col: int
    tat_start_col: int
    stage_columns: dict[str, int]
    stages: tuple[StageConfig, ...]


@dataclass(frozen=True)
class StageTatColumn:
    stage_key: str
    fallback_col: int
    aliases: tuple[str, ...]


BASE_STAGES_OTHER = (
    StageConfig('mpesa_to_admin', 'MPESA sent to Admin', 9, 'BRO'),
    StageConfig('mpesa_verified', 'MPESA verified and sent to CA', 10, 'ADMIN'),
    StageConfig('ca_analysis_sent', 'Credit analysis sent', 11, 'CA'),
    StageConfig('bro_response', 'BRO response to CA', 12, 'BRO'),
    StageConfig('bm_tat_request', 'BM TAT request sent', 13, 'BM'),
    StageConfig('tat_scheduled', 'HOCC scheduled', 14, 'SECRETARY'),
    StageConfig('tat_held', 'HOCC held', 15, 'SECRETARY'),
    StageConfig('decision', 'Decision', 16, 'CHAIR', 'dropdown', tuple(DECISION_OPTIONS), 'decision_ts'),
    StageConfig('minutes_shared', 'Minutes shared', 18, 'SECRETARY'),
    StageConfig('sanctions', 'Sanctions', 19, 'LOAN_APPROVER', 'dropdown', tuple(SANCTIONS_OPTIONS), 'sanctions_ts'),
    StageConfig('bro_applied', 'BRO applied on system', 21, 'BRO'),
    StageConfig('disbursement_register', 'Disbursement register', 22, 'ADMIN', 'dropdown', tuple(REGISTER_OPTIONS), 'register_ts'),
    StageConfig('register_approved', 'Register approved', 24, 'LOAN_APPROVER', 'dropdown', tuple(REGISTER_APPROVED_OPTIONS), 'register_approved_ts'),
    StageConfig('disbursement', 'Finance disbursement', 25, 'FINANCE'),
)

BASE_STAGES_LOGBOOK = (
    StageConfig('mpesa_to_admin', 'MPESA sent to Admin', 9, 'BRO'),
    StageConfig('mpesa_verified', 'MPESA verified and sent to CA', 10, 'ADMIN'),
    StageConfig('ca_analysis_sent', 'Credit analysis sent', 11, 'CA'),
    StageConfig('bro_response', 'BRO response to CA', 12, 'BRO'),
    StageConfig('valuation_ready', 'Valuation ready', 13, 'BM'),
    StageConfig('bm_tat_request', 'BM TAT request sent', 14, 'BM'),
    StageConfig('tat_scheduled', 'HOCC scheduled', 15, 'SECRETARY'),
    StageConfig('tat_held', 'HOCC held', 16, 'SECRETARY'),
    StageConfig('decision', 'Decision', 17, 'CHAIR', 'dropdown', tuple(DECISION_OPTIONS), 'decision_ts'),
    StageConfig('minutes_shared', 'Minutes shared', 19, 'SECRETARY'),
    StageConfig('sanctions', 'Sanctions', 20, 'LOAN_APPROVER', 'dropdown', tuple(SANCTIONS_OPTIONS), 'sanctions_ts'),
    StageConfig('bro_applied', 'BRO applied on system', 22, 'BRO'),
    StageConfig('disbursement_register', 'Disbursement register', 23, 'ADMIN', 'dropdown', tuple(REGISTER_OPTIONS), 'register_ts'),
    StageConfig('register_approved', 'Register approved', 25, 'LOAN_APPROVER', 'dropdown', tuple(REGISTER_APPROVED_OPTIONS), 'register_approved_ts'),
    StageConfig('disbursement', 'Finance disbursement', 26, 'FINANCE'),
)

BASE_STAGES_BUSINESS = (
    StageConfig('mpesa_to_admin', 'MPESA sent to Admin', 9, 'BRO'),
    StageConfig('mpesa_verified', 'MPESA verified and sent to CA', 10, 'ADMIN'),
    StageConfig('ca_analysis_sent', 'Credit analysis sent', 11, 'CA'),
    StageConfig('bro_response', 'BRO response to CA', 12, 'BRO'),
    StageConfig('bm_response', 'BM response to CA', 13, 'BM', requires_signature_certificate=True),
    StageConfig('bro_applied', 'BRO applied loan on system', 14, 'BRO'),
    StageConfig('disbursement_register', 'Disbursement register', 15, 'ADMIN', 'dropdown', tuple(REGISTER_OPTIONS), 'register_ts'),
    StageConfig('register_approved', 'Register approved', 17, 'LOAN_APPROVER', 'dropdown', tuple(REGISTER_APPROVED_OPTIONS), 'register_approved_ts'),
    StageConfig('disbursement', 'Finance disbursement', 18, 'FINANCE'),
)

PRODUCTS: dict[str, ProductConfig] = {
    'logbook': ProductConfig('logbook', 'Logbook', 'TRACKER-LOGBOOK', 'JBL-LB', Decimal('50000'), Decimal('500000'), 28, 27, 29, {'created': 8, 'decision_ts': 18, 'sanctions_ts': 21, 'register_ts': 24}, BASE_STAGES_LOGBOOK),
    'mjengo': ProductConfig('mjengo', 'Mjengo', 'TRACKER-MJENGO', 'JBL-MJ', Decimal('50000'), Decimal('300000'), 27, 26, 28, {'created': 8, 'decision_ts': 17, 'sanctions_ts': 20, 'register_ts': 23}, BASE_STAGES_OTHER),
    'kilimo': ProductConfig('kilimo', 'Kilimo', 'TRACKER-KILIMO', 'JBL-KI', Decimal('50000'), Decimal('300000'), 27, 26, 28, {'created': 8, 'decision_ts': 17, 'sanctions_ts': 20, 'register_ts': 23}, BASE_STAGES_OTHER),
    'micro_asset': ProductConfig('micro_asset', 'Micro Asset', 'TRACKER-MICRO-ASSET', 'JBL-MA', Decimal('50000'), Decimal('300000'), 27, 26, 28, {'created': 8, 'decision_ts': 17, 'sanctions_ts': 20, 'register_ts': 23}, BASE_STAGES_OTHER),
    'business': ProductConfig('business', 'Business', 'TRACKER-Business', 'JBL-BS', Decimal('5000'), None, 20, 19, 21, {'created': 8, 'register_ts': 16}, BASE_STAGES_BUSINESS),
}


def _stage_tat_aliases(stage: StageConfig) -> tuple[str, ...]:
    label = stage.label
    return (
        f'{label} TAT Minutes',
        f'{label} TAT',
        f'{label} Lag',
        f'{label} Lag Minutes',
        f'{stage.key} TAT Minutes',
    )


STAGE_TAT_COLUMNS: dict[str, tuple[StageTatColumn, ...]] = {
    'logbook': tuple(
        StageTatColumn(stage.key, 31 + index, _stage_tat_aliases(stage))
        for index, stage in enumerate(BASE_STAGES_LOGBOOK)
    ),
    'mjengo': tuple(
        StageTatColumn(stage.key, 30 + index, _stage_tat_aliases(stage))
        for index, stage in enumerate(BASE_STAGES_OTHER)
    ),
    'kilimo': tuple(
        StageTatColumn(stage.key, 30 + index, _stage_tat_aliases(stage))
        for index, stage in enumerate(BASE_STAGES_OTHER)
    ),
    'micro_asset': tuple(
        StageTatColumn(stage.key, 30 + index, _stage_tat_aliases(stage))
        for index, stage in enumerate(BASE_STAGES_OTHER)
    ),
    'business': tuple(
        StageTatColumn(stage.key, 23 + index, _stage_tat_aliases(stage))
        for index, stage in enumerate(BASE_STAGES_BUSINESS)
    ),
}


def is_tat_tracker_workflow(group_config) -> bool:
    workflow = getattr(group_config, 'workflow', None) or {}
    return str(workflow.get('type') or '') == TAT_TRACKER_WORKFLOW_TYPE


def configured_products(workflow: dict | None = None) -> list[ProductConfig]:
    workflow = workflow or {}
    keys = workflow.get('products') or list(PRODUCTS.keys())
    return [PRODUCTS[key] for key in keys if key in PRODUCTS]


def workflow_branches(workflow: dict | None = None) -> list[str]:
    env_branches = str(getattr(settings, 'TAT_TRACKER_BRANCH_CHOICES', '') or '').strip()
    if env_branches:
        return configured_workflow_branches({'branches': env_branches}, default=global_branch_choices(), replace_stale_defaults=True)
    return configured_workflow_branches(workflow, default=global_branch_choices(), replace_stale_defaults=True)


def create_tat_form_token(group_id: str) -> str:
    return signing.dumps({'group_id': str(group_id)}, salt=TAT_FORM_TOKEN_SALT)


def validate_tat_form_token(token: str, group_id: str) -> tuple[bool, str]:
    if not token:
        return False, 'Form token is missing. Open the tracker again from Telegram.'
    max_age = int(getattr(settings, 'TAT_TRACKER_WEBAPP_AUTH_MAX_AGE_SECONDS', 86400))
    try:
        payload = signing.loads(token, salt=TAT_FORM_TOKEN_SALT, max_age=max_age if max_age > 0 else None)
    except signing.SignatureExpired:
        return False, 'Form token has expired. Open the tracker again from Telegram.'
    except signing.BadSignature:
        return False, 'Form token is invalid. Open the tracker again from Telegram.'
    if str(payload.get('group_id', '')) != str(group_id):
        return False, 'Form token does not match this group.'
    return True, ''


def build_tat_tracker_url(group_id: str) -> str:
    base_url = getattr(settings, 'APP_BASE_URL', '').rstrip('/')
    if not base_url:
        return ''
    return f"{base_url}/tat-tracker/?" + urlencode({'group_id': str(group_id), 'token': create_tat_form_token(group_id)})


def build_tat_tracker_mini_app_url(group_id: str) -> str:
    bot_username = str(getattr(settings, 'TELEGRAM_BOT_USERNAME', '') or '').strip().lstrip('@')
    short_name = str(getattr(settings, 'TAT_TRACKER_MINI_APP_SHORT_NAME', '') or '').strip().strip('/')
    if not bot_username or not short_name:
        return ''
    return f"https://t.me/{bot_username}/{short_name}?startapp={create_tat_start_param(group_id)}"


def build_tat_tracker_launcher_url(group_id: str) -> str:
    """Return a durable group launcher URL for a pinned Telegram message."""
    bot_username = str(getattr(settings, 'TELEGRAM_BOT_USERNAME', '') or '').strip().lstrip('@')
    short_name = str(getattr(settings, 'TAT_TRACKER_MINI_APP_SHORT_NAME', '') or '').strip().strip('/')
    if not bot_username or not short_name:
        return ''
    return f"https://t.me/{bot_username}/{short_name}?startapp={create_tat_launcher_start_param(group_id)}"


def create_tat_start_param(group_id: str) -> str:
    payload = {'group_id': str(group_id), 'token': create_tat_form_token(group_id)}
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode('utf-8')).decode('ascii')
    return encoded.rstrip('=')


def create_tat_launcher_start_param(group_id: str) -> str:
    """Create the non-expiring locator used only by the pinned JBL Apps message."""
    payload = {'group_id': str(group_id), 'launcher': 'jbl_apps'}
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode('utf-8')).decode('ascii')
    return encoded.rstrip('=')


def decode_tat_start_param(start_param: str) -> dict[str, str]:
    value = str(start_param or '').strip()
    if not value:
        return {}
    padding = '=' * (-len(value) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode((value + padding).encode('ascii')).decode('utf-8'))
    except (binascii.Error, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    group_id = str(payload.get('group_id', '')).strip()
    token = str(payload.get('token', '')).strip()
    if str(payload.get('launcher', '')).strip() == 'jbl_apps' and group_id:
        return {'group_id': group_id, 'token': ''}
    if not group_id or not token:
        return {}
    return {'group_id': group_id, 'token': token}


def validate_tat_telegram_webapp_init_data(init_data: str) -> tuple[bool, str, dict]:
    if not getattr(settings, 'TAT_TRACKER_WEBAPP_REQUIRE_TELEGRAM_AUTH', True):
        return True, '', {}
    bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    if not bot_token:
        return False, 'TELEGRAM_BOT_TOKEN is not configured.', {}
    if not init_data:
        return False, 'Telegram Mini App authentication data is missing.', {}
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop('hash', '')
    if not received_hash:
        return False, 'Telegram Mini App hash is missing.', {}
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret_key = hmac.new(b'WebAppData', bot_token.encode('utf-8'), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode('utf-8'), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        return False, 'Telegram Mini App authentication failed.', {}
    max_age = int(getattr(settings, 'TAT_TRACKER_WEBAPP_AUTH_MAX_AGE_SECONDS', 86400))
    auth_date = pairs.get('auth_date')
    if auth_date and max_age > 0:
        try:
            if time.time() - int(auth_date) > max_age:
                return False, 'Telegram Mini App authentication expired.', {}
        except ValueError:
            return False, 'Telegram Mini App auth_date is invalid.', {}
    user_payload = {}
    if pairs.get('user'):
        try:
            user_payload = json.loads(pairs['user'])
        except json.JSONDecodeError:
            user_payload = {}
    return True, '', user_payload if isinstance(user_payload, dict) else {}


def staff_user_for_payload(group_config, user_payload: dict, fallback_name: str = '') -> dict:
    workflow = getattr(group_config, 'workflow', None) or {}
    staff = workflow.get('staff') or []
    telegram_id = str(user_payload.get('id') or '').strip()
    username = str(user_payload.get('username') or '').strip().lower().lstrip('@')
    full_name = _telegram_name(user_payload) or fallback_name or username or telegram_id or 'Unknown user'
    for row in staff:
        if not isinstance(row, dict) or row.get('active') is False:
            continue
        row_id = str(row.get('telegram_user_id') or row.get('telegram_id') or '').strip()
        row_username = str(row.get('telegram_username') or row.get('username') or '').strip().lower().lstrip('@')
        if (telegram_id and row_id == telegram_id) or (username and row_username == username):
            roles = _normalize_list(row.get('roles') or row.get('role'))
            return {'authorized': True, 'telegram_id': telegram_id, 'username': username, 'name': str(row.get('name') or full_name).strip(), 'roles': roles or ['BRO'], 'branches': _normalize_list(row.get('branches') or row.get('branch')), 'products': _normalize_list(row.get('products') or row.get('sheets'))}
    if workflow.get('allow_unconfigured_users'):
        return {'authorized': True, 'telegram_id': telegram_id, 'username': username, 'name': full_name, 'roles': _normalize_list(workflow.get('default_roles')) or ['BRO'], 'branches': [], 'products': []}
    return {'authorized': False, 'telegram_id': telegram_id, 'username': username, 'name': full_name, 'roles': [], 'branches': [], 'products': [], 'reason': 'Your Telegram account is not configured for the TAT Tracker. Ask admin to add you under workflow.staff.'}


def configured_bro_names(workflow: dict | None) -> list[str]:
    """Return active BRO names configured for the tracker group."""
    names = {
        str(row.get('name') or '').strip()
        for row in (workflow or {}).get('staff') or []
        if isinstance(row, dict)
        and row.get('active') is not False
        and 'BRO' in _normalize_list(row.get('roles') or row.get('role'))
        and str(row.get('name') or '').strip()
    }
    return sorted(names, key=str.casefold)
def bootstrap(group_config, user_payload: dict) -> dict:
    user = staff_user_for_payload(group_config, user_payload)
    workflow = getattr(group_config, 'workflow', None) or {}
    if not user['authorized']:
        return {'authorized': False, 'user': user, 'reason': user.get('reason', 'Unauthorized')}
    products = [serialize_product(product) for product in _allowed_products(workflow, user)]
    home = home_data(group_config, user)
    return {
        'authorized': True,
        'user': public_user(user),
        'products': products,
        'branches': _allowed_branches(workflow, user),
        'bro_names': configured_bro_names(workflow),
        'statuses': STATUS_VALUES,
        'recent': home['recent'],
        'action_required': home['action_required'],
        'pagination': home['pagination'],
    }


def home_data(
    group_config,
    user: dict,
    *,
    action_offset: int = 0,
    recent_offset: int = 0,
    page_size: int = TAT_HOME_PAGE_SIZE,
    product_key: str = '',
    branch: str = '',
) -> dict:
    """Return independently paginated home lists for the TAT Mini App."""
    workflow = getattr(group_config, 'workflow', None) or {}
    queryset = TatTrackerCase.objects.filter(group_id=str(group_config.group_id))
    allowed_keys = [p.key for p in _allowed_products(workflow, user)]
    if allowed_keys:
        queryset = queryset.filter(product_key__in=allowed_keys)
    selected_product = str(product_key or '').strip()
    if selected_product:
        if selected_product in allowed_keys:
            queryset = queryset.filter(product_key=selected_product)
        else:
            queryset = queryset.none()
    allowed_branches = _allowed_branches(workflow, user)
    selected_branch = str(branch or '').strip()
    if selected_branch:
        if selected_branch in allowed_branches:
            queryset = queryset.filter(branch=selected_branch)
        else:
            queryset = queryset.none()
    action_offset = max(0, int(action_offset or 0))
    recent_offset = max(0, int(recent_offset or 0))
    page_size = max(1, min(int(page_size or TAT_HOME_PAGE_SIZE), 50))

    recent_total = queryset.count()
    recent_cases = queryset.order_by('-created_at')[recent_offset:recent_offset + page_size]
    recent = [serialize_case_summary(case, user, workflow=workflow) for case in recent_cases]

    actionable_cases = []
    for case in queryset.exclude(status__in=['Disbursed', 'Rejected', 'Declined']).order_by('-updated_at'):
        next_stage = next_action(case)
        if next_stage and can_user_edit_stage(user, case, next_stage):
            actionable_cases.append((case, next_stage))
    action_total = len(actionable_cases)
    action_required = [
        serialize_case_summary(case, user, next_stage=next_stage, workflow=workflow)
        for case, next_stage in actionable_cases[action_offset:action_offset + page_size]
    ]
    return {
        'recent': recent,
        'action_required': action_required,
        'pagination': {
            'recent': pagination_payload(recent_offset, page_size, recent_total, len(recent)),
            'action_required': pagination_payload(action_offset, page_size, action_total, len(action_required)),
        },
    }


def pagination_payload(offset: int, page_size: int, total: int, returned: int) -> dict:
    return {
        'offset': offset,
        'page_size': page_size,
        'total': total,
        'has_more': offset + returned < total,
    }


def search_cases(group_config, user: dict, query: str) -> list[dict]:
    q = str(query or '').strip()
    if len(q) < 2:
        return []
    workflow = getattr(group_config, 'workflow', None) or {}
    normalized_id = normalize_national_id(q)
    normalized_phone = normalize_kenyan_phone(q)
    query = Q(case_id__icontains=q) | Q(client_name__icontains=q) | Q(branch__icontains=q) | Q(bro_name__icontains=q)
    if normalized_id:
        query |= Q(national_id=normalized_id)
    if normalized_phone:
        query |= Q(primary_phone=normalized_phone)
    queryset = TatTrackerCase.objects.filter(group_id=str(group_config.group_id)).filter(query)
    allowed_keys = [p.key for p in _allowed_products(workflow, user)]
    if allowed_keys:
        queryset = queryset.filter(product_key__in=allowed_keys)
    return [serialize_case_summary(case, user, workflow=workflow) for case in queryset.order_by('-updated_at')[:25]]


def get_case_detail(group_config, user: dict, case_id: str) -> dict:
    case = TatTrackerCase.objects.get(group_id=str(group_config.group_id), case_id=str(case_id))
    return serialize_case_detail(case, user, workflow=getattr(group_config, 'workflow', None) or {})


@transaction.atomic
def create_case(group_config, user: dict, payload: dict) -> dict:
    product = product_by_key(str(payload.get('product_key') or payload.get('product') or ''))
    workflow = getattr(group_config, 'workflow', None) or {}
    if product not in _allowed_products(workflow, user):
        raise ValueError('You do not have access to this product.')
    client_name = str(payload.get('client_name') or '').strip().upper()
    national_id = normalize_national_id(payload.get('national_id'))
    primary_phone = normalize_kenyan_phone(payload.get('primary_phone'))
    branch = str(payload.get('branch') or '').strip()
    bro_name = str(payload.get('bro_name') or user.get('name') or '').strip()
    amount = parse_amount(payload.get('amount'))
    if not client_name:
        raise ValueError('Client name is required.')
    if not re.fullmatch(r'\d{7,8}', national_id):
        raise ValueError('ID number must be 7 or 8 digits.')
    if not primary_phone:
        raise ValueError('Enter a valid Kenyan phone number.')
    if branch not in _allowed_branches(workflow, user):
        raise ValueError('Select a valid branch.')
    validate_amount(product, amount)
    create_request_id = normalize_create_request_id(payload.get('client_request_id') or payload.get('create_request_id') or payload.get('request_id'))
    if create_request_id:
        existing = TatTrackerCase.objects.select_for_update().filter(
            group_id=str(group_config.group_id),
            create_request_id=create_request_id,
        ).first()
        if existing:
            return serialize_case_detail(existing, user, workflow=workflow)
    case_id = next_case_id(group_config, product)
    now = timezone.now()
    case = TatTrackerCase.objects.create(
        group_id=str(group_config.group_id), sheet_id=str(group_config.sheet_id or ''), sheet_name=product.sheet_name,
        create_request_id=create_request_id,
        case_id=case_id, product_key=product.key, product_label=product.label, client_name=client_name,
        national_id=national_id, primary_phone=primary_phone,
        branch=branch, bro_name=bro_name, amount=amount, stage_values={'created': now.isoformat()},
        status='Active', current_stage=(product.stages[0].key if product.stages else ''),
        created_by=user.get('name', ''), created_by_telegram_id=user.get('telegram_id', ''), last_updated_by=user.get('name', ''),
    )
    TatTrackerEvent.objects.create(case=case, group_id=case.group_id, actor_name=user.get('name', ''), actor_telegram_id=user.get('telegram_id', ''), actor_role=','.join(user.get('roles') or []), stage_key='created', stage_label='Case Created', new_value=format_datetime(now), source='mini_app', sheet_name=case.sheet_name)
    if payload.get('_defer_sheet_sync'):
        return serialize_case_detail(case, user, workflow=workflow)
    sync_case_to_sheet(group_config, case)
    if not case.row_number:
        raise RuntimeError('TAT tracker sheet sync did not return a row number. Case was not saved.')
    return serialize_case_detail(case, user, workflow=workflow)


def tat_batch_format_message() -> str:
    return TAT_BATCH_FORMAT_TEXT


def process_tat_batch_upload(
    group_config,
    batch_text: str,
    *,
    user_payload: dict,
    telegram_message_id: str,
    sender: str = '',
) -> dict:
    user = staff_user_for_payload(group_config, user_payload, fallback_name=sender)
    if not user.get('authorized'):
        return {
            'status': 'command',
            'reply_text': user.get('reason') or 'Your Telegram account is not configured for the TAT Tracker.',
        }
    roles = {str(role).upper() for role in user.get('roles') or []}
    if 'BRO' not in roles and 'IT' not in roles:
        return {
            'status': 'command',
            'reply_text': 'Only configured BRO users can upload TAT batches.',
        }

    try:
        rows = parse_tat_batch_rows(batch_text)
    except ValueError as exc:
        return {
            'status': 'command',
            'reply_text': f"{exc}\n\n{TAT_BATCH_FORMAT_TEXT}",
        }
    if not rows:
        return {'status': 'command', 'reply_text': TAT_BATCH_FORMAT_TEXT}

    return process_tat_batch_rows(
        group_config,
        rows,
        user=user,
        telegram_message_id=telegram_message_id,
        sender=sender,
    )


def process_tat_batch_file(
    group_config,
    *,
    filename: str,
    content: bytes,
    user_payload: dict,
    telegram_message_id: str,
    sender: str = '',
) -> dict:
    user = staff_user_for_payload(group_config, user_payload, fallback_name=sender)
    if not user.get('authorized'):
        return {
            'status': 'command',
            'reply_text': user.get('reason') or 'Your Telegram account is not configured for the TAT Tracker.',
        }
    roles = {str(role).upper() for role in user.get('roles') or []}
    if 'BRO' not in roles and 'IT' not in roles:
        return {
            'status': 'command',
            'reply_text': 'Only configured BRO users can upload TAT batches.',
        }

    try:
        rows = parse_tat_batch_file(filename, content)
    except ValueError as exc:
        return {
            'status': 'command',
            'reply_text': f"{exc}\n\n{TAT_BATCH_FORMAT_TEXT}",
        }
    if not rows:
        return {'status': 'command', 'reply_text': TAT_BATCH_FORMAT_TEXT}

    return process_tat_batch_rows(
        group_config,
        rows,
        user=user,
        telegram_message_id=telegram_message_id,
        sender=sender,
    )


def process_tat_batch_rows(
    group_config,
    rows: list[dict],
    *,
    user: dict,
    telegram_message_id: str,
    sender: str = '',
) -> dict:
    imported = 0
    duplicates = 0
    failed = 0
    errors = []
    case_ids = []
    created_cases = []
    for row in rows:
        payload = dict(row['payload'])
        payload['bro_name'] = user.get('name') or sender or payload.get('bro_name') or ''
        payload['client_request_id'] = f"tat-batch:{group_config.group_id}:{telegram_message_id}:{row['line_number']}"
        payload['_defer_sheet_sync'] = True
        try:
            before_count = TatTrackerCase.objects.filter(group_id=str(group_config.group_id)).count()
            result = create_case(group_config, user, payload)
            after_count = TatTrackerCase.objects.filter(group_id=str(group_config.group_id)).count()
        except Exception as exc:
            failed += 1
            errors.append(f"Line {row['line_number']}: {exc}")
            continue

        summary = result.get('summary') or {}
        case_ids.append(summary.get('case_id') or '')
        if after_count == before_count:
            duplicates += 1
        else:
            imported += 1
            case_id = summary.get('case_id') or ''
            if case_id:
                created_cases.append(TatTrackerCase.objects.get(group_id=str(group_config.group_id), case_id=case_id))

    sync_result = sync_tat_batch_created_cases(group_config, created_cases)
    if sync_result['failed']:
        errors.extend(sync_result['failed'][:8])

    reply_lines = [
        'TAT batch processed.',
        f'Rows received: {len(rows)}',
        f'Created: {imported}',
        f'Already imported: {duplicates}',
        f'Synced to sheet: {sync_result["synced"]}',
        f'Failed: {failed}',
    ]
    visible_case_ids = [case_id for case_id in case_ids if case_id][:8]
    if visible_case_ids:
        reply_lines.append('Case IDs: ' + ', '.join(visible_case_ids))
    if errors:
        reply_lines.append('')
        reply_lines.append('Issues:')
        reply_lines.extend(errors[:8])

    return {
        'status': 'tat_batch_processed',
        'total': len(rows),
        'created': imported,
        'duplicates': duplicates,
        'failed': failed,
        'errors': errors,
        'case_ids': case_ids,
        'reply_text': '\n'.join(reply_lines),
    }


def parse_tat_batch_file(filename: str, content: bytes) -> list[dict]:
    lower_filename = str(filename or '').lower()
    if lower_filename.endswith('.xlsx'):
        return parse_tat_batch_xlsx(content)
    if lower_filename.endswith('.csv'):
        return parse_tat_batch_csv(decode_tat_batch_csv(content))
    raise ValueError('TAT batch upload only supports .xlsx or .csv files.')


def parse_tat_batch_csv(csv_text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(csv_text))
    return rows_from_tat_batch_dicts(reader, line_offset=1)


def parse_tat_batch_xlsx(content: bytes) -> list[dict]:
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError('Could not read the Excel workbook. Save it as .xlsx and retry.') from exc
    worksheet = workbook.worksheets[0]
    header_row = None
    headers = []
    for row_number, row in enumerate(worksheet.iter_rows(min_row=1, max_row=10, values_only=True), start=1):
        values = [str(value or '').strip() for value in row]
        if required_tat_batch_fields_present(values):
            header_row = row_number
            headers = values
            break
    if not header_row:
        raise ValueError('Excel file is missing required headers: Product, Client Name, National ID, Phone, Branch, Amount.')

    dict_rows = []
    for row_number, row in enumerate(worksheet.iter_rows(min_row=header_row + 1, values_only=True), start=header_row + 1):
        if not any(str(value or '').strip() for value in row):
            continue
        values = {
            headers[index]: row[index] if index < len(row) else ''
            for index in range(len(headers))
        }
        values['__line_number'] = row_number
        dict_rows.append(values)
    return rows_from_tat_batch_dicts(dict_rows)


def decode_tat_batch_csv(content: bytes) -> str:
    for encoding in ('utf-8-sig', 'utf-8', 'cp1252'):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError('Could not read the CSV text encoding. Export it as UTF-8 CSV and retry.')


def rows_from_tat_batch_dicts(dict_rows, *, line_offset: int = 0) -> list[dict]:
    rows = []
    for index, row in enumerate(dict_rows, start=1):
        normalized = {normalize_tat_batch_header(key): value for key, value in dict(row or {}).items()}
        line_number = int(normalized.get('line_number') or index + line_offset)
        payload = {
            'product_key': normalize_tat_batch_product(normalized.get('product')),
            'client_name': normalized.get('client_name') or '',
            'national_id': normalized.get('national_id') or '',
            'primary_phone': normalized.get('phone') or '',
            'branch': normalized.get('branch') or '',
            'amount': normalized.get('amount') or '',
        }
        if not any(str(value or '').strip() for value in payload.values()):
            continue
        missing = [
            label
            for key, label in TAT_BATCH_REQUIRED_FIELDS.items()
            if not str(payload.get(key) or '').strip()
        ]
        if missing:
            raise ValueError(f"Line {line_number}: missing required field(s): {', '.join(missing)}.")
        rows.append({'line_number': line_number, 'payload': payload})
    return rows


TAT_BATCH_REQUIRED_FIELDS = {
    'product_key': 'Product',
    'client_name': 'Client Name',
    'national_id': 'National ID',
    'primary_phone': 'Phone',
    'branch': 'Branch',
    'amount': 'Amount',
}


def required_tat_batch_fields_present(headers: list[str]) -> bool:
    normalized = {normalize_tat_batch_header(header) for header in headers}
    return {'product', 'client_name', 'national_id', 'phone', 'branch', 'amount'}.issubset(normalized)


def normalize_tat_batch_header(value: str) -> str:
    key = re.sub(r'[^a-z0-9]+', '_', str(value or '').strip().lower()).strip('_')
    aliases = {
        'product_key': 'product',
        'product_type': 'product',
        'customer_name': 'client_name',
        'name': 'client_name',
        'client': 'client_name',
        'id': 'national_id',
        'id_number': 'national_id',
        'national_id_number': 'national_id',
        'phone_number': 'phone',
        'primary_phone': 'phone',
        'mobile': 'phone',
        'loan_amount': 'amount',
    }
    return aliases.get(key, key)


def parse_tat_batch_rows(batch_text: str) -> list[dict]:
    rows = []
    for line_number, raw_line in enumerate(str(batch_text or '').splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if line.lower().startswith(('product |', 'product,', 'tat batch upload format')):
            continue
        parts = split_tat_batch_line(line)
        if len(parts) != 6:
            raise ValueError(
                f"Line {line_number}: expected 6 fields: product | client name | national id | phone | branch | amount."
            )
        product, client_name, national_id, phone, branch, amount = parts
        rows.append({
            'line_number': line_number,
            'payload': {
                'product_key': normalize_tat_batch_product(product),
                'client_name': client_name,
                'national_id': national_id,
                'primary_phone': phone,
                'branch': branch,
                'amount': amount,
            },
        })
    return rows


def split_tat_batch_line(line: str) -> list[str]:
    delimiter = '|' if '|' in line else ','
    return [part.strip() for part in line.split(delimiter)]


def normalize_tat_batch_product(value: str) -> str:
    key = str(value or '').strip().lower().replace('-', '_').replace(' ', '_')
    aliases = {
        'microasset': 'micro_asset',
        'micro': 'micro_asset',
        'sme': 'business',
    }
    return aliases.get(key, key)


def sync_tat_batch_created_cases(group_config, cases: list[TatTrackerCase]) -> dict:
    result = {'synced': 0, 'failed': []}
    if not cases:
        return result
    cases_by_product: dict[str, list[TatTrackerCase]] = {}
    for case in cases:
        cases_by_product.setdefault(case.product_key, []).append(case)

    for product_key, product_cases in cases_by_product.items():
        product = product_by_key(product_key)
        service = get_sheets_service(sheet_id=group_config.sheet_id, sheet_name=product.sheet_name)
        if not service.is_available():
            error = 'Google Sheets service unavailable.'
            for case in product_cases:
                case.sync_error = error
                case.save(update_fields=['sync_error', 'updated_at'])
                result['failed'].append(f'{case.case_id}: {error}')
            continue
        sheet = service._sheet
        try:
            headers = cached_tat_sheet_headers(group_config, product, sheet)
            validate_tracker_identity_headers(headers)
            rows = [
                build_tat_sheet_row_data(group_config, case, product, headers)
                for case in product_cases
            ]
            append_result = append_tat_batch_rows(sheet, rows)
            start_row = row_number_from_update_result(append_result)
            now = timezone.now()
            for index, case in enumerate(product_cases):
                if start_row:
                    case.row_number = start_row + index
                case.sheet_name = product.sheet_name
                case.last_synced_at = now
                case.sync_error = ''
                case.save(update_fields=['row_number', 'sheet_name', 'last_synced_at', 'sync_error', 'updated_at'])
                result['synced'] += 1
        except Exception as exc:
            logger.exception('TAT batch sheet sync failed for product %s', product_key)
            error = str(exc)
            for case in product_cases:
                case.sync_error = error
                case.save(update_fields=['sync_error', 'updated_at'])
                result['failed'].append(f'{case.case_id}: {error}')
    return result


def append_tat_batch_rows(sheet, rows: list[list[Any]]) -> Any:
    if not rows:
        return None
    if hasattr(sheet, 'append_rows'):
        return sheet.append_rows(rows, value_input_option='USER_ENTERED')
    start_row = next_sheet_row(sheet)
    width = max(len(row) for row in rows)
    sheet.update(
        f'A{start_row}:{column_letter(width)}{start_row + len(rows) - 1}',
        rows,
        value_input_option='USER_ENTERED',
    )
    return {'updates': {'updatedRange': f'A{start_row}:{column_letter(width)}{start_row + len(rows) - 1}'}}


@transaction.atomic
def update_case(group_config, user: dict, case_id: str, updates: list[dict]) -> dict:
    workflow = getattr(group_config, 'workflow', None) or {}
    case = TatTrackerCase.objects.select_for_update().get(group_id=str(group_config.group_id), case_id=str(case_id))
    if not updates:
        raise ValueError('No updates were submitted.')
    for item in updates:
        apply_update(case, user, item)
    next_stage = next_action(case)
    case.current_stage = next_stage.key if next_stage else ''
    case.last_updated_by = user.get('name', '')
    case.save()
    sync_case_to_sheet(group_config, case)
    return serialize_case_detail(case, user, workflow=workflow)


def apply_update(case: TatTrackerCase, user: dict, item: dict) -> None:
    field = str(item.get('field') or '').strip()
    product = product_by_key(case.product_key)
    if field == 'remarks':
        old = case.remarks
        case.remarks = str(item.get('value') or '').strip()
        stage_key = 'remarks'
        event_label = 'Remarks / Delays'
        new = case.remarks
    else:
        stage = stage_by_key(product, field)
        if not stage:
            raise ValueError('Invalid stage submitted.')
        if not can_user_edit_stage(user, case, stage):
            raise ValueError(f'Your role cannot update {stage.label}.')
        if not previous_stages_complete(case, stage):
            raise ValueError(f'Complete the previous stage before {stage.label}.')
        old = case.stage_values.get(stage.key, '')
        if old and stage.kind != 'dropdown':
            raise ValueError(f'{stage.label} is already completed.')
        if stage.kind == 'timestamp':
            value = timezone.now().isoformat()
            new = format_datetime(timezone.now())
        elif stage.kind == 'dropdown':
            value = str(item.get('value') or '').strip()
            if value not in stage.options:
                raise ValueError(f'Select a valid value for {stage.label}.')
            if value == old:
                raise ValueError(f'{stage.label} is already set to {value}.')
            new = value
        else:
            value = str(item.get('value') or '').strip()
            new = value
        case.stage_values[stage.key] = value
        apply_side_effects(case, product, stage, value)
        stage_key = stage.key
        event_label = stage.label
    event = TatTrackerEvent.objects.create(case=case, group_id=case.group_id, actor_name=user.get('name', ''), actor_telegram_id=user.get('telegram_id', ''), actor_role=','.join(user.get('roles') or []), stage_key=stage_key, stage_label=event_label, old_value=str(old or ''), new_value=str(new or ''), source='mini_app', sheet_name=case.sheet_name, row_number=case.row_number)
    if signatures_enabled() and field != 'remarks' and stage.requires_signature_certificate:
        create_approval_certificate(case, event, user, stage)


def create_approval_certificate(case: TatTrackerCase, event: TatTrackerEvent, user: dict, stage: StageConfig) -> None:
    staff_member = TatTrackerStaffMember.objects.filter(
        group_configuration__group_id=case.group_id,
        telegram_user_id=str(user.get('telegram_id') or ''),
        active=True,
    ).first()
    if not staff_member or not staff_member.signing_national_id or not staff_member.signing_phone_number:
        raise ValueError('Your Branch Manager signing identity is incomplete. Ask an administrator to add your national ID and phone number.')
    TatTrackerApprovalCertificate.objects.get_or_create(
        event=event,
        defaults={
            'case': case,
            'staff_member': staff_member,
            'stage_key': stage.key,
            'external_reference': f'TAT-{case.id}-{stage.key}-v1',
        },
    )


def apply_side_effects(case: TatTrackerCase, product: ProductConfig, stage: StageConfig, value: str) -> None:
    now = timezone.now().isoformat()
    if stage.key == 'bro_applied' and product.stage_columns.get('sanctions_ts') and case.stage_values.get('sanctions') != 'Met':
        raise ValueError('Sanctions must be marked Met before applying on system.')
    if stage.key == 'disbursement' and case.stage_values.get('register_approved') != 'Approved':
        raise ValueError('Register must be approved before disbursement.')
    if stage.auto_timestamp_key and value:
        case.stage_values.setdefault(stage.auto_timestamp_key, now)
    if stage.key == 'decision':
        if value == 'Rejected':
            case.status = 'Rejected'
        elif value == 'Deferred':
            case.status = 'Deferred'
        elif value == 'Approved' and case.status in {'Rejected', 'Deferred'}:
            case.status = 'Active'
    if stage.key == 'sanctions' and value == 'Not Met' and 'Sanctions Not Met' not in case.remarks:
        case.remarks = f"[{format_datetime(timezone.now())}: Sanctions Not Met - conditions unfulfilled] {case.remarks}".strip()
    if stage.key == 'disbursement':
        case.status = 'Disbursed'


def normalize_create_request_id(value: Any) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9_.:-]', '', str(value or '').strip())
    return cleaned[:128]


def next_case_id(group_config, product: ProductConfig) -> str:
    year = timezone.localdate().year
    prefix = f'{product.case_prefix}-{year}'
    existing = TatTrackerCase.objects.filter(group_id=str(group_config.group_id), case_id__startswith=prefix).values_list('case_id', flat=True)
    max_num = 0
    for case_id in existing:
        try:
            max_num = max(max_num, int(str(case_id).rsplit('-', 1)[-1]))
        except (TypeError, ValueError):
            continue
    return f'{prefix}-{max_num + 1:03d}'


def sync_case_to_sheet(group_config, case: TatTrackerCase) -> None:
    product = product_by_key(case.product_key)
    service = get_sheets_service(sheet_id=group_config.sheet_id, sheet_name=product.sheet_name)
    if not service.is_available():
        case.sync_error = 'Google Sheets service unavailable.'
        case.save(update_fields=['sync_error', 'updated_at'])
        raise RuntimeError(case.sync_error)
    sheet = service._sheet
    try:
        # TAT values are Django-calculated display columns. Keeping them out
        # of sheet formulas avoids delayed spreadsheet recalculation.
        headers = cached_tat_sheet_headers(group_config, product, sheet)
        validate_tracker_identity_headers(headers)
        row = case.row_number
        values = sheet.row_values(row) if row else []
        row_data = build_tat_sheet_row_data(group_config, case, product, headers, values)
        width = len(row_data)
        if row:
            sheet.update(f'A{row}:{column_letter(width)}{row}', [row_data], value_input_option='USER_ENTERED')
        else:
            row = append_case_row(sheet, row_data)
        case.row_number = row
        case.sheet_name = product.sheet_name
        case.last_synced_at = timezone.now()
        case.sync_error = ''
        case.save(update_fields=['row_number', 'sheet_name', 'last_synced_at', 'sync_error', 'updated_at'])
        if should_sync_secondary_sheets(group_config):
            try:
                sync_case_index(group_config, case)
            except Exception as exc:
                logger.warning('TAT tracker CASE_INDEX sync failed for %s: %s', case.case_id, exc, exc_info=True)
            try:
                sync_audit_log(group_config, case)
            except Exception as exc:
                logger.warning('TAT tracker AUDIT LOG sync failed for %s: %s', case.case_id, exc, exc_info=True)
    except Exception as exc:
        case.sync_error = str(exc)
        case.save(update_fields=['sync_error', 'updated_at'])
        logger.exception('TAT tracker sheet sync failed for %s', case.case_id)
        raise


def build_tat_sheet_row_data(
    group_config,
    case: TatTrackerCase,
    product: ProductConfig,
    headers: list[Any],
    existing_values: list[Any] | None = None,
) -> list[Any]:
    del group_config
    tat_columns = resolve_tat_sheet_columns(product, headers)
    width = max([product.tat_start_col + 1, *tat_columns.values()])
    row_data = [''] * width
    for idx, value in enumerate((existing_values or [])[:width], start=1):
        row_data[idx - 1] = value
    row_data[0] = case.case_id
    row_data[1] = case.client_name
    row_data[2] = case.national_id
    row_data[3] = case.primary_phone
    row_data[4] = case.branch
    row_data[5] = case.bro_name
    row_data[6] = float(case.amount or 0) if case.amount is not None else ''
    row_data[product.stage_columns['created'] - 1] = sheet_datetime(case.stage_values.get('created'))
    for stage in product.stages:
        if stage.key in case.stage_values:
            row_data[stage.column - 1] = sheet_value_for_stage(stage, case.stage_values.get(stage.key))
        if stage.auto_timestamp_key and stage.auto_timestamp_key in case.stage_values:
            col = product.stage_columns.get(stage.auto_timestamp_key)
            if col:
                row_data[col - 1] = sheet_datetime(case.stage_values.get(stage.auto_timestamp_key))
    row_data[product.status_col - 1] = case.status
    row_data[product.remarks_col - 1] = case.remarks
    tat_minutes = calculated_tat_minutes(case)
    tat_hours = calculated_tat_hours(case) if tat_minutes is not None else None
    tat_days = calculated_tat_days(case) if tat_minutes is not None else None
    row_data[product.tat_start_col - 1] = float(tat_hours) if tat_hours is not None else ''
    row_data[product.tat_start_col] = float(tat_days) if tat_days is not None else ''
    if tat_columns.get('total_minutes'):
        row_data[tat_columns['total_minutes'] - 1] = float(tat_minutes) if tat_minutes is not None else ''
    for stage in product.stages:
        col = tat_columns.get(stage.key)
        if col:
            minutes = stage_tat_minutes(case, stage)
            row_data[col - 1] = float(minutes) if minutes is not None else ''
    return row_data


def cached_tat_sheet_headers(group_config, product: ProductConfig, sheet) -> list[Any]:
    if not hasattr(sheet, 'row_values'):
        return []
    group_key = str(getattr(group_config, 'pk', '') or getattr(group_config, 'group_id', '') or '')
    cache_key = (group_key, str(group_config.sheet_id or ''), product.sheet_name)
    now = time.monotonic()
    cached = _TAT_HEADER_CACHE.get(cache_key)
    if cached and now - cached[0] < _TAT_HEADER_CACHE_TTL_SECONDS:
        return list(cached[1])
    headers = sheet.row_values(TAT_TRACKER_HEADER_ROW)
    _TAT_HEADER_CACHE[cache_key] = (now, list(headers))
    return headers


def resync_tat_tracker_cases(
    group_config,
    *,
    product_key: str = '',
    case_ids: list[str] | None = None,
    dry_run: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, object]:
    """Re-write linked TAT cases from Django without creating unknown rows.

    This is intentionally an explicit repair operation. Cases that do not have
    a stored tracker row are skipped, rather than appended, so an operator
    cannot accidentally duplicate a manually maintained spreadsheet row.
    """
    selected_product = str(product_key or '').strip()
    if selected_product and selected_product not in PRODUCTS:
        raise ValueError(f'Unknown TAT product: {selected_product}.')

    selected_case_ids = [str(case_id).strip() for case_id in (case_ids or []) if str(case_id).strip()]
    queryset = TatTrackerCase.objects.filter(group_id=str(group_config.group_id))
    if selected_product:
        queryset = queryset.filter(product_key=selected_product)
    if selected_case_ids:
        queryset = queryset.filter(case_id__in=selected_case_ids)

    linked_cases = queryset.filter(row_number__gt=0).order_by('product_key', 'case_id')
    total_candidates = linked_cases.count()
    selected_offset = max(0, int(offset or 0))
    skipped_unlinked = queryset.exclude(row_number__gt=0).count()
    if limit is not None:
        linked_cases = linked_cases[selected_offset:selected_offset + max(0, int(limit))]
    elif selected_offset:
        linked_cases = linked_cases[selected_offset:]
    candidates = list(linked_cases)
    result: dict[str, object] = {
        'total_candidates': total_candidates,
        'candidates': len(candidates),
        'synced': 0,
        'skipped_unlinked': skipped_unlinked,
        'failed': [],
        'offset': selected_offset,
        'next_offset': selected_offset + len(candidates) if selected_offset + len(candidates) < total_candidates else None,
    }
    if dry_run:
        return result

    for case in candidates:
        try:
            sync_case_to_sheet(group_config, case)
            result['synced'] = int(result['synced']) + 1
        except Exception as exc:
            logger.exception('TAT repair re-sync failed for %s', case.case_id)
            result['failed'].append({'case_id': case.case_id, 'error': str(exc)})
    return result


def resolve_tat_sheet_columns(product: ProductConfig, headers: list[Any]) -> dict[str, int]:
    normalized_headers = {
        normalize_header(header): index
        for index, header in enumerate(headers, start=1)
        if str(header or '').strip()
    }
    columns: dict[str, int] = {}
    total_col = first_matching_header(normalized_headers, ('TAT Minutes', 'Total TAT Minutes', 'Case TAT Minutes'))
    if total_col:
        columns['total_minutes'] = total_col
    for config in STAGE_TAT_COLUMNS.get(product.key, ()):
        columns[config.stage_key] = first_matching_header(normalized_headers, config.aliases) or config.fallback_col
    return columns


def first_matching_header(headers: dict[str, int], candidates: tuple[str, ...]) -> int | None:
    for candidate in candidates:
        col = headers.get(normalize_header(candidate))
        if col:
            return col
    return None


def normalize_header(value: Any) -> str:
    return re.sub(r'[^a-z0-9]+', '', str(value or '').strip().lower())


def validate_tracker_identity_headers(headers: list[Any]) -> None:
    if not any(str(header or '').strip() for header in headers):
        return
    expected = ('idnumber', 'phonenumber')
    actual = tuple(normalize_header(headers[index]) if len(headers) > index else '' for index in (2, 3))
    if actual != expected:
        raise ValueError('Tracker sheet row 2 must have ID NUMBER in column C and PHONE NUMBER in column D before cases can be synced.')


def append_case_row(sheet, row_data: list[Any]) -> int:
    result = None
    if hasattr(sheet, 'append_row'):
        result = sheet.append_row(row_data, value_input_option='USER_ENTERED')
    elif hasattr(sheet, 'append_rows'):
        result = sheet.append_rows([row_data], value_input_option='USER_ENTERED')
    else:
        row = next_sheet_row(sheet)
        sheet.update(f'A{row}:{column_letter(len(row_data))}{row}', [row_data], value_input_option='USER_ENTERED')
        return row
    row = row_number_from_update_result(result)
    if row:
        return row
    return next_sheet_row(sheet) - 1


def row_number_from_update_result(result: Any) -> int | None:
    if not isinstance(result, dict):
        return None
    updated_range = str((result.get('updates') or {}).get('updatedRange') or result.get('updatedRange') or '')
    match = re.search(r'![A-Z]+(\d+)(?::[A-Z]+(\d+))?$', updated_range)
    if not match:
        return None
    return int(match.group(1))


def signatures_enabled() -> bool:
    return bool(getattr(settings, 'TAT_TRACKER_SIGNATURES_ENABLED', False))


def should_sync_secondary_sheets(group_config) -> bool:
    workflow = getattr(group_config, 'workflow', None) or {}
    if 'sync_secondary_sheets' in workflow:
        return bool(workflow.get('sync_secondary_sheets'))
    return bool(getattr(settings, 'TAT_TRACKER_SYNC_SECONDARY_SHEETS', False))


def sync_case_index(group_config, case: TatTrackerCase) -> None:
    service = get_sheets_service(sheet_id=group_config.sheet_id, sheet_name='CASE_INDEX')
    if not service.is_available():
        return
    sheet = service._sheet
    rows = sheet.get_all_values()
    target = None
    for idx, row in enumerate(rows[1:], start=2):
        if row and row[0] == case.case_id:
            target = idx
            break
    if not target:
        target = max(len(rows) + 1, 2)
    sheet.update(f'A{target}:K{target}', [[case.case_id, case.sheet_name, case.row_number or '', case.client_name, case.national_id, case.primary_phone, case.branch, case.bro_name, case.status, sheet_datetime(case.stage_values.get('created')), timezone.localtime(timezone.now()).strftime('%d-%b-%Y %H:%M')]], value_input_option='USER_ENTERED')


def sync_audit_log(group_config, case: TatTrackerCase) -> None:
    unsynced = list(case.events.filter(synced_to_sheet=False).order_by('created_at'))
    if not unsynced:
        return
    service = get_sheets_service(sheet_id=group_config.sheet_id, sheet_name='AUDIT LOG')
    if not service.is_available():
        return
    sheet = service._sheet
    existing_count = max(len(sheet.get_all_values()), 1)
    rows = []
    for event in unsynced:
        rows.append([timezone.localtime(event.created_at).strftime('%d-%b-%Y %H:%M'), event.actor_name, case.sheet_name, case.case_id, case.row_number or '', event.stage_label or event.stage_key, event.new_value, '', event.source.upper()])
    if rows:
        start = existing_count + 1
        sheet.update(f'A{start}:I{start + len(rows) - 1}', rows, value_input_option='USER_ENTERED')
        TatTrackerEvent.objects.filter(id__in=[event.id for event in unsynced]).update(synced_to_sheet=True, synced_at=timezone.now(), sync_error='')


def calculated_tat_minutes(case: TatTrackerCase, now=None) -> Decimal | None:
    created = parse_iso_datetime((case.stage_values or {}).get('created'))
    if not created:
        return None
    end = overall_tat_end(case, now=now)
    return minutes_between(created, end)


def calculated_tat_hours(case: TatTrackerCase, now=None) -> Decimal | None:
    minutes = calculated_tat_minutes(case, now=now)
    if minutes is None:
        return None
    return (minutes / Decimal('60')).quantize(Decimal('0.01'))


def calculated_tat_days(case: TatTrackerCase, now=None) -> Decimal | None:
    minutes = calculated_tat_minutes(case, now=now)
    if minutes is None:
        return None
    return (minutes / Decimal('1440')).quantize(Decimal('0.01'))


def overall_tat_end(case: TatTrackerCase, now=None):
    values = case.stage_values or {}
    if case.status in {'Rejected', 'Declined'}:
        return parse_iso_datetime(values.get('decision_ts')) or parse_iso_datetime(values.get('decision')) or now or timezone.now()
    return parse_iso_datetime(values.get('disbursement')) or now or timezone.now()


def minutes_between(start, end) -> Decimal | None:
    if not start or not end:
        return None
    delta = end - start
    seconds = max(Decimal(str(delta.total_seconds())), Decimal('0'))
    return (seconds / Decimal('60')).quantize(Decimal('0.01'))


def stage_tat_minutes(case: TatTrackerCase, stage: StageConfig, now=None) -> Decimal | None:
    product = product_by_key(case.product_key)
    previous = previous_stage_timestamp(case, product, stage)
    if not previous:
        return None
    current = stage_completed_at(case, stage)
    if not current and next_action(case) and next_action(case).key == stage.key:
        current = now or timezone.now()
    return minutes_between(previous, current)


def previous_stage_timestamp(case: TatTrackerCase, product: ProductConfig, stage: StageConfig):
    previous = parse_iso_datetime((case.stage_values or {}).get('created'))
    for current in product.stages:
        if current.key == stage.key:
            return previous
        value = stage_completed_at(case, current)
        if value:
            previous = value
    return previous


def stage_completed_at(case: TatTrackerCase, stage: StageConfig):
    values = case.stage_values or {}
    timestamp = parse_iso_datetime(values.get(stage.auto_timestamp_key)) or parse_iso_datetime(values.get(stage.key))
    if timestamp:
        return timestamp
    if not stage.auto_timestamp_key or not values.get(stage.key) or not case.pk:
        return None
    event = case.events.filter(stage_key=stage.key).order_by('created_at').first()
    return event.created_at if event else None


def tat_targets_for_product(workflow: dict | None, product: ProductConfig) -> dict:
    workflow = workflow or {}
    configured = workflow.get('tat_targets_minutes') or {}
    product_targets = configured.get(product.key) or configured.get(product.sheet_name) or {}
    defaults = DEFAULT_TAT_TARGETS_MINUTES.get(product.key, {})
    return {
        'total': product_targets.get('total', defaults.get('total')),
        'stages': product_targets.get('stages') or defaults.get('stages') or {},
    }



def can_manage_tat_targets(user: dict | None) -> bool:
    """Return whether the staff member may change workflow-wide SLA targets."""
    roles = {str(role).strip().upper() for role in (user or {}).get('roles') or []}
    return bool(roles & TAT_TARGET_MANAGER_ROLES)


def tat_target_settings(workflow: dict | None) -> list[dict]:
    """Serialize the configured targets for the administrator Mini App form."""
    settings = []
    for product in configured_products(workflow):
        targets = tat_targets_for_product(workflow, product)
        settings.append({
            'key': product.key,
            'label': product.label,
            'total_minutes': targets.get('total') or '',
            'stages': [
                {
                    'key': stage.key,
                    'label': stage.label,
                    'target_minutes': (targets.get('stages') or {}).get(stage.key) or '',
                }
                for stage in product.stages
            ],
        })
    return settings


def _target_minutes_from_value(value: object, label: str) -> int | None:
    if value in (None, ''):
        return None
    try:
        minutes = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f'{label} must be a number of minutes.') from exc
    if minutes < 0 or minutes > Decimal('5256000'):
        raise ValueError(f'{label} must be between 0 and 5,256,000 minutes.')
    if minutes != minutes.to_integral_value():
        raise ValueError(f'{label} must use whole minutes.')
    return int(minutes)

def normalize_tat_target_settings(workflow: dict | None, payload: object) -> dict:
    """Validate Mini App target minutes and store canonical minute values."""
    submitted = payload if isinstance(payload, dict) else {}
    targets: dict[str, dict] = {}
    for product in configured_products(workflow):
        row = submitted.get(product.key) or {}
        if not isinstance(row, dict):
            raise ValueError(f'{product.label} targets are invalid.')
        product_targets: dict[str, object] = {'stages': {}}
        total = _target_minutes_from_value(row.get('total_minutes'), f'{product.label} total target')
        if total is not None:
            product_targets['total'] = total
        submitted_stages = row.get('stages') or {}
        if not isinstance(submitted_stages, dict):
            raise ValueError(f'{product.label} stage targets are invalid.')
        for stage in product.stages:
            minutes = _target_minutes_from_value(
                submitted_stages.get(stage.key),
                f'{product.label}: {stage.label} target',
            )
            if minutes is not None:
                product_targets['stages'][stage.key] = minutes
        if product_targets.get('total') is not None or product_targets['stages']:
            targets[product.key] = {
                key: value for key, value in product_targets.items()
                if key != 'stages' or value
            }
    return targets


def sync_tat_target_settings_to_sheet(group_config, workflow: dict | None) -> dict:
    """Write configured SLA targets to the Apps Script support tab.

    The tab is created on the first IT target save, so formatting does not
    depend on an administrator remembering to run a separate Apps Script setup.
    """
    if not getattr(group_config, 'sheet_id', ''):
        return {'status': 'not_configured'}
    service = get_sheets_service(sheet_id=group_config.sheet_id, sheet_name='TAT TARGETS')
    sheet = service.get_or_create_worksheet('TAT TARGETS', rows=500, cols=4)
    if sheet is None:
        return {'status': 'unavailable'}
    rows = []
    for product in tat_target_settings(workflow):
        if product['total_minutes']:
            rows.append([product['key'], '__total__', product['total_minutes'], str(NEAR_SLA_RATIO)])
        for stage in product['stages']:
            if stage['target_minutes']:
                rows.append([product['key'], stage['key'], stage['target_minutes'], str(NEAR_SLA_RATIO)])
    try:
        sheet.update('A1:D1', [['Product Key', 'Stage Key', 'Target Minutes', 'Near Ratio']], value_input_option='USER_ENTERED')
        sheet.batch_clear(['A2:D500'])
        if rows:
            sheet.update(f'A2:D{len(rows) + 1}', rows, value_input_option='USER_ENTERED')
        return {'status': 'synced'}
    except Exception as exc:
        logger.warning('TAT target sheet sync failed for group %s: %s', group_config.group_id, exc)
        return {'status': 'failed'}
@transaction.atomic
def update_tat_target_settings(group_config, user: dict, payload: object) -> dict:
    """Persist administrator-managed SLA targets and refresh the group registry."""
    if not can_manage_tat_targets(user):
        raise ValueError('Only IT staff can change SLA targets.')
    from core.models import GroupSheetConfiguration
    from core.services.group_config import GroupRegistry

    config = GroupSheetConfiguration.objects.select_for_update().get(group_id=str(group_config.group_id))
    workflow = dict(config.workflow or {})
    targets = normalize_tat_target_settings(workflow, payload)
    changed = workflow.get('tat_targets_minutes') != targets
    if changed:
        workflow['tat_targets_minutes'] = targets
        config.workflow = workflow
        config.save(update_fields=['workflow', 'updated_at'])
        GroupRegistry.get_instance().reload()
    active_workflow = workflow if changed else config.workflow
    return {
        'changed': changed,
        'targets': tat_target_settings(active_workflow),
        'sheet_sync': sync_tat_target_settings_to_sheet(group_config, active_workflow),
    }
def stage_target_minutes(workflow: dict | None, product: ProductConfig, stage: StageConfig) -> Decimal | None:
    value = (tat_targets_for_product(workflow, product).get('stages') or {}).get(stage.key)
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def total_target_minutes(workflow: dict | None, product: ProductConfig) -> Decimal | None:
    value = tat_targets_for_product(workflow, product).get('total')
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def sla_status(minutes: Decimal | None, target: Decimal | None) -> str:
    if minutes is None or target is None or target <= 0:
        return ''
    if minutes > target:
        return 'over'
    if minutes >= (target * NEAR_SLA_RATIO):
        return 'near'
    return 'within'


def resolve_case_sheet_row(sheet, case: TatTrackerCase) -> int:
    """Return the safest row for this case, even after manual sheet edits."""
    if case.row_number:
        try:
            current_id = str(sheet.cell(case.row_number, 1).value or '').strip()
        except Exception:
            current_id = ''
        if current_id == case.case_id:
            return case.row_number
    case_ids = sheet.col_values(1)
    for idx, value in enumerate(case_ids, start=1):
        if idx >= 5 and str(value or '').strip() == case.case_id:
            return idx
    return next_sheet_row(sheet)

def next_sheet_row(sheet) -> int:
    values = sheet.col_values(1)
    for idx in range(len(values), 4, -1):
        if str(values[idx - 1] or '').strip():
            return idx + 1
    return 5


def next_action(case: TatTrackerCase) -> StageConfig | None:
    product = product_by_key(case.product_key)
    if case.status in {'Disbursed', 'Rejected', 'Declined'}:
        return None
    for stage in product.stages:
        if not case.stage_values.get(stage.key):
            return stage
    return None


def previous_stages_complete(case: TatTrackerCase, stage: StageConfig) -> bool:
    product = product_by_key(case.product_key)
    for current in product.stages:
        if current.key == stage.key:
            return True
        if not case.stage_values.get(current.key):
            return False
        if signatures_enabled() and current.requires_signature_certificate and not case.approval_certificates.filter(stage_key=current.key, status='signed').exists():
            return False
    return True


def can_user_edit_stage(user: dict, case: TatTrackerCase, stage: StageConfig) -> bool:
    roles = {str(role).upper() for role in user.get('roles') or []}
    if 'IT' in roles:
        return True
    if stage.role.upper() not in roles:
        return False
    branches = user.get('branches') or []
    if branches and case.branch not in branches:
        return False
    products = user.get('products') or []
    if products and case.product_key not in products and case.sheet_name not in products:
        return False
    return True


def serialize_case_summary(case: TatTrackerCase, user: dict | None = None, next_stage: StageConfig | None = None, workflow: dict | None = None) -> dict:
    next_stage = next_stage or next_action(case)
    product = product_by_key(case.product_key)
    tat_minutes = calculated_tat_minutes(case)
    tat_hours = calculated_tat_hours(case) if tat_minutes is not None else None
    tat_days = calculated_tat_days(case) if tat_minutes is not None else None
    total_target = total_target_minutes(workflow, product)
    certificates = {certificate.stage_key: certificate.status for certificate in case.approval_certificates.all()}
    return {'case_id': case.case_id, 'product': case.product_label or product.label, 'product_key': case.product_key, 'client_name': case.client_name, 'national_id': case.national_id, 'primary_phone': case.primary_phone, 'branch': case.branch, 'bro_name': case.bro_name, 'amount': str(case.amount or ''), 'status': case.status, 'current_stage': case.current_stage, 'next_stage': next_stage.label if next_stage else '', 'next_stage_key': next_stage.key if next_stage else '', 'tat_minutes': str(tat_minutes) if tat_minutes is not None else '', 'tat_hours': str(tat_hours) if tat_hours is not None else '', 'tat_days': str(tat_days) if tat_days is not None else '', 'target_minutes': str(total_target) if total_target is not None else '', 'sla_status': sla_status(tat_minutes, total_target), 'certificate_statuses': certificates, 'updated_at': format_datetime(case.updated_at), 'created_at': format_datetime(case.created_at)}


def serialize_case_detail(case: TatTrackerCase, user: dict, workflow: dict | None = None) -> dict:
    product = product_by_key(case.product_key)
    fields = []
    for stage in product.stages:
        value = case.stage_values.get(stage.key, '')
        editable = previous_stages_complete(case, stage) and can_user_edit_stage(user, case, stage) and (not value or stage.kind == 'dropdown')
        tat_minutes = stage_tat_minutes(case, stage)
        target = stage_target_minutes(workflow, product, stage)
        certificate = case.approval_certificates.filter(stage_key=stage.key).first() if stage.requires_signature_certificate else None
        fields.append({'key': stage.key, 'label': stage.label, 'kind': stage.kind, 'value': display_stage_value(stage, value), 'editable': editable, 'options': list(stage.options), 'role': stage.role, 'locked_reason': '' if editable else lock_reason(case, user, stage), 'tat_minutes': str(tat_minutes) if tat_minutes is not None else '', 'target_minutes': str(target) if target is not None else '', 'sla_status': sla_status(tat_minutes, target), 'certificate_status': certificate.status if certificate else ''})
    events = [{'at': format_datetime(event.created_at), 'actor': event.actor_name, 'stage': event.stage_label, 'value': event.new_value, 'source': event.source} for event in case.events.order_by('-created_at')[:20]]
    return {'summary': serialize_case_summary(case, user, workflow=workflow), 'fields': fields, 'remarks': case.remarks, 'events': events}


def next_role_alert(group_config, case_data: dict | None) -> dict[str, str]:
    if not case_data:
        return {}
    workflow = getattr(group_config, 'workflow', None) or {}
    if workflow.get('stage_alerts_enabled') is False:
        return {}
    summary = case_data.get('summary') or {}
    next_stage_key = summary.get('next_stage_key') or ''
    if not next_stage_key:
        return {}
    try:
        product = product_by_key(summary.get('product_key') or '')
    except ValueError:
        return {}
    stage = stage_by_key(product, next_stage_key)
    if not stage:
        return {}
    role_label = role_display_name(stage.role)
    return {
        'role': stage.role,
        'role_label': role_label,
        'stage': stage.label,
        'text': (
            f"TAT action needed: {role_label}\n\n"
            f"Case: {summary.get('case_id', '')}\n"
            f"Client: {summary.get('client_name', '')}\n"
            f"Branch: {summary.get('branch', '')}\n"
            f"Next step: {stage.label}\n\n"
            "Please open the TAT Tracker and update this stage when done."
        ),
    }


def role_display_name(role: str) -> str:
    labels = {
        'BRO': 'BRO',
        'ADMIN': 'Admin',
        'CA': 'Credit Analyst',
        'BM': 'Branch Manager',
        'SECRETARY': 'Secretary',
        'CHAIR': 'Chair',
        'LOAN_APPROVER': 'Loan Approver',
        'FINANCE': 'Finance',
    }
    return labels.get(str(role or '').strip().upper(), str(role or '').strip() or 'Responsible team')


def lock_reason(case: TatTrackerCase, user: dict, stage: StageConfig) -> str:
    if not previous_stages_complete(case, stage):
        return 'Previous stage is not complete.'
    if not can_user_edit_stage(user, case, stage):
        return 'Not assigned to your role.'
    if case.stage_values.get(stage.key) and stage.kind != 'dropdown':
        return 'Already completed.'
    return ''


def public_user(user: dict) -> dict:
    return {'name': user.get('name', ''), 'roles': user.get('roles') or [], 'telegram_id': user.get('telegram_id', ''), 'username': user.get('username', '')}


def serialize_product(product: ProductConfig) -> dict:
    return {'key': product.key, 'label': product.label, 'sheet_name': product.sheet_name, 'min_amount': str(product.min_amount), 'max_amount': str(product.max_amount) if product.max_amount is not None else ''}


def _allowed_products(workflow: dict, user: dict) -> list[ProductConfig]:
    products = configured_products(workflow)
    allowed = set(user.get('products') or [])
    upper = {item.upper() for item in allowed}
    if not allowed or 'ALL' in upper or '*' in allowed:
        return products
    return [p for p in products if p.key in allowed or p.sheet_name in allowed]


def _allowed_branches(workflow: dict, user: dict) -> list[str]:
    branches = workflow_branches(workflow)
    allowed = user.get('branches') or []
    upper = {item.upper() for item in allowed}
    if not allowed or 'ALL' in upper or '*' in allowed:
        return branches
    return [branch for branch in branches if branch in allowed]


def product_by_key(key: str) -> ProductConfig:
    normalized = str(key or '').strip().lower().replace('-', '_')
    if normalized not in PRODUCTS:
        raise ValueError('Invalid product.')
    return PRODUCTS[normalized]


def stage_by_key(product: ProductConfig, key: str) -> StageConfig | None:
    return next((stage for stage in product.stages if stage.key == key), None)


def parse_amount(value) -> Decimal:
    try:
        return Decimal(str(value or '').replace(',', '').strip())
    except (InvalidOperation, ValueError):
        raise ValueError('Enter a valid amount.')


def validate_amount(product: ProductConfig, amount: Decimal) -> None:
    if amount < product.min_amount:
        raise ValueError(f'{product.label} amount must be at least KES {product.min_amount:,.0f}.')
    if product.max_amount is not None and amount > product.max_amount:
        raise ValueError(f'{product.label} amount must be at most KES {product.max_amount:,.0f}.')


def display_stage_value(stage: StageConfig, value: Any) -> str:
    if not value:
        return ''
    if stage.kind == 'timestamp':
        return format_datetime(parse_iso_datetime(value))
    return str(value)


def sheet_value_for_stage(stage: StageConfig, value: Any) -> str:
    if not value:
        return ''
    if stage.kind == 'timestamp':
        return sheet_datetime(value)
    return str(value)


def parse_iso_datetime(value: Any):
    if hasattr(value, 'isoformat'):
        return value
    try:
        parsed = timezone.datetime.fromisoformat(str(value))
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed
    except Exception:
        return None


def sheet_datetime(value: Any) -> str:
    parsed = parse_iso_datetime(value)
    if not parsed:
        return str(value or '')
    return timezone.localtime(parsed).strftime('%d-%b-%Y %H:%M')


def format_datetime(value) -> str:
    if not value:
        return ''
    if isinstance(value, str):
        value = parse_iso_datetime(value)
    if not value:
        return ''
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime('%d-%b-%Y %H:%M')


def tat_hours_formula(product: ProductConfig, row: int) -> str:
    created_col = column_letter(product.stage_columns['created'])
    disbursement_stage = stage_by_key(product, 'disbursement')
    if not disbursement_stage:
        return ''
    end_col = column_letter(disbursement_stage.column)
    return f'=IF(OR(${created_col}{row}="",${end_col}{row}=""),"",ROUND((${end_col}{row}-${created_col}{row})*24,2))'


def tat_days_formula(product: ProductConfig, row: int) -> str:
    hours_col = column_letter(product.tat_start_col)
    return f'=IF({hours_col}{row}="","",ROUND({hours_col}{row}/24,2))'
def column_letter(index: int) -> str:
    letters = ''
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _telegram_name(user_payload: dict) -> str:
    parts = [str(user_payload.get('first_name') or '').strip(), str(user_payload.get('last_name') or '').strip()]
    return ' '.join(part for part in parts if part).strip()


def _normalize_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(',') if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []
