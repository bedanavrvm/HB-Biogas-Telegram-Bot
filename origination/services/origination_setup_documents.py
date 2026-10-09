"""Catalogue-backed document preparation for the product-first admin journey.

Selection events retain the work-in-progress intent; catalogue eligibility remains
the authority for application availability. No legacy packet assignments are made.
"""

from copy import deepcopy
import hashlib
import json
import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from origination.models import (
    OriginationDocumentProductEligibility, OriginationDocumentTemplate,
    OriginationDocumentTemplateEvent, OriginationProductDefinitionEvent,
    OriginationProductDefinition,
)


def _require_authority(actor):
    if not getattr(actor, 'is_active', False) or not getattr(actor, 'is_superuser', False):
        raise ValidationError('Only an active Superuser may set up Origination documents.')


def _upload_reserved_document(template, *, data, actor):
    """One bounded upload owner per retained draft; no DB lock spans Drive I/O."""
    from origination.services.origination_templates import upload_template_record
    attempt_id = str(uuid.uuid4())
    with transaction.atomic():
        template = OriginationDocumentTemplate.objects.order_by().select_for_update(of=('self',)).get(pk=template.pk)
        if template.drive_file_id and template.status != 'upload_failed':
            return template
        latest = template.events.filter(action__in=['setup_upload_started', 'setup_upload_finished']).order_by('-occurred_at', '-pk').first()
        if latest and latest.action == 'setup_upload_started' and latest.occurred_at > timezone.now() - timedelta(minutes=10):
            raise ValidationError('This PDF is already uploading. Wait for it to finish, then retry the same draft.')
        OriginationDocumentTemplateEvent.objects.create(template=template, action='setup_upload_started', actor=actor,
            metadata={'attempt_id': attempt_id})
    try:
        return upload_template_record(template, pdf_data=data, actor=actor)
    finally:
        OriginationDocumentTemplateEvent.objects.create(template=template, action='setup_upload_finished', actor=actor,
            metadata={'attempt_id': attempt_id})


def selected_documents(definition):
    event = definition.events.filter(action='setup_documents_selected').order_by('-occurred_at', '-pk').first()
    documents = OriginationDocumentTemplate.objects.filter(
        product_eligibilities__product_id=definition.product_version.product_id,
        status__in=['ready', 'active'],
    ).distinct()
    if event:
        from django.db.models import Q
        chosen = Q(pk__in=event.metadata.get('template_ids', []))
        if definition.lifecycle_status == definition.STATUS_PUBLISHED:
            chosen |= Q(status='active')
        documents = documents.filter(chosen)
    changes = pending_changes(definition)
    removed = [item['source'] for item in changes if item['action'] in {'remove', 'replace', 'edit'}]
    documents = documents.exclude(pk__in=removed)
    return documents.order_by('display_order', 'name', '-version')


def pending_changes(definition):
    event = definition.events.filter(action__in=['maintenance_staged', 'maintenance_applied']).order_by('-occurred_at', '-pk').first()
    return event.metadata.get('changes', []) if event and event.action == 'maintenance_staged' else []


