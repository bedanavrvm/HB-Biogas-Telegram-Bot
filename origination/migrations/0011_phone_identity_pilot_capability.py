from django.db import migrations
from django.db.models import F


def seed(apps, schema_editor):
    alias = schema_editor.connection.alias
    apps.get_model('core', 'WorkflowRoleCapability').objects.using(alias).get_or_create(
        workflow='loan_origination', role='IT', capability_key='origination.identity.phone.verify',
        defaults={'enabled': True, 'effect': 'allow'},
    )
    bump(apps, schema_editor)


def bump(apps, schema_editor):
    rows = apps.get_model('core', 'AccessControlPolicyState').objects.using(schema_editor.connection.alias)
    rows.get_or_create(singleton=1)
    rows.filter(singleton=1).update(version=F('version') + 1)


class Migration(migrations.Migration):
    dependencies = [('origination', '0010_originationphoneidentitydailyusage_and_more')]
    # Preserve later policy decisions on reversal, as in 0003. Old code ignores
    # the unknown capability; bump the version so active sessions refresh.
    operations = [migrations.RunPython(seed, bump)]
