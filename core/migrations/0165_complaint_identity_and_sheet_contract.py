from django.db import migrations, models


def enforce_complaint_sheet_contract(apps, schema_editor):
    GroupSheetConfiguration = apps.get_model('core', 'GroupSheetConfiguration')
    for config in GroupSheetConfiguration.objects.all().iterator():
        workflow = dict(config.workflow or {})
        if workflow.get('type') not in {'case', 'complaint'}:
            continue

        workflow['header_row'] = 1
        sheet_schema = dict(config.sheet_schema or {})
        sheet_schema.update({
            'schema_version': 2,
            'header_row': 1,
            'data_start_row': 2,
            'row_key_field': 'complaint_id',
        })
        config.workflow = workflow
        config.sheet_schema = sheet_schema
        config.save(update_fields=['workflow', 'sheet_schema'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0164_complaint_evidence_storage_filename'),
    ]

    operations = [
        migrations.RunPython(enforce_complaint_sheet_contract, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='groupsheetconfiguration',
            name='sheet_id',
            field=models.CharField(
                blank=True,
                help_text='Google spreadsheet ID. Separate workflow configurations may share the same workbook.',
                max_length=255,
            ),
        ),
        migrations.AlterField(
            model_name='groupsheetconfiguration',
            name='sheet_name',
            field=models.CharField(
                blank=True,
                default='Complaints Register',
                help_text='Worksheet/tab for this workflow. Use a distinct tab name when sharing a workbook.',
                max_length=255,
            ),
        ),
    ]
