"""Governed branch, county, and sub-county resolution and service-area policy."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import (
    BranchServiceArea,
    LocationConfigurationEvent,
    LocationMappingIssue,
    LocationPolicyState,
    OperationalLocation,
    OperationalLocationAlias,
)


class LocationCatalogError(ValueError):
    """Stable location validation error safe for staff-facing responses."""


def normalize_location_value(value: Any) -> str:
    text = unicodedata.normalize('NFKC', str(value or '')).replace('\u2019', "'")
    return re.sub(r'[^a-z0-9]+', '_', text.casefold()).strip('_')


def _record_event(
    *, subject_type: str, subject_id: Any, action: str, actor=None,
    request_id: str = '', before: dict | None = None, after: dict | None = None,
) -> LocationConfigurationEvent:
    event = LocationConfigurationEvent.objects.create(
        subject_type=subject_type,
        subject_id=str(subject_id),
        action=action,
        actor=actor,
        request_id=str(request_id or '').strip()[:128],
        before_values=before or {},
        after_values=after or {},
    )
    try:
        from core.services.compliance_audit import record_event
        record_event(
            workflow='configuration', action=f'global_location.{action}',
            category='configuration', origin='human' if actor else 'system',
            subject_type=subject_type, subject_id=str(subject_id),
            actor=actor, authority_user=actor,
            request_id=str(request_id or '').strip()[:128],
            source_model='LocationConfigurationEvent', source_event_id=str(event.pk),
            deduplication_key=f'global-location:{event.pk}',
            before_values=before or {}, after_values=after or {},
        )
    except Exception as exc:
        raise LocationCatalogError('The location change audit event could not be recorded.') from exc
    return event


def current_policy() -> LocationPolicyState:
    state, _created = LocationPolicyState.objects.get_or_create(pk=1)
    return state


def resolve_location(
    value: Any, *, location_type: str, include_inactive: bool = False,
    parent: OperationalLocation | None = None,
) -> OperationalLocation | None:
    if isinstance(value, OperationalLocation):
        if value.location_type != location_type:
            return None
        return value if include_inactive or value.active else None
    raw = str(value or '').strip()
    if not raw:
        return None
    queryset = OperationalLocation.objects.filter(location_type=location_type)
    if not include_inactive:
        queryset = queryset.filter(active=True)
    by_code = queryset.filter(code__iexact=raw).first()
    if by_code:
        return by_code
    if location_type == 'sub_county' and parent is not None:
        queryset = queryset.filter(parent=parent)
    name_matches = list(queryset.filter(name__iexact=raw)[:2])
    if len(name_matches) == 1:
        return name_matches[0]
    normalized = normalize_location_value(raw)
    aliases = OperationalLocationAlias.objects.select_related('location').filter(
        location_type=location_type,
        normalized_alias=normalized,
        active=True,
    )
    if location_type == 'sub_county' and parent is not None:
        aliases = aliases.filter(parent=parent)
    alias_matches = [
        item.location for item in aliases[:2]
        if include_inactive or item.location.active
    ]
    if len(alias_matches) == 1:
        return alias_matches[0]
    # Canonical-name punctuation normalization remains deterministic and
    # intentionally does not perform fuzzy matching.
    normalized_matches = []
    for candidate in queryset.only('id', 'name', 'code', 'location_type', 'active', 'parent_id'):
        if normalize_location_value(candidate.name) == normalized:
            normalized_matches.append(candidate)
            if len(normalized_matches) > 1:
                return None
    return normalized_matches[0] if normalized_matches else None


def stage_location_mapping_issue(
    value: Any, *, location_type: str, source_workflow: str,
    source_model: str, source_field: str, source_record_id: Any,
    detail: str = '',
) -> LocationMappingIssue | None:
    raw = str(value or '').strip()
    normalized = normalize_location_value(raw)
    if not normalized:
        return None
    issue, _created = LocationMappingIssue.objects.get_or_create(
        location_type=location_type,
        normalized_value=normalized,
        source_model=str(source_model or '')[:120],
        source_field=str(source_field or '')[:80],
        source_record_id=str(source_record_id or '')[:120],
        status=LocationMappingIssue.STATUS_OPEN,
        defaults={
            'raw_value': raw[:255],
            'source_workflow': str(source_workflow or '')[:40],
            'detail': str(detail or ''),
        },
    )
    return issue


def serialize_location(location: OperationalLocation) -> dict[str, Any]:
    return {
        'code': location.code,
        'name': location.name,
        'type': location.location_type,
        'parent_code': location.parent.code if location.parent_id else '',
    }


def location_snapshot(
    *, branch: OperationalLocation | None = None,
    county: OperationalLocation | None = None,
    sub_county: OperationalLocation | None = None,
) -> dict[str, Any]:
    return {
        key: serialize_location(value)
        for key, value in {
            'branch': branch, 'county': county, 'sub_county': sub_county,
        }.items()
        if value is not None
    }


def _active_service_areas(branch: OperationalLocation):
    return BranchServiceArea.objects.select_related('area', 'area__parent').filter(
        branch=branch, active=True, area__active=True,
    )


def branch_covers_area(
    branch: OperationalLocation, *, county: OperationalLocation,
    sub_county: OperationalLocation | None = None,
) -> bool:
    assignments = _active_service_areas(branch)
    if assignments.filter(area=county).exists():
        return True
    if sub_county is not None:
        return assignments.filter(area=sub_county).exists()
    return assignments.filter(area__location_type='sub_county', area__parent=county).exists()


def _authorized_branch_names(user, access: dict | None) -> set[str] | None:
    if access is None or getattr(user, 'is_superuser', False):
        return None
    values = {
        str(value).strip().casefold()
        for value in (access or {}).get('branches', [])
        if str(value).strip()
    }
    return values or None


def location_options(
    *, user=None, access: dict | None = None, branch_value: Any = '',
    county_value: Any = '',
) -> dict[str, Any]:
    allowed_branch_names = _authorized_branch_names(user, access)
    branches = OperationalLocation.objects.filter(
        location_type='branch', active=True,
    ).order_by('sort_order', 'name')
    if allowed_branch_names is not None:
        branches = [item for item in branches if item.name.casefold() in allowed_branch_names]
    else:
        branches = list(branches)
    branch = resolve_location(branch_value, location_type='branch') if branch_value else None
    if branch and allowed_branch_names is not None and branch.name.casefold() not in allowed_branch_names:
        raise LocationCatalogError('Choose a branch within your authorized scope.')
    all_counties = list(OperationalLocation.objects.filter(
        location_type='county', active=True,
    ).order_by('sort_order', 'name'))
    coverage_configured = bool(branch and _active_service_areas(branch).exists())
    override_available = bool(getattr(user, 'is_superuser', False))
    if branch and coverage_configured and not override_available:
        assignments = list(_active_service_areas(branch))
        county_ids = {
            item.area_id if item.area.location_type == 'county' else item.area.parent_id
            for item in assignments
        }
        counties = [item for item in all_counties if item.pk in county_ids]
    elif branch and current_policy().mode == LocationPolicyState.MODE_STRICT and not override_available:
        counties = []
    else:
        counties = all_counties
    county = resolve_location(county_value, location_type='county') if county_value else None
    sub_counties: list[OperationalLocation] = []
    if county:
        all_sub_counties = list(OperationalLocation.objects.filter(
            location_type='sub_county', parent=county, active=True,
        ).select_related('parent').order_by('sort_order', 'name'))
        if branch and coverage_configured and not override_available:
            assignments = _active_service_areas(branch)
            if assignments.filter(area=county).exists():
                sub_counties = all_sub_counties
            else:
                assigned_ids = set(assignments.filter(
                    area__location_type='sub_county', area__parent=county,
                ).values_list('area_id', flat=True))
                sub_counties = [item for item in all_sub_counties if item.pk in assigned_ids]
        elif branch and current_policy().mode == LocationPolicyState.MODE_STRICT and not override_available:
            sub_counties = []
        else:
            sub_counties = all_sub_counties
    return {
        'branches': [serialize_location(item) for item in branches],
        'counties': [serialize_location(item) for item in counties],
        'sub_counties': [serialize_location(item) for item in sub_counties],
        'selected_branch': serialize_location(branch) if branch else None,
        'selected_county': serialize_location(county) if county else None,
        'coverage_configured': coverage_configured,
        'override_available': override_available,
        'policy': {'mode': current_policy().mode},
    }


def location_catalog_manifest() -> dict[str, Any]:
    """Return the public hierarchy and branch coverage used by Mini Apps."""
    alias_map: dict[Any, list[str]] = {}
    for location_id, alias in OperationalLocationAlias.objects.filter(active=True).values_list(
        'location_id', 'alias',
    ):
        alias_map.setdefault(location_id, []).append(alias)

    def manifest_item(location: OperationalLocation) -> dict[str, Any]:
        return {**serialize_location(location), 'aliases': alias_map.get(location.pk, [])}

    counties = list(OperationalLocation.objects.filter(
        location_type='county', active=True,
    ).order_by('sort_order', 'name'))
    sub_counties = list(OperationalLocation.objects.filter(
        location_type='sub_county', active=True,
    ).select_related('parent').order_by('parent__sort_order', 'sort_order', 'name'))
    children: dict[Any, list[dict[str, Any]]] = {}
    for sub_county in sub_counties:
        children.setdefault(sub_county.parent_id, []).append(manifest_item(sub_county))
    assignments: dict[str, list[str]] = {}
    for assignment in BranchServiceArea.objects.select_related('branch', 'area').filter(
        active=True, branch__active=True, area__active=True,
    ):
        assignments.setdefault(assignment.branch.code, []).append(assignment.area.code)
    return {
        'branches': [
            manifest_item(item) for item in OperationalLocation.objects.filter(
                location_type='branch', active=True,
            ).order_by('sort_order', 'name')
        ],
        'counties': [
            {**manifest_item(item), 'sub_counties': children.get(item.pk, [])}
            for item in counties
        ],
        'branch_service_areas': assignments,
        'policy': {'mode': current_policy().mode},
    }


def _unmapped_or_error(
    value: Any, *, location_type: str, source_workflow: str,
    source_model: str, source_field: str, source_record_id: Any,
    parent: OperationalLocation | None = None,
) -> OperationalLocation | None:
    raw = str(value or '').strip()
    if not raw:
        return None
    location = resolve_location(raw, location_type=location_type, parent=parent)
    if location:
        return location
    stage_location_mapping_issue(
        raw, location_type=location_type, source_workflow=source_workflow,
        source_model=source_model, source_field=source_field,
        source_record_id=source_record_id,
        detail='Value did not match a canonical code, name, or active alias.',
    )
    if current_policy().mode == LocationPolicyState.MODE_STRICT:
        raise LocationCatalogError(
            f'Choose an active canonical {location_type.replace("_", "-")}.',
        )
    return None


def validate_location_selection(
    *, branch_value: Any = '', county_value: Any = '', sub_county_value: Any = '',
    source_workflow: str, source_model: str, source_record_id: Any,
    actor=None, override_reason: str = '', request_id: str = '',
    record_policy_event: bool = True,
) -> tuple[OperationalLocation | None, OperationalLocation | None, OperationalLocation | None]:
    branch = _unmapped_or_error(
        branch_value, location_type='branch', source_workflow=source_workflow,
        source_model=source_model, source_field='branch', source_record_id=source_record_id,
    )
    county = _unmapped_or_error(
        county_value, location_type='county', source_workflow=source_workflow,
        source_model=source_model, source_field='county', source_record_id=source_record_id,
    )
    sub_county = _unmapped_or_error(
        sub_county_value, location_type='sub_county', source_workflow=source_workflow,
        source_model=source_model, source_field='sub_county', source_record_id=source_record_id,
        parent=county,
    )
    if sub_county and not county:
        county = sub_county.parent
    if sub_county and county and sub_county.parent_id != county.pk:
        raise LocationCatalogError('Choose a sub-county within the selected county.')
    if branch and county and not branch_covers_area(branch, county=county, sub_county=sub_county):
        reason = str(override_reason or '').strip()
        strict = current_policy().mode == LocationPolicyState.MODE_STRICT
        allowed_override = bool(getattr(actor, 'is_superuser', False) and reason)
        if strict and not allowed_override:
            raise LocationCatalogError('The selected area is outside this branch service area.')
        if record_policy_event:
            _record_event(
                subject_type='branch_service_area', subject_id=branch.pk,
                action='service_area_override' if allowed_override else 'service_area_warning',
                actor=actor, request_id=request_id,
                after={
                    'branch_code': branch.code,
                    'county_code': county.code,
                    'sub_county_code': sub_county.code if sub_county else '',
                    'reason': reason,
                    'policy_mode': current_policy().mode,
                    'source_workflow': source_workflow,
                    'source_model': source_model,
                    'source_record_id': str(source_record_id),
                },
            )
    return branch, county, sub_county


def bind_farmer_location_fields(
    farmer, *, actor=None, request_id: str = '', canonicalize_display: bool = False,
) -> tuple[OperationalLocation | None, OperationalLocation | None, OperationalLocation | None]:
    """Bind a farmer write to canonical refs while retaining audit-mode compatibility."""
    branch, county, sub_county = validate_location_selection(
        branch_value=farmer.branch_ref or farmer.branch,
        county_value=farmer.county_ref or farmer.county,
        sub_county_value=farmer.sub_county_ref or farmer.sub_county,
        source_workflow='jawabu_portal',
        source_model=type(farmer).__name__,
        source_record_id=farmer.pk,
        actor=actor,
        request_id=request_id,
    )
    farmer.branch_ref = branch
    farmer.county_ref = county
    farmer.sub_county_ref = sub_county
    if canonicalize_display:
        if branch:
            farmer.branch = branch.name
        if county:
            farmer.county = county.name
        if sub_county:
            farmer.sub_county = sub_county.name
    return branch, county, sub_county


def catalog_readiness() -> dict[str, Any]:
    from core.models import AccessGrant, JawabuFarmerMaster, LoanOriginationApplication

    active_branches = OperationalLocation.objects.filter(location_type='branch', active=True)
    uncovered = [
        {'code': item.code, 'name': item.name}
        for item in active_branches
        if not BranchServiceArea.objects.filter(branch=item, active=True).exists()
    ]
    open_issues = LocationMappingIssue.objects.filter(status=LocationMappingIssue.STATUS_OPEN).count()
    missing_parents = OperationalLocation.objects.filter(
        location_type='sub_county', active=True, parent__isnull=True,
    ).count()
    reference_gaps = {
        'farmer_branch': JawabuFarmerMaster.objects.exclude(branch='').filter(branch_ref__isnull=True).count(),
        'farmer_county': JawabuFarmerMaster.objects.exclude(county='').filter(county_ref__isnull=True).count(),
        'farmer_sub_county': JawabuFarmerMaster.objects.exclude(sub_county='').filter(sub_county_ref__isnull=True).count(),
        'access_branch': AccessGrant.objects.exclude(branch__in=['', '*', 'all', 'All', 'global', 'Global']).filter(branch_ref__isnull=True).count(),
        'origination_branch': LoanOriginationApplication.objects.exclude(branch='').filter(branch_ref__isnull=True).count(),
    }
    canonical_counts = {
        'counties': OperationalLocation.objects.filter(location_type='county', active=True).count(),
        'sub_counties': OperationalLocation.objects.filter(location_type='sub_county', active=True).count(),
    }
    ready = (
        not uncovered and open_issues == 0 and missing_parents == 0
        and not any(reference_gaps.values())
        and canonical_counts == {'counties': 47, 'sub_counties': 349}
    )
    return {
        'ready': ready,
        'uncovered_branches': uncovered,
        'open_mapping_issues': open_issues,
        'sub_counties_without_parent': missing_parents,
        'canonical_reference_gaps': reference_gaps,
        'canonical_counts': canonical_counts,
    }


@transaction.atomic
def resolve_mapping_issue(
    issue: LocationMappingIssue, *, location: OperationalLocation, actor,
    request_id: str = '',
) -> LocationMappingIssue:
    """Link a reviewed legacy value without rewriting its historical display text."""
    issue = LocationMappingIssue.objects.select_for_update().get(pk=issue.pk)
    if issue.status != LocationMappingIssue.STATUS_OPEN:
        return issue
    if location.location_type != issue.location_type:
        raise LocationCatalogError('Choose a canonical location with the same type as the issue.')
    model_map = {
        'JawabuFarmerMaster': ('core', 'JawabuFarmerMaster'),
        'AccessGrant': ('core', 'AccessGrant'),
        'LoanOriginationApplication': ('core', 'LoanOriginationApplication'),
        'OrderApprovalUpdate': ('core', 'OrderApprovalUpdate'),
    }
    target = model_map.get(issue.source_model)
    if target:
        from django.apps import apps
        model = apps.get_model(*target)
        ref_field = {
            'branch': 'branch_ref_id',
            'county': 'county_ref_id',
            'sub_county': 'sub_county_ref_id',
        }[issue.location_type]
        updates = {ref_field: location.pk}
        if any(field.name == 'location_snapshot' for field in model._meta.fields):
            record = model.objects.filter(pk=issue.source_record_id).only('location_snapshot').first()
            if record:
                snapshot = dict(record.location_snapshot or {})
                snapshot[issue.location_type] = serialize_location(location)
                updates['location_snapshot'] = snapshot
        model.objects.filter(pk=issue.source_record_id).update(**updates)
    issue.location = location
    issue.status = LocationMappingIssue.STATUS_RESOLVED
    issue.resolved_by = actor
    issue.resolved_at = timezone.now()
    issue.save(update_fields=['location', 'status', 'resolved_by', 'resolved_at'])
    _record_event(
        subject_type='location_mapping_issue', subject_id=issue.pk,
        action='mapping_issue_resolved', actor=actor, request_id=request_id,
        after={'location_code': location.code, 'source_model': issue.source_model,
               'source_record_id': issue.source_record_id, 'source_field': issue.source_field},
    )
    return issue


@transaction.atomic
def publish_policy(*, mode: str, actor, request_id: str = '') -> LocationPolicyState:
    if not getattr(actor, 'is_superuser', False):
        raise LocationCatalogError('Only a Django Superuser may publish location policy.')
    if mode not in {LocationPolicyState.MODE_AUDIT, LocationPolicyState.MODE_STRICT}:
        raise LocationCatalogError('Choose audit or strict location enforcement.')
    if mode == LocationPolicyState.MODE_STRICT:
        readiness = catalog_readiness()
        if not readiness['ready']:
            raise LocationCatalogError('Resolve location readiness issues before enabling strict enforcement.')
    state, _created = LocationPolicyState.objects.select_for_update().get_or_create(pk=1)
    before = {'mode': state.mode}
    if state.mode == mode:
        return state
    state.mode = mode
    state.updated_by = actor
    state.save(update_fields=['mode', 'updated_by', 'updated_at'])
    _record_event(
        subject_type='location_policy', subject_id=state.pk,
        action='policy_published', actor=actor, request_id=request_id,
        before=before, after={'mode': state.mode},
    )
    return state
