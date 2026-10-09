"""Exact-row, DB-first Sheet cleanup. Never opens or deletes a Drive file."""
from contextlib import contextmanager
from datetime import timedelta
from functools import wraps
import logging
import threading
import time

from django.apps import apps
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone

from core.models import GroupSheetConfiguration, IntegrationCircuitState, IntegrationOperation

logger = logging.getLogger(__name__)
_worker = threading.BoundedSemaphore(1)


def lock_sheet_mutations():
    # Same durable mutex for deletion and case publication, including PG workers.
    IntegrationCircuitState.objects.get_or_create(integration='miniapp_sheet_mutation')
    IntegrationCircuitState.objects.select_for_update().get(integration='miniapp_sheet_mutation')


@contextmanager
def sheet_mutation():
    with transaction.atomic():
        lock_sheet_mutations()
        yield


def guarded_publication(function):
    """Do not republish a previously loaded record after committed deletion."""
    @wraps(function)
    def run(*args, **kwargs):
        records = []
        for value in (*args, *kwargs.values()):
            if isinstance(value, (list, tuple)):
                records.extend(item for item in value if hasattr(item, '_meta'))
            elif hasattr(value, '_meta'):
                records.append(value)

        def publish():
            for record in records:
                if IntegrationOperation.objects.filter(operation_type='miniapp_record_deleted',
                        source_model=record._meta.label, source_id=str(record.pk)).exists():
                    if any(isinstance(value, (list, tuple)) for value in (*args, *kwargs.values())):
                        return {'success': False, 'synced': 0, 'failed': [], 'row_numbers': [],
                                'error': 'A selected source was removed by testing cleanup.'}
                    return False
            return function(*args, **kwargs)
        # Ordinary production publication is not serialized once cleanup settles.
        # Tombstone checks still protect stale objects after the testing flag is off.
        if not getattr(settings, 'MINIAPP_TEST_DELETION_ENABLED', False) and not IntegrationOperation.objects.filter(
                operation_type='miniapp_sheet_delete', status__in=[IntegrationOperation.STATUS_PENDING,
                    IntegrationOperation.STATUS_RUNNING, IntegrationOperation.STATUS_RETRYABLE]).exists():
            return publish()
        with sheet_mutation():
            return publish()
    return run


