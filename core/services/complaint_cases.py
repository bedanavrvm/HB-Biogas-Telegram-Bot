"""Complaint case Mini App services: authorization, case updates, map data, and evidence."""
from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import base64
import binascii
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import get_valid_filename

from core.models import (
    CaseUpdate,
    ComplaintCaseControl,
    ComplaintCaseEvent,
    ComplaintCaseEvidence,
    ComplaintCaseSequence,
    ComplaintCategory,
    ComplaintCategoryAlias,
    JawabuCustomer,
    OperationalLocation,
    ParsedMessage,
    ProcessedMessage,
    RawMessage,
)
from core.services.identifiers import normalize_kenyan_phone
from core.services.order_approval import GoogleDriveMediaStorage
from core.services.sheets import append_parsed_message_to_sheet, get_sheets_service


logger = logging.getLogger(__name__)


ACTIVE_STATUSES = {'Open', 'In Progress'}
STATUS_VALUES = {'Open', 'In Progress', 'Closed'}
MANAGER_ROLE = 'MANAGER'
ALLOWED_DOCUMENT_TYPES = {
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}


class ComplaintCaseError(ValueError):
    """Staff-safe complaint Mini App validation error."""


class ComplaintCaseConflict(ComplaintCaseError):
    """The client edited a stale complaint revision."""

    def __init__(self, message: str, *, current_revision: int):
        super().__init__(message)
        self.current_revision = current_revision


@dataclass(frozen=True)
class ComplaintCaseActor:
    user: Any
    name: str
    telegram_id: str
    username: str
    role: str
    capabilities: frozenset[str]
    access: dict | None = None

    @property
    def is_manager(self) -> bool:
        return 'complaint.case.manage' in self.capabilities


def is_complaint_workflow(group_config) -> bool:
    return str((getattr(group_config, 'workflow', None) or {}).get('type') or 'case') == 'case'


def available_categories(group_config):
    """Return active global categories not restricted away from this group."""
    group_id = str(getattr(group_config, 'group_id', '') or '')
    return ComplaintCategory.objects.filter(active=True).filter(
        Q(availability__isnull=True)
        | Q(availability__active=True, availability__group_configuration__group_id=group_id)
    ).distinct().order_by('label')


def resolve_category(group_config, value: Any) -> ComplaintCategory:
    text = ' '.join(str(value or '').split())
    normalized = re.sub(r'[^a-z0-9]+', ' ', text.casefold()).strip()
    categories = available_categories(group_config)
    category = categories.filter(Q(key=text) | Q(label__iexact=text)).first()
    if not category and normalized:
        alias = ComplaintCategoryAlias.objects.filter(
            category__in=categories, normalized_alias=normalized, active=True,
        ).select_related('category').first()
        category = alias.category if alias else None
    if not category:
        raise ComplaintCaseError('Select an available complaint category.')
    return category


def resolve_branch(value: Any) -> OperationalLocation | None:
    text = ' '.join(str(value or '').split())
    if not text:
        return None
    normalized = re.sub(r'[^a-z0-9]+', '_', text.casefold().replace('\u2019', "'")).strip('_')
    return OperationalLocation.objects.filter(location_type='branch', active=True).filter(
        Q(name__iexact=text) | Q(code__iexact=text)
        | Q(aliases__normalized_alias=normalized, aliases__active=True),
    ).distinct().first()


def match_customer(customer_id: str, customer_phone: str) -> tuple[JawabuCustomer | None, str]:
    id_matches = JawabuCustomer.objects.none()
    phone_matches = JawabuCustomer.objects.none()
    if customer_id:
        id_matches = JawabuCustomer.objects.filter(national_id__iexact=customer_id)
    if customer_phone:
        normalized_phone = normalize_kenyan_phone(customer_phone) or customer_phone
        phone_matches = JawabuCustomer.objects.filter(
            Q(primary_phone=normalized_phone) | Q(phone_history__phone=normalized_phone),
        ).distinct()
    id_ids = set(id_matches.values_list('pk', flat=True))
    phone_ids = set(phone_matches.values_list('pk', flat=True))
    if len(id_ids) == 1 and len(phone_ids) == 1 and id_ids != phone_ids:
        return None, 'conflict'
    if len(id_ids) == 1:
        return id_matches.first(), 'exact_id'
    if len(phone_ids) == 1:
        return phone_matches.first(), 'exact_phone'
    if len(id_ids) > 1 or len(phone_ids) > 1:
        return None, 'ambiguous'
    return None, 'unmatched'


def ensure_case_control(case: ParsedMessage, group_config=None) -> ComplaintCaseControl:
    try:
        return case.complaint_control
    except ComplaintCaseControl.DoesNotExist:
        pass
    category = None
    if group_config:
        try:
            category = resolve_category(group_config, case.complaint_category or 'General complaint')
        except ComplaintCaseError:
            category = available_categories(group_config).first()
    branch = resolve_branch(case.branch_region)
    customer, match_status = match_customer(case.customer_id, case.customer_phone)
    priority = category.default_priority if category else 'normal'
    target = {'high': 24, 'normal': 72, 'low': 120}[priority]
    started = case.timestamp or case.created_at or timezone.now()
    control, _ = ComplaintCaseControl.objects.get_or_create(
        parsed_message=case,
        defaults={
            'category': category, 'branch_ref': branch, 'customer': customer,
            'customer_match_status': match_status, 'priority': priority,
            'sla_target_hours': target, 'sla_started_at': started,
            'sla_due_at': started + timedelta(hours=target),
            'sync_status': 'success' if case.synced_to_sheets and not case.last_sync_error else 'pending',
        },
    )
    return control


def staff_actor_for_payload(group_config, auth_payload: dict) -> ComplaintCaseActor:
    user = _telegram_user(auth_payload)
    telegram_id = str(user.get('id') or '').strip()
    username = str(user.get('username') or '').strip().lower().lstrip('@')
    if not telegram_id and not username:
        raise ComplaintCaseError('Telegram identity is missing. Reopen Complaint Cases from Telegram.')
    from core.services.telegram_identity import identity_from_user_payload, resolve_or_bind_telegram_user, user_access
    canonical_user = resolve_or_bind_telegram_user(identity_from_user_payload(user)) if telegram_id else None
    access = user_access(canonical_user, 'complaint_cases', group_configuration=group_config)
    if not access['authorized']:
        raise ComplaintCaseError('Your Telegram account is not configured for complaint cases in this group.')
    roles = {str(role).upper() for role in access['roles']}
    role = MANAGER_ROLE if MANAGER_ROLE in roles else ('OFFICER' if 'OFFICER' in roles else ('IT' if 'IT' in roles else ''))
    if not role:
        raise ComplaintCaseError('Your user has no complaint-case role for this group.')
    from core.services.workflow_capabilities import effective_capability_keys
    return ComplaintCaseActor(
        user=canonical_user,
        name=canonical_user.get_full_name() or canonical_user.get_username(),
        telegram_id=telegram_id,
        username=username,
        role=role,
        capabilities=frozenset(effective_capability_keys(canonical_user, 'complaint_cases', access=access)),
        access=access,
    )


