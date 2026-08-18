"""Versioned generated-document packets for Loan Origination."""

from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Any

from django.db import transaction
from pypdf import PdfReader, PdfWriter

from core.models import (
    LoanOriginationApplication,
    OriginationApplicationDocument,
    OriginationDocumentTemplate,
)


def _condition_matches(condition: dict[str, Any], values: dict[str, Any]) -> bool:
    key = str(condition.get('field') or '').strip()
    operator = str(condition.get('operator') or 'equals').strip()
    actual = values.get(key)
    expected = condition.get('value')
    if operator == 'equals':
        return actual == expected
    if operator == 'not_equals':
        return actual != expected
    if operator == 'in':
        return actual in (expected if isinstance(expected, list) else [])
    if operator == 'not_in':
        return actual not in (expected if isinstance(expected, list) else [])
    if operator == 'truthy':
        return bool(actual)
    if operator == 'falsy':
        return not bool(actual)
    raise ValueError(f'Unsupported document applicability operator: {operator}.')


def rule_matches(rule: Any, values: dict[str, Any]) -> bool:
    """Evaluate the deliberately small, non-executable applicability DSL."""
    if not rule:
        return True
    if not isinstance(rule, dict):
        raise ValueError('Document applicability rules must be objects.')
    if 'all' in rule:
        items = rule['all']
        if not isinstance(items, list):
            raise ValueError('The document rule "all" value must be a list.')
        return all(rule_matches(item, values) for item in items)
    if 'any' in rule:
        items = rule['any']
        if not isinstance(items, list):
            raise ValueError('The document rule "any" value must be a list.')
        return any(rule_matches(item, values) for item in items)
    return _condition_matches(rule, values)


def validate_applicability_rule(rule: Any, *, allowed_fields: set[str]) -> None:
    if not rule:
        return
    if not isinstance(rule, dict):
        raise ValueError('Document applicability rules must be objects.')
    group_keys = [key for key in ('all', 'any') if key in rule]
    if group_keys:
        if len(group_keys) != 1 or len(rule) != 1 or not isinstance(rule[group_keys[0]], list):
            raise ValueError('Use exactly one "all" or "any" list in each rule group.')
        if not rule[group_keys[0]]:
            raise ValueError('Document rule groups cannot be empty.')
        for item in rule[group_keys[0]]:
            validate_applicability_rule(item, allowed_fields=allowed_fields)
        return
    field = str(rule.get('field') or '').strip()
    operator = str(rule.get('operator') or 'equals').strip()
    if field not in allowed_fields:
        raise ValueError(f'Document rule references unknown field: {field}.')
    if operator not in {'equals', 'not_equals', 'in', 'not_in', 'truthy', 'falsy'}:
        raise ValueError(f'Unsupported document applicability operator: {operator}.')
    if operator in {'in', 'not_in'} and not isinstance(rule.get('value'), list):
        raise ValueError(f'The {operator} operator requires a list value.')


def _template_snapshot(template: OriginationDocumentTemplate) -> dict[str, Any]:
    revision = template.published_configuration_revision
    return {
        'template_id': str(template.pk),
        'document_type': template.document_type,
        'version': template.version,
        'sha256': template.source_sha256,
        'configuration': (revision.configuration if revision else template.placement_config) or {},
        'applicability_rule': template.applicability_rule or {},
    }


def initialize_document_packet(application: LoanOriginationApplication) -> None:
    templates = list(application.product_definition.document_templates.filter(
        status=OriginationDocumentTemplate.STATUS_ACTIVE,
    ).order_by('display_order', 'document_key'))
    if not templates:
        return
    for template in templates:
        applicable = rule_matches(template.applicability_rule, application.form_payload)
        if template.document_role == template.ROLE_PRIMARY:
            selected, source = True, OriginationApplicationDocument.SOURCE_REQUIRED
        elif template.inclusion_mode == template.INCLUDE_REQUIRED:
            selected, source = True, OriginationApplicationDocument.SOURCE_REQUIRED
        elif template.inclusion_mode == template.INCLUDE_CONDITIONAL:
            selected, source = applicable, OriginationApplicationDocument.SOURCE_RULE
        else:
            selected = applicable and template.default_selected
            source = OriginationApplicationDocument.SOURCE_DEFAULT
        OriginationApplicationDocument.objects.create(
            application=application,
            template=template,
            document_key=template.document_key,
            name=template.name,
            document_role=template.document_role,
            display_order=template.display_order,
            inclusion_mode=template.inclusion_mode,
            selection_source=source,
            applicable=applicable,
            selected=selected,
            template_snapshot=_template_snapshot(template),
            schema_snapshot=template.form_schema or {},
            signer_rules_snapshot=(
                template.signer_rules
                if template.signer_rules
                else application.signer_rules_snapshot if template.document_role == template.ROLE_PRIMARY else []
            ),
        )


