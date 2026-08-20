"""Governed canonical data fields for origination forms, PDFs, and reporting."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import (
    LoanOriginationApplication,
    OriginationDataField,
    OriginationDataFieldEvent,
    OriginationFieldReviewIssue,
    OriginationDocumentTemplate,
    OriginationDocumentTemplateEvent,
    OriginationProductDefinition,
    OriginationProductDefinitionEvent,
    OriginationReportingValue,
)
from core.services.origination_terminology import (
    aliases_with_legacy_terms,
    field_terminology_signatures,
)


class OriginationFieldError(ValueError):
    """Stable, user-safe catalogue validation error."""


class OriginationFieldConflict(OriginationFieldError):
    """A stale schema revision or incompatible canonical field was supplied."""


def normalize_field_key(value: Any) -> str:
    key = re.sub(r'[^a-z0-9_]+', '_', str(value or '').strip().casefold()).strip('_')
    if not key:
        raise OriginationFieldError('Enter a canonical field key.')
    return key[:120]


def normalize_choice_options(options: Any) -> list[dict[str, Any]]:
    if not isinstance(options, list):
        raise OriginationFieldError('Choice options must be a list.')
    normalized = []
    seen = set()
    for raw in options:
        if isinstance(raw, dict):
            label = str(raw.get('label') or raw.get('code') or '').strip()
            code = normalize_field_key(raw.get('code') or label)
            active = raw.get('active', True) is not False
        else:
            label = str(raw or '').strip()
            code = normalize_field_key(label)
            active = True
        if not label:
            raise OriginationFieldError('Every choice requires a label.')
        if code in seen:
            raise OriginationFieldError(f'Duplicate canonical choice code: {code}.')
        seen.add(code)
        normalized.append({'code': code, 'label': label[:160], 'active': active})
    if not normalized:
        raise OriginationFieldError('Choice fields require at least one option.')
    return normalized


def serialize_data_field(data_field: OriginationDataField, *, attached: bool = False) -> dict[str, Any]:
    return {
        'id': str(data_field.pk),
        'key': data_field.key,
        'label': data_field.label,
        'aliases': list(data_field.aliases or []),
        'category': data_field.category,
        'type': data_field.data_type,
        'source_type': data_field.source_type,
        'sensitivity': data_field.sensitivity,
        'masking_policy': data_field.masking_policy,
        'reporting_use': data_field.reporting_use,
        'export_allowed': data_field.export_allowed,
        'help_text': data_field.help_text,
        'choice_options': list(data_field.choice_options or []),
        'structure_schema': dict(data_field.structure_schema or {}),
        'active': data_field.active,
        'preferred_field_id': str(data_field.preferred_field_id or ''),
        'attached': attached,
    }


def _semantic_signatures_for_field(data_field: OriginationDataField) -> set[str]:
    return field_terminology_signatures(
        data_field.key, data_field.label, *(data_field.aliases or []),
    )


def semantic_field_conflict(
    *, key: str, label: str, aliases: list[str] | None = None,
    exclude_id=None,
) -> OriginationDataField | None:
    """Find an active field represented by the same approved terminology."""

    requested = field_terminology_signatures(key, label, *(aliases or []))
    if not requested:
        return None
    candidates = OriginationDataField.objects.select_for_update().filter(
        active=True,
    ).order_by('created_at', 'key')
    if exclude_id:
        candidates = candidates.exclude(pk=exclude_id)
    for candidate in candidates:
        if requested & _semantic_signatures_for_field(candidate):
            return candidate
    return None


def terminology_audit_candidates() -> list[dict[str, Any]]:
    """Return unresolved active-field pairs that appear semantically equivalent."""

    fields = list(OriginationDataField.objects.filter(
        active=True, preferred_field__isnull=True,
    ).order_by('category', 'label', 'key'))
    rows: list[dict[str, Any]] = []
    for index, left in enumerate(fields):
        if left.terminology_reviewed_distinct:
            continue
        left_signatures = _semantic_signatures_for_field(left)
        for right in fields[index + 1:]:
            if right.terminology_reviewed_distinct:
                continue
            signatures = left_signatures & _semantic_signatures_for_field(right)
            if not signatures:
                continue
            preferred, duplicate = sorted(
                (left, right),
                key=lambda item: (
                    not item.key.startswith('applicant_'),
                    item.key != 'applicant',
                    item.created_at,
                    item.key,
                ),
            )
            rows.append({
                'preferred': preferred,
                'duplicate': duplicate,
                'same_type': preferred.data_type == duplicate.data_type,
                'matched_names': sorted(signatures),
            })
    return rows


@transaction.atomic
def consolidate_data_field(
    *, duplicate: OriginationDataField, preferred: OriginationDataField, actor,
) -> OriginationDataField:
    """Retire an explicit duplicate without touching historical contracts."""

    if not getattr(actor, 'is_superuser', False):
        raise OriginationFieldError('Only a Django Superuser may consolidate canonical fields.')
    duplicate = OriginationDataField.objects.select_for_update().get(pk=duplicate.pk)
    preferred = OriginationDataField.objects.select_for_update().get(pk=preferred.pk)
    if duplicate.pk == preferred.pk:
        raise OriginationFieldError('Choose two different canonical fields.')
    if not duplicate.active and duplicate.preferred_field_id == preferred.pk:
        return duplicate
    if not duplicate.active or duplicate.preferred_field_id:
        raise OriginationFieldError('Choose an active duplicate field that has not been consolidated.')
    if not preferred.active or preferred.preferred_field_id:
        raise OriginationFieldError('Choose an active preferred canonical field.')
    if duplicate.data_type != preferred.data_type:
        raise OriginationFieldConflict('Only fields with the same data type can be consolidated.')
    preferred.aliases = aliases_with_legacy_terms(
        duplicate.label,
        duplicate.key,
        [*(preferred.aliases or []), *(duplicate.aliases or [])],
    )
    preferred.save(update_fields=['aliases', 'updated_at'])
    duplicate.active = False
    duplicate.preferred_field = preferred
    duplicate.terminology_reviewed_distinct = False
    duplicate.save(update_fields=[
        'active', 'preferred_field', 'terminology_reviewed_distinct', 'updated_at',
    ])
    OriginationDataFieldEvent.objects.create(
        data_field=preferred, action='terminology_aliases_merged', actor=actor,
        metadata={'legacy_field_id': str(duplicate.pk), 'legacy_key': duplicate.key},
    )
    OriginationDataFieldEvent.objects.create(
        data_field=duplicate, action='terminology_consolidated', actor=actor,
        metadata={'preferred_field_id': str(preferred.pk), 'preferred_key': preferred.key},
    )
    return duplicate


@transaction.atomic
def mark_data_field_terminology_distinct(*, data_field: OriginationDataField, actor) -> OriginationDataField:
    if not getattr(actor, 'is_superuser', False):
        raise OriginationFieldError('Only a Django Superuser may review canonical fields.')
    data_field = OriginationDataField.objects.select_for_update().get(pk=data_field.pk)
    if not data_field.active or data_field.preferred_field_id:
        raise OriginationFieldError('Only active canonical fields can be confirmed as distinct.')
    if not data_field.terminology_reviewed_distinct:
        data_field.terminology_reviewed_distinct = True
        data_field.save(update_fields=['terminology_reviewed_distinct', 'updated_at'])
        OriginationDataFieldEvent.objects.create(
            data_field=data_field, action='terminology_confirmed_distinct', actor=actor,
            metadata={'key': data_field.key},
        )
    return data_field


def product_schema_revision(product: OriginationProductDefinition) -> int:
    try:
        return int((product.form_schema or {}).get('_revision') or 0)
    except (TypeError, ValueError):
        return 0


def template_schema_revision(template: OriginationDocumentTemplate) -> int:
    try:
        return int((template.form_schema or {}).get('_revision') or 0)
    except (TypeError, ValueError):
        return 0


def catalogue_for_product(product: OriginationProductDefinition | None) -> list[dict[str, Any]]:
    schema_fields = (product.form_schema or {}).get('fields', []) if product else []
    attached_keys = {
        str(item.get('key') or '') for item in schema_fields if isinstance(item, dict)
    }
    catalogue = [
        serialize_data_field(item, attached=item.key in attached_keys)
        for item in OriginationDataField.objects.filter(active=True).order_by('category', 'label', 'key')
    ]
    known_keys = {item['key'] for item in catalogue}
    for item in schema_fields:
        if not isinstance(item, dict):
            continue
        key = str(item.get('key') or '').strip()
        if not key or key in known_keys:
            continue
        catalogue.append({
            'id': str(item.get('data_field_id') or ''),
            'key': key,
            'label': str(item.get('label') or key.replace('_', ' ').title()),
            'aliases': [], 'category': 'Legacy',
            'type': str(item.get('type') or 'text'),
            'source_type': OriginationDataField.SOURCE_USER_INPUT,
            'sensitivity': str(item.get('sensitivity') or OriginationDataField.SENSITIVITY_PII),
            'masking_policy': str(item.get('masking_policy') or OriginationDataField.MASK_PARTIAL),
            'reporting_use': str(item.get('reporting_use') or OriginationDataField.REPORT_UNAVAILABLE),
            'export_allowed': bool(item.get('export_allowed', False)),
            'help_text': str(item.get('help_text') or ''),
            'choice_options': list(item.get('options') or []),
            'active': True, 'attached': True, 'legacy': True,
        })
    return sorted(
        catalogue,
        key=lambda item: (not item.get('attached'), item.get('category', ''), item.get('label', '')),
    )


@transaction.atomic
def create_data_field(*, payload: dict[str, Any], actor) -> tuple[OriginationDataField, bool]:
    if not getattr(actor, 'is_superuser', False):
        raise OriginationFieldError('Only a Django Superuser may create canonical fields.')
    label = str(payload.get('label') or '').strip()
    if not label:
        raise OriginationFieldError('Enter a data-field label.')
    key = normalize_field_key(payload.get('key') or label)
    data_type = str(payload.get('type') or OriginationDataField.TYPE_TEXT).strip()
    if data_type not in dict(OriginationDataField.TYPE_CHOICES):
        raise OriginationFieldError('Choose a supported data type.')
    existing = OriginationDataField.objects.select_for_update().filter(key=key).first()
    if existing:
        if existing.data_type != data_type:
            raise OriginationFieldConflict(
                f'{key} already exists with type {existing.get_data_type_display()}.',
            )
        return existing, True
    aliases = [str(item).strip() for item in (payload.get('aliases') or []) if str(item).strip()]
    equivalent = semantic_field_conflict(key=key, label=label, aliases=aliases)
    if equivalent:
        if equivalent.data_type != data_type:
            raise OriginationFieldConflict(
                f'“{label}” appears to mean the same thing as {equivalent.label} '
                f'({equivalent.key}), but that field uses '
                f'{equivalent.get_data_type_display()}. Review the existing field instead of creating another.',
            )
        raise OriginationFieldConflict(
            f'“{label}” appears to mean the same thing as {equivalent.label} '
            f'({equivalent.key}). Reuse that canonical field and add this wording as an alias if needed.',
        )
    options = payload.get('choice_options') or []
    if data_type == OriginationDataField.TYPE_CHOICE:
        options = normalize_choice_options(options)
    elif options:
        raise OriginationFieldError('Only choice fields may define choice options.')
    structure_schema = payload.get('structure_schema') or {}
    if data_type != OriginationDataField.TYPE_REPEATING_GROUP and structure_schema:
        raise OriginationFieldError('Only repeatable-group fields may define a structure.')
    sensitivity = str(
        payload.get('sensitivity') or OriginationDataField.SENSITIVITY_PII
    ).strip()
    if sensitivity not in dict(OriginationDataField.SENSITIVITY_CHOICES):
        raise OriginationFieldError('Choose a supported sensitivity classification.')
    masking = str(payload.get('masking_policy') or '').strip()
    if not masking:
        masking = (
            OriginationDataField.MASK_NONE
            if sensitivity in {
                OriginationDataField.SENSITIVITY_PUBLIC,
                OriginationDataField.SENSITIVITY_INTERNAL,
            }
            else OriginationDataField.MASK_PARTIAL
        )
    data_field = OriginationDataField.objects.create(
        key=key, label=label[:160],
        aliases=aliases,
        category=str(payload.get('category') or 'Application').strip()[:80],
        data_type=data_type,
        source_type=OriginationDataField.SOURCE_USER_INPUT,
        sensitivity=sensitivity,
        masking_policy=masking,
        reporting_use=str(
            payload.get('reporting_use') or OriginationDataField.REPORT_UNAVAILABLE
        ).strip(),
        export_allowed=bool(payload.get('export_allowed', False)),
        help_text=str(payload.get('help_text') or '').strip()[:500],
        choice_options=options,
        structure_schema=structure_schema,
        created_by=actor,
    )
    OriginationDataFieldEvent.objects.create(
        data_field=data_field, action='created', actor=actor,
        metadata={
            'key': data_field.key, 'type': data_field.data_type,
            'sensitivity': data_field.sensitivity,
            'reporting_use': data_field.reporting_use,
        },
    )
    return data_field, False


def _product_choice_options(data_field: OriginationDataField, requested: Any) -> list[dict[str, str]]:
    canonical = {
        str(item.get('code')): item
        for item in (data_field.choice_options or [])
        if isinstance(item, dict) and item.get('code')
    }
    requested = requested or [
        {'code': code, 'label': item.get('label') or code}
        for code, item in canonical.items() if item.get('active', True)
    ]
    if not isinstance(requested, list) or not requested:
        raise OriginationFieldError('Choose at least one option for this product.')
    normalized = []
    seen = set()
    for raw in requested:
        code = str(raw.get('code') if isinstance(raw, dict) else raw).strip()
        if code not in canonical:
            raise OriginationFieldError(f'Unknown canonical choice code: {code}.')
        if code in seen:
            raise OriginationFieldError(f'Duplicate product choice code: {code}.')
        seen.add(code)
        label = str(
            raw.get('label') if isinstance(raw, dict) else canonical[code].get('label')
        ).strip()
        normalized.append({'code': code, 'label': label[:160] or canonical[code]['label']})
    return normalized


def _field_schema_item(data_field: OriginationDataField, presentation: dict[str, Any]) -> dict[str, Any]:
    validation = presentation.get('validation') or {}
    if not isinstance(validation, dict):
        raise OriginationFieldError('Product field validation must be an object.')
    allowed_validation = {
        key: value for key, value in validation.items()
        if key in {'min', 'max', 'min_length', 'max_length', 'pattern', 'min_date', 'max_date'}
        and value not in (None, '')
    }
    item = {
        'data_field_id': str(data_field.pk),
        'key': data_field.key,
        'label': str(presentation.get('label') or data_field.label).strip()[:160],
        'type': data_field.data_type,
        'section_key': str(presentation.get('section_key') or '').strip(),
        'required': bool(presentation.get('required', False)),
        'width': str(presentation.get('width') or 'half').strip(),
        'help_text': str(presentation.get('help_text') or data_field.help_text).strip()[:500],
        'sensitivity': data_field.sensitivity,
        'masking_policy': data_field.masking_policy,
        'reporting_use': data_field.reporting_use,
        'export_allowed': data_field.export_allowed,
        'source_type': data_field.source_type,
        'validation': allowed_validation,
    }
    if data_field.data_type == OriginationDataField.TYPE_REPEATING_GROUP:
        item['structure'] = json.loads(json.dumps(data_field.structure_schema or {}))
    if item['width'] not in {'half', 'full'}:
        raise OriginationFieldError('Field width must be half or full.')
    if data_field.data_type == OriginationDataField.TYPE_CHOICE:
        item['options'] = _product_choice_options(data_field, presentation.get('options'))
    else:
        item['options'] = []
    return item


@transaction.atomic
def attach_data_field(
    *, product: OriginationProductDefinition, data_field: OriginationDataField,
    presentation: dict[str, Any], actor, expected_schema_revision: int,
) -> tuple[OriginationProductDefinition, bool]:
    if not getattr(actor, 'is_superuser', False):
        raise OriginationFieldError('Only a Django Superuser may change a product schema.')
    product = OriginationProductDefinition.objects.select_for_update().get(pk=product.pk)
    if product.lifecycle_status != product.STATUS_DRAFT:
        raise OriginationFieldError('Create a new draft product version before changing its fields.')
    schema = json.loads(json.dumps(product.form_schema or {}))
    schema['fields'] = [item for item in (schema.get('fields') or []) if isinstance(item, dict)]
    existing = next(
        (item for item in schema['fields'] if str(item.get('key') or '') == data_field.key),
        None,
    )
    if existing:
        if str(existing.get('type') or 'text') != data_field.data_type:
            raise OriginationFieldConflict(
                f'{data_field.key} is already attached with an incompatible type.',
            )
        return product, True
    actual_revision = product_schema_revision(product)
    if int(expected_schema_revision) != actual_revision:
        raise OriginationFieldConflict('This product form changed. Reload before adding the field.')
    if data_field.source_type == OriginationDataField.SOURCE_SYSTEM:
        return product, True
    sections = [item for item in (schema.get('sections') or []) if isinstance(item, dict)]
    if not sections:
        sections = [{'key': 'application', 'label': 'Application', 'help_text': ''}]
    schema['sections'] = sections
    section_key = str(presentation.get('section_key') or sections[0].get('key') or '').strip()
    if section_key not in {str(item.get('key') or '') for item in sections}:
        raise OriginationFieldError('Choose an existing product-form section.')
    presentation = {**presentation, 'section_key': section_key}
    schema['fields'].append(_field_schema_item(data_field, presentation))
    schema['_revision'] = actual_revision + 1
    product.form_schema = schema
    product.save(update_fields=['form_schema', 'updated_at'])
    OriginationProductDefinitionEvent.objects.create(
        product_definition=product, action='field_attached', actor=actor,
        metadata={'field_id': str(data_field.pk), 'field_key': data_field.key},
    )
    OriginationDataFieldEvent.objects.create(
        data_field=data_field, action='attached', actor=actor,
        metadata={'product_definition_id': str(product.pk), 'product_key': product.product_key},
    )
    return product, False


@transaction.atomic
def attach_data_field_to_template(
    *, template: OriginationDocumentTemplate, data_field: OriginationDataField,
    presentation: dict[str, Any], actor, expected_schema_revision: int,
) -> tuple[OriginationDocumentTemplate, bool]:
    """Attach a canonical field to a supporting template without polluting the main LAF."""
    if not getattr(actor, 'is_superuser', False):
        raise OriginationFieldError('Only a Django Superuser may change a supporting-document schema.')
    template = OriginationDocumentTemplate.objects.select_for_update().get(pk=template.pk)
    if template.document_role != template.ROLE_SUPPORTING:
        raise OriginationFieldError('Only supporting documents use a document-specific schema.')
    if template.status not in {template.STATUS_READY, template.STATUS_UPLOAD_FAILED}:
        raise OriginationFieldError('Create a new template revision before changing a published schema.')
    if template.product_definition_id and template.product_definition.lifecycle_status != OriginationProductDefinition.STATUS_DRAFT:
        raise OriginationFieldError('Create a new draft product version before changing this supporting document.')
    schema = json.loads(json.dumps(template.form_schema or {}))
    schema['fields'] = [item for item in (schema.get('fields') or []) if isinstance(item, dict)]
    existing = next((item for item in schema['fields'] if str(item.get('key') or '') == data_field.key), None)
    if existing:
        if str(existing.get('type') or 'text') != data_field.data_type:
            raise OriginationFieldConflict(f'{data_field.key} is already attached with an incompatible type.')
        return template, True
    actual_revision = template_schema_revision(template)
    if int(expected_schema_revision) != actual_revision:
        raise OriginationFieldConflict('This supporting-document schema changed. Reload before adding the field.')
    sections = [item for item in (schema.get('sections') or []) if isinstance(item, dict)]
    if not sections:
        sections = [{'key': 'document', 'label': template.name, 'help_text': ''}]
    schema['sections'] = sections
    presentation = {**presentation, 'section_key': str(presentation.get('section_key') or sections[0]['key'])}
    schema['fields'].append(_field_schema_item(data_field, presentation))
    schema['_revision'] = actual_revision + 1
    template.form_schema = schema
    template.save(update_fields=['form_schema', 'updated_at'])
    OriginationDocumentTemplateEvent.objects.create(
        template=template, action='schema_field_attached', actor=actor,
        metadata={'field_key': data_field.key, 'schema_revision': schema['_revision']},
    )
    OriginationDataFieldEvent.objects.create(
        data_field=data_field, action='attached_to_supporting_template', actor=actor,
        metadata={'template_id': str(template.pk)},
    )
    return template, False


def bind_compatible_schema_fields(
    product: OriginationProductDefinition, *, create_issues: bool = True,
) -> bool:
    """Bind safe draft legacy fields and make every ambiguous field visible in Admin."""
    if product.lifecycle_status != product.STATUS_DRAFT:
        return False
    schema = json.loads(json.dumps(product.form_schema or {}))
    fields = [item for item in (schema.get('fields') or []) if isinstance(item, dict)]
    changed = False
    for item in fields:
        key = str(item.get('key') or '').strip()
        field_type = str(item.get('type') or 'text').strip()
        if not key or item.get('data_field_id'):
            continue
        candidate = OriginationDataField.objects.filter(key=key, data_type=field_type).first()
        conflicting = OriginationDataField.objects.filter(key=key).exclude(data_type=field_type).first()
        if not candidate and not conflicting:
            try:
                financial = field_type == OriginationDataField.TYPE_MONEY or any(
                    token in key for token in ('income', 'expense', 'amount', 'interest', 'balance')
                )
                pii = field_type in {
                    OriginationDataField.TYPE_PHONE, OriginationDataField.TYPE_NATIONAL_ID,
                } or any(
                    token in key for token in ('name', 'address', 'location', 'email', 'dob')
                )
                sensitivity = (
                    OriginationDataField.SENSITIVITY_FINANCIAL if financial else
                    OriginationDataField.SENSITIVITY_PII if pii else
                    OriginationDataField.SENSITIVITY_INTERNAL
                )
                choice_options = (
                    normalize_choice_options(item.get('options') or [])
                    if field_type == OriginationDataField.TYPE_CHOICE else []
                )
                candidate = OriginationDataField.objects.create(
                    key=key,
                    label=str(item.get('label') or key.replace('_', ' ').title())[:160],
                    category='Legacy import', data_type=field_type,
                    sensitivity=sensitivity,
                    masking_policy=(
                        OriginationDataField.MASK_PARTIAL
                        if sensitivity in {
                            OriginationDataField.SENSITIVITY_PII,
                            OriginationDataField.SENSITIVITY_FINANCIAL,
                        } else OriginationDataField.MASK_NONE
                    ),
                    reporting_use=OriginationDataField.REPORT_UNAVAILABLE,
                    choice_options=choice_options,
                    created_by=product.created_by,
                )
                OriginationDataFieldEvent.objects.create(
                    data_field=candidate, action='legacy_imported', actor=product.created_by,
                    metadata={
                        'key': candidate.key, 'type': candidate.data_type,
                        'product_definition_id': str(product.pk),
                    },
                )
            except (OriginationFieldError, ValidationError):
                candidate = None
        if candidate:
            presentation = dict(item)
            if field_type == OriginationDataField.TYPE_CHOICE:
                presentation.pop('options', None)
            snapshot = _field_schema_item(candidate, presentation)
            snapshot.update({
                'label': item.get('label') or snapshot['label'],
                'required': bool(item.get('required', False)),
                'width': item.get('width') or snapshot['width'],
                'section_key': item.get('section_key') or snapshot['section_key'],
                'help_text': item.get('help_text') or snapshot['help_text'],
            })
            if field_type == OriginationDataField.TYPE_CHOICE and item.get('options'):
                # Preserve legacy stored values until a Superuser explicitly
                # reviews the choice-code conversion.
                snapshot['options'] = item['options']
            item.clear()
            item.update(snapshot)
            changed = True
            continue
        if create_issues:
            OriginationFieldReviewIssue.objects.get_or_create(
                product_definition=product, legacy_key=key,
                defaults={
                    'legacy_type': field_type,
                    'legacy_label': str(item.get('label') or key.replace('_', ' ').title()),
                    'reason': 'type_conflict' if conflicting else 'missing_catalogue_field',
                    'suggested_field': conflicting,
                },
            )
    if changed:
        schema['fields'] = fields
        schema['_revision'] = product_schema_revision(product) + 1
        product.form_schema = schema
        product.save(update_fields=['form_schema', 'updated_at'])
    return changed


def create_conflict_review_issues(product: OriginationProductDefinition) -> int:
    """Expose known key/type collisions without rewriting a freshly cloned schema."""
    created = 0
    for item in (product.form_schema or {}).get('fields', []) or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get('key') or '').strip()
        field_type = str(item.get('type') or 'text').strip()
        conflict = OriginationDataField.objects.filter(key=key).exclude(data_type=field_type).first()
        if not conflict:
            continue
        _issue, was_created = OriginationFieldReviewIssue.objects.get_or_create(
            product_definition=product, legacy_key=key,
            defaults={
                'legacy_type': field_type,
                'legacy_label': str(item.get('label') or key.replace('_', ' ').title()),
                'reason': 'type_conflict', 'suggested_field': conflict,
            },
        )
        created += int(was_created)
    return created


def snapshot_form_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Capture catalogue governance with a form contract at application creation."""
    snapshot = json.loads(json.dumps(schema or {}))
    fields = [item for item in (snapshot.get('fields') or []) if isinstance(item, dict)]
    ids = [item.get('data_field_id') for item in fields if item.get('data_field_id')]
    by_id = {str(item.pk): item for item in OriginationDataField.objects.filter(pk__in=ids)}
    by_key = {
        item.key: item
        for item in OriginationDataField.objects.filter(
            key__in=[str(field.get('key') or '') for field in fields],
        )
    }
    for item in fields:
        data_field = by_id.get(str(item.get('data_field_id') or '')) or by_key.get(
            str(item.get('key') or ''),
        )
        if not data_field or data_field.data_type != str(item.get('type') or 'text'):
            continue
        item.update({
            'data_field_id': str(data_field.pk),
            'canonical_key': data_field.key,
            'sensitivity': data_field.sensitivity,
            'masking_policy': data_field.masking_policy,
            'reporting_use': data_field.reporting_use,
            'export_allowed': data_field.export_allowed,
            'source_type': data_field.source_type,
        })
        if data_field.data_type == OriginationDataField.TYPE_CHOICE:
            item['canonical_choice_options'] = list(data_field.choice_options or [])
    snapshot['fields'] = fields
    snapshot['system_fields'] = [
        serialize_data_field(item)
        for item in OriginationDataField.objects.filter(
            active=True, source_type=OriginationDataField.SOURCE_SYSTEM,
        ).order_by('key')
    ]
    return snapshot


