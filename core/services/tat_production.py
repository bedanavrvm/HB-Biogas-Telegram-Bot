"""Read-only TAT production-readiness checks with no external side effects."""

from __future__ import annotations

from datetime import timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Q
from django.utils import timezone

from core.models import (
    AccessGrant,
    GroupSheetConfiguration,
    SheetRegisterContract,
    TatNotificationProcessorRun,
    TatPrivateAlertConnection,
    TatResponsibilityAssignment,
    TatTrackerCase,
    TatUpdateSideEffectDispatch,
    WorkflowDataModeState,
    WORKFLOW_DATA_MODE_PRODUCTION,
)
from core.production import ReadinessIssue, _blank_or_placeholder
from core.services.tat_responsibilities import configuration_issues, stage_catalog
from core.services.tat_tracker import is_tat_tracker_workflow


VALID_NOTIFICATION_MODES = {'group', 'shadow', 'hybrid'}


def _active_assignment_candidates(*, group, branch: str, product_key: str, stage_key: str, role: str):
    now = timezone.now()
    rows = TatResponsibilityAssignment.objects.filter(
        group_configuration=group,
        branch__iexact=branch,
        role__iexact=role,
        active=True,
        effective_from__lte=now,
    ).filter(Q(effective_until__isnull=True) | Q(effective_until__gt=now)).select_related(
        'primary_user', 'primary_user__staff_profile', 'group_configuration',
    ).prefetch_related('backups__user', 'backups__user__staff_profile')
    ranked = []
    for assignment in rows:
        if assignment.product_key and assignment.product_key.casefold() != product_key.casefold():
            continue
        if assignment.stage_key and assignment.stage_key != stage_key:
            continue
        specificity = int(bool(assignment.product_key)) + (2 * int(bool(assignment.stage_key)))
        ranked.append((specificity, assignment))
    if not ranked:
        return []
    highest = max(item[0] for item in ranked)
    return [assignment for specificity, assignment in ranked if specificity == highest]


def _grant_covers(*, user_id=None, group, branch: str, product_key: str, role: str) -> bool:
    grants = AccessGrant.objects.filter(
        workflow='tat_tracker', active=True, user__is_active=True, role__iexact=role,
    ).filter(Q(group_configuration__isnull=True) | Q(group_configuration=group))
    if user_id:
        grants = grants.filter(user_id=user_id)
    grants = grants.filter(Q(branch='') | Q(branch__iexact=branch))
    grants = grants.filter(Q(product='') | Q(product__iexact=product_key))
    return grants.exists()


