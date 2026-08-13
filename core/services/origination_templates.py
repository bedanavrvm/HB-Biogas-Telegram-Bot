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
from django.db import models, transaction
from django.utils import timezone
from pypdf import PdfReader

from core.models import (
    OriginationDocumentTemplate,
    OriginationDocumentTemplateEvent,
    OriginationProductDefinition,
    OriginationProductDefinitionEvent,
    OriginationTemplateConfigurationRevision,
)


class OriginationTemplateError(ValueError):
    """Stable, staff-safe template management error."""


SYSTEM_CONTEXT_KEYS = (
    ('reference_number', 'Reference Number'),
    ('branch_code', 'Branch Code'),
    ('loan_officer_name', 'Loan Officer Name'),
    ('application_date', 'Application Date'),
)


def validate_template_pdf(pdf_data: bytes) -> tuple[str, int]:
    """Validate an immutable PDF source without requiring placement JSON."""
    limit = max(1, int(getattr(settings, 'ORIGINATION_TEMPLATE_MAX_FILE_SIZE_MB', 15))) * 1024 * 1024
    if not pdf_data or len(pdf_data) > limit:
        raise OriginationTemplateError(f'The PDF must be no larger than {limit // (1024 * 1024)} MB.')
    if not pdf_data.startswith(b'%PDF'):
        raise OriginationTemplateError('The template file is not a valid PDF.')
    try:
        reader = PdfReader(BytesIO(pdf_data))
        page_count = len(reader.pages)
    except Exception as exc:
        raise OriginationTemplateError('The template PDF cannot be read.') from exc
    if page_count < 1:
        raise OriginationTemplateError('The template PDF has no pages.')
    return hashlib.sha256(pdf_data).hexdigest(), page_count


def initial_template_configuration(product: OriginationProductDefinition) -> dict[str, Any]:
    sample_context = {}
    for field in (product.form_schema or {}).get('fields', []) or []:
        key = str(field.get('key') or '').strip()
        if not key:
            continue
        field_type = str(field.get('type') or 'text')
        if field_type == 'boolean':
            value = True
        elif field_type in {'money', 'number'}:
            value = '12,500'
        elif field_type == 'date':
            value = '13-Aug-2026'
        elif field_type == 'choice':
            value = next(iter(field.get('options') or []), field.get('label') or key)
        else:
            value = field.get('label') or key.replace('_', ' ').title()
        sample_context[key] = value
    sample_context.update({
        'reference_number': 'ORG-2026-SAMPLE',
        'branch_code': 'Sample Branch',
        'loan_officer_name': 'Sample Loan Officer',
        'application_date': '13-Aug-2026',
    })
    return {
        'document_type': product.document_type,
        'version': product.version,
        'field_overlay_manifest': {
            'defaults': {
                'font': 'Helvetica', 'font_size': 8, 'min_font_size': 5,
                'text_case': 'none', 'align': 'left', 'vertical_align': 'bottom',
                'fit': 'shrink', 'padding': {'x': 0, 'y': 0},
            },
            'fields': {},
        },
        'signature_overlay_manifest': {'slots': {}},
        'sample_context': sample_context,
    }


def validate_template_files(pdf_data: bytes, config_data: bytes) -> tuple[dict[str, Any], str, int]:
    digest, page_count = validate_template_pdf(pdf_data)
    if not config_data or len(config_data) > 1024 * 1024:
        raise OriginationTemplateError('The placement configuration must be no larger than 1 MB.')
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
    return config, digest, page_count


def _template_product(template: OriginationDocumentTemplate) -> OriginationProductDefinition | None:
    if template.product_definition_id:
        return template.product_definition
    return OriginationProductDefinition.objects.filter(
        document_type=template.document_type, is_active=True,
    ).order_by('-version').first()


def _expected_signature_slots(product: OriginationProductDefinition | None) -> dict[str, dict[str, Any]]:
    expected = {}
    for rule in (product.signer_rules if product else []) or []:
        if not isinstance(rule, dict):
            continue
        role = str(rule.get('role') or '').strip()
        for raw_slot in rule.get('slots', []) or []:
            slot = {'key': raw_slot} if isinstance(raw_slot, str) else dict(raw_slot or {})
            slot_key = str(slot.get('key') or '').strip()
            if not role or not slot_key:
                continue
            identity = f'{role}.{slot_key}'
            expected[identity] = {
                'role': role,
                'slot_key': slot_key,
                'label': str(slot.get('label') or slot_key.replace('_', ' ').title()),
                'slot_type': str(slot.get('type') or rule.get('slot_type') or 'signature'),
                'required': bool(slot.get('required', rule.get('required', False))),
            }
    return expected


