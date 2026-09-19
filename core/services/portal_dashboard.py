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


def dashboard_payload(user, *, access=None) -> dict:
    capabilities = effective_capability_keys(user, 'jawabu_portal', access=access) if user else {
        capability for _key, _label, capability, _queryset in QUEUE_DEFINITIONS
    } | {'portal.case.read', 'portal.invoice_identity.manage', 'portal.health.read'}
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
        failed_operations = IntegrationOperation.objects.filter(status__in=['retryable_failure', 'dead_letter'])
        integration_labels = dict(IntegrationOperation.INTEGRATION_CHOICES)
        for item in failed_operations.values('integration', 'operation_type', 'last_error_code').annotate(count=Count('id')).order_by('integration', 'operation_type'):
            operation = str(item['operation_type'] or 'operation').replace('_', ' ').title()
            integration = integration_labels.get(item['integration'], str(item['integration']).replace('_', ' ').title())
            error_code = str(item['last_error_code'] or '').replace('_', ' ').strip()
            attention.append({
                'key': f"integration_failure:{item['integration']}:{item['operation_type']}",
                'label': f'{integration}: {operation}',
                'detail': f"{item['count']} failed operation{'s' if item['count'] != 1 else ''}{f' · {error_code}' if error_code else ''}",
                'count': item['count'], 'severity': 'warning',
                'url': reverse('portal_screen', kwargs={'screen': 'settings'}),
            })

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
    if 'portal.hb_action.view' in capabilities:
        from hb_operations.services import COMMISSIONING_WAIT_DAYS, scoped_actions

        hb_scoped = scoped_actions(user, access, 'portal.hb_action.view')
        hb_installations = hb_scoped.exclude(
            installation_status__in=['installed', 'closed'],
        )
        commissioning_threshold = timezone.localdate() - timedelta(days=COMMISSIONING_WAIT_DAYS)
        hb_commissioning = hb_scoped.filter(
            installation_status='installed', installation_date__isnull=False,
        ).exclude(commissioning_status='done')
        hb_commissioning_due = hb_commissioning.filter(installation_date__lte=commissioning_threshold)
        hb_action_count = hb_installations.count() + hb_commissioning.count()
        hb_actionable_count = hb_installations.count() + hb_commissioning_due.count()
        hb_action_urgent_count = (
            hb_installations.filter(
                installation_status='scheduled', installation_date__lt=timezone.localdate(),
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
    notification_count = (
        actionable_queue_count + due_count + reviews.count() + changes.count()
        + failed_operations.count()
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
    scope_label = ', '.join(branch_values) if branch_values and not case_scope.get('global_branch') else 'All authorized branches'
    active_total = sum(item['count'] for item in queues if item['key'] != 'deferred')
    pipeline = [
        {
            **item,
            'percent': round((item['count'] / active_total) * 100, 1) if active_total else 0,
        }
        for item in queues if item['key'] != 'deferred'
    ]
    return {
        'as_of': timezone.now().isoformat(),
        'scope': {'label': scope_label, 'branches': branch_values},
        'counts': legacy_counts,
        'queues': queues,
        'attention': attention,
        'notification_items': notification_items[:20],
        'notification_count': notification_count,
        'activity_today': {'completed_actions': today_events},
        'activity_7d': activity_7d,
        'business_metrics': business_metrics,
        'pipeline_distribution': pipeline_distribution,
        'pipeline': pipeline,
        'overview': {
            'total_active': legacy_counts['total'],
            'in_progress': sum(item['count'] for item in queues if item['key'] in {'jbl', 'credit', 'final'}),
            'attention': sum(int(item.get('count') or 0) for item in attention),
            'ready_for_order': legacy_counts['requisition_queue'],
        },
        'recent_cases': recent_cases[:5],
    }
