"""Testing-only, manifest-bound deletion of reviewed Mini App records.

Public interface: preview_selection / delete_selection. No provider calls occur
in either transaction. Exact Sheet work survives in IntegrationOperation; Drive
and independent security evidence are never deletion targets.
"""
from collections import defaultdict
import hashlib
import json
import re

from django.apps import apps
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from core.models import ComplianceAuditEvent, IntegrationOperation
from core.services.compliance_audit import record_event
from core.services.miniapp_deletion_registry import REGISTRY, RETAIN_REFERENCERS, UNLINK

KEEP = 'keep'
CASCADE = 'linked'
MARKER = 'miniapp_record_deleted'
MAX_RECORDS = 10000


class DeletionError(ValueError):
    pass


class SelectionChanged(DeletionError):
    pass


def authorize(actor):
    if not (getattr(settings, 'MINIAPP_TEST_DELETION_ENABLED', False)
            and actor and actor.is_active and actor.is_superuser):
        raise PermissionDenied('Testing deletion requires the setting and an active Superuser.')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def _model(label):
    if label not in REGISTRY:
        raise DeletionError('This model is not included in the reviewed deletion registry.')
    return apps.get_model(label)


def _ids(model, ids):
    try:
        values = list(ids)
        if any(isinstance(value, (bool, float)) for value in values):
            raise ValueError('Invalid record reference.')
        result = sorted({str(model._meta.pk.to_python(value)) for value in values})
    except (ValueError, TypeError, OverflowError, ValidationError) as exc:
        raise DeletionError('Choose valid record references.') from exc
    if not result or len(result) > MAX_RECORDS:
        raise DeletionError('Choose between 1 and 10,000 records.')
    return result


def _key(record):
    return (record._meta.label, str(record.pk))


def _owner(record):
    """Promote explicitly selected evidence to its integrity-owning workspace."""
    seen = set()
    while _key(record) not in seen:
        seen.add(_key(record))
        policy = REGISTRY[record._meta.label]
        field = policy.owner
        if record._meta.label == 'core.DocumentPhysicalSignoff':
            field = 'requisition_batch' if record.requisition_batch_id else 'payment_document'
        if not field or not getattr(record, field + '_id', None):
            return record
        record = getattr(record, field)
    raise DeletionError('An evidence ownership cycle needs review.')


def _uses_key(value, key):
    if isinstance(value, dict):
        return any((k in {'key', 'data_field_key', 'context_key', 'canonical_key'} and v == key)
                   or _uses_key(v, key) for k, v in value.items())
    return isinstance(value, list) and any(_uses_key(v, key) for v in value)


def _json_members(model_label, field, reference):
    model = apps.get_model(model_label)
    if connection.features.supports_json_field_contains:
        yield from model.objects.filter(**{field + '__contains': [reference]})
    else:
        # SQLite is a local test fallback; PostgreSQL filters this in the DB.
        for row in model.objects.all().iterator():
            if reference in {str(value) for value in (getattr(row, field) or [])}:
                yield row