def validate_template_configuration(
    config: Any, *, template: OriginationDocumentTemplate, require_complete: bool = True,
) -> dict[str, Any]:
    """Validate a calibration draft against its product contract and PDF geometry."""
    if not isinstance(config, dict):
        raise OriginationTemplateError('Template configuration must be a JSON object.')
    normalized = json.loads(json.dumps(config))
    if str(normalized.get('document_type') or '') != template.document_type:
        raise OriginationTemplateError('The calibration document type does not match this template.')
    if int(normalized.get('version') or 0) != template.version:
        raise OriginationTemplateError('The calibration version does not match this template.')
    fields = (normalized.get('field_overlay_manifest') or {}).get('fields')
    if not isinstance(fields, dict):
        raise OriginationTemplateError('The calibrated field collection must be an object.')
    if require_complete and not fields:
        raise OriginationTemplateError('At least one calibrated field is required.')
    product = _template_product(template)
    schema_fields = (product.form_schema or {}).get('fields', []) if product else []
    known_context_keys = {str(item.get('key') or '') for item in schema_fields if item.get('key')}
    known_context_keys.update(key for key, _label in SYSTEM_CONTEXT_KEYS)
    configured_context_keys = {
        str(spec.get('context_key') or '').strip() for spec in fields.values() if isinstance(spec, dict)
    }
    unknown = sorted(configured_context_keys - known_context_keys) if known_context_keys else []
    if unknown:
        raise OriginationTemplateError(f'Unknown application fields: {", ".join(unknown)}.')
    if require_complete and template.product_definition_id:
        required = {str(item.get('key')) for item in schema_fields if item.get('required') and item.get('key')}
        missing = sorted(required - configured_context_keys)
        if missing:
            raise OriginationTemplateError(f'Required application fields are not calibrated: {", ".join(missing)}.')
    reader = PdfReader(BytesIO(load_template_source(template)))
    page_sizes = {
        index + 1: (float(page.mediabox.width), float(page.mediabox.height))
        for index, page in enumerate(reader.pages)
    }
    def validate_box(key: str, spec: dict[str, Any], *, item_label: str) -> None:
        try:
            page_number = int(spec.get('page_number') or 0)
        except (TypeError, ValueError) as exc:
            raise OriginationTemplateError(f'{item_label} {key} has an invalid page number.') from exc
        if page_number < 1 or page_number > template.page_count:
            raise OriginationTemplateError(f'{item_label} {key} references a page outside the PDF.')
        box = spec.get('allowed_area') or spec.get('box')
        if not isinstance(box, dict):
            raise OriginationTemplateError(f'{item_label} {key} requires a placement box.')
        scale = 72 / 25.4 if spec.get('units', 'pt') == 'mm' else 1
        try:
            x, y = float(box['x']) * scale, float(box['y']) * scale
            width, height = float(box['width']) * scale, float(box['height']) * scale
        except (KeyError, TypeError, ValueError) as exc:
            raise OriginationTemplateError(f'{item_label} {key} has invalid placement coordinates.') from exc
        if min(x, y) < 0 or width <= 0 or height <= 0:
            raise OriginationTemplateError(f'{item_label} {key} has invalid placement dimensions.')
        page_width, page_height = page_sizes[page_number]
        if x + width > page_width or y + height > page_height:
            raise OriginationTemplateError(f'{item_label} {key} extends outside page {page_number}.')

    for key, spec in fields.items():
        if not isinstance(spec, dict) or not str(spec.get('context_key') or '').strip():
            raise OriginationTemplateError(f'Field {key} requires a context key.')
        if str(spec.get('render_as') or 'text') not in {'text', 'checkbox'}:
            raise OriginationTemplateError(f'Field {key} has an unsupported rendering mode.')
        validate_box(key, spec, item_label='Field')

    signature_slots = (normalized.get('signature_overlay_manifest') or {}).get('slots', {})
    if not isinstance(signature_slots, dict):
        raise OriginationTemplateError('The signature slot collection must be an object.')
    expected_slots = _expected_signature_slots(product)
    unknown_slots = sorted(set(signature_slots) - set(expected_slots)) if expected_slots else []
    if unknown_slots:
        raise OriginationTemplateError(f'Unknown signature slots: {", ".join(unknown_slots)}.')
    if require_complete and template.product_definition_id:
        missing_slots = sorted(
            identity for identity, spec in expected_slots.items()
            if spec.get('required') and identity not in signature_slots
        )
        if missing_slots:
            raise OriginationTemplateError(f'Required signature slots are not calibrated: {", ".join(missing_slots)}.')
    for key, spec in signature_slots.items():
        if not isinstance(spec, dict):
            raise OriginationTemplateError(f'Signature slot {key} is invalid.')
        slot_type = str(spec.get('slot_type') or expected_slots.get(key, {}).get('slot_type') or 'signature')
        if slot_type not in {'signature', 'stamp'}:
            raise OriginationTemplateError(f'Signature slot {key} has an unsupported type.')
        validate_box(key, spec, item_label='Signature slot')
    return normalized


