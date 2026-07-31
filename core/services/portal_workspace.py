"""Private Portal workspace metadata without changing case workflow state.

Saved views, pins, and recents are convenience data.  Every caller must still
resolve current Portal capabilities and branch scope before this module returns
a case or applies a saved view.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Iterable

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from core.models import PortalCaseWorkspace, PortalSavedView
from core.services.compliance_audit import record_event
from core.services.jawabu_pipeline import JawabuWorkflowState, current_workflow_state


MAX_SAVED_VIEWS = 10
MAX_PINNED_CASES = 12
RECENT_CASE_LIMIT = 10
RECENT_RETENTION_DAYS = 90
UNAVAILABLE_PIN_RETENTION_DAYS = 30

ORDERING_VALUES = frozenset({
    PortalSavedView.ORDER_QUEUE_DEFAULT,
    PortalSavedView.ORDER_NEWEST,
})


class PortalWorkspaceError(ValueError):
    """Raised when a private workspace request is malformed or unsafe."""


def _now():
    return timezone.now()


def _audit(*, action: str, subject_type: str, subject_id: str, user, before: dict | None = None,
           after: dict | None = None, deduplication_key: str) -> None:
    record_event(
        workflow='portal', action=action, subject_type=subject_type,
        subject_id=str(subject_id), actor=user, before_values=before or {},
        after_values=after or {}, sensitive=False,
        deduplication_key=deduplication_key,
    )


def _boolean(value: Any, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {'true', '1', 'yes', 'on'}:
            return True
        if normalized in {'false', '0', 'no', 'off', ''}:
            return False
    if value is None:
        return False
    raise PortalWorkspaceError(f'{field} must be true or false.')


def _normalise_view_payload(payload: dict[str, Any], *, options: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PortalWorkspaceError('Workspace view must be a JSON object.')
    name = ' '.join(str(payload.get('name') or '').split())
    if not name:
        raise PortalWorkspaceError('Give this workspace view a name.')
    if len(name) > 60:
        raise PortalWorkspaceError('Workspace view names may contain at most 60 characters.')

    allowed_screens = set(options.get('screens') or ())
    allowed_queues = set(options.get('queues') or ())
    screen = str(payload.get('screen') or '').strip()
    queue = str(payload.get('queue') or '').strip()
    if screen not in allowed_screens:
        raise PortalWorkspaceError('Choose a Portal screen available to your current access.')
    if queue and queue not in allowed_queues:
        raise PortalWorkspaceError('Choose a work queue available to your current access.')

    filters = payload.get('filters') or {}
    if not isinstance(filters, dict) or set(filters).difference({'branch', 'status'}):
        raise PortalWorkspaceError('Only the branch and review list may be saved in a workspace view.')
    branch = str(filters.get('branch') or '').strip()
    status = str(filters.get('status') or '').strip().casefold()
    allowed_branches = {
        str(value).strip().casefold(): str(value).strip()
        for value in options.get('branches') or ()
        if str(value).strip()
    }
    if branch and branch.casefold() not in allowed_branches:
        raise PortalWorkspaceError('Choose a branch within your current Portal scope.')
    if status and status not in set(options.get('review_statuses') or ()):
        raise PortalWorkspaceError('Choose a valid Portal review list.')

    ordering = str(payload.get('ordering') or PortalSavedView.ORDER_QUEUE_DEFAULT).strip()
    if ordering not in ORDERING_VALUES:
        raise PortalWorkspaceError('Choose either queue default or newest first ordering.')
    return {
        'name': name,
        'screen': screen,
        'queue': queue,
        'filters': {
            **({'branch': allowed_branches[branch.casefold()]} if branch else {}),
            **({'status': status} if status else {}),
        },
        'ordering': ordering,
    }


def _view_values(view: PortalSavedView) -> dict[str, Any]:
    return {
        'name': view.name,
        'screen': view.screen,
        'queue': view.queue,
        'filters': view.filters or {},
        'ordering': view.ordering,
        'is_startup': view.is_startup,
    }


def saved_view_availability(view: PortalSavedView, *, options: dict[str, Any]) -> tuple[bool, str]:
    """Treat permission and taxonomy drift identically: preserve, do not apply."""
    try:
        _normalise_view_payload(_view_values(view), options=options)
    except PortalWorkspaceError as exc:
        return False, str(exc)
    return True, ''


def serialize_saved_view(view: PortalSavedView, *, options: dict[str, Any]) -> dict[str, Any]:
    available, unavailable_reason = saved_view_availability(view, options=options)
    return {
        'id': str(view.pk),
        **_view_values(view),
        'available': available,
        'unavailable_reason': unavailable_reason,
        'last_used_at': view.last_used_at.isoformat() if view.last_used_at else '',
        'updated_at': view.updated_at.isoformat() if view.updated_at else '',
    }


@transaction.atomic
def create_saved_view(*, user, payload: dict[str, Any], options: dict[str, Any]) -> PortalSavedView:
    values = _normalise_view_payload(payload, options=options)
    get_user_model().objects.select_for_update().get(pk=user.pk)
    if PortalSavedView.objects.filter(user=user).count() >= MAX_SAVED_VIEWS:
        raise PortalWorkspaceError(f'You can save up to {MAX_SAVED_VIEWS} Portal views.')
    try:
        view = PortalSavedView.objects.create(user=user, **values)
    except IntegrityError as exc:
        raise PortalWorkspaceError('You already have a saved view with this name.') from exc
    _audit(
        action='portal.workspace.view.created', subject_type='portal_saved_view', subject_id=str(view.pk),
        user=user, after=_view_values(view),
        deduplication_key=f'portal-workspace-view:create:{view.pk}',
    )
    return view


@transaction.atomic
def rename_saved_view(*, user, view_id, name: str) -> PortalSavedView:
    view = PortalSavedView.objects.select_for_update().filter(pk=view_id, user=user).first()
    if view is None:
        raise PortalWorkspaceError('Saved view not found.')
    before = _view_values(view)
    clean_name = ' '.join(str(name or '').split())
    if not clean_name:
        raise PortalWorkspaceError('Give this workspace view a name.')
    if len(clean_name) > 60:
        raise PortalWorkspaceError('Workspace view names may contain at most 60 characters.')
    if PortalSavedView.objects.filter(user=user, name__iexact=clean_name).exclude(pk=view.pk).exists():
        raise PortalWorkspaceError('You already have a saved view with this name.')
    view.name = clean_name
    view.save(update_fields=['name', 'updated_at'])
    _audit(
        action='portal.workspace.view.renamed', subject_type='portal_saved_view', subject_id=str(view.pk),
        user=user, before=before, after=_view_values(view),
        deduplication_key=f'portal-workspace-view:rename:{view.pk}:{view.updated_at.isoformat()}',
    )
    return view


@transaction.atomic
def update_saved_view(*, user, view_id, payload: dict[str, Any], options: dict[str, Any]) -> PortalSavedView:
    """Repair a retained view with the user's current valid Portal scope."""
    view = PortalSavedView.objects.select_for_update().filter(pk=view_id, user=user).first()
    if view is None:
        raise PortalWorkspaceError('Saved view not found.')
    before = _view_values(view)
    values = _normalise_view_payload(payload, options=options)
    try:
        for field, value in values.items():
            setattr(view, field, value)
        view.save(update_fields=[*values.keys(), 'updated_at'])
    except IntegrityError as exc:
        raise PortalWorkspaceError('You already have a saved view with this name.') from exc
    _audit(
        action='portal.workspace.view.updated', subject_type='portal_saved_view', subject_id=str(view.pk),
        user=user, before=before, after=_view_values(view),
        deduplication_key=f'portal-workspace-view:update:{view.pk}:{view.updated_at.isoformat()}',
    )
    return view


