from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone


def prepare_cutover(apps, schema_editor):
    ParsedMessage = apps.get_model('core', 'ParsedMessage')
    CaseUpdate = apps.get_model('core', 'CaseUpdate')
    ImportBatch = apps.get_model('core', 'ComplaintCaseImportBatch')
    ImportItem = apps.get_model('core', 'ComplaintCaseImportItem')
    GroupConfig = apps.get_model('core', 'GroupSheetConfiguration')

    for case in ParsedMessage.objects.filter(complaint_control__isnull=False).exclude(
        complaint_status__in=['Closed', 'Review Needed', 'Reopened']
    ).iterator(chunk_size=500):
        latest = CaseUpdate.objects.filter(parsed_message=case).order_by('-created_at', '-pk').first()
        if latest and latest.old_status == 'Closed' and latest.new_status in {'Open', 'In Progress'}:
            ParsedMessage.objects.filter(pk=case.pk).update(complaint_status='Reopened')

    ImportBatch.objects.filter(status__in=['queued', 'running']).update(
        status='cancelled', last_error_code='complaint_import_retired', lease_token=None,
        completed_at=timezone.now(),
    )
    ImportItem.objects.filter(status__in=['queued', 'running']).update(
        status='cancelled', last_error_code='complaint_import_retired',
        completed_at=timezone.now(),
    )

    fixed_schema = {
        'schema_version': 2,
        'header_row': 1,
        'data_start_row': 2,
        'row_key_field': 'complaint_id',
    }
    for config in GroupConfig.objects.all().iterator(chunk_size=200):
        if str((config.workflow or {}).get('type') or 'case') == 'case':
            workflow = dict(config.workflow or {})
            workflow['header_row'] = 1
            config.workflow = workflow
            config.sheet_schema = fixed_schema
            config.save(update_fields=['workflow', 'sheet_schema'])


class Migration(migrations.Migration):
    dependencies = [('core', '0161_alter_complaintcasecontrol_reference_number')]

    operations = [
        migrations.AlterModelOptions(
            name='complaintcaseimportbatch',
            options={'ordering': ['-created_at'], 'verbose_name': 'Archived complaint import batch', 'verbose_name_plural': 'Archived complaint import batches'},
        ),
        migrations.AlterModelOptions(
            name='complaintcaseimportitem',
            options={'ordering': ['source_index'], 'verbose_name': 'Archived complaint import item', 'verbose_name_plural': 'Archived complaint import items'},
        ),
        migrations.AddField(
            model_name='parsedmessage', name='secondary_phone',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='parsedmessage', name='county',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
        migrations.AddField(
            model_name='parsedmessage', name='sub_county',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
        migrations.AddField(
            model_name='parsedmessage', name='village',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='complaintcasecontrol', name='county_ref',
            field=models.ForeignKey(blank=True, limit_choices_to={'location_type': 'county'}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='complaint_county_cases', to='core.operationallocation'),
        ),
        migrations.AddField(
            model_name='complaintcasecontrol', name='sub_county_ref',
            field=models.ForeignKey(blank=True, limit_choices_to={'location_type': 'sub_county'}, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='complaint_sub_county_cases', to='core.operationallocation'),
        ),
        migrations.RunPython(prepare_cutover, migrations.RunPython.noop),
    ]