def maintenance_impact(definition):
    """Database-only review of exact versions and the current shared blast radius."""
    changes = pending_changes(definition)
    templates = list(selected_documents(definition))
    ids = {item['source'] for item in changes} | {item['target'] for item in changes if item.get('target')}
    ids.update(str(item.pk) for item in templates)
    records = list(OriginationDocumentTemplate.objects.filter(pk__in=ids))
    families = {item.document_type for item in records}
    records += list(OriginationDocumentTemplate.objects.filter(document_type__in=families, status='active').exclude(pk__in=ids))
    facts = []
    for item in sorted(records, key=lambda item: str(item.pk)):
        revision = item.configuration_revisions.order_by('-revision').first()
        facts.append([str(item.pk), item.status, item.source_sha256, item.form_schema, item.signer_rules,
                      revision.configuration if revision else None,
                      sorted(str(pk) for pk in item.eligible_products.values_list('pk', flat=True))])
    product_ids = {pk for item in records for pk in item.eligible_products.values_list('pk', flat=True)}
    profiles = list(OriginationProductDefinition.objects.filter(product_version__product_id__in=product_ids, is_active=True)
                    .order_by('pk').values('pk', 'form_schema', 'signer_rules', 'approval_roles'))
    token = hashlib.sha256(json.dumps([changes, facts, profiles], sort_keys=True, default=str).encode()).hexdigest()
    by_id = {str(item.pk): item for item in records}
    rows = [{'action': item['action'], 'source': by_id.get(item['source']),
             'target': by_id.get(item.get('target'))} for item in changes]
    products = set()
    for template in templates:
        if template.status == 'ready':
            products.update(OriginationDocumentTemplate.objects.filter(document_type=template.document_type, status='active')
                            .values_list('eligible_products__name', flat=True))
            products.update(template.eligible_products.values_list('name', flat=True))
    return {'token': token, 'changes': rows, 'affected_products': sorted(name for name in products if name),
            'unavailable': not any(item.document_role == 'primary' for item in templates)}


@transaction.atomic
def stage_change(*, definition, action, source, target=None, actor, request_id):
    _require_authority(actor)
    definition = OriginationProductDefinition.objects.select_for_update().get(pk=definition.pk)
    if definition.lifecycle_status not in {'draft', 'published'}:
        raise ValidationError('Retired products cannot change document availability.')
    replay = definition.events.filter(action='maintenance_staged', metadata__request_id=request_id).first()
    if replay:
        if replay.metadata.get('request') != {'action': action, 'source': str(source.pk), 'target': str(target.pk) if target else ''}:
            raise ValidationError('This request was already used for a different document change. Refresh and try again.')
        return replay.metadata['changes']
    if action not in {'remove', 'replace', 'edit'}:
        raise ValidationError('Choose a supported document action.')
    if not source.product_eligibilities.filter(product_id=definition.product_version.product_id).exists():
        raise ValidationError('This document is not connected to this product.')
    if source.status not in {'active', 'ready', 'upload_failed'}:
        raise ValidationError('This document changed. Refresh before editing.')
    if action != 'remove' and (not target or target.pk == source.pk or target.document_role != source.document_role):
        raise ValidationError('Choose a different document with the same purpose.')
    if target and target.status not in {'ready', 'active'}:
        raise ValidationError('Finish uploading the replacement document first.')
    request = {'action': action, 'source': str(source.pk), 'target': str(target.pk) if target else ''}
    changes = [item for item in pending_changes(definition) if item['source'] != str(source.pk)]
    changes.append({'action': action, 'source': str(source.pk), 'target': str(target.pk) if target else ''})
    if target:
        chosen = [item for item in selected_documents(definition) if item.pk != source.pk]
        chosen.append(target)
        resolved = select_documents(definition=definition, templates=chosen, actor=actor, request_id=request_id)
        changes[-1]['target'] = str(resolved[-1].pk)
    OriginationProductDefinitionEvent.objects.create(product_definition=definition, action='maintenance_staged', actor=actor,
        metadata={'request_id': request_id, 'request': request, 'changes': changes})
    return changes


@transaction.atomic
def prepare_edit(*, definition, source, actor, request_id):
    from origination.services.origination_templates import clone_reusable_template_version
    _require_authority(actor)
    if not source.product_eligibilities.filter(product_id=definition.product_version.product_id).exists():
        raise ValidationError('This document is not connected to this product.')
    if source.status == 'ready':
        return source
    successor, _ = clone_reusable_template_version(source, actor=actor)
    stage_change(definition=definition, action='edit', source=source, target=successor, actor=actor, request_id=request_id)
    return successor


