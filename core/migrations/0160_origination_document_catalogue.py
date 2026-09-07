from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


def migrate_document_eligibility(apps, schema_editor):
    Template = apps.get_model('core', 'OriginationDocumentTemplate')
    Eligibility = apps.get_model('core', 'OriginationDocumentProductEligibility')
    Assignment = apps.get_model('core', 'OriginationProductDocumentAssignment')

    rows = set()
    for template in Template.objects.select_related(
        'product_definition__product_version__product',
    ).iterator():
        definition = template.product_definition
        if definition and definition.product_version_id:
            rows.add((template.pk, definition.product_version.product_id))
    for assignment in Assignment.objects.select_related(
        'product_definition__product_version__product', 'template',
    ).iterator():
        definition = assignment.product_definition
        if definition.product_version_id:
            for template_id in Template.objects.filter(
                document_type=assignment.template.document_type,
            ).values_list('pk', flat=True):
                rows.add((template_id, definition.product_version.product_id))
    Eligibility.objects.bulk_create([
        Eligibility(template_id=template_id, product_id=product_id)
        for template_id, product_id in rows
    ], ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0159_tat_reporting'),
    ]

    operations = [
        migrations.CreateModel(
            name='OriginationDocumentProductEligibility',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='created_origination_document_eligibilities', to=settings.AUTH_USER_MODEL)),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='origination_document_eligibilities', to='core.product')),
                ('template', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='product_eligibilities', to='core.originationdocumenttemplate')),
            ],
            options={
                'ordering': ['template__document_type', 'product__name'],
            },
        ),
        migrations.AddConstraint(
            model_name='originationdocumentproducteligibility',
            constraint=models.UniqueConstraint(fields=('template', 'product'), name='unique_origination_document_product_eligibility'),
        ),
        migrations.AddField(
            model_name='originationdocumenttemplate',
            name='eligible_products',
            field=models.ManyToManyField(blank=True, help_text='Global products allowed to use this exact immutable document version. An empty list makes the document unavailable for new applications.', related_name='eligible_origination_document_templates', through='core.OriginationDocumentProductEligibility', to='core.product'),
        ),
        migrations.AddField(
            model_name='loanoriginationapplication',
            name='creation_request_digest',
            field=models.CharField(blank=True, db_index=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='loanoriginationapplication',
            name='supersedes_application',
            field=models.ForeignKey(blank=True, help_text='Cancelled draft replaced through the audited Main LAF restart flow.', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='replacement_applications', to='core.loanoriginationapplication'),
        ),
        migrations.RunPython(migrate_document_eligibility, migrations.RunPython.noop),
    ]
