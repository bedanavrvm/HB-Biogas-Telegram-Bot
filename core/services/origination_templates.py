"""Validation, Drive persistence, activation, and retrieval of legal templates."""

from __future__ import annotations

import hashlib
import json
import math
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
    OriginationProductDocumentAssignment,
    OriginationTemplateConfigurationRevision,
)


class OriginationTemplateError(ValueError):
    """Stable, staff-safe template management error."""


def _calibration_request_id(value: Any) -> str:
    request_id = str(value or '').strip()
    if len(request_id) > 120:
        raise OriginationTemplateError('The calibration request ID is invalid.')
    return request_id


def _calibration_payload_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _calibration_request_replay(*, template, action: str, request_id: str, payload_hash: str):
    if not request_id:
        return None
    event = template.events.filter(
        action=action, metadata__request_id=request_id,
    ).order_by('-occurred_at').first()
    if not event:
        return None
    if event.metadata.get('payload_hash') != payload_hash:
        raise OriginationTemplateError('This calibration request ID was already used for different content.')
    revision = event.metadata.get('configuration_revision')
    return template.configuration_revisions.filter(revision=revision).first()


SYSTEM_CONTEXT_KEYS = (
    ('reference_number', 'Reference Number'),
    ('branch_code', 'Branch Code'),
    ('loan_officer_name', 'Loan Officer Name'),
    ('application_date', 'Application Date'),
    ('secured_assets_total', 'Secured Assets Total'),
    ('home_visit_completed_date', 'Home Visit Completed Date'),
    ('product_code', 'Product Code'),
    ('product_name', 'Product Name'),
    ('borrower_full_name', 'Borrower Full Name'),
    ('deponent_full_name', 'Deponent Full Name'),
    ('acknowledgement_recipient_name', 'Acknowledgement Recipient Name'),
    ('repayment_frequency', 'Repayment Frequency'),
    ('interest_rate', 'Interest Rate'),
    ('loan_product', 'Loan Product'),
    ('loan_product_other', 'Other Loan Product'),
    ('approval_amount', 'Approved Amount'),
    ('amount_advanced', 'Amount Advanced'),
    ('acknowledgement_amount', 'Acknowledgement Amount'),
    ('installment_amount', 'Installment Amount'),
    ('penalty_rate', 'Penalty Rate'),
    ('bro_1_name', 'Business Relationship Officer 1 Name'),
    ('bro_2_name', 'Business Relationship Officer 2 Name'),
    ('branch_manager_name', 'Branch Manager Name'),
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


def _sample_value_for_field(field: dict[str, Any]) -> tuple[Any, Any | None]:
    """Return a display sample and, for governed choices, its canonical value."""
    key = str(field.get('key') or '').strip()
    field_type = str(field.get('type') or 'text')
    if field_type == 'boolean':
        return 'Yes', True
    if field_type in {'money', 'number'}:
        return '12,500', None
    if field_type == 'date':
        return '2026-08-13', None
    if field_type == 'choice':
        options = [item for item in (field.get('options') or []) if isinstance(item, dict) and item.get('code') and item.get('active', True)]
        if options:
            option = options[0]
            code = str(option['code'])
            return str(option.get('label') or code), code
    if field_type == 'repeating_group':
        return [{
            str(column.get('key') or ''): (
                '12,500' if str(column.get('type') or '') == 'money'
                else '2026-08-13' if str(column.get('type') or '') == 'date'
                else str(column.get('label') or column.get('key') or 'Sample')
            )
            for column in ((field.get('structure') or {}).get('columns') or [])
            if isinstance(column, dict) and column.get('key')
        }], None
    return field.get('label') or key.replace('_', ' ').title(), None


def sample_context_for_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    """Build display samples while retaining canonical values for checkbox tests."""
    sample_context: dict[str, Any] = {}
    canonical_values: dict[str, Any] = {}
    for field in (schema or {}).get('fields', []) or []:
        if not isinstance(field, dict):
            continue
        key = str(field.get('key') or '').strip()
        if not key:
            continue
        display_value, canonical_value = _sample_value_for_field(field)
        sample_context[key] = display_value
        if canonical_value is not None:
            canonical_values[key] = canonical_value
    if canonical_values:
        sample_context['_canonical_values'] = canonical_values
    sample_context['_date_fields'] = [
        str(field.get('key') or '') for field in (schema or {}).get('fields', []) or []
        if isinstance(field, dict) and str(field.get('type') or '') == 'date'
    ]
    return sample_context


def initial_template_configuration(
    product: OriginationProductDefinition | None,
    *, form_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    schema = form_schema if form_schema is not None else (product.form_schema if product else {})
    sample_context = sample_context_for_schema(schema)
    sample_context.update({
        'reference_number': 'ORG-2026-SAMPLE',
        'branch_code': 'Sample Branch',
        'loan_officer_name': 'Sample Loan Officer',
        'application_date': '2026-08-13',
        'product_code': 'sample_product',
        'product_name': 'Sample Loan Product',
        'borrower_full_name': 'Sample Applicant',
        'deponent_full_name': 'Sample Applicant',
        'acknowledgement_recipient_name': 'Sample Applicant',
        'repayment_frequency': 'Weekly',
        'interest_rate': '10',
    })
    sample_context['_date_fields'] = sorted(set(sample_context.get('_date_fields') or []) | {'application_date'})
    return {
        'document_type': product.document_type if product else '',
        'version': product.version if product else 1,
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


def _expected_signature_slots(
    product: OriginationProductDefinition | None,
    template: OriginationDocumentTemplate | None = None,
) -> dict[str, dict[str, Any]]:
    expected = {}
    rules = (
        template.signer_rules
        if template and template.signer_rules
        else product.signer_rules if product else []
    )
    for rule in rules or []:
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
    schema = (
        template.form_schema
        if template.form_schema and (
            template.document_role == template.ROLE_SUPPORTING
            or template.product_definition_id is None
        )
        else product.form_schema if product else {}
    )
    schema_fields = (schema or {}).get('fields', [])
    known_context_keys = {str(item.get('key') or '') for item in schema_fields if item.get('key')}
    if product and template.document_role == template.ROLE_SUPPORTING:
        known_context_keys.update(
            str(item.get('key') or '')
            for item in (product.form_schema or {}).get('fields', [])
            if item.get('key')
        )
    known_context_keys.update(key for key, _label in SYSTEM_CONTEXT_KEYS)
    configured_context_keys = {
        str(spec.get('context_key') or '').strip() for spec in fields.values() if isinstance(spec, dict)
    }
    unknown = sorted(configured_context_keys - known_context_keys) if known_context_keys else []
    if unknown:
        raise OriginationTemplateError(f'Unknown application fields: {", ".join(unknown)}.')
    if require_complete and (
        template.product_definition_id
        or bool(schema_fields)
    ):
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
        if not all(math.isfinite(value) for value in (x, y, width, height)):
            raise OriginationTemplateError(f'{item_label} {key} has invalid placement dimensions.')
        if min(x, y) < 0 or width <= 0 or height <= 0:
            raise OriginationTemplateError(f'{item_label} {key} has invalid placement dimensions.')
        page_width, page_height = page_sizes[page_number]
        if x + width > page_width or y + height > page_height:
            raise OriginationTemplateError(f'{item_label} {key} extends outside page {page_number}.')

    for key, spec in fields.items():
        if not isinstance(spec, dict) or not str(spec.get('context_key') or '').strip():
            raise OriginationTemplateError(f'Field {key} requires a context key.')
        render_as = str(spec.get('render_as') or 'text')
        if render_as not in {'text', 'checkbox', 'repeating_table'}:
            raise OriginationTemplateError(f'Field {key} has an unsupported rendering mode.')
        if render_as == 'repeating_table':
            schema_field = next((item for item in schema_fields if str(item.get('key') or '') == str(spec.get('context_key') or '')), None)
            if not schema_field or str(schema_field.get('type') or '') != 'repeating_group':
                raise OriginationTemplateError(f'Field {key} must reference a repeatable-group field.')
            columns = spec.get('columns')
            expected_columns = {
                str(item.get('key') or '') for item in ((schema_field.get('structure') or {}).get('columns') or [])
                if isinstance(item, dict)
            }
            configured_columns = {
                str(item.get('key') or '') for item in (columns or []) if isinstance(item, dict)
            }
            rows = int(spec.get('rows') or 0)
            maximum = int((schema_field.get('structure') or {}).get('max_items') or 0)
            if not isinstance(columns, list) or configured_columns != expected_columns or rows < 1 or (maximum and rows > maximum):
                raise OriginationTemplateError(f'Field {key} has an invalid repeatable-table layout.')
            try:
                widths = [float(item.get('width_ratio')) for item in columns]
                offsets = []
                cursor = 0.0
                for item, width in zip(columns, widths):
                    offsets.append(float(item.get('x_ratio')) if item.get('x_ratio') is not None else cursor)
                    cursor = offsets[-1] + width
            except (TypeError, ValueError, AttributeError) as exc:
                raise OriginationTemplateError(f'Field {key} has invalid repeatable-table column widths.') from exc
            if (
                any(not math.isfinite(value) or value <= 0 for value in widths)
                or any(not math.isfinite(value) or value < 0 for value in offsets)
                or abs(sum(widths) - 1) > .001
                or any(abs(offsets[index] - sum(widths[:index])) > .001 for index in range(len(widths)))
            ):
                raise OriginationTemplateError(f'Field {key} repeatable-table column widths must total 100% without gaps or overlaps.')
        validate_box(key, spec, item_label='Field')

    signature_slots = (normalized.get('signature_overlay_manifest') or {}).get('slots', {})
    if not isinstance(signature_slots, dict):
        raise OriginationTemplateError('The signature slot collection must be an object.')
    expected_slots = _expected_signature_slots(product, template)
    unknown_slots = sorted(set(signature_slots) - set(expected_slots)) if expected_slots else []
    if unknown_slots:
        raise OriginationTemplateError(f'Unknown signature slots: {", ".join(unknown_slots)}.')
    if require_complete and (
        template.product_definition_id
        or (template.document_role == template.ROLE_SUPPORTING and bool(template.signer_rules))
    ):
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
        if slot_type not in {'signature', 'stamp', 'date_signed'}:
            raise OriginationTemplateError(f'Signature slot {key} has an unsupported type.')
        expected_type = str(expected_slots.get(key, {}).get('slot_type') or '')
        if expected_type and slot_type != expected_type:
            raise OriginationTemplateError(
                f'Signature slot {key} must remain a {expected_type.replace("_", " ")} slot.'
            )
        label = str(spec.get('label') or expected_slots.get(key, {}).get('label') or '').strip()
        if not label or len(label) > 120:
            raise OriginationTemplateError(f'Signature slot {key} requires a label of at most 120 characters.')
        if str(spec.get('align') or 'center') not in {'left', 'center', 'right'}:
            raise OriginationTemplateError(f'Signature slot {key} has an invalid horizontal alignment.')
        if str(spec.get('vertical_align') or 'center') not in {'bottom', 'center', 'top'}:
            raise OriginationTemplateError(f'Signature slot {key} has an invalid vertical alignment.')
        padding = spec.get('padding') or {'x': 0, 'y': 0}
        if not isinstance(padding, dict):
            raise OriginationTemplateError(f'Signature slot {key} has invalid padding.')
        try:
            padding_x = float(padding.get('x', 0))
            padding_y = float(padding.get('y', 0))
            rotation = float(spec.get('rotation', 0))
        except (TypeError, ValueError) as exc:
            raise OriginationTemplateError(f'Signature slot {key} has invalid appearance values.') from exc
        if not all(math.isfinite(value) for value in (padding_x, padding_y, rotation)):
            raise OriginationTemplateError(f'Signature slot {key} has invalid appearance values.')
        if padding_x < 0 or padding_y < 0:
            raise OriginationTemplateError(f'Signature slot {key} padding cannot be negative.')
        if rotation < -180 or rotation > 180:
            raise OriginationTemplateError(f'Signature slot {key} rotation must be between -180 and 180 degrees.')
        box = spec.get('allowed_area') or spec.get('box') or {}
        try:
            box_width = float(box.get('width'))
            box_height = float(box.get('height'))
        except (TypeError, ValueError) as exc:
            raise OriginationTemplateError(f'Signature slot {key} has invalid placement dimensions.') from exc
        if padding_x * 2 >= box_width or padding_y * 2 >= box_height:
            raise OriginationTemplateError(f'Signature slot {key} padding leaves no usable signing area.')
        if slot_type == 'signature':
            if str(spec.get('ink_color') or 'black') not in {'black', 'blue', 'purple'}:
                raise OriginationTemplateError(f'Signature slot {key} has an unsupported ink colour.')
            if str(spec.get('typed_font') or 'Helvetica-BoldOblique') not in {
                'Helvetica-BoldOblique', 'Times-Italic', 'Courier-Oblique',
            }:
                raise OriginationTemplateError(f'Signature slot {key} has an unsupported typed-signature font.')
            try:
                font_size = float(spec.get('font_size', 15))
                stroke_width = float(spec.get('stroke_width', 2))
            except (TypeError, ValueError) as exc:
                raise OriginationTemplateError(f'Signature slot {key} has invalid signature sizing.') from exc
            if not math.isfinite(font_size) or font_size < 6 or font_size > 30:
                raise OriginationTemplateError(f'Signature slot {key} font size must be between 6 and 30.')
            if not math.isfinite(stroke_width) or stroke_width < .5 or stroke_width > 8:
                raise OriginationTemplateError(f'Signature slot {key} stroke width must be between 0.5 and 8.')
        if slot_type == 'stamp' and str(spec.get('stamp_fit') or 'contain') not in {'contain', 'stretch'}:
            raise OriginationTemplateError(f'Signature slot {key} has an unsupported stamp fit.')
        validate_box(key, spec, item_label='Signature slot')
    return normalized


@transaction.atomic
def save_calibration_draft(
    *, template: OriginationDocumentTemplate, configuration: Any, actor,
    expected_revision: int, client_request_id: str = '',
) -> OriginationTemplateConfigurationRevision:
    template = OriginationDocumentTemplate.objects.select_for_update().get(pk=template.pk)
    if template.status in {template.STATUS_ACTIVE, template.STATUS_RETIRED}:
        raise OriginationTemplateError('Published template revisions are immutable. Upload a new shared-template version.')
    if template.product_definition_id and template.product_definition.lifecycle_status != OriginationProductDefinition.STATUS_DRAFT:
        raise OriginationTemplateError('Published product versions are immutable. Create a new product version to change its template.')
    latest = template.configuration_revisions.order_by('-revision').first()
    current_revision = latest.revision if latest else 0
    normalized = validate_template_configuration(
        configuration, template=template, require_complete=False,
    )
    request_id = _calibration_request_id(client_request_id)
    payload_hash = _calibration_payload_hash(normalized)
    replay = _calibration_request_replay(
        template=template, action='calibration_saved', request_id=request_id,
        payload_hash=payload_hash,
    )
    if replay:
        return replay
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
        metadata={
            'configuration_revision': revision.revision,
            **({'request_id': request_id, 'payload_hash': payload_hash} if request_id else {}),
        },
    )
    return revision


@transaction.atomic
def publish_calibration(
    *, template: OriginationDocumentTemplate, revision: int, actor,
    client_request_id: str = '',
) -> OriginationTemplateConfigurationRevision:
    template = OriginationDocumentTemplate.objects.select_for_update().get(pk=template.pk)
    selected = template.configuration_revisions.get(revision=revision)
    validate_template_configuration(selected.configuration, template=template)
    request_id = _calibration_request_id(client_request_id)
    payload_hash = _calibration_payload_hash({'source_revision': int(revision)})
    replay = _calibration_request_replay(
        template=template, action='calibration_published', request_id=request_id,
        payload_hash=payload_hash,
    )
    if replay:
        return replay
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
        metadata={
            'configuration_revision': published.revision, 'source_revision': revision,
            **({'request_id': request_id, 'payload_hash': payload_hash} if request_id else {}),
        },
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


def create_shared_document_template(
    *, pdf_file, name: str, document_key: str, form_schema: dict[str, Any],
    signer_rules: list[dict[str, Any]], actor, document_role: str = OriginationDocumentTemplate.ROLE_SUPPORTING,
) -> OriginationDocumentTemplate:
    """Create an unassigned reusable primary or supporting PDF.

    The document is deliberately global: attaching it to a draft product is a
    separate, auditable action and uses ``latest_compatible`` by default.
    """
    if document_role not in {
        OriginationDocumentTemplate.ROLE_PRIMARY,
        OriginationDocumentTemplate.ROLE_SUPPORTING,
    }:
        raise OriginationTemplateError('Choose primary LAF or supporting document.')
    document_key = str(document_key or '').strip().lower()
    try:
        validate_slug(document_key)
    except ValidationError as exc:
        raise OriginationTemplateError('Document key must be a lowercase slug.') from exc
    if document_role == OriginationDocumentTemplate.ROLE_PRIMARY:
        document_key = 'primary'
    elif document_key == 'primary':
        raise OriginationTemplateError('Supporting documents need their own document key.')
    from core.services.loan_origination import OriginationError, validate_product_form_contract
    try:
        validate_product_form_contract(form_schema or {}, signer_rules or [], require_signers=False)
    except OriginationError as exc:
        raise OriginationTemplateError(str(exc)) from exc
    pdf_data = pdf_file.read()
    digest, page_count = validate_template_pdf(pdf_data)
    filename = str(getattr(pdf_file, 'name', '') or f'{document_key}.pdf')[:255]
    with transaction.atomic():
        version = (
            OriginationDocumentTemplate.objects.filter(document_type=document_key)
            .aggregate(models.Max('version'))['version__max'] or 0
        ) + 1
        template = OriginationDocumentTemplate(
            product_definition=None,
            document_key=document_key,
            document_role=document_role,
            inclusion_mode=OriginationDocumentTemplate.INCLUDE_REQUIRED,
            display_order=0 if document_role == OriginationDocumentTemplate.ROLE_PRIMARY else 10,
            officer_selectable=False,
            default_selected=False,
            applicability_rule={},
            form_schema=form_schema or {},
            signer_rules=signer_rules or [],
            document_type=document_key,
            name=str(name or filename).strip()[:180],
            version=version,
            status=OriginationDocumentTemplate.STATUS_READY,
            source_filename=filename,
            source_sha256=digest,
            source_byte_size=len(pdf_data),
            page_count=page_count,
            placement_config=initial_template_configuration(None, form_schema=form_schema or {}),
            created_by=actor,
        )
        template.placement_config['document_type'] = document_key
        template.placement_config['version'] = version
        template.full_clean()
        template.save()
        OriginationDocumentTemplateEvent.objects.create(
            template=template, action='created', actor=actor,
            metadata={
                'sha256': digest, 'byte_size': len(pdf_data), 'page_count': page_count,
                'origin': 'product_document_packet_wizard',
            },
        )
    return upload_template_record(template, pdf_data=pdf_data, actor=actor)


def create_shared_supporting_template(**kwargs) -> OriginationDocumentTemplate:
    """Compatibility wrapper for existing supporting-document callers."""
    return create_shared_document_template(
        **kwargs, document_role=OriginationDocumentTemplate.ROLE_SUPPORTING,
    )


def _merge_shared_primary_contract(
    *, product: OriginationProductDefinition, template: OriginationDocumentTemplate,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Merge the reusable primary's minimum contract into an editable product."""
    product_schema = json.loads(json.dumps(product.form_schema or {}))
    template_schema = template.form_schema or {}
    sections = [item for item in product_schema.get('sections', []) if isinstance(item, dict)]
    product_fields = [item for item in product_schema.get('fields', []) if isinstance(item, dict)]
    if product_fields and any(not str(item.get('section_key') or '').strip() for item in product_fields):
        fallback_section = next((str(item.get('key') or '') for item in sections if item.get('key')), '')
        if not fallback_section:
            fallback_section = 'product_specific'
            sections.append({
                'key': fallback_section,
                'label': 'Product Specific',
                'help_text': 'Additional fields configured for this loan product.',
            })
        for item in product_fields:
            if not str(item.get('section_key') or '').strip():
                item['section_key'] = fallback_section
    section_keys = {str(item.get('key') or '') for item in sections}
    for section in template_schema.get('sections', []) or []:
        if isinstance(section, dict) and str(section.get('key') or '') not in section_keys:
            sections.append(json.loads(json.dumps(section)))
            section_keys.add(str(section.get('key') or ''))
    fields = product_fields
    fields_by_key = {str(item.get('key') or ''): item for item in fields}
    for field in template_schema.get('fields', []) or []:
        if not isinstance(field, dict) or not field.get('key'):
            continue
        key = str(field['key'])
        current = fields_by_key.get(key)
        if current:
            if str(current.get('type') or 'text') != str(field.get('type') or 'text'):
                raise OriginationTemplateError(
                    f'Canonical field {key} has a different type in this product.',
                )
            if field.get('required') and not current.get('required'):
                current['required'] = True
            continue
        copied = json.loads(json.dumps(field))
        fields.append(copied)
        fields_by_key[key] = copied
    product_schema.update({
        'sections': sections,
        'fields': fields,
        'identity_contract': template_schema.get('identity_contract') or product_schema.get('identity_contract'),
    })

    product_rules = [
        json.loads(json.dumps(item)) for item in (product.signer_rules or [])
        if isinstance(item, dict)
    ]
    product_by_role = {str(item.get('role') or ''): item for item in product_rules}
    for rule in template.signer_rules or []:
        if not isinstance(rule, dict) or not rule.get('role'):
            continue
        role = str(rule['role'])
        current = product_by_role.get(role)
        if not current:
            copied = json.loads(json.dumps(rule))
            product_rules.append(copied)
            product_by_role[role] = copied
            continue
        if rule.get('required'):
            current['required'] = True
        current['identity_fields'] = {
            **(rule.get('identity_fields') if isinstance(rule.get('identity_fields'), dict) else {}),
            **(current.get('identity_fields') if isinstance(current.get('identity_fields'), dict) else {}),
        }
        slots = [item for item in current.get('slots', [])]
        slot_keys = {
            str(item.get('key') if isinstance(item, dict) else item) for item in slots
        }
        for slot in rule.get('slots', []) or []:
            slot_key = str(slot.get('key') if isinstance(slot, dict) else slot)
            if slot_key not in slot_keys:
                slots.append(json.loads(json.dumps(slot)))
                slot_keys.add(slot_key)
        current['slots'] = slots
    return product_schema, product_rules


def attach_shared_document_template(
    *, product_definition: OriginationProductDefinition,
    template: OriginationDocumentTemplate, inclusion_mode: str, display_order: int,
    officer_selectable: bool, default_selected: bool, applicability_rule: dict[str, Any], actor,
    version_policy: str | None = None,
) -> OriginationProductDocumentAssignment:
    """Attach a published global document family to one draft product."""
    with transaction.atomic():
        product = OriginationProductDefinition.objects.select_for_update().get(pk=product_definition.pk)
        template = OriginationDocumentTemplate.objects.select_for_update().get(pk=template.pk)
        if product.lifecycle_status != product.STATUS_DRAFT:
            raise OriginationTemplateError('Create an editable product version before changing its document packet.')
        if (
            template.product_definition_id is not None
            or template.status != template.STATUS_ACTIVE
            or not template.published_configuration_revision_id
        ):
            raise OriginationTemplateError('Choose a published reusable document.')
        existing = product.document_assignments.select_for_update().filter(
            template=template,
        ).first()
        if existing:
            # Admin/browser retries are common on slow connections. The
            # assignment is already the durable result of this exact family
            # attachment, so make the retry harmless rather than creating a
            # second route-specific failure.
            return existing
        if template.document_role == template.ROLE_PRIMARY:
            owned_primary = product.document_templates.filter(
                document_role=template.ROLE_PRIMARY,
                status__in=[template.STATUS_READY, template.STATUS_ACTIVE],
            ).exists()
            assigned_primary = product.document_assignments.select_for_update().filter(
                template__document_role=template.ROLE_PRIMARY,
            ).first()
            if owned_primary:
                raise OriginationTemplateError(
                    'This draft already has a product-owned primary LAF. Remove or retire it '
                    'from the Document packet before assigning a reusable Main LAF.',
                )
            if assigned_primary:
                baseline = OriginationDocumentTemplate.objects.get(
                    pk=assigned_primary.template_id,
                )
                if baseline.document_type != template.document_type:
                    raise OriginationTemplateError(
                        f'This draft already uses {baseline.name} as its Main LAF. '
                        'Remove it from the Document packet before choosing a different LAF family.',
                    )
                compatibility_errors = assignment_template_compatibility_errors(
                    baseline, template,
                )
                if compatibility_errors:
                    raise OriginationTemplateError(
                        'This published version cannot replace the current Main LAF because '
                        + '; '.join(compatibility_errors)
                        + '. Remove the current Main LAF first only if this contract change is intentional.',
                    )

                previous = baseline
                assigned_primary.template = template
                assigned_primary.name = template.name
                assigned_primary.version_policy = (
                    OriginationProductDocumentAssignment.VERSION_PINNED
                )
                assigned_primary.full_clean()
                assigned_primary.save(update_fields=['template', 'name', 'version_policy'])
                merged_schema, merged_signers = _merge_shared_primary_contract(
                    product=product, template=template,
                )
                product.form_schema = merged_schema
                product.signer_rules = merged_signers
                product.document_type = template.document_type
                product.document_template_name = template.name
                product.document_template_version = template.version
                product.document_template_sha256 = template.source_sha256
                product.save(update_fields=[
                    'form_schema', 'signer_rules', 'document_type', 'document_template_name',
                    'document_template_version', 'document_template_sha256', 'updated_at',
                ])
                OriginationProductDefinitionEvent.objects.create(
                    product_definition=product, action='shared_primary_upgraded', actor=actor,
                    metadata={
                        'assignment_id': str(assigned_primary.pk),
                        'previous_template_id': str(previous.pk),
                        'previous_version': previous.version,
                        'template_id': str(template.pk),
                        'version': template.version,
                        'version_policy': assigned_primary.version_policy,
                        'origin': 'shared_document_assignment_admin',
                    },
                )
                return assigned_primary
            inclusion_mode = template.INCLUDE_REQUIRED
            display_order = 0
            officer_selectable = False
            default_selected = False
            applicability_rule = {}
            version_policy = OriginationProductDocumentAssignment.VERSION_PINNED
        elif version_policy is None:
            version_policy = OriginationProductDocumentAssignment.VERSION_LATEST_COMPATIBLE
        if version_policy not in {
            OriginationProductDocumentAssignment.VERSION_PINNED,
            OriginationProductDocumentAssignment.VERSION_LATEST_COMPATIBLE,
        }:
            raise OriginationTemplateError('Choose a supported reusable-document version policy.')
        from core.services.origination_documents import validate_applicability_rule
        product_keys = {
            str(item.get('key')) for item in (product.form_schema or {}).get('fields', [])
            if isinstance(item, dict) and item.get('key')
        }
        document_keys = {
            str(item.get('key')) for item in (template.form_schema or {}).get('fields', [])
            if isinstance(item, dict) and item.get('key')
        }
        try:
            validate_applicability_rule(applicability_rule or {}, allowed_fields=product_keys | document_keys)
        except ValueError as exc:
            raise OriginationTemplateError(str(exc)) from exc
        if product.document_assignments.filter(document_key=template.document_key).exists():
            raise OriginationTemplateError('This product already has a document with that key.')
        assignment = OriginationProductDocumentAssignment(
            product_definition=product,
            template=template,
            version_policy=version_policy,
            document_key=template.document_key,
            name=template.name,
            inclusion_mode=inclusion_mode,
            display_order=max(0, int(display_order or 0)),
            officer_selectable=bool(officer_selectable),
            default_selected=bool(default_selected),
            applicability_rule=applicability_rule or {},
            created_by=actor,
        )
        assignment.full_clean()
        assignment.save()
        if template.document_role == template.ROLE_PRIMARY:
            merged_schema, merged_signers = _merge_shared_primary_contract(
                product=product, template=template,
            )
            product.form_schema = merged_schema
            product.signer_rules = merged_signers
            product.document_type = template.document_type
            product.document_template_name = template.name
            product.document_template_version = template.version
            product.document_template_sha256 = template.source_sha256
            product.save(update_fields=[
                'form_schema', 'signer_rules', 'document_type', 'document_template_name',
                'document_template_version', 'document_template_sha256', 'updated_at',
            ])
        OriginationProductDefinitionEvent.objects.create(
            product_definition=product, action='shared_document_assigned', actor=actor,
            metadata={
                'assignment_id': str(assignment.pk), 'template_id': str(template.pk),
                'document_key': assignment.document_key,
                'version_policy': assignment.version_policy,
                'document_role': template.document_role,
                'origin': 'product_document_packet_wizard',
            },
        )
        return assignment


def attach_shared_supporting_template(**kwargs) -> OriginationProductDocumentAssignment:
    """Compatibility wrapper that continues to reject primary templates."""
    template = kwargs.get('template')
    if template and template.document_role != OriginationDocumentTemplate.ROLE_SUPPORTING:
        raise OriginationTemplateError('Choose a published reusable supporting document.')
    return attach_shared_document_template(**kwargs)


def remove_shared_document_template(
    *, product_definition: OriginationProductDefinition,
    assignment_id, actor,
) -> bool:
    """Detach one shared document from a draft packet without deleting its family."""
    with transaction.atomic():
        product = OriginationProductDefinition.objects.select_for_update().get(pk=product_definition.pk)
        if product.lifecycle_status != product.STATUS_DRAFT:
            raise OriginationTemplateError('Create an editable product version before changing its document packet.')
        assignment = product.document_assignments.select_for_update().filter(pk=assignment_id).select_related('template').first()
        if not assignment:
            # A repeated browser request after a successful removal is safe.
            return False
        metadata = {
            'assignment_id': str(assignment.pk), 'template_id': str(assignment.template_id),
            'document_key': assignment.document_key,
            'origin': 'product_document_packet',
        }
        removed_primary = assignment.template.document_role == assignment.template.ROLE_PRIMARY
        assignment.delete()
        if removed_primary:
            product.document_template_name = ''
            product.document_template_sha256 = ''
            product.document_template_version = product.version
            product.save(update_fields=[
                'document_template_name', 'document_template_sha256',
                'document_template_version', 'updated_at',
            ])
        OriginationProductDefinitionEvent.objects.create(
            product_definition=product, action='shared_document_assignment_removed',
            actor=actor, metadata=metadata,
        )
        return True


def remove_shared_supporting_template(**kwargs) -> bool:
    """Compatibility wrapper for existing callers."""
    return remove_shared_document_template(**kwargs)


@transaction.atomic
def clone_reusable_template_version(
    template: OriginationDocumentTemplate, *, actor,
) -> tuple[OriginationDocumentTemplate, bool]:
    """Create or reuse an editable successor without duplicating Drive bytes.

    The immutable source PDF, governed form/signers, and published placement
    configuration are copied into a new database version. A later activation
    retires the old family version; existing applications and pinned product
    assignments remain unchanged.
    """
    if not getattr(actor, 'is_superuser', False):
        raise OriginationTemplateError('Only a Django Superuser may version legal templates.')
    # Lock only the concrete template row. ``published_configuration_revision``
    # is nullable, and PostgreSQL rejects FOR UPDATE when a select_related()
    # LEFT OUTER JOIN tries to lock the nullable side as well.
    source = OriginationDocumentTemplate.objects.select_for_update().get(pk=template.pk)
    if source.product_definition_id:
        raise OriginationTemplateError(
            'Create an editable product version to change a product-owned document.',
        )
    if source.status != source.STATUS_ACTIVE or not source.published_configuration_revision_id:
        raise OriginationTemplateError(
            'Create an editable version from the current published family version.',
        )
    existing = OriginationDocumentTemplate.objects.select_for_update().filter(
        product_definition__isnull=True,
        document_type=source.document_type,
        status=OriginationDocumentTemplate.STATUS_READY,
        version__gt=source.version,
    ).order_by('-version').first()
    if existing:
        return existing, True
    next_version = (
        OriginationDocumentTemplate.objects.filter(
            document_type=source.document_type,
        ).aggregate(models.Max('version'))['version__max'] or 0
    ) + 1
    published_revision = OriginationTemplateConfigurationRevision.objects.get(
        pk=source.published_configuration_revision_id,
    )
    configuration = json.loads(json.dumps(published_revision.configuration))
    configuration['document_type'] = source.document_type
    configuration['version'] = next_version
    successor = OriginationDocumentTemplate.objects.create(
        product_definition=None,
        document_key=source.document_key,
        document_role=source.document_role,
        inclusion_mode=source.inclusion_mode,
        display_order=source.display_order,
        officer_selectable=source.officer_selectable,
        default_selected=source.default_selected,
        applicability_rule=json.loads(json.dumps(source.applicability_rule or {})),
        form_schema=json.loads(json.dumps(source.form_schema or {})),
        signer_rules=json.loads(json.dumps(source.signer_rules or [])),
        document_type=source.document_type,
        name=source.name,
        version=next_version,
        status=OriginationDocumentTemplate.STATUS_READY,
        source_filename=source.source_filename,
        source_sha256=source.source_sha256,
        source_byte_size=source.source_byte_size,
        page_count=source.page_count,
        native_consent_policy=source.native_consent_policy,
        native_consent_attestation_reference=source.native_consent_attestation_reference,
        native_consent_attested_by=source.native_consent_attested_by,
        native_consent_attested_at=source.native_consent_attested_at,
        placement_config=configuration,
        drive_file_id=source.drive_file_id,
        drive_url=source.drive_url,
        created_by=actor,
    )
    OriginationTemplateConfigurationRevision.objects.create(
        template=successor,
        revision=1,
        configuration=configuration,
        created_by=actor,
    )
    OriginationDocumentTemplateEvent.objects.create(
        template=successor,
        action='editable_version_created',
        actor=actor,
        metadata={
            'source_template_id': str(source.pk),
            'source_version': source.version,
            'source_sha256': source.source_sha256,
            'reused_drive_file': True,
        },
    )
    return successor, False


def publish_and_attach_shared_supporting_template(
    *, product_definition: OriginationProductDefinition,
    template: OriginationDocumentTemplate, revision: int, actor,
    client_request_id: str = '', assignment_options: dict[str, Any] | None = None,
) -> tuple[OriginationDocumentTemplate, OriginationTemplateConfigurationRevision, OriginationProductDocumentAssignment]:
    """Publish a new shared PDF and attach its latest-compatible family atomically."""
    options = assignment_options or {}
    with transaction.atomic():
        product = OriginationProductDefinition.objects.select_for_update().get(pk=product_definition.pk)
        if product.lifecycle_status != product.STATUS_DRAFT:
            raise OriginationTemplateError('Create an editable product version before changing its document packet.')
        _unused_product, activated, published = publish_product_template(
            template=template, revision=revision, actor=actor,
            client_request_id=client_request_id,
        )
        assignment = attach_shared_supporting_template(
            product_definition=product, template=activated, actor=actor,
            inclusion_mode=options.get('inclusion_mode', OriginationDocumentTemplate.INCLUDE_REQUIRED),
            display_order=options.get('display_order', 10),
            officer_selectable=bool(options.get('officer_selectable')),
            default_selected=bool(options.get('default_selected')),
            applicability_rule=options.get('applicability_rule') or {},
        )
        return activated, published, assignment


def _source_template_for_product(
    product: OriginationProductDefinition,
) -> OriginationDocumentTemplate | None:
    template = (
        product.document_templates.filter(
            status__in=[
                OriginationDocumentTemplate.STATUS_ACTIVE,
                OriginationDocumentTemplate.STATUS_READY,
            ],
        )
        .select_related('published_configuration_revision')
        .order_by('-created_at')
        .first()
    )
    if template:
        return template
    if not product.document_template_sha256:
        return None
    return (
        OriginationDocumentTemplate.objects.filter(
            document_type=product.document_type,
            version=product.document_template_version,
            source_sha256=product.document_template_sha256,
        )
        .exclude(status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED)
        .select_related('published_configuration_revision')
        .order_by('-created_at')
        .first()
    )


def _inherit_template_for_product_version(
    *, source: OriginationProductDefinition,
    successor: OriginationProductDefinition,
    actor,
) -> OriginationDocumentTemplate | None:
    assigned_keys = set(source.document_assignments.values_list('document_key', flat=True))
    source_templates = list(source.document_templates.filter(
        status__in=[
            OriginationDocumentTemplate.STATUS_ACTIVE,
            OriginationDocumentTemplate.STATUS_READY,
        ],
        drive_file_id__gt='',
    ).exclude(
        document_role=OriginationDocumentTemplate.ROLE_SUPPORTING,
        document_key__in=assigned_keys,
    ).select_related('published_configuration_revision').order_by('display_order', 'document_key'))
    if not source_templates:
        fallback = _source_template_for_product(source)
        source_templates = [fallback] if fallback and fallback.drive_file_id else []
    inherited_primary = None
    for source_template in source_templates:
        existing = successor.document_templates.filter(
            document_key=source_template.document_key,
            status__in=[
                OriginationDocumentTemplate.STATUS_READY,
                OriginationDocumentTemplate.STATUS_ACTIVE,
            ],
        ).first()
        if existing:
            inherited_primary = inherited_primary or (
                existing if existing.document_role == existing.ROLE_PRIMARY else None
            )
            continue
        source_revision = source_template.published_configuration_revision
        configuration = json.loads(json.dumps(
            source_revision.configuration if source_revision else source_template.placement_config,
        ))
        document_type = (
            successor.document_type
            if source_template.document_role == source_template.ROLE_PRIMARY
            else f'{successor.product_key}-{source_template.document_key}'[:80]
        )
        template_version = successor.version
        collision = OriginationDocumentTemplate.objects.filter(
            document_type=document_type,
            version=template_version,
            status__in=[
                OriginationDocumentTemplate.STATUS_READY,
                OriginationDocumentTemplate.STATUS_ACTIVE,
            ],
        ).exists()
        if collision:
            # Product versions and PDF-family versions are independent. A
            # reusable family may already own (document_type, version), and a
            # product successor must never retire or collide with that family.
            suffix = (
                'primary' if source_template.document_role == source_template.ROLE_PRIMARY
                else source_template.document_key
            )
            document_type = f'{successor.product_key[:55]}-{suffix[:15]}-owned'[:80]
            template_version = (
                OriginationDocumentTemplate.objects.filter(
                    document_type=document_type,
                ).aggregate(models.Max('version'))['version__max'] or 0
            ) + 1
        configuration['document_type'] = document_type
        configuration['version'] = template_version
        inherited = OriginationDocumentTemplate.objects.create(
            product_definition=successor,
            document_key=source_template.document_key,
            document_role=source_template.document_role,
            inclusion_mode=source_template.inclusion_mode,
            display_order=source_template.display_order,
            officer_selectable=source_template.officer_selectable,
            default_selected=source_template.default_selected,
            applicability_rule=json.loads(json.dumps(source_template.applicability_rule)),
            form_schema=json.loads(json.dumps(
                successor.form_schema
                if source_template.document_role == source_template.ROLE_PRIMARY
                else source_template.form_schema
            )),
            signer_rules=json.loads(json.dumps(
                successor.signer_rules
                if source_template.document_role == source_template.ROLE_PRIMARY
                else source_template.signer_rules
            )),
            document_type=document_type,
            name=(
                f'{successor.name} LAF v{successor.version}'
                if source_template.document_role == source_template.ROLE_PRIMARY
                else source_template.name
            ),
            version=template_version,
            status=OriginationDocumentTemplate.STATUS_READY,
            source_filename=source_template.source_filename,
            source_sha256=source_template.source_sha256,
            source_byte_size=source_template.source_byte_size,
            page_count=source_template.page_count,
            native_consent_policy=source_template.native_consent_policy,
            native_consent_attestation_reference=source_template.native_consent_attestation_reference,
            native_consent_attested_by=source_template.native_consent_attested_by,
            native_consent_attested_at=source_template.native_consent_attested_at,
            placement_config=configuration,
            drive_file_id=source_template.drive_file_id,
            drive_url=source_template.drive_url,
            created_by=actor,
        )
        OriginationTemplateConfigurationRevision.objects.create(
            template=inherited, revision=1, configuration=configuration, created_by=actor,
        )
        OriginationDocumentTemplateEvent.objects.create(
            template=inherited, action='version_inherited', actor=actor,
            metadata={
                'source_template_id': str(source_template.pk),
                'source_product_definition_id': str(source.pk),
                'source_product_version': source.version,
                'product_successor_version': successor.version,
                'template_version': template_version,
                'sha256': source_template.source_sha256,
            },
        )
        if inherited.document_role == inherited.ROLE_PRIMARY:
            inherited_primary = inherited
    return inherited_primary


def _inherit_document_assignments(*, source, successor, actor) -> None:
    for assignment in source.document_assignments.select_related('template').all():
        OriginationProductDocumentAssignment.objects.get_or_create(
            product_definition=successor, document_key=assignment.document_key,
            defaults={
                'template': assignment.template, 'name': assignment.name,
                'version_policy': assignment.version_policy,
                'display_order': assignment.display_order,
                'inclusion_mode': assignment.inclusion_mode,
                'officer_selectable': assignment.officer_selectable,
                'default_selected': assignment.default_selected,
                'applicability_rule': json.loads(json.dumps(assignment.applicability_rule or {})),
                'created_by': actor,
            },
        )


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
        if existing.product_version_id:
            from core.services.origination_commercial_terms import (
                ensure_commercial_catalogue, merge_commercial_contract,
            )
            fields = ensure_commercial_catalogue(actor=actor)
            upgraded_schema = merge_commercial_contract(existing.form_schema, fields=fields)
            if upgraded_schema != existing.form_schema:
                existing.form_schema = upgraded_schema
                existing.save(update_fields=['form_schema', 'updated_at'])
        _inherit_template_for_product_version(
            source=source, successor=existing, actor=actor,
        )
        _inherit_document_assignments(source=source, successor=existing, actor=actor)
        return existing
    global_version = source.product_version
    next_version = (
        OriginationProductDefinition.objects.filter(product_key=source.product_key)
        .aggregate(models.Max('version'))['version__max'] or 0
    ) + 1
    successor_schema = json.loads(json.dumps(source.form_schema))
    if source.product_version_id:
        from core.services.origination_commercial_terms import (
            ensure_commercial_catalogue, merge_commercial_contract,
        )
        fields = ensure_commercial_catalogue(actor=actor)
        successor_schema = merge_commercial_contract(source.form_schema, fields=fields)
    clone = OriginationProductDefinition.objects.create(
        product_version=global_version,
        product_key=source.product_key,
        name=source.name,
        version=next_version,
        form_schema=successor_schema,
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
    inherited_template = _inherit_template_for_product_version(
        source=source, successor=clone, actor=actor,
    )
    _inherit_document_assignments(source=source, successor=clone, actor=actor)
    OriginationProductDefinitionEvent.objects.create(
        product_definition=clone, action='version_created', actor=actor,
        metadata={
            'supersedes_id': str(source.pk),
            'version': next_version,
            'inherited_template_id': (
                str(inherited_template.pk) if inherited_template else ''
            ),
        },
    )
    from core.services.origination_fields import create_conflict_review_issues
    create_conflict_review_issues(clone)
    return clone


def _upload_template_bytes(
    template: OriginationDocumentTemplate, *, pdf_data: bytes,
) -> tuple[str, str]:
    folder_id = str(getattr(settings, 'GOOGLE_DRIVE_MEDIA_FOLDER_ID', '') or '').strip()
    if not folder_id:
        raise OriginationTemplateError('GOOGLE_DRIVE_MEDIA_FOLDER_ID is not configured.')
    from core.services.order_approval import GoogleDriveMediaStorage
    return GoogleDriveMediaStorage(parent_folder_id=folder_id).upload(
        pdf_data, template.source_filename, 'application/pdf', template.document_type,
        timezone.now(), workflow_key='Loan Origination/Templates',
        record_type=template.document_type,
        record_key=f'v{template.version}-{template.source_sha256[:12]}',
    )


def _record_template_upload_failure(
    template: OriginationDocumentTemplate, *, actor, message: str,
) -> OriginationDocumentTemplate:
    template.status = template.STATUS_UPLOAD_FAILED
    template.upload_error = message
    template.save(update_fields=['status', 'upload_error', 'updated_at'])
    OriginationDocumentTemplateEvent.objects.create(
        template=template, action='upload_failed', actor=actor,
    )
    return template


def upload_template_record(template: OriginationDocumentTemplate, *, pdf_data: bytes, actor) -> OriginationDocumentTemplate:
    """Upload a validated, already-persisted template record and retain failures for audit."""
    try:
        file_id, url = _upload_template_bytes(template, pdf_data=pdf_data)
    except OriginationTemplateError as exc:
        return _record_template_upload_failure(
            template, actor=actor, message=str(exc),
        )
    except Exception:
        return _record_template_upload_failure(
            template, actor=actor,
            message='Drive upload failed; retry the PDF upload from the draft product.',
        )
    template.status = template.STATUS_READY
    template.drive_file_id = file_id
    template.drive_url = url
    template.upload_error = ''
    template.save(update_fields=[
        'status', 'drive_file_id', 'drive_url', 'upload_error', 'updated_at',
    ])
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
    # ``OriginationDocumentTemplate`` has a nullable ``product_definition`` and
    # its default ordering traverses that relation.  Leaving that ordering on a
    # locking queryset introduces a LEFT OUTER JOIN; PostgreSQL then rejects
    # ``FOR UPDATE`` because it would lock the nullable side.  Ordering is not
    # meaningful while retiring a document family, so clear it and lock only
    # the template rows we are about to retire.
    previous = list(OriginationDocumentTemplate.objects.order_by().select_for_update(
        of=('self',),
    ).filter(
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
    activation_metadata = {}
    if template.product_definition_id is None:
        family_assignments = OriginationProductDocumentAssignment.objects.filter(
            version_policy=OriginationProductDocumentAssignment.VERSION_LATEST_COMPATIBLE,
            template__document_type=template.document_type,
        ).select_related('template', 'template__published_configuration_revision')
        latest_ids, fallback_ids = [], []
        for assignment in family_assignments:
            resolved = resolve_assignment_template(assignment)
            target = latest_ids if resolved and resolved.pk == template.pk else fallback_ids
            target.append(str(assignment.pk))
        activation_metadata = {
            'document_family': template.document_type,
            'latest_compatible_assignment_ids': latest_ids,
            'fallback_assignment_ids': fallback_ids,
        }
    OriginationDocumentTemplateEvent.objects.create(
        template=template, action='activated', actor=actor,
        metadata=activation_metadata,
    )
    return template


def assignment_template_compatibility_errors(
    baseline: OriginationDocumentTemplate,
    candidate: OriginationDocumentTemplate,
) -> list[str]:
    """Return contract breaks that prevent transparent family-version adoption."""
    errors: list[str] = []
    if candidate.document_role != baseline.document_role:
        errors.append('the candidate changed document role')
    if candidate.document_type != baseline.document_type:
        errors.append('the candidate belongs to another document family')
    if candidate.product_definition_id is not None:
        errors.append('the candidate is not a global shared template')
    if candidate.status not in {candidate.STATUS_ACTIVE, candidate.STATUS_RETIRED}:
        errors.append('the candidate is not published')
    if not candidate.published_configuration_revision_id:
        errors.append('the candidate has no published calibration')

    baseline_fields = {
        str(item.get('key') or ''): item
        for item in (baseline.form_schema or {}).get('fields', [])
        if isinstance(item, dict) and item.get('key')
    }
    candidate_fields = {
        str(item.get('key') or ''): item
        for item in (candidate.form_schema or {}).get('fields', [])
        if isinstance(item, dict) and item.get('key')
    }
    for key, baseline_field in baseline_fields.items():
        candidate_field = candidate_fields.get(key)
        if baseline_field.get('required') and not candidate_field:
            errors.append(f'required field {key} was removed')
            continue
        if candidate_field and str(candidate_field.get('type') or 'text') != str(baseline_field.get('type') or 'text'):
            errors.append(f'field {key} changed type')
            continue
        if candidate_field and str(baseline_field.get('type') or '') == 'repeating_group':
            baseline_columns = {
                str(item.get('key') or ''): item
                for item in ((baseline_field.get('structure') or {}).get('columns') or [])
                if isinstance(item, dict) and item.get('key')
            }
            candidate_columns = {
                str(item.get('key') or ''): item
                for item in ((candidate_field.get('structure') or {}).get('columns') or [])
                if isinstance(item, dict) and item.get('key')
            }
            for column_key, baseline_column in baseline_columns.items():
                candidate_column = candidate_columns.get(column_key)
                if baseline_column.get('required') and not candidate_column:
                    errors.append(f'required column {key}.{column_key} was removed')
                elif candidate_column and str(candidate_column.get('type') or 'text') != str(baseline_column.get('type') or 'text'):
                    errors.append(f'column {key}.{column_key} changed type')

    baseline_requirements = {
        str(item.get('key') or ''): item
        for item in (baseline.form_schema or {}).get('evidence_requirements', [])
        if isinstance(item, dict) and item.get('key')
    }
    candidate_requirements = {
        str(item.get('key') or ''): item
        for item in (candidate.form_schema or {}).get('evidence_requirements', [])
        if isinstance(item, dict) and item.get('key')
    }
    for key, baseline_requirement in baseline_requirements.items():
        baseline_validation = (
            baseline_requirement.get('validation')
            if isinstance(baseline_requirement.get('validation'), dict) else {}
        )
        governed = bool(
            baseline_requirement.get('required') or baseline_validation.get('required_when')
        )
        if not governed:
            continue
        candidate_requirement = candidate_requirements.get(key)
        if not candidate_requirement:
            errors.append(f'required evidence requirement {key} was removed')
        elif str(candidate_requirement.get('type') or '') != str(baseline_requirement.get('type') or ''):
            errors.append(f'evidence requirement {key} changed type')

    baseline_signers = {
        str(item.get('role') or ''): item
        for item in (baseline.signer_rules or [])
        if isinstance(item, dict) and item.get('role')
    }
    candidate_signers = {
        str(item.get('role') or ''): item
        for item in (candidate.signer_rules or [])
        if isinstance(item, dict) and item.get('role')
    }
    for role, baseline_signer in baseline_signers.items():
        if not baseline_signer.get('required'):
            continue
        candidate_signer = candidate_signers.get(role)
        if not candidate_signer:
            errors.append(f'required signer {role} was removed')
            continue
        candidate_slots = {
            str(slot.get('key') if isinstance(slot, dict) else slot): slot
            for slot in (candidate_signer.get('slots') or [])
        }
        for slot in baseline_signer.get('slots') or []:
            normalized = slot if isinstance(slot, dict) else {'key': slot, 'required': True}
            slot_key = str(normalized.get('key') or '')
            slot_required = bool(normalized.get('required', baseline_signer.get('required', True)))
            if slot_required and slot_key not in candidate_slots:
                errors.append(f'required signer slot {role}.{slot_key} was removed')
            elif slot_key in candidate_slots:
                candidate_slot = candidate_slots[slot_key]
                candidate_type = (
                    candidate_slot.get('type') or candidate_slot.get('slot_type') or 'signature'
                    if isinstance(candidate_slot, dict) else 'signature'
                )
                baseline_type = normalized.get('type') or normalized.get('slot_type') or 'signature'
                if str(candidate_type) != str(baseline_type):
                    errors.append(f'signer slot {role}.{slot_key} changed type')
    return errors


def latest_compatible_assignment_template(
    assignment: OriginationProductDocumentAssignment,
) -> OriginationDocumentTemplate | None:
    """Return the newest published member compatible with an assignment baseline."""
    baseline = assignment.template
    if baseline.product_definition_id is not None:
        return baseline if (
            baseline.status in {baseline.STATUS_ACTIVE, baseline.STATUS_RETIRED}
            and baseline.published_configuration_revision_id
        ) else None

    candidates = OriginationDocumentTemplate.objects.filter(
        product_definition__isnull=True,
        document_type=baseline.document_type,
        document_role=baseline.document_role,
        status__in=[
            OriginationDocumentTemplate.STATUS_ACTIVE,
            OriginationDocumentTemplate.STATUS_RETIRED,
        ],
        published_configuration_revision__isnull=False,
    ).select_related('published_configuration_revision').annotate(
        _active_rank=models.Case(
            models.When(status=OriginationDocumentTemplate.STATUS_ACTIVE, then=models.Value(1)),
            default=models.Value(0), output_field=models.IntegerField(),
        ),
    ).order_by('-version', '-_active_rank', '-activated_at', '-created_at')
    return next((item for item in candidates if not assignment_template_compatibility_errors(baseline, item)), None)


def resolve_assignment_template(
    assignment: OriginationProductDocumentAssignment,
) -> OriginationDocumentTemplate | None:
    """Resolve the immutable template revision a newly created application should snapshot."""
    baseline = assignment.template
    if assignment.version_policy == assignment.VERSION_PINNED:
        return baseline if (
            baseline.status in {baseline.STATUS_ACTIVE, baseline.STATUS_RETIRED}
            and baseline.published_configuration_revision_id
        ) else None
    return latest_compatible_assignment_template(assignment)


def upgrade_pinned_primary_assignment(
    *, product_definition: OriginationProductDefinition, assignment_id, actor,
) -> tuple[OriginationProductDocumentAssignment, bool]:
    """Explicitly move a draft product's pinned primary to the newest compatible version."""
    with transaction.atomic():
        product = OriginationProductDefinition.objects.select_for_update().get(
            pk=product_definition.pk,
        )
        if product.lifecycle_status != product.STATUS_DRAFT:
            raise OriginationTemplateError(
                'Create an editable product version before upgrading its main LAF.',
            )
        # Lock the assignment row without joining the template's nullable
        # published revision; PostgreSQL cannot apply FOR UPDATE to that outer join.
        assignment = product.document_assignments.select_for_update().filter(
            pk=assignment_id,
        ).first()
        baseline = (
            OriginationDocumentTemplate.objects.select_related(
                'published_configuration_revision',
            ).filter(pk=assignment.template_id).first()
            if assignment else None
        )
        if not assignment or not baseline or baseline.document_role != baseline.ROLE_PRIMARY:
            raise OriginationTemplateError('Choose this product\'s reusable primary LAF assignment.')
        assignment.template = baseline
        if assignment.version_policy != assignment.VERSION_PINNED:
            raise OriginationTemplateError('Only a pinned primary LAF uses the explicit upgrade action.')
        candidate = latest_compatible_assignment_template(assignment)
        if not candidate or candidate.pk == assignment.template_id:
            return assignment, False
        previous = assignment.template
        assignment.template = candidate
        assignment.name = candidate.name
        assignment.full_clean()
        assignment.save(update_fields=['template', 'name'])
        merged_schema, merged_signers = _merge_shared_primary_contract(
            product=product, template=candidate,
        )
        product.form_schema = merged_schema
        product.signer_rules = merged_signers
        product.document_type = candidate.document_type
        product.document_template_name = candidate.name
        product.document_template_version = candidate.version
        product.document_template_sha256 = candidate.source_sha256
        product.save(update_fields=[
            'form_schema', 'signer_rules', 'document_type', 'document_template_name',
            'document_template_version', 'document_template_sha256', 'updated_at',
        ])
        OriginationProductDefinitionEvent.objects.create(
            product_definition=product, action='shared_primary_upgraded', actor=actor,
            metadata={
                'assignment_id': str(assignment.pk),
                'previous_template_id': str(previous.pk),
                'previous_version': previous.version,
                'template_id': str(candidate.pk),
                'version': candidate.version,
                'version_policy': assignment.version_policy,
            },
        )
        return assignment, True


def replace_draft_template(
    *, product_definition: OriginationProductDefinition, pdf_file, name: str, actor,
) -> OriginationDocumentTemplate:
    """Replace a draft's PDF without mutating or hiding its previous template record."""
    pdf_data = pdf_file.read()
    digest, page_count = validate_template_pdf(pdf_data)
    filename = str(
        getattr(pdf_file, 'name', '')
        or f'{product_definition.document_type}-v{product_definition.version}.pdf'
    )[:255]
    with transaction.atomic():
        product = OriginationProductDefinition.objects.select_for_update().get(
            pk=product_definition.pk,
        )
        if product.lifecycle_status != product.STATUS_DRAFT:
            raise OriginationTemplateError(
                'Templates can only be replaced for a draft product version.',
            )
        current = product.document_templates.filter(
            status__in=[
                OriginationDocumentTemplate.STATUS_READY,
                OriginationDocumentTemplate.STATUS_ACTIVE,
            ],
            document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
        ).order_by('-created_at').first()
        if current and current.source_sha256 == digest:
            return current
        candidate = OriginationDocumentTemplate.objects.create(
            product_definition=product,
            document_type=product.document_type,
            name=str(name or filename).strip()[:180],
            version=product.version,
            status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED,
            source_filename=filename,
            source_sha256=digest,
            source_byte_size=len(pdf_data),
            page_count=page_count,
            placement_config=initial_template_configuration(product),
            upload_error='Replacement upload pending.',
            created_by=actor,
        )
        OriginationDocumentTemplateEvent.objects.create(
            template=candidate,
            action='replacement_created',
            actor=actor,
            metadata={
                'replaces_template_id': str(current.pk) if current else '',
                'sha256': digest,
                'byte_size': len(pdf_data),
                'page_count': page_count,
            },
        )
    try:
        file_id, url = _upload_template_bytes(candidate, pdf_data=pdf_data)
    except OriginationTemplateError as exc:
        return _record_template_upload_failure(
            candidate, actor=actor, message=str(exc),
        )
    except Exception:
        return _record_template_upload_failure(
            candidate, actor=actor,
            message='Drive upload failed; the current draft template remains available.',
        )
    with transaction.atomic():
        product = OriginationProductDefinition.objects.select_for_update().get(
            pk=product_definition.pk,
        )
        candidate = OriginationDocumentTemplate.objects.select_for_update().get(
            pk=candidate.pk,
        )
        if product.lifecycle_status != product.STATUS_DRAFT:
            candidate.drive_file_id = file_id
            candidate.drive_url = url
            candidate.upload_error = (
                'The product changed while the replacement uploaded. Its current '
                'published template was left unchanged.'
            )
            candidate.save(update_fields=[
                'drive_file_id', 'drive_url', 'upload_error', 'updated_at',
            ])
            OriginationDocumentTemplateEvent.objects.create(
                template=candidate,
                action='replacement_abandoned',
                actor=actor,
                metadata={'product_status': product.lifecycle_status},
            )
            return candidate
        previous = list(product.document_templates.select_for_update().filter(
            status__in=[
                OriginationDocumentTemplate.STATUS_READY,
                OriginationDocumentTemplate.STATUS_ACTIVE,
            ],
            document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
        ).exclude(pk=candidate.pk))
        for old in previous:
            old.status = old.STATUS_RETIRED
            old.save(update_fields=['status', 'updated_at'])
            OriginationDocumentTemplateEvent.objects.create(
                template=old,
                action='retired_for_replacement',
                actor=actor,
                metadata={'replacement_template_id': str(candidate.pk)},
            )
        candidate.status = candidate.STATUS_READY
        candidate.drive_file_id = file_id
        candidate.drive_url = url
        candidate.upload_error = ''
        candidate.save(update_fields=[
            'status', 'drive_file_id', 'drive_url', 'upload_error', 'updated_at',
        ])
        OriginationDocumentTemplateEvent.objects.create(
            template=candidate,
            action='uploaded',
            actor=actor,
            metadata={'replaced_template_ids': [str(item.pk) for item in previous]},
        )
        OriginationTemplateConfigurationRevision.objects.create(
            template=candidate,
            revision=1,
            configuration=candidate.placement_config,
            created_by=actor,
        )
    return candidate


@transaction.atomic
def publish_product_template(
    *, template: OriginationDocumentTemplate, revision: int, actor,
    client_request_id: str = '', product_definition: OriginationProductDefinition | None = None,
) -> tuple[OriginationProductDefinition | None, OriginationDocumentTemplate, OriginationTemplateConfigurationRevision]:
    """Publish calibration, activate its immutable PDF, and expose the product atomically."""
    # Lock only the template row. ``product_definition`` is nullable, so
    # combining select_for_update() with select_related() makes PostgreSQL try
    # to lock the nullable side of a LEFT OUTER JOIN, which it rejects. The
    # product row is locked explicitly below when the template has one.
    template = OriginationDocumentTemplate.objects.select_for_update().get(
        pk=template.pk,
    )
    publishing_assigned_primary = bool(product_definition and not template.product_definition_id)
    if not template.product_definition_id and not publishing_assigned_primary:
        published = publish_calibration(
            template=template, revision=revision, actor=actor,
            client_request_id=client_request_id,
        )
        return None, activate_template(template, actor=actor), published
    product = OriginationProductDefinition.objects.select_for_update().get(
        pk=product_definition.pk if publishing_assigned_primary else template.product_definition_id,
    )
    if (
        product.lifecycle_status == product.STATUS_PUBLISHED
        and product.is_active
        and template.status == template.STATUS_ACTIVE
        and template.published_configuration_revision_id
    ):
        return product, template, template.published_configuration_revision
    if product.lifecycle_status != product.STATUS_DRAFT:
        raise OriginationTemplateError('Only a draft product version can be published.')
    from core.services.origination_fields import bind_compatible_schema_fields, unresolved_review_keys
    bind_compatible_schema_fields(product, create_issues=True)
    unresolved_fields = unresolved_review_keys(product)
    if unresolved_fields:
        raise OriginationTemplateError(
            'Resolve legacy data fields before publishing: '
            + ', '.join(unresolved_fields)
            + '.',
        )

    selected = (
        template.published_configuration_revision
        if publishing_assigned_primary else template.configuration_revisions.get(revision=revision)
    )
    if publishing_assigned_primary and (
        template.document_role != template.ROLE_PRIMARY
        or template.status != template.STATUS_ACTIVE
        or not selected
    ):
        raise OriginationTemplateError('The assigned primary LAF must be published before the product.')
    validate_template_configuration(
        selected.configuration, template=template, require_complete=True,
    )
    if template.document_role == template.ROLE_SUPPORTING and not publishing_assigned_primary:
        published = publish_calibration(
            template=template, revision=revision, actor=actor,
            client_request_id=client_request_id,
        )
        activated = activate_template(template, actor=actor)
        OriginationDocumentTemplateEvent.objects.create(
            template=activated, action='supporting_document_published', actor=actor,
            metadata={'configuration_revision': published.revision},
        )
        return product, activated, published

    supporting_not_ready = product.document_templates.filter(
        document_role=OriginationDocumentTemplate.ROLE_SUPPORTING,
    ).exclude(status__in=[
        OriginationDocumentTemplate.STATUS_ACTIVE,
        OriginationDocumentTemplate.STATUS_UPLOAD_FAILED,
    ])
    if supporting_not_ready.exists():
        raise OriginationTemplateError(
            'Publish or remove every supporting document before publishing the product.',
        )
    packet_templates = list(product.document_templates.filter(status__in=[
        OriginationDocumentTemplate.STATUS_READY,
        OriginationDocumentTemplate.STATUS_ACTIVE,
    ]))
    assignments = list(product.document_assignments.select_related('template').all())
    resolved_assignments = [
        (item, resolve_assignment_template(item)) for item in assignments
    ]
    invalid_assignments = [item for item, resolved in resolved_assignments if not resolved]
    if invalid_assignments:
        raise OriginationTemplateError('Every reusable document must have a compatible published version before the product.')
    primaries = [item for item in packet_templates if item.document_role == item.ROLE_PRIMARY]
    primaries.extend(
        resolved for _assignment, resolved in resolved_assignments
        if resolved and resolved.document_role == resolved.ROLE_PRIMARY
    )
    if len(primaries) != 1:
        raise OriginationTemplateError('A published product requires exactly one primary LAF.')
    primary_template = primaries[0]
    if publishing_assigned_primary and primary_template.pk != template.pk:
        raise OriginationTemplateError('The selected reusable primary LAF is not this product\'s resolved primary.')
    product_fields = {
        str(item.get('key') or ''): item
        for item in (product.form_schema or {}).get('fields', [])
        if isinstance(item, dict) and item.get('key')
    }
    for field in (primary_template.form_schema or {}).get('fields', []) or []:
        if not isinstance(field, dict) or not field.get('key'):
            continue
        key = str(field['key'])
        product_field = product_fields.get(key)
        if field.get('required') and not product_field:
            raise OriginationTemplateError(
                f'The primary LAF requires canonical field {key}; restore it to the product form.',
            )
        if product_field and str(product_field.get('type') or 'text') != str(field.get('type') or 'text'):
            raise OriginationTemplateError(
                f'The primary LAF and product disagree on the type of {key}.',
            )
    keys = [item.document_key for item in packet_templates if item.document_role == item.ROLE_PRIMARY]
    keys.extend(item.document_key for item in assignments)
    keys.extend(
        item.document_key for item in packet_templates
        if item.document_role == item.ROLE_SUPPORTING
        and item.document_key not in {assignment.document_key for assignment in assignments}
    )
    if len(keys) != len(set(keys)):
        raise OriginationTemplateError('Document keys must be unique within a product version.')
    from core.services.loan_origination import (
        APPLICANT_IDENTITY_CONTRACT,
        OriginationError,
        require_applicant_identity_fields,
        validate_applicant_identity_contract,
    )
    if (product.form_schema or {}).get('identity_contract') == APPLICANT_IDENTITY_CONTRACT:
        try:
            product.form_schema = require_applicant_identity_fields(
                product.form_schema, product.signer_rules,
            )
            validate_applicant_identity_contract(product.form_schema, product.signer_rules)
            if not publishing_assigned_primary and template.form_schema != product.form_schema:
                template.form_schema = json.loads(json.dumps(product.form_schema))
                template.save(update_fields=['form_schema', 'updated_at'])
                OriginationDocumentTemplateEvent.objects.create(
                    template=template, action='applicant_identity_contract_normalized',
                    actor=actor,
                    metadata={
                        'required_field_keys': sorted(
                            str(item.get('key') or '')
                            for item in product.form_schema.get('fields', [])
                            if isinstance(item, dict) and item.get('required')
                        ),
                    },
                )
        except OriginationError as exc:
            raise OriginationTemplateError(str(exc)) from exc
    from core.services.origination_documents import validate_applicability_rule
    allowed_fields = {
        str(item.get('key')) for item in (product.form_schema or {}).get('fields', [])
        if isinstance(item, dict) and item.get('key')
    }
    for packet_template in packet_templates:
        document_fields = {
            str(item.get('key'))
            for item in (packet_template.form_schema or {}).get('fields', [])
            if isinstance(item, dict) and item.get('key')
        }
        try:
            validate_applicability_rule(
                packet_template.applicability_rule,
                allowed_fields=allowed_fields | document_fields,
            )
        except ValueError as exc:
            raise OriginationTemplateError(str(exc)) from exc
    for assignment, resolved_template in resolved_assignments:
        document_fields = {
            str(item.get('key'))
            for item in (resolved_template.form_schema or {}).get('fields', [])
            if isinstance(item, dict) and item.get('key')
        }
        try:
            validate_applicability_rule(
                assignment.applicability_rule,
                allowed_fields=allowed_fields | document_fields,
            )
        except ValueError as exc:
            raise OriginationTemplateError(str(exc)) from exc
    if product.product_version_id:
        from core.services.product_catalog import ProductCatalogError, publish_product_version
        try:
            publish_product_version(version=product.product_version, actor=actor)
        except ProductCatalogError as exc:
            raise OriginationTemplateError(str(exc)) from exc
    if publishing_assigned_primary:
        published = selected
        activated = template
    else:
        published = publish_calibration(
            template=template, revision=revision, actor=actor,
            client_request_id=client_request_id,
        )
        activated = activate_template(template, actor=actor)

    product.document_type = primary_template.document_type
    product.document_template_name = primary_template.name
    product.document_template_version = primary_template.version
    product.document_template_sha256 = primary_template.source_sha256
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
        'form_schema', 'document_type', 'document_template_name', 'document_template_version', 'document_template_sha256',
        'is_active', 'lifecycle_status', 'published_by', 'published_at', 'updated_at',
    ])
    if not was_published:
        product_event = OriginationProductDefinitionEvent.objects.create(
            product_definition=product, action='published', actor=actor,
            metadata={
                'template_id': str(primary_template.pk),
                'template_sha256': primary_template.source_sha256,
                'configuration_revision': published.revision,
                'shared_document_resolutions': [
                    {
                        'assignment_id': str(assignment.pk),
                        'family': assignment.template.document_type,
                        'version_policy': assignment.version_policy,
                        'resolved_template_id': str(resolved_template.pk),
                        'resolved_version': resolved_template.version,
                    }
                    for assignment, resolved_template in resolved_assignments
                ],
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
            metadata={'template_id': str(primary_template.pk), 'template_sha256': primary_template.source_sha256},
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
