"""Catalogue-only document resolution for new Loan Origination applications."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Iterable

from django.db.models import Prefetch

from core.models import (
    OriginationDocumentProductEligibility,
    OriginationDocumentTemplate,
    OriginationProductDefinition,
)


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str,
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def catalogue_revision() -> str:
    """Return a stable revision for the currently published catalogue."""
    rows = OriginationDocumentProductEligibility.objects.filter(
        template__status=OriginationDocumentTemplate.STATUS_ACTIVE,
    ).values_list(
        'template_id', 'template__document_type', 'template__version',
        'template__source_sha256', 'product_id',
    ).order_by('template__document_type', 'template__version', 'product_id')
    return _stable_hash(list(rows))


def _fields(schema: Any) -> list[dict[str, Any]]:
    if not isinstance(schema, dict) or not isinstance(schema.get('fields'), list):
        return []
    return [item for item in schema['fields'] if isinstance(item, dict)]


def _field_types(schema: Any) -> dict[str, str]:
    return {
        str(item.get('key') or '').strip(): str(item.get('type') or 'text').strip()
        for item in _fields(schema) if str(item.get('key') or '').strip()
    }


def _signer_roles(rules: Any) -> set[str]:
    return {
        str(item.get('role') or '').strip()
        for item in (rules or []) if isinstance(item, dict) and str(item.get('role') or '').strip()
    }


def main_laf_contract(
    definition: OriginationProductDefinition,
    template: OriginationDocumentTemplate,
    *, require_active: bool = True,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Build the immutable application schema and name incompatibility reasons."""
    reasons: list[str] = []
    if require_active and template.status != template.STATUS_ACTIVE:
        reasons.append('The document version is not published.')
    if not template.published_configuration_revision_id:
        reasons.append('The document alignment is not published.')
    if template.document_role != template.ROLE_PRIMARY:
        reasons.append('The document is not configured as a Main LAF.')
    if not definition.product_version_id:
        reasons.append('The Origination product is not linked to a governed global product version.')
        return None, reasons
    if not template.product_eligibilities.filter(
        product_id=definition.product_version.product_id,
    ).exists():
        reasons.append('The document does not allow this product.')

    from core.services.origination_commercial_terms import (
        COMMERCIAL_INPUT_KEYS,
        commercial_contract_enabled,
        merge_commercial_contract,
    )
    template_types = _field_types(template.form_schema)
    if commercial_contract_enabled(definition.form_schema):
        definition_types = _field_types(definition.form_schema)
        for key in COMMERCIAL_INPUT_KEYS:
            if key not in template_types:
                reasons.append(f'The Main LAF is missing the canonical commercial field {key}.')
            elif template_types[key] != definition_types.get(key):
                reasons.append(f'The Main LAF uses an incompatible type for {key}.')
        try:
            schema = merge_commercial_contract(deepcopy(template.form_schema or {}))
        except (TypeError, ValueError) as exc:
            reasons.append(str(exc))
            schema = None
    else:
        schema = deepcopy(template.form_schema or {})

    required_roles = _signer_roles(definition.signer_rules)
    missing_roles = sorted(required_roles - _signer_roles(template.signer_rules))
    if missing_roles:
        reasons.append('The Main LAF is missing required signer roles: ' + ', '.join(missing_roles) + '.')
    if schema is not None:
        from core.services.loan_origination import OriginationError, validate_product_form_contract
        try:
            validate_product_form_contract(schema, template.signer_rules)
        except OriginationError as exc:
            reasons.append(str(exc))
    return (schema if not reasons else None), reasons


