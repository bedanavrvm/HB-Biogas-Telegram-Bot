"""Scoped built-in TAT register and privacy-minimised XLSX export."""
from __future__ import annotations

from io import BytesIO

from django.db.models import Prefetch

from core.models import TatActionTask, TatActionTaskRecipient, TatTrackerCase
from core.services.tat_tracker import (
    _scope_tat_queryset, next_action, product_for_case, stage_target_minutes_for_case,
    stage_tat_minutes,
)
from core.services.workflow_data_mode import operational_tat_cases


EXPORT_FIELDS = (
    'Case reference', 'Branch', 'Product', 'Product version', 'Stage',
    'Responsible role', 'Current owner', 'Status', 'Stage elapsed minutes',
    'Stage target minutes', 'Created at', 'Updated at',
)


def _base_queryset(group, user: dict | None = None):
    queryset = operational_tat_cases(TatTrackerCase.objects.filter(
        group_id=str(group.group_id), is_deleted=False,
    )).select_related('product_version').prefetch_related(Prefetch(
        'action_tasks', queryset=TatActionTask.objects.filter(
            status=TatActionTask.STATUS_PENDING,
        ).select_related('assignment__primary_user').prefetch_related(
            'recipients__user',
        ), to_attr='pending_action_tasks',
    ))
    return _scope_tat_queryset(queryset, user, 'tat.home.view') if user else queryset


def _owner(task) -> str:
    if not task:
        return ''
    current = [
        row for row in task.recipients.all()
        if row.routing_generation == task.routing_generation
        and row.inbox_status in {TatActionTaskRecipient.INBOX_UNREAD, TatActionTaskRecipient.INBOX_READ}
    ]
    primary = next((row for row in current if row.kind == TatActionTaskRecipient.KIND_PRIMARY), None)
    row = primary or (current[0] if current else None)
    if not row:
        return ''
    return row.user.get_full_name().strip() or row.user.get_username()


def _row(case, workflow: dict) -> dict:
    stage = next_action(case)
    unresolved = case.configuration_binding_status == TatTrackerCase.CONFIG_UNRESOLVED
    if unresolved:
        product = None
    else:
        product = product_for_case(case)
    task = (getattr(case, 'pending_action_tasks', None) or [None])[0]
    elapsed = stage_tat_minutes(case, stage) if stage else None
    target = stage_target_minutes_for_case(case, workflow, product, stage) if stage else None
    version = case.product_version.version if case.product_version_id else (
        (case.tat_configuration_snapshot or {}).get('product_version') or ''
    )
    return {
        'id': str(case.pk), 'case_reference': case.case_id, 'branch': case.branch,
        'task_id': str(task.pk) if task else '',
        'product': case.product_label or (product.label if product else case.product_key), 'product_key': case.product_key,
        'product_version': version, 'stage': stage.label if stage else 'Complete',
        'stage_key': stage.key if stage else '', 'role': stage.role if stage else '',
        'owner': _owner(task), 'status': case.status,
        'elapsed_minutes': str(elapsed) if elapsed is not None else '',
        'target_minutes': str(target) if target is not None else '',
        'binding_status': case.configuration_binding_status,
        'created_at': case.created_at, 'updated_at': case.updated_at,
    }


def register_data(
    *, group, user: dict | None = None, filters: dict | None = None,
    page: int = 1, page_size: int = 25,
) -> dict:
    filters = filters or {}
    queryset = _base_queryset(group, user)
    if filters.get('branch'):
        queryset = queryset.filter(branch=str(filters['branch']))
    if filters.get('product'):
        queryset = queryset.filter(product_key=str(filters['product']))
    if filters.get('status'):
        queryset = queryset.filter(status=str(filters['status']))
    if filters.get('version'):
        queryset = queryset.filter(product_version_id=str(filters['version']))
    search = str(filters.get('search') or '').strip()
    if search:
        queryset = queryset.filter(case_id__icontains=search)
    workflow = dict(getattr(group, 'workflow', None) or {})
    rows = [_row(case, workflow) for case in queryset.order_by('-updated_at')]
    if filters.get('stage'):
        rows = [row for row in rows if row['stage_key'] == str(filters['stage'])]
    if filters.get('owner'):
        needle = str(filters['owner']).casefold()
        rows = [row for row in rows if needle in row['owner'].casefold()]
    try:
        page_size = int(page_size or 25)
    except (TypeError, ValueError):
        page_size = 25
    page_size = max(10, min(page_size, 100))
    pages = max(1, (len(rows) + page_size - 1) // page_size)
    try:
        page = int(page or 1)
    except (TypeError, ValueError):
        page = 1
    page = max(1, min(page, pages))
    start = (page - 1) * page_size
    selected = rows[start:start + page_size]
    board = {}
    for row in rows:
        board.setdefault(row['stage'], 0)
        board[row['stage']] += 1
    return {
        'items': selected, 'total': len(rows), 'page': page, 'pages': pages,
        'page_size': page_size, 'stage_board': board,
    }


def version_timeline(*, group, version) -> dict:
    """Return one version's stage columns; never merge incompatible versions."""
    if not version:
        return {'columns': [], 'items': []}
    config = getattr(version, 'tat_configuration', None)
    columns = [
        {'key': str(item.get('key') or ''), 'label': str(item.get('label') or item.get('key') or '')}
        for item in (getattr(config, 'stages', None) or []) if item.get('key')
    ]
    cases = operational_tat_cases(TatTrackerCase.objects.filter(
        group_id=str(group.group_id), product_version=version, is_deleted=False,
    )).order_by('-updated_at')[:100]
    return {
        'columns': columns,
        'items': [{
            'case_reference': case.case_id,
            'values': [{
                'complete': bool((case.stage_values or {}).get(column['key'])),
                'value': str((case.stage_values or {}).get(column['key']) or ''),
            } for column in columns],
        } for case in cases],
    }


def export_xlsx(*, group, actor, request_id: str, filters: dict | None = None) -> bytes:
    """Export only the approved operational allowlist; never customer PII/free text."""
    from openpyxl import Workbook

    rows = register_data(group=group, filters=filters, page=1, page_size=100)['items']
    # Export all matching rows in bounded pages without exposing the excluded
    # customer fields held on the underlying case model.
    total = register_data(group=group, filters=filters, page=1, page_size=10)['total']
    if total > 100:
        rows = []
        for page in range(1, ((total + 99) // 100) + 1):
            rows.extend(register_data(group=group, filters=filters, page=page, page_size=100)['items'])
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'TAT Register'
    sheet.append(EXPORT_FIELDS)
    for row in rows:
        sheet.append((
            row['case_reference'], row['branch'], row['product'], row['product_version'],
            row['stage'], row['role'], row['owner'], row['status'],
            row['elapsed_minutes'], row['target_minutes'],
            row['created_at'].isoformat(), row['updated_at'].isoformat(),
        ))
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    output = BytesIO()
    workbook.save(output)
    from core.services.compliance_audit import record_event
    record_event(
        workflow='tat_tracker', action='register.exported', category='data_export', origin='human',
        subject_type='tat_register', subject_id=str(group.pk), actor=actor, authority_user=actor,
        request_id=str(request_id or ''), source_model='GroupSheetConfiguration',
        source_event_id=str(request_id or ''),
        deduplication_key=f'tat-register-export:{group.pk}:{request_id}',
        after_values={
            'group_id': group.group_id, 'filters': dict(filters or {}),
            'fields': list(EXPORT_FIELDS), 'row_count': len(rows),
        },
    )
    return output.getvalue()
