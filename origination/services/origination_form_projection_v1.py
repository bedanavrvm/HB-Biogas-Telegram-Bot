"""Preserve the captured projection of already-submitted version-1 packets."""
from copy import deepcopy
from typing import Any

from origination.services.origination_value_contracts import (
    PERSON_LINKS_KEY, TOTAL_KEYS, TOTAL_INPUTS, _fields, enabled,
    form_projection_enabled, placed_field_keys, person_fields, schema_with_mapped_values,
)


def essential_field_reasons(schema: dict, signer_rules=(), *, primary=True, quote_keys=()) -> dict[str, str]:
    from origination.services.loan_origination import _applicant_identity_field_keys
    from origination.services.origination_commercial_terms import (
        COMMERCIAL_KEYS, COMMERCIAL_INPUT_KEYS, commercial_contract_enabled, commercial_contract_version,
    )
    reasons = {}
    if primary:
        reasons.update({key: 'applicant' for keys in _applicant_identity_field_keys(schema, signer_rules).values() for key in keys})
    for rule in signer_rules or []:
        reasons.update({str(key): 'signing' for key in (rule.get('identity_fields') or {}).values() if key and key not in reasons})
    if primary:
        lending = (COMMERCIAL_KEYS if commercial_contract_version(schema) < 2 else COMMERCIAL_INPUT_KEYS) if commercial_contract_enabled(schema) else quote_keys
        reasons.update({key: 'lending' for key in lending if key not in reasons})
    return reasons




def rule_field_keys(rule: Any) -> set[str]:
    if not isinstance(rule, dict):
        return set()
    return ({str(rule['field'])} if rule.get('field') else set()) | {
        key for group in ('all', 'any') for child in rule.get(group, []) for key in rule_field_keys(child)
    }


def project_document_schema(schema: dict, configuration: dict, *, signer_rules=(), primary=True,
                            quote_keys=(), captured_system=None, dependency_keys=()) -> dict:
    """Pure active-field projection; stored contracts and answers are never edited."""
    result = schema_with_mapped_values(schema, configuration, captured_system=captured_system) if enabled(schema) else deepcopy(schema)
    placed = placed_field_keys(configuration)
    reasons = essential_field_reasons(result, signer_rules, primary=primary, quote_keys=quote_keys)
    reasons.update({key: 'dependency' for key in dependency_keys if key not in reasons})
    known = {item['key']: item for item in _fields(result)}
    active = placed | set(reasons)
    pending, visited = list(active), set()
    while pending:
        key = pending.pop()
        if key in visited:
            continue
        visited.add(key)
        binding = (known.get(key, {}).get('value_contract') or {}).get('binding', '')
        if not binding and key in TOTAL_KEYS and known.get(key, {}).get('source_type') == 'system':
            binding = 'total.' + key
        if binding.startswith('total.'):
            for dependency in TOTAL_INPUTS.get(binding[6:], ()):
                reasons.setdefault(dependency, 'calculation')
                active.add(dependency)
                pending.append(dependency)
        field = known.get(key, {})
        for dependency in rule_field_keys((field.get('validation') or {}).get('required_when')):
            reasons.setdefault(dependency, 'dependency')
            active.add(dependency)
            pending.append(dependency)
        parent = (field.get('validation') or {}).get('parent_field')
        if parent in known:
            reasons.setdefault(parent, 'dependency')
            active.add(parent)
            pending.append(parent)
    lending_section = result.get('commercial_section_key') or next((field.get('section_key') for key, field in known.items()
        if reasons.get(key) == 'lending' and field.get('section_key')), 'commercial_terms')
    groups = {'applicant': ('applicant', 'Applicant'), 'signing': ('signing_details', 'Signing details'),
              'lending': (lending_section, 'Lending details')}
    sections = result.setdefault('sections', [])
    existing = {item['key']: item for item in sections}
    fields = []
    for key, field in known.items():
        if key not in active:
            continue
        field['form_visibility'] = 'placed' if key in placed else reasons[key]
        if field.get('source_type') == 'system' or (field.get('value_contract') or {}).get('source', 'entered') != 'entered':
            field['editable'] = False
        if key not in placed and reasons[key] in groups:
            section, label = groups[reasons[key]]
            field['section_key'] = section
            if section not in existing:
                existing[section] = {'key': section, 'label': label}
                sections.append(existing[section])
        else:
            section = field.get('section_key') or (sections[0]['key'] if sections else 'document_details')
            field['section_key'] = section
            if section not in existing:
                existing[section] = {'key': section, 'label': 'Document details'}
                sections.append(existing[section])
        fields.append(field)
    result['fields'] = fields
    used = {field['section_key'] for field in fields if (field.get('value_contract') or {}).get('source', 'entered') == 'entered'
            and field.get('source_type') != 'system'}
    result['sections'] = [item for item in sections if item['key'] in used]
    return result


def application_document_schema(application: Any, document=None) -> dict:
    primary = document is None or document.document_role == 'primary'
    schema = application.schema_snapshot if document is None else document.schema_snapshot
    configuration = application.template_configuration_snapshot if document is None else (document.template_snapshot or {}).get('configuration', {})
    if not form_projection_enabled(application):
        return deepcopy(schema or {})
    terms = application.product_terms_snapshot or {}
    dependencies = set()
    if enabled(application.schema_snapshot) and getattr(application, 'form_payload', {}).get(PERSON_LINKS_KEY):
        documents = [(application.schema_snapshot, application.template_configuration_snapshot, application.signer_rules_snapshot, True)]
        documents += [(item.schema_snapshot, (item.template_snapshot or {}).get('configuration', {}), item.signer_rules_snapshot, False)
                      for item in application.packet_documents.all() if item.selected and getattr(item, 'applicable', True) and item.document_role != 'primary']
        shared = {field['key']: field for raw, _config, _rules, _primary in documents for field in _fields(raw)
                  if (field.get('value_contract') or {}).get('scope') == 'application'
                  and (field.get('value_contract') or {}).get('source') == 'entered'}
        roles = person_fields({'fields': shared})
        active = set().union(*(placed_field_keys(config) | set(essential_field_reasons(raw, rules, primary=is_primary))
                               for raw, config, rules, is_primary in documents))
        for target, source in application.form_payload[PERSON_LINKS_KEY].items():
            if active.intersection(roles.get(target, {}).values()):
                dependencies.update(roles.get(target, {}).values())
                dependencies.update(roles.get(source, {}).values())
    if primary:
        for requirement in terms.get('requirements', []):
            dependencies.update(rule_field_keys((requirement.get('validation') or {}).get('required_when')))
        for item in application.packet_documents.all():
            dependencies.update(rule_field_keys((item.template_snapshot or {}).get('applicability_rule')))
    signers = getattr(application if document is None else document, 'signer_rules_snapshot', [])
    if getattr(application, 'signing_policy_snapshot', '') == 'all_required' and getattr(application, 'signing_plan', {}).get('participants'):
        keys = set(application.signing_participants.filter(pk__in=application.signing_plan['participants']).values_list('participant_key', flat=True))
        signers = [rule for rule in signers if (rule.get('participant_key') or rule.get('role')) in keys]
    return project_document_schema(schema or {}, configuration or {},
        signer_rules=signers, primary=primary, dependency_keys=dependencies,
        quote_keys=[terms.get(key) for key in ('quote_amount_field_key', 'quote_tenor_field_key') if terms.get(key)],
        captured_system=(application.schema_snapshot or {}).get('system_fields', []))


