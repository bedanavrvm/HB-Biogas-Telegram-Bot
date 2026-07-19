"""Complaint case Mini App services: authorization, case updates, map data, and evidence."""
from __future__ import annotations

import hashlib
import json
import re
import base64
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.text import get_valid_filename

from core.models import CaseUpdate, ComplaintCaseEvidence, ComplaintCaseStaffMember, ParsedMessage
from core.services.order_approval import GoogleDriveMediaStorage
from core.services.sheets import get_sheets_service


ACTIVE_STATUSES = {'Open', 'In Progress'}
STATUS_VALUES = {'Open', 'In Progress', 'Closed'}
MANAGER_ROLE = 'MANAGER'
ALLOWED_DOCUMENT_TYPES = {
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}


class ComplaintCaseError(ValueError):
    """Staff-safe complaint Mini App validation error."""


@dataclass(frozen=True)
class ComplaintCaseActor:
    name: str
    telegram_id: str
    username: str
    role: str

    @property
    def is_manager(self) -> bool:
        return self.role == MANAGER_ROLE


def is_complaint_workflow(group_config) -> bool:
    return str((getattr(group_config, 'workflow', None) or {}).get('type') or 'case') == 'case'


def staff_actor_for_payload(group_config, auth_payload: dict) -> ComplaintCaseActor:
    user = _telegram_user(auth_payload)
    telegram_id = str(user.get('id') or '').strip()
    username = str(user.get('username') or '').strip().lower().lstrip('@')
    if not telegram_id and not username:
        raise ComplaintCaseError('Telegram identity is missing. Reopen Complaint Cases from Telegram.')
    identity_query = Q(telegram_user_id=telegram_id) if telegram_id else Q()
    if username:
        identity_query |= Q(telegram_username__iexact=username)
    staff = ComplaintCaseStaffMember.objects.filter(
        group_configuration__group_id=str(group_config.group_id),
        active=True,
    ).filter(identity_query).order_by('name').first()
    if not staff:
        raise ComplaintCaseError('Your Telegram account is not configured for complaint cases in this group.')
    return ComplaintCaseActor(
        name=staff.name,
        telegram_id=telegram_id,
        username=username,
        role=staff.role,
    )


def bootstrap_data(group_config, actor: ComplaintCaseActor) -> dict[str, Any]:
    cases = _case_queryset(group_config.group_id)
    return {
        'actor': {'name': actor.name, 'role': actor.role, 'is_manager': actor.is_manager},
        'statuses': sorted(STATUS_VALUES),
        'counts': {
            'open': cases.filter(complaint_status='Open').count(),
            'in_progress': cases.filter(complaint_status='In Progress').count(),
            'closed': cases.filter(complaint_status='Closed').count(),
        },
    }


def list_cases(group_config, query: str = '', status: str = 'active', limit: int = 50) -> list[dict[str, Any]]:
    cases = _case_queryset(group_config.group_id)
    cases = _filter_status(cases, status)
    cases = _filter_query(cases, query)
    return [serialize_case(case) for case in cases[:max(1, min(limit, 100))]]


def case_detail(group_config, case_id: str) -> dict[str, Any]:
    case = _case_for_group(group_config.group_id, case_id)
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
    case = _case_for_group(group_config.group_id, case_id)
    existing = CaseUpdate.objects.filter(parsed_message=case, client_request_id=request_id).first()
    if existing:
        return case_detail(group_config, case_id)
    validate_uploaded_files(uploaded_files)
    values = validate_update_fields(case, actor, {**fields, 'has_evidence': bool(uploaded_files)})
    try:
        update_record = apply_case_update(group_config, case, actor, values, request_id)
    except IntegrityError:
        # A double tap can race the optimistic lookup above. The database
        # constraint is authoritative; return the first completed update.
        return case_detail(group_config, case_id)
    store_evidence(group_config, case, update_record, actor, uploaded_files)
    return case_detail(group_config, case_id)


def validate_update_fields(case: ParsedMessage, actor: ComplaintCaseActor, fields: dict[str, Any]) -> dict[str, Any]:
    status = str(fields.get('status') or case.complaint_status or 'Open').strip()
    if status not in STATUS_VALUES:
        raise ComplaintCaseError('Select a valid case status.')
    if status == 'Closed' and not actor.is_manager:
        raise ComplaintCaseError('Only a case manager can close a complaint.')
    if case.complaint_status == 'Closed' and status != 'Closed' and not actor.is_manager:
        raise ComplaintCaseError('Only a case manager can reopen a complaint.')
    note = str(fields.get('resolution_text') or '').strip()
    latitude, longitude, gps_link = normalize_location(fields)
    if not note and not gps_link and not fields.get('has_evidence') and status == (case.complaint_status or 'Open'):
        raise ComplaintCaseError('Add a note, location, evidence, or a status change before saving.')
    return {'status': status, 'note': note, 'latitude': latitude, 'longitude': longitude, 'gps_link': gps_link}


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


