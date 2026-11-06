"""Current Portal publication problems, never another Mini App's operations."""
from django.db.models import OuterRef, Subquery, F
from django.utils import timezone
from datetime import timedelta

from core.models import IntegrationOperation, JawabuFarmerUploadBatch, RequisitionBatch
from core.services.miniapp_recovery import issue, page_payload, request_action, configuration_failure
from core.services.portal_recognition import _scoped_cases
from core.services.portal_publication import SOURCE_MODEL, MASTER_OPERATION, INTERNAL_ORDER_OPERATION
from core.services.workflow_access import workflow_access_decision


def storage_rows(actor, access):
    from core.services.workflow_access import scope_workflow_queryset
    from core.services.portal_imports import ARCHIVE_OPERATION, SOURCE_MODEL as IMPORT_SOURCE
    from core.services.invoice_cleanup import DELETE_OPERATION
    rows = []
    for capability, kind in [('portal.imports.view', 'system_export'), ('portal.farmup.view', 'farmers')]:
        batches = scope_workflow_queryset(JawabuFarmerUploadBatch.objects.filter(import_kind=kind),
            actor, 'jawabu_portal', capability, access=access, group_field='group_id')
        for batch in batches.exclude(archive_error='').filter(archive_file_id=''):
            operation = IntegrationOperation.objects.filter(source_model=IMPORT_SOURCE, operation_type=ARCHIVE_OPERATION,
                source_id=str(batch.pk)).order_by('-created_at').first()
            action = None
            if operation and operation.status in {'pending', 'retryable_failure'} and batch.source_content:
                endpoint = '/api/portal/imports/archive-attempt/' if kind == 'system_export' else '/api/portal/farmup/archive-attempt/'
                action = request_action('Retry saving', endpoint, {'operation_id': str(operation.pk)},
                    'Retry saving this source file to Drive? No source rows will be imported again.')
            rows.append(issue(operation.pk if operation else batch.pk, 'Source file storage',
                status='Processing' if operation and operation.status == 'running' else 'Waiting' if operation and operation.status == 'pending' else 'Needs review',
                detail=f'{batch.source_filename or "Uploaded worklist"} · Saved in Portal; Drive storage needs attention.', action=action,
                steps=['Ask Portal IT to check the shared Drive folder and its access.',
                       'If the original upload is missing or retries are exhausted, review this retained upload in SysUp or FarmUp using its support reference. Do not import its rows again.']))
    cleanup = scope_workflow_queryset(IntegrationOperation.objects.filter(source_model='InvoiceUploadBatch', operation_type=DELETE_OPERATION),
        actor, 'jawabu_portal', 'portal.invoice.write', access=access,
        branch_field='metadata__branch', product_field='metadata__product', group_field='metadata__group_id')
    for operation in cleanup.exclude(status='succeeded'):
        action = request_action('Retry cleanup', '/api/portal/invoice-pool/cleanup/',
            {'operation_id': str(operation.pk), 'retry': True},
            'Retry removing this already-deleted invoice’s unused Drive file? No other invoice or file will be selected.') if operation.status in {'dead_letter', 'retryable_failure'} else None
        rows.append(issue(operation.pk, 'Invoice file cleanup', detail='Invoice removal is saved. Its unused Drive file is still waiting for cleanup.',
            status='Processing' if operation.status == 'running' else 'Needs review' if action else 'Waiting', action=action))
    allowed_ids = {str(pk) for pk in _scoped_cases(actor, 'portal.requisition.write', access).values_list('pk', flat=True)}
    for batch in RequisitionBatch.objects.exclude(drive_upload_error='').exclude(status='cancelled').select_related('group_configuration'):
        members = {str(pk) for pk in batch.farmer_ids or []}
        if not members or not members.issubset(allowed_ids) or not workflow_access_decision(actor, 'jawabu_portal', 'portal.requisition.write',
                access=access, group_configuration=batch.group_configuration).allowed:
            continue
        action = request_action('Retry saving', f'/api/portal/requisition-batches/{batch.pk}/retry-sync/', {'automatic': True},
            'Retry saving the existing order workbook? Its number, cases and approval will not change.') if batch.file_content else None
        rows.append(issue(batch.pk, f'{batch.order_number} · Order storage', detail='The order is saved in the app.', action=action))
    from core.models import DocumentPhysicalSignoff, PaymentDocument
    allowed_documents = {str(pk) for pk in _scoped_cases(actor, 'portal.documents.sign', access).values_list('pk', flat=True)}
    for signoff in DocumentPhysicalSignoff.objects.filter(status__in=['upload_pending', 'upload_failed']).select_related('requisition_batch', 'payment_document'):
        document = signoff.requisition_batch or signoff.payment_document
        members = {str(pk) for pk in document.farmer_ids or []} if document else set()
        if not members or not members.issubset(allowed_documents) or signoff.source_version != document.version:
            continue
        action = request_action('Retry saving', f'/api/portal/document-signoffs/{signoff.pk}/retry/', {},
            'Retry saving this existing signed scan? No new signature or approval will be created.') if signoff.status == 'upload_failed' else None
        rows.append(issue(signoff.pk, 'Signed scan storage', detail='The submitted scan is retained in the app.',
            status='Waiting' if signoff.status == 'upload_pending' else 'Needs review', action=action))
    allowed_payments = {str(pk) for pk in _scoped_cases(actor, 'portal.payment.view', access).values_list('pk', flat=True)}
    for document in PaymentDocument.objects.exclude(error=''):
        members = {str(pk) for pk in document.farmer_ids or []}
        if not members or not members.issubset(allowed_payments):
            continue
        rows.append(issue(document.pk, 'Payment document storage', detail='The payment record is saved; its document needs review.',
            steps=['Ask Portal IT to check Drive access using this document’s support reference.',
                   'Review the existing payment in Document history. Do not create another payment or approve it again.']))
    return rows


