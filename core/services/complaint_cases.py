"""Complaint case Mini App services: authorization, case updates, map data, and evidence."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import base64
import binascii
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
    ComplaintCaseImportItem,
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


ACTIVE_STATUSES = {'Open', 'In Progress', 'Review Needed', ''}
STATUS_VALUES = {'Open', 'In Progress', 'Closed'}
MANAGER_ROLE = 'MANAGER'
CATEGORY_SUGGESTION_RULES = (
    ('relocation-request', (
        r'\brelocat(?:e|ed|ing|ion)\b', r'\b(?:move|moving|shift)\b.{0,30}\b(?:system|digester|unit)\b',
    )),
    ('installation-delay', (
        r'\binstall(?:ation|ed|ing)?\b.{0,45}\b(?:delay(?:ed)?|pending|waiting|not done|not happened|hasn.t happened)\b',
        r'\b(?:delay(?:ed)?|pending|waiting)\b.{0,30}\binstall(?:ation|ed|ing)?\b',
    )),
    ('commissioning-delay', (
        r'\b(?:commission(?:ing|ed)?|start[ -]?up)\b.{0,45}\b(?:delay(?:ed)?|pending|waiting|not done|not happened)\b',
        r'\b(?:delay(?:ed)?|pending|waiting)\b.{0,30}\b(?:commission(?:ing|ed)?|start[ -]?up)\b',
    )),
    ('accessories-delay', (
        r'\baccessor(?:y|ies)\b.{0,45}\b(?:delay(?:ed)?|pending|waiting|missing|not received|not delivered)\b',
        r'\b(?:delay(?:ed)?|pending|waiting|missing)\b.{0,30}\baccessor(?:y|ies)\b',
    )),
    ('leakage', (
        r'\bleak(?:age|ing|s|ed)?\b', r'\bgas\s+(?:is\s+)?escap(?:e|ing)\b', r'\b(?:smell|odou?r)\s+of\s+gas\b', r'\bgas\s+smell\b',
    )),
    ('blockage', (
        r'\bblock(?:age|ed|ing)?\b', r'\bclog(?:ged|ging)?\b', r'\b(?:inlet|outlet)\b.{0,25}\b(?:stuck|blocked|clogged)\b',
    )),
    ('burner-knob-fault', (
        r'\bburner\b', r'\bknob\b', r'\bignit(?:e|ion|ing)\b', r'\bflame\b', r'\bstove\b',
    )),
    ('system-performance', (
        r'\b(?:no|low|little|poor)\s+gas\b', r'\b(?:gas\s+)?production\b', r'\blow\s+pressure\b',
        r'\bpoor\s+(?:system\s+)?performance\b', r'\bsystem\b.{0,25}\bnot\s+work(?:ing)?\b',
    )),
    ('pipe-connection-fault', (
        r'\b(?:pipe|hose|connection|joint|valve)\b.{0,35}\b(?:fault|broken|damage(?:d)?|disconnect(?:ed)?|crack(?:ed)?|loose)\b',
        r'\b(?:broken|damage(?:d)?|disconnect(?:ed)?|crack(?:ed)?|loose)\b.{0,35}\b(?:pipe|hose|connection|joint|valve)\b',
    )),
)


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


def complaint_sheet_projection_enabled(group_config) -> bool:
    """Return the backwards-compatible Complaint Cases publication gate."""
    return bool(getattr(group_config, 'complaint_sheet_projection_enabled', True))


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


def suggest_category(group_config, description: Any) -> dict[str, Any]:
    """Suggest, but never assign, one active category from complaint text."""
    text = ' '.join(str(description or '').casefold().split())
    matched_keys = [
        key for key, patterns in CATEGORY_SUGGESTION_RULES
        if any(re.search(pattern, text) for pattern in patterns)
    ]
    # A leak in a pipe or connection is still primarily Leakage. This is the
    # only deliberate dominance rule; unrelated collisions stay ambiguous.
    if 'leakage' in matched_keys and 'pipe-connection-fault' in matched_keys:
        matched_keys.remove('pipe-connection-fault')
    categories = {category.key: category for category in available_categories(group_config)}
    matched = [categories[key] for key in matched_keys if key in categories]
    if len(matched) == 1:
        category = matched[0]
        return {
            'state': 'matched',
            'suggestion': {'key': category.key, 'label': category.label},
            'candidates': [],
        }
    if len(matched) > 1:
        return {
            'state': 'ambiguous', 'suggestion': None,
            'candidates': [{'key': item.key, 'label': item.label} for item in matched],
        }
    fallback = categories.get('other-complaint')
    return {
        'state': 'fallback',
        'suggestion': ({'key': fallback.key, 'label': fallback.label} if fallback else None),
        'candidates': [],
    }


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
        control = case.complaint_control
        return ensure_control_reference(control)
    except ComplaintCaseControl.DoesNotExist:
        pass
    category = None
    if group_config:
        try:
            category = resolve_category(group_config, case.complaint_category or 'General complaint')
        except ComplaintCaseError:
            categories = available_categories(group_config)
            category = categories.filter(key='other-complaint').first() or categories.filter(
                label__iexact='Other Complaint',
            ).first()
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
            'sync_status': (
                'success' if case.synced_to_sheets and not case.last_sync_error
                else ('pending' if complaint_sheet_projection_enabled(group_config) else 'not_required')
            ),
        },
    )
    return ensure_control_reference(control)


def staff_actor_for_user(group_config, canonical_user, *, identity=None) -> ComplaintCaseActor:
    """Authorize an already resolved canonical Django user for one complaint group."""
    if canonical_user is None or not canonical_user.is_active:
        raise ComplaintCaseError('Your Telegram account is not configured for complaint cases in this group.')
    profile = getattr(canonical_user, 'staff_profile', None)
    telegram_id = str(
        getattr(identity, 'telegram_id', '') or getattr(profile, 'telegram_id', '') or ''
    ).strip()
    username = str(
        getattr(identity, 'username', '') or getattr(profile, 'telegram_username', '') or ''
    ).strip().lower().lstrip('@')
    from core.services.telegram_identity import user_access
    access = user_access(canonical_user, 'complaint_cases', group_configuration=group_config)
    if not access['authorized']:
        raise ComplaintCaseError('Your Telegram account is not configured for complaint cases in this group.')
    roles = {str(role).upper() for role in access['roles']}
    role = MANAGER_ROLE if MANAGER_ROLE in roles else (
        'OFFICER' if 'OFFICER' in roles else ('HB_STAFF' if 'HB_STAFF' in roles else ('IT' if 'IT' in roles else ''))
    )
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


def staff_actor_for_payload(group_config, auth_payload: dict) -> ComplaintCaseActor:
    """Compatibility adapter for service callers that still hold raw auth fields."""
    user = _telegram_user(auth_payload)
    telegram_id = str(user.get('id') or '').strip()
    username = str(user.get('username') or '').strip().lower().lstrip('@')
    if not telegram_id and not username:
        raise ComplaintCaseError('Telegram identity is missing. Reopen Complaints from Telegram.')
    from core.services.telegram_identity import identity_from_user_payload, resolve_or_bind_telegram_user
    identity = identity_from_user_payload(user)
    canonical_user = resolve_or_bind_telegram_user(identity) if telegram_id else None
    return staff_actor_for_user(group_config, canonical_user, identity=identity)


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
    branch_values = set(configured_branches) | set(observed_branches)
    resolved = cases.filter(complaint_status='Closed').count()
    needs_details = cases.filter(complaint_status='Review Needed').count()
    total = cases.count()
    return {
        'actor': {
            'name': actor.name, 'role': actor.role, 'is_manager': actor.is_manager,
            'capabilities': sorted(actor.capabilities),
        },
        'statuses': ['pending', 'resolved', 'all'],
        'branches': sorted(branch_values, key=str.casefold),
        'categories': list(available_categories(group_config).values_list('label', flat=True)),
        'category_catalogue': list(available_categories(group_config).values('key', 'label', 'description')),
        'evidence_limits': {
            'max_files': int(getattr(settings, 'COMPLAINT_CASE_MAX_FILES_PER_UPDATE', 10)),
            'max_file_size_mb': int(getattr(settings, 'COMPLAINT_CASE_MAX_FILE_SIZE_MB', 10)),
            'max_total_upload_mb': int(getattr(settings, 'COMPLAINT_CASE_MAX_TOTAL_UPLOAD_MB', 30)),
        },
        'counts': {
            'pending': total - resolved,
            'resolved': resolved,
            'needs_details': needs_details,
            'total': total,
        },
    }


def list_cases_page(
    group_config, actor: ComplaintCaseActor | None = None, query: str = '', status: str = 'pending',
    branch: str = '', priority: str = '', assignment: str = '', sla: str = '', cursor: str = '', limit: int = 40,
    page: int | str | None = None, page_size: int = 10,
) -> dict[str, Any]:
    cases = _case_queryset(group_config.group_id, actor=actor)
    cases = _filter_status(cases, status)
    cases = _filter_query(cases, query)
    if status in {'pending', 'active'}:
        cases = cases.exclude(complaint_status='Closed').order_by('timestamp', 'pk')
    elif status in {'resolved', 'closed', 'Closed'}:
        cases = cases.filter(complaint_status='Closed').order_by('-date_resolved', '-timestamp', '-pk')
    else:
        cases = cases.order_by('-timestamp', '-pk')
    if page not in (None, ''):
        try:
            requested_page = max(1, int(page))
            bounded_page_size = max(1, min(int(page_size or 10), 10))
        except (TypeError, ValueError):
            raise ComplaintCaseError('The requested case-list page is invalid. Refresh the queue.')
        total = cases.count()
        pages = max(1, (total + bounded_page_size - 1) // bounded_page_size)
        current_page = min(requested_page, pages)
        offset = (current_page - 1) * bounded_page_size
        rows = list(cases[offset:offset + bounded_page_size])
        return {
            'items': [serialize_case(case) for case in rows],
            'next_cursor': '',
            'start_index': offset + 1 if rows else 0,
            'pagination': {
                'page': current_page,
                'pages': pages,
                'total': total,
                'page_size': bounded_page_size,
            },
        }
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
    return {
        'items': [serialize_case(case) for case in rows[:page_size]],
        'next_cursor': next_cursor,
        'start_index': 1,
        'pagination': None,
    }


def list_cases(group_config, actor: ComplaintCaseActor | None = None, **filters) -> list[dict[str, Any]]:
    """Compatibility list facade; HTTP callers use ``list_cases_page`` for cursors."""
    return list_cases_page(group_config, actor, **filters)['items']


def case_detail(group_config, case_id: str, actor: ComplaintCaseActor | None = None) -> dict[str, Any]:
    case = _case_for_group(group_config.group_id, case_id, actor=actor)
    payload = serialize_case(case)
    payload['sheet_projection_enabled'] = complaint_sheet_projection_enabled(group_config)
    if not payload['sheet_projection_enabled'] and payload['sync_status'] in {'pending', 'failed'}:
        payload['sync_status'] = 'suspended'
    payload['raw_message'] = case.raw_message
    payload['resolution_details'] = case.resolution_details
    updates = list(case.case_updates.all())
    payload['updates'] = [serialize_update(update) for update in updates]
    resolution = next((item for item in updates if item.new_status == 'Closed'), None)
    reopen = next((item for item in updates if item.old_status == 'Closed' and item.new_status != 'Closed'), None)
    payload['latest_resolution'] = serialize_update(resolution) if resolution else None
    payload['latest_reopen'] = serialize_update(reopen) if reopen else None
    payload['evidence'] = [serialize_evidence(evidence) for evidence in case.complaint_evidence.all()]
    payload['location'] = location_for_case(case)
    return payload


def update_case(
    group_config,
    actor: ComplaintCaseActor,
    case_id: str,
    fields: dict[str, Any],
    uploaded_files: list,
    *,
    required_capability: str = 'complaint.case.update',
) -> dict[str, Any]:
    request_id = str(fields.get('client_request_id') or '').strip()
    if not request_id:
        raise ComplaintCaseError('The update request is missing its retry identifier. Refresh and try again.')
    case = _case_for_group(group_config.group_id, case_id, actor=actor)
    # Complaint work is a shared queue inside the configured group. The case
    # lookup above enforces that hard boundary; branch-scoped grants must not
    # make a visible group case impossible to resolve or reopen.
    if not actor_can(group_config, actor, required_capability):
        raise ComplaintCaseError('Your role does not permit this complaint transition in the configured group.')
    control = ensure_case_control(case, group_config)
    existing_event = control.events.filter(request_id=request_id).first()
    if existing_event:
        existing = CaseUpdate.objects.filter(parsed_message=case, client_request_id=request_id).first()
        requested_status = str(fields.get('status') or '').strip()
        requested_note = str(
            fields.get('resolution_text') if fields.get('resolution_text') is not None else fields.get('reason') or ''
        ).strip()
        if not existing or existing.new_status != requested_status or existing.resolution_text != requested_note:
            raise ComplaintCaseError('That retry identifier was already used for a different transition.')
        if uploaded_files:
            validate_uploaded_files(uploaded_files)
            store_evidence(group_config, case, existing, actor, uploaded_files)
        return case_detail(group_config, case_id, actor)
    try:
        expected_revision = int(fields.get('expected_revision'))
    except (TypeError, ValueError):
        raise ComplaintCaseError('Refresh this case before saving; its revision is missing.')
    if control.revision != expected_revision:
        raise ComplaintCaseConflict(
            'This complaint changed while you were editing it. Review the latest resolution and your retained draft.',
            current_revision=control.revision,
        )
    validate_uploaded_files(uploaded_files)
    values = validate_update_fields(group_config, case, actor, {**fields, 'has_evidence': bool(uploaded_files)})
    payload_hash = mutation_payload_hash(values)
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


def resolve_case(group_config, actor, case_id: str, fields: dict[str, Any], uploaded_files: list) -> dict[str, Any]:
    """Resolve one pending complaint through the manager-only transition."""
    return update_case(
        group_config, actor, case_id,
        {**fields, 'status': 'Closed'}, uploaded_files,
        required_capability='complaint.case.close',
    )


def reopen_case(group_config, actor, case_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Return a resolved complaint to the shared queue with an audited reason."""
    reason = fields.get('reason') if fields.get('reason') is not None else fields.get('resolution_text')
    return update_case(
        group_config, actor, case_id,
        {**fields, 'status': 'Open', 'resolution_text': reason}, [],
        required_capability='complaint.case.reopen',
    )