def _extra_children(record):
    """Reviewed non-FK links. Never match a customer by name or phone."""
    label = record._meta.label
    if label in {'core.TatTrackerCase', 'core.JawabuFarmerMaster'}:
        workflow = 'tat_tracker' if label == 'core.TatTrackerCase' else 'jawabu_pipeline'
        for name in ('WorkflowSlaEscalation', 'WorkflowTimelineAnnotation'):
            yield from apps.get_model('core', name).objects.filter(workflow=workflow, subject_id=str(record.pk))
    if label == 'origination.OriginationDataField':
        for target in ('OriginationProductDefinition', 'OriginationDocumentTemplate'):
            for item in apps.get_model('origination', target)._base_manager.all().iterator():
                if _uses_key(item.form_schema, record.key):
                    yield item
    if label == 'core.Product':
        # Old product definitions/requests predate their canonical FK.
        yield from apps.get_model('origination', 'OriginationProductDefinition').objects.filter(
            product_version__isnull=True, product_key=record.code)
        for target, field in (('SpinCreditRequest', 'loan_product'), ('TatTrackerCase', 'product_key')):
            yield from apps.get_model('core', target).objects.filter(product__isnull=True, **{field: record.code})
    if label in {'core.ComplaintCaseImportBatch', 'core.JawabuFarmerUploadBatch'}:
        if label == 'core.ComplaintCaseImportBatch':
            ids = record.items.exclude(parsed_message_id=None).values_list('parsed_message_id', flat=True)
            yield from apps.get_model('core', 'ParsedMessage').objects.filter(pk__in=ids)
        else:
            # Only exact publication ownership, never mutable row/name matching.
            # SysUp enriches existing cases; deleting its upload must not erase them.
            if record.import_kind == 'farmers':
                refs = IntegrationOperation.objects.filter(source_model='JawabuFarmerMaster',
                    metadata__farmup_worklist_id=str(record.worklist_id)).values_list('source_id', flat=True)
                yield from apps.get_model('core', 'JawabuFarmerMaster').objects.filter(pk__in=list(refs))
    if label == 'core.JawabuFarmerMaster':
        # A shared batch cannot retain signed bytes after a member is erased.
        for membership in record.payment_batch_memberships.select_related('batch'):
            yield membership.batch
        if record.requisition_batch_id:
            yield record.requisition_batch
        # Reviewed legacy JSON membership is still exact UUID ownership.
        yield from _json_members('core.RequisitionBatch', 'farmer_ids', str(record.pk))
        yield from _json_members('core.PaymentDocument', 'farmer_ids', str(record.pk))
    if label == 'payments.PaymentBatch' and record.current_document_id:
        yield record.current_document
    if label == 'core.PaymentDocument':
        yield from apps.get_model('payments', 'PaymentBatch').objects.filter(current_document=record)


def _closure(roots):
    rows, retain, unlink, blockers = {}, set(), {}, set()
    queue = list(roots)
    while queue:
        record = queue.pop()
        key = _key(record)
        if key in rows:
            continue
        rows[key] = record
        if len(rows) > MAX_RECORDS:
            raise DeletionError('This selection affects more than 10,000 records. Use smaller selections.')
        queue.extend(_extra_children(record))
        for relation in record._meta.related_objects:
            if relation.many_to_many:
                continue  # The explicit through model below owns this link.
            target = relation.related_model
            field = relation.field
            edge = f'{target._meta.label}.{field.name}'
            children = target._base_manager.filter(**{field.attname: record.pk})
            if edge in UNLINK:
                for child in children:
                    unlink[(_key(child), field.name)] = None
                continue
            if target._meta.label in {'requisitions.OrderNumberClaim', 'payments.PaymentNumberClaim'}:
                for child in children:
                    unlink[(_key(child), field.name)] = None
                    unlink[(_key(child), 'retired')] = True
                continue
            if target._meta.label in REGISTRY:
                for child in children:
                    # Evidence is never orphaned by a deletion of a different FK.
                    queue.append(_owner(child) if REGISTRY[target._meta.label].kind == 'evidence' else child)
                    queue.append(child)
            elif children.exists():
                if target._meta.label in RETAIN_REFERENCERS:
                    retain.add(key)
                else:
                    blockers.add(f'{target._meta.verbose_name_plural}: relationship not reviewed for testing deletion.')
    return rows, retain, unlink, blockers


def _row_fingerprint(record):
    # Bind every concrete value, including retained bytes, without putting them
    # in the confirmation token, compliance ledger or an operations payload.
    values = {}
    for field in record._meta.concrete_fields:
        value = getattr(record, field.attname)
        if isinstance(value, (bytes, memoryview)):
            value = hashlib.sha256(bytes(value)).hexdigest()
        values[field.attname] = value
    return digest(values)


