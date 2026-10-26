"""Catalogue-only document resolution for new Loan Origination applications."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Iterable

from django.db.models import Prefetch

from origination.models import (
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
    *, require_active: bool = True, require_complete: bool = True,
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

    from origination.services.origination_fields import template_form_contract
    document_schema, document_signers = template_form_contract(template)
    schema = deepcopy(document_schema)
    schema.pop('required_signer_roles', None)

    # The chosen Main LAF owns its signer contract. Product-level mirrors must
    # not reintroduce retired roles; the independently governed approval policy
    # is validated below and application snapshots remain unchanged.
    if schema is not None and require_complete:
        from origination.services.loan_origination import OriginationError, validate_product_form_contract
        try:
            validate_product_form_contract(schema, document_signers, require_signers=False,
                require_fields=False, allow_shared_identity=True)
            from origination.services.origination_approval import validate_approval_roles
            if document_signers:
                validate_approval_roles(definition.approval_roles, document_signers)
        except OriginationError as exc:
            reasons.append(str(exc))
    return (schema if not reasons else None), reasons


def validate_catalogue_publication(template: OriginationDocumentTemplate, *, require_complete: bool = True) -> None:
    """Fail publication when an allowlisted product would receive an invalid document."""
    from origination.services.loan_origination import OriginationError, validate_product_form_contract
    from origination.services.origination_value_contracts import enabled
    from origination.services.origination_value_contracts import build_packet_contract, schema_with_mapped_values, ValueContractError

    if require_complete and enabled(template.form_schema):
        configuration = (template.published_configuration_revision.configuration if template.published_configuration_revision_id
                         else template.placement_config or {})
        try:
            reviewed_schema = schema_with_mapped_values(template.form_schema, configuration)
            build_packet_contract(reviewed_schema, []) if template.document_role == 'primary' else build_packet_contract(
                {'value_contract_version': 2, 'fields': []}, [{'key':template.document_key, 'schema':reviewed_schema}])
        except ValueContractError as exc:
            raise OriginationError(str(exc), errors=exc.errors) from exc
        if any(field.get('required') and (field.get('value_contract') or {}).get('source') == 'workflow'
               for field in reviewed_schema.get('fields', [])):
            raise OriginationError('A required field cannot depend on a later workflow event.')

    product_ids = list(template.product_eligibilities.values_list('product_id', flat=True))
    if template.document_role == template.ROLE_SUPPORTING:
        if require_complete:
            try:
                validate_product_form_contract(
                    template.form_schema or {'fields': []}, template.signer_rules or [],
                    require_signers=False, require_fields=False, allow_shared_identity=True,
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
        return
    definitions = OriginationProductDefinition.objects.filter(
        is_active=True, product_version__product_id__in=product_ids,
    ).select_related('product_version__product')
    failures = []
    for definition in definitions:
        _schema, reasons = main_laf_contract(definition, template, require_active=False, require_complete=require_complete)
        if reasons:
            failures.append(f'{definition.name}: {" ".join(reasons)}')
    if failures:
        raise OriginationError(' '.join(failures))


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
    ).select_related('published_configuration_revision', 'product_definition').prefetch_related(
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
    by_id = {str(template.pk): template for template in templates}
    for item in supporting:
        item['compatible_main_ids'] = []
        for main in mains:
            try:
                validate_document_combination(by_id[main['id']], [by_id[item['id']]])
            except ValueError:
                continue
            item['compatible_main_ids'].append(main['id'])
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
    from origination.services.loan_origination import OriginationConflict, OriginationError

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


def _reviewed_compatibility_schema(schema: dict) -> dict:
    """Compare known meanings while unfinished authoring remains advisory."""
    from origination.services.origination_value_contracts import enabled, field_contract, ValueContractError
    if not enabled(schema):
        return schema
    fields = []
    for field in _fields(schema):
        try:
            if field_contract(field):
                fields.append(field)
        except ValueContractError:
            continue
    return {**schema, 'fields': fields}


def validate_document_combination(
    primary: OriginationDocumentTemplate,
    supporting: Iterable[OriginationDocumentTemplate], *, require_complete: bool = True,
) -> None:
    """Reject canonical keys whose types disagree in the selected packet."""
    from origination.services.loan_origination import OriginationError

    from origination.services.origination_fields import template_form_contract
    supporting = list(supporting)
    primary_schema, _signers = template_form_contract(primary)
    from origination.services.origination_value_contracts import build_packet_contract, enabled, schema_with_mapped_values, ValueContractError
    try:
        def mapped_schema(template, raw_schema):
            if not require_complete or not enabled(raw_schema):
                return raw_schema
            configuration = (template.published_configuration_revision.configuration if template.published_configuration_revision_id
                             else template.placement_config or {})
            return schema_with_mapped_values(raw_schema, configuration,
                captured_system=primary_schema.get('system_fields', []))

        primary_schema = mapped_schema(primary, primary_schema)
        supporting_schemas = [mapped_schema(template, template_form_contract(template)[0]) for template in supporting]
        compatible = (lambda schema: schema) if require_complete else _reviewed_compatibility_schema
        build_packet_contract(compatible(primary_schema), [
            {'key': str(template.pk), 'schema': compatible(schema)}
            for template, schema in zip(supporting, supporting_schemas)
        ])
    except ValueContractError as exc:
        raise OriginationError(str(exc), errors=exc.errors) from exc
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


def validate_snapshot_combination(primary_schema: Any, supporting_schemas: Iterable[Any], *, require_complete: bool = True) -> None:
    """Apply the same type-safety rule to an application's frozen candidates."""
    from origination.services.loan_origination import OriginationError
    supporting_schemas = list(supporting_schemas)
    from origination.services.origination_value_contracts import build_packet_contract, ValueContractError
    try:
        compatible = (lambda schema: schema) if require_complete else _reviewed_compatibility_schema
        build_packet_contract(compatible(primary_schema), [
            {'key': str(index), 'schema': compatible(schema)} for index, schema in enumerate(supporting_schemas)
        ])
    except ValueContractError as exc:
        raise OriginationError(str(exc), errors=exc.errors) from exc

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