def reconcile_shared_eligibility(template):
    """Inherited draft allowlists must never resurrect a withdrawn product."""
    source = OriginationDocumentTemplate.objects.filter(document_type=template.document_type, status='active').exclude(pk=template.pk).first()
    if not source:
        return
    explicit = template.events.filter(action='editor_products_selected').order_by('-occurred_at','-pk').first()
    if explicit:
        current_ids = sorted(str(pk) for pk in source.eligible_products.values_list('pk',flat=True))
        if current_ids != explicit.metadata['source_ids']:
            raise ValidationError('The products using this document changed. Review and save its product choices again.')
        # The editor saved an explicit allowlist; do not silently reattach a removed product.
        return
    added = set()
    for event in template.events.filter(action='setup_product_connected').order_by('occurred_at', 'pk'):
        product_id = event.metadata['product_id']
        withdrawn = OriginationDocumentTemplateEvent.objects.filter(template__document_type=template.document_type,
            action='product_withdrawn', metadata__product_id=product_id, occurred_at__gte=event.occurred_at).exists()
        if not withdrawn:
            added.add(product_id)
    current = set(str(pk) for pk in source.eligible_products.values_list('pk', flat=True)) | added
    template.product_eligibilities.exclude(product_id__in=current).delete()
    for product_id in current:
        OriginationDocumentProductEligibility.objects.get_or_create(template=template, product_id=product_id)


def replace_pdf(*, definition, source, pdf_file, actor, request_id):
    """Reserve a distinct source, upload without DB locks, and retain retry ownership."""
    from origination.services.origination_templates import validate_template_pdf, upload_template_record, initial_template_configuration
    from origination.services.origination_fields import template_form_contract
    _require_authority(actor)
    if not source.product_eligibilities.filter(product_id=definition.product_version.product_id).exists():
        raise ValidationError('This document is not connected to this product.')
    data = pdf_file.read()
    digest, pages = validate_template_pdf(data)
    if digest == source.source_sha256:
        return source
    with transaction.atomic():
        locked = OriginationDocumentTemplate.objects.order_by().select_for_update(of=('self',)).get(pk=source.pk)
        definition = OriginationProductDefinition.objects.select_for_update().get(pk=definition.pk)
        if definition.lifecycle_status not in {'draft', 'published'} or locked.status not in {'active', 'ready', 'upload_failed'}:
            raise ValidationError('The product or document changed. Refresh before replacing the PDF.')
        attempt = locked.events.filter(action='pdf_replacement_reserved', metadata__request_id=request_id).first()
        if attempt:
            if attempt.metadata['sha256'] != digest:
                raise ValidationError('This retry contains a different PDF. Start a new replacement.')
            candidate = OriginationDocumentTemplate.objects.get(pk=attempt.metadata['target'])
        else:
            select_documents(definition=definition, templates=list(selected_documents(definition)), actor=actor,
                             request_id=f'{request_id}:retain-selection')
            schema, signers = template_form_contract(locked)
            latest = OriginationDocumentTemplate.objects.filter(document_type=source.document_type).order_by('-version').first()
            version = latest.version + 1
            config = initial_template_configuration(None, form_schema=schema)
            config.update(document_type=source.document_type, version=version)
            config['field_overlay_manifest']['fields'] = {}
            config['signature_overlay_manifest']['slots'] = {}
            candidate = OriginationDocumentTemplate.objects.create(
                document_type=source.document_type, version=version, name=source.name,
                document_key=source.document_key, document_role=source.document_role,
                inclusion_mode=source.inclusion_mode, officer_selectable=source.officer_selectable,
                default_selected=source.default_selected, display_order=source.display_order,
                applicability_rule=deepcopy(source.applicability_rule), form_schema=schema, signer_rules=signers,
                source_filename=pdf_file.name[:255], source_sha256=digest, source_byte_size=len(data), page_count=pages,
                status='upload_failed', placement_config=config, upload_error='PDF upload pending.', created_by=actor)
            for product_id in source.eligible_products.values_list('pk', flat=True):
                OriginationDocumentProductEligibility.objects.create(template=candidate, product_id=product_id, created_by=actor)
            OriginationDocumentTemplateEvent.objects.create(template=locked, action='pdf_replacement_reserved', actor=actor,
                metadata={'target': str(candidate.pk), 'sha256': digest, 'request_id': request_id})
        expected_state = maintenance_impact(definition)['token']
    if not candidate.drive_file_id or candidate.status == 'upload_failed':
        candidate = _upload_reserved_document(candidate, data=data, actor=actor)
    if candidate.status == 'upload_failed':
        return candidate
    with transaction.atomic():
        definition = OriginationProductDefinition.objects.select_for_update().get(pk=definition.pk)
        locked.refresh_from_db()
        if locked.status not in {'active', 'ready', 'upload_failed'}:
            raise ValidationError('The document changed during upload. The uploaded draft is retained; refresh before selecting it.')
        if maintenance_impact(definition)['token'] != expected_state:
            raise ValidationError('Settings changed during upload. The uploaded draft is retained; refresh before selecting it.')
        stage_change(definition=definition, action='edit', source=locked, target=candidate, actor=actor, request_id=request_id)
    return candidate