def _group_scope_issues(group) -> list[ReadinessIssue]:
    issues: list[ReadinessIssue] = []
    workflow = dict(group.workflow or {})
    group_label = group.display_name or group.group_id
    mode = str(workflow.get('tat_notification_mode') or 'group').strip().lower()
    if mode not in VALID_NOTIFICATION_MODES:
        issues.append(ReadinessIssue(
            'error', 'tat-notification-mode',
            f'{group_label}: notification mode must be group, shadow, or hybrid.',
        ))
    branches = [str(item).strip() for item in workflow.get('branches') or [] if str(item).strip()]
    catalog = stage_catalog(workflow)
    if not branches:
        issues.append(ReadinessIssue(
            'error', 'tat-branches', f'{group_label}: configure at least one governed branch.',
        ))
    if not catalog:
        issues.append(ReadinessIssue(
            'error', 'tat-products', f'{group_label}: configure at least one TAT product and stage.',
        ))
        return issues

    if group.tat_sheet_projection_enabled and not SheetRegisterContract.objects.filter(
        group_configuration=group,
        subject_type=SheetRegisterContract.SUBJECT_TAT_CASE,
        enabled=True,
    ).exists():
        issues.append(ReadinessIssue(
            'error', 'tat-sheet-contract',
            f'{group_label}: enable a governed TAT Sheet register contract before production.',
        ))

    unresolved_count = TatTrackerCase.objects.filter(
        group_id=group.group_id, is_deleted=False,
        configuration_binding_status=TatTrackerCase.CONFIG_UNRESOLVED,
    ).count()
    if unresolved_count:
        issues.append(ReadinessIssue(
            'error', 'tat-configuration-unresolved',
            f'{group_label}: {unresolved_count} case(s) have no verified TAT configuration and are read-only.',
        ))
    assumed_count = TatTrackerCase.objects.filter(
        group_id=group.group_id, is_deleted=False,
        configuration_binding_status=TatTrackerCase.CONFIG_LEGACY_ASSUMED,
    ).count()
    if assumed_count:
        issues.append(ReadinessIssue(
            'warning', 'tat-configuration-legacy-assumed',
            f'{group_label}: {assumed_count} legacy case(s) still use an assumed configuration.',
        ))

    routing_enabled = mode in {'shadow', 'hybrid'}
    private_delivery_enabled = mode == 'hybrid'
    assignments = TatResponsibilityAssignment.objects.none()
    if routing_enabled:
        assignments = TatResponsibilityAssignment.objects.filter(
            group_configuration=group,
        ).select_related('group_configuration', 'primary_user')
        for category, rows in configuration_issues(assignments).items():
            for assignment, message in rows:
                issues.append(ReadinessIssue(
                    'error', f'tat-responsibility-{category}',
                    f'{group_label}: responsibility {assignment.pk} is invalid. {message}',
                ))

    checked = set()
    for row in catalog:
        product_key = row['product_key']
        stage_key = row['stage_key']
        role = row['role']
        for branch in branches:
            scope = (branch.casefold(), product_key.casefold(), stage_key, role)
            if scope in checked:
                continue
            checked.add(scope)
            prefix = f'{group_label}: {branch}/{product_key}/{stage_key}/{role}'
            if not _grant_covers(
                group=group, branch=branch, product_key=product_key, role=role,
            ):
                issues.append(ReadinessIssue(
                    'error', 'tat-access-coverage', f'{prefix} has no active AccessGrant coverage.',
                ))
            if not routing_enabled:
                continue
            winners = _active_assignment_candidates(
                group=group, branch=branch, product_key=product_key,
                stage_key=stage_key, role=role,
            )
            if not winners:
                issues.append(ReadinessIssue(
                    'error', 'tat-responsibility-missing', f'{prefix} has no active responsibility owner.',
                ))
                continue
            if len(winners) > 1:
                issues.append(ReadinessIssue(
                    'error', 'tat-responsibility-ambiguous',
                    f'{prefix} has {len(winners)} equally specific responsibility owners.',
                ))
                continue
            assignment = winners[0]
            if not _grant_covers(
                user_id=assignment.primary_user_id, group=group, branch=branch,
                product_key=product_key, role=role,
            ):
                issues.append(ReadinessIssue(
                    'error', 'tat-primary-access',
                    f'{prefix} primary owner lacks matching active access.',
                ))
            if private_delivery_enabled:
                connection = TatPrivateAlertConnection.objects.filter(
                    user_id=assignment.primary_user_id,
                ).first()
                if not connection or connection.status != TatPrivateAlertConnection.STATUS_CONNECTED:
                    issues.append(ReadinessIssue(
                        'error', 'tat-private-alert-connection',
                        f'{prefix} primary owner has not connected private Telegram alerts.',
                    ))
    return issues


