"""Deterministic database catalogue and relationship documentation.

The Django model graph is authoritative for physical identity and relations.
This module adds the business meaning PostgreSQL cannot infer: domain,
lifecycle, retention, source-of-truth status, and repository usage locations.
It never reads customer row values.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re
from typing import Any, Iterable

from django.apps import apps
from django.db import connection


ROOT = Path(__file__).resolve().parents[2]
USAGE_ROOTS = (ROOT / 'core' / 'api', ROOT / 'core' / 'services', ROOT / 'core' / 'management')

DOMAIN_RULES = (
    ('origination', ('Origination', 'LoanOrigination')),
    ('tat', ('Tat', 'WorkflowTat', 'BusinessCalendar')),
    ('complaints', ('Complaint', 'CaseUpdate', 'ParsedMessage', 'RawMessage', 'ProcessedMessage')),
    ('jawabu', ('Jawabu', 'Fca', 'Requisition', 'PaymentDocument', 'Invoice', 'ParsedInvoice')),
    ('catalog', ('Product', 'OperationalLocation', 'BranchServiceArea', 'Location', 'ComplaintCategory')),
    ('access', ('Access', 'Staff', 'UserProfile', 'WorkflowRole', 'EmergencyAccess', 'CapabilityUsage')),
    ('integration', ('Integration', 'Sheet', 'LiveSheet', 'DocumentSignoff')),
    ('audit', ('ComplianceAudit',)),
    ('platform', ('MiniApp', 'DurableJob', 'ProductionRelease', 'WorkflowDataMode', 'PortalMaintenance')),
    ('spin', ('Spin',)),
    ('order_approval', ('OrderApproval', 'MediaAttachment')),
)

# New models must be explicitly declared here. Existing models are covered by
# scripts/database_catalog_existing_models.json and deterministic inference.
MODEL_OVERRIDES: dict[str, dict[str, Any]] = {
    'requisitions.OrderSequenceState': {
        'domain': 'requisitions',
        'purpose': 'Group-scoped source of truth for the next official requisition order number.',
        'classification': 'configuration_state',
        'source_of_truth': True,
        'lifecycle': 'active',
        'retention': 'Retain permanently; adjustments are attributed and finalized numbers are never rewritten.',
    },
    'requisitions.OrderSequenceEvent': {
        'domain': 'requisitions',
        'purpose': 'Immutable customer-data-free evidence for each official sequence mutation.',
        'classification': 'immutable_event',
        'source_of_truth': True,
        'lifecycle': 'active',
        'retention': 'Permanent; sequence audit events are never edited or deleted.',
    },
    'core.TatTrackerCase': {
        'domain': 'tat',
        'purpose': 'Authoritative TAT case and its current workflow stage.',
        'classification': 'authoritative_record',
        'source_of_truth': True,
        'lifecycle': 'active',
        'retention': 'Retained with the permanent TAT operational record.',
    },
    'core.ComplianceAuditEvent': {
        'domain': 'audit',
        'purpose': 'Immutable cross-workflow compliance evidence in the verified hash chain.',
        'classification': 'immutable_event',
        'source_of_truth': True,
        'lifecycle': 'active',
        'retention': 'Permanent; application deletion is prohibited.',
    },
    'core.MiniAppDiagnosticSession': {
        'domain': 'platform',
        'purpose': 'Privacy-safe Mini App lifecycle session telemetry.',
        'classification': 'operational_telemetry',
        'source_of_truth': False,
        'lifecycle': 'temporary',
        'retention': 'Raw retention is configured by MINIAPP_DIAGNOSTICS_RAW_RETENTION_DAYS, then aggregated.',
    },
    'core.MiniAppDiagnosticEvent': {
        'domain': 'platform',
        'purpose': 'Privacy-safe events belonging to a Mini App diagnostic session.',
        'classification': 'operational_telemetry',
        'source_of_truth': False,
        'lifecycle': 'temporary',
        'retention': 'Deleted with expired raw diagnostic sessions after aggregation.',
    },
    'core.MiniAppDiagnosticDailyAggregate': {
        'domain': 'platform',
        'purpose': 'Anonymous daily Mini App diagnostic trend totals.',
        'classification': 'derived_metric',
        'source_of_truth': False,
        'lifecycle': 'active',
        'retention': 'Retention is configured by MINIAPP_DIAGNOSTICS_AGGREGATE_RETENTION_DAYS.',
    },
    'core.MiniAppLegacyWriteDailyAggregate': {
        'domain': 'platform',
        'purpose': 'Anonymous readiness totals for outdated Mini App writes missing retry keys.',
        'classification': 'derived_metric',
        'source_of_truth': False,
        'lifecycle': 'compatibility',
        'retention': 'Bounded by the idempotency readiness observation window and operational policy.',
    },
    'core.ComplianceAuditCheckpoint': {
        'domain': 'audit',
        'purpose': 'Supervised daily checkpoint of the compliance hash-chain head.',
        'classification': 'immutable_snapshot',
        'source_of_truth': False,
        'lifecycle': 'active',
        'retention': 'Retained as compliance evidence; created only by the supervised checkpoint command.',
    },
    'core.FcaImportRecord': {
        'domain': 'jawabu',
        'purpose': 'Auditable staging and review row for one FCA workbook record.',
        'classification': 'processing_record',
        'source_of_truth': False,
        'lifecycle': 'active',
        'retention': 'Retained with its FCA import and Jawabu workflow evidence.',
    },
    'core.OriginationDocumentProductEligibility': {
        'domain': 'origination',
        'purpose': 'Current product allowlist for one immutable Origination catalogue document version.',
        'classification': 'business_link',
        'source_of_truth': True,
        'lifecycle': 'active',
        'retention': 'Retained while the catalogue document or product history requires it.',
    },
    'core.OriginationProductDocumentAssignment': {
        'domain': 'origination',
        'purpose': 'Version-policy assignment between a legacy product definition and document family.',
        'classification': 'business_assignment',
        'source_of_truth': True,
        'lifecycle': 'compatibility',
        'retention': 'Retained for historical product-definition and application compatibility.',
    },
}


def domain_for(model) -> str:
    override = MODEL_OVERRIDES.get(model._meta.label, {})
    if override.get('domain'):
        return str(override['domain'])
    name = model.__name__
    for domain, prefixes in DOMAIN_RULES:
        if name.startswith(prefixes):
            return domain
    return 'platform'


def _purpose(model) -> str:
    doc = re.sub(r'\s+', ' ', str(model.__doc__ or '')).strip()
    if doc and not doc.startswith(f'{model.__name__}('):
        sentence = doc.split('\n', 1)[0].strip()
        if sentence:
            return sentence.rstrip('.') + '.'
    return f'Persists {model._meta.verbose_name_plural} for the owning workflow.'


def _classification(model) -> str:
    name = model.__name__.casefold()
    if 'event' in name or name.endswith('history'):
        return 'immutable_event'
    if 'audit' in name:
        return 'audit_evidence'
    if name.endswith(('assignment', 'eligibility', 'availability', 'alias')):
        return 'business_assignment' if name.endswith('assignment') else 'business_link'
    if name.endswith(('aggregate', 'metric')):
        return 'derived_metric'
    if name.endswith(('state', 'settings', 'policy')):
        return 'configuration_state'
    if name.endswith(('batch', 'item', 'job', 'task', 'challenge')):
        return 'processing_record'
    if name.endswith(('template', 'definition', 'configuration', 'config')):
        return 'configuration'
    return 'authoritative_record'


def _lifecycle(model, classification: str) -> str:
    name = model.__name__.casefold()
    if 'legacy' in name:
        return 'compatibility'
    if any(word in name for word in ('draft', 'heartbeat', 'challenge', 'session')):
        return 'temporary'
    if name.startswith('orderapproval'):
        return 'archived'
    return 'active'


def _retention(model, classification: str, lifecycle: str) -> str:
    if lifecycle == 'temporary':
        return 'Service-managed bounded retention; see the owning service and deployment settings.'
    if classification in {'immutable_event', 'audit_evidence'}:
        return 'Retained with the permanent workflow or compliance audit record.'
    if classification == 'derived_metric':
        return 'Retained according to the reporting or telemetry aggregation policy.'
    if classification in {'configuration', 'configuration_state', 'business_assignment', 'business_link'}:
        return 'Retain while referenced; retire or deactivate instead of deleting governed history.'
    return 'Retained with the owning business record according to its workflow policy.'


def _relations(models: Iterable) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    parents: dict[str, set[str]] = defaultdict(set)
    children: dict[str, set[str]] = defaultdict(set)
    known = {model._meta.label: model for model in models}
    for model in known.values():
        for field in model._meta.concrete_fields:
            if not field.is_relation or not field.related_model:
                continue
            target = field.related_model._meta.label
            parents[model._meta.label].add(target)
            if target in known:
                children[target].add(model._meta.label)
    return (
        {key: sorted(value) for key, value in parents.items()},
        {key: sorted(value) for key, value in children.items()},
    )


def usage_inventory(model_names: Iterable[str]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Find all model call sites in one bounded repository pass."""
    names = sorted(set(model_names), key=len, reverse=True)
    pattern = re.compile(rf'\b({"|".join(re.escape(name) for name in names)})\b')
    locations: dict[str, set[str]] = defaultdict(set)
    writers: dict[str, set[str]] = defaultdict(set)
    mutation_names = 'create|bulk_create|update|update_or_create|get_or_create|delete'
    for root in USAGE_ROOTS:
        if not root.exists():
            continue
        for path in sorted(root.rglob('*.py')):
            try:
                content = path.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                continue
            relative = path.relative_to(ROOT).as_posix()
            matched_names = {match.group(1) for match in pattern.finditer(content)}
            for name in matched_names:
                locations[name].add(relative)
                direct_mutation = re.search(
                    rf'\b{re.escape(name)}\.objects[\s\S]{{0,400}}?\.(?:{mutation_names})\s*\(',
                    content,
                )
                if direct_mutation:
                    writers[name].add(relative)
    return (
        {name: sorted(values) for name, values in locations.items()},
        {name: sorted(values) for name, values in writers.items()},
    )


