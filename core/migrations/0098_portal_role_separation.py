"""Separate Head of Rural approval authority from Portal operations authority.

This migration deliberately changes only the Jawabu Portal capability matrix.
It never rewrites AccessGrant rows, customer records, workflow events, or
financial documents.  Existing BUSINESS_ADMIN grants retain their stable code
but become the narrower Head of Rural policy.  Operations Administrator grants
must be assigned through the existing maker-checker path after deployment.

Rollback note: this migration is intentionally irreversible.  Reversing a
matrix migration blindly could restore an unknown, stale policy.  To undo,
redeploy the prior application code and submit an audited maker-checker policy
change using the before/after evidence in WorkflowRoleCapabilityAuditEvent.
"""

from django.db import migrations


PORTAL_CAPABILITIES = (
    'portal.dashboard.view', 'portal.case.read', 'portal.deferred.view',
    'portal.jbl_queue.view', 'portal.jbl_followup.view',
    'portal.jbl_visit.write', 'portal.jbl_media.view', 'portal.jbl_media.write',
    'portal.credit_queue.view', 'portal.credit.write',
    'portal.final_review.view', 'portal.final_review.write',
    'portal.requisition.view', 'portal.requisition.write', 'portal.batches.view',
    'portal.invoice.view', 'portal.invoice.write', 'portal.payment.view',
    'portal.payment.prepare', 'portal.payment.review',
    'portal.approval.delegation.authorize', 'portal.documents.view',
    'portal.documents.regenerate', 'portal.documents.sign',
    'portal.imports.view', 'portal.health.read',
    'portal.health.maintenance.manage', 'portal.workspace.manage',
)


TARGET_ALLOW = {
    'JBL_OFFICER': {
        'portal.dashboard.view', 'portal.case.read', 'portal.deferred.view',
        'portal.jbl_queue.view', 'portal.jbl_followup.view',
        'portal.jbl_visit.write', 'portal.jbl_media.view',
        'portal.jbl_media.write', 'portal.requisition.view',
    },
    'CREDIT_ANALYST': {
        'portal.dashboard.view', 'portal.case.read', 'portal.jbl_media.view',
        'portal.credit_queue.view', 'portal.credit.write',
    },
    'HB_STAFF': {
        'portal.dashboard.view', 'portal.case.read', 'portal.deferred.view',
        'portal.requisition.view', 'portal.requisition.write',
        'portal.batches.view', 'portal.invoice.view', 'portal.invoice.write',
        'portal.payment.view', 'portal.payment.prepare', 'portal.documents.view',
        'portal.documents.regenerate', 'portal.health.read',
    },
    'OPERATIONS_ADMIN': {
        'portal.dashboard.view', 'portal.case.read', 'portal.deferred.view',
        'portal.jbl_queue.view', 'portal.jbl_media.view',
        'portal.credit_queue.view', 'portal.credit.write',
        'portal.requisition.view', 'portal.requisition.write',
        'portal.batches.view', 'portal.invoice.view', 'portal.invoice.write',
        'portal.payment.view', 'portal.payment.prepare', 'portal.documents.view',
        'portal.documents.regenerate', 'portal.documents.sign',
        'portal.health.read',
    },
    'IT': {
        'portal.dashboard.view', 'portal.case.read', 'portal.imports.view',
        'portal.health.read', 'portal.health.maintenance.manage',
        'portal.workspace.manage',
    },
    'BUSINESS_ADMIN': {
        'portal.dashboard.view', 'portal.case.read', 'portal.deferred.view',
        'portal.jbl_media.view', 'portal.final_review.view',
        'portal.final_review.write', 'portal.payment.view',
        'portal.payment.review', 'portal.approval.delegation.authorize',
        'portal.documents.view', 'portal.documents.sign', 'portal.health.read',
    },
}


def apply_portal_role_separation(apps, schema_editor):
    Capability = apps.get_model('core', 'WorkflowRoleCapability')
    Audit = apps.get_model('core', 'WorkflowRoleCapabilityAuditEvent')
    PolicyState = apps.get_model('core', 'AccessControlPolicyState')
    SignoffPolicy = apps.get_model('core', 'DocumentSignoffPolicy')

    # 0097 preserves legacy rows as an empty JSON list. Materialise their
    # existing single responsible role before the first multi-role proposal.
    for policy in SignoffPolicy.objects.filter(approval_roles=[]).exclude(approval_role=''):
        policy.approval_roles = [policy.approval_role]
        policy.save(update_fields=['approval_roles'])

    changed_roles = []
    for role, allowed in TARGET_ALLOW.items():
        before = {
            row['capability_key']: row['effect']
            for row in Capability.objects.filter(
                workflow='jawabu_portal', role=role,
                capability_key__in=PORTAL_CAPABILITIES,
            ).values('capability_key', 'effect')
        }
        for key in PORTAL_CAPABILITIES:
            effect = 'allow' if key in allowed else 'deny'
            Capability.objects.update_or_create(
                workflow='jawabu_portal', role=role, capability_key=key,
                defaults={'effect': effect, 'enabled': effect == 'allow'},
            )
        after = {key: ('allow' if key in allowed else 'deny') for key in PORTAL_CAPABILITIES}
        if before != after:
            changed_roles.append(role)
            Audit.objects.create(
                workflow='jawabu_portal', role=role, actor=None,
                source='role_separation_0098',
                changes={
                    'reason': 'Approved Portal Head of Rural / Operations Administrator separation.',
                    'before': before,
                    'after': after,
                },
            )
    if changed_roles:
        state, _created = PolicyState.objects.get_or_create(singleton=1)
        state.version += 1
        state.save(update_fields=['version', 'updated_at'])


def reverse_noop(apps, schema_editor):
    # See the module rollback note: preserving the live, audited policy is
    # safer than guessing which historical entitlement should be restored.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0097_document_signoff_approval_roles'),
    ]

    operations = [
        migrations.RunPython(apply_portal_role_separation, reverse_noop),
    ]
