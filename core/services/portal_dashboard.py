"""Capability- and branch-scoped operational dashboard read model."""
from __future__ import annotations

from datetime import datetime, time, timedelta
import uuid

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from core.models import (
    IntegrationOperation,
    InvoiceIdentityReview,
    InvoiceNameChangeItem,
    JawabuFarmerMaster,
    JawabuPipelineEvent,
    WorkflowSlaEscalation,
)
from core.services.jawabu_pipeline import (
    all_cases,
    credit_queue,
    current_workflow_state,
    deferred_queue,
    final_review_queue,
    jbl_visit_queue,
    reappraisal_required_queue,
    requisition_queue,
)
from core.services.workflow_capabilities import effective_capability_keys


def _deferred_work_queue():
    return (deferred_queue() | reappraisal_required_queue()).distinct()


def _reappraisal_for_actor(queryset, capabilities):
    stages = set()
    for capability, stage in (
        ('portal.jbl_visit.write', 'jbl_visit'),
        ('portal.credit.write', 'credit'),
        ('portal.final_review.write', 'final'),
        ('portal.requisition.write', 'order'),
        ('portal.payment.review', 'payment'),
    ):
        if capability in capabilities:
            stages.add(stage)
    return queryset.filter(deferred_stage__in=stages) if stages else queryset.none()


QUEUE_DEFINITIONS = (
    ('jbl', 'Awaiting JBL visit', 'portal.jbl_queue.view', jbl_visit_queue),
    ('credit', 'Credit analysis', 'portal.credit_queue.view', credit_queue),
    ('final', 'Head of Rural review', 'portal.final_review.view', final_review_queue),
    ('requisition', 'Ready for order', 'portal.requisition.view', requisition_queue),
    ('deferred', 'Deferred or flagged', 'portal.deferred.view', _deferred_work_queue),
)


def _branch_scope(queryset, access, *, user=None, capability='portal.case.read'):
    if user is not None:
        from core.services.portal_permissions import scope_portal_case_queryset

        return scope_portal_case_queryset(queryset, user, capability, access=access)
    branches = [str(value).strip() for value in (access or {}).get('branches', []) if str(value).strip()]
    if not branches:
        return queryset
    branch_query = Q()
    for branch in branches:
        branch_query |= Q(branch__iexact=branch)
    return queryset.filter(branch_query)


def _case_payload(farmer, *, reason: str = '') -> dict:
    stage = current_workflow_state(farmer)
    return {
        'id': str(farmer.id),
        'customer_name': farmer.customer_name,
        'branch': farmer.system_branch or farmer.branch,
        'stage': str(stage or '').replace('_', ' ').title(),
        'reason': reason,
        'updated_at': farmer.updated_at.isoformat() if farmer.updated_at else None,
        'url': reverse('portal_case_history_detail', kwargs={'farmer_id': farmer.id}),
    }


def _focused_queue_url(queue_key: str, farmer_id) -> str:
    return f"{reverse('portal_screen', kwargs={'screen': queue_key})}?focus={farmer_id}&attention=1"


def _case_notification(farmer, *, queue_key: str, action: str, severity: str = 'action') -> dict:
    return {
        'key': f'{queue_key}:{farmer.pk}',
        'kind': 'case',
        'farmer_id': str(farmer.pk),
        'queue_key': queue_key,
        'label': farmer.customer_name or 'Unnamed customer',
        'detail': action,
        'context': farmer.system_branch or farmer.branch or '',
        'severity': severity,
        'url': _focused_queue_url(queue_key, farmer.pk),
    }


