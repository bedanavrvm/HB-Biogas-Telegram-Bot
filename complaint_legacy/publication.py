"""Reviewed register changeover and bounded, read-back-verified FIFO publication."""
from datetime import timedelta
import hashlib
import json
import time
import zlib

from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from openpyxl.utils import get_column_letter

from core.models import ComplaintCaseControl, GroupSheetConfiguration, IntegrationOperation, ParsedMessage
from core.services import complaint_cases as cases
from core.services.external_resilience import external_call_budget
from core.services.miniapp_deletion_sheets import sheet_mutation
from .models import ImportChunk, ImportRow, ImportUpload
from .services import save

CUTOVER_PHASES = ('backing_up', 'clearing', 'deleting_tests')


def checksum(values):
    return hashlib.sha256(json.dumps(values, separators=(',', ':'), ensure_ascii=False, default=str).encode()).hexdigest()


def destination(group):
    if not cases.complaint_sheet_projection_enabled(group):
        raise ValueError('Enable Complaints Sheet projection before syncing.')
    if not group.sheet_id or not group.sheet_name:
        raise ValueError('Configure the exact Complaints spreadsheet and worksheet first.')
    service = cases.get_sheets_service(sheet_id=group.sheet_id, sheet_name=group.sheet_name,
                                      sheet_schema=group.sheet_schema_config)
    from core.services.complaint_publication import validate_publication_target
    validate_publication_target(service)
    if service.schema.row_key_field != 'complaint_id' or not service.schema.strict_headers:
        raise ValueError('Use the current Complaints register with its Complaint ID column.')
    sheet = service._sheet.spreadsheet.get_worksheet_by_id(service._sheet.id)
    return service, sheet


def paused(group_id):
    return ImportUpload.objects.filter(group__group_id=group_id, phase__in=CUTOVER_PHASES).exists()


def test_cases(upload):
    return ParsedMessage.objects.filter(group_id=upload.group.group_id).exclude(
        pk__in=ImportRow.objects.filter(case__isnull=False).values('case_id'))


def test_facts(upload):
    fields = [field.attname for field in ParsedMessage._meta.fields]
    return {str(row['id']): checksum(row) for row in test_cases(upload).order_by('pk').values(
        *fields, 'complaint_control__revision', 'complaint_control__updated_at')}


def _require_superuser(actor):
    if not actor.user.is_active or not actor.user.is_superuser:
        raise PermissionDenied('An active Superuser must confirm deletion of test cases and register clearing. Complaints IT can import and sync afterwards.')


def preview(upload, group, actor):
    _require_superuser(actor)
    if upload.phase not in {'ready', *CUTOVER_PHASES} or ImportUpload.objects.filter(
            group=upload.group, phase__in=CUTOVER_PHASES).exclude(pk=upload.pk).exists():
        raise ValueError('Finish or resume the current step before preparing changeover.')
    if ImportUpload.objects.filter(group=upload.group, state__cutover_complete=True).exists():
        raise ValueError('Changeover is already complete. Use Sync imported cases; the register will not be cleared again.')
    if not upload.rows.exclude(proposal__status='blocked').exists():
        raise ValueError('Stage at least one valid replacement row before deleting test cases or clearing the register.')
    service, sheet = destination(group)
    owners = GroupSheetConfiguration.objects.filter(enabled=True, sheet_id=group.sheet_id, sheet_name=group.sheet_name).exclude(pk=upload.group_id)
    if owners.exists():
        raise ValueError('Another workspace uses this same register. Assign a separate worksheet before clearing it.')
    facts = test_facts(upload)
    manifest = checksum(facts)
    target = {'spreadsheet': str(sheet.spreadsheet.id), 'sheet': sheet.id, 'name': sheet.title,
              'header_row': service.header_row, 'headers': sheet.row_values(service.header_row),
              'rows': sheet.row_count, 'cols': sheet.col_count}
    upload.state['cutover_preview'] = {'manifest': manifest, 'target': target, 'count': len(facts)}
    save(upload)
    return {'test_cases': len(facts), 'retained_imports': ImportRow.objects.filter(upload__group=upload.group,
            committed_at__isnull=False).values('case_id').distinct().count(), **target,
            'token': signing.dumps({'upload': str(upload.pk), 'actor': actor.user.pk, 'manifest': manifest,
                                   'target': target}, salt='complaint-register-changeover')}


