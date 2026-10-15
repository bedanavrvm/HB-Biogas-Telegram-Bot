"""Deploy the approved, workflow-scoped Sheet recovery permission."""
from django.db import migrations

CAPABILITY = 'tat.publication.retry'
SOURCE = 'tat_publication_retry_0205'


def change(apps, schema_editor, *, reverse=False):
    alias = schema_editor.connection.alias
    Policy = apps.get_model('core', 'WorkflowRoleCapability')
    Audit = apps.get_model('core', 'WorkflowRoleCapabilityAuditEvent')
    State = apps.get_model('core', 'AccessControlPolicyState')
    query = Policy.objects.using(alias).filter(workflow='tat_tracker', role='IT', capability_key=CAPABILITY)
    changed = False
    if reverse:
        # Any later policy event means this default now belongs to the admin.
        seed = Audit.objects.using(alias).filter(source=SOURCE, workflow='tat_tracker', role='IT').order_by('-created_at').first()
        edited = seed and Audit.objects.using(alias).filter(workflow='tat_tracker', role='IT', created_at__gt=seed.created_at).exists()
        if seed and not edited:
            changed = bool(query.filter(enabled=True, effect='allow').delete()[0])
    else:
        _, changed = Policy.objects.using(alias).get_or_create(
            workflow='tat_tracker', role='IT', capability_key=CAPABILITY,
            defaults={'enabled': True, 'effect': 'allow'},
        )
        if changed:
            Audit.objects.using(alias).create(workflow='tat_tracker', role='IT', actor=None, source=SOURCE,
                changes={'allowed': [CAPABILITY], 'reason': 'Approved TAT Sheet recovery only; other Mini App roles are unchanged.'})
    if changed:
        state, _ = State.objects.using(alias).select_for_update().get_or_create(singleton=1)
        state.version += 1
        state.save(using=alias, update_fields=['version', 'updated_at'])


def forward(apps, schema_editor):
    change(apps, schema_editor)


def backward(apps, schema_editor):
    change(apps, schema_editor, reverse=True)


class Migration(migrations.Migration):
    dependencies = [('core', '0204_tat_bm_analysis_capability')]
    operations = [migrations.RunPython(forward, backward)]
