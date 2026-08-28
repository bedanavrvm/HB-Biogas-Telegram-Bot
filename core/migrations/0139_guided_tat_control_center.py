import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def backfill_tat_configuration(apps, schema_editor):
    TatTrackerCase = apps.get_model('core', 'TatTrackerCase')
    ProductTatConfiguration = apps.get_model('core', 'ProductTatConfiguration')
    GroupSheetConfiguration = apps.get_model('core', 'GroupSheetConfiguration')

    for group in GroupSheetConfiguration.objects.iterator():
        workflow = group.workflow or {}
        if str(workflow.get('type') or '') == 'tat_tracker':
            group.tat_sheet_projection_enabled = True
            group.save(update_fields=['tat_sheet_projection_enabled'])

    configurations = {
        row.product_version_id: row
        for row in ProductTatConfiguration.objects.all().iterator()
    }
    for case in TatTrackerCase.objects.select_related('product_version__product').iterator():
        configuration = configurations.get(case.product_version_id)
        if configuration:
            version = case.product_version
            case.tat_configuration_snapshot = {
                'schema_version': 1,
                'product_id': version.product_id,
                'product_key': case.product_key,
                'product_label': case.product_label or version.product.name,
                'product_version_id': str(case.product_version_id),
                'product_version': version.version,
                'min_amount': str(version.min_amount),
                'max_amount': str(version.max_amount) if version.max_amount is not None else '',
                'sheet_name': configuration.sheet_name,
                'case_prefix': configuration.case_prefix,
                'remarks_col': configuration.remarks_col,
                'status_col': configuration.status_col,
                'tat_start_col': configuration.tat_start_col,
                'stage_columns': configuration.stage_columns or {},
                'stages': configuration.stages or [],
                'stage_tat_columns': configuration.stage_tat_columns or [],
            }
            case.configuration_binding_status = 'versioned'
        elif case.stage_values or case.current_stage:
            case.tat_configuration_snapshot = {
                'product_key': case.product_key,
                'stages': [],
                'legacy_stage_keys': sorted(set((case.stage_values or {}).keys())),
            }
            case.configuration_binding_status = 'legacy_assumed'
        else:
            case.configuration_binding_status = 'unresolved'
        case.save(update_fields=['tat_configuration_snapshot', 'configuration_binding_status'])


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0138_tat_notification_processor_run'),
    ]

    operations = [
        migrations.AlterField(
            model_name='groupsheetconfiguration', name='sheet_id',
            field=models.CharField(blank=True, help_text='Google spreadsheet ID for this group.', max_length=255),
        ),
        migrations.AlterField(
            model_name='groupsheetconfiguration', name='sheet_name',
            field=models.CharField(blank=True, default='Complaints Register', help_text='Worksheet/tab name inside the spreadsheet.', max_length=255),
        ),
        migrations.AddField(
            model_name='groupsheetconfiguration', name='tat_sheet_projection_disabled_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='groupsheetconfiguration', name='tat_sheet_projection_enabled',
            field=models.BooleanField(default=False, help_text='Publish the canonical TAT register to Google Sheets for this group.'),
        ),
        migrations.AddField(
            model_name='tatactiontask', name='routing_generation',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='tatactiontaskrecipient', name='routing_generation',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='tattrackercase', name='configuration_binding_status',
            field=models.CharField(choices=[('versioned', 'Versioned'), ('legacy_assumed', 'Legacy assumed'), ('unresolved', 'Unresolved')], db_index=True, default='legacy_assumed', max_length=24),
        ),
        migrations.AddField(
            model_name='tattrackercase', name='tat_configuration_snapshot',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.CreateModel(
            name='TatConfigurationEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('action', models.CharField(db_index=True, max_length=80)),
                ('request_id', models.CharField(blank=True, db_index=True, default='', max_length=128)),
                ('reason', models.TextField(blank=True, default='')),
                ('before_snapshot', models.JSONField(blank=True, default=dict)),
                ('after_snapshot', models.JSONField(blank=True, default=dict)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tat_configuration_events', to=settings.AUTH_USER_MODEL)),
                ('group_configuration', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tat_configuration_events', to='core.groupsheetconfiguration')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='TatResponsibilityChangePlan',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('proposed_snapshot', models.JSONField(default=dict)),
                ('expected_updated_at', models.DateTimeField()),
                ('effective_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('status', models.CharField(choices=[('draft', 'Draft'), ('scheduled', 'Scheduled'), ('applied', 'Applied'), ('cancelled', 'Cancelled'), ('failed', 'Failed')], db_index=True, default='draft', max_length=16)),
                ('reason', models.TextField()),
                ('request_id', models.CharField(max_length=128, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('applied_at', models.DateTimeField(blank=True, null=True)),
                ('error', models.CharField(blank=True, default='', max_length=500)),
                ('assignment', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='change_plans', to='core.tatresponsibilityassignment')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_tat_responsibility_change_plans', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='TatTaskRerouteEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('request_id', models.CharField(db_index=True, max_length=128)),
                ('reason', models.TextField()),
                ('generation_before', models.PositiveIntegerField()),
                ('generation_after', models.PositiveIntegerField()),
                ('before_snapshot', models.JSONField(default=dict)),
                ('after_snapshot', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tat_task_reroute_events', to=settings.AUTH_USER_MODEL)),
                ('task', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reroute_events', to='core.tatactiontask')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddConstraint(
            model_name='tatconfigurationevent',
            constraint=models.UniqueConstraint(condition=~models.Q(request_id=''), fields=('action', 'request_id'), name='unique_tat_configuration_event_request'),
        ),
        migrations.AddConstraint(
            model_name='tattaskrerouteevent',
            constraint=models.UniqueConstraint(fields=('task', 'request_id'), name='unique_tat_task_reroute_request'),
        ),
        migrations.RunPython(backfill_tat_configuration, migrations.RunPython.noop),
    ]