def shared_review(template):
    """Review token for direct catalogue publication, without requiring a product workspace."""
    sources = list(OriginationDocumentTemplate.objects.filter(document_type=template.document_type, status='active').exclude(pk=template.pk))
    product_ids = set(str(pk) for source in sources for pk in source.eligible_products.values_list('pk', flat=True))
    product_ids.update(str(pk) for pk in template.eligible_products.values_list('pk', flat=True))
    definitions = OriginationProductDefinition.objects.filter(product_version__product_id__in=product_ids, is_active=True)
    facts = [[str(item.pk), item.form_schema, item.signer_rules, item.approval_roles] for item in definitions.order_by('pk')]
    revision = template.configuration_revisions.order_by('-revision').first()
    facts += [[str(source.pk), sorted(str(pk) for pk in source.eligible_products.values_list('pk', flat=True))] for source in sources]
    facts += [[str(template.pk), template.source_sha256, template.form_schema, template.signer_rules,
               revision.configuration if revision else {}, sorted(str(pk) for pk in template.eligible_products.values_list('pk', flat=True))]]
    from core.models import Product
    return {'required': bool(sources), 'token': hashlib.sha256(json.dumps(facts, sort_keys=True, default=str).encode()).hexdigest(),
            'products': list(Product.objects.filter(pk__in=product_ids).order_by('name').values_list('name', flat=True))}


@transaction.atomic
def apply_changes(*, definition, actor, request_id, expected_impact, allow_unavailable=False):
    _require_authority(actor)
    definition = OriginationProductDefinition.objects.select_for_update().get(pk=definition.pk)
    if definition.events.filter(action='maintenance_applied', metadata__request_id=request_id).exists():
        return
    impact = maintenance_impact(definition)
    from origination.services.origination_setup import OriginationSetupConflict
    if expected_impact != impact['token']:
        raise OriginationSetupConflict(['documents'])
    if impact['unavailable'] and (definition.lifecycle_status != 'published' or not allow_unavailable):
        raise ValidationError('Confirm that removing the last Main LAF stops new applications.')
    changes = pending_changes(definition)
    # Publication and withdrawal share this transaction; failures keep current choices.
    publish_setup_documents(definition=definition, actor=actor, request_id=request_id)
    for change in changes:
        if change['action'] not in {'remove', 'replace'}:
            continue
        source = OriginationDocumentTemplate.objects.order_by().select_for_update(of=('self',)).get(pk=change['source'])
        # Remove current and inherited draft links for the same family/product.
        OriginationDocumentTemplateEvent.objects.create(template=source, action='product_withdrawn', actor=actor,
            metadata={'product_id': str(definition.product_version.product_id), 'request_id': request_id,
                      'replacement': change.get('target', '')})
        replacement = OriginationDocumentTemplate.objects.filter(pk=change.get('target')).first() if change.get('target') else None
        if replacement and replacement.document_type == source.document_type:
            continue
        OriginationDocumentProductEligibility.objects.filter(template__document_type=source.document_type,
            product_id=definition.product_version.product_id).delete()
    OriginationProductDefinitionEvent.objects.create(product_definition=definition, action='maintenance_applied', actor=actor,
        metadata={'request_id': request_id, 'changes': changes})


