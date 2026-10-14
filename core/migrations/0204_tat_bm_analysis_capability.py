"""Provision the approved TAT BM action during the normal deployment release."""
from django.db import migrations


CAPABILITY = 'tat.stage.bm_analysis_approval.update'


def provision_bm_action(apps, schema_editor):
    alias = schema_editor.connection.alias
    Policy = apps.get_model('core', 'WorkflowRoleCapability')
    Audit = apps.get_model('core', 'WorkflowRoleCapabilityAuditEvent')
    State = apps.get_model('core', 'AccessControlPolicyState')
    changed = False
    for role in ('BM', 'IT'):
        # An existing explicit deny is a deliberate administrator policy, not
        # a missing default. Preserve it and every unrelated workflow choice.
        _, created = Policy.objects.using(alias).get_or_create(
            workflow='tat_tracker', role=role, capability_key=CAPABILITY,
            defaults={'enabled': True, 'effect': 'allow'},
        )
        if created:
            changed = True
            Audit.objects.using(alias).create(
                workflow='tat_tracker', role=role, actor=None,
                source='tat_bm_analysis_0204',
                changes={'allowed': [CAPABILITY], 'reason': 'Deploy the approved TAT BM analysis action independently of other Mini Apps.'},
            )
    if changed:
        state, _ = State.objects.using(alias).select_for_update().get_or_create(singleton=1)
        state.version += 1
        state.save(using=alias, update_fields=['version', 'updated_at'])


class Migration(migrations.Migration):
    dependencies = [('core', '0203_tat_event_role_attribution')]
    # Reversal retains deployed policy/audit evidence. Disable the action using
    # the governed capability matrix if an operational rollback is required.
    operations = [migrations.RunPython(provision_bm_action, migrations.RunPython.noop)]