def unresolved_review_keys(product: OriginationProductDefinition) -> list[str]:
    return list(product.field_review_issues.filter(
        status=OriginationFieldReviewIssue.STATUS_OPEN,
    ).order_by('legacy_key').values_list('legacy_key', flat=True))


@transaction.atomic
def resolve_review_issue(
    *, issue: OriginationFieldReviewIssue, status: str,
    resolution_field: OriginationDataField | None, notes: str, actor,
) -> OriginationFieldReviewIssue:
    if not getattr(actor, 'is_superuser', False):
        raise OriginationFieldError('Only a Django Superuser may resolve legacy fields.')
    # resolution_field is nullable. Joining it into a FOR UPDATE query makes
    # PostgreSQL reject the lock as targeting the nullable side of an outer
    # join. Lock only the issue row and join the required product relation.
    issue = OriginationFieldReviewIssue.objects.select_for_update(
        of=('self',),
    ).select_related('product_definition').get(pk=issue.pk)
    if status not in {issue.STATUS_RESOLVED, issue.STATUS_ACCEPTED}:
        raise OriginationFieldError('Choose resolved or accepted as legacy.')
    if status == issue.STATUS_RESOLVED:
        if not resolution_field or resolution_field.data_type != issue.legacy_type:
            raise OriginationFieldError('Choose a canonical field with the same data type.')
        product = OriginationProductDefinition.objects.select_for_update().get(
            pk=issue.product_definition_id,
        )
        if product.lifecycle_status != product.STATUS_DRAFT:
            raise OriginationFieldError('Resolve this binding on an editable successor version.')
        schema = json.loads(json.dumps(product.form_schema or {}))
        target = next(
            (item for item in (schema.get('fields') or []) if item.get('key') == issue.legacy_key),
            None,
        )
        if not target:
            raise OriginationFieldError('The legacy field is no longer present in this schema.')
        if any(
            item.get('key') == resolution_field.key and item is not target
            for item in (schema.get('fields') or [])
        ):
            raise OriginationFieldError('That canonical field is already attached to the product.')
        presentation = dict(target)
        target.clear()
        target.update(_field_schema_item(resolution_field, presentation))
        schema['_revision'] = product_schema_revision(product) + 1
        product.form_schema = schema
        product.save(update_fields=['form_schema', 'updated_at'])
    elif not str(notes or '').strip():
        raise OriginationFieldError('Explain why this field remains legacy.')
    issue.status = status
    issue.resolution_field = resolution_field if status == issue.STATUS_RESOLVED else None
    issue.resolution_notes = str(notes or '').strip()
    issue.resolved_by = actor
    issue.resolved_at = timezone.now()
    issue.full_clean()
    issue.save(update_fields=[
        'status', 'resolution_field', 'resolution_notes', 'resolved_by',
        'resolved_at', 'updated_at',
    ])
    OriginationProductDefinitionEvent.objects.create(
        product_definition=issue.product_definition,
        action='legacy_field_resolved' if status == issue.STATUS_RESOLVED else 'legacy_field_accepted',
        actor=actor,
        metadata={
            'legacy_key': issue.legacy_key,
            'resolution_field_id': str(resolution_field.pk) if resolution_field else '',
        },
    )
    if resolution_field:
        OriginationDataFieldEvent.objects.create(
            data_field=resolution_field, action='legacy_bound', actor=actor,
            metadata={
                'product_definition_id': str(issue.product_definition_id),
                'legacy_key': issue.legacy_key,
            },
        )
    return issue


