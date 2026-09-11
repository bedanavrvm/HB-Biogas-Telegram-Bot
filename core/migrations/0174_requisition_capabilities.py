from django.db import migrations


CAPABILITIES = (
    ('portal.requisition.finalize', ('OPERATIONS_ADMIN',)),
    ('portal.requisition.sequence.manage', ('IT',)),
    ('portal.requisition.view', ('IT',)),
)


def seed(apps, schema_editor):
    Policy = apps.get_model('core', 'WorkflowRoleCapability')
    Audit = apps.get_model('core', 'WorkflowRoleCapabilityAuditEvent')
    PolicyState = apps.get_model('core', 'AccessControlPolicyState')
    changed = []
    for key, roles in CAPABILITIES:
        for role in roles:
            _row, created = Policy.objects.update_or_create(
                workflow='jawabu_portal', role=role, capability_key=key,
                defaults={'enabled': True, 'effect': 'allow'},
            )
            changed.append((role, key, created))
    if changed:
        Audit.objects.create(
            workflow='jawabu_portal', role='IT / OPERATIONS_ADMIN', actor=None,
            source='requisition_capabilities_0174',
            changes={'reason': 'Governed official requisition numbering and Operations finalization.',
                     'capabilities': [key for _role, key, _created in changed]},
        )
        state, _created = PolicyState.objects.get_or_create(singleton=1)
        state.version += 1
        state.save(update_fields=['version', 'updated_at'])


class Migration(migrations.Migration):
    dependencies = [('core', '0173_requisition_finality_and_stage_terms')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
