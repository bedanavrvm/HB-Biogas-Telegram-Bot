from django.db import migrations


CAPABILITIES = (
    'portal.hb_action.view',
    'portal.hb_action.write',
    'portal.hb_action.correct',
)


def seed(apps, schema_editor):
    Policy = apps.get_model('core', 'WorkflowRoleCapability')
    Audit = apps.get_model('core', 'WorkflowRoleCapabilityAuditEvent')
    PolicyState = apps.get_model('core', 'AccessControlPolicyState')
    changed = []
    for capability in CAPABILITIES:
        existing = Policy.objects.filter(
            workflow='jawabu_portal', role='HB_STAFF', capability_key=capability,
        ).values('enabled', 'effect').first()
        Policy.objects.update_or_create(
            workflow='jawabu_portal', role='HB_STAFF', capability_key=capability,
            defaults={'enabled': True, 'effect': 'allow'},
        )
        if not existing or not existing['enabled'] or existing['effect'] != 'allow':
            changed.append(capability)
    if changed:
        Audit.objects.create(
            workflow='jawabu_portal', role='HB_STAFF', actor=None,
            source='homebiogas_action_capabilities_0184',
            changes={
                'reason': 'Dedicated post-order installation and commissioning workspace.',
                'capabilities': changed,
            },
        )
        state, _created = PolicyState.objects.get_or_create(singleton=1)
        state.version += 1
        state.save(update_fields=['version', 'updated_at'])


class Migration(migrations.Migration):
    dependencies = [('core', '0183_complaint_voice_transcription')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]

