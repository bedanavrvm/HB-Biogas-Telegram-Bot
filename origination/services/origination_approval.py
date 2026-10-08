"""Version-pinned approval signatures; legacy independent review is unchanged."""
from django.utils import timezone

from origination.models import OriginationSigningAction
from origination.services.loan_origination import OriginationError, _record_event

APPROVER_LABELS = {'branch_manager': 'BM', 'management_approver': 'Management'}


def validate_approval_roles(roles, signer_rules=None):
    if not isinstance(roles, list) or any(role not in APPROVER_LABELS for role in roles):
        raise OriginationError('Choose supported approval roles in their signing order.')
    if len(roles) != len(set(roles)):
        raise OriginationError('An approval role cannot appear twice.')
    if roles and roles[0] != 'branch_manager':
        raise OriginationError('BM must be the first approval signature.')
    if roles and signer_rules is not None:
        required_roles = {rule.get('role') for rule in signer_rules if rule.get('required', True)}
        if not {'officer', 'credit_analyst', *roles} <= required_roles:
            raise OriginationError('This flow requires officer, Credit Analyst and every approval role in the packet.')


def signing_progress(package):
    from origination.services.origination_signing import _slot_catalog
    roles = package.application.approval_roles_snapshot or []
    required = {(s['document_key'], s['key']) for s in _slot_catalog(package) if s['required']}
    complete = set(package.actions.filter(mode='verified', invalidation__isnull=True).values_list('document_key', 'slot_key'))
    missing = required - complete
    outstanding = list(dict.fromkeys(s['role'] for s in _slot_catalog(package)
                                    if (s['document_key'], s['key']) in missing))
    next_role = next((role for role in roles if role in outstanding), '')
    ready = bool(next_role and all(role == next_role or role in roles[roles.index(next_role) + 1:]
                                  for role in outstanding))
    return {'approval_roles': roles, 'next_approver': next_role, 'approval_ready': ready,
            'outstanding_roles': outstanding,
            'status_label': f'Awaiting {APPROVER_LABELS[next_role]}' if ready else 'Awaiting signatures'}


def guard_staff_signature(package, *, signer_role, actor, reviewed_packet_version=''):
    roles = package.application.approval_roles_snapshot or []
    if not roles:
        return
    validate_approval_roles(roles)
    if (not package.conditional_approval or package.consent_policy_snapshot.get('approval_roles') != roles
            or not package.consent_policy_id or package.consent_policy.approval_roles != roles):
        raise OriginationError('This packet does not have approved consent for its approval sequence.')
    application = package.application
    if signer_role == 'officer' and actor.pk != application.officer_id:
        raise OriginationError('Only the assigned officer may sign the officer slot.')
    if signer_role in {'officer', 'credit_analyst', *roles}:
        other_actors = set(package.actions.filter(
            mode='verified', invalidation__isnull=True,
            signer_role__in=['officer', 'credit_analyst', *roles],
        ).exclude(signer_role=signer_role).values_list('actor_id', flat=True))
        if (signer_role != 'officer' and actor.pk == application.officer_id) or actor.pk in other_actors:
            raise OriginationError('Officer, Credit Analyst and approvers must be different people.')
    if signer_role not in roles:
        return
    from origination.services.origination_signing import _slot_catalog
    for slot in _slot_catalog(package):
        if slot['role'] == signer_role and slot['required'] and slot['type'] == 'stamp' and not package.actions.filter(
            mode='verified', invalidation__isnull=True, document_key=slot['document_key'], slot_key=slot['key'],
        ).exists():
            raise OriginationError('Apply your required stamp, then open the packet before approving and signing.')
    progress = signing_progress(package)
    if not progress['approval_ready'] or progress['next_approver'] != signer_role:
        raise OriginationError('All preceding participants must finish signing before you approve and sign.')
    from origination.services.origination_signing import verified_packet_version
    version = verified_packet_version(package)
    if reviewed_packet_version != version or not application.events.filter(
        action='approval_packet_opened', actor=actor,
        after_values__package_id=str(package.pk), after_values__packet_version=version,
        after_values__revision=application.revision,
    ).exists():
        raise OriginationError('Open the latest packet with its signatures before approving and signing.')


def approve_completed_packet(package):
    """Called inside the signing transaction, after rendering the final signed bytes."""
    roles = package.application.approval_roles_snapshot or []
    if not roles:
        return False
    final_action = package.actions.filter(signer_role=roles[-1], mode='verified',
                                         invalidation__isnull=True, action_type='signature').first()
    if not final_action:
        raise OriginationError('The final approval signature is missing.')
    application = package.application
    now = timezone.now()
    application.status = application.STATUS_APPROVED
    application.final_reviewed_by = final_action.actor
    application.final_reviewed_at = now
    package.final_decision = 'approved'
    package.final_reviewed_by = final_action.actor
    package.final_reviewed_at = now
    package.final_approved_signed_document_hash = package.signed_document_hash
    package.archive_status = 'pending'
    _record_event(application, 'approval_signed', actor=final_action.actor,
                  request_id=f'approval:{package.pk}', after={
                      'package_id': str(package.pk), 'signed_document_hash': package.signed_document_hash,
                      'approval_roles': roles, 'status': application.STATUS_APPROVED,
                      **({'approved_facility_amount': (package.context_snapshot or {}).get('loan_amount'),
                          'approved_package_revision': package.application_revision}
                         if (package.context_snapshot or {}).get('_value_contract_version') == 2 else {}),
                  })
    return True
