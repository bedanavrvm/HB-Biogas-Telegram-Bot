"""Catalogue-backed document preparation for the product-first admin journey.

Selection events retain the work-in-progress intent; catalogue eligibility remains
the authority for application availability. No legacy packet assignments are made.
"""

from copy import deepcopy
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction

from origination.models import (
    OriginationDocumentProductEligibility, OriginationDocumentTemplate,
    OriginationDocumentTemplateEvent, OriginationProductDefinitionEvent,
)


def _require_authority(actor):
    if not getattr(actor, 'is_active', False) or not getattr(actor, 'is_superuser', False):
        raise ValidationError('Only an active Superuser may set up Origination documents.')


def selected_documents(definition):
    event = definition.events.filter(action='setup_documents_selected').order_by('-occurred_at', '-pk').first()
    documents = OriginationDocumentTemplate.objects.filter(
        product_eligibilities__product_id=definition.product_version.product_id,
        status__in=['ready', 'active'],
    ).distinct()
    if event:
        documents = documents.filter(pk__in=event.metadata.get('template_ids', []))
    return documents.order_by('display_order', 'name', '-version')


@transaction.atomic
def select_documents(*, definition, templates, actor, request_id):
    """Connect explicit choices without modifying any published document bytes."""
    from origination.services.origination_templates import clone_reusable_template_version
    _require_authority(actor)
    if definition.lifecycle_status not in {definition.STATUS_DRAFT, definition.STATUS_PUBLISHED}:
        raise ValidationError('Retired products cannot change document availability.')
    resolved = []
    for template in templates:
        if not template.product_eligibilities.filter(product_id=definition.product_version.product_id).exists():
            if template.status == template.STATUS_ACTIVE:
                template, _reused = clone_reusable_template_version(template, actor=actor)
            OriginationDocumentProductEligibility.objects.get_or_create(
                template=template, product_id=definition.product_version.product_id,
                defaults={'created_by': actor},
            )
            OriginationDocumentTemplateEvent.objects.create(
                template=template, action='setup_product_connected', actor=actor,
                metadata={'product_id': str(definition.product_version.product_id), 'request_id': request_id},
            )
        resolved.append(template)
    OriginationProductDefinitionEvent.objects.create(
        product_definition=definition, action='setup_documents_selected', actor=actor,
        metadata={'template_ids': [str(item.pk) for item in resolved], 'request_id': request_id},
    )
    return resolved


def create_setup_document(*, definition, pdf_file, name, role, preset, actor):
    _require_authority(actor)
    from origination.services.origination_templates import (
        initial_template_configuration, upload_template_record, validate_template_pdf,
    )
    schema, signers = {}, []
    if preset == 'generic_jawabu_laf':
        from origination.services.generic_jawabu_laf_seed import SIGNER_RULES, build_form_schema, ensure_catalogue
        schema = build_form_schema(ensure_catalogue(actor=actor))
        signers = deepcopy(SIGNER_RULES)
    data = pdf_file.read()
    digest, pages = validate_template_pdf(data)
    # A new upload is a new family. Replacing a family is an explicit version action.
    family = f'document-{uuid.uuid4().hex}'
    template = OriginationDocumentTemplate.objects.create(
        document_type=family, version=1, name=name,
        document_key='primary' if role == 'primary' else family,
        document_role=role, status=OriginationDocumentTemplate.STATUS_READY,
        source_filename=pdf_file.name[:255], source_sha256=digest,
        source_byte_size=len(data), page_count=pages, form_schema=schema,
        signer_rules=signers, created_by=actor,
        placement_config={**initial_template_configuration(None, form_schema=schema),
                          'document_type': family, 'version': 1},
    )
    OriginationDocumentTemplateEvent.objects.create(
        template=template, action='created', actor=actor,
        metadata={'source': 'guided_setup', 'sha256': digest, 'page_count': pages},
    )
    OriginationDocumentProductEligibility.objects.create(
        template=template, product_id=definition.product_version.product_id, created_by=actor,
    )
    return upload_template_record(template, pdf_data=data, actor=actor)