def _origination_signing_home(user, access, capabilities):
    """Reuse Origination's exact scoped signer queue; Home grants no new access."""
    if not user or 'portal.origination.signing.staff' not in capabilities:
        return [], None
    from core.models import LoanOriginationApplication
    from core.services.origination_access import queue_capabilities, scope_application_queryset
    from core.api.origination_views import _pending_staff_signature_application_ids

    scoped = scope_application_queryset(
        LoanOriginationApplication.objects.select_related('product_definition'),
        user=user, access=access,
    )
    signer_roles = queue_capabilities(user=user, access=access)['staff_signer_roles']
    application_ids = _pending_staff_signature_application_ids(scoped, signer_roles)
    actions = []
    for application in scoped.filter(pk__in=application_ids).order_by('updated_at')[:6]:
        identity = application.identity_snapshot or {}
        actions.append({
            'key': f'origination_signature:{application.pk}',
            'kind': 'origination',
            'label': str(identity.get('name') or application.reference_number),
            'detail': 'Your signature is needed',
            'context': application.branch,
            'workflow': 'Origination',
            'severity': 'action',
            'url': f"{reverse('loan_origination_app')}?queue=my_signatures&application={application.pk}",
        })
    queue = None
    if application_ids:
        queue = {
            'key': 'origination_signatures', 'label': 'My signatures',
            'count': len(application_ids), 'urgent_count': 0,
            'url': f"{reverse('loan_origination_app')}?queue=my_signatures",
            'workflow': 'Origination',
        }
    return actions, queue


def _payment_review_home(user, access, capabilities):
    if 'portal.payment.review' not in capabilities:
        return [], None
    from payments.models import PaymentBatch, PaymentCaseReview
    from core.services.portal_permissions import portal_access_decision

    actions = []
    count = 0
    batches = PaymentBatch.objects.filter(status=PaymentBatch.STATUS_IN_REVIEW).select_related(
        'group_configuration',
    ).prefetch_related('case_memberships__farmer', 'case_memberships__review')
    for batch in batches:
        members = [item for item in batch.case_memberships.all() if item.is_active]
        if not members:
            continue
        if user is not None and not all(
            portal_access_decision(
                user, 'portal.payment.review', access=access, resource=item.farmer,
                group_configuration=batch.group_configuration, enforce_group_scope=True,
            ).allowed for item in members
        ):
            continue
        for item in members:
            review = getattr(item, 'review', None)
            if review and review.decision != PaymentCaseReview.DECISION_PENDING:
                continue
            count += 1
            if len(actions) < 6:
                actions.append({
                    'key': f'payment_review:{item.pk}', 'kind': 'payment',
                    'label': item.farmer.customer_name or 'Unnamed customer',
                    'detail': 'Payment decision needed',
                    'context': f'Payment {batch.payment_number or "draft"}',
                    'workflow': 'Payments', 'severity': 'action',
                    'url': reverse('portal_payment_approval_detail', kwargs={'batch_id': batch.pk}),
                })
    queue = ({
        'key': 'payment_review', 'label': 'Payment cases awaiting review',
        'count': count, 'urgent_count': 0,
        'url': reverse('portal_payment_approvals_screen'), 'workflow': 'Payments',
    } if count else None)
    return actions, queue


def _import_review_home(user, access, capabilities):
    from core.models import GroupSheetConfiguration, JawabuFarmerUploadBatch
    from core.services.portal_permissions import portal_capability_scope

    actions, queues = [], []
    for capability, kind, label, screen in (
        ('portal.farmup.view', 'farmers', 'FarmUp worklists to review', 'farmup'),
        ('portal.imports.view', 'system_export', 'SysUp imports to review', 'imports'),
    ):
        if capability not in capabilities:
            continue
        queryset = JawabuFarmerUploadBatch.objects.filter(
            import_kind=kind, status='pending_review',
            is_current_version=True, is_portal_archived=False,
        )
        if user is not None:
            assignments = portal_capability_scope(user, capability, access=access)['assignments']
            # Batch reviews have no safe branch/product row projection. Such a
            # grant cannot authorize a whole upload merely by matching group.
            assignments = [item for item in assignments if not item['branch'] and not item['product']]
            if not assignments:
                continue
            if not any(item['group_configuration_id'] is None for item in assignments):
                group_ids = GroupSheetConfiguration.objects.filter(
                    pk__in=[item['group_configuration_id'] for item in assignments],
                ).values_list('group_id', flat=True)
                queryset = queryset.filter(group_id__in=group_ids)
        count = queryset.count()
        if not count:
            continue
        queues.append({
            'key': screen, 'label': label, 'count': count,
            'urgent_count': 0, 'workflow': 'FarmUp' if kind == 'farmers' else 'SysUp',
            'url': reverse('portal_screen', kwargs={'screen': screen}),
        })
        for batch in queryset.order_by('created_at')[:3]:
            actions.append({
                'key': f'{screen}:{batch.pk}', 'kind': 'import',
                'label': batch.source_filename or label,
                'detail': 'Review staged rows',
                'context': f'{batch.total_rows} rows',
                'workflow': 'FarmUp' if kind == 'farmers' else 'SysUp',
                'severity': 'action',
                'url': (
                    reverse('portal_farmup_review_screen', kwargs={'batch_id': batch.pk})
                    if kind == 'farmers' else
                    reverse('portal_screen', kwargs={'screen': 'imports'})
                ),
            })
    return actions, queues


