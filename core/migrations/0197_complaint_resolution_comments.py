from django.db import migrations, models


def change_policy(apps, remove=False):
    Policy = apps.get_model('core', 'WorkflowRoleCapability')
    Audit = apps.get_model('core', 'WorkflowRoleCapabilityAuditEvent')
    State = apps.get_model('core', 'AccessControlPolicyState')
    for role in ('OFFICER', 'MANAGER', 'HB_STAFF', 'IT'):
        key = dict(workflow='complaint_cases', role=role, capability_key='complaint.case.comment')
        if remove:
            Policy.objects.filter(**key).delete()
        else:
            Policy.objects.update_or_create(**key, defaults={'enabled': True, 'effect': 'allow' if role in ('HB_STAFF', 'IT') else 'deny'})
        Audit.objects.create(workflow='complaint_cases', role=role, source='complaint_comments_0197',
                             changes={'reason': 'Remove comment capability' if remove else 'HB feedback without resolving complaints', 'capability': 'complaint.case.comment'})
    state, _ = State.objects.get_or_create(singleton=1)
    state.version += 1
    state.save(update_fields=['version', 'updated_at'])


def forwards(apps, schema_editor):
    change_policy(apps)


def backwards(apps, schema_editor):
    change_policy(apps, remove=True)


class Migration(migrations.Migration):
    dependencies = [('core', '0196_parsed_invoice_deleted_choices')]
    operations = [
        migrations.AlterField(model_name='portalvoicetranscriptionattempt', name='field_name', field=models.CharField(max_length=64, choices=[
            ('jbl_visit_comment', 'JBL visit comment'), ('final_decision_comment', 'Final decision after-call comment'),
            ('complaint_description', 'Complaint description'), ('complaint_resolution_note', 'Complaint resolution note'),
            ('complaint_resolution_comment', 'Complaint resolution comment'), ('complaint_reopen_reason', 'Complaint reopening reason'),
        ])),
        migrations.RunPython(forwards, backwards),
    ]