def refresh_document_applicability(application: LoanOriginationApplication) -> None:
    for document in application.packet_documents.exclude(document_role=OriginationDocumentTemplate.ROLE_PRIMARY):
        rule = (document.template_snapshot or {}).get('applicability_rule') or {}
        applicable = rule_matches(rule, application.form_payload)
        selected = document.selected
        source = document.selection_source
        if document.inclusion_mode == OriginationDocumentTemplate.INCLUDE_CONDITIONAL:
            selected, source = applicable, OriginationApplicationDocument.SOURCE_RULE
        elif not applicable:
            selected = False
        document.applicable = applicable
        document.selected = selected
        document.selection_source = source
        document.save(update_fields=['applicable', 'selected', 'selection_source', 'updated_at'])


def _document_fields(document: OriginationApplicationDocument) -> list[dict[str, Any]]:
    schema = document.schema_snapshot or {}
    fields = schema.get('fields') if isinstance(schema, dict) else []
    return fields if isinstance(fields, list) else []


def document_context(application: LoanOriginationApplication, document: OriginationApplicationDocument) -> dict[str, Any]:
    from core.services.loan_origination import preview_context
    return {**preview_context(application), **(document.field_payload or {})}


def serialize_document(document: OriginationApplicationDocument) -> dict[str, Any]:
    application = document.application
    fields = _document_fields(document)
    missing = [
        str(item.get('key')) for item in fields
        if item.get('required') and document_context(application, document).get(str(item.get('key'))) in (None, '')
    ]
    if document.document_role == OriginationDocumentTemplate.ROLE_PRIMARY:
        previewed = application.primary_previewed_revision == application.revision or application.events.filter(
            action='document_previewed', revision=application.revision,
        ).exists()
    else:
        previewed = document.previewed_application_revision == application.revision
    return {
        'key': document.document_key,
        'name': document.name,
        'role': document.document_role,
        'order': document.display_order,
        'inclusion_mode': document.inclusion_mode,
        'selection_source': document.selection_source,
        'applicable': document.applicable,
        'selected': document.selected,
        'officer_selectable': document.inclusion_mode == OriginationDocumentTemplate.INCLUDE_OPTIONAL,
        'schema': document.schema_snapshot,
        'field_payload': document.field_payload,
        'missing_fields': missing,
        'complete': not missing,
        'previewed': previewed,
    }


def serialize_packet(application: LoanOriginationApplication) -> dict[str, Any]:
    documents = [serialize_document(item) for item in application.packet_documents.all()]
    primary = next((item for item in documents if item['role'] == 'primary'), None)
    selected = [item for item in documents if item['selected']]
    return {
        'primary_ready': bool(primary and primary['complete'] and primary['previewed']),
        'documents': documents,
        'ready': bool(selected) and all(item['complete'] and item['previewed'] for item in selected),
    }


@transaction.atomic
def select_documents(*, application_id, actor, selected_keys: Any, expected_revision: int, request_id: str):
    from core.services.loan_origination import OriginationConflict, OriginationError, _record_event, _require_request_id
    request_id = _require_request_id(request_id)
    application = LoanOriginationApplication.objects.select_for_update().get(pk=application_id)
    if application.events.filter(request_id=request_id).exists():
        return application
    if application.officer_id != actor.pk:
        raise OriginationError('Only the assigned officer may select supporting documents.')
    if int(expected_revision) != application.revision:
        raise OriginationConflict('This application changed. Refresh before selecting documents.')
    if application.primary_previewed_revision != application.revision and not application.events.filter(
        action='document_previewed', revision=application.revision,
    ).exists():
        raise OriginationError('Save and preview the primary LAF before selecting supporting documents.')
    requested = {str(key) for key in (selected_keys or [])}
    allowed = set()
    changed = False
    for document in application.packet_documents.select_for_update().all():
        if document.document_role == OriginationDocumentTemplate.ROLE_PRIMARY:
            continue
        if document.inclusion_mode == OriginationDocumentTemplate.INCLUDE_OPTIONAL and document.applicable:
            allowed.add(document.document_key)
            next_selected = document.document_key in requested
            changed = changed or next_selected != document.selected
            document.selected = next_selected
            document.selection_source = OriginationApplicationDocument.SOURCE_OFFICER
            document.save(update_fields=['selected', 'selection_source', 'updated_at'])
    unknown = requested - allowed
    if unknown:
        raise OriginationError('One or more supporting documents cannot be selected for this application.')
    if not changed:
        _record_event(application, 'document_selection_unchanged', actor=actor, request_id=request_id)
        return application
    application.revision += 1
    application.primary_previewed_revision = application.revision
    application.save(update_fields=['revision', 'primary_previewed_revision', 'updated_at'])
    _record_event(application, 'document_selection_updated', actor=actor, request_id=request_id, after={'selected_keys': sorted(requested)})
    return application


