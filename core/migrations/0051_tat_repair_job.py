import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0050_invoice_confirmation_state')]

    operations = [
        migrations.CreateModel(
            name='TatRepairJob',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('product_key', models.CharField(blank=True, db_index=True, default='', max_length=80)),
                ('case_ids', models.JSONField(blank=True, default=list)),
                ('cursor', models.PositiveIntegerField(default=0)),
                ('total_cases', models.PositiveIntegerField(default=0)),
                ('synced_cases', models.PositiveIntegerField(default=0)),
                ('skipped_unlinked', models.PositiveIntegerField(default=0)),
                ('failures', models.JSONField(blank=True, default=list)),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('running', 'Running'), ('completed', 'Completed'), ('completed_with_errors', 'Completed with errors'), ('failed', 'Failed')], db_index=True, default='queued', max_length=32)),
                ('worker_token', models.UUIDField(blank=True, editable=False, null=True)),
                ('heartbeat_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('error', models.TextField(blank=True, default='')),
                ('requested_by', models.CharField(blank=True, default='', max_length=255)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('group_configuration', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tat_repair_jobs', to='core.groupsheetconfiguration')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddIndex(model_name='tatrepairjob', index=models.Index(fields=['status', 'updated_at'], name='core_tatrep_status_2b5f2e_idx')),
    ]
