"""Read-only model relationship inventory for reporting governance.

The reporting engine does not consume this graph as a dynamic join planner.
It documents the model topology so a new report source cannot quietly turn a
phone/name match into an unsafe cross-workflow customer join.
"""
from __future__ import annotations

from typing import Any

from django.apps import apps


PORTAL_ROOT_LABEL = 'core.JawabuFarmerMaster'
IDENTITY_ONLY_MODELS = {
    # Complaint Cases are connected to their own Telegram/message lineage, not
    # to the Portal customer record through a canonical FK.
    'core.CaseUpdate',
    'core.ComplaintCaseEvidence',
    'core.TatTrackerCase',
    'core.SpinCreditRequest',
    'core.ParsedMessage',
    'core.ProcessedMessage',
    'core.RawMessage',
}


def _classification(model_label: str, *, relation, reverse: bool) -> str:
    if model_label in IDENTITY_ONLY_MODELS:
        return 'unlinked_identity_only'
    if reverse or relation.many_to_many or relation.one_to_many:
        return 'aggregate_only'
    return 'safe_direct'


def relationship_inventory() -> list[dict[str, Any]]:
    """Return every installed core relation without querying customer data."""
    inventory: list[dict[str, Any]] = []
    for model in sorted(apps.get_app_config('core').get_models(), key=lambda item: item._meta.label):
        relations = []
        for field in model._meta.get_fields():
            if not field.is_relation:
                continue
            related = field.related_model
            if not related or getattr(related._meta, 'app_label', '') != 'core':
                continue
            reverse = bool(field.auto_created and not field.concrete)
            accessor = field.get_accessor_name() if reverse else field.name
            if not accessor or accessor == '+':
                continue
            relations.append({
                'name': accessor,
                'target': related._meta.label,
                'direction': 'reverse' if reverse else 'forward',
                'cardinality': 'many' if field.many_to_many or field.one_to_many else 'one',
                'classification': _classification(model._meta.label, relation=field, reverse=reverse),
            })
        inventory.append({
            'model': model._meta.label,
            'reporting_status': 'identity_only' if model._meta.label in IDENTITY_ONLY_MODELS else 'unclassified',
            'relations': sorted(relations, key=lambda item: (item['target'], item['name'])),
        })
    return inventory


def portal_relationship_summary() -> dict[str, Any]:
    """Describe the only v1 report graph, without making joins executable."""
    root = apps.get_model(PORTAL_ROOT_LABEL)
    safe_direct = []
    aggregate_only = []
    for field in root._meta.get_fields():
        if not field.is_relation or not field.related_model:
            continue
        reverse = bool(field.auto_created and not field.concrete)
        target = field.related_model._meta.label
        name = field.get_accessor_name() if reverse else field.name
        if not name or name == '+':
            continue
        item = {'name': name, 'target': target}
        (aggregate_only if reverse or field.many_to_many or field.one_to_many else safe_direct).append(item)
    return {
        'root': PORTAL_ROOT_LABEL,
        'safe_direct': sorted(safe_direct, key=lambda item: item['name']),
        'aggregate_only': sorted(aggregate_only, key=lambda item: item['name']),
        'unlinked_identity_only': sorted(IDENTITY_ONLY_MODELS),
        'rule': 'Only catalogue-defined Portal fields and named aggregate projections are reportable in v1.',
    }
