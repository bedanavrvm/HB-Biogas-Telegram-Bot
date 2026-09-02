from django.db import migrations


CAPABILITY = 'complaint.reports.view'


def seed_management_report_capability(apps, schema_editor):
    Capability = apps.get_model('core', 'WorkflowRoleCapability')
    Capability.objects.update_or_create(
        workflow='complaint_cases',
        role='IT',
        capability_key=CAPABILITY,
        defaults={'enabled': True, 'effect': 'allow'},
    )


def remove_management_report_capability(apps, schema_editor):
    apps.get_model('core', 'WorkflowRoleCapability').objects.filter(
        workflow='complaint_cases', capability_key=CAPABILITY,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [('core', '0157_tat_update_dispatch')]
    operations = [migrations.RunPython(
        seed_management_report_capability,
        remove_management_report_capability,
    )]
