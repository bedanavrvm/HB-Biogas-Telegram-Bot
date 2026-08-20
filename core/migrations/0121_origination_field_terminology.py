from django.db import migrations, models
import django.db.models.deletion


def standardize_known_applicant_field(apps, schema_editor):
    DataField = apps.get_model('core', 'OriginationDataField')
    DataFieldEvent = apps.get_model('core', 'OriginationDataFieldEvent')
    field = DataField.objects.filter(key='borrower_full_name').first()
    if not field:
        return
    aliases = list(field.aliases or [])
    for alias in ('Borrower full name', 'Customer full name', 'Client full name', 'Farmer full name'):
        if alias.casefold() not in {str(item).casefold() for item in aliases}:
            aliases.append(alias)
    field.label = 'Applicant full name'
    field.aliases = aliases
    field.category = 'Applicant'
    field.save(update_fields=['label', 'aliases', 'category', 'updated_at'])
    DataFieldEvent.objects.create(
        data_field=field,
        action='terminology_standardized',
        metadata={
            'preferred_label': 'Applicant full name',
            'historical_key_retained': 'borrower_full_name',
        },
    )


class Migration(migrations.Migration):

    dependencies = [('core', '0120_origination_assignment_version_policy')]

    operations = [
        migrations.AddField(
            model_name='originationdatafield',
            name='preferred_field',
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    'Preferred canonical field for this historical duplicate. Existing '
                    'applications and PDF mappings continue using this field.'
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='legacy_equivalent_fields',
                to='core.originationdatafield',
            ),
        ),
        migrations.AddField(
            model_name='originationdatafield',
            name='terminology_reviewed_distinct',
            field=models.BooleanField(
                default=False,
                help_text='Confirm that this similarly named field has a genuinely distinct meaning.',
            ),
        ),
        migrations.AddConstraint(
            model_name='originationdatafield',
            constraint=models.CheckConstraint(
                condition=models.Q(('preferred_field__isnull', True), ('active', False), _connector='OR'),
                name='orig_field_preferred_requires_inactive',
            ),
        ),
        migrations.AddConstraint(
            model_name='originationdatafield',
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ('preferred_field__isnull', True),
                    ('terminology_reviewed_distinct', False),
                    _connector='OR',
                ),
                name='orig_field_preferred_not_distinct',
            ),
        ),
        migrations.RunPython(standardize_known_applicant_field, migrations.RunPython.noop),
    ]