def _live_statistics() -> dict[str, dict[str, Any]]:
    if connection.vendor != 'postgresql':
        return {}
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT c.relname, COALESCE(c.reltuples, 0)::bigint,
                   pg_total_relation_size(c.oid), obj_description(c.oid, 'pg_class')
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema() AND c.relkind = 'r'
        """)
        return {
            row[0]: {'estimated_rows': row[1], 'storage_bytes': row[2], 'database_comment': row[3] or ''}
            for row in cursor.fetchall()
        }


def database_catalog(*, include_usage: bool = True, include_live: bool = False) -> list[dict[str, Any]]:
    models = sorted(apps.get_app_config('core').get_models(), key=lambda model: model._meta.db_table)
    parents, children = _relations(models)
    live = _live_statistics() if include_live else {}
    usages, writers = usage_inventory(model.__name__ for model in models) if include_usage else ({}, {})
    entries = []
    for model in models:
        override = MODEL_OVERRIDES.get(model._meta.label, {})
        classification = str(override.get('classification') or _classification(model))
        lifecycle = str(override.get('lifecycle') or _lifecycle(model, classification))
        domain = domain_for(model)
        parent_labels = parents.get(model._meta.label, [])
        child_labels = children.get(model._meta.label, [])
        entries.append({
            'domain': domain,
            'table': model._meta.db_table,
            'django_model': model._meta.label,
            'application_area': domain.replace('_', ' ').title(),
            'purpose': str(override.get('purpose') or _purpose(model)),
            'classification': classification,
            'source_of_truth': bool(override.get('source_of_truth', classification not in {'derived_metric', 'operational_telemetry'})),
            'lifecycle': lifecycle,
            'retention': str(override.get('retention') or _retention(model, classification, lifecycle)),
            'parents': parent_labels,
            'children': child_labels,
            'cross_domain_parents': [
                label for label in parent_labels
                if label.startswith('core.') and domain_for(apps.get_model(label)) != domain
            ],
            'used_by': usages.get(model.__name__, []),
            'direct_orm_writers': writers.get(model.__name__, []),
            'column_count': len(model._meta.concrete_fields),
            'explicit_indexes': [index.name or '<migration-generated>' for index in model._meta.indexes],
            **live.get(model._meta.db_table, {}),
        })
    return entries


def table_comment(entry: dict[str, Any]) -> str:
    parents = ', '.join(entry.get('parents', [])[:6]) or 'none'
    children = ', '.join(entry.get('children', [])[:6]) or 'none'
    usage = ', '.join(entry.get('used_by', [])[:6]) or 'owning Django model and workflow service'
    return (
        f"Domain: {entry['domain']}. Purpose: {entry['purpose']} "
        f"Classification: {entry['classification']}. Source of truth: "
        f"{'yes' if entry['source_of_truth'] else 'no'}. Lifecycle: {entry['lifecycle']}. "
        f"Retention: {entry['retention']} Parents: {parents}. Children: {children}. Code usage: {usage}."
    )


def column_comment(field) -> str:
    help_text = re.sub(r'\s+', ' ', str(field.help_text or '')).strip()
    if help_text:
        return help_text
    if field.is_relation and field.related_model:
        on_delete = getattr(getattr(field, 'remote_field', None), 'on_delete', None)
        delete_name = getattr(on_delete, '__name__', 'unspecified')
        return f'Reference to {field.related_model._meta.db_table}; deletion behavior: {delete_name}.'
    label = str(field.verbose_name or field.name).strip()
    return f'{label[:1].upper()}{label[1:]} ({field.get_internal_type()}).'
