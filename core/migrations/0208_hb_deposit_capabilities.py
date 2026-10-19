from django.db import migrations


GRANTS = (
    ('HB_STAFF', 'portal.hb_deposit.view'),
    ('HB_STAFF', 'portal.hb_deposit.write'),
    ('OPERATIONS_ADMIN', 'portal.hb_deposit.view'),
)


def update(apps, reverse=False):
    Policy = apps.get_model('core', 'WorkflowRoleCapability')
    Audit = apps.get_model('core', 'WorkflowRoleCapabilityAuditEvent')
    State = apps.get_model('core', 'AccessControlPolicyState')
    changed = False
    for role, key in GRANTS:
        query = dict(workflow='jawabu_portal', role=role, capability_key=key)
        if reverse:
            count, _ = Policy.objects.filter(**query, enabled=True, effect='allow').delete()
            modified = bool(count)
        else:
            _, modified = Policy.objects.get_or_create(**query, defaults={'enabled': True, 'effect': 'allow'})
        if modified:
            changed = True
            Audit.objects.create(
                workflow='jawabu_portal', role=role, actor=None, source='hb_deposit_capabilities_0208',
                changes={'capabilities': [key], 'reversed': reverse, 'reason': 'Approved HB pre-visit cumulative deposits; Operations read-only.'},
            )
    if changed:
        state, _ = State.objects.get_or_create(singleton=1)
        state.version += 1
        state.save(update_fields=['version', 'updated_at'])


def seed(apps, schema_editor):
    update(apps)


def unseed(apps, schema_editor):
    update(apps, reverse=True)


class Migration(migrations.Migration):
    dependencies = [('core', '0207_alter_integrationoperation_integration')]
    operations = [migrations.RunPython(seed, unseed)]