def confirm(upload, group, actor, body):
    _require_superuser(actor)
    reviewed = upload.state.get('cutover_preview', {})
    if upload.phase not in {'ready', *CUTOVER_PHASES} or not reviewed or not body.get('manual_edits_paused'):
        raise ValueError('Preview the destination and pause manual Sheet edits before confirming changeover.')
    expected = {'upload': str(upload.pk), 'actor': actor.user.pk, 'manifest': reviewed['manifest'], 'target': reviewed['target']}
    if signing.loads(body.get('token', ''), salt='complaint-register-changeover', max_age=1800) != expected:
        raise ValueError('Changeover selection changed. Preview it again.')
    with sheet_mutation():
        GroupSheetConfiguration.objects.select_for_update().get(pk=upload.group_id)
        if ImportUpload.objects.filter(group=upload.group, phase__in=CUTOVER_PHASES).exclude(pk=upload.pk).exists() or ImportUpload.objects.filter(group=upload.group, state__cutover_complete=True).exists():
            raise ValueError('Another changeover already started. Resume its saved import.')
        facts = test_facts(upload)
        if checksum(facts) != reviewed['manifest']:
            raise ValueError('Existing cases changed after preview. Review deletion again.')
        deleted = upload.state.get('cutover', {}).get('deleted', 0)
        upload.state['cutover'] = {**reviewed['target'], 'remaining': list(facts), 'facts': facts,
                                   'offset': 0, 'hashes': [], 'deleted': deleted, 'backup_kind': f'bak{upload.revision}'}
        upload.phase = 'backing_up'
        save(upload)


def _target(upload, group):
    service, sheet = destination(group)
    target = upload.state['cutover']
    if (str(sheet.spreadsheet.id), sheet.id, sheet.row_count, sheet.col_count,
        service.header_row, sheet.row_values(service.header_row)) != (
            target['spreadsheet'], target['sheet'], target['rows'], target['cols'], target['header_row'], target['headers']):
        raise ValueError('The reviewed Sheet destination or layout changed. Restore it before resuming changeover.')
    return service, sheet, target


def advance_cutover(upload, group, actor):
    _require_superuser(actor)
    with sheet_mutation(), external_call_budget(18):
        service, sheet, target = _target(upload, group)
        if upload.phase == 'backing_up':
            start = service.header_row + 1 + target['offset']
            if start <= target['rows']:
                end = min(start + 249, target['rows'])
                values = sheet.get(f'A{start}:{get_column_letter(target["cols"])}{end}', value_render_option='FORMULA')
                content = zlib.compress(json.dumps(values, ensure_ascii=False).encode())
                ImportChunk.objects.update_or_create(upload=upload, kind=target['backup_kind'], position=target['offset'],
                    defaults={'content': content, 'digest': hashlib.sha256(content).hexdigest()})
                target['hashes'].append(checksum(values)); target['offset'] += 250
            else:
                upload.phase = 'deleting_tests'
            save(upload)
            return
        if upload.phase == 'deleting_tests':
            from core.services.group_reset import _reset_complaint_configuration
            selected = target['remaining'][:50]
            current = test_facts(upload)
            if any(current.get(pk) != target['facts'][pk] for pk in selected):
                raise ValueError('A confirmed test case changed. Review its ownership before continuing deletion.')
            _reset_complaint_configuration(group.group_id, case_ids=selected)
            target['remaining'] = target['remaining'][len(selected):]
            target['deleted'] += len(selected)
            if not target['remaining']:
                upload.phase = 'clearing'
            save(upload)
            return
        # One atomic provider request clears values below the header; formatting and other tabs survive.
        area = f'A{service.header_row+1}:{get_column_letter(target["cols"])}{target["rows"]}'
        values = sheet.get(area, value_render_option='FORMULA') if target['rows']>service.header_row else []
        if any(str(cell).strip() for row in values for cell in row):
            for index, offset in enumerate(range(0, target['rows'] - service.header_row, 250)):
                page = values[offset:offset+250]
                while page and not page[-1]: page.pop()
                if checksum(page) != target['hashes'][index]:
                    raise ValueError('Sheet values changed after backup. Restore the reviewed values before clearing; saved imports are retained.')
            sheet.spreadsheet.batch_update({'requests': [{'updateCells': {'range': {
                'sheetId': sheet.id, 'startRowIndex': service.header_row, 'endRowIndex': target['rows'],
                'startColumnIndex': 0, 'endColumnIndex': target['cols']}, 'fields': 'userEnteredValue'}}]})
        remaining = sheet.get(area, value_render_option='FORMULA') if target['rows']>service.header_row else []
        if any(str(cell).strip() for row in remaining for cell in row):
            raise ValueError('Sheet clearing is not yet verified. Resume before importing.')
        ParsedMessage.objects.filter(group_id=group.group_id).update(synced_to_sheets=False, synced_at=None)
        ComplaintCaseControl.objects.filter(parsed_message__group_id=group.group_id).update(sync_status='pending', last_sync_at=None)
        upload.state['cutover_complete'] = True
        upload.phase = 'ready'
        save(upload)
        from complaint_publications.services import queue_sheet
        for case in test_cases(upload).iterator(chunk_size=50):
            queue_sheet(group, case)
        from core.services.compliance_audit import record_event
        record_event(workflow='complaint_cases', action='complaint.legacy.changeover', actor=actor.user,
            subject_type='complaint_import', subject_id=str(upload.pk),
            deduplication_key=f'complaint-changeover:{upload.pk}',
            metadata={'deleted_test_cases': target['deleted'], 'backup_chunks': len(target['hashes']), 'sheet': sheet.id})