@transaction.atomic
def set_startup_view(*, user, view_id, options: dict[str, Any]) -> PortalSavedView:
    view = PortalSavedView.objects.select_for_update().filter(pk=view_id, user=user).first()
    if view is None:
        raise PortalWorkspaceError('Saved view not found.')
    available, reason = saved_view_availability(view, options=options)
    if not available:
        raise PortalWorkspaceError(f'This saved view cannot be your startup view: {reason}')
    before = _view_values(view)
    PortalSavedView.objects.filter(user=user, is_startup=True).exclude(pk=view.pk).update(is_startup=False)
    if not view.is_startup:
        view.is_startup = True
        view.save(update_fields=['is_startup', 'updated_at'])
    _audit(
        action='portal.workspace.view.startup_set', subject_type='portal_saved_view', subject_id=str(view.pk),
        user=user, before=before, after=_view_values(view),
        deduplication_key=f'portal-workspace-view:startup:{view.pk}:{view.updated_at.isoformat()}',
    )
    return view


@transaction.atomic
def activate_saved_view(*, user, view_id, options: dict[str, Any]) -> PortalSavedView:
    view = PortalSavedView.objects.select_for_update().filter(pk=view_id, user=user).first()
    if view is None:
        raise PortalWorkspaceError('Saved view not found.')
    available, reason = saved_view_availability(view, options=options)
    if not available:
        raise PortalWorkspaceError(f'This saved view is unavailable: {reason}')
    view.last_used_at = _now()
    view.save(update_fields=['last_used_at', 'updated_at'])
    return view


