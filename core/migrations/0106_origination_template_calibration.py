import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_configuration_snapshots(apps, schema_editor):
    application_model = apps.get_model('core', 'LoanOriginationApplication')
    template_model = apps.get_model('core', 'OriginationDocumentTemplate')
    revision_model = apps.get_model('core', 'OriginationTemplateConfigurationRevision')
    for template in template_model.objects.all().iterator():
        revision, _ = revision_model.objects.get_or_create(
            template=template,
            revision=1,
            defaults={
                'configuration': template.placement_config or {},
                'is_published': template.status == 'active',
                'created_by_id': template.created_by_id,
                'published_at': template.activated_at if template.status == 'active' else None,
            },
        )
        if template.status == 'active':
            template.published_configuration_revision_id = revision.pk
            template.save(update_fields=['published_configuration_revision'])
    for application in application_model.objects.select_related('product_definition').iterator():
        definition = application.product_definition
        template = template_model.objects.filter(
            document_type=definition.document_type,
            version=definition.document_template_version,
            source_sha256=definition.document_template_sha256,
        ).order_by('-created_at').first()
        if template:
            application.template_configuration_snapshot = template.placement_config or {}
            application.save(update_fields=['template_configuration_snapshot'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0105_origination_document_templates'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='loanoriginationapplication',
            name='template_configuration_snapshot',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.CreateModel(
            name='OriginationTemplateConfigurationRevision',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('revision', models.PositiveIntegerField()),
                ('configuration', models.JSONField(default=dict)),
                ('is_published', models.BooleanField(db_index=True, default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('published_at', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='origination_template_configuration_revisions', to=settings.AUTH_USER_MODEL)),
                ('template', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='configuration_revisions', to='core.originationdocumenttemplate')),
            ],
            options={'ordering': ['template', '-revision']},
        ),
        migrations.AddField(
            model_name='originationdocumenttemplate',
            name='published_configuration_revision',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='core.originationtemplateconfigurationrevision'),
        ),
        migrations.AddConstraint(
            model_name='originationtemplateconfigurationrevision',
            constraint=models.UniqueConstraint(fields=('template', 'revision'), name='unique_origination_template_config_revision'),
        ),
        migrations.RunPython(backfill_configuration_snapshots, migrations.RunPython.noop),
    ]