def publication_issue(operation, case, *, actor, access):
    from core.services.external_resilience import operation_lease_seconds
    from core.services.portal_publication import _targets_for_farmer, publication_deferral
    from core.services.jawabu_case_reference import display_case_reference
    from portal_legacy.fence import case_blocked
    setup = configuration_failure(operation.last_error_code)
    decision = workflow_access_decision(actor, 'jawabu_portal', 'portal.publication.retry', access=access, resource=case)
    blocked = case_blocked(case)
    enabled = operation.operation_type in _targets_for_farmer(case)
    stale = operation.status == 'running' and operation.last_attempt_at and operation.last_attempt_at <= timezone.now() - timedelta(seconds=operation_lease_seconds())
    action = None
    if decision.allowed and enabled and not blocked and operation.last_error_code != 'identity_conflict' and (operation.status in {'pending', 'dead_letter', 'retryable_failure'} or stale):
        action = request_action('Retry sync', '/api/portal/publication/attempt/',
            {'operation_id': str(operation.pk), 'manual_retry': True},
            ('Repair the Sheet access or named-column configuration first, then retry this update. ' if setup else '')
            + 'Retry this Sheet update? The saved case will not be submitted again.')
    if not enabled:
        waiting = 'Sheet sync is disabled for this register. Enable it in the group configuration.'
    elif blocked:
        waiting = 'This case is held by an unfinished legacy changeover. Resume its import step first.'
    elif operation.last_error_code == 'identity_conflict':
        waiting = 'The matching Sheet row belongs to a different case. Correct its ownership before retrying.'
    elif stale:
        waiting = 'The previous worker stopped reporting. Retry can safely reclaim this update.'
    elif operation.status == 'running':
        waiting = 'A worker is updating this row now.'
    elif operation.status == 'dead_letter':
        waiting = 'Automatic attempts stopped. Retry starts a new attempt and retains the failed history.'
    else:
        deferral = publication_deferral(operation, farmer=case)
        waiting = deferral['waiting_reason'] if deferral['deferred_reason'] != 'queued' else (
            'No Sheet attempt has started. Retry runs it now.' if not operation.attempts else 'Ready to sync. Retry runs a Sheet attempt now.')
    row = issue(operation.pk, display_case_reference(case.pk), detail=case.customer_name or 'Unnamed case',
        status='Configuration required' if setup else 'Retrying' if operation.status == 'running' else 'Waiting' if operation.status in {'pending', 'retryable_failure'} else 'Needs review',
        action=action, steps=(['Ask Portal IT to check Sheet access and the named columns for this case.',
                              'For an identity conflict, review the customer details in All cases before retrying.'] if setup else None))
    row.update(batch_retry=bool(action), waiting_reason=waiting, queued_at=operation.created_at.isoformat(),
               attempts=operation.attempts, retry_replacement=operation.status == 'dead_letter', changes=[], steps=[])
    context = (operation.metadata or {}).get('failure_context') or {}
    if context.get('detail'):
        row['waiting_reason'] += ' ' + context['detail']
    return row