def _projection_kwargs(field_type: str, value: Any) -> dict[str, Any]:
    if field_type in {'text', 'textarea', 'phone', 'national_id', 'branch', 'county', 'sub_county'}:
        text = str(value)
        if len(text) > 500:
            raise OriginationFieldError('A reportable text value exceeds 500 characters.')
        return {'text_value': text}
    if field_type in {'number', 'money'}:
        try:
            return {'decimal_value': Decimal(str(value))}
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise OriginationFieldError('A reportable numeric value is invalid.') from exc
    if field_type == 'date':
        try:
            return {'date_value': date.fromisoformat(str(value))}
        except (TypeError, ValueError) as exc:
            raise OriginationFieldError('A reportable date value is invalid.') from exc
    if field_type == 'boolean':
        if not isinstance(value, bool):
            raise OriginationFieldError('A reportable yes/no value is invalid.')
        return {'boolean_value': value}
    if field_type == 'choice':
        return {'choice_code': str(value)[:120]}
    raise OriginationFieldError('This field type cannot be projected for reporting.')


def project_reporting_values(application: LoanOriginationApplication) -> int:
    """Idempotently rebuild the approved reporting projection from frozen values."""
    schema = application.schema_snapshot or {}
    field_specs = [
        item for item in [
            *((schema.get('fields') or [])), *((schema.get('system_fields') or [])),
        ] if isinstance(item, dict)
    ]
    context = {
        **application.form_payload,
        'reference_number': application.reference_number,
        'branch_code': application.branch,
        'loan_officer_name': application.officer.get_full_name() or application.officer.get_username(),
        'application_date': timezone.localdate(application.created_at).isoformat(),
    }
    ids = [item.get('data_field_id') or item.get('id') for item in field_specs]
    catalogue = {
        str(item.pk): item for item in OriginationDataField.objects.filter(pk__in=ids)
    }
    rows = []
    seen = set()
    for spec in field_specs:
        data_field = catalogue.get(str(spec.get('data_field_id') or spec.get('id') or ''))
        if not data_field or data_field.pk in seen:
            continue
        seen.add(data_field.pk)
        if (
            data_field.reporting_use == OriginationDataField.REPORT_UNAVAILABLE
            or data_field.sensitivity == OriginationDataField.SENSITIVITY_RESTRICTED
            or str(spec.get('sensitivity') or data_field.sensitivity)
            == OriginationDataField.SENSITIVITY_RESTRICTED
            or str(spec.get('reporting_use') or data_field.reporting_use)
            == OriginationDataField.REPORT_UNAVAILABLE
        ):
            continue
        value = context.get(data_field.key)
        if value in (None, ''):
            continue
        rows.append(OriginationReportingValue(
            application=application, data_field=data_field,
            field_key=data_field.key, value_type=data_field.data_type,
            sensitivity=str(spec.get('sensitivity') or data_field.sensitivity),
            masking_policy=str(spec.get('masking_policy') or data_field.masking_policy),
            reporting_use=str(spec.get('reporting_use') or data_field.reporting_use),
            export_allowed=bool(spec.get('export_allowed', data_field.export_allowed)),
            **_projection_kwargs(data_field.data_type, value),
        ))
    application.reporting_values.all().delete()
    OriginationReportingValue.objects.bulk_create(rows)
    return len(rows)


def masked_reporting_value(
    row: OriginationReportingValue, *, allow_sensitive_export: bool = False,
) -> Any:
    raw = (
        row.text_value if row.text_value is not None else
        row.decimal_value if row.decimal_value is not None else
        row.date_value if row.date_value is not None else
        row.boolean_value if row.boolean_value is not None else row.choice_code
    )
    if allow_sensitive_export and row.export_allowed:
        return raw
    if row.masking_policy == OriginationDataField.MASK_NONE:
        return raw
    if row.masking_policy == OriginationDataField.MASK_FULL:
        return '***'
    text = str(raw or '')
    if len(text) <= 4:
        return '*' * len(text)
    return f'{text[:2]}{"*" * (len(text) - 4)}{text[-2:]}'
