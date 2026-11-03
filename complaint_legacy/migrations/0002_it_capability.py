from django.db import migrations


def seed(apps,schema_editor):
    Capability=apps.get_model('core','WorkflowRoleCapability')
    row,created=Capability.objects.get_or_create(workflow='complaint_cases',role='IT',capability_key='complaint.legacy.manage',defaults={'enabled':True,'effect':'allow'})
    if created:
        apps.get_model('core','WorkflowRoleCapabilityAuditEvent').objects.create(workflow='complaint_cases',role='IT',actor=None,source='complaint_legacy_0002',changes={'reason':'Explicit historical workbook import; normal complaint intake remains strict.','created_capabilities':['complaint.legacy.manage']})
        state,_=apps.get_model('core','AccessControlPolicyState').objects.get_or_create(singleton=1)
        state.version+=1;state.save(update_fields=['version','updated_at'])


class Migration(migrations.Migration):
    dependencies=[('complaint_legacy','0001_initial')]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