@transaction.atomic
def cancel_changes(*, definition, actor, request_id):
    _require_authority(actor)
    definition = OriginationProductDefinition.objects.select_for_update().get(pk=definition.pk)
    if definition.events.filter(action='maintenance_applied', metadata__request_id=request_id, metadata__cancelled=True).exists():
        return
    OriginationProductDefinitionEvent.objects.create(product_definition=definition, action='maintenance_applied', actor=actor,
        metadata={'request_id': request_id, 'cancelled': True, 'changes': pending_changes(definition)})
    select_documents(definition=definition, templates=list(OriginationDocumentTemplate.objects.filter(
        product_eligibilities__product_id=definition.product_version.product_id, status='active')),
        actor=actor, request_id=request_id)


@transaction.atomic
def select_documents(*, definition, templates, actor, request_id):
    """Connect explicit choices without modifying any published document bytes."""
    from origination.services.origination_document_catalogue import main_laf_contract, validate_catalogue_publication
    _require_authority(actor)
    definition = OriginationProductDefinition.objects.select_for_update().get(pk=definition.pk)
    if definition.lifecycle_status not in {definition.STATUS_DRAFT, definition.STATUS_PUBLISHED}:
        raise ValidationError('Retired products cannot change document availability.')
    template_ids = list(dict.fromkeys(item.pk for item in templates))
    locked = {
        item.pk: item for item in OriginationDocumentTemplate.objects.order_by('pk')
        .select_for_update(of=('self',)).filter(pk__in=template_ids)
        .select_related('published_configuration_revision')
    }
    if len(locked) != len(template_ids):
        raise ValidationError('A selected document is unavailable. Refresh the list.')
    resolved = [locked[pk] for pk in template_ids]
    requested_ids = [str(item.pk) for item in resolved]
    replay = definition.events.filter(action='setup_documents_selected', metadata__request_id=request_id).first()
    if replay:
        if replay.actor_id != actor.pk or replay.metadata.get('template_ids') != requested_ids:
            raise ValidationError('This request was already used for different document choices. Refresh and try again.')
        return resolved
    for template in resolved:
        if template.status not in {template.STATUS_ACTIVE, template.STATUS_READY}:
            raise ValidationError(f'{template.name}: this document changed. Refresh the list.')
        if template.status == template.STATUS_ACTIVE and (
            not template.published_configuration_revision_id or not template.published_configuration_revision.is_published
        ):
            raise ValidationError(f'{template.name}: publish its alignment in the Document editor first.')
        _eligibility, created = OriginationDocumentProductEligibility.objects.get_or_create(
            template=template, product_id=definition.product_version.product_id,
            defaults={'created_by': actor},
        )
        if created:
            # Product attachment changes the allowlist, never the published PDF
            # or its alignment. Copies are reserved for explicit editing actions.
            if template.status == template.STATUS_ACTIVE:
                try:
                    if template.document_role == template.ROLE_PRIMARY:
                        _schema, reasons = main_laf_contract(definition, template)
                        if reasons:
                            raise ValueError(' '.join(reasons))
                    validate_catalogue_publication(template)
                except ValueError as exc:
                    reason = str(exc).replace('The Main LAF is missing the canonical commercial field ', 'Add the field ')
                    for field in definition.form_schema.get('fields', []):
                        if field.get('key') and field.get('label'):
                            reason = reason.replace(str(field['key']), str(field['label']))
                    raise ValidationError(f'{template.name}: {reason}') from exc
            OriginationDocumentTemplateEvent.objects.create(
                template=template, action='setup_product_connected', actor=actor,
                metadata={'product_id': str(definition.product_version.product_id), 'request_id': request_id},
            )
    OriginationProductDefinitionEvent.objects.create(
        product_definition=definition, action='setup_documents_selected', actor=actor,
        metadata={'template_ids': requested_ids, 'request_id': request_id},
    )
    return resolved


