from django.db import migrations, models


def enable_complaint_exports(apps, schema_editor):
    Capability = apps.get_model('core', 'WorkflowRoleCapability')
    for role in ('OFFICER', 'MANAGER', 'IT'):
        Capability.objects.update_or_create(
            workflow='complaint_cases', role=role,
            capability_key='complaint.case.export',
            defaults={'effect': 'allow', 'enabled': True},
        )


def remove_complaint_exports(apps, schema_editor):
    Capability = apps.get_model('core', 'WorkflowRoleCapability')
    Capability.objects.filter(
        workflow='complaint_cases', capability_key='complaint.case.export',
    ).delete()


class Migration(migrations.Migration):
    dependencies = [('core', '0152_productionreleaseaudit')]

    operations = [
        migrations.AddField(
            model_name='groupsheetconfiguration',
            name='complaint_sheet_projection_enabled',
            field=models.BooleanField(
                default=True,
                help_text=(
                    'Publish Complaint Cases to Google Sheets as a best-effort projection. '
                    'Django remains canonical when this is disabled.'
                ),
            ),
        ),
        migrations.AlterField(
            model_name='caseupdate',
            name='sync_status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'), ('success', 'Synced'), ('failed', 'Failed'),
                    ('not_required', 'Django only'),
                ],
                default='pending', max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name='complaintcasecontrol',
            name='sync_status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'), ('success', 'Synced'), ('failed', 'Failed'),
                    ('not_required', 'Django only'),
                ],
                db_index=True, default='pending', max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name='parsedmessage',
            index=models.Index(
                fields=['complaint_status', 'timestamp'],
                name='core_parsed_complaint_time_idx',
            ),
        ),
        migrations.RunPython(enable_complaint_exports, remove_complaint_exports),
    ]
