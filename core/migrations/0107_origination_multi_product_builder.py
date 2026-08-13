from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


def backfill_product_lifecycle_and_template_links(apps, schema_editor):
    product_model = apps.get_model('core', 'OriginationProductDefinition')
    template_model = apps.get_model('core', 'OriginationDocumentTemplate')

    product_model.objects.filter(is_active=True).update(lifecycle_status='published')
    product_model.objects.filter(
        is_active=False,
    ).exclude(document_template_sha256='').update(lifecycle_status='retired')
    for template in template_model.objects.filter(product_definition__isnull=True).iterator():
        matches = product_model.objects.filter(
            document_type=template.document_type,
            document_template_version=template.version,
            document_template_sha256=template.source_sha256,
        )
        if matches.count() == 1:
            template.product_definition_id = matches.values_list('pk', flat=True).first()
            template.save(update_fields=['product_definition'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0106_origination_template_calibration'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='OriginationProductDefinitionEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('action', models.CharField(db_index=True, max_length=40)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('occurred_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('actor', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='origination_product_definition_events',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('product_definition', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='events',
                    to='core.originationproductdefinition',
                )),
            ],
            options={'ordering': ['occurred_at', 'id']},
        ),
        migrations.AddField(
            model_name='originationproductdefinition',
            name='lifecycle_status',
            field=models.CharField(
                choices=[('draft', 'Draft'), ('published', 'Published'), ('retired', 'Retired')],
                db_index=True,
                default='draft',
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name='originationproductdefinition',
            name='published_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='originationproductdefinition',
            name='published_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='published_origination_product_definitions',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='originationproductdefinition',
            name='supersedes',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='superseded_by_versions',
                to='core.originationproductdefinition',
            ),
        ),
        migrations.AddField(
            model_name='originationdocumenttemplate',
            name='product_definition',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='document_templates',
                to='core.originationproductdefinition',
            ),
        ),
        migrations.AddField(
            model_name='originationsigningpackage',
            name='template_configuration_snapshot',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='originationsigningpackage',
            name='template_sha256',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.RunPython(
            backfill_product_lifecycle_and_template_links,
            migrations.RunPython.noop,
        ),
    ]
