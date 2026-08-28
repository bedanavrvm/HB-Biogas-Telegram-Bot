"""Derived progress, concurrency, and audit contracts for Origination setup."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError
from django.core import signing

from core.models import (
    OriginationDocumentTemplate,
    OriginationProductDefinition,
    OriginationProductDefinitionEvent,
    ProductVersion,
    ProductVersionEvent,
)


SETUP_STEPS = (
    ('identity', 'Product and availability'),
    ('terms', 'Commercial terms'),
    ('terms_publish', 'Publish terms'),
    ('form', 'Form and signers'),
    ('documents', 'Document packet'),
    ('calibration', 'PDF alignment'),
    ('publish', 'Review and publish'),
)
RETURN_TOKEN_SALT = 'core.origination.setup.return.v1'
RETURN_TOKEN_MAX_AGE_SECONDS = 24 * 60 * 60


class OriginationSetupConflict(ValueError):
    def __init__(self, changed_steps: list[str]):
        self.changed_steps = changed_steps
        super().__init__('This setup changed after you opened it.')


def make_return_token(*, definition_id, step_key: str = 'calibration') -> str:
    if step_key not in {key for key, _label in SETUP_STEPS}:
        raise ValueError('Unknown Origination setup step.')
    return signing.dumps(
        {'definition_id': str(definition_id), 'step_key': step_key},
        salt=RETURN_TOKEN_SALT,
        compress=True,
    )


def resolve_return_token(token: str) -> dict[str, str]:
    payload = signing.loads(
        token, salt=RETURN_TOKEN_SALT, max_age=RETURN_TOKEN_MAX_AGE_SECONDS,
    )
    if not isinstance(payload, dict):
        raise signing.BadSignature('Invalid Origination setup return token.')
    definition_id = str(payload.get('definition_id') or '')
    step_key = str(payload.get('step_key') or '')
    if not definition_id or step_key not in {key for key, _label in SETUP_STEPS}:
        raise signing.BadSignature('Invalid Origination setup return target.')
    return {'definition_id': definition_id, 'step_key': step_key}


def resume_step(definition: OriginationProductDefinition) -> str:
    rows = setup_readiness(definition)
    for wanted in ('stale', 'in_progress'):
        row = next((item for item in rows if item['status'] == wanted), None)
        if row:
            return row['key']
    row = next((item for item in rows if item['status'] == 'blocked'), None)
    return row['key'] if row else 'publish'


def _json_value(value: Any) -> Any:
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value)


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(',', ':'), default=_json_value,
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _model_values(instance, excluded: set[str] | None = None) -> dict[str, Any]:
    excluded = excluded or set()
    return {
        field.attname: getattr(instance, field.attname)
        for field in instance._meta.concrete_fields
        if field.name not in excluded and field.attname not in excluded
    }


def workspace_snapshot(definition: OriginationProductDefinition) -> dict[str, Any]:
    definition = OriginationProductDefinition.objects.select_related(
        'product_version__product',
    ).get(pk=definition.pk)
    version = definition.product_version
    product = version.product if version else None
    availability = []
    if product:
        availability = [
            _model_values(item, {'id', 'created_at'})
            for item in product.availability_assignments.filter(
                workflow='loan_origination', active=True,
            ).order_by('scope_signature', 'pk')
        ]
    terms = _model_values(version, {'updated_at'}) if version else {}
    if version:
        terms.update({
            'fees': [_model_values(item, {'id'}) for item in version.fees.order_by('position', 'pk')],
            'requirements': [
                _model_values(item, {'id'})
                for item in version.requirements.order_by('position', 'pk')
            ],
            'attributes': [
                _model_values(item, {'id'})
                for item in version.custom_attributes.order_by('position', 'pk')
            ],
        })
    owned_documents = [
        {
            **_model_values(item, {'updated_at', 'drive_url', 'upload_error'}),
            'latest_revision': (
                item.configuration_revisions.order_by('-revision')
                .values_list('revision', flat=True).first() or 0
            ),
        }
        for item in definition.document_templates.order_by('display_order', 'document_key', 'pk')
    ]
    assignments = [
        _model_values(item, {'id', 'created_at'})
        for item in definition.document_assignments.order_by('display_order', 'document_key', 'pk')
    ]
    return {
        'identity': {
            'product': _model_values(product, {'updated_at', 'active'}) if product else {},
            'availability': availability,
        },
        'terms': terms,
        'form': {
            'definition': _model_values(definition, {
                'updated_at', 'published_at', 'published_by_id', 'is_active',
                'document_template_name', 'document_template_version',
                'document_template_sha256',
            }),
            'schema': definition.form_schema,
            'signers': definition.signer_rules,
        },
        'documents': {'owned': owned_documents, 'assignments': assignments},
        'calibration': {
            'owned': [
                {
                    'id': item['id'], 'source_sha256': item['source_sha256'],
                    'status': item['status'], 'latest_revision': item['latest_revision'],
                    'published_revision_id': item['published_configuration_revision_id'],
                }
                for item in owned_documents
            ],
            'assigned': [
                {'template_id': item['template_id'], 'version_policy': item['version_policy']}
                for item in assignments
            ],
        },
        'publication': {
            'terms_status': version.status if version else '',
            'definition_status': definition.lifecycle_status,
            'definition_active': definition.is_active,
        },
    }


def step_tokens(definition: OriginationProductDefinition) -> dict[str, str]:
    snapshot = workspace_snapshot(definition)
    return {
        'identity': _digest(snapshot['identity']),
        'terms': _digest(snapshot['terms']),
        'terms_publish': _digest({
            'terms': snapshot['terms'],
            'status': snapshot['publication']['terms_status'],
        }),
        'form': _digest({
            'terms': snapshot['terms'], 'form': snapshot['form'],
        }),
        'documents': _digest({
            'form': snapshot['form'], 'documents': snapshot['documents'],
        }),
        'calibration': _digest({
            'form': snapshot['form'], 'documents': snapshot['documents'],
            'calibration': snapshot['calibration'],
        }),
        'publish': _digest(snapshot),
    }


def state_token(definition: OriginationProductDefinition) -> str:
    return _digest(step_tokens(definition))


def _event_owner(definition, step_key):
    if step_key in {'identity', 'terms', 'terms_publish'} and definition.product_version_id:
        return ProductVersionEvent, {'product_version': definition.product_version}
    return OriginationProductDefinitionEvent, {'product_definition': definition}


def record_step_completion(
    *, definition: OriginationProductDefinition, step_key: str, actor,
    request_id: str,
) -> None:
    tokens = step_tokens(definition)
    model, relation = _event_owner(definition, step_key)
    existing = model.objects.filter(
        **relation, action='setup_step_completed',
        metadata__request_id=request_id,
    ).first()
    if existing:
        return
    model.objects.create(
        **relation, action='setup_step_completed', actor=actor,
        metadata={
            'step_key': step_key, 'request_id': request_id,
            'state_sha256': tokens[step_key],
            'workspace_sha256': _digest(tokens),
        },
    )


def completed_request(
    *, definition: OriginationProductDefinition, step_key: str, request_id: str,
) -> bool:
    if not request_id:
        return False
    model, relation = _event_owner(definition, step_key)
    return model.objects.filter(
        **relation, action='setup_step_completed',
        metadata__step_key=step_key, metadata__request_id=request_id,
    ).exists()


def assert_expected_state(
    *, definition: OriginationProductDefinition, expected_tokens: dict[str, str],
) -> None:
    current = step_tokens(definition)
    changed = [
        key for key, _label in SETUP_STEPS
        if expected_tokens.get(key) and expected_tokens.get(key) != current.get(key)
    ]
    if changed:
        raise OriginationSetupConflict(changed)


def _valid_terms(version: ProductVersion | None) -> tuple[bool, str]:
    if not version:
        return False, 'Choose or create a governed commercial-terms version.'
    try:
        version.full_clean()
        for collection in (version.fees.all(), version.requirements.all(), version.custom_attributes.all()):
            for item in collection:
                item.full_clean()
    except ValidationError as exc:
        return False, '; '.join(exc.messages)
    return True, 'Commercial terms and their Origination configuration are valid.'


def _valid_form(definition) -> tuple[bool, str]:
    from core.services.loan_origination import OriginationError, validate_product_form_contract
    try:
        validate_product_form_contract(definition.form_schema, definition.signer_rules)
    except OriginationError as exc:
        return False, str(exc)
    return True, 'Form fields and signer roles are valid.'


def _packet(definition):
    from core.services.origination_templates import resolve_assignment_template
    owned = list(definition.document_templates.exclude(
        status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED,
    ))
    assigned = [
        (item, resolve_assignment_template(item))
        for item in definition.document_assignments.select_related('template')
    ]
    primaries = [item for item in owned if item.document_role == item.ROLE_PRIMARY]
    primaries += [
        resolved for _item, resolved in assigned
        if resolved and resolved.document_role == resolved.ROLE_PRIMARY
    ]
    unresolved = [item for item, resolved in assigned if not resolved]
    valid = len(primaries) == 1 and not unresolved
    detail = (
        'Exactly one main LAF and every reusable document resolve successfully.'
        if valid else
        'Attach exactly one main LAF and resolve every reusable document.'
    )
    return valid, detail, owned, assigned


def _valid_calibration(definition) -> tuple[bool, str]:
    from core.services.origination_templates import _expected_signature_slots
    valid_packet, detail, owned, assigned = _packet(definition)
    if not valid_packet:
        return False, detail
    for template in owned:
        revision = template.configuration_revisions.order_by('-revision').first()
        if not revision:
            return False, f'{template.name} has no saved alignment.'
        config = revision.configuration if isinstance(revision.configuration, dict) else {}
        fields = (config.get('field_overlay_manifest') or {}).get('fields')
        slots = (config.get('signature_overlay_manifest') or {}).get('slots')
        if not isinstance(fields, dict) or not fields:
            return False, f'{template.name} requires at least one aligned PDF field.'
        schema = (
            template.form_schema
            if template.document_role == template.ROLE_SUPPORTING and template.form_schema
            else definition.form_schema
        )
        required_fields = {
            str(item.get('key')) for item in (schema or {}).get('fields', [])
            if isinstance(item, dict) and item.get('required') and item.get('key')
        }
        mapped = {
            str(item.get('context_key') or '') for item in fields.values()
            if isinstance(item, dict)
        }
        missing_fields = sorted(required_fields - mapped)
        if missing_fields:
            return False, f'{template.name} is missing required fields: {", ".join(missing_fields)}.'
        if not isinstance(slots, dict):
            return False, f'{template.name} has an invalid signer-slot alignment.'
        expected_slots = _expected_signature_slots(definition, template)
        missing_slots = sorted(
            key for key, spec in expected_slots.items()
            if spec.get('required') and key not in slots
        )
        if missing_slots:
            return False, f'{template.name} is missing required signer slots: {", ".join(missing_slots)}.'
        for label, collection in (('field', fields), ('signer slot', slots)):
            for key, spec in collection.items():
                if not isinstance(spec, dict):
                    return False, f'{template.name} {label} {key} is invalid.'
                box = spec.get('allowed_area') or spec.get('box')
                try:
                    page = int(spec.get('page_number') or 0)
                    width = float(box['width'])
                    height = float(box['height'])
                except (KeyError, TypeError, ValueError):
                    return False, f'{template.name} {label} {key} has incomplete placement.'
                if page < 1 or page > template.page_count or width <= 0 or height <= 0:
                    return False, f'{template.name} {label} {key} has invalid placement.'
    for assignment, resolved in assigned:
        if not resolved or not resolved.published_configuration_revision_id:
            return False, f'{assignment.name} is not calibrated and published.'
    return True, 'Every selected document has a complete alignment.'


def _last_completion(definition, step_key):
    model, relation = _event_owner(definition, step_key)
    return model.objects.filter(
        **relation, action='setup_step_completed', metadata__step_key=step_key,
    ).order_by('-occurred_at', '-pk').first()


def setup_readiness(definition: OriginationProductDefinition) -> list[dict[str, Any]]:
    definition = OriginationProductDefinition.objects.select_related(
        'product_version__product',
    ).get(pk=definition.pk)
    tokens = step_tokens(definition)
    product = definition.product_version.product if definition.product_version_id else None
    identity_valid = bool(
        product and product.name and product.code
        and product.availability_assignments.filter(
            workflow='loan_origination', active=True,
        ).exists()
    )
    terms_valid, terms_detail = _valid_terms(definition.product_version)
    form_valid, form_detail = _valid_form(definition)
    packet_valid, packet_detail, _owned, _assigned = _packet(definition)
    calibration_valid, calibration_detail = _valid_calibration(definition)
    candidates = {
        'identity': (identity_valid, 'Product identity and Origination availability are saved.'),
        'terms': (terms_valid, terms_detail),
        'terms_publish': (
            bool(definition.product_version_id and definition.product_version.status in {
                ProductVersion.STATUS_PUBLISHED, ProductVersion.STATUS_SCHEDULED,
            }),
            'Publish the governed commercial terms before continuing.'
        ),
        'form': (form_valid, form_detail),
        'documents': (packet_valid, packet_detail),
        'calibration': (calibration_valid, calibration_detail),
        'publish': (
            definition.lifecycle_status == definition.STATUS_PUBLISHED and definition.is_active,
            'The exact Origination product and resolved packet are published.'
        ),
    }
    guided_workspace = bool(
        definition.events.filter(action='setup_started').exists()
        or (
            definition.product_version_id
            and definition.product_version.events.filter(action='setup_started').exists()
        )
    )
    rows = []
    for index, (key, label) in enumerate(SETUP_STEPS):
        valid, detail = candidates[key]
        event = _last_completion(definition, key)
        previous_required = all(candidates[item_key][0] for item_key, _ in SETUP_STEPS[:index])
        if key == 'publish' and valid:
            status = 'published'
        elif event and event.metadata.get('state_sha256') != tokens[key]:
            status = 'stale'
            detail = 'An upstream or Advanced setting changed. Reopen and confirm this step.'
        elif not previous_required:
            status = 'blocked'
            detail = 'Complete the preceding required step first.'
        elif valid and (event or not guided_workspace):
            status = 'complete'
        elif event:
            status = 'stale'
        else:
            status = 'in_progress'
        rows.append({'key': key, 'label': label, 'status': status, 'detail': detail})
    return rows
