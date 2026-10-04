from django.db import migrations
from django.db.models import F


POLICY = {
    'origination.view': ('JBL_OFFICER', 'BM', 'MANAGEMENT', 'CA', 'OPERATIONS_ADMIN', 'BUSINESS_ADMIN', 'IT'),
    'origination.create': ('JBL_OFFICER', 'IT'),
    'origination.review': ('OPERATIONS_ADMIN', 'BUSINESS_ADMIN', 'IT'),
    'origination.signing.start': ('OPERATIONS_ADMIN', 'IT'),
    'origination.signing.staff': ('JBL_OFFICER', 'BM', 'MANAGEMENT', 'CA', 'IT'),
}


def forward(apps, schema_editor):
    alias = schema_editor.connection.alias
    rows = apps.get_model('core', 'WorkflowRoleCapability').objects.using(alias)
    for capability, roles in POLICY.items():
        for role in roles:
            rows.get_or_create(workflow='loan_origination', role=role, capability_key=capability,
                               defaults={'enabled': True, 'effect': 'allow'})
    state = apps.get_model('core', 'AccessControlPolicyState').objects.using(alias)
    state.get_or_create(singleton=1)
    state.filter(singleton=1).update(version=F('version') + 1)


def reverse(apps, schema_editor):
    # Keep grants and later policy changes as durable governance evidence.
    # Previous code ignores the new workflow; no Portal grants are restored or copied.
    pass


class Migration(migrations.Migration):
    dependencies = [('origination', '0002_loanoriginationapplication_group_configuration')]
    operations = [migrations.RunPython(forward, reverse)]