@transaction.atomic
def _reserve_setup_document(*, definition, pdf_file, name, role, preset, actor, request_id):
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
    if preset == 'generic_jawabu_laf' and pages != 2:
        raise ValidationError('The reviewed Jawabu LAF preset requires a two-page PDF.')
    definition = OriginationProductDefinition.objects.select_for_update().get(pk=definition.pk)
    if definition.lifecycle_status not in {'draft', 'published'}:
        raise ValidationError('Retired products cannot add documents.')
    previous = definition.events.filter(action='setup_pdf_reserved', metadata__request_id=request_id).first()
    if previous:
        if previous.metadata['sha256'] != digest or previous.metadata['name'] != name or previous.metadata['role'] != role or previous.metadata.get('preset', '') != preset:
            raise ValidationError('This retry contains a different document. Start a new upload.')
        return OriginationDocumentTemplate.objects.get(pk=previous.metadata['template_id']), data
    select_documents(definition=definition, templates=list(selected_documents(definition)), actor=actor,
                     request_id=f'{request_id}:retain-selection')
    # A new upload is a new family. Replacing a family is an explicit version action.
    family = f'document-{uuid.uuid4().hex}'
    template = OriginationDocumentTemplate.objects.create(
        document_type=family, version=1, name=name,
        document_key='primary' if role == 'primary' else family,
        document_role=role, status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED,
        upload_error='PDF upload pending.',
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
    OriginationProductDefinitionEvent.objects.create(product_definition=definition, action='setup_pdf_reserved', actor=actor,
        metadata={'request_id':request_id, 'template_id':str(template.pk), 'sha256':digest, 'name':name, 'role':role, 'preset':preset})
    return template, data


def create_setup_document(*, definition, pdf_file, name, role, preset, actor, request_id=None):
    from origination.services.origination_templates import upload_template_record
    template, data = _reserve_setup_document(definition=definition, pdf_file=pdf_file, name=name,
        role=role, preset=preset, actor=actor, request_id=request_id or str(uuid.uuid4()))
    if template.drive_file_id and template.status != 'upload_failed':
        return template
    return _upload_reserved_document(template, data=data, actor=actor)


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
    if not mains and not (definition.lifecycle_status == definition.STATUS_PUBLISHED and pending_changes(definition)):
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
        field_manifest = config.get('field_overlay_manifest') or {}
        slot_manifest = config.get('signature_overlay_manifest') or {}
        if not isinstance(field_manifest, dict) or not isinstance(slot_manifest, dict):
            errors.append(f'{template.name}: review its saved alignment.')
            continue
        fields = field_manifest.get('fields') or {}
        slots = slot_manifest.get('slots') or {}
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
        if template.status == 'ready':
            from origination.services.origination_document_catalogue import validate_catalogue_publication
            original_revision = template.published_configuration_revision_id
            template.published_configuration_revision_id = revision.pk
            try:
                validate_catalogue_publication(template)
            except ValueError as exc:
                errors.append(f'{template.name}: {exc}')
            finally:
                template.published_configuration_revision_id = original_revision
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
        template = OriginationDocumentTemplate.objects.order_by().select_for_update(of=('self',)).get(pk=item.pk)
        if template.status == 'ready':
            reconcile_shared_eligibility(template)
        revision = (template.published_configuration_revision if template.status == template.STATUS_ACTIVE
                    else template.configuration_revisions.order_by('-revision').first())
        validate_template_configuration(revision.configuration, template=template, require_complete=True)
        if template.status == template.STATUS_ACTIVE:
            continue
        publish_product_template(template=template, revision=revision.revision,
                                 actor=actor, client_request_id=f'{request_id}:{template.pk}')
