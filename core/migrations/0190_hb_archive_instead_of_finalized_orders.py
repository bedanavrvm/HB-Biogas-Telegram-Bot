"""Keep HB order access in Document Archive, not the batch-management screen."""

from django.db import migrations


def remove_hb_batch_access(apps, schema_editor):
    Policy = apps.get_model('core', 'WorkflowRoleCapability')
    Audit = apps.get_model('core', 'WorkflowRoleCapabilityAuditEvent')
    PolicyState = apps.get_model('core', 'AccessControlPolicyState')
    key = {'workflow': 'jawabu_portal', 'role': 'HB_STAFF', 'capability_key': 'portal.batches.view'}
    previous = Policy.objects.filter(**key).values('enabled', 'effect').first()
    Policy.objects.update_or_create(**key, defaults={'enabled': False, 'effect': 'deny'})
    if previous is None or previous['enabled'] or previous['effect'] != 'deny':
        Audit.objects.create(
            workflow='jawabu_portal', role='HB_STAFF', actor=None,
            source='hb_archive_instead_of_finalized_orders_0190',
            changes={
                'reason': 'HB staff preview finalized orders through scoped Document Archive; batch management remains Operations-only.',
                'removed': ['portal.batches.view'],
            },
        )
        state, _created = PolicyState.objects.get_or_create(singleton=1)
        state.version += 1
        state.save(update_fields=['version', 'updated_at'])


class Migration(migrations.Migration):
    dependencies = [('core', '0189_fulfillment_partner_orders')]

    operations = [migrations.RunPython(remove_hb_batch_access, migrations.RunPython.noop)]
