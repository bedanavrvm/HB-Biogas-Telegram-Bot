from django.db import migrations


DERIVED_KEYS = (
    'repayment_tenor_unit',
    'contract_currency',
    'contract_interest_rate_percent',
    'contract_interest_method',
    'contract_interest_rate_period',
    'contract_repayment_frequency',
    'installment_count',
    'installment_amount',
    'final_installment_amount',
    'financed_principal_amount',
    'total_interest_amount',
    'total_repayment_amount',
    'financed_fee_total',
    'upfront_fee_total',
    'loan_fees',
)


def mark_policy_derived_fields(apps, schema_editor):
    OriginationDataField = apps.get_model('core', 'OriginationDataField')
    OriginationDataFieldEvent = apps.get_model('core', 'OriginationDataFieldEvent')
    fields = list(
        OriginationDataField.objects.filter(key__in=DERIVED_KEYS)
        .exclude(source_type='system')
        .order_by('key')
    )
    for field in fields:
        previous = field.source_type
        field.source_type = 'system'
        field.save(update_fields=['source_type', 'updated_at'])
        OriginationDataFieldEvent.objects.create(
            data_field=field,
            action='commercial_contract_governance_updated',
            metadata={
                'key': field.key,
                'contract_version': 2,
                'migration': '0134',
                'source_type_before': previous,
                'source_type_after': 'system',
            },
        )


def restore_policy_fields_as_inputs(apps, schema_editor):
    OriginationDataField = apps.get_model('core', 'OriginationDataField')
    OriginationDataField.objects.filter(
        key__in=DERIVED_KEYS, source_type='system',
    ).update(source_type='user_input')


class Migration(migrations.Migration):
    dependencies = [('core', '0133_origination_commercial_terms')]
    operations = [migrations.RunPython(mark_policy_derived_fields, restore_policy_fields_as_inputs)]
