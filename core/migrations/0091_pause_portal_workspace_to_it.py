"""Seed scoped IT support access for the paused private Portal workspace."""

from django.db import migrations


IT_CAPABILITIES = (
    ('jawabu_portal', 'IT', 'portal.dashboard.view'),
    ('jawabu_portal', 'IT', 'portal.case.read'),
    ('jawabu_portal', 'IT', 'portal.workspace.manage'),
    ('complaint_cases', 'IT', 'complaint.queue.view'),
    ('spin_credit_analysis', 'IT', 'spin.request.view'),
)


def _snapshot_state(Capability, Grant):
    grants = []
    for row in Grant.objects.order_by(
        'user_id', 'workflow', 'role', 'branch', 'product',
    ).values(
        'id', 'user_id', 'workflow', 'role', 'branch', 'product',
        'group_configuration_id', 'active', 'source',
    ):
        row['id'] = str(row['id'])
        grants.append(row)
    return {
        'capabilities': list(Capability.objects.order_by(
            'workflow', 'role', 'capability_key',
        ).values('workflow', 'role', 'capability_key', 'effect')),
        'grants': grants,
    }


def seed_paused_workspace_access(apps, schema_editor):
    """Keep the feature recoverable while limiting it to explicit IT grants.

    Existing explicit policy choices always win.  In particular, a prior deny
    is never overwritten by this deployment seed.
    """
    Capability = apps.get_model('core', 'WorkflowRoleCapability')
    PolicyState = apps.get_model('core', 'AccessControlPolicyState')
    Snapshot = apps.get_model('core', 'AccessControlPolicySnapshot')
    CapabilityAudit = apps.get_model('core', 'WorkflowRoleCapabilityAuditEvent')
    Grant = apps.get_model('core', 'AccessGrant')

    created = []
    for workflow, role, capability_key in IT_CAPABILITIES:
        row, was_created = Capability.objects.get_or_create(
            workflow=workflow,
            role=role,
            capability_key=capability_key,
            defaults={'enabled': True, 'effect': 'allow'},
        )
        if was_created:
            created.append({
                'workflow': workflow,
                'role': role,
                'capability_key': capability_key,
                'effect': row.effect,
            })

    if not created:
        return

    state, _created = PolicyState.objects.get_or_create(singleton=1, defaults={'version': 1})
    state.version += 1
    state.save(update_fields=['version', 'updated_at'])
    Snapshot.objects.get_or_create(
        version=state.version,
        defaults={'state': _snapshot_state(Capability, Grant)},
    )
    policy_audit = CapabilityAudit.objects.create(
        workflow='jawabu_portal',
        role='IT',
        actor=None,
        source='system_migration',
        changes={
            'reason': 'Private Portal workspace paused for operational staff; IT support retains scoped access.',
            'created_capabilities': created,
            'policy_version': state.version,
        },
    )

    # Use the ledger writer so this system-originated policy change remains
    # hash-chain verifiable instead of being an untraceable data migration.
    from core.services.compliance_audit import record_event

    record_event(
        workflow='access_control',
        action='access_control.portal_workspace.paused_to_it',
        category='authorization',
        origin='system',
        subject_type='workflow_role_capability',
        subject_id='jawabu_portal:IT:portal.workspace.manage',
        deduplication_key='migration:core:0091:portal-workspace-paused-to-it',
        source_model='WorkflowRoleCapabilityAuditEvent',
        source_event_id=str(policy_audit.pk),
        before_values={},
        after_values={'created_capabilities': created, 'policy_version': state.version},
        metadata={'migration': '0091_pause_portal_workspace_to_it'},
        sensitive=True,
    )


class Migration(migrations.Migration):
    # To undo: do not roll back application code to re-open the workspace.
    # Submit and independently approve a capability-matrix change instead.
    # The reverse operation intentionally preserves policy/audit evidence and
    # never touches cases, financial records, or private workspace rows.

    dependencies = [('core', '0090_accesscontrolcheckerassignment')]

    operations = [
        migrations.RunPython(seed_paused_workspace_access, migrations.RunPython.noop),
    ]