def prepare_document_profile(*, definition, templates):
    """Derive compatibility from the LAF, preserving the product's approval policy."""
    from origination.services.origination_commercial_terms import merge_commercial_contract
    from origination.services.origination_fields import template_form_contract
    if definition.lifecycle_status != definition.STATUS_DRAFT:
        raise ValidationError('Published product contracts remain unchanged.')
    main = next((item for item in templates if item.document_role == item.ROLE_PRIMARY), None)
    if not main:
        raise ValidationError('Choose at least one Main LAF.')
    schema, signers = template_form_contract(main)
    definition.form_schema = merge_commercial_contract(schema)
    # Preserve established minimum signing requirements; a new product adopts
    # its chosen LAF roles once instead of asking for a second signer builder.
    if not definition.signer_rules:
        definition.signer_rules = deepcopy(signers)
    if definition.approval_roles:
        by_role = {rule.get('role'): rule for rule in definition.signer_rules}
        document_roles = {rule.get('role'): rule for rule in signers}
        for role in ['officer', 'credit_analyst', *definition.approval_roles]:
            if role not in by_role:
                rule = deepcopy(document_roles.get(role, {'role': role}))
                rule['required'] = True
                definition.signer_rules.append(rule)
            else:
                by_role[role]['required'] = True
    definition.save(update_fields=['form_schema', 'signer_rules', 'updated_at'])


def document_readiness(definition):
    from origination.services.origination_document_catalogue import main_laf_contract, validate_document_combination
    from origination.services.origination_fields import template_form_contract
    from origination.services.origination_templates import _expected_signature_slots
    templates = list(selected_documents(definition))
    mains = [item for item in templates if item.document_role == item.ROLE_PRIMARY]
    errors = []
    if not mains:
        errors.append('Choose a Main LAF.')
    if mains:
        from origination.services.loan_origination import validate_product_definition
        try:
            validate_product_definition(definition)
        except ValueError as exc:
            errors.append(str(exc))
    for template in templates:
        revision = (template.published_configuration_revision if template.status == template.STATUS_ACTIVE
                    else template.configuration_revisions.order_by('-revision').first())
        if not revision or not template.drive_file_id:
            errors.append(f'{template.name}: save its fields and PDF alignment.')
            continue
        # Dashboard reads must not download PDFs or contact Drive. Full source,
        # page-boundary and integrity checks run only at explicit publication.
        config = revision.configuration or {}
        if not isinstance(config, dict):
            errors.append(f'{template.name}: review its saved alignment.')
            continue
        fields = (config.get('field_overlay_manifest') or {}).get('fields') or {}
        slots = (config.get('signature_overlay_manifest') or {}).get('slots') or {}
        if not isinstance(fields, dict) or not isinstance(slots, dict):
            errors.append(f'{template.name}: review its field and signature alignment.')
            continue
        schema, _signers = template_form_contract(template)
        mapped = {spec.get('context_key') for spec in fields.values() if isinstance(spec, dict)}
        missing = [field.get('label') or field.get('key') for field in schema.get('fields', [])
                   if field.get('required') and field.get('key') not in mapped]
        if not fields or missing:
            errors.append(f'{template.name}: align required fields' + (': ' + ', '.join(missing) if missing else '.'))
        expected_slots = _expected_signature_slots(template.product_definition, template)
        missing_slots = [spec.get('label') or key for key, spec in expected_slots.items()
                         if spec.get('required') and key not in slots]
        if missing_slots:
            errors.append(f'{template.name}: align signing locations: ' + ', '.join(missing_slots))
        if template in mains:
            # Draft alignment is deliberately not published until Enable.
            original_revision = template.published_configuration_revision_id
            template.published_configuration_revision_id = revision.pk
            _schema, reasons = main_laf_contract(definition, template, require_active=False)
            template.published_configuration_revision_id = original_revision
            for reason in reasons:
                reason = reason.replace('The Main LAF is missing the canonical commercial field ', 'Add the field ')
                for field in definition.form_schema.get('fields', []):
                    if field.get('key') and field.get('label'):
                        reason = reason.replace(str(field['key']), str(field['label']))
                errors.append(f'{template.name}: {reason}')
    try:
        for main in mains:
            validate_document_combination(main, [item for item in templates if item not in mains])
    except ValueError as exc:
        errors.append(str(exc))
    return templates, errors


@transaction.atomic
def publish_setup_documents(*, definition, actor, request_id):
    _require_authority(actor)
    from origination.services.origination_templates import publish_product_template, validate_template_configuration
    templates, errors = document_readiness(definition)
    if errors:
        raise ValidationError(errors)
    for item in sorted(templates, key=lambda item: str(item.pk)):
        template = OriginationDocumentTemplate.objects.select_for_update().get(pk=item.pk)
        revision = (template.published_configuration_revision if template.status == template.STATUS_ACTIVE
                    else template.configuration_revisions.order_by('-revision').first())
        validate_template_configuration(revision.configuration, template=template, require_complete=True)
        if template.status == template.STATUS_ACTIVE:
            continue
        publish_product_template(template=template, revision=revision.revision,
                                 actor=actor, client_request_id=f'{request_id}:{template.pk}')
