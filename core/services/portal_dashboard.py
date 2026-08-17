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


def dashboard_payload(user, *, access=None) -> dict:
    capabilities = effective_capability_keys(user, 'jawabu_portal', access=access) if user else {
        capability for _key, _label, capability, _queryset in QUEUE_DEFINITIONS
    } | {'portal.case.read', 'portal.invoice_identity.manage', 'portal.health.read'}
    scoped_all = _branch_scope(all_cases(), access, user=user, capability='portal.case.read')
    queues = []
    legacy_counts = {'jbl_queue': 0, 'credit_queue': 0, 'final_review_queue': 0, 'requisition_queue': 0, 'deferred': 0}
    legacy_key = {
        'jbl': 'jbl_queue', 'credit': 'credit_queue', 'final': 'final_review_queue',
        'requisition': 'requisition_queue', 'deferred': 'deferred',
    }
    for key, label, capability, queryset_factory in QUEUE_DEFINITIONS:
        if capability not in capabilities:
            continue
        queryset = _branch_scope(queryset_factory(), access, user=user, capability=capability)
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
        queue_queryset = next(definition[3] for definition in QUEUE_DEFINITIONS if definition[0] == queue['key'])()
        queue_capability = next(definition[2] for definition in QUEUE_DEFINITIONS if definition[0] == queue['key'])
        queue['urgent_count'] = _branch_scope(
            queue_queryset, access, user=user, capability=queue_capability,
        ).filter(id__in=escalation_ids).count()

    attention = []
    if overdue_count and 'portal.case.read' in capabilities:
        attention.append({'key': 'sla_overdue', 'label': 'SLA follow-up overdue', 'count': overdue_count, 'severity': 'urgent', 'url': reverse('portal_screen', kwargs={'screen': 'all'})})
    if 'portal.deferred.view' in capabilities:
        due_count = _branch_scope(
            reappraisal_required_queue(), access, user=user,
            capability='portal.deferred.view',
        ).count()
        if due_count:
            attention.append({'key': 'reappraisal_due', 'label': 'Reappraisal due', 'count': due_count, 'severity': 'warning', 'url': reverse('portal_screen', kwargs={'screen': 'deferred'})})
    if 'portal.invoice_identity.manage' in capabilities:
        reviews = InvoiceIdentityReview.objects.filter(status='pending')
        changes = InvoiceNameChangeItem.objects.filter(status__in=['draft', 'awaiting_replacement'])
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
        failed = IntegrationOperation.objects.filter(status__in=['retryable_failure', 'dead_letter']).count()
        if failed:
            attention.append({'key': 'integration_failure', 'label': 'External operations need attention', 'count': failed, 'severity': 'warning', 'url': reverse('portal_screen', kwargs={'screen': 'dashboard'})})

    today = timezone.localdate()
    today_start = timezone.make_aware(datetime.combine(today, time.min))
    seven_days_start = today_start - timedelta(days=6)
    events = JawabuPipelineEvent.objects.filter(farmer__in=scoped_all, occurred_at__gte=seven_days_start) if 'portal.case.read' in capabilities else JawabuPipelineEvent.objects.none()
    today_events = events.filter(occurred_at__gte=today_start).count()
    activity_7d = [
        {'key': row['stage_key'] or 'other', 'label': (row['stage_key'] or 'Other').replace('_', ' ').title(), 'count': row['count']}
        for row in events.values('stage_key').annotate(count=Count('id')).order_by('-count')[:6]
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
    legacy_counts.update({
        'reappraisal_required': _branch_scope(
            reappraisal_required_queue(), access, user=user,
            capability='portal.deferred.view',
        ).count(),
        'total': scoped_all.count() if 'portal.case.read' in capabilities else 0,
    })
    scope_label = ', '.join(branch_values) if branch_values and not case_scope.get('global_branch') else 'All authorized branches'
    return {
        'as_of': timezone.now().isoformat(),
        'scope': {'label': scope_label, 'branches': branch_values},
        'counts': legacy_counts,
        'queues': queues,
        'attention': attention,
        'activity_today': {'completed_actions': today_events},
        'activity_7d': activity_7d,
        'pipeline_distribution': pipeline_distribution,
        'recent_cases': recent_cases,
    }
