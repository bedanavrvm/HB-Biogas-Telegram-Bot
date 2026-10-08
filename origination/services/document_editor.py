"""Independent document authoring; published contracts and applications stay immutable."""
from copy import deepcopy
import hashlib
import json
import math
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.contrib.auth import get_user_model

from origination.models import (OriginationDocumentTemplate, OriginationDocumentTemplateEvent,
    OriginationDocumentProductEligibility, OriginationTemplateConfigurationRevision)
from origination.services.origination_fields import template_form_contract, template_schema_revision


def require_editor(actor):
    if not getattr(actor, 'is_active', False) or not getattr(actor, 'is_superuser', False):
        raise PermissionDenied('Only an active Superuser may edit documents.')


def authoring_products():
    """Draft products can select documents without becoming operationally active."""
    from core.models import Product
    return Product.objects.filter(
        Q(active=True) | Q(versions__origination_definitions__lifecycle_status='draft')
    ).distinct()


def create_document(*, actor, request_id, source, name, role, products, pdf):
    from origination.services.origination_templates import validate_template_pdf, initial_template_configuration
    from origination.services.origination_setup_documents import _upload_reserved_document
    require_editor(actor)
    if not request_id:
        raise ValidationError('A create request key is required.')
    selection = [name, role, sorted(str(p.pk) for p in products), str(source.pk) if source else '']
    if source and pdf:
        raise ValidationError('Choose a copy or a new PDF, not both.')
    if source:
        document = copy_document(source=source, actor=actor, request_id=request_id)
        event = document.events.filter(action='editor_created').first()
        if event and event.metadata['selection'] != selection:
            raise ValidationError('This retry contains a different document selection.')
        # A matching replay after publication never mutates the live document.
        if document.status != 'ready':
            return document
    else:
        data = pdf.read()
        digest, pages = validate_template_pdf(data)
        with transaction.atomic():
            # Serialize creation through the actor row; request keys are actor scoped.
            get_user_model().objects.select_for_update().get(pk=actor.pk)
            event = OriginationDocumentTemplateEvent.objects.filter(action='editor_upload_reserved', actor=actor,
                metadata__request_id=request_id).first()
            if event:
                if event.metadata['digest'] != digest or event.metadata['selection'] != selection:
                    raise ValidationError('This retry contains a different document.')
                document = event.template
            else:
                family = 'document-'+uuid.uuid4().hex
                config = initial_template_configuration(None, form_schema={'fields':[]})
                config.update(document_type=family, version=1)
                document = OriginationDocumentTemplate.objects.create(name=name, document_type=family, version=1,
                    document_key='primary' if role == 'primary' else family, document_role=role,
                    form_schema={'fields':[],'sections':[]}, signer_rules=[], placement_config=config,
                    source_filename=pdf.name[:255], source_sha256=digest, source_byte_size=len(data), page_count=pages,
                    status='upload_failed', created_by=actor)
                document.events.create(action='editor_upload_reserved', actor=actor,
                    metadata={'request_id':request_id,'digest':digest,'selection':selection})
        if document.status == 'upload_failed':
            document = _upload_reserved_document(document, data=data, actor=actor)
    with transaction.atomic():
        document = OriginationDocumentTemplate.objects.order_by().select_for_update(of=('self',)).get(pk=document.pk)
        event = document.events.filter(action='editor_created').first()
        if event and event.metadata['selection'] != selection:
            raise ValidationError('This retry contains a different document selection.')
        if document.status == 'ready' and not event:
            document.name = name
            document.document_role = role
            document.document_key = 'primary' if role == 'primary' else document.document_type
            document.save(update_fields=['name','document_role','document_key','updated_at'])
            for product in products:
                OriginationDocumentProductEligibility.objects.get_or_create(template=document, product=product,
                    defaults={'created_by':actor})
            document.events.create(action='editor_created', actor=actor, metadata={'selection':selection})
    return document