def sheet_targets(records):
    """Freeze destinations and immutable keys before their canonical rows go."""
    result = {}
    for record in records:
        label = record._meta.label
        group_id = str(getattr(record, 'group_id', ''))
        config = getattr(record, 'group_configuration', None)
        if not config and label == 'core.JawabuFarmerMaster':
            from core.services.jawabu_pipeline import _jawabu_group_config
            config = _jawabu_group_config(record)
        if not config and group_id:
            configs = list(GroupSheetConfiguration.objects.filter(group_id=group_id))
            config = configs[0] if len(configs) == 1 else None
        workflow = (config.workflow or {}) if config else {}
        sheet_id = str(getattr(record, 'sheet_id', '') or getattr(config, 'sheet_id', '') or '')
        tab = str(getattr(record, 'sheet_name', '') or getattr(config, 'sheet_name', '') or '')
        destinations = []
        if label == 'core.ParsedMessage':
            from core.services.sheet_schema import SheetSchema
            schema_config = getattr(config, 'sheet_schema', None) or workflow.get('sheet_schema') or {}
            if workflow.get('header_row') and 'header_row' not in schema_config:
                schema_config = {**schema_config, 'header_row': workflow['header_row']}
            schema = SheetSchema.from_config(schema_config)
            key_field = schema.row_key_field
            identity = record.message_id
            if key_field == 'complaint_id':
                control = getattr(record, 'complaint_control', None)
                identity = control.reference_number if control else ''
            header = schema.field_headers[key_field]
            destinations.append((sheet_id, tab, [header], identity, schema.header_row, schema.header_row + 1))
        elif label == 'core.SpinCreditRequest':
            from core.services.spin_credit import spin_request_id, configured_spin_batch_sheet_name, configured_header_row, configured_field_headers
            tab = tab or configured_spin_batch_sheet_name(workflow, '')
            header_row = configured_header_row(workflow)
            destinations.append((sheet_id, tab, [configured_field_headers(workflow)['request_id']],
                                 spin_request_id(record), header_row, header_row + 1))
        elif label == 'core.TatTrackerCase':
            from core.services.tat_tracker import should_sync_secondary_sheets, TAT_TRACKER_DATA_START_ROW, TAT_TRACKER_HEADER_ROW
            destinations.append((sheet_id, tab, ['Case ID'], record.case_id, TAT_TRACKER_HEADER_ROW, TAT_TRACKER_DATA_START_ROW))
            if config and should_sync_secondary_sheets(config):
                destinations.extend([(sheet_id, 'CASE_INDEX', ['Case ID'], record.case_id, 1, 2),
                                     (sheet_id, 'AUDIT LOG', ['Case ID'], record.case_id, 1, 2)])
        elif label == 'core.JawabuFarmerMaster' and config:
            master = str(workflow.get('master_sheet_id') or config.sheet_id or '')
            if not master:
                continue  # No configured remote projection for this local case.
            for name in (workflow.get('master_sheet_name') or 'Master Data',
                         workflow.get('eco_conserve_sheet_name') or 'Eco-conserve'):
                header_row = int(workflow.get('master_header_row') or 1)
                destinations.append((master, str(name), ['Case ID', 'Master Record ID'], str(record.pk),
                                     header_row, int(workflow.get('master_data_start_row') or header_row + 1)))
            # The legacy internal order tab has no canonical case UUID. Do not
            # guess using an ID, name or stale row number: report it for review.
            if workflow.get('internal_order_sync_enabled'):
                destinations.append((str(workflow.get('internal_order_sheet_id') or ''),
                    str(workflow.get('internal_order_sheet_name') or 'Orders'),
                    ['Case ID', 'Master Record ID'], str(record.pk),
                    int(workflow.get('internal_order_header_row') or 2),
                    int(workflow.get('internal_order_data_start_row') or 3)))
        for spreadsheet, name, headers, identity, header_row, start in destinations:
            if not spreadsheet and not name:
                continue  # Synthetic/local-only records never had a Sheet.
            key = (spreadsheet, name, tuple(headers), header_row, start, label)
            if key not in result:
                result[key] = {'spreadsheet': spreadsheet, 'tab': name, 'headers': headers,
                    'header_row': header_row, 'data_start_row': start, 'model': label,
                    'group_id': str(config.group_id) if config else group_id, 'identities': []}
            result[key]['identities'].append(str(identity))
    return [{**value, 'identities': sorted(set(value['identities']))}
            for key, value in sorted(result.items())]


def _layout(target, values):
    row = target['header_row']
    headers = values[row - 1] if len(values) >= row else []
    matches = [i for i, name in enumerate(headers)
               if str(name).strip().casefold() in {h.casefold() for h in target['headers']}]
    if not matches:
        raise ValueError('The Sheet needs an immutable record-ID column. No rows were guessed or removed.')
    return matches


def _ids_for_row(row, columns):
    return {str(row[c]).strip().lstrip("'") for c in columns if c < len(row) and str(row[c]).strip()}


def remove_rows(target):
    from core.services.sheets import get_sheets_service
    if not target['spreadsheet'] or not target['tab']:
        raise ValueError('The original Sheet destination needs review. Database deletion is already complete.')
    service = get_sheets_service(sheet_id=target['spreadsheet'], sheet_name=target['tab'])
    if not service.is_available() or service._sheet is None:
        raise RuntimeError('The Sheet is unavailable. Database deletion is complete; retry Sheet cleanup.')
    sheet = service._sheet
    identities = set(target['identities'])
    values = sheet.get_all_values()
    if target['model'] == 'core.JawabuFarmerMaster' and values:
        # Match the publisher's row-1/row-2 cutover even with legacy saved 3/5 settings.
        headers = {str(value).strip().casefold() for value in values[0]}
        if {'no.', 'customer name'} <= headers:
            target = {**target, 'header_row': 1, 'data_start_row': 2}
    columns = _layout(target, values)
    rows = [number for number, row in enumerate(values, 1)
            if number >= target['data_start_row'] and _ids_for_row(row, columns) & identities]
    for number in reversed(rows):
        # Staff can edit a Sheet independently of our DB mutex.
        current = sheet.row_values(number)
        if not _ids_for_row(current, columns) & identities:
            raise RuntimeError('The Sheet changed during cleanup. Retry will find the exact records again.')
        if _ids_for_row(current, columns) - identities:
            raise ValueError('Conflicting immutable IDs share a row. Ask IT to review it; no guessed deletion.')
        sheet.delete_rows(number)
    values = sheet.get_all_values()
    columns = _layout(target, values)
    if any(_ids_for_row(row, columns) & identities for row in values[target['data_start_row'] - 1:]):
        raise RuntimeError('Sheet removal could not be verified. Retry cleanup.')
    _repair_pointers(target, values, columns)
    return {'rows_removed': len(rows), 'verified_absent': True}


