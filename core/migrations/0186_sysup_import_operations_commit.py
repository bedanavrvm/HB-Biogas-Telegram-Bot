"""Permit Operations to review and commit governed SysUp borrower updates."""

from django.db import migrations


CAPABILITIES = ('portal.imports.view', 'portal.imports.commit')
ROLES = ('IT', 'OPERATIONS_ADMIN')


def seed_sysup_import_capabilities(apps, schema_editor):
    """Create only the newly governed permissions, preserving Admin policy edits."""
    Capability = apps.get_model('core', 'WorkflowRoleCapability')
    Audit = apps.get_model('core', 'WorkflowRoleCapabilityAuditEvent')
    PolicyState = apps.get_model('core', 'AccessControlPolicyState')

    changes = []
    for role in ROLES:
        created = []
        for key in CAPABILITIES:
            _row, was_created = Capability.objects.get_or_create(
                workflow='jawabu_portal', role=role, capability_key=key,
                defaults={'enabled': True, 'effect': 'allow'},
            )
            if was_created:
                created.append(key)
        if created:
            changes.append({'role': role, 'capabilities': created})
            Audit.objects.create(
                workflow='jawabu_portal', role=role, actor=None,
                source='sysup_import_operations_0186',
                changes={
                    'reason': 'Operations and IT may review and commit governed SysUp borrower updates.',
                    'created_capabilities': created,
                },
            )
    if changes:
        state, _created = PolicyState.objects.get_or_create(singleton=1)
        state.version += 1
        state.save(update_fields=['version', 'updated_at'])


def reverse_noop(apps, schema_editor):
    # A live policy may be intentionally changed after deployment.
    pass


class Migration(migrations.Migration):

    dependencies = [('core', '0185_hb_action_operations_read_access')]

    operations = [migrations.RunPython(seed_sysup_import_capabilities, reverse_noop)]
