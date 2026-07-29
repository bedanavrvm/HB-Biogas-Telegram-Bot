"""Seed the editable matrix with the role policy that existed before it."""

from django.db import migrations


def seed_capabilities(apps, schema_editor):
    # Import the reviewed, code-owned catalogue rather than accepting a data
    # value from an external system.  The migration creates explicit rows so
    # later Admin edits are immediately authoritative.
    from core.services.workflow_capabilities import capability_definitions

    Capability = apps.get_model('core', 'WorkflowRoleCapability')
    for definition in capability_definitions():
        for role in definition.default_roles:
            Capability.objects.get_or_create(
                workflow=definition.workflow,
                role=role,
                capability_key=definition.key,
                defaults={'enabled': True},
            )


class Migration(migrations.Migration):

    dependencies = [('core', '0069_workflowrolecapability_and_more')]

    operations = [migrations.RunPython(seed_capabilities, migrations.RunPython.noop)]
