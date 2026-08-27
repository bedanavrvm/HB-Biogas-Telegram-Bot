import uuid

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0137_origination_conditional_approval'),
    ]

    operations = [
        migrations.CreateModel(
            name='TatNotificationProcessorRun',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('status', models.CharField(choices=[('running', 'Running'), ('succeeded', 'Succeeded'), ('failed', 'Failed'), ('skipped_overlap', 'Skipped because another run was active')], db_index=True, max_length=24)),
                ('active_lock_key', models.CharField(blank=True, editable=False, max_length=64, null=True, unique=True)),
                ('started_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('completed_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('processed_task_count', models.PositiveIntegerField(default=0)),
                ('retry_recipient_count', models.PositiveIntegerField(default=0)),
                ('overdue_recipient_count', models.PositiveIntegerField(default=0)),
                ('unreachable_recipient_count', models.PositiveIntegerField(default=0)),
                ('error_code', models.CharField(blank=True, default='', max_length=80)),
                ('error_message', models.CharField(blank=True, default='', max_length=500)),
            ],
            options={
                'verbose_name': 'TAT notification processor run',
                'verbose_name_plural': 'TAT notification processor runs',
                'ordering': ['-started_at'],
                'indexes': [models.Index(fields=['status', 'started_at'], name='tat_notify_run_status_idx')],
            },
        ),
    ]