@transaction.atomic
def delete_saved_view(*, user, view_id) -> None:
    view = PortalSavedView.objects.select_for_update().filter(pk=view_id, user=user).first()
    if view is None:
        raise PortalWorkspaceError('Saved view not found.')
    before = _view_values(view)
    view_id = str(view.pk)
    view.delete()
    _audit(
        action='portal.workspace.view.deleted', subject_type='portal_saved_view', subject_id=view_id,
        user=user, before=before,
        deduplication_key=f'portal-workspace-view:delete:{view_id}:{_now().isoformat()}',
    )


def _is_non_pinnable(farmer) -> bool:
    state = current_workflow_state(farmer)
    return str(farmer.status or '').casefold() == 'inactive' or state in {
        JawabuWorkflowState.REJECTED,
        JawabuWorkflowState.WITHDRAWN,
    }


def _locked_case_workspace_item(*, user, farmer) -> PortalCaseWorkspace:
    item = PortalCaseWorkspace.objects.select_for_update().filter(user=user, farmer=farmer).first()
    if item is not None:
        return item
    try:
        with transaction.atomic():
            return PortalCaseWorkspace.objects.create(user=user, farmer=farmer)
    except IntegrityError:
        return PortalCaseWorkspace.objects.select_for_update().get(user=user, farmer=farmer)


@transaction.atomic
def pin_case(*, user, farmer) -> PortalCaseWorkspace:
    if _is_non_pinnable(farmer):
        raise PortalWorkspaceError('Closed or withdrawn cases cannot be pinned.')
    get_user_model().objects.select_for_update().get(pk=user.pk)
    item = _locked_case_workspace_item(user=user, farmer=farmer)
    if item.pinned and item.unavailable_since is None:
        return item
    active_pins = PortalCaseWorkspace.objects.filter(
        user=user, pinned=True, unavailable_since__isnull=True,
    ).exclude(pk=item.pk).count()
    if active_pins >= MAX_PINNED_CASES:
        raise PortalWorkspaceError(f'You can pin up to {MAX_PINNED_CASES} accessible cases.')
    before = {'pinned': item.pinned}
    now = _now()
    item.pinned = True
    item.pinned_at = now
    item.unavailable_since = None
    item.save(update_fields=['pinned', 'pinned_at', 'unavailable_since', 'updated_at'])
    _audit(
        action='portal.workspace.case.pinned', subject_type='portal_case_workspace', subject_id=str(item.pk),
        user=user, before=before, after={'pinned': True, 'farmer_id': str(farmer.pk)},
        deduplication_key=f'portal-workspace-pin:{item.pk}:{now.isoformat()}',
    )
    return item


