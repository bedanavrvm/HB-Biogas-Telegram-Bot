"""Read-only, action-scoped Origination navigation; no workflow transitions."""
from core.services.workflow_access import scope_workflow_queryset, workflow_access_decision
from origination.models import OriginationSigningPackage

STATUS_LABELS = {
    'draft': 'Draft', 'ready_for_review': 'Awaiting review',
    'correction_required': 'Changes requested', 'reviewed': 'Reviewed',
    'signing_pending': 'Awaiting signatures', 'partially_signed': 'Partly signed',
    'fully_signed': 'Fully signed', 'signed_pending_approval': 'Awaiting final approval',
    'approved': 'Approved', 'declined': 'Declined', 'expired': 'Expired',
    'cancelled': 'Cancelled',
}


def actionable_applications(scoped, *, user, access):
    """Map each authorized application to one next action, not a slot count."""
    actions = {}

    def scope(capability):
        return scope_workflow_queryset(
            scoped, user, 'loan_origination', capability, access=access,
            branch_field='branch', product_field='product_version__product__code',
            group_field='group_configuration__group_id',
        )

    for row in scope('origination.create').filter(
        officer=user, status__in=['draft', 'correction_required'],
    ):
        actions[str(row.pk)] = 'Make corrections' if row.status == 'correction_required' else 'Complete application'
    from origination.services.origination_consent import conditional_approval_enabled
    if conditional_approval_enabled():
        for row in scope('origination.create').filter(officer=user, status__in=['ready_for_review', 'reviewed']):
            actions[str(row.pk)] = 'Continue to signing'

    # Legacy packets still require preparation, independent review and dispatch.
    for row in scope('origination.signing.start').filter(
        approval_roles_snapshot=[], status__in=['ready_for_review', 'reviewed'],
    ):
        prepared = row.signing_packages.filter(status='pending', review_scope_sha256__gt='').exists()
        if str(row.pk) in actions:
            continue
        if row.status == 'reviewed':
            actions[str(row.pk)] = 'Start signing'
        elif not prepared:
            actions[str(row.pk)] = 'Prepare packet'
    for row in scope('origination.review').filter(
        approval_roles_snapshot=[], status__in=['ready_for_review', 'signed_pending_approval'],
    ).exclude(officer=user):
        if row.status == 'signed_pending_approval':
            actions[str(row.pk)] = 'Review signed application'
        elif row.signing_packages.filter(status='pending', review_scope_sha256__gt='').exists():
            actions[str(row.pk)] = 'Review application'

    from origination.services.origination_esign import STAFF_SIGNER_ACCESS_ROLES
    from origination.services.origination_approval import signing_progress
    from origination.services.origination_signing import _slot_catalog
    packages = OriginationSigningPackage.objects.filter(
        application__in=scope('origination.signing.staff').filter(
            status__in=['signing_pending', 'partially_signed']),
        status__in=['pending', 'in_progress'],
    ).select_related('application').prefetch_related('actions__invalidation').order_by('application_id', '-created_at')
    seen = set()
    for package in packages:
        row = package.application
        if row.pk in seen:
            continue
        seen.add(row.pk)
        decision = workflow_access_decision(
            user, 'loan_origination', 'origination.signing.staff', access=access, resource=row)
        complete = {(a.document_key, a.slot_key) for a in package.actions.all()
                    if a.mode == 'verified' and not hasattr(a, 'invalidation')}
        progress = signing_progress(package) if row.approval_roles_snapshot else {}
        slots = _slot_catalog(package)
        for participant in package.participants_snapshot or []:
            role = participant.get('role') if isinstance(participant, dict) else ''
            if not role or not participant.get('applicable', True) or not decision.allowed:
                continue
            if not (decision.technical_override or STAFF_SIGNER_ACCESS_ROLES.get(role, set()).intersection(decision.roles)):
                continue
            if role == 'officer' and row.officer_id != user.pk:
                continue
            if row.approval_roles_snapshot:
                if role != 'officer' and (row.officer_id == user.pk or any(
                    a.actor_id == user.pk and a.signer_role != role and a.mode == 'verified'
                    and not hasattr(a, 'invalidation') for a in package.actions.all())):
                    continue
                if role in row.approval_roles_snapshot and not (
                    progress.get('approval_ready') and progress.get('next_approver') == role):
                    continue
            if any(s['required'] and (s['document_key'], s['key']) not in complete
                   for s in slots if s['role'] == role):
                actions[str(row.pk)] = 'Review and sign' if role in row.approval_roles_snapshot else 'Sign application'
                break
    return actions