def create_complaint_case(
    group_config,
    actor: ComplaintCaseActor,
    fields: dict[str, Any],
    uploaded_files: list,
) -> dict[str, Any]:
    if not actor_can(group_config, actor, 'complaint.case.create'):
        raise ComplaintCaseError('Your role does not permit creating complaints in this group.')
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
                    projection_enabled = complaint_sheet_projection_enabled(group_config)
                    control = create_case_control(case, values, group_config)
                    create_update = CaseUpdate.objects.create(
                        parsed_message=case,
                        group_id=case.group_id,
                        updated_by=actor.name,
                        old_status='',
                        new_status='Open',
                        resolution_text='Complaint recorded.',
                        raw_update_text='Complaint created in Complaint Cases Mini App',
                        source='mini_app_create',
                        client_request_id=request_id,
                        gps_link=values['gps_link'],
                        latitude=values['latitude'],
                        longitude=values['longitude'],
                        sync_status='pending' if projection_enabled else 'not_required',
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
    projection_enabled = complaint_sheet_projection_enabled(group_config)
    if not projection_enabled and not created:
        # A cached create retry after cutover must not erase a real pre-cutover
        # pending/failed publication. It remains suspended until re-enabled.
        return {
            'case': case_detail(group_config, case.message_id),
            'created': False,
            'synced_to_sheet': control.sync_status == 'success',
            'sheet_projection_enabled': False,
        }
    if projection_enabled:
        try:
            synced = sync_new_case_to_sheet(group_config, case)
        except Exception:
            logger.exception('Complaint creation publication failed for case %s.', case.pk)
            synced = False
        sync_status = 'success' if synced else 'failed'
        sync_error = '' if synced else (case.last_sync_error or 'Complaint register publication is pending.')
    else:
        synced = False
        sync_status = 'not_required'
        sync_error = ''
    control.sync_status = sync_status
    control.sync_error = sync_error
    control.last_sync_at = timezone.now() if synced else control.last_sync_at
    control.save(update_fields=['sync_status', 'sync_error', 'last_sync_at', 'updated_at'])
    if create_update:
        create_update.sync_status = sync_status
        create_update.sync_error = sync_error
        create_update.save(update_fields=['sync_status', 'sync_error'])
    return {
        'case': case_detail(group_config, case.message_id),
        'created': created,
        'synced_to_sheet': synced,
        'sheet_projection_enabled': projection_enabled,
    }


def create_request_id(value: Any) -> str:
    request_id = str(value or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{7,127}', request_id):
        raise ComplaintCaseError('The create request is missing a valid retry identifier. Refresh and try again.')
    return request_id


def validate_new_case_fields(group_config, fields: dict[str, Any]) -> dict[str, Any]:
    client_name = normalize_customer_name(fields.get('client_name'))
    branch_region = required_case_text(fields.get('branch_region'), 'Branch')
    category_text = required_case_text(fields.get('complaint_category'), 'Complaint category')
    complaint_description = required_description(fields.get('complaint_description'))
    customer_id = numeric_customer_id(fields.get('customer_id'))
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


def create_case_control(case: ParsedMessage, values: dict[str, Any], group_config=None) -> ComplaintCaseControl:
    priority = values['category'].default_priority
    target = {'high': 24, 'normal': 72, 'low': 120}[priority]
    started = case.timestamp or timezone.now()
    control = ComplaintCaseControl.objects.create(
        parsed_message=case,
        category=values['category'], branch_ref=values['branch_ref'],
        customer=values['customer'], customer_match_status=values['customer_match_status'],
        priority=priority, sla_target_hours=target, sla_started_at=started,
        sla_due_at=started + timedelta(hours=target),
        sync_status='pending' if complaint_sheet_projection_enabled(group_config) else 'not_required',
    )
    return ensure_control_reference(control)


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


def normalize_customer_name(value: Any) -> str:
    """Cap ordinary all-lower/all-upper name parts while preserving intentional mixed case."""
    text = ' '.join(required_case_text(value, 'Customer name').split())

    def capitalize_part(match):
        part = match.group(0)
        if part.islower() or part.isupper():
            return part[:1].upper() + part[1:].lower()
        return part

    return re.sub(r'[^\W\d_]+', capitalize_part, text, flags=re.UNICODE)


def numeric_customer_id(value: Any) -> str:
    """Validate an optional national ID as digits while preserving leading zeros."""
    text = limited_case_text(value, 'Customer ID')
    if text and (not text.isascii() or not text.isdigit()):
        raise ComplaintCaseError('Customer ID must contain numbers only.')
    return text


def complaint_case_message_id(group_id: str, request_id: str) -> str:
    return f'CMP-MA-{hashlib.sha256(f"{group_id}:{request_id}".encode()).hexdigest()[:24]}'


def next_complaint_case_id(group_config_or_id, *, reference_at=None) -> str:
    """Allocate the next staff-facing complaint reference for one group/year."""
    group_id = str(
        getattr(group_config_or_id, 'group_id', group_config_or_id) or 'default'
    )
    reference_time = reference_at or timezone.now()
    if timezone.is_naive(reference_time):
        reference_time = timezone.make_aware(
            reference_time, timezone.get_current_timezone()
        )
    year = timezone.localtime(reference_time).year
    sequence, _ = ComplaintCaseSequence.objects.select_for_update().get_or_create(
        group_id=group_id,
        year=year,
        defaults={'next_number': 1},
    )
    while True:
        number = sequence.next_number
        sequence.next_number = number + 1
        sequence.save(update_fields=['next_number', 'updated_at'])
        case_id = f'CMP-{year}-{number:03d}'
        if not ParsedMessage.objects.filter(group_id=group_id, message_id=case_id).exists():
            return case_id


@transaction.atomic
def next_complaint_reference() -> str:
    """Allocate one globally unique, short reference without exposing source message IDs."""
    sequence, _ = ComplaintCaseSequence.objects.select_for_update().get_or_create(
        group_id='__complaint_global__', year=0, defaults={'next_number': 1},
    )
    number = sequence.next_number
    sequence.next_number = number + 1
    sequence.save(update_fields=['next_number', 'updated_at'])
    return f'CMP{number:06d}'


@transaction.atomic
def ensure_control_reference(control: ComplaintCaseControl) -> ComplaintCaseControl:
    """Assign a reference once under a row lock; retries return the existing value."""
    locked = ComplaintCaseControl.objects.select_for_update().get(pk=control.pk)
    if not locked.reference_number:
        locked.reference_number = next_complaint_reference()
        locked.save(update_fields=['reference_number', 'updated_at'])
    return locked


def complete_review_details(
    group_config,
    actor: ComplaintCaseActor,
    case_id: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    """Complete identifiers on a Review Needed case and return it to Pending."""
    request_id = create_request_id(fields.get('client_request_id'))
    case = _case_for_group(group_config.group_id, case_id, actor=actor)
    if not actor_can(group_config, actor, 'complaint.case.details.complete', case):
        raise ComplaintCaseError('Your role does not permit completing complaint details in this group.')
    control = ensure_case_control(case, group_config)
    values = validate_review_completion_fields(group_config, case, fields)
    payload_hash = mutation_payload_hash(values)
    existing_event = control.events.filter(request_id=request_id).first()
    if existing_event:
        if existing_event.action != 'details_completed' or existing_event.payload_hash != payload_hash:
            raise ComplaintCaseError('That retry identifier was already used for different complaint details.')
        return case_detail(group_config, case_id, actor)
    try:
        expected_revision = int(fields.get('expected_revision'))
    except (TypeError, ValueError):
        raise ComplaintCaseError('Refresh this case before saving; its revision is missing.')
    if case.complaint_status != 'Review Needed':
        raise ComplaintCaseError('Only a complaint marked Needs More Information can use this action.')
    if control.revision != expected_revision:
        raise ComplaintCaseConflict(
            'This complaint changed while you were completing its details. Review the latest case and try again.',
            current_revision=control.revision,
        )
    projection_enabled = complaint_sheet_projection_enabled(group_config)
    try:
        case, control, update, replayed = _persist_review_completion(
            case=case,
            actor=actor,
            values=values,
            request_id=request_id,
            payload_hash=payload_hash,
            expected_revision=expected_revision,
            projection_enabled=projection_enabled,
        )
    except IntegrityError:
        replay = ComplaintCaseEvent.objects.filter(case=control, request_id=request_id).first()
        if replay and replay.action == 'details_completed' and replay.payload_hash == payload_hash:
            return case_detail(group_config, case_id, actor)
        raise
    if replayed:
        return case_detail(group_config, case_id, actor)
    if projection_enabled:
        try:
            synced = (
                update_sheet_case(group_config, case, {
                    'customer_phone': case.customer_phone,
                    'customer_id': case.customer_id,
                    'complaint_category': case.complaint_category,
                    'status': 'Open',
                })
                if case.synced_to_sheets else sync_new_case_to_sheet(group_config, case)
            )
        except Exception:
            logger.exception('Complaint detail-completion publication failed for case %s.', case.pk)
            synced = False
        update.sync_status = 'success' if synced else 'failed'
        update.sync_error = '' if synced else 'The local details are saved; complaint register publication is pending.'
    else:
        synced = False
        update.sync_status = 'not_required'
        update.sync_error = ''
    update.save(update_fields=['sync_status', 'sync_error'])
    control.sync_status = update.sync_status
    control.sync_error = update.sync_error
    control.last_sync_at = timezone.now() if synced else control.last_sync_at
    control.save(update_fields=['sync_status', 'sync_error', 'last_sync_at', 'updated_at'])
    return case_detail(group_config, case_id, actor)


def _persist_review_completion(
    *, case, actor, values, request_id: str, payload_hash: str,
    expected_revision: int, projection_enabled: bool,
):
    with transaction.atomic():
        case = ParsedMessage.objects.select_for_update().get(pk=case.pk)
        control = ComplaintCaseControl.objects.select_for_update().get(parsed_message=case)
        if case.complaint_status != 'Review Needed':
            replay = control.events.filter(request_id=request_id).first()
            if replay and replay.action == 'details_completed' and replay.payload_hash == payload_hash:
                update = CaseUpdate.objects.get(parsed_message=case, client_request_id=request_id)
                return case, control, update, True
            raise ComplaintCaseError('Only a complaint marked Needs More Information can use this action.')
        if control.revision != expected_revision:
            raise ComplaintCaseConflict(
                'This complaint changed while you were completing its details. Review the latest case and try again.',
                current_revision=control.revision,
            )
        before = control_snapshot(control, case)
        case.customer_phone = values['customer_phone']
        case.customer_id = values['customer_id']
        case.complaint_category = values['category'].label
        case.complaint_status = 'Open'
        case.save(update_fields=[
            'customer_phone', 'customer_id', 'complaint_category', 'complaint_status',
        ])
        control.category = values['category']
        control.customer = values['customer']
        control.customer_match_status = values['customer_match_status']
        control.revision += 1
        control.sync_status = 'pending' if projection_enabled else 'not_required'
        control.sync_error = ''
        control.save(update_fields=[
            'category', 'customer', 'customer_match_status', 'revision',
            'sync_status', 'sync_error', 'updated_at',
        ])
        update = CaseUpdate.objects.create(
            parsed_message=case,
            group_id=case.group_id,
            updated_by=actor.name,
            old_status='Review Needed',
            new_status='Open',
            resolution_text='Required customer details completed.',
            raw_update_text='Complaint review details completed in Complaint Cases Mini App',
            source='mini_app_review_completion',
            client_request_id=request_id,
            sync_status='pending' if projection_enabled else 'not_required',
        )
        ComplaintCaseEvent.objects.create(
            case=control,
            revision=control.revision,
            action='details_completed',
            actor=actor.user,
            actor_label=actor.name,
            request_id=request_id,
            payload_hash=payload_hash,
            before_values=before,
            after_values=control_snapshot(control, case),
            reason='Required customer identifiers and category confirmed.',
        )
        record_complaint_update(update, case, actor, action='complaint.case.details_completed')
        return case, control, update, False


def validate_review_completion_fields(group_config, case: ParsedMessage, fields: dict[str, Any]) -> dict[str, Any]:
    submitted_phone = str(fields.get('customer_phone') or '').strip()
    if case.customer_phone and submitted_phone:
        normalized_submitted = normalize_kenyan_phone(submitted_phone)
        normalized_existing = normalize_kenyan_phone(case.customer_phone) or case.customer_phone
        if normalized_submitted != normalized_existing:
            raise ComplaintCaseError('The existing phone number cannot be changed in this completion action.')
    phone_input = str(case.customer_phone or submitted_phone).strip()
    customer_phone = normalize_kenyan_phone(phone_input) if phone_input else ''
    if not customer_phone:
        raise ComplaintCaseError('Enter the missing valid Kenyan phone number.')
    submitted_id = numeric_customer_id(fields.get('customer_id'))
    existing_id = str(case.customer_id or '').strip()
    existing_id_is_numeric = bool(existing_id and existing_id.isascii() and existing_id.isdigit())
    if existing_id_is_numeric and submitted_id and submitted_id != existing_id:
        raise ComplaintCaseError('The existing customer ID cannot be changed in this completion action.')
    customer_id = existing_id if existing_id_is_numeric else submitted_id
    if not customer_id:
        raise ComplaintCaseError('Enter the missing customer ID.')
    category = resolve_category(group_config, fields.get('complaint_category') or case.complaint_category)
    customer, match_status = match_customer(customer_id, customer_phone)
    return {
        'customer_phone': customer_phone,
        'customer_id': customer_id,
        'category': category,
        'customer': customer,
        'customer_match_status': match_status,
    }


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
    if not complaint_sheet_projection_enabled(group_config):
        raise ComplaintCaseError('Sheet projection is disabled for this complaint group.')
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
    if status not in {'Open', 'Closed'}:
        raise ComplaintCaseError('Complaint cases can only be Pending or Resolved.')
    if status == 'Closed' and case.complaint_status != 'Closed' and not actor_can(group_config, actor, 'complaint.case.close'):
        raise ComplaintCaseError('Only authorized HomeBiogas resolution staff can resolve a complaint.')
    if case.complaint_status == 'Closed' and status != 'Closed' and not actor_can(group_config, actor, 'complaint.case.reopen'):
        raise ComplaintCaseError('Your role cannot reopen this complaint.')
    if case.complaint_status == 'Closed' and status == 'Closed':
        raise ComplaintCaseError('This complaint is already resolved.')
    if case.complaint_status != 'Closed' and status == 'Open':
        raise ComplaintCaseError('Use Resolve when the complaint has been addressed.')
    note = str(fields.get('resolution_text') or '').strip()
    if len(note) > 5000:
        raise ComplaintCaseError('The update note must be 5,000 characters or fewer.')
    if not note:
        raise ComplaintCaseError(
            'Add a resolution note.' if status == 'Closed' else 'Explain why this complaint needs to be reopened.'
        )
    latitude, longitude, gps_link = normalize_location(fields)
    return {
        'status': status, 'note': note, 'latitude': latitude, 'longitude': longitude,
        'gps_link': gps_link,
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
        projection_enabled = complaint_sheet_projection_enabled(group_config)
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
            sync_status='pending' if projection_enabled else 'not_required',
        )
        update_case_fields(case, values, resolution_details, resolved_at)
        reopened = before['status'] == 'Closed' and values['status'] == 'Open'
        action = 'reopened' if reopened else 'resolved'
        control.revision += 1
        control.sync_status = 'pending' if projection_enabled else 'not_required'
        control.sync_error = ''
        control.save(update_fields=['revision', 'sync_status', 'sync_error', 'updated_at'])
        ComplaintCaseEvent.objects.create(
            case=control, revision=control.revision, action=action, actor=actor.user,
            actor_label=actor.name, request_id=request_id, payload_hash=payload_hash,
            before_values=before, after_values=control_snapshot(control, case), reason=values['note'],
        )
        record_complaint_update(update, case, actor, action=f'complaint.case.{action}')
    if projection_enabled:
        try:
            synced = update_sheet_case(group_config, case, sheet_updates(values, resolution_details, resolved_at))
        except Exception:
            logger.exception('Complaint update publication failed for case %s.', case.pk)
            synced = False
        update.sync_status = 'success' if synced else 'failed'
        update.sync_error = '' if synced else 'The local update is saved; complaint register publication is pending.'
    else:
        synced = False
        update.sync_status = 'not_required'
        update.sync_error = ''
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
    if not complaint_sheet_projection_enabled(group_config):
        raise ComplaintCaseError('Sheet projection is disabled for this complaint group.')
    service = get_sheets_service(
        sheet_id=group_config.sheet_id,
        sheet_name=group_config.sheet_name,
        sheet_schema=group_config.sheet_schema_config,
    )
    return service.update_case_row(case.message_id, updates)


def retry_case_sync(group_config, actor: ComplaintCaseActor, case_id: str) -> dict[str, Any]:
    if not complaint_sheet_projection_enabled(group_config):
        raise ComplaintCaseError(
            'Sheet projection is disabled. Re-enable it before retrying suspended publications.'
        )
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


def evidence_for_preview(group_config, actor: ComplaintCaseActor, evidence_id: str) -> ComplaintCaseEvidence:
    evidence = ComplaintCaseEvidence.objects.select_related('parsed_message').filter(pk=evidence_id).first()
    if not evidence or evidence.upload_status != 'success' or not evidence.drive_file_id:
        raise ComplaintCaseError('Evidence is unavailable.')
    case = _case_for_group(group_config.group_id, evidence.parsed_message.message_id, actor=actor)
    if not actor_can(group_config, actor, 'complaint.case.evidence.view', case):
        raise ComplaintCaseError('Your role cannot view evidence for this case.')
    if evidence.mime_type not in {'image/jpeg', 'image/png', 'image/webp', 'application/pdf'}:
        raise ComplaintCaseError('This older evidence type cannot be previewed inside the Mini App.')
    return evidence


def record_evidence_preview(group_config, actor: ComplaintCaseActor, evidence: ComplaintCaseEvidence) -> None:
    case = _case_for_group(group_config.group_id, evidence.parsed_message.message_id, actor=actor)
    control = ensure_case_control(case, group_config)
    ComplaintCaseEvent.objects.create(
        case=control, revision=control.revision, action='evidence_opened', actor=actor.user,
        actor_label=actor.name, after_values={'evidence_id': str(evidence.pk)},
    )


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
            raise ComplaintCaseError('Evidence must be a genuine JPEG, PNG, WebP, or PDF file.')


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
    resolved = case.complaint_status == 'Closed'
    source = (
        {'type': 'officer', 'label': 'Recorded by an officer'}
        if case.source == 'complaint_mini_app'
        else {'type': 'telegram', 'label': 'Telegram report'}
    )
    try:
        imported = case.complaint_import_item
    except ComplaintCaseImportItem.DoesNotExist:
        imported = None
    if imported:
        batch = imported.batch
        source = {
            'type': 'batch',
            'label': 'Imported complaint',
            'actor': batch.actor_label or 'Uploader unavailable',
            'created_at': format_datetime(batch.created_at),
        }
    elif case.source == 'whatsapp_export':
        source = {'type': 'legacy_batch', 'label': 'Imported from another system'}
    reported_at = case.timestamp or case.created_at
    age_ended_at = case.date_resolved if resolved and case.date_resolved else timezone.now()
    age_days = max(0, int((age_ended_at - reported_at).total_seconds() // 86400))
    if resolved:
        age_label = f'Resolved after {age_days} day' + ('s' if age_days != 1 else '')
    else:
        age_label = 'Pending today' if age_days == 0 else f'Pending for {age_days} day' + ('s' if age_days != 1 else '')
    return {
        'id': str(case.id),
        'case_id': case.message_id,
        'reference_number': control.reference_number,
        'customer_name': case.customer_name,
        'customer_phone': case.customer_phone,
        'customer_id': case.customer_id,
        'branch': case.branch_region,
        'category': control.category.label if control.category_id else case.complaint_category,
        'description': case.complaint_description,
        'status': 'Resolved' if resolved else 'Pending',
        'stored_status': case.complaint_status or 'Open',
        'needs_details': case.complaint_status == 'Review Needed',
        'reported_at': format_datetime(case.timestamp),
        'recorded_at': format_datetime(case.created_at),
        'days_open': age_days,
        'age_label': age_label,
        'source_attribution': source,
        'risk_level': case.risk_level,
        'revision': control.revision,
        'customer_match_status': control.customer_match_status,
        'sync_status': control.sync_status,
        'sync_error': control.sync_error,
    }


def serialize_update(update: CaseUpdate) -> dict[str, Any]:
    return {
        'old_status': update.old_status,
        'status': update.new_status,
        'note': update.resolution_text,
        'updated_by': update.updated_by,
        'created_at': format_datetime(update.created_at),
        'gps_link': update.gps_link,
    }


def serialize_evidence(evidence: ComplaintCaseEvidence) -> dict[str, Any]:
    previewable = (
        evidence.upload_status == 'success'
        and bool(evidence.drive_file_id)
        and evidence.mime_type in {'image/jpeg', 'image/png', 'image/webp', 'application/pdf'}
    )
    return {
        'id': str(evidence.id),
        'name': evidence.original_filename,
        'mime_type': evidence.mime_type,
        'preview_url': f'/api/complaints/evidence/{evidence.id}/open/' if previewable else '',
        'previewable': previewable,
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
    # Complaint work is deliberately shared across branches inside one
    # configured Telegram group. The group filter above remains the hard
    # tenant boundary; branch-scoped AccessGrants do not hide group cases.
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
    if status == 'resolved':
        return cases.filter(complaint_status='Closed')
    if status == 'pending':
        return cases.exclude(complaint_status='Closed')
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
        | Q(complaint_control__reference_number__icontains=text)
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