@transaction.atomic
def unpin_case(*, user, farmer) -> PortalCaseWorkspace:
    item = PortalCaseWorkspace.objects.select_for_update().filter(user=user, farmer=farmer).first()
    if item is None or not item.pinned:
        raise PortalWorkspaceError('This case is not pinned in your workspace.')
    before = {'pinned': True, 'farmer_id': str(farmer.pk)}
    item.pinned = False
    item.pinned_at = None
    item.unavailable_since = None
    item.save(update_fields=['pinned', 'pinned_at', 'unavailable_since', 'updated_at'])
    _audit(
        action='portal.workspace.case.unpinned', subject_type='portal_case_workspace', subject_id=str(item.pk),
        user=user, before=before, after={'pinned': False, 'farmer_id': str(farmer.pk)},
        deduplication_key=f'portal-workspace-unpin:{item.pk}:{item.updated_at.isoformat()}',
    )
    return item


@transaction.atomic
def record_case_open(*, user, farmer, open_key: str) -> PortalCaseWorkspace | None:
    """Upsert one current recent item; repeat requests for one open are inert."""
    key = str(open_key or '').strip()
    if not key:
        return None
    if len(key) > 64:
        raise PortalWorkspaceError('Workspace open key is too long.')
    item = _locked_case_workspace_item(user=user, farmer=farmer)
    if item.last_open_key == key:
        return item
    now = _now()
    item.last_open_key = key
    item.last_opened_at = now
    item.recent_dismissed_at = None
    item.save(update_fields=['last_open_key', 'last_opened_at', 'recent_dismissed_at', 'updated_at'])
    return item


@transaction.atomic
def dismiss_recent_cases(*, user) -> int:
    now = _now()
    cutoff = now - timedelta(days=RECENT_RETENTION_DAYS)
    count = PortalCaseWorkspace.objects.filter(
        user=user, last_opened_at__gte=cutoff, recent_dismissed_at__isnull=True,
    ).update(recent_dismissed_at=now)
    if count:
        _audit(
            action='portal.workspace.recents.dismissed', subject_type='portal_case_workspace', subject_id=str(user.pk),
            user=user, after={'dismissed_count': count},
            deduplication_key=f'portal-workspace-recents-dismiss:{user.pk}:{now.isoformat()}',
        )
    return count


def _item_payload(item: PortalCaseWorkspace) -> dict[str, Any]:
    farmer = item.farmer
    return {
        'farmer_id': str(farmer.pk),
        'customer_name': str(farmer.customer_name or '').strip() or 'Unnamed customer',
        'branch': str(farmer.branch or '').strip(),
        'workflow_state': current_workflow_state(farmer),
        'pinned': item.pinned,
        'last_opened_at': item.last_opened_at.isoformat() if item.last_opened_at else '',
    }


def refresh_workspace_availability(*, user, accessible_farmer_ids: Iterable[str]) -> list[PortalCaseWorkspace]:
    """Hide inaccessible/closed pins immediately and free their pin slot."""
    accessible = {str(value) for value in accessible_farmer_ids}
    items = list(PortalCaseWorkspace.objects.filter(user=user).select_related('farmer'))
    now = _now()
    for item in items:
        unavailable = str(item.farmer_id) not in accessible or _is_non_pinnable(item.farmer)
        if unavailable and item.unavailable_since is None:
            PortalCaseWorkspace.objects.filter(pk=item.pk, unavailable_since__isnull=True).update(
                unavailable_since=now,
            )
            item.unavailable_since = now
        elif not unavailable and item.unavailable_since is not None:
            PortalCaseWorkspace.objects.filter(pk=item.pk).update(unavailable_since=None)
            item.unavailable_since = None
    return items