def validate_catalogue_publication(template: OriginationDocumentTemplate) -> None:
    """Fail publication when an allowlisted product would receive an invalid document."""
    from core.services.loan_origination import OriginationError, validate_product_form_contract

    product_ids = list(template.product_eligibilities.values_list('product_id', flat=True))
    other_templates = OriginationDocumentTemplate.objects.filter(
        status=OriginationDocumentTemplate.STATUS_ACTIVE,
        product_eligibilities__product_id__in=product_ids,
    ).exclude(document_type=template.document_type).distinct()
    if template.document_role == template.ROLE_SUPPORTING:
        try:
            validate_product_form_contract(
                template.form_schema or {'fields': []}, template.signer_rules or [],
                require_signers=False,
            )
        except OriginationError as exc:
            raise OriginationError(f'The supporting document contract is invalid: {exc}') from exc
        collision = OriginationDocumentTemplate.objects.filter(
            status=OriginationDocumentTemplate.STATUS_ACTIVE,
            document_role=template.ROLE_SUPPORTING,
            document_key=template.document_key,
            product_eligibilities__product_id__in=product_ids,
        ).exclude(document_type=template.document_type).exists()
        if collision:
            raise OriginationError(
                'Another published supporting document uses this key for an allowed product.',
            )
        for primary in other_templates.filter(document_role=template.ROLE_PRIMARY):
            validate_document_combination(primary, [template])
        for supporting in other_templates.filter(document_role=template.ROLE_SUPPORTING):
            # Either supporting template may be selected alongside the other.
            validate_snapshot_combination({}, [supporting.form_schema, template.form_schema])
        return
    definitions = OriginationProductDefinition.objects.filter(
        is_active=True, product_version__product_id__in=product_ids,
    ).select_related('product_version__product')
    failures = []
    for definition in definitions:
        _schema, reasons = main_laf_contract(definition, template, require_active=False)
        if reasons:
            failures.append(f'{definition.name}: {" ".join(reasons)}')
    if failures:
        raise OriginationError(' '.join(failures))
    for supporting in other_templates.filter(document_role=template.ROLE_SUPPORTING):
        validate_document_combination(template, [supporting])


def catalogue_for_product(
    definition: OriginationProductDefinition, *, revision: str | None = None,
) -> dict[str, Any]:
    """Return compatible selections and explicit readiness for one product."""
    revision = revision or catalogue_revision()
    if not definition.product_version_id:
        return {
            'catalogue_revision': revision, 'ready': False,
            'reasons': ['The product is not linked to a governed global product version.'],
            'main_lafs': [], 'supporting_documents': [],
        }
    templates = list(OriginationDocumentTemplate.objects.filter(
        status=OriginationDocumentTemplate.STATUS_ACTIVE,
        published_configuration_revision__isnull=False,
        product_eligibilities__product_id=definition.product_version.product_id,
    ).select_related('published_configuration_revision').prefetch_related(
        Prefetch('product_eligibilities', queryset=OriginationDocumentProductEligibility.objects.all()),
    ).distinct().order_by('display_order', 'name', '-version'))
    mains = []
    supporting = []
    rejected = []
    for template in templates:
        item = {
            'id': str(template.pk), 'family': template.document_type,
            'key': template.document_key, 'name': template.name,
            'version': template.version, 'role': template.document_role,
            'order': template.display_order,
        }
        if template.document_role == template.ROLE_PRIMARY:
            _schema, reasons = main_laf_contract(definition, template)
            if reasons:
                rejected.append({**item, 'reasons': reasons})
            else:
                mains.append(item)
        else:
            supporting.append(item)
    reasons = []
    if not mains:
        reasons.append('No published compatible Main LAF is available for this product.')
    duplicate_keys = sorted({
        item['key'] for item in supporting
        if sum(candidate['key'] == item['key'] for candidate in supporting) > 1
    })
    if duplicate_keys:
        reasons.append('Supporting document keys collide: ' + ', '.join(duplicate_keys) + '.')
        supporting = []
    return {
        'catalogue_revision': revision, 'ready': bool(mains) and not reasons,
        'reasons': reasons, 'main_lafs': mains,
        'supporting_documents': supporting, 'rejected_main_lafs': rejected,
    }


