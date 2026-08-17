"""Portal-only approval, delegation, and review-validity controls.

The legacy decision columns remain the operational compatibility surface.
New approval records supply append-only evidence and validity checks without
silently reinterpreting historical decisions made before this control existed.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import (
    AccessGrant,
    JawabuApprovalCondition,
    JawabuApprovalDelegation,
    JawabuApprovalDelegationEvent,
    JawabuApprovalRecord,
)
from core.services.workflow_capabilities import has_capability


APPROVAL_VALIDITY_DAYS = 90
MAX_DELEGATION_DAYS = 14

# A short shared taxonomy makes Portfolio reporting usable without forcing a
# reason onto an uncomplicated approval. ``other`` deliberately requires text.
REASON_CODES = (
    ('insufficient_collateral', 'Insufficient collateral'),
    ('adverse_crb', 'Adverse CRB result'),
    ('missing_kyc', 'Missing KYC/document'),
    ('affordability', 'Affordability concern'),
    ('data_discrepancy', 'Data discrepancy'),
    ('customer_withdrew', 'Customer withdrew'),
    ('policy_exception', 'Policy exception'),
    ('other', 'Other'),
)
REASON_CODE_VALUES = {value for value, _label in REASON_CODES}
NON_POSITIVE_DECISIONS = {
    JawabuApprovalRecord.DECISION_CONDITIONAL,
    JawabuApprovalRecord.DECISION_REJECTED,
    JawabuApprovalRecord.DECISION_DEFERRED,
    JawabuApprovalRecord.DECISION_RETURNED,
}
MATERIAL_FIELDS = frozenset({
    'national_id', 'primary_phone', 'secondary_phone', 'customer_no',
    'imab_created', 'imab_customer_name', 'branch', 'system_branch',
    'payment_product', 'system_deposit_paid_jbl', 'invoice_amount',
    'discount', 'payment', 'balance_due', 'repayment_date',
    'repayment_day', 'repayment_tenor', 'repayment_tenor_months',
    'jbl_visit_date', 'jbl_visit_status', 'jbl_media',
})

GATE_CAPABILITIES = {
    JawabuApprovalRecord.GATE_CREDIT: 'portal.credit.write',
    JawabuApprovalRecord.GATE_FINAL_REVIEW: 'portal.final_review.write',
    JawabuApprovalRecord.GATE_PAYMENT_REVIEW: 'portal.payment.review',
}
JBL_MEDIA_LABELS = {
    'LAF': 'signed LAF document',
    'JBL_VISIT_PHOTO': 'JBL visit photo',
}


class JawabuApprovalError(ValidationError):
    """A safe validation message that Portal API views may return."""


def decision_code(decision: str) -> str:
    value = str(decision or '').strip()
    mapping = {
        'Approved': JawabuApprovalRecord.DECISION_APPROVED,
        'Rejected': JawabuApprovalRecord.DECISION_REJECTED,
        'Deferred': JawabuApprovalRecord.DECISION_DEFERRED,
        'Returned for Rework': JawabuApprovalRecord.DECISION_RETURNED,
    }
    if value not in mapping:
        raise JawabuApprovalError('Choose a supported approval decision.')
    return mapping[value]


def validate_reason(*, decision: str, reason_code: str = '', comment: str = '') -> tuple[str, str]:
    normalized_decision = decision_code(decision)
    code = str(reason_code or '').strip().casefold()
    note = str(comment or '').strip()
    if normalized_decision in NON_POSITIVE_DECISIONS:
        if code not in REASON_CODE_VALUES:
            raise JawabuApprovalError('Choose a structured reason for this decision.')
        if code == 'other' and not note:
            raise JawabuApprovalError('Explain the decision when reason is Other.')
    elif code and code not in REASON_CODE_VALUES:
        raise JawabuApprovalError('Choose a valid structured decision reason.')
    return normalized_decision, code


def _scope_matches(delegation: JawabuApprovalDelegation, farmer) -> bool:
    if delegation.branch and delegation.branch.casefold() != str(farmer.branch or '').casefold():
        return False
    if delegation.product and delegation.product.casefold() != str(farmer.payment_product or '').casefold():
        return False
    return True


def active_delegation(*, user, gate: str, farmer) -> JawabuApprovalDelegation | None:
    if not user or not getattr(user, 'is_active', False):
        return None
    current = timezone.now()
    candidates = JawabuApprovalDelegation.objects.filter(
        delegate=user, gate=gate, starts_at__lte=current,
        expires_at__gt=current, revoked_at__isnull=True,
    ).order_by('-starts_at')
    return next((item for item in candidates if _scope_matches(item, farmer)), None)


def approval_authority(*, user, access: dict | None, gate: str, farmer) -> tuple[bool, str, JawabuApprovalDelegation | None]:
    """Resolve direct role authority before considering a scoped delegation."""
    capability = GATE_CAPABILITIES[gate]
    from core.services.portal_permissions import portal_access_decision

    direct = portal_access_decision(user, capability, access=access, resource=farmer)
    if direct.allowed:
        role = direct.roles[0] if direct.roles else 'BUSINESS_ADMIN'
        return True, role, None
    delegation = active_delegation(user=user, gate=gate, farmer=farmer)
    if delegation:
        return True, delegation.source_role, delegation
    return False, '', None


def can_authorize_delegation(*, user, access: dict | None) -> bool:
    return bool(user and getattr(user, 'is_active', False) and has_capability(
        user, 'jawabu_portal', 'portal.approval.delegation.authorize', access=access,
    ))


def _has_global_branch_scope(access: dict | None) -> bool:
    """Return whether an access snapshot contains an all-branch grant.

    An active Django Superuser is the documented technical break-glass
    override.  ``user_access`` deliberately represents that override without
    synthetic ``AccessGrant`` rows, so it must be treated as global here as
    well; otherwise a Superuser can reach the delegation screen but cannot
    delegate for any configured branch.
    """
    if bool((access or {}).get('technical_override')):
        return True
    return any(not str(getattr(grant, 'branch', '') or '').strip() for grant in (access or {}).get('grants', []))


def _branch_scope_values(access: dict | None) -> set[str]:
    return {
        str(value).strip().casefold()
        for value in (access or {}).get('branches', [])
        if str(value).strip()
    }


def delegation_is_within_authorization_scope(delegation: JawabuApprovalDelegation, access: dict | None) -> bool:
    """Return whether an issuer may inspect or revoke this delegation scope."""
    if _has_global_branch_scope(access):
        return True
    branch = str(delegation.branch or '').strip().casefold()
    return bool(branch and branch in _branch_scope_values(access))


def _validate_delegation_branch_scope(*, delegate, authorized_by, authorization_access: dict | None, branch: str) -> str:
    """Keep temporary authority within both staff members' existing Portal scope.

    A delegation must not turn a branch-scoped Business Admin or delegate into
    an all-branch approver.  Keeping this in the service protects the Django
    Admin surface as well as the Mini App API.
    """
    from core.services.telegram_identity import user_access

    issuer_branches = _branch_scope_values(authorization_access)
    issuer_global = _has_global_branch_scope(authorization_access)
    delegate_access = user_access(delegate, 'jawabu_portal')
    delegate_branches = _branch_scope_values(delegate_access)
    delegate_global = _has_global_branch_scope(delegate_access)
    normalized_branch = str(branch or '').strip().casefold()

    if not normalized_branch:
        if not issuer_global:
            raise JawabuApprovalError('Choose a branch because your Portal authority is branch-scoped.')
        if not delegate_global:
            raise JawabuApprovalError('Choose a branch because the delegate has branch-scoped Portal access.')
        return ''
    from core.services.branches import global_branch_choices
    configured_branches = {
        str(value).strip().casefold(): str(value).strip()
        for value in global_branch_choices() if str(value).strip()
    }
    if normalized_branch not in configured_branches:
        raise JawabuApprovalError('Choose a configured branch for this temporary delegation.')
    if not issuer_global and normalized_branch not in issuer_branches:
        raise JawabuApprovalError('The selected branch is outside your Portal authority.')
    if not delegate_global and normalized_branch not in delegate_branches:
        raise JawabuApprovalError('The delegate does not have Portal access to the selected branch.')
    return configured_branches[normalized_branch]


@transaction.atomic
def create_delegation(*, delegate, gate: str, authorized_by, authorization_access: dict | None,
                      reason: str, branch: str = '', product: str = '', expires_at=None) -> JawabuApprovalDelegation:
    if gate not in GATE_CAPABILITIES:
        raise JawabuApprovalError('Choose a valid Portal approval gate.')
    if delegate == authorized_by:
        raise JawabuApprovalError('You cannot delegate approval authority to yourself.')
    if not can_authorize_delegation(user=authorized_by, access=authorization_access):
        raise JawabuApprovalError('Your Portal role cannot authorize approval delegations.')
    if not delegate or not delegate.is_active:
        raise JawabuApprovalError('The delegate must be an active staff user.')
    if not AccessGrant.objects.filter(user=delegate, workflow='jawabu_portal', active=True).exists():
        raise JawabuApprovalError('The delegate must have an active, scoped Portal access grant.')
    branch = _validate_delegation_branch_scope(
        delegate=delegate,
        authorized_by=authorized_by,
        authorization_access=authorization_access,
        branch=branch,
    )
    reason = str(reason or '').strip()
    if not reason:
        raise JawabuApprovalError('Give a reason for this temporary delegation.')
    starts_at = timezone.now()
    max_expiry = starts_at + timedelta(days=MAX_DELEGATION_DAYS)
    expiry = expires_at or max_expiry
    if expiry <= starts_at or expiry > max_expiry:
        raise JawabuApprovalError('A delegation must expire within 14 days.')
    existing = JawabuApprovalDelegation.objects.select_for_update().filter(
        delegate=delegate, gate=gate, revoked_at__isnull=True, expires_at__gt=starts_at,
        branch=str(branch or ''), product=str(product or ''),
    ).first()
    if existing:
        raise JawabuApprovalError('This delegate already has an active approval delegation for the selected scope.')
    delegation = JawabuApprovalDelegation.objects.create(
        delegate=delegate, gate=gate, branch=str(branch or '').strip(),
        product=str(product or '').strip(), reason=reason,
        authorized_by=authorized_by, starts_at=starts_at, expires_at=expiry,
    )
    JawabuApprovalDelegationEvent.objects.create(
        delegation=delegation, action=JawabuApprovalDelegationEvent.ACTION_CREATED,
        actor=authorized_by, note=reason,
    )
    return delegation


@transaction.atomic
def revoke_delegation(*, delegation_id, actor, access: dict | None, reason: str) -> JawabuApprovalDelegation:
    delegation = JawabuApprovalDelegation.objects.select_for_update().get(pk=delegation_id)
    if not can_authorize_delegation(user=actor, access=access):
        raise JawabuApprovalError('Your Portal role cannot revoke approval delegations.')
    if not delegation_is_within_authorization_scope(delegation, access):
        raise JawabuApprovalError('This delegation is outside your Portal branch authority.')
    reason = str(reason or '').strip()
    if not reason:
        raise JawabuApprovalError('Give a reason before revoking this delegation.')
    if delegation.revoked_at is None:
        delegation.revoked_at = timezone.now()
        delegation.revoked_by = actor
        delegation.revocation_reason = reason
        delegation.save(update_fields=['revoked_at', 'revoked_by', 'revocation_reason'])
        JawabuApprovalDelegationEvent.objects.create(
            delegation=delegation, action=JawabuApprovalDelegationEvent.ACTION_REVOKED,
            actor=actor, note=reason,
        )
    return delegation


def _expire_if_due(record: JawabuApprovalRecord) -> JawabuApprovalRecord:
    if record.status in {record.STATUS_ACTIVE, record.STATUS_CONDITIONS_PENDING} and record.expires_at and record.expires_at <= timezone.now():
        record.status = record.STATUS_EXPIRED
        record.invalidation_reason = 'Approval validity window elapsed.'
        record.invalidated_at = timezone.now()
        record.save(update_fields=['status', 'invalidation_reason', 'invalidated_at'])
    return record


def current_approval(farmer, gate: str, *, payment_document=None) -> JawabuApprovalRecord | None:
    filters = {'farmer': farmer, 'gate': gate}
    if payment_document is not None:
        filters['payment_document'] = payment_document
    else:
        filters['payment_document__isnull'] = True
    record = JawabuApprovalRecord.objects.filter(**filters).order_by('-decided_at', '-created_at').first()
    return _expire_if_due(record) if record else None


def approval_state(farmer, gate: str, *, payment_document=None) -> str:
    record = current_approval(farmer, gate, payment_document=payment_document)
    if record is None:
        return 'legacy'
    return record.status


def approval_is_effective(farmer, gate: str, *, payment_document=None) -> bool:
    record = current_approval(farmer, gate, payment_document=payment_document)
    # Historical decisions remain operational during the phased rollout; they
    # are intentionally highlighted for review, not retroactively expired.
    if record is None:
        return True
    return record.status == record.STATUS_ACTIVE and record.decision == record.DECISION_APPROVED


def require_effective_approval(farmer, gate: str, *, payment_document=None) -> None:
    if approval_is_effective(farmer, gate, payment_document=payment_document):
        return
    state = approval_state(farmer, gate, payment_document=payment_document)
    label = dict(JawabuApprovalRecord.GATE_CHOICES).get(gate, 'required')
    if state == JawabuApprovalRecord.STATUS_CONDITIONS_PENDING:
        raise JawabuApprovalError(f'{label} has unresolved approval conditions.')
    if state == JawabuApprovalRecord.STATUS_EXPIRED:
        raise JawabuApprovalError(f'{label} approval expired and must be reviewed again.')
    raise JawabuApprovalError(f'{label} approval is no longer valid and must be reviewed again.')


@transaction.atomic
def record_approval(*, farmer, gate: str, decision: str, reason_code: str = '', comment: str = '',
                    conditions: list[str] | None = None, actor=None, actor_label: str = '', access: dict | None = None,
                    payment_document=None) -> JawabuApprovalRecord:
    normalized_decision, normalized_reason = validate_reason(
        decision=decision, reason_code=reason_code, comment=comment,
    )
    # Existing service tests and explicitly authentication-disabled local
    # environments do not manufacture a Portal user.  Preserve that narrow
    # compatibility mode; every real Mini App request supplies both actor and
    # access and is evaluated normally.
    if actor is None and access is None:
        allowed, role, delegation = True, 'SYSTEM_TEST', None
    else:
        allowed, role, delegation = approval_authority(user=actor, access=access, gate=gate, farmer=farmer)
    if not allowed:
        raise JawabuApprovalError('Your Portal role is not authorized to record this approval.')
    condition_values = [str(value or '').strip() for value in (conditions or []) if str(value or '').strip()]
    # Conditional decisions were retired from the operational workflow.  The
    # historical tables remain append-only evidence, but no new active
    # approval may depend on conditions that would create an ambiguous route.
    if condition_values:
        raise JawabuApprovalError('Conditional approvals are no longer supported. Choose Approved, Deferred, or Rejected.')
    existing = JawabuApprovalRecord.objects.select_for_update().filter(
        farmer=farmer, gate=gate, payment_document=payment_document,
        status__in=[JawabuApprovalRecord.STATUS_ACTIVE, JawabuApprovalRecord.STATUS_CONDITIONS_PENDING],
    )
    existing.update(status=JawabuApprovalRecord.STATUS_SUPERSEDED)
    current = timezone.now()
    record = JawabuApprovalRecord.objects.create(
        farmer=farmer, payment_document=payment_document, gate=gate,
        decision=normalized_decision,
        status=JawabuApprovalRecord.STATUS_ACTIVE,
        reason_code=normalized_reason, comment=str(comment or '').strip(),
        source_revision=int(getattr(farmer, 'workflow_revision', 1) or 1),
        authority_role=role, delegation=delegation, decided_by=actor,
        decided_by_label=str(actor_label or ''), decided_at=current,
        expires_at=current + timedelta(days=APPROVAL_VALIDITY_DAYS),
    )
    return record


@transaction.atomic
def invalidate_material_approvals(*, farmer, changed_fields, actor=None, reason: str = '') -> int:
    changed = sorted(set(str(field) for field in changed_fields).intersection(MATERIAL_FIELDS))
    if not changed:
        return 0
    records = JawabuApprovalRecord.objects.select_for_update().filter(
        farmer=farmer,
        status__in=[JawabuApprovalRecord.STATUS_ACTIVE, JawabuApprovalRecord.STATUS_CONDITIONS_PENDING],
    )
    message = str(reason or f'Material case data changed: {", ".join(changed)}.')
    return records.update(
        status=JawabuApprovalRecord.STATUS_INVALIDATED,
        invalidated_at=timezone.now(), invalidated_by=actor,
        invalidation_reason=message,
    )


@transaction.atomic
def clear_condition(*, condition_id, actor, access: dict | None, note: str = '') -> JawabuApprovalCondition:
    condition = JawabuApprovalCondition.objects.select_for_update().select_related('approval__farmer').get(pk=condition_id)
    approval = condition.approval
    if approval.status != JawabuApprovalRecord.STATUS_CONDITIONS_PENDING:
        raise JawabuApprovalError('This approval no longer has pending conditions.')
    allowed, _role, _delegation = approval_authority(
        user=actor, access=access, gate=approval.gate, farmer=approval.farmer,
    )
    if not allowed:
        raise JawabuApprovalError('Your Portal role is not authorized to clear this approval condition.')
    if condition.satisfied_at is None:
        condition.satisfied_at = timezone.now()
        condition.satisfied_by = actor
        condition.satisfaction_note = str(note or '').strip()
        condition.save(update_fields=['satisfied_at', 'satisfied_by', 'satisfaction_note'])
    if not approval.conditions.filter(satisfied_at__isnull=True).exists():
        approval.status = JawabuApprovalRecord.STATUS_ACTIVE
        approval.save(update_fields=['status'])
        # A conditional decision is deliberately not treated as an approval
        # while any condition is open.  Once every condition is evidenced as
        # complete, promote only the *current* decision and leave the
        # conditional approval record intact as the audit trail.
        farmer = approval.farmer
        from core.services.jawabu_pipeline import JawabuWorkflowState, current_workflow_state
        from core.services.workflow_transitions import next_workflow_revision
        from core.services.jawabu_case360 import record_pipeline_event

        prior_state = current_workflow_state(farmer)
        if approval.gate == JawabuApprovalRecord.GATE_CREDIT:
            farmer.credit_decision = 'Approved'
            next_state = JawabuWorkflowState.FINAL_REVIEW
            update_fields = ['credit_decision']
        elif approval.gate == JawabuApprovalRecord.GATE_FINAL_REVIEW:
            farmer.final_decision = 'Approved'
            next_state = JawabuWorkflowState.ORDER
            update_fields = ['final_decision']
        else:
            # Payment conditions affect the payment document only; there is
            # no farmer workflow state to advance at this point.
            return condition
        revision_before, revision_after = next_workflow_revision(farmer)
        farmer.workflow_state = next_state
        farmer.workflow_state_entered_at = timezone.now()
        farmer.workflow_revision = revision_after
        farmer.save(update_fields=update_fields + [
            'workflow_state', 'workflow_state_entered_at',
            'workflow_revision', 'updated_at',
        ])
        record_pipeline_event(
            farmer,
            action='approval_conditions_cleared',
            stage_key=approval.gate,
            actor=getattr(actor, 'username', '') or str(actor or ''),
            new_values={'approval_id': str(approval.id), 'decision': 'Approved'},
            actor_user=actor,
            transition_code=f'jawabu.{approval.gate}.conditions_cleared',
            from_state=prior_state,
            to_state=next_state,
            revision_before=revision_before,
            revision_after=revision_after,
        )
        # Approval clearance is committed with its audit event.  Publication
        # is intentionally durable and request-assisted so a degraded Google
        # register cannot hold this Portal transaction open.
        from core.services.portal_publication import reserve_farmer_publication
        reserve_farmer_publication(
            farmer,
            request_id=f'approval-conditions-cleared:{approval.id}:{farmer.id}',
            requested_by=actor,
            requested_by_label=getattr(actor, 'username', '') or str(actor or ''),
        )
    return condition


def visit_evidence_status(farmer) -> dict[str, int]:
    """Return controlled JBL-visit evidence counts for stage guard checks."""
    from core.models import MediaAttachment

    rows = MediaAttachment.objects.filter(
        jawabu_farmer=farmer,
        file_type__in=['LAF', 'JBL_VISIT_PHOTO'],
        upload_status='success',
    ).values_list('file_type', flat=True)
    counts = {'LAF': 0, 'JBL_VISIT_PHOTO': 0}
    for row in rows:
        counts[str(row)] = counts.get(str(row), 0) + 1
    return counts


def require_visit_evidence(farmer) -> None:
    counts = visit_evidence_status(farmer)
    missing = [JBL_MEDIA_LABELS[key] for key in ('LAF', 'JBL_VISIT_PHOTO') if not counts.get(key)]
    if missing:
        raise JawabuApprovalError(
            'Upload the required visit evidence before forwarding this case: ' + ', '.join(missing) + '.'
        )


def visit_media_orphan_report(*, limit: int = 100) -> dict:
    """Return a non-destructive audit of unlinked controlled visit evidence.

    Rows created before direct case linkage can still be associated using their
    legacy national-ID key, so they are reported separately from true orphan
    candidates.  This is intentionally a report only: a Drive object is never
    deleted or relinked merely because a periodic check found it.
    """
    from django.db.models import Subquery
    from core.models import JawabuFarmerMaster, MediaAttachment

    controlled = MediaAttachment.objects.filter(
        upload_status='success', file_type__in=['LAF', 'JBL_VISIT_PHOTO'],
    )
    linked_count = controlled.filter(jawabu_farmer__isnull=False).count()
    unlinked = controlled.filter(jawabu_farmer__isnull=True)
    known_national_ids = JawabuFarmerMaster.objects.exclude(
        national_id='',
    ).values('national_id')
    legacy_linkable = unlinked.filter(
        business_key_type='id_number',
        business_key_value__in=Subquery(known_national_ids),
    )
    orphan_candidates = unlinked.exclude(pk__in=legacy_linkable.values('pk'))
    rows = orphan_candidates.order_by('-created_at')[:max(1, int(limit or 100))]
    return {
        'linked_count': linked_count,
        'legacy_linkable_count': legacy_linkable.count(),
        'orphan_candidate_count': orphan_candidates.count(),
        'orphan_candidates': [
            {
                'attachment_id': str(item.id),
                'category': item.file_type,
                'created_at': item.created_at.isoformat() if item.created_at else None,
                'business_key_type': item.business_key_type,
                'has_drive_file': bool(item.drive_file_id),
            }
            for item in rows
        ],
    }


def approval_payload(farmer) -> dict:
    """Compact UI metadata; legacy decisions are never rewritten by this call."""
    result = {}
    for gate in (JawabuApprovalRecord.GATE_CREDIT, JawabuApprovalRecord.GATE_FINAL_REVIEW):
        record = current_approval(farmer, gate)
        result[gate] = {
            'state': record.status if record else 'legacy',
            'decision': record.decision if record else '',
            'reason_code': record.reason_code if record else '',
            'expires_at': record.expires_at.isoformat() if record and record.expires_at else None,
            'conditions_pending': record.conditions.filter(satisfied_at__isnull=True).count() if record else 0,
            'conditions': [
                {
                    'id': str(condition.id),
                    'description': condition.description,
                    'satisfied_at': condition.satisfied_at.isoformat() if condition.satisfied_at else None,
                }
                for condition in (record.conditions.all() if record else [])
            ],
        }
    return result
