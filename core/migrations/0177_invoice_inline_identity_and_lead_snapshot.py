from django.db import migrations, models


def preserve_existing_lead_identity(apps, schema_editor):
    Farmer = apps.get_model('core', 'JawabuFarmerMaster')
    for farmer in Farmer.objects.all().iterator(chunk_size=500):
        farmer.lead_name = farmer.customer_name or ''
        farmer.lead_national_id = farmer.national_id or ''
        farmer.lead_primary_phone = farmer.primary_phone or ''
        farmer.lead_secondary_phone = farmer.secondary_phone or ''
        farmer.lead_source_reference = farmer.source_name or farmer.external_id or farmer.source or ''
        farmer.save(update_fields=[
            'lead_name', 'lead_national_id', 'lead_primary_phone',
            'lead_secondary_phone', 'lead_source_reference',
        ])


class Migration(migrations.Migration):
    dependencies = [('core', '0176_payment_sequence_capability')]

    operations = [
        migrations.AddField(
            model_name='jawabufarmermaster', name='lead_name',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='jawabufarmermaster', name='lead_national_id',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='jawabufarmermaster', name='lead_primary_phone',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
        migrations.AddField(
            model_name='jawabufarmermaster', name='lead_secondary_phone',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
        migrations.AddField(
            model_name='jawabufarmermaster', name='lead_source_reference',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='parsedinvoice', name='revision',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.RunPython(preserve_existing_lead_identity, migrations.RunPython.noop),
    ]
