from __future__ import annotations

from django.db import transaction

from core.models import (
    TatConfigurationEvent,
    TatPresentationSettings,
    WorkflowConfigurationChangeRequest,
)


INITIAL_REASON = 'Initial migration — business-hours TAT retained as enabled.'


REPORT_PANEL_ORDER = (
    'trend', 'case_progression', 'backlog_age', 'sla_compliance', 'tat_percentiles',
    'stage_target', 'explorer', 'heatmap', 'target_review_signals', 'oldest_cases',
)


def validate_report_panel_order(value):
    order = list(value) if isinstance(value, (list, tuple)) else []
    if len(order) != len(REPORT_PANEL_ORDER) or set(order) != set(REPORT_PANEL_ORDER):
        raise ValueError('Include every TAT report panel exactly once.')
    return order


def presentation_settings() -> dict:
    """Return the global TAT presentation policy without creating rows on reads."""
    row = TatPresentationSettings.objects.filter(singleton=1).first()
    if row is None:
        return {
            'business_time_enabled': True,
            'near_target_percent': 80,
            'report_panel_order': list(REPORT_PANEL_ORDER),
            'revision': 0,
            'updated_at': '',
        }
    return {
        'business_time_enabled': bool(row.business_time_enabled),
        'near_target_percent': int(row.near_target_percent),
        'report_panel_order': list(row.report_panel_order or REPORT_PANEL_ORDER),
        'revision': int(row.revision),
        'updated_at': row.updated_at.isoformat() if row.updated_at else '',
    }


def business_time_enabled() -> bool:
    return bool(presentation_settings()['business_time_enabled'])


def pending_business_calendar_proposals():
    return WorkflowConfigurationChangeRequest.objects.filter(
        workflow=WorkflowConfigurationChangeRequest.WORKFLOW_TAT,
        setting_key=WorkflowConfigurationChangeRequest.SETTING_HOLIDAYS,
        status=WorkflowConfigurationChangeRequest.STATUS_PENDING,
    )


@transaction.atomic
def update_presentation_settings(
    *, actor, business_time_visible: bool, reason: str, expected_revision: int,
    near_target_percent: int | None = None,
    report_panel_order=None,
) -> TatPresentationSettings:
    if not actor or not actor.is_active or not actor.is_superuser:
        raise PermissionError('Only an active Superuser may change global TAT presentation settings.')
    clean_reason = ' '.join(str(reason or '').split())
    if len(clean_reason) < 8:
        raise ValueError('Provide a short reason for this global TAT presentation change.')

    row = TatPresentationSettings.objects.select_for_update().get(singleton=1)
    if int(expected_revision) != int(row.revision):
        raise ValueError('TAT presentation settings changed. Reload and review the current value before saving.')
    desired = bool(business_time_visible)
    desired_near = int(row.near_target_percent if near_target_percent is None else near_target_percent)
    current_order = list(row.report_panel_order or REPORT_PANEL_ORDER)
    desired_order = validate_report_panel_order(report_panel_order if report_panel_order is not None else current_order)
    if not 50 <= desired_near <= 99:
        raise ValueError('Near-target percentage must be between 50 and 99.')
    if desired == bool(row.business_time_enabled) and desired_near == int(row.near_target_percent) and desired_order == current_order:
        raise ValueError('The global TAT presentation settings are unchanged.')
    if not desired and pending_business_calendar_proposals().select_for_update().exists():
        raise ValueError(
            'Resolve the pending Business Calendar proposal(s) before hiding business-hours TAT.'
        )

    before = {
        'business_time_enabled': bool(row.business_time_enabled),
        'near_target_percent': int(row.near_target_percent),
        'report_panel_order': current_order,
        'revision': int(row.revision),
    }
    row.business_time_enabled = desired
    row.near_target_percent = desired_near
    row.report_panel_order = desired_order
    row.revision += 1
    row.change_reason = clean_reason
    row.updated_by = actor
    row.save(update_fields=[
        'business_time_enabled', 'near_target_percent', 'report_panel_order', 'revision', 'change_reason', 'updated_by', 'updated_at',
    ])
    after = {
        'business_time_enabled': bool(row.business_time_enabled),
        'near_target_percent': int(row.near_target_percent),
        'report_panel_order': list(row.report_panel_order),
        'revision': int(row.revision),
    }
    business_time_changed = before['business_time_enabled'] != after['business_time_enabled']
    near_target_changed = before['near_target_percent'] != after['near_target_percent']
    order_changed = before['report_panel_order'] != after['report_panel_order']
    action = (
        'tat.presentation.changed' if sum((business_time_changed, near_target_changed, order_changed)) > 1
        else 'tat.presentation.business_time.changed' if business_time_changed
        else 'tat.presentation.near_target.changed' if near_target_changed
        else 'tat.presentation.report_order.changed'
    )
    TatConfigurationEvent.objects.create(
        action=action,
        actor=actor,
        reason=clean_reason,
        before_snapshot=before,
        after_snapshot=after,
        metadata={'scope': 'global'},
    )
    from core.services.compliance_audit import record_event
    record_event(
        workflow='tat_tracker',
        action=action,
        category='configuration',
        origin='human',
        subject_type='tat_presentation_settings',
        subject_id='1',
        actor=actor,
        authority_user=actor,
        deduplication_key=f'tat-presentation:{row.revision}',
        before_values=before,
        after_values=after,
        metadata={'reason': clean_reason, 'scope': 'global'},
        sensitive=False,
    )
    if near_target_changed:
        from datetime import timedelta
        from django.utils import timezone
        from core.models import WorkflowTatMetricRebuildRequest
        today = timezone.localdate()
        WorkflowTatMetricRebuildRequest.objects.get_or_create(
            request_key=f'presentation:{row.revision}',
            defaults={
                'case': None, 'correction_revision': row.revision,
                'date_from': today - timedelta(days=364), 'date_to': today,
                'next_date': today - timedelta(days=364),
            },
        )
    return row
