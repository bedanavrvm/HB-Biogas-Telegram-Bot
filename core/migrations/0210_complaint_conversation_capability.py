from django.db import migrations


def seed(apps, schema_editor):
    Policy = apps.get_model('core', 'WorkflowRoleCapability')
    Audit = apps.get_model('core', 'WorkflowRoleCapabilityAuditEvent')
    State = apps.get_model('core', 'AccessControlPolicyState')
    changed = False
    for role in ('OFFICER', 'MANAGER', 'HB_STAFF', 'IT'):
        _, created = Policy.objects.get_or_create(workflow='complaint_cases', role=role,
            capability_key='complaint.conversation.participate', defaults={'enabled': True, 'effect': 'allow'})
        if created:
            changed = True
            Audit.objects.create(workflow='complaint_cases', role=role, actor=None,
                source='complaint_conversation_0210', changes={'capabilities': ['complaint.conversation.participate'],
                    'reason': 'Approved shared browser staff conversation; HB resolution feedback authority is unchanged.'})
    if changed:
        state, _ = State.objects.get_or_create(singleton=1)
        state.version += 1
        state.save(update_fields=['version', 'updated_at'])


class Migration(migrations.Migration):
    dependencies = [('core', '0209_portal_deposit_date')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