def publication_changes(operation, case):
    """Compare the canonical field plan with retained Sheet-write evidence, never a live Google read."""
    from core.models import LiveSheetRecordChange
    from core.services.portal_publication import _destination_for_farmer
    from core.services.jawabu_pipeline import master_projection_fields, internal_order_projection_fields, MASTER_UPPERCASE_TEXT_FIELDS, _smart_sheet_label, _sheet_cell_value
    from core.services.jawabu_master import normalize_header
    destination = _destination_for_farmer(case, operation.operation_type) or {}
    keys = [str(case.pk)] if operation.operation_type == MASTER_OPERATION else [str(value) for value in (case.duplicate_key, case.national_id, case.primary_phone) if value]
    evidence = LiveSheetRecordChange.objects.filter(group_id=destination.get('group_id', ''), sheet_id=destination.get('spreadsheet', ''),
        sheet_tab=destination.get('tab', ''), record_key__in=keys, status='success').order_by('-created_at', '-pk')
    previous = {}
    for changes in evidence.values_list('changes', flat=True):
        for header, change in (changes or {}).items():
            if isinstance(change, dict) and 'after' in change:
                previous.setdefault(normalize_header(header), (header, change['after']))
    fields = master_projection_fields(case) if operation.operation_type == MASTER_OPERATION else internal_order_projection_fields(case)
    result = []
    for field, (headers, value) in fields.items():
        if not headers:
            continue
        if operation.operation_type == MASTER_OPERATION and field in MASTER_UPPERCASE_TEXT_FIELDS:
            value = _smart_sheet_label(value)
        if field in {'Order Record ID', 'Last Updated At', 'Duplicate Key'}:
            continue
        value = _sheet_cell_value(value)
        match = next((previous[normalize_header(header)] for header in headers if normalize_header(header) in previous), None)
        if match and str(match[1] if match[1] is not None else '').strip() == str(value if value is not None else '').strip():
            continue
        if not match and value in ('', None):
            continue
        result.append({'field':match[0] if match else headers[0], 'before':match[1] if match else None, 'after':value})
    return {'changes':result, 'destination':destination.get('tab', ''), 'comparison_basis':'Last recorded Sheet values → Current saved values'}


def status_payload(actor, access, *, page=1):
    cases = _scoped_cases(actor, 'portal.case.read', access)
    revisions = {str(pk):int(revision or 0) for pk, revision in cases.values_list('pk', 'workflow_revision')}
    # Only the latest publication for the current canonical revision survives.
    current = IntegrationOperation.objects.filter(
        source_model=SOURCE_MODEL, source_id=OuterRef('source_id'), operation_type=OuterRef('operation_type'),
    ).order_by('-created_at', '-pk').values('pk')[:1]
    operations = IntegrationOperation.objects.filter(source_model=SOURCE_MODEL,
        source_id__in=revisions,
        operation_type__in=[MASTER_OPERATION, INTERNAL_ORDER_OPERATION],
    ).annotate(latest=Subquery(current)).filter(pk=F('latest')).exclude(status='succeeded').order_by('created_at', 'pk')
    rows = [{'key':str(op.pk), 'status':'Configuration required' if configuration_failure(op.last_error_code) else
             'Retrying' if op.status == 'running' else 'Waiting' if op.status in {'pending', 'retryable_failure'} else 'Needs review'}
            for op in operations if int((op.metadata or {}).get('workflow_revision', -1)) == revisions.get(op.source_id)]
    rows.extend(storage_rows(actor, access))
    from report_delivery.recovery import recovery_rows
    rows.extend(recovery_rows(actor, 'jawabu_portal'))
    counts = {'waiting': 0, 'processing': 0, 'needs_attention': 0}
    for row in rows:
        row['status_code'] = {'Waiting': 'waiting', 'Retrying': 'processing', 'Processing': 'processing'}.get(row['status'], 'needs_attention')
        counts[row['status_code']] += 1
    payload = page_payload(rows, page)
    operation_map = {str(operation.pk):operation for operation in operations}
    page_ids = [operation_map[row['key']].source_id for row in payload['items'] if row['key'] in operation_map]
    case_map = {str(case.pk):case for case in cases.filter(pk__in=page_ids).select_related('group_configuration')}
    for row in payload['items']:
        operation = operation_map.get(row['key'])
        if operation:
            row.update(publication_issue(operation, case_map[operation.source_id], actor=actor, access=access))
            row.update(publication_changes(operation, case_map[operation.source_id]))
    return {**payload, 'summary': counts}
