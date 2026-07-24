from decimal import Decimal, InvalidOperation
from datetime import datetime
import re
import uuid

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def initialize_case360(apps, schema_editor):
    Farmer = apps.get_model('core', 'JawabuFarmerMaster')
    Event = apps.get_model('core', 'JawabuPipelineEvent')
    now = django.utils.timezone.now()
    events = []
    for farmer in Farmer.objects.iterator(chunk_size=500):
        updates = []
        for fmt in ('%Y-%m-%d', '%d-%B-%Y', '%d-%b-%Y', '%d/%m/%Y', '%d/%m/%y'):
            try:
                farmer.hbg_visit_date = datetime.strptime(str(farmer.sign_date or '').strip(), fmt).date()
                updates.append('hbg_visit_date')
                break
            except ValueError:
                continue
        try:
            text = re.sub(r'[^0-9.\-]', '', str(farmer.actual_receipts or ''))
            amount = Decimal(text) if text else None
            if amount is not None and amount >= 0:
                farmer.deposit_paid_hbg = amount.quantize(Decimal('0.01'))
                updates.append('deposit_paid_hbg')
        except (InvalidOperation, ValueError):
            pass
        if updates:
            farmer.save(update_fields=updates)
        events.append(Event(
            id=uuid.uuid4(), farmer_id=farmer.id, action='tracking_started',
            stage_key='tracking', source='migration', occurred_at=now,
            metadata={'historical_transitions_inferred': False},
        ))
        if len(events) >= 500:
            Event.objects.bulk_create(events)
            events = []
    if events:
        Event.objects.bulk_create(events)


class Migration(migrations.Migration):
    dependencies = [('core', '0051_tat_repair_job')]

    operations = [
        migrations.AddField(model_name='jawabufarmermaster', name='deposit_paid_hbg', field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
        migrations.AddField(model_name='jawabufarmermaster', name='hbg_visit_date', field=models.DateField(blank=True, db_index=True, null=True)),
        migrations.AddField(model_name='jawabufarmermaster', name='latitude_value', field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
        migrations.AddField(model_name='jawabufarmermaster', name='longitude_value', field=models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
        migrations.AddField(model_name='jawabufarmermaster', name='repayment_day', field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name='jawabufarmermaster', name='repayment_tenor_months', field=models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField(model_name='jawabupipelineevent', name='actor_telegram_id', field=models.CharField(blank=True, db_index=True, default='', max_length=100)),
        migrations.AddField(model_name='jawabupipelineevent', name='new_values', field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name='jawabupipelineevent', name='occurred_at', field=models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
        migrations.AddField(model_name='jawabupipelineevent', name='old_values', field=models.JSONField(blank=True, default=dict)),
        migrations.AddField(model_name='jawabupipelineevent', name='request_id', field=models.CharField(blank=True, db_index=True, default='', max_length=128)),
        migrations.AddField(model_name='jawabupipelineevent', name='source', field=models.CharField(blank=True, db_index=True, default='system', max_length=40)),
        migrations.AddField(model_name='jawabupipelineevent', name='stage_key', field=models.CharField(blank=True, db_index=True, default='', max_length=40)),
        migrations.CreateModel(
            name='JawabuDataQualityIssue',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('field_name', models.CharField(db_index=True, max_length=80)),
                ('code', models.CharField(db_index=True, max_length=80)),
                ('severity', models.CharField(db_index=True, default='warning', max_length=20)),
                ('message', models.TextField()),
                ('active', models.BooleanField(db_index=True, default=True)),
                ('detected_at', models.DateTimeField(auto_now_add=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('farmer', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='data_quality_issues', to='core.jawabufarmermaster')),
            ],
            options={'ordering': ['field_name', 'code']},
        ),
        migrations.CreateModel(
            name='JawabuPortalStaffMember',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('telegram_id', models.CharField(db_index=True, max_length=100, unique=True)),
                ('display_name', models.CharField(blank=True, default='', max_length=255)),
                ('roles', models.JSONField(blank=True, default=list)),
                ('branches', models.JSONField(blank=True, default=list)),
                ('active', models.BooleanField(db_index=True, default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['display_name', 'telegram_id']},
        ),
        migrations.RemoveIndex(model_name='jawabupipelineevent', name='core_jawabu_farmer__35ee65_idx'),
        migrations.AddIndex(model_name='jawabupipelineevent', index=models.Index(fields=['farmer', 'occurred_at'], name='jawabu_farmer_timeline_idx')),
        migrations.AddIndex(model_name='jawabupipelineevent', index=models.Index(fields=['farmer', 'stage_key'], name='jawabu_farmer_stage_idx')),
        migrations.AddConstraint(model_name='jawabupipelineevent', constraint=models.UniqueConstraint(condition=~models.Q(request_id=''), fields=('farmer', 'request_id'), name='jawabu_unique_event_request')),
        migrations.AddConstraint(model_name='jawabudataqualityissue', constraint=models.UniqueConstraint(fields=('farmer', 'field_name', 'code'), name='jawabu_unique_quality_issue')),
        migrations.RunPython(initialize_case360, migrations.RunPython.noop),
    ]
