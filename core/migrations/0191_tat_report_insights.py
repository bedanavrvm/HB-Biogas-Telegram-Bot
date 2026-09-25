from django.db import migrations, models


INSIGHTS = (
    'trend', 'case_progression', 'backlog_age', 'sla_compliance', 'tat_percentiles',
    'stage_target', 'explorer', 'heatmap', 'target_review_signals', 'oldest_cases',
)


def preserve_report_access(apps, schema_editor):
    Policy = apps.get_model('core', 'WorkflowRoleCapability')
    Audit = apps.get_model('core', 'WorkflowRoleCapabilityAuditEvent')
    Presentation = apps.get_model('core', 'TatPresentationSettings')
    Presentation.objects.filter(singleton=1).update(report_panel_order=list(INSIGHTS))
    roles = Policy.objects.filter(
        workflow='tat_tracker', capability_key='tat.reports.view', effect='allow', enabled=True,
    ).values_list('role', flat=True).distinct()
    for role in roles:
        added = []
        for insight in INSIGHTS:
            if insight == 'target_review_signals' and role != 'IT':
                continue
            key = f'tat.reports.insight.{insight}'
            _, created = Policy.objects.get_or_create(
                workflow='tat_tracker', role=role, capability_key=key,
                defaults={'effect': 'allow', 'enabled': True},
            )
            if created:
                added.append(key)
        if added:
            Audit.objects.create(
                workflow='tat_tracker', role=role, actor=None,
                source='tat_report_insights_0191', changes={'allowed': added, 'reason': 'Preserve existing report visibility'},
            )


class Migration(migrations.Migration):
    dependencies = [('core', '0190_hb_archive_instead_of_finalized_orders')]
    operations = [
        migrations.AddField(
            model_name='tatpresentationsettings', name='report_panel_order',
            field=models.JSONField(default=list, blank=True),
        ),
        migrations.RunPython(preserve_report_access, migrations.RunPython.noop),
    ]
