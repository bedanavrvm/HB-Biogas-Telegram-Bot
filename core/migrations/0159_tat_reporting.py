import django.db.models.deletion
import uuid

from django.conf import settings
from django.db import migrations, models


REPORT_ROLES = (
    'BRO', 'BUSINESS_ADMIN', 'CA', 'BM', 'SECRETARY', 'CHAIR',
    'LOAN_APPROVER', 'FINANCE', 'IT', 'MANAGEMENT',
)


def seed_report_capabilities(apps, schema_editor):
    capability = apps.get_model('core', 'WorkflowRoleCapability')
    for role in REPORT_ROLES:
        capability.objects.update_or_create(
            workflow='tat_tracker', role=role, capability_key='tat.reports.view',
            defaults={'enabled': True, 'effect': 'allow'},
        )
    capability.objects.update_or_create(
        workflow='tat_tracker', role='IT', capability_key='tat.reports.people.view',
        defaults={'enabled': True, 'effect': 'allow'},
    )


def remove_report_capabilities(apps, schema_editor):
    apps.get_model('core', 'WorkflowRoleCapability').objects.filter(
        workflow='tat_tracker',
        capability_key__in=('tat.reports.view', 'tat.reports.people.view'),
    ).delete()


class Migration(migrations.Migration):
    dependencies = [('core', '0158_complaint_reports_capability')]

    operations = [
        migrations.AddField(
            model_name='tatpresentationsettings', name='near_target_percent',
            field=models.PositiveSmallIntegerField(default=80, help_text='Percentage of the frozen stage target at which a case is shown as Near Target (50-99).'),
        ),
        migrations.AddConstraint(
            model_name='tatpresentationsettings',
            constraint=models.CheckConstraint(
                condition=models.Q(near_target_percent__gte=50, near_target_percent__lte=99),
                name='tat_presentation_near_target_range',
            ),
        ),
        migrations.RemoveConstraint(
            model_name='workflowtatdailymetric', name='unique_workflow_tat_daily_metric',
        ),
        migrations.AddField(model_name='workflowtatdailymetric', name='metric_grain', field=models.CharField(db_index=True, default='stage_completion_leaf', max_length=32)),
        migrations.AddField(model_name='workflowtatdailymetric', name='outcome', field=models.CharField(blank=True, db_index=True, default='', max_length=24)),
        migrations.AddField(model_name='workflowtatdailymetric', name='near_target_count', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='workflowtatdailymetric', name='stalled_count', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='workflowtatdailymetric', name='target_unavailable_count', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='workflowtatdailymetric', name='created_count', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='workflowtatdailymetric', name='finished_count', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='workflowtatdailymetric', name='disbursed_count', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='workflowtatdailymetric', name='rejected_count', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='workflowtatdailymetric', name='declined_count', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='workflowtatdailymetric', name='sla_met_count', field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='workflowtatdailymetric', name='near_target_percent', field=models.PositiveSmallIntegerField(default=80)),
        migrations.AddField(model_name='workflowtatdailymetric', name='presentation_revision', field=models.PositiveIntegerField(default=0)),
        migrations.AddConstraint(
            model_name='workflowtatdailymetric',
            constraint=models.UniqueConstraint(
                fields=('metric_date', 'workflow', 'group_id', 'branch', 'product_key', 'stage_key', 'responsible_role', 'responsible_actor', 'outcome', 'metric_grain', 'data_scope_key'),
                name='unique_workflow_tat_daily_metric_v2',
            ),
        ),
        migrations.CreateModel(
            name='WorkflowTatMetricRebuildRequest',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('request_key', models.CharField(max_length=160, unique=True)),
                ('correction_revision', models.PositiveIntegerField()),
                ('date_from', models.DateField()),
                ('date_to', models.DateField()),
                ('next_date', models.DateField()),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('processing', 'Processing'), ('complete', 'Complete'), ('failed', 'Failed')], db_index=True, default='pending', max_length=16)),
                ('attempts', models.PositiveSmallIntegerField(default=0)),
                ('last_error', models.CharField(blank=True, default='', max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('case', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='metric_rebuild_requests', to='core.tattrackercase')),
            ],
            options={
                'ordering': ['created_at'],
                'indexes': [models.Index(fields=['status', 'next_date'], name='core_workfl_status_985459_idx')],
                'constraints': [models.UniqueConstraint(fields=('case', 'correction_revision'), name='unique_tat_metric_rebuild_revision')],
            },
        ),
        migrations.RunPython(seed_report_capabilities, remove_report_capabilities),
    ]