def readiness(document):
    """Cheap server-owned tasks: no Drive download or render during autosave."""
    from origination.services.origination_templates import _expected_signature_slots
    from origination.services.loan_origination import validate_product_form_contract, OriginationError
    schema, signers = template_form_contract(document)
    latest = document.configuration_revisions.order_by('-revision').first()
    config = latest.configuration if latest else document.placement_config or {}
    if not isinstance(config, dict):
        config = {}
    field_manifest = config.get('field_overlay_manifest') or {}
    slot_manifest = config.get('signature_overlay_manifest') or {}
    fields = field_manifest.get('fields') if isinstance(field_manifest, dict) else None
    slots = slot_manifest.get('slots') if isinstance(slot_manifest, dict) else None
    malformed = not isinstance(fields, dict) or not isinstance(slots, dict)
    fields = fields if isinstance(fields, dict) else {}
    slots = slots if isinstance(slots, dict) else {}
    tasks = []
    def task(key, label, section, item=None):
        tasks.append({'key':key, 'label':label, 'section':section, **(item or {})})
    if malformed:
        task('layout', 'Review the saved layout', 'placement')
    if not document.drive_file_id or document.status == 'upload_failed':
        task('pdf', 'Upload the PDF', 'pdf')
    if not schema.get('fields'):
        task('fields', 'Add a field', 'fields')
    if document.document_role == 'primary' and not signers:
        task('signers', 'Add a signer', 'signers')
    mapped = {spec.get('context_key') for spec in fields.values() if isinstance(spec, dict)}
    for field in schema.get('fields', []):
        if field.get('required') and field.get('key') not in mapped:
            task('field:'+field['key'], 'Place: '+(field.get('label') or field['key']), 'placement',
                 {'kind':'field', 'item_key':field['key']})
    for key, spec in _expected_signature_slots(document.product_definition, document).items():
        if spec.get('required') and key not in slots:
            task('signature:'+key, 'Place: '+spec['label'], 'placement', {'kind':'signature', 'item_key':key})
    if schema.get('fields') and (signers or document.document_role != 'primary'):
        try:
            validate_product_form_contract(schema, signers, require_signers=document.document_role == 'primary')
        except OriginationError as exc:
            task('contract', str(exc), 'signers')
    if fields and not any(t['section'] == 'placement' for t in tasks):
        for key, spec in {**fields, **slots}.items():
            try:
                box = spec.get('allowed_area') or spec.get('box') or {}
                values = [float(box[name]) for name in ['x','y','width','height']]
                if not all(math.isfinite(value) for value in values) or min(values[:2]) < 0 or min(values[2:]) <= 0 or not 1 <= int(spec.get('page_number',0)) <= document.page_count:
                    raise ValueError
            except (ValueError, TypeError, KeyError, AttributeError):
                task('geometry:'+key, 'Review the placement for '+key.replace('_',' '), 'placement')
    if not fields and schema.get('fields') and not any(item['section'] == 'placement' for item in tasks):
        task('placement', 'Place a field on the PDF', 'placement')
    if latest and not tasks:
        from origination.services.origination_document_catalogue import validate_catalogue_publication
        original = document.published_configuration_revision_id
        document.published_configuration_revision_id = latest.pk
        try:
            validate_catalogue_publication(document)
            from origination.models import OriginationProductDefinition
            from origination.services.origination_document_catalogue import main_laf_contract
            if document.document_role == 'primary':
                for definition in OriginationProductDefinition.objects.filter(
                        lifecycle_status='draft', product_version__product__in=document.eligible_products.all()):
                    _schema, reasons = main_laf_contract(definition, document, require_active=False)
                    for index, reason in enumerate(reasons):
                        task(f'product:{definition.pk}:{index}', definition.name+': '+reason, 'fields')
        except ValueError as exc:
            task('compatibility', str(exc), 'fields')
        finally:
            document.published_configuration_revision_id = original
    return {'tasks':tasks, 'outstanding_count':len(tasks), 'can_publish':not tasks,
            'revision':latest.revision if latest else 0, 'schema_revision':template_schema_revision(document),
            'signers':signers, 'form_schema':schema}