def pending_rows(owner=None):
    rows = ImportRow.objects.filter(case__isnull=False, committed_at__isnull=False)
    if owner is not None: rows = rows.filter(upload__group=owner)
    return rows.filter(
        Q(case__synced_to_sheets=False) | ~Q(case__complaint_control__sync_status='success'))


def sync(upload, group):
    """Use the existing register projection, with atomic writes and full-cell readback."""
    try:
        with sheet_mutation(), external_call_budget(18):
            if paused(group.group_id):
                raise ValueError('Finish the saved test-data changeover before syncing.')
            service, sheet = destination(group)
            drafts = list(pending_rows(upload.group).select_related('case__complaint_control').order_by('committed_at', 'pk')[:50])
            if not drafts:
                upload.state.pop('sync_error', None); upload.state.pop('sync_retry_at', None)
                if upload.phase=='publishing': upload.phase='ready'
                save(upload)
                return 0
            width = sheet.col_count
            values = sheet.get(f'A1:{get_column_letter(width)}{sheet.row_count}', value_render_option='UNFORMATTED_VALUE')
            headers = sheet.row_values(service.header_row)
            from core.services.sheet_columns import NamedColumns, assert_columns_unchanged
            layout = NamedColumns(headers, sheet_name=sheet.title)
            normalized = [service.schema.normalize(h) for h in headers]
            key = normalized.index(service.schema.normalize(service.schema.header('complaint_id')))
            positions = {}
            for number, row in enumerate(values[service.header_row:], service.header_row + 1):
                reference = str(row[key]).strip() if key < len(row) else ''
                if not reference: continue
                if reference in positions: raise ValueError('Duplicate Complaint IDs exist in the register. Resolve them before syncing.')
                positions[reference] = number
            next_row = service._next_case_row_from_values(headers, values)
            plans = []
            seen = set()
            for draft in drafts:
                case = draft.case; control = case.complaint_control
                if case.group_id != group.group_id:
                    raise ValueError('Imported case ownership differs from this workspace. No rows were written; ask Complaints IT to review the link.')
                if case.pk in seen: continue
                seen.add(case.pk)
                number = positions.get(control.reference_number)
                if not number: number = next_row; next_row += 1
                projected = {service.schema.normalize(h): service._complaint_projection_value(service.schema.normalize(h), value)
                             for h, value in zip(service.sheet_columns, service.schema.row_for_message(case))}
                projected[service.schema.normalize(service.schema.header('row_number'))] = str(number - service.header_row)
                row = list(values[number-1]) if number <= len(values) else []
                row += [''] * max(0, len(headers)-len(row))
                for column, header in enumerate(normalized):
                    if header in projected: row[column] = projected[header]
                if any(len(str(value)) > 50000 for value in row):
                    raise ValueError('A projected cell exceeds the Sheet limit. All original history remains in Django; ask Complaints IT to review it.')
                plans.append((case, control, number, row[:len(headers)]))
            requests = []
            last = max(p[2] for p in plans)
            if last > sheet.row_count:
                requests.append({'appendDimension': {'sheetId': sheet.id, 'dimension': 'ROWS', 'length': last-sheet.row_count}})
            for case, control, number, row in plans:
                columns = [(i+1, value, 'RAW') for i, value in enumerate(row) if normalized[i] in projected]
                for block in service._group_consecutive_columns(columns):
                    cells = [{'userEnteredValue': {'numberValue': value} if isinstance(value, (int, float)) else {'stringValue': str(value)}} for _, value, _ in block]
                    requests.append({'updateCells': {'range': {'sheetId': sheet.id, 'startRowIndex': number-1,
                        'endRowIndex': number, 'startColumnIndex': block[0][0]-1, 'endColumnIndex': block[-1][0]},
                        'rows': [{'values': cells}], 'fields': 'userEnteredValue'}})
            assert_columns_unchanged(sheet, layout, header_row=service.header_row)
            sheet.spreadsheet.batch_update({'requests': requests})
            service._format_complaint_date_rows([p[2] for p in plans])
            service._format_complaint_status_rows([(p[2], p[0].complaint_status.upper()) for p in plans])
            readback = sheet.batch_get([f'A{p[2]}:{get_column_letter(len(headers))}{p[2]}' for p in plans], value_render_option='UNFORMATTED_VALUE')
            assert_columns_unchanged(sheet, layout, header_row=service.header_row)
            if len(readback) != len(plans): raise ValueError('Sheet readback is incomplete. Resume sync to verify saved rows.')
            for (case, control, number, expected), actual in zip(plans, readback):
                found = (list(actual[0]) if actual else [])
                found += [''] * max(0, len(expected)-len(found))
                if any(str(found[i]) != str(expected[i]) for i, header in enumerate(normalized) if header in projected):
                    raise ValueError('Sheet values did not verify. Resume sync; Complaint IDs prevent duplicate rows.')
                if ComplaintCaseControl.objects.filter(pk=control.pk, revision=control.revision).update(sync_status='success', sync_error='', last_sync_at=timezone.now()):
                    ParsedMessage.objects.filter(pk=case.pk).update(synced_to_sheets=True, synced_at=timezone.now(), sheet_id=group.sheet_id, sheet_name=group.sheet_name, last_sync_error='')
                    IntegrationOperation.objects.filter(operation_type='complaint_browser.sheet', source_id=str(control.pk),
                        metadata__revision=control.revision, status__in=['pending', 'retryable', 'dead_letter']).update(
                            status='succeeded', last_error='', last_error_code='', next_retry_at=None)
            upload.state.pop('sync_error', None); upload.state.pop('sync_retry_at', None)
            if upload.phase=='publishing' and not pending_rows(upload.group).exists(): upload.phase='ready'
            save(upload)
            return len(plans)
    except Exception as error:
        upload.refresh_from_db()
        diagnostic = getattr(error, 'publication_diagnostic', {})
        message = str(error) if isinstance(error, ValueError) else ('Register columns missing: ' + ', '.join(diagnostic['missing_headers'])
            if diagnostic.get('missing_headers') else 'Sheet publication could not be verified. Check the configured register and Google access, then retry. Saved cases are retained.')
        upload.state['sync_error'] = message
        upload.state['sync_retry_at'] = (timezone.now() + timedelta(minutes=1)).isoformat()
        save(upload)
        raise ValueError(message) from None


def drain(*, seconds, limit=10):
    """The existing scheduled publisher also resumes imports after the app closes."""
    from core.services.group_config import GroupConfig
    from .services import leased
    deadline = time.monotonic() + seconds
    total = 0
    uploads = ImportUpload.objects.filter(rows__in=pending_rows()).exclude(phase__in=CUTOVER_PHASES).select_related('group').distinct().order_by('created_at')
    for upload in uploads[:10]:
        if deadline - time.monotonic() < 18: break
        if upload.state.get('sync_retry_at', '') > timezone.now().isoformat(): continue
        group = GroupConfig(**upload.group.as_group_config_kwargs())
        if not upload.group.enabled: continue
        while limit>0 and deadline-time.monotonic()>=18:
            try:
                with leased(upload): count=sync(upload, group)
            except ValueError:
                break
            total+=count;limit-=1
            if not count: break
    return total