@transaction.atomic
def save_document_fields(*, application_id, document_key: str, actor, payload: Any, expected_revision: int, request_id: str):
    from core.services.loan_origination import (
        OriginationConflict, OriginationError, _record_event, _require_request_id,
        validate_form_payload,
    )
    request_id = _require_request_id(request_id)
    application = LoanOriginationApplication.objects.select_for_update().get(pk=application_id)
    if application.events.filter(request_id=request_id).exists():
        return application
    if application.officer_id != actor.pk:
        raise OriginationError('Only the assigned officer may edit supporting documents.')
    if int(expected_revision) != application.revision:
        raise OriginationConflict('This application changed. Refresh before saving this document.')
    document = application.packet_documents.select_for_update().filter(document_key=document_key).first()
    if not document or document.document_role == OriginationDocumentTemplate.ROLE_PRIMARY or not document.selected:
        raise OriginationError('This supporting document is not selected for the application.')
    result = validate_form_payload(document.schema_snapshot or {'fields': []}, payload, require_complete=False)
    if not result.valid:
        raise OriginationError('Correct the supporting-document fields before saving.', errors=result.errors)
    allowed = {str(item.get('key')) for item in _document_fields(document)}
    primary_keys = {
        str(item.get('key')) for item in (application.schema_snapshot or {}).get('fields', [])
        if isinstance(item, dict) and item.get('key')
    }
    values = {
        key: value for key, value in payload.items()
        if key in allowed and (key not in primary_keys or application.form_payload.get(key) in (None, ''))
    }
    if values == document.field_payload:
        _record_event(
            application, 'supporting_document_unchanged', actor=actor,
            request_id=request_id, after={'document_key': document_key},
        )
        return application
    document.field_payload = values
    document.previewed_application_revision = None
    document.save(update_fields=['field_payload', 'previewed_application_revision', 'updated_at'])
    application.form_payload = {**application.form_payload, **values}
    application.revision += 1
    application.primary_previewed_revision = application.revision
    application.save(update_fields=['form_payload', 'revision', 'primary_previewed_revision', 'updated_at'])
    refresh_document_applicability(application)
    _record_event(application, 'supporting_document_saved', actor=actor, request_id=request_id, after={'document_key': document_key})
    return application


def render_document(application: LoanOriginationApplication, document_key: str) -> bytes:
    from core.services.loan_origination import OriginationError, render_application_preview
    document = application.packet_documents.select_related('template').filter(document_key=document_key).first()
    if document_key == 'primary' and not document:
        return render_application_preview(application)
    if not document or not document.selected:
        raise OriginationError('This document is not selected for the application.')
    if document.document_role == OriginationDocumentTemplate.ROLE_PRIMARY:
        return render_application_preview(application)
    if not document.template_id:
        raise OriginationError('The supporting document template is unavailable.')
    from core.services.origination_templates import load_template_source
    from core.services.partnership_laf_preview import render_template
    configuration = (document.template_snapshot or {}).get('configuration') or {}
    return render_template(load_template_source(document.template), configuration, document_context(application, document))


def mark_document_previewed(application: LoanOriginationApplication, document_key: str) -> None:
    document = application.packet_documents.filter(document_key=document_key).first()
    if document and document.document_role != OriginationDocumentTemplate.ROLE_PRIMARY:
        document.previewed_application_revision = application.revision
        document.save(update_fields=['previewed_application_revision', 'updated_at'])


def render_packet(application: LoanOriginationApplication) -> tuple[bytes, list[dict[str, Any]]]:
    writer = PdfWriter()
    manifest = []
    for document in application.packet_documents.filter(selected=True).order_by('display_order', 'document_key'):
        content = render_document(application, document.document_key)
        digest = hashlib.sha256(content).hexdigest()
        reader = PdfReader(BytesIO(content))
        for page in reader.pages:
            writer.add_page(page)
        manifest.append({
            'key': document.document_key,
            'name': document.name,
            'template': document.template_snapshot,
            'rendered_sha256': digest,
            'signer_rules': document.signer_rules_snapshot,
            'page_count': len(reader.pages),
        })
    if not manifest:
        content = render_document(application, 'primary')
        return content, []
    output = BytesIO()
    writer.write(output)
    return output.getvalue(), manifest


def packet_signers(application: LoanOriginationApplication) -> list[dict[str, Any]]:
    from core.services.loan_origination import OriginationError
    roles: dict[str, dict[str, Any]] = {}
    documents = application.packet_documents.filter(selected=True)
    if not documents.exists():
        return application.signer_rules_snapshot
    for document in documents:
        for raw in document.signer_rules_snapshot or []:
            role = str(raw.get('role') or '').strip() if isinstance(raw, dict) else ''
            if not role:
                continue
            existing = roles.get(role)
            if existing is not None and existing != raw:
                raise OriginationError(f'Conflicting signer definitions exist for role {role}.')
            roles[role] = raw
    return list(roles.values())