def workspace_payload(*, user, accessible_farmer_ids: Iterable[str], options: dict[str, Any]) -> dict[str, Any]:
    """Return only currently accessible personal metadata and save no case data."""
    items = refresh_workspace_availability(user=user, accessible_farmer_ids=accessible_farmer_ids)
    recent_cutoff = _now() - timedelta(days=RECENT_RETENTION_DAYS)
    pinned = [item for item in items if item.pinned and item.unavailable_since is None]
    recent = [
        item for item in items
        if not item.pinned and item.unavailable_since is None and item.recent_dismissed_at is None
        and item.last_opened_at and item.last_opened_at >= recent_cutoff
    ]
    views = list(PortalSavedView.objects.filter(user=user))
    serialized_views = [serialize_saved_view(view, options=options) for view in views]
    startup = next((view for view in serialized_views if view['is_startup'] and view['available']), None)
    return {
        'limits': {
            'saved_views': MAX_SAVED_VIEWS,
            'pinned_cases': MAX_PINNED_CASES,
            'recent_cases': RECENT_CASE_LIMIT,
        },
        'views': serialized_views,
        'startup_view': startup,
        'pinned': [_item_payload(item) for item in pinned[:MAX_PINNED_CASES]],
        'recent': [_item_payload(item) for item in sorted(recent, key=lambda item: item.last_opened_at, reverse=True)[:RECENT_CASE_LIMIT]],
        'summary': {
            'pinned_count': len(pinned),
            'recent_count': len(recent),
        },
    }


@transaction.atomic
def purge_expired_workspace_metadata(*, now=None, apply: bool = True) -> dict[str, int]:
    """Safely remove expired convenience metadata; customer cases are untouched."""
    now = now or _now()
    pin_cutoff = now - timedelta(days=UNAVAILABLE_PIN_RETENTION_DAYS)
    recent_cutoff = now - timedelta(days=RECENT_RETENTION_DAYS)
    stale_pins = PortalCaseWorkspace.objects.filter(
        pinned=True, unavailable_since__isnull=False, unavailable_since__lte=pin_cutoff,
    )
    stale_pin_count = stale_pins.count()
    if apply and stale_pin_count:
        stale_pins.update(pinned=False, pinned_at=None, unavailable_since=None)
    expired = PortalCaseWorkspace.objects.filter(pinned=False).filter(
        Q(last_opened_at__isnull=True) | Q(last_opened_at__lt=recent_cutoff),
    )
    expired_count = expired.count()
    if apply and expired_count:
        expired.delete()
    return {'stale_pins_released': stale_pin_count, 'expired_workspace_rows_deleted': expired_count}


def workspace_data_inventory(*, user) -> dict[str, Any]:
    """Restricted export helper for future staff data-access/investigation tooling."""
    return {
        'saved_views': [
            {
                'name': view.name,
                'screen': view.screen,
                'queue': view.queue,
                'filters': view.filters or {},
                'ordering': view.ordering,
                'is_startup': view.is_startup,
                'created_at': view.created_at.isoformat() if view.created_at else '',
                'updated_at': view.updated_at.isoformat() if view.updated_at else '',
            }
            for view in PortalSavedView.objects.filter(user=user)
        ],
        'case_workspace': [
            {
                'farmer_id': str(item.farmer_id),
                'pinned': item.pinned,
                'last_opened_at': item.last_opened_at.isoformat() if item.last_opened_at else '',
                'recent_dismissed_at': item.recent_dismissed_at.isoformat() if item.recent_dismissed_at else '',
                'retained_until': (
                    (item.last_opened_at + timedelta(days=RECENT_RETENTION_DAYS)).isoformat()
                    if item.last_opened_at else ''
                ),
            }
            for item in PortalCaseWorkspace.objects.filter(user=user)
        ],
    }
