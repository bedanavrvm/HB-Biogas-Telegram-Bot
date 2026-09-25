from django.db import migrations, models
import django.db.models.deletion


def backfill_portal_ownership(apps, schema_editor):
    Group = apps.get_model('core', 'GroupSheetConfiguration')
    Farmer = apps.get_model('core', 'JawabuFarmerMaster')
    Upload = apps.get_model('core', 'JawabuFarmerUploadBatch')
    InvoiceUpload = apps.get_model('core', 'InvoiceUploadBatch')
    Access = apps.get_model('core', 'JawabuMediaAccessEvent')
    groups = {
        row.group_id: row.pk for row in Group.objects.all()
        if (row.workflow or {}).get('type') in {'jawabu', 'jawabu_homebiogas'}
    }
    batch_groups = {
        str(pk): group_id for pk, group_id in
        Upload.objects.filter(group_id__in=groups).values_list('pk', 'group_id')
    }
    for farmer in Farmer.objects.filter(group_configuration__isnull=True).only('pk', 'raw_data').iterator():
        batch_id = str((farmer.raw_data or {}).get('upload_batch_id') or '')
        group_id = batch_groups.get(batch_id) or batch_groups.get(batch_id.lower())
        if group_id:
            Farmer.objects.filter(pk=farmer.pk).update(group_configuration_id=groups[group_id])
    if len(groups) == 1:
        only_group = next(iter(groups.values()))
        Farmer.objects.filter(group_configuration__isnull=True).update(group_configuration_id=only_group)
        InvoiceUpload.objects.filter(group_configuration__isnull=True).update(group_configuration_id=only_group)
    for event in Access.objects.all().only('pk', 'farmer_id', 'attachment_id').iterator():
        Access.objects.filter(pk=event.pk).update(
            farmer_id_snapshot=str(event.farmer_id or ''),
            attachment_id_snapshot=str(event.attachment_id or ''),
        )


class Migration(migrations.Migration):
    dependencies = [('core', '0191_tat_report_insights')]

    operations = [
        migrations.AddField(
            model_name='jawabufarmermaster', name='group_configuration',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='portal_cases', to='core.groupsheetconfiguration',
                db_comment='Portal group that owns this case, including leads entered directly by JBL staff.',
            ),
        ),
        migrations.AddField(
            model_name='invoiceuploadbatch', name='group_configuration',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='portal_invoice_uploads', to='core.groupsheetconfiguration',
                db_comment='Portal group owning this invoice upload independently of its optional order number.',
            ),
        ),
        migrations.AlterField(
            model_name='jawabumediaaccessevent', name='farmer',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='media_access_events', to='core.jawabufarmermaster',
            ),
        ),
        migrations.AlterField(
            model_name='jawabumediaaccessevent', name='attachment',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name='access_events', to='core.mediaattachment',
            ),
        ),
        migrations.AddField(
            model_name='jawabumediaaccessevent', name='farmer_id_snapshot',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='jawabumediaaccessevent', name='attachment_id_snapshot',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.RunPython(backfill_portal_ownership, migrations.RunPython.noop),
    ]
