"""Validation, Drive persistence, activation, and retrieval of legal templates."""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.core.validators import validate_slug
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from pypdf import PdfReader

from core.models import OriginationDocumentTemplate, OriginationDocumentTemplateEvent


class OriginationTemplateError(ValueError):
    """Stable, staff-safe template management error."""


def validate_template_files(pdf_data: bytes, config_data: bytes) -> tuple[dict[str, Any], str, int]:
    limit = max(1, int(getattr(settings, 'ORIGINATION_TEMPLATE_MAX_FILE_SIZE_MB', 15))) * 1024 * 1024
    if not pdf_data or len(pdf_data) > limit:
        raise OriginationTemplateError(f'The PDF must be no larger than {limit // (1024 * 1024)} MB.')
    if not pdf_data.startswith(b'%PDF'):
        raise OriginationTemplateError('The template file is not a valid PDF.')
    if not config_data or len(config_data) > 1024 * 1024:
        raise OriginationTemplateError('The placement configuration must be no larger than 1 MB.')
    try:
        reader = PdfReader(BytesIO(pdf_data))
        page_count = len(reader.pages)
    except Exception as exc:
        raise OriginationTemplateError('The template PDF cannot be read.') from exc
    if page_count < 1:
        raise OriginationTemplateError('The template PDF has no pages.')
    try:
        config = json.loads(config_data.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OriginationTemplateError('The placement configuration must be valid UTF-8 JSON.') from exc
    if not isinstance(config, dict):
        raise OriginationTemplateError('The placement configuration must be a JSON object.')
    document_type = str(config.get('document_type') or '').strip()
    version = config.get('version')
    fields = (config.get('field_overlay_manifest') or {}).get('fields')
    if not document_type or isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise OriginationTemplateError('The configuration requires document_type and a positive integer version.')
    try:
        validate_slug(document_type)
    except ValidationError as exc:
        raise OriginationTemplateError('The document_type must be a lowercase slug.') from exc
    if not isinstance(fields, dict) or not fields:
        raise OriginationTemplateError('The configuration requires a non-empty field overlay manifest.')
    for field_name, spec in fields.items():
        if not isinstance(spec, dict) or not str(spec.get('context_key') or '').strip():
            raise OriginationTemplateError(f'Field {field_name} requires a context_key.')
        try:
            page_number = int(spec.get('page_number') or 0)
        except (TypeError, ValueError) as exc:
            raise OriginationTemplateError(f'Field {field_name} has an invalid page number.') from exc
        if page_number < 1 or page_number > page_count:
            raise OriginationTemplateError(f'Field {field_name} references a page outside the PDF.')
        box = spec.get('box')
        if not isinstance(box, dict) or any(key not in box for key in ('x', 'y', 'width', 'height')):
            raise OriginationTemplateError(f'Field {field_name} requires a complete placement box.')
        try:
            if float(box['width']) <= 0 or float(box['height']) <= 0:
                raise ValueError
            float(box['x'])
            float(box['y'])
        except (TypeError, ValueError) as exc:
            raise OriginationTemplateError(f'Field {field_name} has invalid placement coordinates.') from exc
    return config, hashlib.sha256(pdf_data).hexdigest(), page_count


def create_template(*, pdf_file, config_file, name: str, actor) -> OriginationDocumentTemplate:
    """Create an immutable record and archive its PDF in the restricted Drive folder."""
    pdf_data = pdf_file.read()
    config_data = config_file.read()
    config, digest, page_count = validate_template_files(pdf_data, config_data)
    document_type = str(config['document_type']).strip()
    version = int(config['version'])
    filename = str(getattr(pdf_file, 'name', '') or f'{document_type}-v{version}.pdf')[:255]
    with transaction.atomic():
        template = OriginationDocumentTemplate.objects.create(
            document_type=document_type,
            name=str(name or filename).strip()[:180],
            version=version,
            source_filename=filename,
            source_sha256=digest,
            source_byte_size=len(pdf_data),
            page_count=page_count,
            placement_config=config,
            created_by=actor,
        )
        OriginationDocumentTemplateEvent.objects.create(
            template=template, action='created', actor=actor,
            metadata={'sha256': digest, 'byte_size': len(pdf_data), 'page_count': page_count},
        )
    return upload_template_record(template, pdf_data=pdf_data, actor=actor)


def upload_template_record(template: OriginationDocumentTemplate, *, pdf_data: bytes, actor) -> OriginationDocumentTemplate:
    """Upload a validated, already-persisted template record and retain failures for audit."""
    folder_id = str(getattr(settings, 'ORIGINATION_TEMPLATE_DRIVE_FOLDER_ID', '') or '').strip()
    if not folder_id:
        error = 'ORIGINATION_TEMPLATE_DRIVE_FOLDER_ID is not configured.'
        template.status = template.STATUS_UPLOAD_FAILED
        template.upload_error = error
        template.save(update_fields=['status', 'upload_error', 'updated_at'])
        OriginationDocumentTemplateEvent.objects.create(template=template, action='upload_failed', actor=actor)
        return template
    try:
        from core.services.order_approval import GoogleDriveMediaStorage
        file_id, url = GoogleDriveMediaStorage(parent_folder_id=folder_id).upload(
            pdf_data, template.source_filename, 'application/pdf', template.document_type, timezone.now(),
            workflow_key='Loan Origination/Templates', record_type=template.document_type,
            record_key=f'v{template.version}-{template.source_sha256[:12]}',
        )
    except Exception as exc:
        template.status = template.STATUS_UPLOAD_FAILED
        template.upload_error = 'Drive upload failed; retry with a new template version.'
        template.save(update_fields=['status', 'upload_error', 'updated_at'])
        OriginationDocumentTemplateEvent.objects.create(template=template, action='upload_failed', actor=actor)
        return template
    template.drive_file_id = file_id
    template.drive_url = url
    template.upload_error = ''
    template.save(update_fields=['drive_file_id', 'drive_url', 'upload_error', 'updated_at'])
    OriginationDocumentTemplateEvent.objects.create(template=template, action='uploaded', actor=actor)
    return template


@transaction.atomic
def activate_template(template: OriginationDocumentTemplate, *, actor) -> OriginationDocumentTemplate:
    template = OriginationDocumentTemplate.objects.select_for_update().get(pk=template.pk)
    if not template.drive_file_id or template.status == template.STATUS_UPLOAD_FAILED:
        raise OriginationTemplateError('Only a successfully uploaded template can be activated.')
    if template.created_by_id == getattr(actor, 'pk', None):
        raise OriginationTemplateError('A different administrator must review and activate this template.')
    try:
        from core.services.order_approval import GoogleDriveMediaStorage
        folder_id = str(getattr(settings, 'ORIGINATION_TEMPLATE_DRIVE_FOLDER_ID', '') or '').strip()
        if not folder_id:
            raise OriginationTemplateError('ORIGINATION_TEMPLATE_DRIVE_FOLDER_ID is not configured.')
        source = GoogleDriveMediaStorage(parent_folder_id=folder_id).download(template.drive_file_id)
    except Exception as exc:
        raise OriginationTemplateError('The template could not be retrieved from Drive for review.') from exc
    if hashlib.sha256(source).hexdigest() != template.source_sha256:
        raise OriginationTemplateError('The Drive file failed integrity verification and cannot be activated.')
    previous = list(OriginationDocumentTemplate.objects.select_for_update().filter(
        document_type=template.document_type, status=template.STATUS_ACTIVE,
    ).exclude(pk=template.pk))
    for old in previous:
        old.status = old.STATUS_RETIRED
        old.save(update_fields=['status', 'updated_at'])
        OriginationDocumentTemplateEvent.objects.create(template=old, action='retired', actor=actor)
    template.status = template.STATUS_ACTIVE
    template.activated_by = actor
    template.activated_at = timezone.now()
    template.save(update_fields=['status', 'activated_by', 'activated_at', 'updated_at'])
    OriginationDocumentTemplateEvent.objects.create(template=template, action='activated', actor=actor)
    return template


def load_active_template(
    document_type: str,
    version: int | None = None,
    expected_sha256: str = '',
) -> tuple[bytes, dict[str, Any]]:
    query = OriginationDocumentTemplate.objects.filter(document_type=document_type, status='active')
    if version is not None:
        query = query.filter(version=version)
    template = query.order_by('-version').first()
    if not template:
        raise OriginationTemplateError('No active document template is configured. Upload and activate it in Django Admin.')
    if expected_sha256 and template.source_sha256 != str(expected_sha256).strip().lower():
        raise OriginationTemplateError('The active template does not match the version approved by this loan product.')
    cache_key = f'origination-template:{template.pk}:{template.source_sha256}'
    source = cache.get(cache_key)
    if source is None:
        try:
            from core.services.order_approval import GoogleDriveMediaStorage
            folder_id = str(getattr(settings, 'ORIGINATION_TEMPLATE_DRIVE_FOLDER_ID', '') or '').strip()
            if not folder_id:
                raise OriginationTemplateError('ORIGINATION_TEMPLATE_DRIVE_FOLDER_ID is not configured.')
            source = GoogleDriveMediaStorage(parent_folder_id=folder_id).download(template.drive_file_id)
        except Exception as exc:
            raise OriginationTemplateError('The active document template could not be retrieved from Drive.') from exc
        if hashlib.sha256(source).hexdigest() != template.source_sha256:
            raise OriginationTemplateError('The active document template failed integrity verification.')
        cache.set(cache_key, source, timeout=600)
    return source, template.placement_config
