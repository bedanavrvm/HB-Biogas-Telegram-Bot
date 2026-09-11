"""Add durable Portal FarmUp revision/replay state and scoped capabilities."""

from django.db import migrations, models


CAPABILITIES = (
    'portal.farmup.view',
    'portal.farmup.stage',
    'portal.farmup.commit',
)
ROLES = ('IT', 'OPERATIONS_ADMIN')


def seed_portal_farmup_capabilities(apps, schema_editor):
    Capability = apps.get_model('core', 'WorkflowRoleCapability')
    Audit = apps.get_model('core', 'WorkflowRoleCapabilityAuditEvent')
    PolicyState = apps.get_model('core', 'AccessControlPolicyState')

    changed_roles = []
    for role in ROLES:
        created = []
        for key in CAPABILITIES:
            _row, was_created = Capability.objects.get_or_create(
                workflow='jawabu_portal',
                role=role,
                capability_key=key,
                defaults={'enabled': True, 'effect': 'allow'},
            )
            if was_created:
                created.append(key)
        if created:
            changed_roles.append(role)
            Audit.objects.create(
                workflow='jawabu_portal',
                role=role,
                actor=None,
                source='portal_farmup_0171',
                changes={
                    'reason': 'Dedicated scoped Portal FarmUp intake and commit workflow.',
                    'created_capabilities': created,
                },
            )
    if changed_roles:
        state, _created = PolicyState.objects.get_or_create(singleton=1)
        state.version += 1
        state.save(update_fields=['version', 'updated_at'])


def reverse_noop(apps, schema_editor):
    # Live capability policy may have been edited after deployment. Preserve
    # it instead of guessing which reviewed assignments should be removed.
    pass


class Migration(migrations.Migration):

    dependencies = [('core', '0170_tat_terminal_outcome_options')]

    operations = [
        migrations.AddField(
            model_name='jawabufarmeruploadbatch',
            name='portal_revision',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='jawabufarmeruploadbatch',
            name='portal_commit_replays',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(seed_portal_farmup_capabilities, reverse_noop),
    ]