def tat_production_readiness_issues(
    settings, *, allow_pending_migrations: bool = False,
) -> list[ReadinessIssue]:
    """Return local configuration/database issues; never call Telegram or Google."""
    issues: list[ReadinessIssue] = []

    def error(code: str, message: str) -> None:
        issues.append(ReadinessIssue('error', code, message))

    def warning(code: str, message: str) -> None:
        issues.append(ReadinessIssue('warning', code, message))

    if _blank_or_placeholder(getattr(settings, 'TAT_TRACKER_MINI_APP_SHORT_NAME', '')):
        error('tat-miniapp-short-name', 'TAT_TRACKER_MINI_APP_SHORT_NAME must match BotFather.')
    if not getattr(settings, 'TAT_TRACKER_WEBAPP_REQUIRE_TELEGRAM_AUTH', False):
        error('tat-telegram-auth', 'TAT_TRACKER_WEBAPP_REQUIRE_TELEGRAM_AUTH must be enabled.')
    if int(getattr(settings, 'TAT_TRACKER_WEBAPP_AUTH_MAX_AGE_SECONDS', 0)) <= 0:
        error('tat-auth-age', 'TAT_TRACKER_WEBAPP_AUTH_MAX_AGE_SECONDS must be positive.')
    if not getattr(settings, 'TAT_NOTIFICATION_SCHEDULER_REQUIRED', False):
        error(
            'tat-notification-scheduler-required',
            'Enable TAT_NOTIFICATION_SCHEDULER_REQUIRED after provisioning the one-minute runner.',
        )
    if int(getattr(settings, 'TAT_NOTIFICATION_PROCESSOR_LOCK_SECONDS', 0)) < 60:
        error('tat-notification-lock', 'TAT notification processor lock must be at least 60 seconds.')
    if int(getattr(settings, 'TAT_NOTIFICATION_SCHEDULER_MAX_SILENCE_SECONDS', 0)) < 120:
        error('tat-notification-silence', 'TAT scheduler silence threshold must be at least 120 seconds.')
    if not getattr(settings, 'SENTRY_DSN', ''):
        warning('tat-server-monitoring', 'Configure SENTRY_DSN so runner failures raise an operational alert.')

    try:
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
    except Exception:
        error('tat-migration-check', 'Could not determine the database migration state.')
        return issues
    if pending and not allow_pending_migrations:
        error('tat-migrations', f'{len(pending)} database migration(s) are unapplied.')
        return issues

    state = WorkflowDataModeState.objects.filter(pk=WorkflowDataModeState.SINGLETON_PK).first()
    if not state or state.tat_mode != WORKFLOW_DATA_MODE_PRODUCTION:
        error('tat-data-mode', 'TAT workflow data mode must be Production before go-live.')

    groups = [
        group for group in GroupSheetConfiguration.objects.filter(enabled=True)
        if is_tat_tracker_workflow(group)
    ]
    if not groups:
        error('tat-group', 'Configure and enable at least one TAT Tracker group.')
    for group in groups:
        issues.extend(_group_scope_issues(group))

    if getattr(settings, 'TAT_NOTIFICATION_SCHEDULER_REQUIRED', False):
        max_silence = max(120, int(settings.TAT_NOTIFICATION_SCHEDULER_MAX_SILENCE_SECONDS))
        recent = TatNotificationProcessorRun.objects.filter(
            status=TatNotificationProcessorRun.STATUS_SUCCEEDED,
            completed_at__gte=timezone.now() - timedelta(seconds=max_silence),
        ).order_by('-completed_at').first()
        if not recent:
            error(
                'tat-notification-scheduler-stale',
                f'No successful TAT notification run was recorded in the last {max_silence} seconds.',
            )
        active = TatNotificationProcessorRun.objects.filter(
            active_lock_key=TatNotificationProcessorRun.LOCK_KEY,
            started_at__lt=timezone.now() - timedelta(
                seconds=max(60, int(settings.TAT_NOTIFICATION_PROCESSOR_LOCK_SECONDS)),
            ),
        ).exists()
        if active:
            error('tat-notification-stale-lock', 'The TAT notification processor holds an expired lock.')
        attention_count = TatUpdateSideEffectDispatch.objects.filter(
            status=TatUpdateSideEffectDispatch.STATUS_NEEDS_ATTENTION,
        ).count()
        if attention_count:
            error(
                'tat-update-dispatch-attention',
                f'{attention_count} TAT background update dispatch(es) need Superuser attention.',
            )

    return issues