def actor_can(group_config, actor: ComplaintCaseActor, capability: str, case: ParsedMessage | None = None) -> bool:
    from core.services.workflow_access import workflow_access_decision
    return workflow_access_decision(
        actor.user, 'complaint_cases', capability, access=actor.access,
        resource=case, group_configuration=group_config,
    ).allowed


def actor_can_access_case(group_config, actor: ComplaintCaseActor, capability: str, case_id: str) -> bool:
    try:
        case = _case_for_group(group_config.group_id, case_id, actor=actor)
    except ComplaintCaseError:
        return False
    return actor_can(group_config, actor, capability, case)


def bootstrap_data(group_config, actor: ComplaintCaseActor) -> dict[str, Any]:
    cases = _case_queryset(group_config.group_id, actor=actor)
    from core.services.branches import global_branch_choices, workflow_branches
    configured_branches = workflow_branches(
        getattr(group_config, 'workflow', None) or {},
        default=global_branch_choices(),
    )
    observed_branches = list(
        cases.exclude(branch_region='').order_by('branch_region').values_list('branch_region', flat=True).distinct()
    )
    from core.services.workflow_access import matching_capability_grants
    scope_grants = matching_capability_grants(
        'complaint_cases', 'complaint.queue.view', access=actor.access,
        group_configuration=group_config,
    ) if not getattr(actor.user, 'is_superuser', False) else []
    scoped_branches = {
        str(getattr(item, 'branch', '') or '').strip() for item in scope_grants
        if str(getattr(item, 'branch', '') or '').strip()
    }
    has_global_branch = getattr(actor.user, 'is_superuser', False) or any(
        not str(getattr(item, 'branch', '') or '').strip() for item in scope_grants
    )
    branch_values = set(configured_branches) | set(observed_branches)
    if scoped_branches and not has_global_branch:
        branch_values = {value for value in branch_values if value.casefold() in {item.casefold() for item in scoped_branches}}
    assignees = []
    if 'complaint.case.assign' in actor.capabilities:
        from core.models import AccessGrant
        grants = AccessGrant.objects.filter(
            workflow='complaint_cases', active=True, user__is_active=True,
        ).filter(
            Q(group_configuration__isnull=True) | Q(group_configuration__group_id=str(group_config.group_id)),
        ).select_related('user').order_by('user__first_name', 'user__username')
        seen = set()
        for grant in grants:
            if grant.user_id in seen or str(grant.role).upper() not in {'OFFICER', 'MANAGER'}:
                continue
            seen.add(grant.user_id)
            assignees.append({
                'id': str(grant.user_id),
                'name': grant.user.get_full_name() or grant.user.get_username(),
            })
    return {
        'actor': {
            'name': actor.name, 'role': actor.role, 'is_manager': actor.is_manager,
            'capabilities': sorted(actor.capabilities),
        },
        'statuses': sorted(STATUS_VALUES),
        'branches': sorted(branch_values, key=str.casefold),
        'categories': list(available_categories(group_config).values_list('label', flat=True)),
        'assignees': assignees,
        'counts': {
            'open': cases.filter(complaint_status='Open').count(),
            'in_progress': cases.filter(complaint_status='In Progress').count(),
            'closed': cases.filter(complaint_status='Closed').count(),
        },
    }


def list_cases_page(
    group_config, actor: ComplaintCaseActor | None = None, query: str = '', status: str = 'active',
    branch: str = '', priority: str = '', assignment: str = '', sla: str = '', cursor: str = '', limit: int = 40,
) -> dict[str, Any]:
    cases = _case_queryset(group_config.group_id, actor=actor)
    cases = _filter_status(cases, status)
    cases = _filter_branch(cases, branch)
    cases = _filter_query(cases, query)
    if priority in {'high', 'normal', 'low'}:
        cases = cases.filter(complaint_control__priority=priority)
    if assignment == 'mine':
        cases = cases.filter(complaint_control__assigned_to=actor.user)
    elif assignment == 'unassigned':
        cases = cases.filter(complaint_control__assigned_to__isnull=True)
    now = timezone.now()
    if sla == 'overdue':
        cases = cases.exclude(complaint_status='Closed').filter(complaint_control__sla_due_at__lt=now)
    elif sla == 'due_soon':
        cases = cases.exclude(complaint_status='Closed').filter(
            Q(complaint_control__priority='high', complaint_control__sla_due_at__range=(now, now + timedelta(hours=6)))
            | Q(complaint_control__priority='normal', complaint_control__sla_due_at__range=(now, now + timedelta(hours=18)))
            | Q(complaint_control__priority='low', complaint_control__sla_due_at__range=(now, now + timedelta(hours=30)))
        )
    if cursor:
        try:
            decoded_cursor = json.loads(base64.urlsafe_b64decode(cursor + ('=' * (-len(cursor) % 4))).decode())
            cursor_at = datetime.fromisoformat(decoded_cursor['at'])
            if timezone.is_naive(cursor_at):
                cursor_at = timezone.make_aware(cursor_at, timezone.get_current_timezone())
            cases = cases.filter(
                Q(timestamp__lt=cursor_at)
                | Q(timestamp=cursor_at, pk__lt=decoded_cursor['id'])
            )
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error):
            raise ComplaintCaseError('The case-list cursor is invalid. Refresh the queue.')
    page_size = max(1, min(int(limit or 40), 100))
    rows = list(cases[:page_size + 1])
    next_cursor = ''
    if len(rows) > page_size and rows[page_size - 1].timestamp:
        raw_cursor = json.dumps({
            'at': rows[page_size - 1].timestamp.isoformat(), 'id': str(rows[page_size - 1].pk),
        }, separators=(',', ':')).encode()
        next_cursor = base64.urlsafe_b64encode(raw_cursor).decode().rstrip('=')
    return {'items': [serialize_case(case) for case in rows[:page_size]], 'next_cursor': next_cursor}


def list_cases(group_config, actor: ComplaintCaseActor | None = None, **filters) -> list[dict[str, Any]]:
    """Compatibility list facade; HTTP callers use ``list_cases_page`` for cursors."""
    return list_cases_page(group_config, actor, **filters)['items']


