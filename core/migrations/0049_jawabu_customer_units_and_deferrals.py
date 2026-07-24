import uuid

from django.db import migrations, models
import django.db.models.deletion
from django.utils import timezone
from datetime import timedelta


def backfill_customer_identities(apps, schema_editor):
    Farmer = apps.get_model('core', 'JawabuFarmerMaster')
    Customer = apps.get_model('core', 'JawabuCustomer')
    for farmer in Farmer.objects.filter(customer__isnull=True).iterator():
        customer = Customer.objects.create(
            national_id=farmer.national_id or '',
            primary_phone=farmer.primary_phone or '',
            customer_no=farmer.customer_no or '',
            identity_enforced=False,
        )
        farmer.customer_id = customer.id
        farmer.unit_number = 1
        farmer.save(update_fields=['customer', 'unit_number'])


def backfill_deferral_dates(apps, schema_editor):
    Farmer = apps.get_model('core', 'JawabuFarmerMaster')
    now = timezone.now()
    for farmer in Farmer.objects.all().iterator():
        stage = ''
        deferred_at = None
        if farmer.final_decision == 'Deferred':
            stage, deferred_at = 'final', farmer.final_decided_at
        elif farmer.credit_decision == 'Deferred':
            stage, deferred_at = 'credit', farmer.credit_decided_at
        elif farmer.jbl_visit_status == 'Deferred / On Hold':
            stage, deferred_at = 'jbl_visit', None
        if not stage:
            continue
        farmer.deferred_stage = stage
        farmer.deferred_at = deferred_at or now
        farmer.deferred_until = timezone.localtime(farmer.deferred_at).date() + timedelta(days=90)
        farmer.save(update_fields=['deferred_stage', 'deferred_at', 'deferred_until'])


class Migration(migrations.Migration):
    dependencies = [('core', '0048_parsedinvoiceevent')]

    operations = [
        migrations.CreateModel(
            name='JawabuCustomer',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('national_id', models.CharField(blank=True, db_index=True, default='', max_length=64)),
                ('primary_phone', models.CharField(blank=True, db_index=True, default='', max_length=32)),
                ('customer_no', models.CharField(blank=True, db_index=True, default='', max_length=64)),
                ('identity_enforced', models.BooleanField(db_index=True, default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddField(model_name='jawabufarmermaster', name='customer', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='applications', to='core.jawabucustomer')),
        migrations.AddField(model_name='jawabufarmermaster', name='unit_number', field=models.PositiveIntegerField(default=1)),
        migrations.AddField(model_name='jawabufarmermaster', name='deferred_at', field=models.DateTimeField(blank=True, db_index=True, null=True)),
        migrations.AddField(model_name='jawabufarmermaster', name='deferred_stage', field=models.CharField(blank=True, db_index=True, default='', max_length=32)),
        migrations.AddField(model_name='jawabufarmermaster', name='deferred_until', field=models.DateField(blank=True, db_index=True, null=True)),
        migrations.CreateModel(
            name='JawabuPipelineEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('action', models.CharField(db_index=True, max_length=40)),
                ('actor', models.CharField(blank=True, default='', max_length=255)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('farmer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='pipeline_events', to='core.jawabufarmermaster')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.RunPython(backfill_customer_identities, migrations.RunPython.noop),
        migrations.RunPython(backfill_deferral_dates, migrations.RunPython.noop),
        migrations.AddConstraint(model_name='jawabucustomer', constraint=models.UniqueConstraint(condition=models.Q(identity_enforced=True) & ~models.Q(national_id=''), fields=('national_id',), name='jawabu_customer_unique_national_id')),
        migrations.AddConstraint(model_name='jawabucustomer', constraint=models.UniqueConstraint(condition=models.Q(identity_enforced=True) & ~models.Q(primary_phone=''), fields=('primary_phone',), name='jawabu_customer_unique_primary_phone')),
        migrations.AddConstraint(model_name='jawabucustomer', constraint=models.UniqueConstraint(condition=models.Q(identity_enforced=True) & ~models.Q(customer_no=''), fields=('customer_no',), name='jawabu_customer_unique_customer_no')),
        migrations.AddConstraint(model_name='jawabufarmermaster', constraint=models.UniqueConstraint(condition=models.Q(customer__isnull=False), fields=('customer', 'unit_number'), name='jawabu_unique_customer_unit')),
        migrations.AddIndex(model_name='jawabufarmermaster', index=models.Index(fields=['customer', 'unit_number'], name='core_jawabu_custome_2783e7_idx')),
        migrations.AddIndex(model_name='jawabufarmermaster', index=models.Index(fields=['deferred_until', 'status'], name='core_jawabu_deferre_ae3b9b_idx')),
        migrations.AddIndex(model_name='jawabupipelineevent', index=models.Index(fields=['farmer', 'created_at'], name='core_jawabu_farmer__35ee65_idx')),
    ]
