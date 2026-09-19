from django.db import migrations


def grant_operations_read_access(apps, schema_editor):
    Policy = apps.get_model('core', 'WorkflowRoleCapability')
    Audit = apps.get_model('core', 'WorkflowRoleCapabilityAuditEvent')
    PolicyState = apps.get_model('core', 'AccessControlPolicyState')
    existing = Policy.objects.filter(
        workflow='jawabu_portal', role='OPERATIONS_ADMIN',
        capability_key='portal.hb_action.view',
    ).values('enabled', 'effect').first()
    Policy.objects.update_or_create(
        workflow='jawabu_portal', role='OPERATIONS_ADMIN',
        capability_key='portal.hb_action.view',
        defaults={'enabled': True, 'effect': 'allow'},
    )
    if not existing or not existing['enabled'] or existing['effect'] != 'allow':
        Audit.objects.create(
            workflow='jawabu_portal', role='OPERATIONS_ADMIN', actor=None,
            source='hb_action_operations_read_access_0185',
            changes={
                'reason': 'Operations may inspect HB fulfilment and open linked invoice records without editing HB progress.',
                'capabilities': ['portal.hb_action.view'],
            },
        )
        state, _created = PolicyState.objects.get_or_create(singleton=1)
        state.version += 1
        state.save(update_fields=['version', 'updated_at'])


class Migration(migrations.Migration):
    dependencies = [('core', '0184_homebiogas_action_capabilities')]
    operations = [migrations.RunPython(grant_operations_read_access, migrations.RunPython.noop)]
