from django.db import migrations


def grant_operations_access(apps, schema_editor):
    Policy = apps.get_model('core', 'WorkflowRoleCapability')
    Audit = apps.get_model('core', 'WorkflowRoleCapabilityAuditEvent')
    PolicyState = apps.get_model('core', 'AccessControlPolicyState')
    existing = Policy.objects.filter(
        workflow='jawabu_portal', role='OPERATIONS_ADMIN',
        capability_key='portal.payment.sequence.manage',
    ).values('enabled', 'effect').first()
    _row, created = Policy.objects.update_or_create(
        workflow='jawabu_portal', role='OPERATIONS_ADMIN',
        capability_key='portal.payment.sequence.manage',
        defaults={'enabled': True, 'effect': 'allow'},
    )
    changed = created or not existing or not existing['enabled'] or existing['effect'] != 'allow'
    if changed:
        Audit.objects.create(
            workflow='jawabu_portal', role='OPERATIONS_ADMIN', actor=None,
            source='payment_sequence_operations_access_0179',
            changes={
                'reason': 'Operations and IT manage the official payment sequence from Portal Settings.',
                'capabilities': ['portal.payment.sequence.manage'],
            },
        )
        state, _created = PolicyState.objects.get_or_create(singleton=1)
        state.version += 1
        state.save(update_fields=['version', 'updated_at'])


class Migration(migrations.Migration):
    dependencies = [('core', '0178_invoice_name_change_pdf_preview')]
    operations = [migrations.RunPython(grant_operations_access, migrations.RunPython.noop)]
