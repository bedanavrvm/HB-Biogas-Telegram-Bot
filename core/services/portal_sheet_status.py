"""Compact Portal register labels; never workflow or approval authority."""

from django.db import models


class PortalSheetStatus(models.TextChoices):
    AWAITING_VISIT = 'Awaiting JBL Visit', 'Awaiting JBL Visit'
    DEFERRED = 'Deferred', 'Deferred'
    REJECTED = 'Rejected', 'Rejected'
    CANCELLED = 'Cancelled/Withdrawn', 'Cancelled/Withdrawn'
    ORDER_PROCESSING = 'Approved — Order Processing', 'Approved — Order Processing'
    INSTALLING = 'Installation in Progress', 'Installation in Progress'
    INSTALLED = 'Installed — Awaiting Commissioning', 'Installed — Awaiting Commissioning'
    COMMISSIONED = 'Commissioned', 'Commissioned'
    LEGACY = 'Legacy', 'Legacy'
    DEPOSIT_PENDING = 'Pending Minimum Deposit', 'Pending Minimum Deposit'
    OPTED_OTHER = 'Opted for Other', 'Opted for Other'
    UNDER_REVIEW = 'Under Review', 'Under Review'


def _reported_legacy_status(farmer):
    """Expose consistent retained outcomes without inventing their stage.

    Date warnings remain in the Mini App. Conflicting outcomes/fulfilment or
    conflicting linked source rows still have no reliable current position.
    """
    from portal_legacy.services import effective_values
    from portal_legacy.workbook import propose

    cached = getattr(farmer, '_prefetched_objects_cache', {}).get('legacy_records')
    rows = cached if cached is not None else farmer.legacy_records.prefetch_related('events').all()
    statuses = set()
    for row in rows:
        if row.committed_at is None:
            continue
        values = effective_values(row)
        proposal = propose(values)
        outcome = proposal['outcome'].strip().upper()
        physical = str(values.get('installation_status') or '').strip().upper()
        commissioning = str(values.get('commissioning_status') or '').strip().upper()
        later_facts = bool(proposal['fields'].get('order_number') or physical == 'INSTALLED'
                           or commissioning == 'COMMISSIONED')
        negative = {'REJECTED', 'DEFERRED / ON HOLD', 'WITHDRAWN', 'CANCELLED',
                    'CLIENT WITHDREW', 'OPTED FOR CASH', 'OPTED FOR OTHER PARTNER'}
        if (outcome in negative and later_facts) or any(
            issue.startswith('Comment decisions need reconciliation')
            for issue in proposal['issues']
        ):
            return PortalSheetStatus.LEGACY
        if commissioning == 'COMMISSIONED':
            if physical not in {'', 'INSTALLED'}:
                return PortalSheetStatus.LEGACY
            status = PortalSheetStatus.COMMISSIONED
        elif physical == 'INSTALLED':
            status = PortalSheetStatus.INSTALLED
        elif physical == 'CLOSED':
            status = PortalSheetStatus.CANCELLED
        elif physical == 'OPEN' and proposal['fields'].get('order_number'):
            status = PortalSheetStatus.INSTALLING
        elif proposal['fields'].get('order_number'):
            # The business accepts a retained legacy order number as evidence
            # of historical approval, without supplying its actor/date/scan.
            status = PortalSheetStatus.ORDER_PROCESSING
        elif outcome == 'REJECTED':
            status = PortalSheetStatus.REJECTED
        elif outcome == 'DEFERRED / ON HOLD' or outcome == 'RESCHEDULED':
            status = PortalSheetStatus.DEFERRED
        elif outcome in {'OPTED FOR CASH', 'OPTED FOR OTHER PARTNER'}:
            status = PortalSheetStatus.OPTED_OTHER
        elif outcome in {'WITHDRAWN', 'CANCELLED', 'CLIENT WITHDREW'}:
            status = PortalSheetStatus.CANCELLED
        elif outcome == 'VISITED, AWAITING CREDIT ANALYSIS':
            status = PortalSheetStatus.UNDER_REVIEW
        elif outcome == 'APPROVED' and proposal['stage'] == 'final_review':
            status = PortalSheetStatus.ORDER_PROCESSING
        elif outcome == 'APPROVED' and proposal['stage'] in {'credit', 'jbl_visit'}:
            status = PortalSheetStatus.UNDER_REVIEW
        else:
            status = PortalSheetStatus.LEGACY
        statuses.add(status)
    return next(iter(statuses)) if len(statuses) == 1 else PortalSheetStatus.LEGACY


def sheet_pipeline_status(farmer):
    """Return one of twelve labels without changing canonical case state.

    Mini App reads retain their detailed current_pipeline_state_label. A
    retained historical outcome can be displayed while its action gate stays
    closed. A legacy order number establishes historical approval for this
    label, without creating a modern approval event or signed-order evidence.
    """
    from core.services.jawabu_pipeline import current_workflow_state
    from hb_operations.deposits import deposit_state
    from hb_operations.models import HomeBiogasAction

    state = current_workflow_state(farmer)
    if state == 'legacy_review':
        return _reported_legacy_status(farmer)
    if state == 'rejected':
        return PortalSheetStatus.REJECTED
    if state == 'deferred':
        return PortalSheetStatus.DEFERRED
    if state == 'withdrawn':
        # An explicit later withdrawal takes precedence over old opted-out
        # source facts. Do not revive an earlier closure reason after resume.
        if farmer.withdrawn_stage:
            return PortalSheetStatus.CANCELLED
        if farmer.jbl_visit_status in {'Opted for Cash', 'Opted for Other Partner'}:
            return PortalSheetStatus.OPTED_OTHER
        if farmer.source == 'portal_legacy' and _reported_legacy_status(farmer) == PortalSheetStatus.OPTED_OTHER:
            return PortalSheetStatus.OPTED_OTHER
        return PortalSheetStatus.CANCELLED

    try:
        hb = farmer.homebiogas_action
    except HomeBiogasAction.DoesNotExist:
        hb = None
    if hb is not None:
        if hb.commissioning_status == 'commissioned':
            return PortalSheetStatus.COMMISSIONED
        if hb.installation_status == 'installed':
            return PortalSheetStatus.INSTALLED
        if hb.installation_status == 'closed':
            return PortalSheetStatus.CANCELLED
        return PortalSheetStatus.INSTALLING

    if state in {'credit', 'final_review'}:
        return PortalSheetStatus.UNDER_REVIEW
    if state == 'order':
        return PortalSheetStatus.ORDER_PROCESSING
    if state == 'ordered' or farmer.order_number:
        # Legacy order numbers imply historical approval. HB handover and
        # accepted signed-order evidence remain separately governed.
        return PortalSheetStatus.ORDER_PROCESSING
    if state == 'jbl_visit':
        if farmer.jbl_visit_status in {'Rescheduled', 'Deferred / On Hold'}:
            return PortalSheetStatus.DEFERRED
        if deposit_state(farmer)['deposit_hold']:
            return PortalSheetStatus.DEPOSIT_PENDING
        return PortalSheetStatus.AWAITING_VISIT
    return PortalSheetStatus.LEGACY