def apply_case_update(group_config, case: ParsedMessage, actor: ComplaintCaseActor, values: dict[str, Any], request_id: str) -> CaseUpdate:
    resolved_at = timezone.now() if values['status'] == 'Closed' else None
    resolution_details = append_resolution_note(case.resolution_details, actor.name, values['note'])
    updates = sheet_updates(values, resolution_details, resolved_at)
    if updates and not update_sheet_case(group_config, case, updates):
        raise ComplaintCaseError('The complaint register could not be updated. Nothing was saved.')
    with transaction.atomic():
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
            sync_status='success',
        )
        update_case_fields(case, values, resolution_details, resolved_at)
    return update


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


def append_resolution_note(existing: str, actor_name: str, note: str) -> str:
    if not note:
        return existing or ''
    stamped_note = f'[{timezone.localtime():%d/%m/%Y %H:%M} {actor_name}] {note}'
    return '\n'.join(part for part in [existing.strip(), stamped_note] if part)


def validate_uploaded_files(uploaded_files: list) -> None:
    max_files = int(getattr(settings, 'COMPLAINT_CASE_MAX_FILES_PER_UPDATE', 10))
    max_bytes = int(getattr(settings, 'COMPLAINT_CASE_MAX_TOTAL_UPLOAD_MB', 30)) * 1024 * 1024
    if len(uploaded_files) > max_files:
        raise ComplaintCaseError(f'Upload at most {max_files} evidence files at a time.')
    total_size = sum(int(getattr(file_obj, 'size', 0) or 0) for file_obj in uploaded_files)
    if total_size > max_bytes:
        raise ComplaintCaseError('The selected evidence files are too large for one update.')
    for file_obj in uploaded_files:
        if not allowed_upload(file_obj):
            raise ComplaintCaseError('Evidence must be an image, PDF, Word document, or supported document file.')


def allowed_upload(file_obj) -> bool:
    mime_type = str(getattr(file_obj, 'content_type', '') or '').lower()
    suffix = Path(str(getattr(file_obj, 'name', '') or '')).suffix.lower()
    image_suffixes = {'.jpg', '.jpeg', '.png', '.webp'}
    document_suffixes = {'.pdf', '.doc', '.docx'}
    if mime_type.startswith('image/'):
        return suffix in image_suffixes
    if mime_type in ALLOWED_DOCUMENT_TYPES:
        return suffix in document_suffixes
    return False


def store_evidence(group_config, case: ParsedMessage, update: CaseUpdate, actor: ComplaintCaseActor, uploaded_files: list) -> None:
    for index, file_obj in enumerate(uploaded_files, start=1):
        store_evidence_file(group_config, case, update, actor, file_obj, index)


def store_evidence_file(group_config, case, update, actor, file_obj, index: int) -> None:
    content = file_obj.read()
    content_hash = hashlib.sha256(content).hexdigest()
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
        mime_type=str(getattr(file_obj, 'content_type', '') or ''),
        size=len(content),
        content_hash=content_hash,
    )
    if duplicate:
        evidence.drive_file_id = duplicate.drive_file_id
        evidence.drive_url = duplicate.drive_url
        evidence.upload_status = 'success'
        evidence.upload_error = 'Reused existing evidence upload.'
        evidence.save(update_fields=['drive_file_id', 'drive_url', 'upload_status', 'upload_error'])
        return
    try:
        file_id, file_url = GoogleDriveMediaStorage().upload(
            data=content,
            filename=evidence_filename(case, evidence.original_filename, index),
            mime_type=evidence.mime_type or 'application/octet-stream',
            id_number=f'CASE_{case.message_id}',
            received_at=timezone.now(),
            group_config=group_config,
        )
    except Exception:
        evidence.upload_status = 'failed'
        evidence.upload_error = 'Evidence upload failed. Upload the file again to retry.'
        evidence.save(update_fields=['upload_status', 'upload_error'])
        return
    evidence.drive_file_id = file_id
    evidence.drive_url = file_url
    evidence.upload_status = 'success'
    evidence.save(update_fields=['drive_file_id', 'drive_url', 'upload_status'])


def evidence_filename(case: ParsedMessage, original_filename: str, index: int) -> str:
    filename = get_valid_filename(original_filename or 'evidence')
    return f'CASE-{get_valid_filename(case.message_id)}-{index:02d}-{filename}'


def serialize_case(case: ParsedMessage) -> dict[str, Any]:
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
        'days_open': case.days_open,
        'risk_level': case.risk_level,
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
        'url': evidence.drive_url,
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


def _case_queryset(group_id: str):
    return ParsedMessage.objects.filter(group_id=str(group_id)).prefetch_related('case_updates', 'complaint_evidence').order_by('-timestamp')


def _case_for_group(group_id: str, case_id: str) -> ParsedMessage:
    case = _case_queryset(group_id).filter(message_id=str(case_id)).first()
    if not case:
        raise ComplaintCaseError('Complaint case was not found in this group.')
    return case


def _filter_status(cases, status: str):
    if status == 'active':
        return cases.filter(Q(complaint_status__in=ACTIVE_STATUSES) | Q(complaint_status=''))
    if status == 'closed':
        return cases.filter(complaint_status='Closed')
    return cases


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
