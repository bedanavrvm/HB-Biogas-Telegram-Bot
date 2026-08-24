from django.db import migrations


def seed_origination_staff_signing_capabilities(apps, schema_editor):
    Capability = apps.get_model('core', 'WorkflowRoleCapability')
    rows = {
        'BM': ('portal.origination.view', 'portal.origination.signing.staff'),
        'MANAGEMENT': ('portal.origination.view', 'portal.origination.signing.staff'),
        'JBL_OFFICER': ('portal.origination.signing.staff',),
    }
    for role, capabilities in rows.items():
        for capability_key in capabilities:
            Capability.objects.get_or_create(
                workflow='jawabu_portal', role=role,
                capability_key=capability_key,
                defaults={'enabled': True, 'effect': 'allow'},
            )


class Migration(migrations.Migration):
    dependencies = [('core', '0128_userminiapppreference_business_hours')]
    operations = [migrations.RunPython(
        seed_origination_staff_signing_capabilities,
        migrations.RunPython.noop,
    )]