@transaction.atomic
def save_signers(*, document, rules, actor, schema_revision, revision, configuration, request_id, details=None, field_pack=''):
    from origination.services.loan_origination import SIGNER_ROLE_CATALOG
    from origination.services.origination_fields import create_data_field, _field_schema_item, semantic_field_conflict
    from origination.services.origination_templates import save_calibration_draft
    require_editor(actor)
    document = OriginationDocumentTemplate.objects.order_by().select_for_update(of=('self',)).get(pk=document.pk)
    if document.status != 'ready' or document.product_definition_id:
        raise ValidationError('Open an editable document before changing signers.')
    digest = hashlib.sha256(json.dumps([rules, configuration, details, field_pack], sort_keys=True).encode()).hexdigest()
    if not request_id:
        raise ValidationError('A save request key is required.')
    if not isinstance(configuration, dict):
        raise ValidationError('The document layout is missing. Reload before saving.')
    if field_pack not in {'', 'lending'}:
        raise ValidationError('Choose an available field pack.')
    replay = document.events.filter(action='editor_signers_saved', metadata__request_id=request_id).first()
    if replay:
        if replay.metadata['digest'] != digest or replay.actor_id != actor.pk:
            raise ValidationError('This retry contains different signer changes.')
        return document
    if template_schema_revision(document) != schema_revision:
        raise ValidationError('Signers or fields changed in another tab. Your changes are still here; reload before saving.')
    if details is not None:
        from core.models import Product
        if not isinstance(details, dict) or not str(details.get('name','')).strip() or len(str(details['name'])) > 180:
            raise ValidationError('Enter a document name of up to 180 characters.')
        product_ids = details.get('products')
        if not isinstance(product_ids, list):
            raise ValidationError('Choose the products that use this document.')
        products = list(authoring_products().filter(pk__in=product_ids))
        if {str(p.pk) for p in products} != set(product_ids):
            raise ValidationError('Choose available or draft products.')
        copy_event = document.events.filter(action='editor_copy_source', metadata__replace=True).first()
        if copy_event and set(product_ids) != {copy_event.metadata['product_id']}:
            raise ValidationError('This copy is for one product only. Make a separate copy for other products.')
        document.name = details['name'].strip()
        document.product_eligibilities.exclude(product_id__in=product_ids).delete()
        for product in products:
            document.product_eligibilities.get_or_create(product=product, defaults={'created_by':actor})
        source = OriginationDocumentTemplate.objects.filter(document_type=document.document_type, status='active').exclude(pk=document.pk).first()
        document.events.create(action='editor_products_selected', actor=actor, metadata={'product_ids':product_ids,
            'source_ids':sorted(str(pk) for pk in source.eligible_products.values_list('pk',flat=True)) if source else []})
    known = dict(SIGNER_ROLE_CATALOG)
    if not isinstance(rules, list) or len(rules) > len(known):
        raise ValidationError('Choose valid signer roles.')
    seen = set()
    schema = deepcopy(document.form_schema or {'fields':[], 'sections':[]})
    schema.setdefault('fields', [])
    if not schema.get('sections'):
        schema['sections'] = [{'key':'applicant', 'label':'Applicant'}]
    normalized = []
    staff = {'officer','loan_officer','bro_1','bro_2','credit_analyst','branch_manager','management_approver'}
    for raw in rules:
        role = raw.get('role') if isinstance(raw, dict) else None
        if role not in known or role in seen:
            raise ValidationError('Each signer role must be valid and appear once.')
        seen.add(role)
        rule = deepcopy(raw)
        if not isinstance(rule.get('required', True), bool):
            raise ValidationError('Choose whether each signer is required.')
        rule.setdefault('required', True)
        rule['label'] = str(rule.get('label') or known[role])[:120]
        rule['slots'] = rule.get('slots') or [{'key':'signature','type':'signature','required':bool(rule.get('required', True)),
                                             'label':rule['label']+' signature'}]
        slot_keys = set()
        for slot in rule['slots']:
            if not isinstance(slot, dict) or not slot.get('key') or slot['key'] in slot_keys or slot.get('type', 'signature') not in {'signature','stamp','date_signed'}:
                raise ValidationError('Each signer needs distinct valid signing fields.')
            slot_keys.add(slot['key'])
        if role not in staff:
            identity = rule.setdefault('identity_fields', {})
            for kind, field_type in [('name','text'),('phone','phone'),('national_id','national_id')]:
                key = identity.get(kind) or f'{role}_{kind}'
                if not any(f.get('key') == key for f in schema['fields']):
                    label = rule['label']+' '+kind.replace('_',' ')
                    equivalent = semantic_field_conflict(key=key, label=label, aliases=[])
                    if equivalent and equivalent.data_type == field_type:
                        field = equivalent
                    else:
                        field, _ = create_data_field(payload={'key':key, 'label':label,
                            'type':field_type}, actor=actor)
                    key = field.key
                    if any(f.get('key') == key for f in schema['fields']):
                        identity[kind] = key
                        continue
                    schema['fields'].append(_field_schema_item(field, {'required':bool(rule.get('required', True)),
                        'section_key':schema['sections'][0]['key']}))
                identity[kind] = key
        normalized.append(rule)
    # Removing a signer removes only that signer's placements, never global fields.
    config = deepcopy(configuration)
    manifest = config.setdefault('signature_overlay_manifest', {}).setdefault('slots', {})
    allowed = {r['role']+'.'+s['key'] for r in normalized for s in r['slots']}
    for key in list(manifest):
        if key not in allowed:
            manifest.pop(key)
    if field_pack == 'lending':
        from origination.services.origination_commercial_terms import ensure_commercial_catalogue, merge_commercial_contract
        schema = merge_commercial_contract(schema, fields=ensure_commercial_catalogue(actor=actor))
    schema['_revision'] = schema_revision + 1
    document.form_schema, document.signer_rules = schema, normalized
    document.save(update_fields=['name','form_schema','signer_rules','updated_at'])
    save_calibration_draft(template=document, configuration=config, actor=actor, expected_revision=revision,
                           client_request_id=request_id+':placement')
    document.events.create(action='editor_signers_saved', actor=actor,
        metadata={'request_id':request_id,'digest':digest,'roles':sorted(seen),'field_pack':field_pack})
    return document


