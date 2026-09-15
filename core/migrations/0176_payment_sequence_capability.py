from django.db import migrations


def seed(apps, schema_editor):
    Policy = apps.get_model('core', 'WorkflowRoleCapability')
    Audit = apps.get_model('core', 'WorkflowRoleCapabilityAuditEvent')
    PolicyState = apps.get_model('core', 'AccessControlPolicyState')
    _row, created = Policy.objects.update_or_create(
        workflow='jawabu_portal', role='IT',
        capability_key='portal.payment.sequence.manage',
        defaults={'enabled': True, 'effect': 'allow'},
    )
    if created:
        Audit.objects.create(
            workflow='jawabu_portal', role='IT', actor=None,
            source='payment_sequence_capability_0176',
            changes={
                'reason': 'IT-only attributed alignment of the official payment sequence.',
                'capabilities': ['portal.payment.sequence.manage'],
            },
        )
        state, _created = PolicyState.objects.get_or_create(singleton=1)
        state.version += 1
        state.save(update_fields=['version', 'updated_at'])


class Migration(migrations.Migration):
    dependencies = [('core', '0175_alter_paymentdocument_status')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