def dashboard_payload(user, *, access=None) -> dict:
    capabilities = effective_capability_keys(user, 'jawabu_portal', access=access) if user else {
        capability for _key, _label, capability, _queryset in QUEUE_DEFINITIONS
    } | {
        'portal.case.read', 'portal.invoice_identity.manage', 'portal.health.read',
        'portal.jbl_visit.write', 'portal.credit.write', 'portal.final_review.write',
        'portal.requisition.write', 'portal.hb_action.write',
    }
    scoped_all = _branch_scope(all_cases(), access, user=user, capability='portal.case.read')
    queues = []
    queue_querysets = {}
    legacy_counts = {'jbl_queue': 0, 'credit_queue': 0, 'final_review_queue': 0, 'requisition_queue': 0, 'deferred': 0}
    legacy_key = {
        'jbl': 'jbl_queue', 'credit': 'credit_queue', 'final': 'final_review_queue',
        'requisition': 'requisition_queue', 'deferred': 'deferred',
    }
    for key, label, capability, queryset_factory in QUEUE_DEFINITIONS:
        if capability not in capabilities:
            continue
        queryset = _branch_scope(queryset_factory(), access, user=user, capability=capability)
        queue_querysets[key] = queryset
        count = queryset.count()
        legacy_counts[legacy_key[key]] = count
        queues.append({
            'key': key,
            'label': label,
            'count': count,
            'urgent_count': 0,
            'url': reverse('portal_screen', kwargs={'screen': key}),
        })

    from core.services.portal_permissions import portal_capability_scope, scope_portal_case_queryset

    case_scope = portal_capability_scope(user, 'portal.case.read', access=access) if user else {
        'global_branch': not (access or {}).get('branches'),
        'branches': (access or {}).get('branches', []),
    }
    branch_values = list(case_scope.get('branches') or [])
    escalations = WorkflowSlaEscalation.objects.filter(workflow='jawabu_pipeline', status='pending')
    if user is not None:
        scoped_subject_ids = [str(value) for value in scoped_all.values_list('id', flat=True)]
        escalations = escalations.filter(subject_id__in=scoped_subject_ids)
    elif branch_values:
        escalation_scope = Q()
        for branch in branch_values:
            escalation_scope |= Q(branch__iexact=branch)
        escalations = escalations.filter(escalation_scope)
    escalation_ids = []
    for subject_id in escalations.order_by('-overdue_minutes').values_list('subject_id', flat=True)[:20]:
        try:
            escalation_ids.append(uuid.UUID(str(subject_id)))
        except (TypeError, ValueError, AttributeError):
            continue
    overdue_count = escalations.count()
    for queue in queues:
        queue['urgent_count'] = queue_querysets[queue['key']].filter(id__in=escalation_ids).count()

    attention = []
    reappraisal_cases = JawabuFarmerMaster.objects.none()
    due_count = 0
    reviews = InvoiceIdentityReview.objects.none()
    changes = InvoiceNameChangeItem.objects.none()
    failed_operations = IntegrationOperation.objects.none()
    if overdue_count and 'portal.case.read' in capabilities:
        attention.append({'key': 'sla_overdue', 'label': 'SLA follow-up overdue', 'count': overdue_count, 'severity': 'urgent', 'url': reverse('portal_screen', kwargs={'screen': 'all'})})
    if 'portal.deferred.view' in capabilities:
        reappraisal_cases = _branch_scope(
            reappraisal_required_queue(), access, user=user,
            capability='portal.deferred.view',
        )
        reappraisal_cases = _reappraisal_for_actor(reappraisal_cases, capabilities)
        due_count = reappraisal_cases.count()
        if due_count:
            attention.append({'key': 'reappraisal_due', 'label': 'Reappraisal due', 'count': due_count, 'severity': 'warning', 'url': reverse('portal_screen', kwargs={'screen': 'deferred'})})
    if 'portal.invoice_identity.manage' in capabilities:
        reviews = InvoiceIdentityReview.objects.filter(status='pending').select_related('farmer', 'invoice')
        changes = InvoiceNameChangeItem.objects.filter(status__in=['draft', 'awaiting_replacement']).select_related('farmer', 'original_invoice')
        if user is not None:
            invoice_cases = scope_portal_case_queryset(
                all_cases(), user, 'portal.invoice_identity.manage', access=access,
            )
            reviews = reviews.filter(farmer__in=invoice_cases)
            changes = changes.filter(farmer__in=invoice_cases)
        elif branch_values:
            review_scope = Q()
            change_scope = Q()
            for branch in branch_values:
                review_scope |= Q(farmer__branch__iexact=branch)
                change_scope |= Q(farmer__branch__iexact=branch)
            reviews = reviews.filter(review_scope)
            changes = changes.filter(change_scope)
        if reviews.exists():
            attention.append({'key': 'invoice_identity', 'label': 'Invoice identities to verify', 'count': reviews.count(), 'severity': 'warning', 'url': reverse('portal_invoices_matched')})
        if changes.exists():
            attention.append({'key': 'invoice_name_change', 'label': 'Invoice-name changes open', 'count': changes.count(), 'severity': 'urgent', 'url': reverse('portal_invoices_matched')})
    health_scope = portal_capability_scope(user, 'portal.health.read', access=access) if user else {
        'global_branch': not branch_values, 'global_product': True,
    }
    if (
        'portal.health.read' in capabilities
        and health_scope.get('global_branch')
        and health_scope.get('global_product')
    ):
        from core.services.portal_publication import publication_scheduler_health

        sheet_health = publication_scheduler_health()
        if sheet_health['queued'] and not sheet_health['healthy']:
            attention.append({
                'key': 'portal_sheet_scheduler_stale',
                'label': 'Portal Sheet scheduler needs attention',
                'detail': f"{sheet_health['queued']} Sheet publication(s) queued. Operations/IT: check the once-per-minute scheduler and its last run before retrying cases.",
                'count': sheet_health['queued'], 'severity': 'urgent',
                'url': reverse('portal_screen', kwargs={'screen': 'settings'}),
            })
        failed_operations = IntegrationOperation.objects.filter(status__in=['retryable_failure', 'dead_letter'])
        portal_types = ('jawabu_master_publish', 'jawabu_internal_order_publish')
        candidate_ids = list(failed_operations.filter(
            source_model='JawabuFarmerMaster', operation_type__in=portal_types,
        ).values_list('source_id', flat=True).distinct())
        revisions = {
            str(pk): int(revision or 0)
            for pk, revision in JawabuFarmerMaster.objects.filter(pk__in=candidate_ids).values_list('pk', 'workflow_revision')
        }
        latest = {}
        for row in IntegrationOperation.objects.filter(
            source_model='JawabuFarmerMaster', source_id__in=candidate_ids,
            operation_type__in=portal_types,
        ).order_by('-created_at', '-pk'):
            if row.source_id not in revisions or int((row.metadata or {}).get('workflow_revision', -1)) != revisions[row.source_id]:
                continue
            latest.setdefault((row.source_id, row.operation_type), row)
        current_failed_ids = [row.pk for row in latest.values()
                              if row.status in {'retryable_failure', 'dead_letter'}]
        failed_operations = failed_operations.filter(
            ~Q(source_model='JawabuFarmerMaster', operation_type__in=portal_types)
            | Q(pk__in=current_failed_ids)
        )
        integration_labels = dict(IntegrationOperation.INTEGRATION_CHOICES)
        for item in failed_operations.values('integration', 'operation_type', 'last_error_code').annotate(count=Count('id')).order_by('integration', 'operation_type'):
            matching_operations = failed_operations.filter(
                integration=item['integration'],
                operation_type=item['operation_type'],
                last_error_code=item['last_error_code'],
            )
            retry_operation_ids = list(matching_operations.values_list('pk', flat=True))
            can_retry = (
                item['integration'] == IntegrationOperation.INTEGRATION_GOOGLE_SHEETS
                and 'portal.publication.retry' in capabilities
                and item['last_error_code'] != 'identity_conflict'
            )
            operation = str(item['operation_type'] or 'operation').replace('_', ' ').title()
            integration = integration_labels.get(item['integration'], str(item['integration']).replace('_', ' ').title())
            error_code = ('Identity review required' if item['last_error_code'] == 'identity_conflict'
                          else str(item['last_error_code'] or '').replace('_', ' ').strip())
            failure_contexts = []
            if item['operation_type'] == 'jawabu_master_publish':
                from core.services.jawabu_case_reference import display_case_reference
                for failed in matching_operations.order_by('-updated_at')[:3]:
                    context = (failed.metadata or {}).get('failure_context') or {}
                    reference = display_case_reference(failed.source_id) if failed.source_id else 'Case'
                    if context.get('sheet_tab'):
                        reference = f'{reference} to {str(context["sheet_tab"])[:120]}'
                    field_names = [str(value) for value in (context.get('field_names') or []) if str(value).strip()]
                    if field_names:
                        failure_contexts.append(f'{reference}: fields waiting to sync — {", ".join(field_names[:6])}')
                    elif context.get('detail'):
                        failure_contexts.append(f'{reference}: {context["detail"]}')
                    else:
                        failure_contexts.append(f'{reference}: fields could not be checked before the sync failed.')
            detail_parts = [
                f"{item['count']} failed operation{'s' if item['count'] != 1 else ''}",
                error_code,
                *failure_contexts,
            ]
            attention.append({
                'key': f"integration_failure:{item['integration']}:{item['operation_type']}",
                'label': f'{integration}: {operation}',
                'detail': f"{item['count']} failed operation{'s' if item['count'] != 1 else ''}{f' · {error_code}' if error_code else ''}",
                'count': item['count'], 'severity': 'warning',
                # Settings cannot repair a failed register publication. Give
                # an authorized operator an explicit retry at the warning.
                'action': ({
                    'type': 'publication_retry',
                    'label': 'Retry sync',
                    'operation_ids': [str(row_id) for row_id in retry_operation_ids],
                } if can_retry else None),
                'url': (
                    reverse('portal_case_history_detail', kwargs={'farmer_id': matching_operations.values_list('source_id', flat=True).first()})
                    if item['last_error_code'] == 'identity_conflict' and matching_operations.exists()
                    else reverse('portal_screen', kwargs={'screen': 'settings'}) if not can_retry else ''
                ),
            })
            attention[-1]['detail'] = ' | '.join(part for part in detail_parts if part)

    notification_items = []
    seen_case_ids = set()

    def add_case_notification(farmer, *, queue_key, action, severity='action'):
        farmer_id = str(farmer.pk)
        if farmer_id in seen_case_ids:
            return
        seen_case_ids.add(farmer_id)
        notification_items.append(_case_notification(
            farmer, queue_key=queue_key, action=action, severity=severity,
        ))

    for farmer in scoped_all.filter(id__in=escalation_ids).order_by('updated_at')[:5]:
        stage = current_workflow_state(farmer)
        queue_key = {
            'jbl_visit': 'jbl', 'credit': 'credit', 'final_review': 'final', 'order': 'requisition',
        }.get(stage, 'all')
        if queue_key not in queue_querysets:
            queue_key = 'all'
        add_case_notification(farmer, queue_key=queue_key, action='SLA follow-up overdue', severity='urgent')
    for farmer in reappraisal_cases[:5]:
        add_case_notification(farmer, queue_key='deferred', action='60-day deferral ended · reappraisal required', severity='urgent')
    queue_actions = {
        'jbl': 'JBL visit required', 'credit': 'Credit analysis required',
        'final': 'Order approval required', 'requisition': 'Order preparation required',
    }
    for queue in queues:
        key = queue['key']
        if key == 'deferred':
            continue
        for farmer in queue_querysets[key][:5]:
            add_case_notification(farmer, queue_key=key, action=queue_actions.get(key, queue['label']))
    for review in reviews[:5]:
        notification_items.append({
            'key': f'invoice_identity:{review.pk}', 'kind': 'invoice',
            'label': review.farmer.customer_name or 'Unnamed customer',
            'detail': f'Invoice identity verification · {review.invoice.invoice_no or "invoice"}',
            'context': review.farmer.system_branch or review.farmer.branch or '',
            'severity': 'warning',
            'url': reverse('portal_invoice_screen_detail', kwargs={'invoice_id': review.invoice_id}),
        })
    for change in changes[:5]:
        notification_items.append({
            'key': f'invoice_name_change:{change.pk}', 'kind': 'invoice',
            'label': change.farmer.customer_name or 'Unnamed customer',
            'detail': f'Invoice-name correction · {change.original_invoice.invoice_no or "invoice"}',
            'context': change.farmer.system_branch or change.farmer.branch or '',
            'severity': 'urgent',
            'url': reverse('portal_invoice_screen_detail', kwargs={'invoice_id': change.original_invoice_id}),
        })
    hb_action_count = 0
    hb_actionable_count = 0
    hb_action_urgent_count = 0
    hb_installations = None
    hb_commissioning_due = None
    if 'portal.hb_action.view' in capabilities:
        from hb_operations.services import COMMISSIONING_WAIT_DAYS, scoped_actions

        hb_scoped = scoped_actions(user, access, 'portal.hb_action.view')
        hb_installations = hb_scoped.filter(
            installation_status='open',
        )
        commissioning_threshold = timezone.localdate() - timedelta(days=COMMISSIONING_WAIT_DAYS)
        hb_commissioning = hb_scoped.filter(
            installation_status='installed', installation_date__isnull=False,
        ).filter(commissioning_status='not_commissioned')
        hb_commissioning_due = hb_commissioning.filter(installation_date__lte=commissioning_threshold)
        hb_action_count = hb_installations.count() + hb_commissioning.count()
        hb_actionable_count = hb_installations.count() + hb_commissioning_due.count()
        hb_action_urgent_count = (
            hb_installations.filter(
                planned_installation_date__lt=timezone.localdate(),
            ).count()
            + hb_commissioning.filter(installation_date__lt=commissioning_threshold).count()
        )
        for action in hb_installations[:5]:
            notification_items.append({
                'key': f'hb_action:{action.pk}', 'kind': 'case',
                'farmer_id': str(action.farmer_id), 'queue_key': 'hb_actions',
                'label': action.farmer.customer_name or 'Unnamed customer',
                'detail': 'Installation action required',
                'context': action.farmer.system_branch or action.farmer.branch or '',
                'severity': 'action',
                'url': f"{reverse('portal_hb_action_detail', kwargs={'farmer_id': action.farmer_id})}?workstream=installation",
            })
        for action in hb_commissioning_due[:5]:
            overdue_days = max(0, (
                timezone.localdate()
                - (action.installation_date + timedelta(days=COMMISSIONING_WAIT_DAYS))
            ).days)
            notification_items.append({
                'key': f'hb_commissioning:{action.pk}', 'kind': 'case',
                'farmer_id': str(action.farmer_id), 'queue_key': 'hb_actions',
                'label': action.farmer.customer_name or 'Unnamed customer',
                'detail': ('Commissioning due today' if overdue_days == 0 else f'Commissioning delayed by {overdue_days} day{"s" if overdue_days != 1 else ""}'),
                'context': action.farmer.system_branch or action.farmer.branch or '',
                'severity': 'action' if overdue_days == 0 else 'urgent',
                'url': f"{reverse('portal_hb_action_detail', kwargs={'farmer_id': action.farmer_id})}?workstream=commissioning",
            })
    for item in attention:
        if not str(item.get('key') or '').startswith('integration_failure:'):
            continue
        notification_items.append({**item, 'kind': 'system', 'context': 'Open Settings for system readiness'})

    actionable_queue_count = sum(int(item['count']) for item in queues if item['key'] != 'deferred') + hb_actionable_count
    # Home and the bell use the same scoped task definitions. A view-only
    # capability is not an instruction to act, and overlapping queues must not
    # turn one customer into two notifications.
    action_capabilities = {
        'jbl': 'portal.jbl_visit.write',
        'credit': 'portal.credit.write',
        'final': 'portal.final_review.write',
        'requisition': 'portal.requisition.write',
        'deferred': 'portal.deferred.view',
        'hb_actions': 'portal.hb_action.write',
    }
    allowed_actions = {
        key for key, capability in action_capabilities.items()
        if capability in capabilities
    }
    notification_items = [
        item for item in notification_items
        if item.get('kind') == 'system'
        or (item.get('queue_key') in allowed_actions)
        or (item.get('kind') == 'invoice' and 'portal.invoice_identity.manage' in capabilities)
    ]
    action_case_ids = set()
    for key in ('jbl', 'credit', 'final', 'requisition'):
        if key in allowed_actions and key in queue_querysets:
            action_case_ids.update(str(pk) for pk in queue_querysets[key].values_list('pk', flat=True))
    if 'deferred' in allowed_actions:
        action_case_ids.update(str(pk) for pk in reappraisal_cases.values_list('pk', flat=True))
    if 'hb_actions' in allowed_actions and hb_installations is not None:
        action_case_ids.update(str(pk) for pk in hb_installations.values_list('farmer_id', flat=True))
        action_case_ids.update(str(pk) for pk in hb_commissioning_due.values_list('farmer_id', flat=True))
    notification_count = (
        len(action_case_ids) + reviews.count() + changes.count() + failed_operations.count()
    )

    today = timezone.localdate()
    today_start = timezone.make_aware(datetime.combine(today, time.min))
    seven_days_start = today_start - timedelta(days=6)
    events = JawabuPipelineEvent.objects.filter(farmer__in=scoped_all, occurred_at__gte=seven_days_start) if 'portal.case.read' in capabilities else JawabuPipelineEvent.objects.none()
    today_events = events.filter(occurred_at__gte=today_start).count()
    activity_7d = [
        {'key': row['stage_key'] or 'other', 'label': (row['stage_key'] or 'Other').replace('_', ' ').title(), 'count': row['count']}
        for row in events.values('stage_key').annotate(count=Count('id')).order_by('-count')[:6]
    ]
    metric_definitions = (
        ('visits_completed', 'Visits completed', 'jbl_visit_completed'),
        ('credit_decisions', 'Credit decisions', 'credit_decision_recorded'),
        ('final_decisions', 'Final decisions', 'final_decision_recorded'),
        ('orders_finalized', 'Orders finalized', 'order_assigned'),
    )
    business_metrics = [
        {
            'key': key,
            'label': label,
            'today': events.filter(action=action, occurred_at__gte=today_start).count(),
            'last_7_days': events.filter(action=action).count(),
        }
        for key, label, action in metric_definitions
    ]

    recent_cases = []
    if 'portal.case.read' in capabilities:
        seen = set()
        urgent = scoped_all.filter(id__in=escalation_ids).order_by('updated_at')
        for farmer in urgent[:4]:
            recent_cases.append(_case_payload(farmer, reason='SLA follow-up overdue'))
            seen.add(farmer.id)
        for farmer in scoped_all.exclude(id__in=seen).order_by('-updated_at')[:max(0, 6 - len(recent_cases))]:
            recent_cases.append(_case_payload(farmer, reason='Recently updated'))

    pipeline_distribution = [
        {'key': item['key'], 'label': item['label'], 'count': item['count']}
        for item in queues
    ]
    if 'portal.hb_action.view' in capabilities:
        hb_queue = {
            'key': 'hb_actions', 'label': 'HB installation and commissioning',
            'count': hb_action_count, 'urgent_count': hb_action_urgent_count,
            'url': reverse('portal_hb_actions_screen'),
        }
        queues.append(hb_queue)
        pipeline_distribution.append({
            'key': hb_queue['key'], 'label': hb_queue['label'], 'count': hb_queue['count'],
        })
    legacy_counts.update({
        'reappraisal_required': _branch_scope(
            reappraisal_required_queue(), access, user=user,
            capability='portal.deferred.view',
        ).count(),
        'total': scoped_all.count() if 'portal.case.read' in capabilities else 0,
        'hb_actions': hb_action_count,
    })
    scope_label = (
        ', '.join(branch_values) if branch_values and not case_scope.get('global_branch')
        else 'All authorized branches'
    ) if user is None else 'Tasks within your access'
    active_total = sum(item['count'] for item in queues if item['key'] != 'deferred')
    pipeline = [
        {
            **item,
            'percent': round((item['count'] / active_total) * 100, 1) if active_total else 0,
        }
        for item in queues if item['key'] != 'deferred'
    ]
    origination_actions, origination_queue = _origination_signing_home(user, access, capabilities)
    payment_actions, payment_queue = _payment_review_home(user, access, capabilities)
    import_actions, import_queues = _import_review_home(user, access, capabilities)
    notification_items.extend(origination_actions)
    notification_items.extend(payment_actions)
    notification_items.extend(import_actions)
    notification_count += origination_queue['count'] if origination_queue else 0
    notification_count += payment_queue['count'] if payment_queue else 0
    notification_count += sum(item['count'] for item in import_queues)
    def home_priority(item):
        detail = str(item.get('detail') or '').lower()
        return (
            0 if item.get('severity') == 'urgent' or 'overdue' in detail or 'delayed' in detail else
            1 if 'due today' in detail or 'reappraisal' in detail else 2,
            str(item.get('label') or ''),
        )

    home_actions = sorted(
        (item for item in notification_items if item.get('kind') != 'system'),
        key=home_priority,
    )[:6]
    system_health = [item for item in notification_items if item.get('kind') == 'system']
    home_queues = [
        {**item, 'count': hb_actionable_count if item['key'] == 'hb_actions' else item['count'], 'workflow': 'Portal'} for item in queues
        if item['key'] in allowed_actions
        and (hb_actionable_count if item['key'] == 'hb_actions' else item['count'])
    ]
    if origination_queue:
        home_queues.append(origination_queue)
    if payment_queue:
        home_queues.append(payment_queue)
    home_queues.extend(import_queues)
    workspace_definitions = (
        ('portal.jbl_lead.create', 'Create lead', 'jbl', 'Field visit'),
        ('portal.jbl_followup.view', 'My submitted visits', 'my_visits', 'Field visit'),
        ('portal.payment.review', 'Payment approvals', 'payment_approvals', 'Payments'),
        ('portal.farmup.view', 'FarmUp review', 'farmup', 'Intake'),
        ('portal.imports.view', 'SysUp review', 'imports', 'Intake'),
        ('portal.invoice.view', 'Invoice review', 'invoices', 'Invoices'),
        ('portal.payment.prepare', 'Payment preparation', 'payments', 'Payments'),
        ('portal.documents.sign', 'Document sign-off', 'history', 'Documents'),
    )
    present_keys = {item['key'] for item in home_queues}
    home_shortcuts = [
        {
            'key': screen, 'label': label, 'workflow': workflow,
            'url': reverse('portal_screen', kwargs={'screen': screen}) + ('?create=1' if label == 'Create lead' else ''),
        }
        for capability, label, screen, workflow in workspace_definitions
        if capability in capabilities and screen not in present_keys
        and not (screen == 'payment_approvals' and payment_queue)
    ]
    if 'portal.origination.signing.staff' in capabilities and not origination_queue:
        home_shortcuts.append({
            'key': 'origination', 'label': 'My signatures', 'workflow': 'Origination',
            'url': reverse('loan_origination_app') + '?queue=my_signatures',
        })
    oversight = bool({'portal.final_review.write', 'portal.health.read'} & capabilities)
    return {
        'as_of': timezone.now().isoformat(),
        'scope': {'label': scope_label, 'branches': branch_values},
        'counts': legacy_counts if oversight else {
            key: value for key, value in legacy_counts.items()
            if key in {legacy_key.get(queue_key) for queue_key in allowed_actions}
            or (key == 'hb_actions' and 'hb_actions' in allowed_actions)
        },
        'queues': queues,
        'attention': attention,
        'notification_items': notification_items[:20],
        'notification_count': notification_count,
        'home': {
            'actions': home_actions,
            'queues': home_queues,
            'shortcuts': home_shortcuts,
            'system_health': system_health,
            'oversight': oversight,
            'next_url': (
                home_queues[0]['url'] if home_queues else
                home_shortcuts[0]['url'] if home_shortcuts else
                reverse('portal_screen', kwargs={'screen': 'settings'})
            ),
        },
        'activity_today': {'completed_actions': today_events} if oversight else {},
        'activity_7d': activity_7d if oversight else [],
        'business_metrics': business_metrics if oversight else [],
        'pipeline_distribution': pipeline_distribution if oversight else [],
        'pipeline': pipeline if oversight else [],
        'overview': {
            'total_active': legacy_counts['total'],
            'in_progress': sum(item['count'] for item in queues if item['key'] in {'jbl', 'credit', 'final'}),
            'attention': sum(int(item.get('count') or 0) for item in attention),
            'ready_for_order': legacy_counts['requisition_queue'],
        } if oversight else {},
        'recent_cases': recent_cases[:5] if oversight else [],
    }