@transaction.atomic
def copy_document(*, source, actor, request_id, product_id=None, replace=False):
    require_editor(actor)
    source = OriginationDocumentTemplate.objects.order_by().select_for_update(of=('self',)).get(pk=source.pk)
    if not request_id:
        raise ValidationError('A copy request key is required.')
    fingerprint = [str(product_id or ''), bool(replace)]
    event = source.events.filter(action='editor_document_copied', metadata__request_id=request_id).first()
    if event:
        if event.metadata['selection'] != fingerprint or event.actor_id != actor.pk:
            raise ValidationError('This retry contains a different copy selection.')
        return OriginationDocumentTemplate.objects.get(pk=event.metadata['target'])
    from core.models import Product
    if product_id and not authoring_products().filter(pk=product_id).exists():
        raise ValidationError('Choose an available or draft product.')
    if replace and not source.eligible_products.filter(pk=product_id).exists():
        raise ValidationError('This document is not used by the selected product.')
    if source.status not in {'ready', 'active'}:
        raise ValidationError('Choose an available document to copy.')
    schema, rules = template_form_contract(source)
    latest = source.published_configuration_revision or source.configuration_revisions.order_by('-revision').first()
    config = deepcopy(latest.configuration if latest else source.placement_config)
    family = 'document-'+uuid.uuid4().hex
    config.update(document_type=family, version=1)
    values = {key:deepcopy(getattr(source,key)) for key in ['document_role','inclusion_mode','display_order',
        'officer_selectable','default_selected','applicability_rule','source_filename','source_sha256','source_byte_size',
        'page_count','drive_file_id','drive_url','native_consent_attestation_reference']}
    document = OriginationDocumentTemplate.objects.create(**values, document_type=family, version=1,
        document_key='primary' if source.document_role == 'primary' else family,
        name=source.name[:173]+' (copy)', status='ready', form_schema=schema, signer_rules=rules,
        native_consent_policy=source.native_consent_policy, native_consent_attested_by=source.native_consent_attested_by,
        native_consent_attested_at=source.native_consent_attested_at, placement_config=config, created_by=actor)
    OriginationTemplateConfigurationRevision.objects.create(template=document, revision=1, configuration=config, created_by=actor)
    if product_id:
        OriginationDocumentProductEligibility.objects.create(template=document, product_id=product_id, created_by=actor)
    document.events.create(action='editor_copy_source', actor=actor, metadata={'source':str(source.pk),
        'product_id':str(product_id or ''), 'replace':bool(replace)})
    source.events.create(action='editor_document_copied', actor=actor,
        metadata={'request_id':request_id,'target':str(document.pk),'selection':fingerprint})
    return document