def preview_selection(*, model_label, ids, actor, mode=KEEP):
    authorize(actor)
    model = _model(model_label)
    selected = _ids(model, ids)
    if mode not in {KEEP, CASCADE}:
        raise DeletionError('Choose whether to keep or delete linked records.')
    objects = list(model._base_manager.filter(pk__in=selected).order_by('pk'))
    if len(objects) != len(selected):
        raise SelectionChanged('The selection changed. Refresh the list.')
    roots = [_owner(item) for item in objects]
    rows, retained, unlink, blockers = _closure(roots)
    if mode == KEEP:
        for root in roots:
            if REGISTRY[root._meta.label].kind != 'configuration':
                continue
            child_rows, child_retained, _, _ = _closure([root])
            if child_retained or any(REGISTRY[label].kind == 'operational' for label, pk in child_rows):
                retained.update(child_rows)
    # A retained definition must keep its non-null historical dependencies too.
    changed = True
    while changed:
        changed = False
        for key in sorted(retained):
            record = rows[key]
            for field in record._meta.fields:
                if field.is_relation and getattr(record, field.attname, None):
                    target = (field.related_model._meta.label, str(getattr(record, field.attname)))
                    if target in rows and target not in retained:
                        retained.add(target)
                        changed = True
    deleted = set(rows) - retained
    # Do not unlink history of surviving cases merely because they were previewed.
    surviving = {}
    for (key, field_name), value in unlink.items():
        if key in deleted:
            continue
        record = apps.get_model(key[0])._base_manager.get(pk=key[1])
        # Number retirement follows removal of its workspace, never a KEEP preview.
        field = record._meta.get_field('batch' if field_name == 'retired' else field_name)
        if (field.related_model._meta.label, str(getattr(record, field.attname))) in deleted:
            surviving[(key, field_name)] = value
    unlink = surviving
    retire = {_key(root): dict(REGISTRY[root._meta.label].retire)
              for root in roots if _key(root) in retained and REGISTRY[root._meta.label].retire}
    from core.services.miniapp_deletion_sheets import sheet_targets
    targets = sheet_targets([rows[key] for key in sorted(deleted)])
    serialized = {'model': model_label, 'ids': selected, 'mode': mode,
                  'deleted': sorted(deleted), 'retained': sorted(retained),
                  'unlink': [(k, v) for k, v in sorted(unlink.items())],
                  'retire': sorted(retire.items()), 'sheets': targets,
                  'facts': [(key, _row_fingerprint(row)) for key, row in sorted(rows.items())]}
    serialized['surviving_facts'] = [(key, _row_fingerprint(apps.get_model(key[0])._base_manager.get(pk=key[1])))
                                   for key in sorted({key for key, field in unlink})]
    groups = {}
    for name, keys in (('deleted', deleted), ('retained', retained), ('unlinked', {key[0] for key in unlink})):
        grouped = defaultdict(list)
        for label, pk in sorted(keys):
            grouped[label].append(pk)
        groups[name] = [{'model': label, 'label': str(apps.get_model(label)._meta.verbose_name_plural),
                         'count': len(pks), 'references': pks} for label, pks in grouped.items()]
    return {'model': model_label, 'ids': selected, 'mode': mode, 'fingerprint': digest(serialized),
            'groups': groups, 'sheet_targets': targets, 'blockers': sorted(blockers),
            'deleted': deleted, 'retained': retained, 'unlink': unlink, 'retire': retire, 'rows': rows,
            'keep_available': any(REGISTRY[root._meta.label].kind == 'configuration' for root in roots)}


def _delete_rows(plan):
    """Delete children first; nullable cycles are severed only inside the manifest.

    Raw deletes deliberately bypass model immutability hooks and file-removal
    signals, under the opt-in service's authorization, locks and audit boundary.
    They do not use CASCADE to enlarge the disclosed set.
    """
    pending = set(plan['deleted'])
    for key in sorted(pending):
        record = plan['rows'][key]
        fields = {}
        for field in record._meta.fields:
            if field.is_relation and field.null:
                target = (field.related_model._meta.label, str(getattr(record, field.attname)))
                if target in pending:
                    fields[field.attname] = None
        if fields:
            record.__class__._base_manager.filter(pk=record.pk).update(**fields)
    while pending:
        parents = set()
        for key in pending:
            record = plan['rows'][key]
            for field in record._meta.fields:
                if field.is_relation and not field.null:
                    target = (field.related_model._meta.label, str(getattr(record, field.attname)))
                    if target in pending and target != key:
                        parents.add(target)
        leaves = pending - parents
        if not leaves:
            raise DeletionError('A non-null historical dependency cycle needs review. Nothing was deleted.')
        for label, pk in sorted(leaves):
            apps.get_model(label)._base_manager.filter(pk=pk)._raw_delete('default')
        pending -= leaves


