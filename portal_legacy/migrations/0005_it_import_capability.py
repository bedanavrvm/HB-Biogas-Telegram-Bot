from django.db import migrations


def seed(apps,schema_editor):
    Capability=apps.get_model('core','WorkflowRoleCapability')
    row,created=Capability.objects.get_or_create(workflow='jawabu_portal',role='IT',capability_key='portal.legacy.manage',defaults={'enabled':True,'effect':'allow'})
    if created:
        apps.get_model('core','WorkflowRoleCapabilityAuditEvent').objects.create(workflow='jawabu_portal',role='IT',actor=None,source='legacy_cutover_0005',changes={'reason':'IT-only reviewed Master Data import; no cross-workflow grants.','created_capabilities':['portal.legacy.manage']})
        state,_=apps.get_model('core','AccessControlPolicyState').objects.get_or_create(singleton=1)
        state.version+=1;state.save(update_fields=['version','updated_at'])


class Migration(migrations.Migration):
    dependencies=[('portal_legacy','0004_resumable_master_cutover'),('core','0212_complaint_verification_comments')]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
