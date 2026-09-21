"""Keep Portal operational settings limited to IT and Operations."""

from django.db import migrations


WORKFLOW = 'jawabu_portal'
OPERATIONS_SETTINGS = 'portal.settings.operations.view'
HEALTH = 'portal.health.read'
OPERATIONS_ROLES = ('IT', 'OPERATIONS_ADMIN')
REMOVED_HEALTH_ROLES = ('HB_STAFF', 'BUSINESS_ADMIN')


def scope_operational_settings(apps, schema_editor):
    Policy = apps.get_model('core', 'WorkflowRoleCapability')
    Audit = apps.get_model('core', 'WorkflowRoleCapabilityAuditEvent')
    PolicyState = apps.get_model('core', 'AccessControlPolicyState')
    changes = []

    for role in OPERATIONS_ROLES:
        _row, created = Policy.objects.get_or_create(
            workflow=WORKFLOW, role=role, capability_key=OPERATIONS_SETTINGS,
            defaults={'enabled': True, 'effect': 'allow'},
        )
        if created:
            changes.append(f'{role}: granted {OPERATIONS_SETTINGS}')

    for role in REMOVED_HEALTH_ROLES:
        previous = Policy.objects.filter(
            workflow=WORKFLOW, role=role, capability_key=HEALTH,
        ).values('enabled', 'effect').first()
        _row, created = Policy.objects.update_or_create(
            workflow=WORKFLOW, role=role, capability_key=HEALTH,
            defaults={'enabled': False, 'effect': 'deny'},
        )
        if created or not previous or previous['enabled'] or previous['effect'] != 'deny':
            # ``update_or_create`` has already applied the correct policy.
            changes.append(f'{role}: removed {HEALTH}')

    if changes:
        Audit.objects.create(
            workflow=WORKFLOW, role='', actor=None,
            source='portal_settings_operations_scope_0187',
            changes={
                'reason': 'Portal Settings keeps operational controls and workflow health limited to IT and Operations.',
                'changes': changes,
            },
        )
        state, _created = PolicyState.objects.get_or_create(singleton=1)
        state.version += 1
        state.save(update_fields=['version', 'updated_at'])


def reverse_noop(apps, schema_editor):
    # Later access-policy changes are deliberate and remain authoritative.
    pass


class Migration(migrations.Migration):

    dependencies = [('core', '0186_sysup_import_operations_commit')]

    operations = [migrations.RunPython(scope_operational_settings, reverse_noop)]