@transaction.atomic
def delete_selection(*, model_label, ids, actor, mode, fingerprint, request_id):
    authorize(actor)
    model = _model(model_label)
    selected = _ids(model, ids)
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', str(request_id or '')):
        raise DeletionError('A stable request reference is required.')
    identity = digest([model_label, selected, mode, fingerprint])
    dedup = f'miniapp-delete:{request_id}'
    # Serialize deletion/Sheet writes and idempotent confirmation across workers.
    from core.services.miniapp_deletion_sheets import lock_sheet_mutations
    lock_sheet_mutations()
    previous = ComplianceAuditEvent.objects.filter(deduplication_key=dedup).first()
    if previous:
        if previous.actor_id != actor.pk or previous.subject_id != identity:
            raise DeletionError('This request reference belongs to a different confirmation.')
        return {**previous.after_values, 'replayed': True}
    plan = preview_selection(model_label=model_label, ids=selected, actor=actor, mode=mode)
    lock_keys = set(plan['rows']) | {key[0] for key in plan['unlink']}
    for label, pk in sorted(lock_keys):
        apps.get_model(label)._base_manager.select_for_update(of=('self',)).get(pk=pk)
    plan = preview_selection(model_label=model_label, ids=selected, actor=actor, mode=mode)
    if plan['fingerprint'] != fingerprint:
        raise SelectionChanged('Related records changed. Review the updated impact before confirming again.')
    if plan['blockers']:
        raise DeletionError(' '.join(plan['blockers']))
    for key, fields in plan['retire'].items():
        apps.get_model(key[0])._base_manager.filter(pk=key[1]).update(**fields)
    for ((label, pk), field), value in plan['unlink'].items():
        apps.get_model(label)._base_manager.filter(pk=pk).update(**{field: value})
    _cancel_work(plan)
    operation_ids = []
    from core.services.external_resilience import reserve_operation
    for index, target in enumerate(plan['sheet_targets']):
        operation, _ = reserve_operation(integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
            operation_type='miniapp_sheet_delete', deduplication_key=f'{dedup}:sheet:{index}',
            source_model='MiniAppDeletion', source_id=identity, request_id=request_id, requested_by=actor,
            operation_payload=target, metadata={'target': target}, max_attempts=100)
        operation_ids.append(str(operation.pk))
    for label, pk in sorted(plan['deleted']):
        IntegrationOperation.objects.get_or_create(deduplication_key=f'miniapp-deleted:{label}:{pk}', defaults={
            'integration': IntegrationOperation.INTEGRATION_GOOGLE_SHEETS, 'operation_type': MARKER,
            'source_model': label, 'source_id': pk, 'status': IntegrationOperation.STATUS_SUCCEEDED,
            'requested_by': actor, 'completed_at': timezone.now()})
    _delete_rows(plan)
    result = {'deleted': sum(group['count'] for group in plan['groups']['deleted']),
              'retained': sum(group['count'] for group in plan['groups']['retained']),
              'sheet_operations': operation_ids, 'drive_files_untouched': True}
    record_event(workflow='miniapp_testing', action='records.deleted', category='configuration',
        subject_type='DeletionSelection', subject_id=identity, actor=actor, authority_user=actor,
        request_id=request_id, deduplication_key=dedup, before_values=plan['groups'], after_values=result,
        metadata={'model': model_label, 'ids': selected, 'mode': mode, 'fingerprint': fingerprint}, sensitive=True)
    from core.services.miniapp_deletion_sheets import wake_cleanup
    if operation_ids:
        transaction.on_commit(lambda: wake_cleanup(operation_ids))
    return result


def _cancel_work(plan):
    # Exact model + identity; neither a group-wide nor a fuzzy name cancellation.
    selection = Q(pk__in=[])
    for label, pk in plan['deleted']:
        selection |= Q(source_model__in=[label, label.split('.')[-1]], source_id=pk)
    IntegrationOperation.objects.filter(selection).exclude(
        status=IntegrationOperation.STATUS_SUCCEEDED).update(status=IntegrationOperation.STATUS_DEAD_LETTER,
        last_error_code='source_deleted', last_error='Source removed by confirmed testing deletion.', next_retry_at=None)
