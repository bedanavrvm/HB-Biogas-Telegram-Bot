"""Validated, idempotent requirement evidence for Loan Origination."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.models import (
    LoanOriginationApplication,
    OriginationRequirementEvidence,
)
from core.services.loan_origination import OriginationConflict, OriginationError


logger = logging.getLogger(__name__)

ALLOWED_FILE_TYPES = {
    'application/pdf': {'.pdf'},
    'image/jpeg': {'.jpg', '.jpeg'},
    'image/png': {'.png'},
}


def _request_id(value: str) -> str:
    normalized = str(value or '').strip()[:128]
    if not normalized:
        raise OriginationError('A client request ID is required.')
    return normalized


def _document_requirement(application, requirement_key: str) -> dict[str, Any]:
    key = str(requirement_key or '').strip()
    for item in (application.product_terms_snapshot or {}).get('requirements', []):
        if not isinstance(item, dict) or str(item.get('key') or '') != key:
            continue
        if str(item.get('type') or '') != 'document':
            raise OriginationError('This product requirement does not accept a file.')
        workflow = str(item.get('workflow') or '')
        if workflow and workflow != 'loan_origination':
            break
        return item
    raise OriginationError('This document requirement is not part of the application snapshot.')


def _safe_filename(value: str, *, fallback: str) -> str:
    basename = Path(str(value or '')).name.strip()
    normalized = re.sub(r'[^A-Za-z0-9._ -]+', '_', basename).strip(' ._')
    return (normalized or fallback)[:180]


def validate_evidence_file(file_obj) -> tuple[str, int, str]:
    if file_obj is None:
        raise OriginationError('Choose a PDF, JPG, or PNG evidence file.')
    from core.services.order_approval import hash_uploaded_file

    digest, actual_size = hash_uploaded_file(file_obj)
    max_size = int(getattr(settings, 'ORIGINATION_EVIDENCE_MAX_FILE_SIZE_MB', 10)) * 1024 * 1024
    if actual_size <= 0:
        raise OriginationError('The evidence file is empty.')
    if actual_size > max_size:
        raise OriginationError(
            f'Evidence files must not exceed '
            f'{getattr(settings, "ORIGINATION_EVIDENCE_MAX_FILE_SIZE_MB", 10)} MB.',
        )
    extension = Path(str(getattr(file_obj, 'name', '') or '')).suffix.casefold()
    declared = str(getattr(file_obj, 'content_type', '') or '').split(';', 1)[0].strip().casefold()
    try:
        file_obj.seek(0)
        header = file_obj.read(16)
        file_obj.seek(0)
    except (AttributeError, OSError) as exc:
        raise OriginationError('The evidence file could not be read.') from exc
    detected = ''
    if header.startswith(b'%PDF-'):
        detected = 'application/pdf'
    elif header.startswith(b'\xff\xd8\xff'):
        detected = 'image/jpeg'
    elif header.startswith(b'\x89PNG\r\n\x1a\n'):
        detected = 'image/png'
    if not detected or extension not in ALLOWED_FILE_TYPES[detected]:
        raise OriginationError('Evidence must be a genuine PDF, JPG, or PNG file.')
    if declared and declared not in {detected, 'application/octet-stream'}:
        if not (detected == 'image/jpeg' and declared == 'image/jpg'):
            raise OriginationError('The evidence file type does not match its content.')
    if detected == 'application/pdf':
        try:
            from pypdf import PdfReader
            reader = PdfReader(file_obj, strict=False)
            if not reader.pages:
                raise ValueError('PDF has no pages')
            file_obj.seek(0)
        except Exception as exc:
            try:
                file_obj.seek(0)
            except (AttributeError, OSError):
                pass
            raise OriginationError('The evidence PDF is damaged or unsupported.') from exc
    elif detected.startswith('image/'):
        try:
            from PIL import Image
            Image.open(file_obj).verify()
            file_obj.seek(0)
        except Exception as exc:
            try:
                file_obj.seek(0)
            except (AttributeError, OSError):
                pass
            raise OriginationError('The evidence image is damaged or unsupported.') from exc
    return detected, actual_size, digest


def serialize_evidence(item: OriginationRequirementEvidence) -> dict[str, Any]:
    return {
        'id': str(item.pk),
        'requirement_key': item.requirement_key,
        'requirement_label': item.requirement_label,
        'filename': item.original_filename,
        'mime_type': item.mime_type,
        'byte_size': item.byte_size,
        'sha256': item.content_sha256,
        'status': item.status,
        'error': item.upload_error if item.status == item.STATUS_FAILED else '',
        'created_at': item.created_at.isoformat(),
        'download_url': (
            f'/api/origination/api/evidence/{item.pk}/download/'
            if item.status == item.STATUS_UPLOADED else ''
        ),
    }


def active_evidence(application) -> list[OriginationRequirementEvidence]:
    return list(application.requirement_evidence_files.filter(
        status=OriginationRequirementEvidence.STATUS_UPLOADED,
    ).order_by('requirement_key', 'created_at'))


def evidence_manifest(application) -> list[dict[str, Any]]:
    return [
        {
            'evidence_id': str(item.pk),
            'requirement_key': item.requirement_key,
            'requirement_label': item.requirement_label,
            'filename': item.original_filename,
            'mime_type': item.mime_type,
            'byte_size': item.byte_size,
            'sha256': item.content_sha256,
        }
        for item in active_evidence(application)
    ]


def requirement_has_evidence(application, requirement_key: str) -> bool:
    return application.requirement_evidence_files.filter(
        requirement_key=str(requirement_key or '').strip(),
        status=OriginationRequirementEvidence.STATUS_UPLOADED,
    ).exists()


@transaction.atomic
def _reserve_upload(
    *, application_id, actor, requirement_key: str, expected_revision: int,
    request_id: str, filename: str, mime_type: str, byte_size: int, sha256: str,
    allow_signing_actor: bool = False,
) -> tuple[OriginationRequirementEvidence, bool]:
    from core.services.loan_origination import _record_event

    application = LoanOriginationApplication.objects.select_for_update().get(pk=application_id)
    replay = application.requirement_evidence_files.filter(request_id=request_id).first()
    if replay:
        return replay, True
    if application.officer_id != actor.pk and not allow_signing_actor:
        raise OriginationError('Only the assigned officer may upload application evidence.')
    allowed_statuses = {application.STATUS_DRAFT, application.STATUS_CORRECTION_REQUIRED}
    if allow_signing_actor:
        allowed_statuses.add(application.STATUS_REVIEWED)
    if application.status not in allowed_statuses:
        raise OriginationError('Evidence can only be changed while the application is editable.')
    if application.status == application.STATUS_CORRECTION_REQUIRED:
        from core.services.loan_origination import correction_targets
        if requirement_key not in correction_targets(application)['requirement']:
            raise OriginationError('This evidence requirement is locked for the current correction.')
    requirement = _document_requirement(application, requirement_key)
    duplicate = application.requirement_evidence_files.filter(
        requirement_key=requirement_key, content_sha256=sha256,
        status=OriginationRequirementEvidence.STATUS_UPLOADED,
    ).first()
    if duplicate:
        return duplicate, True
    if int(expected_revision) != application.revision:
        raise OriginationConflict('This application changed. Refresh before uploading evidence.')
    max_files = int(getattr(settings, 'ORIGINATION_EVIDENCE_MAX_FILES_PER_REQUIREMENT', 5))
    if application.requirement_evidence_files.filter(
        requirement_key=requirement_key,
        status=OriginationRequirementEvidence.STATUS_UPLOADED,
    ).count() >= max_files:
        raise OriginationError(f'Upload at most {max_files} files for this requirement.')
    total_limit = int(getattr(settings, 'ORIGINATION_EVIDENCE_MAX_TOTAL_UPLOAD_MB', 30)) * 1024 * 1024
    current_total = sum(application.requirement_evidence_files.filter(
        status=OriginationRequirementEvidence.STATUS_UPLOADED,
    ).values_list('byte_size', flat=True))
    if current_total + byte_size > total_limit:
        raise OriginationError(
            f'Application evidence must not exceed '
            f'{getattr(settings, "ORIGINATION_EVIDENCE_MAX_TOTAL_UPLOAD_MB", 30)} MB in total.',
        )
    application.revision += 1
    application.save(update_fields=['revision', 'updated_at'])
    item = OriginationRequirementEvidence.objects.create(
        application=application,
        application_revision=application.revision,
        requirement_key=requirement_key,
        requirement_label=str(requirement.get('label') or requirement_key)[:160],
        original_filename=filename,
        mime_type=mime_type,
        byte_size=byte_size,
        content_sha256=sha256,
        request_id=request_id,
        uploaded_by=actor,
    )
    _record_event(
        application, 'evidence_upload_started', actor=actor, request_id=request_id,
        after={'evidence_id': str(item.pk), 'requirement_key': requirement_key},
    )
    return item, False


def upload_requirement_evidence(
    *, application_id, actor, requirement_key: str, expected_revision: int,
    request_id: str, file_obj,
    allow_signing_actor: bool = False,
) -> tuple[OriginationRequirementEvidence, bool]:
    request_id = _request_id(request_id)
    mime_type, byte_size, sha256 = validate_evidence_file(file_obj)
    filename = _safe_filename(
        getattr(file_obj, 'name', ''), fallback=f'{requirement_key}{next(iter(ALLOWED_FILE_TYPES[mime_type]))}',
    )
    item, replayed = _reserve_upload(
        application_id=application_id, actor=actor, requirement_key=requirement_key,
        expected_revision=expected_revision, request_id=request_id, filename=filename,
        mime_type=mime_type, byte_size=byte_size, sha256=sha256,
        allow_signing_actor=allow_signing_actor,
    )
    if replayed or item.status != item.STATUS_PENDING:
        return item, True
    try:
        from core.services.order_approval import GoogleDriveMediaStorage
        stored_name = f'{item.requirement_key}_{str(item.pk)[:8]}_{item.original_filename}'
        file_id, url = GoogleDriveMediaStorage().upload(
            file_obj, stored_name, item.mime_type,
            id_number=item.application.reference_number,
            received_at=item.created_at,
            workflow_key='Origination',
            record_type='Application',
            record_key=item.application.reference_number,
        )
    except Exception:
        logger.exception('Origination evidence Drive upload failed for evidence %s.', item.pk)
        item.status = item.STATUS_FAILED
        item.upload_error = 'Drive upload failed; select the file and retry.'
        item.save(update_fields=['status', 'upload_error', 'updated_at'])
        return item, False
    item.status = item.STATUS_UPLOADED
    item.drive_file_id = file_id
    item.drive_url = url
    item.upload_error = ''
    item.save(update_fields=[
        'status', 'drive_file_id', 'drive_url', 'upload_error', 'updated_at',
    ])
    return item, False


@transaction.atomic
def remove_requirement_evidence(
    *, evidence_id, actor, expected_revision: int, request_id: str,
    allow_signing_actor: bool = False,
) -> OriginationRequirementEvidence:
    from core.services.loan_origination import _record_event

    request_id = _request_id(request_id)
    item = OriginationRequirementEvidence.objects.select_for_update().select_related(
        'application',
    ).get(pk=evidence_id)
    application = LoanOriginationApplication.objects.select_for_update().get(pk=item.application_id)
    if application.events.filter(request_id=request_id).exists():
        return item
    if application.officer_id != actor.pk and not allow_signing_actor:
        raise OriginationError('Only the assigned officer may remove application evidence.')
    allowed_statuses = {application.STATUS_DRAFT, application.STATUS_CORRECTION_REQUIRED}
    if allow_signing_actor:
        allowed_statuses.add(application.STATUS_REVIEWED)
    if application.status not in allowed_statuses:
        raise OriginationError('Evidence can only be changed while the application is editable.')
    if application.status == application.STATUS_CORRECTION_REQUIRED:
        from core.services.loan_origination import correction_targets
        if item.requirement_key not in correction_targets(application)['requirement']:
            raise OriginationError('This evidence requirement is locked for the current correction.')
    if int(expected_revision) != application.revision:
        raise OriginationConflict('This application changed. Refresh before removing evidence.')
    if item.status == item.STATUS_REMOVED:
        return item
    application.revision += 1
    application.save(update_fields=['revision', 'updated_at'])
    item.status = item.STATUS_REMOVED
    item.removed_by = actor
    item.removed_at = timezone.now()
    item.save(update_fields=['status', 'removed_by', 'removed_at', 'updated_at'])
    _record_event(
        application, 'evidence_removed', actor=actor, request_id=request_id,
        after={'evidence_id': str(item.pk), 'requirement_key': item.requirement_key},
    )
    return item