def resolve_catalogue_selection(
    definition: OriginationProductDefinition, *, primary_template_id: Any,
    supporting_template_ids: Iterable[Any], expected_catalogue_revision: str = '',
):
    """Resolve one exact catalogue selection or fail closed."""
    from core.services.loan_origination import OriginationConflict, OriginationError

    catalogue = catalogue_for_product(definition)
    if expected_catalogue_revision and expected_catalogue_revision != catalogue['catalogue_revision']:
        raise OriginationConflict('The document catalogue changed. Refresh your choices before starting.')
    if not catalogue['ready']:
        raise OriginationError(' '.join(catalogue['reasons']))
    primary_id = str(primary_template_id or '').strip()
    primary = next((item for item in catalogue['main_lafs'] if item['id'] == primary_id), None)
    if not primary:
        raise OriginationError('Choose a published Main LAF that is compatible with this product.')
    requested = [str(item).strip() for item in (supporting_template_ids or []) if str(item).strip()]
    if len(requested) != len(set(requested)):
        raise OriginationError('Supporting documents cannot be selected more than once.')
    supporting_by_id = {item['id']: item for item in catalogue['supporting_documents']}
    unknown = sorted(set(requested) - set(supporting_by_id))
    if unknown:
        raise OriginationError('One or more supporting documents are unavailable for this product.')
    templates = {
        str(item.pk): item for item in OriginationDocumentTemplate.objects.filter(
            pk__in=[primary_id, *requested], status=OriginationDocumentTemplate.STATUS_ACTIVE,
        ).select_related('published_configuration_revision')
    }
    primary_template = templates.get(primary_id)
    if not primary_template or any(item not in templates for item in requested):
        raise OriginationConflict('The document catalogue changed. Refresh your choices before starting.')
    supporting_templates = [templates[item] for item in requested]
    schema, reasons = main_laf_contract(definition, primary_template)
    if reasons:
        raise OriginationError(' '.join(reasons))
    validate_document_combination(primary_template, supporting_templates)
    return primary_template, supporting_templates, schema, catalogue


def validate_document_combination(
    primary: OriginationDocumentTemplate,
    supporting: Iterable[OriginationDocumentTemplate],
) -> None:
    """Reject canonical keys whose types disagree in the selected packet."""
    from core.services.loan_origination import OriginationError

    known = _field_types(primary.form_schema)
    conflicts = []
    for template in supporting:
        for key, data_type in _field_types(template.form_schema).items():
            if key in known and known[key] != data_type:
                conflicts.append(f'{key} ({known[key]} vs {data_type})')
            known.setdefault(key, data_type)
    if conflicts:
        raise OriginationError(
            'The selected documents use conflicting canonical field types: '
            + ', '.join(sorted(set(conflicts))) + '.',
        )


def validate_snapshot_combination(primary_schema: Any, supporting_schemas: Iterable[Any]) -> None:
    """Apply the same type-safety rule to an application's frozen candidates."""
    from core.services.loan_origination import OriginationError

    known = _field_types(primary_schema)
    conflicts = []
    for schema in supporting_schemas:
        for key, data_type in _field_types(schema).items():
            if key in known and known[key] != data_type:
                conflicts.append(f'{key} ({known[key]} vs {data_type})')
            known.setdefault(key, data_type)
    if conflicts:
        raise OriginationError(
            'The selected documents use conflicting canonical field types: '
            + ', '.join(sorted(set(conflicts))) + '.',
        )


def selection_digest(*, branch: str, product_version_id: Any, catalogue_revision_value: str,
                     primary_template_id: Any, supporting_template_ids: Iterable[Any],
                     supersedes_application_id: Any = '') -> str:
    return _stable_hash({
        'branch': str(branch or '').strip().casefold(),
        'product_version_id': str(product_version_id or ''),
        'catalogue_revision': str(catalogue_revision_value or ''),
        'primary_template_id': str(primary_template_id or ''),
        'supporting_template_ids': sorted(str(item) for item in (supporting_template_ids or [])),
        'supersedes_application_id': str(supersedes_application_id or ''),
    })
