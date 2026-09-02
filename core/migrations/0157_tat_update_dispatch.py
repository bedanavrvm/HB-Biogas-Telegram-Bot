import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0156_complaint_staff_reference'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='tatnotificationprocessorrun',
            name='dispatch_attention_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='tatnotificationprocessorrun',
            name='processed_dispatch_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.CreateModel(
            name='TatUpdateSideEffectDispatch',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('workflow_revision', models.PositiveIntegerField()),
                ('request_id', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('effect_type', models.CharField(choices=[('sheet_projection', 'Sheet projection'), ('signature_delivery', 'Signature delivery'), ('next_role_alert', 'Next-role alert')], db_index=True, max_length=32)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('running', 'Running'), ('retryable', 'Retryable'), ('succeeded', 'Succeeded'), ('superseded', 'Superseded'), ('needs_attention', 'Needs attention')], db_index=True, default='pending', max_length=24)),
                ('cycle_attempts', models.PositiveSmallIntegerField(default=0)),
                ('total_attempts', models.PositiveIntegerField(default=0)),
                ('next_retry_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('lease_token', models.UUIDField(blank=True, editable=False, null=True)),
                ('lease_started_at', models.DateTimeField(blank=True, null=True)),
                ('last_error_code', models.CharField(blank=True, default='', max_length=80)),
                ('last_error_message', models.CharField(blank=True, default='', max_length=255)),
                ('manual_retry_reason', models.CharField(blank=True, default='', max_length=500)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('case', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='update_dispatches', to='core.tattrackercase')),
                ('manual_retry_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='retried_tat_update_dispatches', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'TAT update dispatch',
                'verbose_name_plural': 'TAT update dispatches',
                'ordering': ['created_at', 'effect_type'],
            },
        ),
        migrations.AddConstraint(
            model_name='tatupdatesideeffectdispatch',
            constraint=models.UniqueConstraint(fields=('case', 'workflow_revision', 'effect_type'), name='unique_tat_update_effect_per_revision'),
        ),
        migrations.AddIndex(
            model_name='tatupdatesideeffectdispatch',
            index=models.Index(fields=['status', 'next_retry_at'], name='tat_update_dispatch_due_idx'),
        ),
        migrations.AddIndex(
            model_name='tatupdatesideeffectdispatch',
            index=models.Index(fields=['case', 'workflow_revision'], name='tat_update_dispatch_case_idx'),
        ),
    ]
