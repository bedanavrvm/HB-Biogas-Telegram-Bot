"""Origination owns its checklist; ProductVersion owns shared financial policy."""
from copy import deepcopy
from types import SimpleNamespace

from django.core.exceptions import ValidationError

from core.models import ProductCustomAttribute, ProductRequirement


def validate_configuration(configuration):
    if not isinstance(configuration, dict):
        raise ValidationError('Origination requirements must be an object.')
    for name, model, type_name in (
        ('requirements', ProductRequirement, 'requirement_type'),
        ('custom_attributes', ProductCustomAttribute, 'attribute_type'),
    ):
        items = configuration.get(name, [])
        if not isinstance(items, list) or len(items) > 200:
            raise ValidationError('Use at most 200 ' + name.replace('_', ' ') + '.')
        keys = set()
        for item in items:
            if not isinstance(item, dict) or not item.get('key') or item['key'] in keys:
                raise ValidationError('Each Origination requirement or attribute needs a distinct key.')
            keys.add(item['key'])
            values = {'key': item['key'], 'label': item.get('label', ''), type_name: item.get('type', ''),
                      'required': item.get('required', False), 'validation_config': item.get('validation') or {}}
            if name == 'requirements':
                values.update(description=item.get('description', ''),
                              workflow='loan_origination', enforcement_stage=item.get('enforcement_stage', ''))
            else:
                values.update(options=item.get('options') or [], default_value=item.get('default'),
                              help_text=item.get('help_text', ''), workflow_visibility=['loan_origination'])
            model(**values).full_clean(exclude=['product_version'], validate_unique=False, validate_constraints=False)


def apply_configuration(terms, definition):
    result = deepcopy(terms)
    configuration = definition.workflow_configuration or {}
    result['requirements'] = deepcopy([item for item in configuration.get('requirements', []) if item.get('active', True)])
    result['custom_attributes'] = deepcopy(configuration.get('custom_attributes', []))
    result['_origination_configuration_version'] = 1
    result['_document_requirements_base'] = deepcopy(result['requirements'])
    return result


def validate_snapshot_custom_values(terms, values):
    from core.services.product_catalog import validate_custom_values
    attributes = [SimpleNamespace(key=item['key'], label=item['label'], attribute_type=item['type'],
        required=item.get('required', False), default_value=item.get('default'),
        validation_config=item.get('validation') or {}, options=item.get('options') or [],
        workflow_visibility=['loan_origination']) for item in terms.get('custom_attributes', [])]
    version = SimpleNamespace(custom_attributes=SimpleNamespace(all=lambda: attributes))
    return validate_custom_values(version, values, workflow='loan_origination')