@transaction.atomic
def publish_document(*, document, actor, revision, request_id, impact_token):
    from origination.services.origination_templates import publish_product_template
    from origination.services.origination_setup_documents import shared_review
    require_editor(actor)
    # Lock the entire family in a stable order, including a product-only copy's
    # source. Two first publications must not lock sibling drafts in reverse.
    copy_event = document.events.filter(action='editor_copy_source').first()
    source_ids = [copy_event.metadata['source']] if copy_event and copy_event.metadata.get('replace') else []
    family_filter = Q(document_type=document.document_type) | Q(pk__in=source_ids)
    candidates = list(OriginationDocumentTemplate.objects.filter(family_filter))
    initial_products = {pk for item in candidates for pk in item.eligible_products.values_list('pk', flat=True)}
    # Lock concrete rows only: nullable joins cannot be locked on PostgreSQL.
    from origination.models import OriginationProductDefinition, OriginationProductDefinitionEvent
    from core.models import Product
    # Product saves lock their definition before touching documents. Follow that
    # order here too; no-key product locks permit eligibility FK inserts.
    definitions = list(OriginationProductDefinition.objects.order_by('pk').select_for_update(of=('self',))
                       .filter(product_version__product_id__in=initial_products))
    list(Product.objects.order_by('pk').select_for_update(of=('self',), no_key=True).filter(pk__in=initial_products))
    family = list(OriginationDocumentTemplate.objects.order_by('pk').select_for_update(of=('self',)).filter(family_filter))
    document = next(item for item in family if item.pk == document.pk)
    current_products = {pk for item in family for pk in item.eligible_products.values_list('pk', flat=True)}
    if current_products != initial_products:
        raise ValidationError('The products using this document changed. Review them again before publishing.')
    previous = [item for item in family if item.document_type == document.document_type
                and item.status == 'active' and item.pk != document.pk]
    digest = hashlib.sha256(json.dumps([revision, impact_token]).encode()).hexdigest()
    replay = document.events.filter(action='editor_published', metadata__request_id=request_id).first()
    if replay:
        if replay.metadata['digest'] != digest or replay.actor_id != actor.pk:
            raise ValidationError('This retry contains a different publish request.')
        return document
    if not request_id:
        raise ValidationError('A publish request key is required.')
    latest = document.configuration_revisions.order_by('-revision').first()
    if not latest or latest.revision != revision:
        raise ValidationError('The document changed. Review its latest saved changes before publishing.')
    review = shared_review(document)
    if review['required'] and review['token'] != impact_token:
        raise ValidationError('The affected products changed. Review them again before publishing.')
    if copy_event and copy_event.metadata.get('replace'):
        source = next(item for item in family if str(item.pk) == copy_event.metadata['source'])
        product_id = copy_event.metadata['product_id']
        if not source.product_eligibilities.filter(product_id=product_id).exists():
            raise ValidationError('This product no longer uses the original document. Review the copy before publishing.')
    publish_product_template(template=document, revision=revision, actor=actor,
        client_request_id=request_id, expected_shared_impact=impact_token)
    if copy_event and copy_event.metadata.get('replace'):
        source.product_eligibilities.filter(product_id=product_id).delete()
        source.events.create(action='product_withdrawn', actor=actor,
            metadata={'product_id':product_id,'replacement':str(document.pk),'request_id':request_id})
    # Refresh draft selection intent, never application snapshots or signed packets.
    for definition in definitions:
        if definition.lifecycle_status != 'draft':
            continue
        old_ids = {str(item.pk) for item in previous}
        if copy_event and copy_event.metadata.get('replace'):
            old_ids.add(copy_event.metadata['source'])
        selected = definition.events.filter(action='setup_documents_selected').order_by('-occurred_at','-pk').first()
        if selected and old_ids.intersection(selected.metadata.get('template_ids', [])):
            ids = [str(document.pk) if item in old_ids else item for item in selected.metadata['template_ids']]
            OriginationProductDefinitionEvent.objects.create(product_definition=definition,
                action='setup_documents_selected', actor=actor,
                metadata={'template_ids':list(dict.fromkeys(ids)), 'request_id':request_id+':document-published'})
    document.events.create(action='editor_published', actor=actor, metadata={'request_id':request_id,'digest':digest})
    document.refresh_from_db()
    return document
