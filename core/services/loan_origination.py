"""Canonical, product-neutral loan-origination application services."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import (
    LoanOriginationApplication,
    OriginationApplicationEvent,
    OriginationProductDefinition,
    OriginationSigningPackage,
)


class OriginationError(ValueError):
    """Stable validation error safe for Portal responses."""


class OriginationConflict(OriginationError):
    """The caller attempted to change a stale application revision."""


SUPPORTED_FIELD_TYPES = {
    'text', 'textarea', 'number', 'money', 'date', 'phone', 'national_id',
    'choice', 'boolean',
}

SIGNER_ROLE_CATALOG = (
    ('borrower', 'Borrower'),
    ('customer', 'Customer (legacy borrower role)'),
    ('guarantor_1', 'Guarantor 1'),
    ('guarantor_2', 'Guarantor 2'),
    ('bro_1', 'Business Relationship Officer 1'),
    ('bro_2', 'Business Relationship Officer 2'),
    ('loan_officer', 'Loan Officer'),
    ('officer', 'Officer (legacy role)'),
    ('branch_manager', 'Branch Manager'),
    ('commissioner_for_oaths', 'Commissioner for Oaths'),
)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: dict[str, str]


def _require_request_id(request_id: str) -> str:
    value = str(request_id or '').strip()
    if not value:
        raise OriginationError('A client request ID is required.')
    return value[:128]


def _schema_fields(schema: dict[str, Any]) -> list[dict[str, Any]]:
    fields = schema.get('fields', []) if isinstance(schema, dict) else []
    if not isinstance(fields, list):
        raise OriginationError('The product form schema is invalid.')
    return [field for field in fields if isinstance(field, dict)]


def validate_product_form_contract(form_schema: dict[str, Any], signer_rules: Any) -> None:
    """Validate the visual form and signer contract before template calibration."""
    fields = _schema_fields(form_schema)
    if not fields:
        raise OriginationError('An active origination product requires at least one form field.')
    keys = [str(field.get('key') or '').strip() for field in fields]
    if any(not key for key in keys) or len(keys) != len(set(keys)):
        raise OriginationError('Every origination field requires a unique key.')
    sections = form_schema.get('sections', []) if isinstance(form_schema, dict) else []
    if sections:
        if not isinstance(sections, list) or any(not isinstance(item, dict) for item in sections):
            raise OriginationError('Origination form sections must be a list of objects.')
        section_keys = [str(item.get('key') or '').strip() for item in sections]
        if any(not key for key in section_keys) or len(section_keys) != len(set(section_keys)):
            raise OriginationError('Every origination section requires a unique key.')
        unknown_sections = sorted({
            str(field.get('section_key') or '').strip()
            for field in fields
            if str(field.get('section_key') or '').strip() not in set(section_keys)
        })
        if unknown_sections:
            raise OriginationError(f'Unknown origination sections: {", ".join(unknown_sections)}.')
    for field in fields:
        field_type = str(field.get('type') or 'text').strip()
        if field_type not in SUPPORTED_FIELD_TYPES:
            raise OriginationError(f'Field {field.get("key")} has an unsupported control type.')
        if field_type == 'choice':
            options = field.get('options')
            if not isinstance(options, list) or not [item for item in options if str(item).strip()]:
                raise OriginationError(f'Choice field {field.get("key")} requires at least one option.')
    known_roles = {key for key, _label in SIGNER_ROLE_CATALOG}
    if not isinstance(signer_rules, list) or not signer_rules:
        raise OriginationError('An active origination product requires signer rules.')
    roles = [str(item.get('role') or '').strip() for item in signer_rules if isinstance(item, dict)]
    if len(roles) != len(signer_rules) or any(role not in known_roles for role in roles):
        raise OriginationError('Every signer requires a role from the approved catalogue.')
    if len(roles) != len(set(roles)):
        raise OriginationError('Signer roles cannot be duplicated.')
    for rule in signer_rules:
        slots = rule.get('slots', [])
        if not isinstance(slots, list):
            raise OriginationError(f'Signer {rule.get("role")} requires a valid slot list.')
        if rule.get('required', False) and 'slots' in rule and not slots:
            raise OriginationError(f'Required signer {rule.get("role")} requires at least one signature or stamp slot.')
        slot_keys = []
        for raw_slot in slots:
            slot = {'key': raw_slot} if isinstance(raw_slot, str) else raw_slot
            if not isinstance(slot, dict) or not str(slot.get('key') or '').strip():
                raise OriginationError(f'Signer {rule.get("role")} has an invalid slot.')
            slot_keys.append(str(slot.get('key')).strip())
            if str(slot.get('type') or rule.get('slot_type') or 'signature') not in {'signature', 'stamp'}:
                raise OriginationError(f'Signer {rule.get("role")} has an unsupported slot type.')
        if len(slot_keys) != len(set(slot_keys)):
            raise OriginationError(f'Signer {rule.get("role")} has duplicate slot keys.')


def validate_product_definition(definition: OriginationProductDefinition) -> None:
    """Reject activation of incomplete or ambiguous product contracts."""
    validate_product_form_contract(definition.form_schema, definition.signer_rules)
    if not definition.document_type.strip():
        raise OriginationError('An active origination product requires an e-sign document type.')
    if not definition.document_template_name.strip():
        raise OriginationError('An active origination product requires an approved document template.')
    digest = definition.document_template_sha256.strip().lower()
    if len(digest) != 64 or any(character not in '0123456789abcdef' for character in digest):
        raise OriginationError('The approved document template requires a valid SHA-256 digest.')


def validate_form_payload(schema: dict[str, Any], payload: Any, *, require_complete: bool) -> ValidationResult:
    if not isinstance(payload, dict):
        return ValidationResult(False, {'form': 'Application data must be an object.'})
    errors: dict[str, str] = {}
    fields = _schema_fields(schema)
    known = {str(field.get('key') or '').strip(): field for field in fields}
    unknown = sorted(set(payload) - set(known))
    if unknown:
        errors['form'] = f'Unknown application fields: {", ".join(unknown)}.'
    for key, field in known.items():
        value = payload.get(key)
        if require_complete and field.get('required') and value in (None, '', []):
            errors[key] = 'This field is required.'
            continue
        if value in (None, ''):
            continue
        field_type = str(field.get('type') or 'text')
        if field_type in {'text', 'textarea', 'phone', 'national_id', 'date', 'choice'} and not isinstance(value, str):
            errors[key] = 'Enter a valid text value.'
        elif field_type == 'boolean' and not isinstance(value, bool):
            errors[key] = 'Choose yes or no.'
        elif field_type in {'money', 'number'}:
            from decimal import Decimal, InvalidOperation
            try:
                Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError):
                errors[key] = 'Enter a valid amount.'
    return ValidationResult(not errors, errors)


def _record_event(application, action: str, *, actor, request_id: str = '', before=None, after=None) -> None:
    event = OriginationApplicationEvent.objects.create(
        application=application,
        action=action,
        revision=application.revision,
        actor=actor,
        request_id=request_id,
        before_values=before or {},
        after_values=after or {},
    )
    from core.services.compliance_audit import record_event
    record_event(
        workflow='portal', action=f'portal.origination.{action}', category='workflow',
        origin='human' if actor else 'system', subject_type='loan_origination_application',
        subject_id=str(application.pk), actor=actor, authority_user=actor,
        request_id=request_id, source_model='OriginationApplicationEvent',
        source_event_id=str(event.pk),
        deduplication_key=f'portal:OriginationApplicationEvent:{event.pk}',
        after_values={'status': application.status, 'revision': application.revision},
        metadata={'product_key': application.product_definition.product_key}, sensitive=True,
        occurred_at=event.occurred_at,
    )


def preview_context(application: LoanOriginationApplication) -> dict[str, Any]:
    return {
        **application.form_payload,
        'reference_number': application.reference_number,
        'branch_code': application.branch,
        'loan_officer_name': application.officer.get_full_name() or application.officer.get_username(),
        'application_date': timezone.localdate(application.created_at).isoformat(),
    }


def render_application_preview(application: LoanOriginationApplication) -> bytes:
    """Render the approved PDF locally; no signing package or file is persisted."""
    definition = application.product_definition
    # Until a signing package is prepared this endpoint is a live preview, so
    # it must reflect the latest published Admin calibration.  The signing
    # package remains immutable and continues to use its captured snapshot.
    if application.status in {
        LoanOriginationApplication.STATUS_DRAFT,
        LoanOriginationApplication.STATUS_CORRECTION_REQUIRED,
        LoanOriginationApplication.STATUS_READY_FOR_REVIEW,
        LoanOriginationApplication.STATUS_REVIEWED,
    }:
        latest_configuration = _published_template_configuration(definition)
        if latest_configuration and latest_configuration != application.template_configuration_snapshot:
            application.template_configuration_snapshot = latest_configuration
            application.save(update_fields=['template_configuration_snapshot', 'updated_at'])
    try:
        from core.services.partnership_laf_preview import (
            PartnershipLafPreviewError, render_origination_document, render_partnership_laf,
        )
        renderer = render_partnership_laf if definition.document_type == 'partnership_loan_application' else render_origination_document
        kwargs = {
            'version': definition.document_template_version,
            'expected_sha256': definition.document_template_sha256,
            'configuration': application.template_configuration_snapshot or None,
        }
        if renderer is render_origination_document:
            kwargs['document_type'] = definition.document_type
        return renderer(preview_context(application), **kwargs)
    except PartnershipLafPreviewError as exc:
        raise OriginationError(str(exc)) from exc


@transaction.atomic
def create_application(*, product_key: str, officer, branch: str, client_request_id: str) -> tuple[LoanOriginationApplication, bool]:
    client_request_id = _require_request_id(client_request_id)
    existing = LoanOriginationApplication.objects.filter(
        officer=officer, client_request_id=client_request_id,
    ).first()
    if existing:
        return existing, True
    definition = OriginationProductDefinition.objects.filter(
        product_key=product_key, is_active=True,
    ).first()
    if not definition:
        raise OriginationError('This origination product is not active.')
    validate_product_definition(definition)
    application_id = uuid.uuid4()
    try:
        with transaction.atomic():
            application = LoanOriginationApplication.objects.create(
                id=application_id,
                reference_number=f'ORG-{timezone.localdate():%Y}-{str(application_id)[:8].upper()}',
                product_definition=definition,
                officer=officer,
                branch=str(branch or '').strip(),
                schema_snapshot=definition.form_schema,
                signer_rules_snapshot=definition.signer_rules,
                template_configuration_snapshot=_published_template_configuration(definition),
                client_request_id=client_request_id,
            )
    except IntegrityError:
        existing = LoanOriginationApplication.objects.filter(
            officer=officer, client_request_id=client_request_id,
        ).first()
        if existing:
            return existing, True
        raise
    _record_event(application, 'created', actor=officer, request_id=client_request_id)
    return application, False


def _published_template_configuration(definition: OriginationProductDefinition) -> dict[str, Any]:
    from core.models import OriginationDocumentTemplate
    template = OriginationDocumentTemplate.objects.filter(
        document_type=definition.document_type,
        version=definition.document_template_version,
        source_sha256=definition.document_template_sha256,
        status=OriginationDocumentTemplate.STATUS_ACTIVE,
    ).first()
    if not template:
        return {}
    revision = template.published_configuration_revision
    return (revision.configuration if revision else template.placement_config) or {}
@transaction.atomic
def save_application_fields(*, application_id, actor, payload: Any, expected_revision: int, request_id: str) -> LoanOriginationApplication:
    request_id = _require_request_id(request_id)
    application = LoanOriginationApplication.objects.select_for_update().select_related('product_definition').get(pk=application_id)
    if request_id and application.events.filter(request_id=request_id).exists():
        return application
    if application.officer_id != actor.pk:
        raise OriginationError('Only the assigned officer may edit this application.')
    if application.status not in {
        LoanOriginationApplication.STATUS_DRAFT,
        LoanOriginationApplication.STATUS_CORRECTION_REQUIRED,
    }:
        raise OriginationError('This application is no longer editable.')
    if int(expected_revision) != application.revision:
        raise OriginationConflict('This application changed on another device. Refresh before saving again.')
    result = validate_form_payload(application.schema_snapshot, payload, require_complete=False)
    if not result.valid:
        raise OriginationError(next(iter(result.errors.values())))
    before = {'status': application.status, 'revision': application.revision}
    application.form_payload = payload
    application.revision += 1
    application.status = LoanOriginationApplication.STATUS_DRAFT
    application.save(update_fields=['form_payload', 'revision', 'status', 'updated_at'])
    _record_event(application, 'fields_saved', actor=actor, request_id=request_id, before=before)
    return application


@transaction.atomic
def submit_for_review(*, application_id, actor, expected_revision: int, request_id: str) -> LoanOriginationApplication:
    request_id = _require_request_id(request_id)
    application = LoanOriginationApplication.objects.select_for_update().select_related('product_definition').get(pk=application_id)
    if request_id and application.events.filter(request_id=request_id).exists():
        return application
    if application.officer_id != actor.pk:
        raise OriginationError('Only the assigned officer may submit this application.')
    if int(expected_revision) != application.revision:
        raise OriginationConflict('This application changed on another device. Refresh before submitting.')
    if application.status not in {LoanOriginationApplication.STATUS_DRAFT, LoanOriginationApplication.STATUS_CORRECTION_REQUIRED}:
        raise OriginationError('This application cannot be submitted from its current state.')
    result = validate_form_payload(application.schema_snapshot, application.form_payload, require_complete=True)
    if not result.valid:
        raise OriginationError('Complete all required application fields before review.')
    if not application.events.filter(action='document_previewed', revision=application.revision).exists():
        raise OriginationError('Preview the filled document for this saved revision before submitting.')
    application.status = LoanOriginationApplication.STATUS_READY_FOR_REVIEW
    application.revision += 1
    application.submitted_at = timezone.now()
    application.save(update_fields=['status', 'revision', 'submitted_at', 'updated_at'])
    _record_event(application, 'submitted_for_review', actor=actor, request_id=request_id)
    return application


@transaction.atomic
def review_application(
    *, application_id, actor, expected_revision: int, request_id: str,
    decision: str, reason: str = '',
) -> LoanOriginationApplication:
    request_id = _require_request_id(request_id)
    application = LoanOriginationApplication.objects.select_for_update().select_related('product_definition').get(pk=application_id)
    if request_id and application.events.filter(request_id=request_id).exists():
        return application
    if int(expected_revision) != application.revision:
        raise OriginationConflict('This application changed on another device. Refresh before reviewing.')
    if application.status != LoanOriginationApplication.STATUS_READY_FOR_REVIEW:
        raise OriginationError('This application is not ready for review.')
    normalized = str(decision or '').strip().casefold()
    if normalized not in {'approve', 'request_correction', 'decline'}:
        raise OriginationError('Choose approve, request_correction, or decline.')
    if application.officer_id == actor.pk and not getattr(actor, 'is_superuser', False):
        raise OriginationError('The submitting officer cannot review their own application.')
    reason = str(reason or '').strip()
    if normalized != 'approve' and not reason:
        raise OriginationError('A reason is required for corrections or decline.')
    status_by_decision = {
        'approve': LoanOriginationApplication.STATUS_REVIEWED,
        'request_correction': LoanOriginationApplication.STATUS_CORRECTION_REQUIRED,
        'decline': LoanOriginationApplication.STATUS_DECLINED,
    }
    before = {'status': application.status, 'revision': application.revision}
    application.status = status_by_decision[normalized]
    application.revision += 1
    application.reviewed_by = actor
    application.reviewed_at = timezone.now()
    application.save(update_fields=['status', 'revision', 'reviewed_by', 'reviewed_at', 'updated_at'])
    _record_event(
        application, f'review_{normalized}', actor=actor, request_id=request_id,
        before=before, after={'reason': reason} if reason else {},
    )
    return application


@transaction.atomic
def prepare_signing_package(
    *, application_id, actor, expected_revision: int, request_id: str,
) -> tuple[OriginationSigningPackage, bool]:
    """Freeze a reviewed revision locally; this deliberately performs no remote dispatch."""
    request_id = _require_request_id(request_id)
    application = LoanOriginationApplication.objects.select_for_update().select_related('product_definition').get(pk=application_id)
    if application.status == LoanOriginationApplication.STATUS_SIGNING_PENDING:
        existing = application.signing_packages.order_by('-created_at').first()
        if existing:
            return existing, True
    existing = OriginationSigningPackage.objects.filter(
        application=application, application_revision=application.revision,
    ).first()
    if existing:
        return existing, True
    if int(expected_revision) != application.revision:
        raise OriginationConflict('This application changed on another device. Refresh before preparing signing.')
    if application.status != LoanOriginationApplication.STATUS_REVIEWED:
        raise OriginationError('Only a reviewed application can be prepared for signing.')
    package_id = uuid.uuid4()
    package = OriginationSigningPackage.objects.create(
        id=package_id,
        application=application,
        application_revision=application.revision,
        external_reference=f'ESIGN-{str(package_id)[:12].upper()}',
        document_type=application.product_definition.document_type,
        template_version=application.product_definition.document_template_version,
        template_sha256=application.product_definition.document_template_sha256,
        template_configuration_snapshot=application.template_configuration_snapshot,
        context_snapshot=preview_context(application),
        participants_snapshot=application.signer_rules_snapshot,
    )
    application.status = LoanOriginationApplication.STATUS_SIGNING_PENDING
    application.revision += 1
    application.save(update_fields=['status', 'revision', 'updated_at'])
    _record_event(
        application, 'signing_prepared', actor=actor, request_id=request_id,
        after={'signing_package_id': str(package.pk)},
    )
    return package, False


def serialize_application(application: LoanOriginationApplication, *, include_payload: bool = True) -> dict[str, Any]:
    payload = {
        'id': str(application.pk), 'reference_number': application.reference_number,
        'product_key': application.product_definition.product_key,
        'product_name': application.product_definition.name,
        'product_version': application.product_definition.version,
        'branch': application.branch, 'status': application.status,
        'revision': application.revision, 'updated_at': application.updated_at.isoformat(),
    }
    if include_payload:
        payload.update({'form_payload': application.form_payload, 'form_schema': application.schema_snapshot})
    return payload