def case_detail(group_config, case_id: str, actor: ComplaintCaseActor | None = None) -> dict[str, Any]:
    case = _case_for_group(group_config.group_id, case_id, actor=actor)
    payload = serialize_case(case)
    payload['raw_message'] = case.raw_message
    payload['resolution_details'] = case.resolution_details
    payload['updates'] = [serialize_update(update) for update in case.case_updates.all()]
    payload['evidence'] = [serialize_evidence(evidence) for evidence in case.complaint_evidence.all()]
    payload['location'] = location_for_case(case)
    return payload


def update_case(
    group_config,
    actor: ComplaintCaseActor,
    case_id: str,
    fields: dict[str, Any],
    uploaded_files: list,
) -> dict[str, Any]:
    request_id = str(fields.get('client_request_id') or '').strip()
    if not request_id:
        raise ComplaintCaseError('The update request is missing its retry identifier. Refresh and try again.')
    case = _case_for_group(group_config.group_id, case_id, actor=actor)
    if not actor_can(group_config, actor, 'complaint.case.update', case):
        raise ComplaintCaseError('Your role does not permit updates to this case branch and group.')
    validate_uploaded_files(uploaded_files)
    values = validate_update_fields(group_config, case, actor, {**fields, 'has_evidence': bool(uploaded_files)})
    payload_hash = mutation_payload_hash(values)
    control = ensure_case_control(case, group_config)
    existing_event = control.events.filter(request_id=request_id).first()
    if existing_event:
        if existing_event.payload_hash != payload_hash:
            raise ComplaintCaseError('That retry identifier was already used for a different update.')
        existing = CaseUpdate.objects.filter(parsed_message=case, client_request_id=request_id).first()
        if existing and uploaded_files:
            store_evidence(group_config, case, existing, actor, uploaded_files)
        return case_detail(group_config, case_id, actor)
    try:
        expected_revision = int(fields.get('expected_revision'))
    except (TypeError, ValueError):
        raise ComplaintCaseError('Refresh this case before saving; its revision is missing.')
    try:
        update_record = apply_case_update(
            group_config, case, actor, values, request_id, expected_revision, payload_hash,
        )
    except IntegrityError:
        # A double tap can race the optimistic lookup above. The database
        # constraint is authoritative; return the first completed update.
        return case_detail(group_config, case_id, actor)
    store_evidence(group_config, case, update_record, actor, uploaded_files)
    return case_detail(group_config, case_id, actor)


def create_complaint_case(
    group_config,
    actor: ComplaintCaseActor,
    fields: dict[str, Any],
    uploaded_files: list,
) -> dict[str, Any]:
    request_id = create_request_id(fields.get('client_request_id'))
    validate_uploaded_files(uploaded_files)
    values = validate_new_case_fields(group_config, fields)
    payload_hash = mutation_payload_hash(values)
    request_hash = complaint_case_hash(group_config.group_id, request_id)
    case = ParsedMessage.objects.filter(
        group_id=str(group_config.group_id),
        processed_message__message_hash=request_hash,
    ).first()
    created = False
    create_update = None

    if not case:
        try:
            with transaction.atomic():
                case = ParsedMessage.objects.select_for_update().filter(
                    group_id=str(group_config.group_id),
                    processed_message__message_hash=request_hash,
                ).first()
                if not case:
                    message_id = next_complaint_case_id(group_config)
                    raw_content = new_case_raw_content(values, actor)
                    raw_message = RawMessage.objects.create(
                        telegram_message_id=message_id,
                        sender=actor.name,
                        content=raw_content,
                        received_at=timezone.now(),
                        has_image=bool(uploaded_files),
                    )
                    processed_message = ProcessedMessage.objects.create(
                        message_hash=request_hash,
                        raw_message=raw_message,
                        status='success',
                    )
                    case = ParsedMessage.objects.create(
                        processed_message=processed_message,
                        message_id=message_id,
                        timestamp=timezone.now(),
                        sender=actor.name,
                        raw_message=raw_content,
                        gps_link=values['gps_link'],
                        image_flag=bool(uploaded_files),
                        source='complaint_mini_app',
                        customer_name=values['client_name'],
                        customer_phone=values['customer_phone'],
                        customer_id=values['customer_id'],
                        branch_region=values['branch_region'],
                        complaint_category=values['complaint_category'],
                        complaint_description=values['complaint_description'],
                        complaint_status='Open',
                        group_id=str(group_config.group_id),
                        sheet_id=str(getattr(group_config, 'sheet_id', '') or ''),
                        sheet_name=str(getattr(group_config, 'sheet_name', '') or ''),
                    )
                    control = create_case_control(case, values)
                    create_update = CaseUpdate.objects.create(
                        parsed_message=case,
                        group_id=case.group_id,
                        updated_by=actor.name,
                        old_status='',
                        new_status='Open',
                        resolution_text='Complaint created in Complaint Cases Mini App.',
                        raw_update_text='Complaint created in Complaint Cases Mini App',
                        source='mini_app_create',
                        client_request_id=request_id,
                        gps_link=values['gps_link'],
                        latitude=values['latitude'],
                        longitude=values['longitude'],
                        sync_status='pending',
                    )
                    ComplaintCaseEvent.objects.create(
                        case=control, revision=control.revision, action='created', actor=actor.user,
                        actor_label=actor.name, request_id=request_id, payload_hash=payload_hash,
                        after_values=control_snapshot(control, case),
                    )
                    record_complaint_update(create_update, case, actor, action='complaint.case.created')
                    created = True
        except IntegrityError:
            case = ParsedMessage.objects.filter(
                group_id=str(group_config.group_id),
                processed_message__message_hash=request_hash,
            ).first()
            if not case:
                raise

    control = ensure_case_control(case, group_config)
    existing_event = control.events.filter(request_id=request_id).first()
    if existing_event and existing_event.payload_hash and existing_event.payload_hash != payload_hash:
        raise ComplaintCaseError('That retry identifier was already used for different complaint details.')
    if not create_update:
        create_update = CaseUpdate.objects.filter(parsed_message=case, client_request_id=request_id).first()
    if create_update and uploaded_files:
        store_evidence(group_config, case, create_update, actor, uploaded_files)
    try:
        synced = sync_new_case_to_sheet(group_config, case)
    except Exception:
        logger.exception('Complaint creation publication failed for case %s.', case.pk)
        synced = False
    control.sync_status = 'success' if synced else 'failed'
    control.sync_error = '' if synced else (case.last_sync_error or 'Complaint register publication is pending.')
    control.last_sync_at = timezone.now() if synced else control.last_sync_at
    control.save(update_fields=['sync_status', 'sync_error', 'last_sync_at', 'updated_at'])
    if create_update:
        create_update.sync_status = 'success' if synced else 'failed'
        create_update.sync_error = '' if synced else control.sync_error
        create_update.save(update_fields=['sync_status', 'sync_error'])
    return {
        'case': case_detail(group_config, case.message_id),
        'created': created,
        'synced_to_sheet': synced,
    }


