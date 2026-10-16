"""Draft-owned document choices; existing contracts never follow catalogue upgrades."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

from origination.models import OriginationApplicationDocument, OriginationDocumentTemplate


def _mapped(schema, configuration, application):
    from origination.services.origination_value_contracts import enabled, schema_with_mapped_values
    if not enabled(schema):
        return schema
    return schema_with_mapped_values(schema, configuration,
        captured_system=(application.schema_snapshot or {}).get('system_fields', []))


def _supporting_candidates(application):
    if not application.product_version_id:
        return []
    return list(OriginationDocumentTemplate.objects.filter(
        status='active', document_role='supporting', published_configuration_revision__isnull=False,
        product_eligibilities__product_id=application.product_version.product_id,
    ).select_related('published_configuration_revision').distinct().order_by('display_order', 'name', '-version'))


def document_choices(application):
    from origination.services.loan_origination import OriginationError
    from origination.services.origination_document_catalogue import catalogue_for_product, catalogue_revision, main_laf_contract, validate_snapshot_combination
    from origination.services.origination_fields import template_form_contract
    documents = list(application.packet_documents.all())
    primary = next((row for row in documents if row.document_role == 'primary' and row.selected), None)
    primary_id = str(primary.template_id) if primary and primary.template_id else 'captured:primary'
    primary_schema = _mapped(application.schema_snapshot, application.template_configuration_snapshot, application)
    mains = [{'id': primary_id, 'key': 'primary', 'name': primary.name if primary else 'Current Main LAF',
              'version': (primary.template_snapshot or {}).get('version') if primary else None,
              'selected': True, 'available': True}]
    schemas = {primary_id: primary_schema}
    catalogue = catalogue_for_product(application.product_definition) if application.product_version_id else {}
    main_rows = {str(row.pk): row for row in OriginationDocumentTemplate.objects.filter(
        pk__in=[item['id'] for item in catalogue.get('main_lafs', [])],
    ).select_related('published_configuration_revision', 'product_definition')}
    for item in catalogue.get('main_lafs', []):
        if item['id'] == primary_id:
            continue
        template = main_rows[item['id']]
        schema, _reasons = main_laf_contract(application.product_definition, template)
        schemas[item['id']] = _mapped(schema, template.published_configuration_revision.configuration, application)
        mains.append({**item, 'selected': False, 'available': True})
    supports = []
    support_schemas = {}
    captured_keys = set()
    candidates = _supporting_candidates(application)
    active_support_ids = {str(row.pk) for row in candidates}
    for row in documents:
        if row.document_role == 'primary':
            continue
        captured_keys.add(row.document_key)
        identity = str(row.template_id) if row.template_id else f'captured:{row.document_key}'
        supports.append({'id': identity, 'key': row.document_key, 'name': row.name,
            'version': (row.template_snapshot or {}).get('version'), 'selected': row.selected,
            'required': row.inclusion_mode != 'optional', 'available': row.applicable,
            'reason': '' if row.applicable else 'Not applicable to this application.', 'captured': True,
            'restart_available': identity in active_support_ids})
        support_schemas[identity] = _mapped(row.schema_snapshot,
            (row.template_snapshot or {}).get('configuration', {}), application)
    counts = Counter(row.document_key for row in candidates)
    for template in candidates:
        if template.document_key in captured_keys:
            continue
        identity = str(template.pk)
        duplicate = counts[template.document_key] > 1
        supports.append({'id': identity, 'key': template.document_key, 'name': template.name,
            'version': template.version, 'selected': False, 'required': False, 'available': not duplicate,
            'reason': 'More than one published document uses this name; ask an administrator to correct the document choices.' if duplicate else '',
            'captured': False, 'restart_available': not duplicate})
        support_schemas[identity] = _mapped(template_form_contract(template)[0],
            template.published_configuration_revision.configuration, application)
    for item in supports:
        compatible = []
        for main_id, schema in schemas.items():
            if main_id != primary_id and not item['restart_available']:
                continue
            try:
                validate_snapshot_combination(schema, [support_schemas[item['id']]])
            except (OriginationError, ValueError):
                continue
            compatible.append(main_id)
        item['compatible_main_ids'] = compatible
    return {'primary_template_id': primary_id, 'catalogue_revision': catalogue_revision(),
            'revision': application.revision, 'main_lafs': mains, 'supporting_documents': supports}


def attach_requested_documents(application, template_ids, expected_catalogue_revision):
    """Called under the application's transaction/lock; return stable document keys."""
    from origination.services.loan_origination import OriginationConflict, OriginationError
    from origination.services.origination_document_catalogue import catalogue_revision
    from origination.services.origination_documents import _template_snapshot
    from origination.services.origination_fields import template_form_contract
    choices = document_choices(application)
    if not expected_catalogue_revision or expected_catalogue_revision != choices['catalogue_revision']:
        raise OriginationConflict('The document choices changed. Refresh the list and try again.')
    by_id = {item['id']: item for item in choices['supporting_documents']}
    if any(identity not in by_id for identity in template_ids):
        raise OriginationError('One or more supporting documents are unavailable for this application.')
    keys = []
    added = []
    for identity in template_ids:
        item = by_id[identity]
        if not item['available'] or choices['primary_template_id'] not in item['compatible_main_ids']:
            raise OriginationError(f'{item["name"]} is not compatible with the current Main LAF.')
        keys.append(item['key'])
        if item['captured']:
            continue
        template = OriginationDocumentTemplate.objects.select_for_update(of=('self',)).select_related(
            'published_configuration_revision',
        ).get(pk=identity)
        schema, signers = template_form_contract(template)
        OriginationApplicationDocument.objects.create(application=application, template=template,
            document_key=template.document_key, name=template.name, document_role='supporting',
            display_order=template.display_order, inclusion_mode='optional', selection_source='officer',
            applicable=True, selected=False, template_snapshot={**_template_snapshot(template),
                'catalogue_revision': choices['catalogue_revision'], 'resolved_template_id': identity},
            schema_snapshot=schema, signer_rules_snapshot=signers)
        added.append(identity)
    if catalogue_revision() != expected_catalogue_revision:
        raise OriginationConflict('The document choices changed. Refresh the list and try again.')
    application._prefetched_objects_cache = {}
    return keys, added


def reconcile_document_requirements(application):
    """Keep commercial values fixed; only document-contributed evidence changes."""
    from core.services.product_catalog import serialize_product_version
    terms = deepcopy(application.product_terms_snapshot or {})
    base = terms.get('_document_requirements_base')
    if base is None:
        # Governed product versions are immutable. Older catalogue applications
        # merged document evidence without recording which rows it contributed.
        base = (serialize_product_version(application.product_version).get('requirements', [])
                if application.product_version_id else terms.get('requirements', []))
    requirements = {str(item['key']): deepcopy(item) for item in base if isinstance(item, dict) and item.get('key')}
    for document in application.packet_documents.all():
        if document.selected and document.applicable:
            for item in (document.schema_snapshot or {}).get('evidence_requirements', []) or []:
                if isinstance(item, dict) and item.get('key'):
                    requirements.setdefault(str(item['key']), deepcopy(item))
    terms['_document_requirements_base'] = deepcopy(base)
    terms['requirements'] = list(requirements.values())
    application.product_terms_snapshot = terms
    application.save(update_fields=['product_terms_snapshot', 'updated_at'])
