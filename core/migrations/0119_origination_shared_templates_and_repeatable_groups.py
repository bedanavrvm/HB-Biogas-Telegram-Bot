import django.db.models.deletion
import uuid

from django.conf import settings
from django.db import migrations, models


REPEATABLE_STRUCTURE = {
    'min_items': 1,
    'max_items': 11,
    'columns': [
        {
            'key': 'description', 'label': 'Asset description', 'type': 'text',
            'required': True, 'validation': {'max_length': 240},
        },
        {
            'key': 'estimated_value', 'label': 'Estimated value', 'type': 'money',
            'required': True, 'validation': {'min': '0'},
        },
    ],
}


def seed_fields_and_assignments(apps, schema_editor):
    DataField = apps.get_model('core', 'OriginationDataField')
    Template = apps.get_model('core', 'OriginationDocumentTemplate')
    Assignment = apps.get_model('core', 'OriginationProductDocumentAssignment')
    definitions = [
        ('guarantor_1_postal_address', 'Guarantor 1 Postal Address', 'text', 'user_input', 'Guarantor', 'pii', {}),
        ('guarantor_1_town', 'Guarantor 1 Town', 'text', 'user_input', 'Guarantor', 'pii', {}),
        ('guarantor_1_email', 'Guarantor 1 Email', 'text', 'user_input', 'Guarantor', 'pii', {}),
        ('loan_agreement_date', 'Loan Agreement Date', 'date', 'user_input', 'Facility', 'internal', {}),
        ('witness_name', 'Witness Name', 'text', 'user_input', 'Signing', 'pii', {}),
        ('secured_assets', 'Secured Assets', 'repeating_group', 'user_input', 'Security', 'financial', REPEATABLE_STRUCTURE),
        ('secured_assets_total', 'Secured Assets Total', 'money', 'system', 'Security', 'financial', {}),
        ('home_visit_completed_date', 'Home Visit Completion Date', 'date', 'system', 'System', 'internal', {}),
    ]
    for key, label, data_type, source_type, category, sensitivity, structure in definitions:
        DataField.objects.get_or_create(
            key=key,
            defaults={
                'label': label, 'data_type': data_type, 'source_type': source_type,
                'category': category, 'sensitivity': sensitivity,
                'masking_policy': 'partial' if sensitivity in {'pii', 'financial'} else 'none',
                'reporting_use': 'unavailable', 'export_allowed': False,
                'structure_schema': structure,
            },
        )
    for template in Template.objects.filter(
        document_role='supporting', product_definition_id__isnull=False,
        status__in=['ready', 'active'],
    ).iterator():
        Assignment.objects.get_or_create(
            product_definition_id=template.product_definition_id,
            document_key=template.document_key,
            defaults={
                'template_id': template.pk,
                'name': template.name,
                'display_order': template.display_order,
                'inclusion_mode': template.inclusion_mode,
                'officer_selectable': template.officer_selectable,
                'default_selected': template.default_selected,
                'applicability_rule': template.applicability_rule or {},
                'created_by_id': template.created_by_id,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0118_alter_originationdocumenttemplate_options_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='originationdatafield',
            name='structure_schema',
            field=models.JSONField(blank=True, default=dict, help_text='Immutable child-column contract for repeatable-group fields.'),
        ),
        migrations.AlterField(
            model_name='originationdatafield', name='data_type',
            field=models.CharField(choices=[('text', 'Short text'), ('textarea', 'Long text'), ('number', 'Number'), ('money', 'Money'), ('date', 'Date'), ('phone', 'Phone'), ('national_id', 'National ID'), ('choice', 'Choice'), ('boolean', 'Yes / No'), ('branch', 'Governed branch'), ('county', 'Governed county'), ('sub_county', 'Governed sub-county'), ('repeating_group', 'Repeatable group')], max_length=20),
        ),
        migrations.AlterField(
            model_name='originationreportingvalue', name='value_type',
            field=models.CharField(choices=[('text', 'Short text'), ('textarea', 'Long text'), ('number', 'Number'), ('money', 'Money'), ('date', 'Date'), ('phone', 'Phone'), ('national_id', 'National ID'), ('choice', 'Choice'), ('boolean', 'Yes / No'), ('branch', 'Governed branch'), ('county', 'Governed county'), ('sub_county', 'Governed sub-county'), ('repeating_group', 'Repeatable group')], max_length=20),
        ),
        migrations.CreateModel(
            name='OriginationProductDocumentAssignment',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('document_key', models.SlugField(max_length=80)),
                ('name', models.CharField(max_length=180)),
                ('display_order', models.PositiveSmallIntegerField(default=10)),
                ('inclusion_mode', models.CharField(choices=[('required', 'Always required'), ('conditional_required', 'Required when rule matches'), ('optional', 'Officer selectable')], default='required', max_length=24)),
                ('officer_selectable', models.BooleanField(default=False)),
                ('default_selected', models.BooleanField(default=False)),
                ('applicability_rule', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='created_origination_document_assignments', to=settings.AUTH_USER_MODEL)),
                ('product_definition', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='document_assignments', to='core.originationproductdefinition')),
                ('template', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='product_assignments', to='core.originationdocumenttemplate')),
            ],
            options={
                'ordering': ['product_definition', 'display_order', 'document_key'],
                'constraints': [
                    models.UniqueConstraint(fields=('product_definition', 'document_key'), name='unique_origination_product_document_key'),
                    models.UniqueConstraint(fields=('product_definition', 'template'), name='unique_origination_product_template_assignment'),
                ],
            },
        ),
        migrations.AddField(
            model_name='originationapplicationdocument', name='assignment',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='application_documents', to='core.originationproductdocumentassignment'),
        ),
        migrations.AddField(
            model_name='originationapplicationdocument', name='completed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='originationcorrectionitem', name='target_key',
            field=models.CharField(max_length=240),
        ),
        migrations.AlterField(
            model_name='originationcorrectionitem', name='target_type',
            field=models.CharField(choices=[('field', 'Application field'), ('requirement', 'Product requirement'), ('document_field', 'Supporting-document field')], max_length=20),
        ),
        migrations.RunPython(seed_fields_and_assignments, migrations.RunPython.noop),
    ]