def create_request_id(value: Any) -> str:
    request_id = str(value or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{7,127}', request_id):
        raise ComplaintCaseError('The create request is missing a valid retry identifier. Refresh and try again.')
    return request_id


def validate_new_case_fields(group_config, fields: dict[str, Any]) -> dict[str, Any]:
    client_name = required_case_text(fields.get('client_name'), 'Client name')
    branch_region = required_case_text(fields.get('branch_region'), 'Branch')
    category_text = required_case_text(fields.get('complaint_category'), 'Complaint category')
    complaint_description = required_description(fields.get('complaint_description'))
    customer_id = limited_case_text(fields.get('customer_id'), 'Customer ID')
    phone_input = str(fields.get('customer_phone') or '').strip()
    customer_phone = normalize_kenyan_phone(phone_input) if phone_input else ''
    if phone_input and not customer_phone:
        raise ComplaintCaseError('Enter a valid Kenyan phone number.')
    if not customer_phone and not customer_id:
        raise ComplaintCaseError('Enter a phone number or customer ID.')
    category = resolve_category(group_config, category_text)
    latitude, longitude, gps_link = normalize_location(fields)
    branch_ref = resolve_branch(branch_region)
    customer, match_status = match_customer(customer_id, customer_phone)
    return {
        'client_name': client_name,
        'customer_phone': customer_phone,
        'customer_id': customer_id,
        'branch_region': branch_region,
        'complaint_category': category.label,
        'category': category,
        'branch_ref': branch_ref,
        'customer': customer,
        'customer_match_status': match_status,
        'complaint_description': complaint_description,
        'latitude': latitude,
        'longitude': longitude,
        'gps_link': gps_link,
    }


def create_case_control(case: ParsedMessage, values: dict[str, Any]) -> ComplaintCaseControl:
    priority = values['category'].default_priority
    target = {'high': 24, 'normal': 72, 'low': 120}[priority]
    started = case.timestamp or timezone.now()
    return ComplaintCaseControl.objects.create(
        parsed_message=case, category=values['category'], branch_ref=values['branch_ref'],
        customer=values['customer'], customer_match_status=values['customer_match_status'],
        priority=priority, sla_target_hours=target, sla_started_at=started,
        sla_due_at=started + timedelta(hours=target), sync_status='pending',
    )


def mutation_payload_hash(values: dict[str, Any]) -> str:
    safe_values = {
        key: (str(value.pk) if hasattr(value, 'pk') else str(value) if isinstance(value, Decimal) else value)
        for key, value in values.items()
        if key not in {'has_evidence'}
    }
    return hashlib.sha256(json.dumps(safe_values, sort_keys=True, default=str).encode()).hexdigest()


def required_case_text(value: Any, label: str) -> str:
    text = limited_case_text(value, label)
    if not text:
        raise ComplaintCaseError(f'{label} is required.')
    return text


def required_description(value: Any) -> str:
    """Keep descriptions useful while still bounding untrusted Mini App input."""
    text = str(value or '').strip()
    if not text:
        raise ComplaintCaseError('Complaint description is required.')
    if len(text) > 5000:
        raise ComplaintCaseError('Complaint description must be 5,000 characters or fewer.')
    return text


def limited_case_text(value: Any, label: str) -> str:
    text = str(value or '').strip()
    if len(text) > 255:
        raise ComplaintCaseError(f'{label} must be 255 characters or fewer.')
    return text


def complaint_case_message_id(group_id: str, request_id: str) -> str:
    return f'CMP-MA-{hashlib.sha256(f"{group_id}:{request_id}".encode()).hexdigest()[:24]}'


def next_complaint_case_id(group_config) -> str:
    year = timezone.localtime(timezone.now()).year
    sequence, _ = ComplaintCaseSequence.objects.select_for_update().get_or_create(
        group_id=str(group_config.group_id),
        year=year,
        defaults={'next_number': 1},
    )
    while True:
        number = sequence.next_number
        sequence.next_number = number + 1
        sequence.save(update_fields=['next_number', 'updated_at'])
        case_id = f'CMP-{year}-{number:03d}'
        if not ParsedMessage.objects.filter(group_id=str(group_config.group_id), message_id=case_id).exists():
            return case_id


def complaint_case_hash(group_id: str, request_id: str) -> str:
    return hashlib.sha256(f'complaint-mini-app:{group_id}:{request_id}'.encode()).hexdigest()


def new_case_raw_content(values: dict[str, Any], actor: ComplaintCaseActor) -> str:
    return json.dumps(
        {
            'source': 'complaint_mini_app',
            'created_by': actor.name,
            'client_name': values['client_name'],
            'customer_phone': values['customer_phone'],
            'customer_id': values['customer_id'],
            'branch_region': values['branch_region'],
            'complaint_category': values['complaint_category'],
            'complaint_description': values['complaint_description'],
            'gps_link': values['gps_link'],
        },
        sort_keys=True,
    )


def sync_new_case_to_sheet(group_config, case: ParsedMessage) -> bool:
    if case.synced_to_sheets and not case.last_sync_error:
        return True
    return append_parsed_message_to_sheet(
        case,
        sheet_id=str(getattr(group_config, 'sheet_id', '') or ''),
        sheet_name=str(getattr(group_config, 'sheet_name', '') or ''),
        sheet_schema=getattr(group_config, 'sheet_schema_config', None),
    )


def validate_update_fields(group_config, case: ParsedMessage, actor: ComplaintCaseActor, fields: dict[str, Any]) -> dict[str, Any]:
    control = ensure_case_control(case, group_config)
    status = str(fields.get('status') or case.complaint_status or 'Open').strip()
    if status not in STATUS_VALUES:
        raise ComplaintCaseError('Select a valid case status.')
    if status == 'Closed' and case.complaint_status != 'Closed' and not actor_can(group_config, actor, 'complaint.case.close', case):
        raise ComplaintCaseError('Only a case manager can close a complaint.')
    if case.complaint_status == 'Closed' and status != 'Closed' and not actor_can(group_config, actor, 'complaint.case.reopen', case):
        raise ComplaintCaseError('Only a case manager can reopen a complaint.')
    note = str(fields.get('resolution_text') or '').strip()
    if len(note) > 5000:
        raise ComplaintCaseError('The update note must be 5,000 characters or fewer.')
    if status == 'Closed' and case.complaint_status != 'Closed' and not note:
        raise ComplaintCaseError('Add a resolution note before closing this complaint.')
    if control.assigned_to_id and control.assigned_to_id != actor.user.pk and not actor_can(group_config, actor, 'complaint.case.assign', case):
        raise ComplaintCaseError('This complaint is assigned to another officer.')
    assignment_action = str(fields.get('assignment_action') or '').strip()
    assigned_to = control.assigned_to
    if assignment_action == 'claim':
        if not actor_can(group_config, actor, 'complaint.case.claim', case):
            raise ComplaintCaseError('Your role cannot claim complaints.')
        if assigned_to and assigned_to.pk != actor.user.pk:
            raise ComplaintCaseError('This complaint has already been assigned.')
        assigned_to = actor.user
    elif assignment_action == 'unassign':
        if not actor_can(group_config, actor, 'complaint.case.assign', case):
            raise ComplaintCaseError('Only a case manager can remove an assignment.')
        assigned_to = None
    elif fields.get('assigned_to') not in (None, ''):
        if not actor_can(group_config, actor, 'complaint.case.assign', case):
            raise ComplaintCaseError('Only a case manager can assign complaints.')
        from django.contrib.auth import get_user_model
        assigned_to = get_user_model().objects.filter(pk=fields.get('assigned_to'), is_active=True).first()
        if not assigned_to:
            raise ComplaintCaseError('Select an active case officer.')
        from core.services.telegram_identity import user_access
        from core.services.workflow_access import workflow_access_decision
        assignee_access = user_access(assigned_to, 'complaint_cases', group_configuration=group_config)
        if not workflow_access_decision(
            assigned_to, 'complaint_cases', 'complaint.case.update', access=assignee_access,
            resource=case, group_configuration=group_config,
        ).allowed:
            raise ComplaintCaseError('That officer is not permitted to work on this case branch and group.')
    priority = str(fields.get('priority') or control.priority).lower()
    if priority not in {'high', 'normal', 'low'}:
        raise ComplaintCaseError('Select High, Normal, or Low priority.')
    if priority != control.priority and not actor_can(group_config, actor, 'complaint.case.assign', case):
        raise ComplaintCaseError('Only a case manager can change priority.')
    latitude, longitude, gps_link = normalize_location(fields)
    if not note and not gps_link and not fields.get('has_evidence') and status == (case.complaint_status or 'Open') and assigned_to == control.assigned_to and priority == control.priority:
        raise ComplaintCaseError('Add a note, location, evidence, or a status change before saving.')
    return {
        'status': status, 'note': note, 'latitude': latitude, 'longitude': longitude,
        'gps_link': gps_link, 'assigned_to': assigned_to, 'priority': priority,
    }


def normalize_location(fields: dict[str, Any]) -> tuple[Decimal | None, Decimal | None, str]:
    latitude = decimal_coordinate(fields.get('latitude'), minimum=-90, maximum=90, label='Latitude')
    longitude = decimal_coordinate(fields.get('longitude'), minimum=-180, maximum=180, label='Longitude')
    if (latitude is None) != (longitude is None):
        raise ComplaintCaseError('Capture both latitude and longitude, or leave both blank.')
    gps_link = google_maps_url(latitude, longitude) if latitude is not None else ''
    return latitude, longitude, gps_link


def decimal_coordinate(value: Any, *, minimum: int, maximum: int, label: str) -> Decimal | None:
    if value is None or str(value).strip() == '':
        return None
    try:
        coordinate = Decimal(str(value)).quantize(Decimal('0.000001'))
    except (InvalidOperation, ValueError):
        raise ComplaintCaseError(f'{label} is invalid.')
    if not Decimal(minimum) <= coordinate <= Decimal(maximum):
        raise ComplaintCaseError(f'{label} is outside the valid range.')
    return coordinate


def apply_case_update(
    group_config, case: ParsedMessage, actor: ComplaintCaseActor, values: dict[str, Any],
    request_id: str, expected_revision: int, payload_hash: str,
) -> CaseUpdate:
    with transaction.atomic():
        case = ParsedMessage.objects.select_for_update().get(pk=case.pk)
        control = ComplaintCaseControl.objects.select_for_update().get(parsed_message=case)
        if control.revision != expected_revision:
            raise ComplaintCaseConflict(
                'This complaint changed while you were editing it. Review the latest version and try again.',
                current_revision=control.revision,
            )
        resolved_at = timezone.now() if values['status'] == 'Closed' else None
        resolution_details = append_resolution_note(case.resolution_details, actor.name, values['note'])
        before = control_snapshot(control, case)
        update = CaseUpdate.objects.create(
            parsed_message=case,
            group_id=case.group_id,
            updated_by=actor.name,
            old_status=case.complaint_status or '',
            new_status=values['status'],
            resolution_text=values['note'],
            raw_update_text='Complaint Cases Mini App update',
            source='mini_app',
            client_request_id=request_id,
            gps_link=values['gps_link'],
            latitude=values['latitude'],
            longitude=values['longitude'],
            sync_status='pending',
        )
        update_case_fields(case, values, resolution_details, resolved_at)
        reopened = before['status'] == 'Closed' and values['status'] != 'Closed'
        if reopened:
            control.sla_started_at = timezone.now()
        control.assigned_to = values['assigned_to']
        control.assigned_at = timezone.now() if values['assigned_to'] else None
        control.priority = values['priority']
        control.sla_target_hours = {'high': 24, 'normal': 72, 'low': 120}[control.priority]
        control.sla_due_at = control.sla_started_at + timedelta(hours=control.sla_target_hours)
        control.revision += 1
        control.sync_status = 'pending'
        control.sync_error = ''
        control.save(update_fields=[
            'assigned_to', 'assigned_at', 'priority', 'sla_target_hours', 'sla_started_at',
            'sla_due_at', 'revision', 'sync_status', 'sync_error', 'updated_at',
        ])
        ComplaintCaseEvent.objects.create(
            case=control, revision=control.revision, action='updated', actor=actor.user,
            actor_label=actor.name, request_id=request_id, payload_hash=payload_hash,
            before_values=before, after_values=control_snapshot(control, case), reason=values['note'],
        )
        record_complaint_update(update, case, actor, action='complaint.case.updated')
    try:
        synced = update_sheet_case(group_config, case, sheet_updates(values, resolution_details, resolved_at))
    except Exception:
        logger.exception('Complaint update publication failed for case %s.', case.pk)
        synced = False
    update.sync_status = 'success' if synced else 'failed'
    update.sync_error = '' if synced else 'The local update is saved; complaint register publication is pending.'
    update.save(update_fields=['sync_status', 'sync_error'])
    control.sync_status = update.sync_status
    control.sync_error = update.sync_error
    control.last_sync_at = timezone.now() if synced else control.last_sync_at
    control.save(update_fields=['sync_status', 'sync_error', 'last_sync_at', 'updated_at'])
    return update


def record_complaint_update(update: CaseUpdate, case: ParsedMessage, actor: ComplaintCaseActor, *, action: str) -> None:
    """Project a complaint-case write into the shared, immutable audit ledger."""
    from core.services.compliance_audit import record_event

    record_event(
        workflow='complaint_cases',
        action=action,
        category='workflow_transition' if update.old_status != update.new_status else 'workflow',
        origin='human' if update.source.startswith('mini_app') else 'external_sync',
        subject_type='complaint_case',
        subject_id=str(case.pk),
        customer_reference=str(case.message_id),
        actor=actor.user,
        authority_user=actor.user,
        actor_label=actor.name,
        authority_label=actor.name,
        request_id=update.client_request_id,
        source_model='CaseUpdate',
        source_event_id=str(update.pk),
        deduplication_key=f'complaint:CaseUpdate:{update.pk}',
        before_values={'status': update.old_status} if update.old_status else {},
        after_values={
            'status': update.new_status,
            'risk_level': update.risk_level,
            'loan_at_risk': update.loan_at_risk,
        },
        metadata={
            'source': update.source,
            'has_resolution_note': bool(update.resolution_text),
            'has_location': bool(update.gps_link),
        },
        sensitive=True,
        occurred_at=update.created_at,
    )


def update_case_fields(case: ParsedMessage, values: dict[str, Any], resolution_details: str, resolved_at) -> None:
    case.complaint_status = values['status']
    case.resolution_details = resolution_details
    if resolved_at:
        case.date_resolved = resolved_at
    elif case.complaint_status != 'Closed':
        case.date_resolved = None
    if values['gps_link']:
        case.gps_link = values['gps_link']
    case.save(update_fields=['complaint_status', 'resolution_details', 'date_resolved', 'gps_link'])


def sheet_updates(values: dict[str, Any], resolution_details: str, resolved_at) -> dict[str, str]:
    updates = {'status': values['status'], 'resolution_details': resolution_details}
    if resolved_at:
        updates['date_resolved'] = timezone.localtime(resolved_at).strftime('%d/%m/%Y')
    if values['gps_link']:
        updates['gps_link'] = values['gps_link']
    return updates


def update_sheet_case(group_config, case: ParsedMessage, updates: dict[str, str]) -> bool:
    service = get_sheets_service(
        sheet_id=group_config.sheet_id,
        sheet_name=group_config.sheet_name,
        sheet_schema=group_config.sheet_schema_config,
    )
    return service.update_case_row(case.message_id, updates)


def retry_case_sync(group_config, actor: ComplaintCaseActor, case_id: str) -> dict[str, Any]:
    case = _case_for_group(group_config.group_id, case_id, actor=actor)
    if not actor_can(group_config, actor, 'complaint.case.sync.retry', case):
        raise ComplaintCaseError('Your role cannot retry publication for this case.')
    control = ensure_case_control(case, group_config)
    updates = {
        'status': case.complaint_status or 'Open',
        'resolution_details': case.resolution_details or '',
        'gps_link': case.gps_link or '',
    }
    if case.date_resolved:
        updates['date_resolved'] = timezone.localtime(case.date_resolved).strftime('%d/%m/%Y')
    try:
        synced = update_sheet_case(group_config, case, updates) if case.synced_to_sheets else sync_new_case_to_sheet(group_config, case)
    except Exception:
        logger.exception('Complaint publication retry failed for case %s.', case.pk)
        synced = False
    control.sync_status = 'success' if synced else 'failed'
    control.sync_error = '' if synced else 'Complaint register publication is still pending.'
    control.last_sync_at = timezone.now() if synced else control.last_sync_at
    control.save(update_fields=['sync_status', 'sync_error', 'last_sync_at', 'updated_at'])
    ComplaintCaseEvent.objects.create(
        case=control, revision=control.revision, action='sync_retried', actor=actor.user,
        actor_label=actor.name, after_values={'sync_status': control.sync_status},
    )
    return case_detail(group_config, case_id, actor)


def evidence_access(group_config, actor: ComplaintCaseActor, evidence_id: str) -> str:
    evidence = ComplaintCaseEvidence.objects.select_related('parsed_message').filter(pk=evidence_id).first()
    if not evidence or evidence.upload_status != 'success' or not evidence.drive_url:
        raise ComplaintCaseError('Evidence is unavailable.')
    case = _case_for_group(group_config.group_id, evidence.parsed_message.message_id, actor=actor)
    if not actor_can(group_config, actor, 'complaint.case.evidence.view', case):
        raise ComplaintCaseError('Your role cannot view evidence for this case.')
    control = ensure_case_control(case, group_config)
    ComplaintCaseEvent.objects.create(
        case=control, revision=control.revision, action='evidence_opened', actor=actor.user,
        actor_label=actor.name, after_values={'evidence_id': str(evidence.pk)},
    )
    return evidence.drive_url


def append_resolution_note(existing: str, actor_name: str, note: str) -> str:
    if not note:
        return existing or ''
    stamped_note = f'[{timezone.localtime():%d/%m/%Y %H:%M} {actor_name}] {note}'
    return '\n'.join(part for part in [existing.strip(), stamped_note] if part)


def validate_uploaded_files(uploaded_files: list) -> None:
    max_files = int(getattr(settings, 'COMPLAINT_CASE_MAX_FILES_PER_UPDATE', 10))
    max_file_bytes = int(getattr(settings, 'COMPLAINT_CASE_MAX_FILE_SIZE_MB', 10)) * 1024 * 1024
    max_bytes = int(getattr(settings, 'COMPLAINT_CASE_MAX_TOTAL_UPLOAD_MB', 30)) * 1024 * 1024
    if len(uploaded_files) > max_files:
        raise ComplaintCaseError(f'Upload at most {max_files} evidence files at a time.')
    total_size = sum(int(getattr(file_obj, 'size', 0) or 0) for file_obj in uploaded_files)
    if total_size > max_bytes:
        raise ComplaintCaseError('The selected evidence files are too large for one update.')
    for file_obj in uploaded_files:
        if int(getattr(file_obj, 'size', 0) or 0) > max_file_bytes:
            raise ComplaintCaseError(f'Each evidence file must be {max_file_bytes // (1024 * 1024)} MB or smaller.')
        if not detected_upload_type(file_obj):
            raise ComplaintCaseError('Evidence must be a genuine JPEG, PNG, WebP, PDF, or DOCX file.')


def allowed_upload(file_obj) -> bool:
    return bool(detected_upload_type(file_obj))


def detected_upload_type(file_obj) -> str:
    """Verify file signatures instead of trusting browser MIME metadata."""
    suffix = Path(str(getattr(file_obj, 'name', '') or '')).suffix.lower()
    position = file_obj.tell() if hasattr(file_obj, 'tell') else 0
    content = file_obj.read()
    if hasattr(file_obj, 'seek'):
        file_obj.seek(position)
    if suffix in {'.jpg', '.jpeg'} and content.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if suffix == '.png' and content.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if suffix == '.webp' and len(content) >= 12 and content[:4] == b'RIFF' and content[8:12] == b'WEBP':
        return 'image/webp'
    if suffix == '.pdf' and content.startswith(b'%PDF-'):
        return 'application/pdf'
    if suffix == '.docx' and content.startswith(b'PK'):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = set(archive.namelist())
            if '[Content_Types].xml' in names and 'word/document.xml' in names:
                return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        except (OSError, zipfile.BadZipFile):
            return ''
    return ''


def store_evidence(group_config, case: ParsedMessage, update: CaseUpdate, actor: ComplaintCaseActor, uploaded_files: list) -> None:
    for index, file_obj in enumerate(uploaded_files, start=1):
        store_evidence_file(group_config, case, update, actor, file_obj, index)


def store_evidence_file(group_config, case, update, actor, file_obj, index: int) -> None:
    detected_mime = detected_upload_type(file_obj)
    content = file_obj.read()
    content_hash = hashlib.sha256(content).hexdigest()
    existing_for_update = ComplaintCaseEvidence.objects.filter(
        case_update=update, content_hash=content_hash,
    ).first()
    if existing_for_update and existing_for_update.upload_status == 'success':
        return
    duplicate = ComplaintCaseEvidence.objects.filter(
        parsed_message=case,
        content_hash=content_hash,
        upload_status='success',
    ).exclude(drive_url='').first()
    evidence = ComplaintCaseEvidence.objects.create(
        parsed_message=case,
        case_update=update,
        group_id=case.group_id,
        uploaded_by=actor.name,
        original_filename=str(getattr(file_obj, 'name', '') or ''),
        mime_type=detected_mime or str(getattr(file_obj, 'content_type', '') or ''),
        size=len(content),
        content_hash=content_hash,
    )
    if duplicate:
        evidence.drive_file_id = duplicate.drive_file_id
        evidence.drive_url = duplicate.drive_url
        evidence.upload_status = 'success'
        evidence.upload_error = 'Reused existing evidence upload.'
        evidence.save(update_fields=['drive_file_id', 'drive_url', 'upload_status', 'upload_error'])
        record_complaint_evidence(evidence, case, actor, action='complaint.evidence.reused')
        return
    try:
        file_id, file_url = GoogleDriveMediaStorage().upload(
            data=content,
            filename=evidence_filename(case, evidence.original_filename, index),
            mime_type=evidence.mime_type or 'application/octet-stream',
            id_number=f'CASE_{case.message_id}',
            received_at=timezone.now(),
            group_config=group_config,
            workflow_key='Complaint Cases',
            record_type='Case',
            record_key=case.message_id,
        )
    except Exception:
        logger.exception('Complaint evidence upload failed for evidence %s.', evidence.pk)
        evidence.upload_status = 'failed'
        evidence.upload_error = 'Evidence upload failed. Upload the file again to retry.'
        evidence.save(update_fields=['upload_status', 'upload_error'])
        record_complaint_evidence(evidence, case, actor, action='complaint.evidence.upload_failed')
        return
    evidence.drive_file_id = file_id
    evidence.drive_url = file_url
    evidence.upload_status = 'success'
    evidence.save(update_fields=['drive_file_id', 'drive_url', 'upload_status'])
    record_complaint_evidence(evidence, case, actor, action='complaint.evidence.uploaded')


def record_complaint_evidence(
    evidence: ComplaintCaseEvidence,
    case: ParsedMessage,
    actor: ComplaintCaseActor,
    *,
    action: str,
) -> None:
    """Log evidence handling without copying document names or document bytes."""
    from core.services.compliance_audit import record_event

    record_event(
        workflow='complaint_cases',
        action=action,
        category='document',
        origin='human',
        subject_type='complaint_case',
        subject_id=str(case.pk),
        customer_reference=str(case.message_id),
        actor=actor.user,
        authority_user=actor.user,
        actor_label=actor.name,
        authority_label=actor.name,
        source_model='ComplaintCaseEvidence',
        source_event_id=str(evidence.pk),
        deduplication_key=f'complaint:ComplaintCaseEvidence:{evidence.pk}',
        after_values={'upload_status': evidence.upload_status},
        metadata={
            'content_hash': evidence.content_hash,
            'mime_type': evidence.mime_type,
            'size': evidence.size,
            'case_update_id': str(evidence.case_update_id),
        },
        sensitive=True,
        occurred_at=evidence.created_at,
    )


def evidence_filename(case: ParsedMessage, original_filename: str, index: int) -> str:
    filename = get_valid_filename(original_filename or 'evidence')
    return f'CASE-{str(case.pk).replace("-", "")[:12]}-{index:02d}-{filename}'


def control_snapshot(control: ComplaintCaseControl, case: ParsedMessage) -> dict[str, Any]:
    return {
        'status': case.complaint_status or 'Open',
        'category_key': control.category.key if control.category_id else '',
        'branch_code': control.branch_ref.code if control.branch_ref_id else '',
        'customer_id': str(control.customer_id or ''),
        'customer_match_status': control.customer_match_status,
        'assigned_to_id': str(control.assigned_to_id or ''),
        'priority': control.priority,
        'sla_target_hours': control.sla_target_hours,
        'sla_started_at': control.sla_started_at.isoformat() if control.sla_started_at else '',
        'sla_due_at': control.sla_due_at.isoformat() if control.sla_due_at else '',
        'revision': control.revision,
        'sync_status': control.sync_status,
    }


def sla_payload(control: ComplaintCaseControl, case: ParsedMessage) -> dict[str, Any]:
    now = timezone.now()
    started = control.sla_started_at or case.timestamp or case.created_at
    due = control.sla_due_at
    elapsed = max(0, int((now - started).total_seconds() // 3600)) if started else 0
    remaining = int((due - now).total_seconds() // 3600) if due else None
    if case.complaint_status == 'Closed':
        state = 'closed'
    elif due and now > due:
        state = 'overdue'
    elif remaining is not None and remaining <= max(1, control.sla_target_hours // 4):
        state = 'due_soon'
    else:
        state = 'on_track'
    return {
        'state': state, 'elapsed_hours': elapsed, 'remaining_hours': remaining,
        'target_hours': control.sla_target_hours, 'due_at': format_datetime(due),
    }


def serialize_case(case: ParsedMessage) -> dict[str, Any]:
    control = ensure_case_control(case)
    return {
        'id': str(case.id),
        'case_id': case.message_id,
        'customer_name': case.customer_name,
        'customer_phone': case.customer_phone,
        'customer_id': case.customer_id,
        'branch': case.branch_region,
        'category': case.complaint_category,
        'description': case.complaint_description,
        'status': case.complaint_status or 'Open',
        'reported_at': format_datetime(case.timestamp),
        'recorded_at': format_datetime(case.created_at),
        'days_open': max(0, int((timezone.now() - (case.timestamp or case.created_at)).total_seconds() // 86400)),
        'risk_level': case.risk_level,
        'revision': control.revision,
        'priority': control.priority,
        'assigned_to': {
            'id': str(control.assigned_to_id),
            'name': (control.assigned_to.get_full_name() or control.assigned_to.get_username()),
        } if control.assigned_to_id else None,
        'customer_match_status': control.customer_match_status,
        'sync_status': control.sync_status,
        'sync_error': control.sync_error,
        'sla': sla_payload(control, case),
    }


def serialize_update(update: CaseUpdate) -> dict[str, Any]:
    return {
        'status': update.new_status,
        'note': update.resolution_text,
        'updated_by': update.updated_by,
        'created_at': format_datetime(update.created_at),
        'gps_link': update.gps_link,
    }


def serialize_evidence(evidence: ComplaintCaseEvidence) -> dict[str, Any]:
    return {
        'id': str(evidence.id),
        'name': evidence.original_filename,
        'url': f'/api/complaints/evidence/{evidence.id}/open/' if evidence.upload_status == 'success' else '',
        'status': evidence.upload_status,
        'created_at': format_datetime(evidence.created_at),
    }


def location_for_case(case: ParsedMessage) -> dict[str, str]:
    update = case.case_updates.exclude(latitude__isnull=True).exclude(longitude__isnull=True).first()
    if update:
        latitude, longitude = update.latitude, update.longitude
        return {'latitude': str(latitude), 'longitude': str(longitude), 'url': google_maps_url(latitude, longitude)}
    latitude, longitude = coordinates_from_link(case.gps_link)
    return {'latitude': latitude, 'longitude': longitude, 'url': case.gps_link or google_maps_url(latitude, longitude)}


def coordinates_from_link(link: str) -> tuple[str, str]:
    text = str(link or '')
    match = re.search(r'@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)', text)
    if not match:
        query = parse_qs(urlparse(text).query).get('q', [''])[0]
        match = re.match(r'(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)', query)
    return (match.group(1), match.group(2)) if match else ('', '')


def google_maps_url(latitude, longitude) -> str:
    if latitude in (None, '') or longitude in (None, ''):
        return ''
    return f'https://www.google.com/maps/search/?{urlencode({"api": "1", "query": f"{latitude},{longitude}"})}'


def format_datetime(value) -> str:
    return timezone.localtime(value).strftime('%d %b %Y %H:%M') if value else ''


def _case_queryset(group_id: str, actor: ComplaintCaseActor | None = None):
    cases = ParsedMessage.objects.filter(group_id=str(group_id)).select_related(
        'complaint_control__category', 'complaint_control__branch_ref',
        'complaint_control__customer', 'complaint_control__assigned_to',
    ).order_by('-timestamp', '-pk')
    if actor is not None:
        from core.services.workflow_access import scope_workflow_queryset
        cases = scope_workflow_queryset(
            cases, actor.user, 'complaint_cases', 'complaint.queue.view', access=actor.access,
            branch_field='branch_region', group_field='group_id',
        )
    return cases


def _case_for_group(group_id: str, case_id: str, actor: ComplaintCaseActor | None = None) -> ParsedMessage:
    case = _case_queryset(group_id, actor=actor).prefetch_related('case_updates', 'complaint_evidence').filter(message_id=str(case_id)).first()
    if not case:
        raise ComplaintCaseError('Complaint case was not found in this group.')
    return case


def _filter_status(cases, status: str):
    if status in STATUS_VALUES:
        return cases.filter(complaint_status=status)
    if status == 'active':
        return cases.filter(Q(complaint_status__in=ACTIVE_STATUSES) | Q(complaint_status=''))
    if status == 'closed':
        return cases.filter(complaint_status='Closed')
    return cases


def _filter_branch(cases, branch: str):
    text = str(branch or '').strip()
    return cases.filter(branch_region=text) if text else cases


def _filter_query(cases, query: str):
    text = str(query or '').strip()
    if not text:
        return cases
    return cases.filter(
        Q(message_id__icontains=text)
        | Q(customer_name__icontains=text)
        | Q(customer_phone__icontains=text)
        | Q(customer_id__icontains=text)
        | Q(branch_region__icontains=text)
        | Q(complaint_description__icontains=text)
    )


def _telegram_user(auth_payload: dict) -> dict:
    raw_user = (auth_payload or {}).get('user', '')
    try:
        return json.loads(raw_user) if raw_user else {}
    except json.JSONDecodeError:
        return {}


def create_complaint_launcher_start_param(group_id: str) -> str:
    payload = json.dumps({'group_id': str(group_id), 'launcher': 'jbl_apps'}, separators=(',', ':'))
    return base64.urlsafe_b64encode(payload.encode('utf-8')).decode('ascii').rstrip('=')


def decode_complaint_start_param(start_param: str) -> dict[str, str]:
    value = str(start_param or '').strip()
    if not value:
        return {}
    try:
        decoded = base64.urlsafe_b64decode(value + ('=' * (-len(value) % 4))).decode('utf-8')
        payload = json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return {'group_id': str(payload.get('group_id') or '')} if isinstance(payload, dict) else {}


def build_complaint_cases_launcher_url(group_id: str) -> str:
    bot_username = str(getattr(settings, 'TELEGRAM_BOT_USERNAME', '') or '').strip().lstrip('@')
    short_name = str(getattr(settings, 'COMPLAINT_CASES_MINI_APP_SHORT_NAME', '') or '').strip().strip('/')
    if bot_username and short_name:
        return f'https://t.me/{bot_username}/{short_name}?startapp={create_complaint_launcher_start_param(group_id)}'
    base_url = str(getattr(settings, 'APP_BASE_URL', '') or '').rstrip('/')
    return f'{base_url}/complaints/?{urlencode({"group_id": str(group_id)})}' if base_url else ''