def _repair_pointers(target, values, columns):
    model = apps.get_model(target['model'])
    fields = {f.name for f in model._meta.fields}
    if not {'sheet_id', 'sheet_name', 'row_number'} <= fields:
        return
    row_map = {identity: number for number, row in enumerate(values, 1)
               if number >= target['data_start_row'] for identity in _ids_for_row(row, columns)}
    from core.services.spin_credit import spin_request_id
    for record in model.objects.filter(sheet_id=target['spreadsheet'], sheet_name=target['tab']):
        identity = spin_request_id(record) if target['model'] == 'core.SpinCreditRequest' else record.case_id
        model.objects.filter(pk=record.pk).update(row_number=row_map.get(identity))


def process_cleanup(operation_id):
    from core.services.external_resilience import execute_operation, external_call_budget
    operation = IntegrationOperation.objects.get(pk=operation_id, operation_type='miniapp_sheet_delete')
    def action():
        with sheet_mutation(), external_call_budget(40):
            return remove_rows(operation.metadata['target'])
    return execute_operation(operation, action, attempt_budget=1)


def retry_cleanup(*, operation_id, actor):
    # Already committed cleanup remains repairable after disabling new deletions.
    if not actor or not actor.is_active or not actor.is_superuser:
        raise PermissionDenied('Sheet cleanup retry requires an active Superuser.')
    with transaction.atomic():
        op = IntegrationOperation.objects.select_for_update().get(pk=operation_id, operation_type='miniapp_sheet_delete')
        from core.services.external_resilience import operation_lease_seconds
        if op.status == op.STATUS_SUCCEEDED:
            return
        if op.status == op.STATUS_RUNNING and op.last_attempt_at and (
                timezone.now() - op.last_attempt_at).total_seconds() < operation_lease_seconds():
            return
        op.status = op.STATUS_PENDING
        op.next_retry_at = None
        op.max_attempts = max(op.max_attempts, op.attempts + 5)
        op.save(update_fields=['status', 'next_retry_at', 'max_attempts', 'updated_at'])
        transaction.on_commit(lambda: wake_cleanup([str(op.pk)]))


def wake_cleanup(operation_ids=None):
    """Server-side bounded wake; closing or navigating away cannot cancel it."""
    if not _worker.acquire(blocking=False):
        return
    def work():
        close_old_connections()
        try:
            deadline = time.monotonic() + 50
            while time.monotonic() < deadline:
                now = timezone.now()
                from core.services.external_resilience import operation_lease_seconds
                pending = IntegrationOperation.objects.filter(operation_type='miniapp_sheet_delete').filter(
                    Q(status__in=[IntegrationOperation.STATUS_PENDING, IntegrationOperation.STATUS_RETRYABLE]) |
                    Q(status=IntegrationOperation.STATUS_RUNNING, last_attempt_at__lt=now - timedelta(seconds=operation_lease_seconds())))
                pending = pending.filter(Q(next_retry_at=None) | Q(next_retry_at__lte=now))
                if operation_ids is not None:
                    pending = pending.filter(pk__in=operation_ids)
                op = pending.order_by('created_at', 'pk').first()
                if not op:
                    break
                try:
                    process_cleanup(op.pk)
                except Exception:
                    # Normalized durable outcome; never print customer payloads.
                    logger.warning('Mini App Sheet cleanup pending: operation_id=%s', op.pk)
        finally:
            close_old_connections()
            _worker.release()
    threading.Thread(target=work, name='miniapp-sheet-cleanup', daemon=True).start()