@transaction.atomic
def save_calibration_draft(*, template: OriginationDocumentTemplate, configuration: Any, actor, expected_revision: int) -> OriginationTemplateConfigurationRevision:
    template = OriginationDocumentTemplate.objects.select_for_update().get(pk=template.pk)
    if template.product_definition_id and template.product_definition.lifecycle_status != OriginationProductDefinition.STATUS_DRAFT:
        raise OriginationTemplateError('Published product versions are immutable. Create a new product version to change its template.')
    latest = template.configuration_revisions.order_by('-revision').first()
    current_revision = latest.revision if latest else 0
    normalized = validate_template_configuration(
        configuration, template=template, require_complete=False,
    )
    if int(expected_revision) != current_revision:
        if latest and latest.created_by_id == getattr(actor, 'pk', None) and latest.configuration == normalized:
            return latest
        raise OriginationTemplateError('This calibration changed. Reload before saving again.')
    revision = OriginationTemplateConfigurationRevision.objects.create(
        template=template, revision=current_revision + 1,
        configuration=normalized, created_by=actor,
    )
    OriginationDocumentTemplateEvent.objects.create(
        template=template, action='calibration_saved', actor=actor,
        metadata={'configuration_revision': revision.revision},
    )
    return revision


@transaction.atomic
def publish_calibration(*, template: OriginationDocumentTemplate, revision: int, actor) -> OriginationTemplateConfigurationRevision:
    template = OriginationDocumentTemplate.objects.select_for_update().get(pk=template.pk)
    selected = template.configuration_revisions.get(revision=revision)
    validate_template_configuration(selected.configuration, template=template)
    current_published = template.published_configuration_revision
    if current_published and current_published.configuration == selected.configuration:
        return current_published
    # Revisions are append-only: publishing creates a new immutable revision.
    published = OriginationTemplateConfigurationRevision.objects.create(
        template=template,
        revision=(template.configuration_revisions.aggregate(models.Max('revision'))['revision__max'] or 0) + 1,
        configuration=selected.configuration,
        is_published=True,
        created_by=actor,
        published_at=timezone.now(),
    )
    template.placement_config = published.configuration
    template.published_configuration_revision = published
    template.save(update_fields=['placement_config', 'published_configuration_revision', 'updated_at'])
    cache.delete(f'origination-template:{template.pk}:{template.source_sha256}')
    OriginationDocumentTemplateEvent.objects.create(
        template=template, action='calibration_published', actor=actor,
        metadata={'configuration_revision': published.revision, 'source_revision': revision},
    )
    return published


