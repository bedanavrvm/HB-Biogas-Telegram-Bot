from django.db import migrations


def grant_home_to_existing_portal_roles(apps, schema_editor):
    Capability = apps.get_model('core', 'WorkflowRoleCapability')
    for role in ('HB_STAFF', 'BM', 'MANAGEMENT'):
        Capability.objects.get_or_create(
            workflow='jawabu_portal', role=role,
            capability_key='portal.dashboard.view',
            defaults={'enabled': True, 'effect': 'allow'},
        )


class Migration(migrations.Migration):
    dependencies = [('core', '0192_portal_reset_ownership')]
    operations = [migrations.RunPython(grant_home_to_existing_portal_roles, migrations.RunPython.noop)]