def create_template(
    *, pdf_file, name: str, actor,
    product_definition: OriginationProductDefinition | None = None,
    config_file=None,
) -> OriginationDocumentTemplate:
    """Create an immutable record and archive its PDF in the restricted Drive folder."""
    pdf_data = pdf_file.read()
    if product_definition is not None:
        if product_definition.lifecycle_status != product_definition.STATUS_DRAFT:
            raise OriginationTemplateError('Templates can only be uploaded for a draft product version.')
        digest, page_count = validate_template_pdf(pdf_data)
        document_type = product_definition.document_type
        version = product_definition.version
        config = initial_template_configuration(product_definition)
    else:
        if config_file is None:
            raise OriginationTemplateError('Choose a draft loan product for this template.')
        config_data = config_file.read()
        config, digest, page_count = validate_template_files(pdf_data, config_data)
        document_type = str(config['document_type']).strip()
        version = int(config['version'])
    filename = str(getattr(pdf_file, 'name', '') or f'{document_type}-v{version}.pdf')[:255]
    with transaction.atomic():
        template = OriginationDocumentTemplate.objects.create(
            product_definition=product_definition,
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


@transaction.atomic
def clone_product_version(
    product: OriginationProductDefinition, *, actor,
) -> OriginationProductDefinition:
    """Create an editable successor while leaving the published contract untouched."""
    source = OriginationProductDefinition.objects.select_for_update().get(pk=product.pk)
    existing = OriginationProductDefinition.objects.filter(
        product_key=source.product_key, lifecycle_status=OriginationProductDefinition.STATUS_DRAFT,
    ).order_by('-version').first()
    if existing:
        return existing
    global_version = source.product_version
    next_version = (
        OriginationProductDefinition.objects.filter(product_key=source.product_key)
        .aggregate(models.Max('version'))['version__max'] or 0
    ) + 1
    clone = OriginationProductDefinition.objects.create(
        product_version=global_version,
        product_key=source.product_key,
        name=source.name,
        version=next_version,
        form_schema=json.loads(json.dumps(source.form_schema)),
        signer_rules=json.loads(json.dumps(source.signer_rules)),
        document_type=source.document_type,
        document_template_name='',
        document_template_version=next_version,
        document_template_sha256='',
        lifecycle_status=OriginationProductDefinition.STATUS_DRAFT,
        is_active=False,
        supersedes=source,
        created_by=actor,
    )
    OriginationProductDefinitionEvent.objects.create(
        product_definition=clone, action='version_created', actor=actor,
        metadata={'supersedes_id': str(source.pk), 'version': next_version},
    )
    return clone


def upload_template_record(template: OriginationDocumentTemplate, *, pdf_data: bytes, actor) -> OriginationDocumentTemplate:
    """Upload a validated, already-persisted template record and retain failures for audit."""
    folder_id = str(getattr(settings, 'GOOGLE_DRIVE_MEDIA_FOLDER_ID', '') or '').strip()
    if not folder_id:
        error = 'GOOGLE_DRIVE_MEDIA_FOLDER_ID is not configured.'
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
    OriginationTemplateConfigurationRevision.objects.get_or_create(
        template=template, revision=1,
        defaults={'configuration': template.placement_config, 'created_by': actor},
    )
    return template


@transaction.atomic
def activate_template(template: OriginationDocumentTemplate, *, actor) -> OriginationDocumentTemplate:
    template = OriginationDocumentTemplate.objects.select_for_update().get(pk=template.pk)
    if not template.drive_file_id or template.status == template.STATUS_UPLOAD_FAILED:
        raise OriginationTemplateError('Only a successfully uploaded template can be activated.')
    if not template.published_configuration_revision_id:
        raise OriginationTemplateError('Publish the calibrated field alignment before activating this template.')
    try:
        from core.services.order_approval import GoogleDriveMediaStorage
        folder_id = str(getattr(settings, 'GOOGLE_DRIVE_MEDIA_FOLDER_ID', '') or '').strip()
        if not folder_id:
            raise OriginationTemplateError('GOOGLE_DRIVE_MEDIA_FOLDER_ID is not configured.')
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


@transaction.atomic
def publish_product_template(
    *, template: OriginationDocumentTemplate, revision: int, actor,
) -> tuple[OriginationProductDefinition | None, OriginationDocumentTemplate, OriginationTemplateConfigurationRevision]:
    """Publish calibration, activate its immutable PDF, and expose the product atomically."""
    template = (
        OriginationDocumentTemplate.objects.select_for_update()
        .select_related('product_definition')
        .get(pk=template.pk)
    )
    product = template.product_definition
    if product is None:
        published = publish_calibration(template=template, revision=revision, actor=actor)
        return None, activate_template(template, actor=actor), published
    product = OriginationProductDefinition.objects.select_for_update().get(pk=product.pk)
    if (
        product.lifecycle_status == product.STATUS_PUBLISHED
        and product.is_active
        and template.status == template.STATUS_ACTIVE
        and template.published_configuration_revision_id
    ):
        return product, template, template.published_configuration_revision
    if product.lifecycle_status != product.STATUS_DRAFT:
        raise OriginationTemplateError('Only a draft product version can be published.')

    selected = template.configuration_revisions.get(revision=revision)
    validate_template_configuration(
        selected.configuration, template=template, require_complete=True,
    )
    if product.product_version_id:
        from core.services.product_catalog import ProductCatalogError, publish_product_version
        try:
            publish_product_version(version=product.product_version, actor=actor)
        except ProductCatalogError as exc:
            raise OriginationTemplateError(str(exc)) from exc
    published = publish_calibration(template=template, revision=revision, actor=actor)
    activated = activate_template(template, actor=actor)

    product.document_template_name = template.name
    product.document_template_version = template.version
    product.document_template_sha256 = template.source_sha256
    from core.services.loan_origination import validate_product_definition
    validate_product_definition(product)

    previous_products = list(
        OriginationProductDefinition.objects.select_for_update().filter(
            product_key=product.product_key, is_active=True,
        ).exclude(pk=product.pk)
    )
    for old in previous_products:
        old.is_active = False
        old.lifecycle_status = old.STATUS_RETIRED
        old.save(update_fields=['is_active', 'lifecycle_status', 'updated_at'])
        OriginationProductDefinitionEvent.objects.create(
            product_definition=old, action='retired', actor=actor,
            metadata={'successor_id': str(product.pk), 'successor_version': product.version},
        )

    was_published = product.lifecycle_status == product.STATUS_PUBLISHED and product.is_active
    product.is_active = True
    product.lifecycle_status = product.STATUS_PUBLISHED
    product.published_by = actor
    product.published_at = product.published_at or timezone.now()
    product.save(update_fields=[
        'document_template_name', 'document_template_version', 'document_template_sha256',
        'is_active', 'lifecycle_status', 'published_by', 'published_at', 'updated_at',
    ])
    if not was_published:
        product_event = OriginationProductDefinitionEvent.objects.create(
            product_definition=product, action='published', actor=actor,
            metadata={
                'template_id': str(template.pk),
                'template_sha256': template.source_sha256,
                'configuration_revision': published.revision,
            },
        )
        from core.services.compliance_audit import record_event
        record_event(
            workflow='portal', action='portal.origination.product_published',
            category='configuration', origin='human',
            subject_type='origination_product_definition', subject_id=str(product.pk),
            actor=actor, authority_user=actor,
            source_model='OriginationProductDefinitionEvent', source_event_id=str(product_event.pk),
            deduplication_key=f'portal:OriginationProductDefinitionEvent:{product_event.pk}',
            after_values={'product_key': product.product_key, 'version': product.version},
            metadata={'template_id': str(template.pk), 'template_sha256': template.source_sha256},
        )
    return product, activated, published


def load_active_template(
    document_type: str,
    version: int | None = None,
    expected_sha256: str = '',
) -> tuple[bytes, dict[str, Any]]:
    query = OriginationDocumentTemplate.objects.filter(document_type=document_type)
    # Existing applications remain pinned to an immutable version/hash after a
    # successor activates. Retired templates were previously active and remain
    # valid for those captured contracts; unpinned callers still require active.
    if version is not None and expected_sha256:
        query = query.filter(status__in=[
            OriginationDocumentTemplate.STATUS_ACTIVE,
            OriginationDocumentTemplate.STATUS_RETIRED,
        ])
    else:
        query = query.filter(status=OriginationDocumentTemplate.STATUS_ACTIVE)
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
            folder_id = str(getattr(settings, 'GOOGLE_DRIVE_MEDIA_FOLDER_ID', '') or '').strip()
            if not folder_id:
                raise OriginationTemplateError('GOOGLE_DRIVE_MEDIA_FOLDER_ID is not configured.')
            source = GoogleDriveMediaStorage(parent_folder_id=folder_id).download(template.drive_file_id)
        except Exception as exc:
            raise OriginationTemplateError('The active document template could not be retrieved from Drive.') from exc
        if hashlib.sha256(source).hexdigest() != template.source_sha256:
            raise OriginationTemplateError('The active document template failed integrity verification.')
        cache.set(cache_key, source, timeout=600)
    return source, template.placement_config


def load_template_source(template: OriginationDocumentTemplate) -> bytes:
    cache_key = f'origination-template:{template.pk}:{template.source_sha256}'
    source = cache.get(cache_key)
    if source is None:
        folder_id = str(getattr(settings, 'GOOGLE_DRIVE_MEDIA_FOLDER_ID', '') or '').strip()
        if not folder_id:
            raise OriginationTemplateError('GOOGLE_DRIVE_MEDIA_FOLDER_ID is not configured.')
        try:
            from core.services.order_approval import GoogleDriveMediaStorage
            source = GoogleDriveMediaStorage(parent_folder_id=folder_id).download(template.drive_file_id)
        except Exception as exc:
            raise OriginationTemplateError('The document template could not be retrieved from Drive.') from exc
        if hashlib.sha256(source).hexdigest() != template.source_sha256:
            raise OriginationTemplateError('The document template failed integrity verification.')
        cache.set(cache_key, source, timeout=600)
    return source
