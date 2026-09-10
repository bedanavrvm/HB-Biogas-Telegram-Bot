from decimal import Decimal

from django.db import migrations, models


GLOBAL_STAGES = [
    {'key': 'mpesa_to_admin', 'label': 'MPESA sent to Admin', 'column': 11, 'role': 'BRO', 'kind': 'timestamp'},
    {'key': 'mpesa_verified', 'label': 'MPESA verified by Business Admin and sent to CA', 'column': 12, 'role': 'BUSINESS_ADMIN', 'kind': 'timestamp'},
    {'key': 'ca_analysis_sent', 'label': 'Credit analysis sent', 'column': 13, 'role': 'CA', 'kind': 'timestamp'},
    {'key': 'bro_response', 'label': 'BRO response to CA', 'column': 14, 'role': 'BRO', 'kind': 'timestamp'},
    {'key': 'bm_response', 'label': 'BM response to CA', 'column': 15, 'role': 'BM', 'kind': 'dropdown', 'options': ['Approved', 'Declined'], 'auto_timestamp_key': 'bm_response_ts', 'requires_signature_certificate': True},
    {'key': 'valuation_ready', 'label': 'Valuation ready', 'column': 17, 'role': 'BM', 'kind': 'timestamp'},
    {'key': 'bm_hocc_request', 'label': 'BM HOCC request', 'column': 18, 'role': 'BM', 'kind': 'timestamp'},
    {'key': 'tat_scheduled', 'label': 'HOCC scheduled', 'column': 19, 'role': 'SECRETARY', 'kind': 'timestamp'},
    {'key': 'tat_held', 'label': 'HOCC held', 'column': 20, 'role': 'SECRETARY', 'kind': 'timestamp'},
    {'key': 'decision', 'label': 'Decision', 'column': 21, 'role': 'CHAIR', 'kind': 'dropdown', 'options': ['Approved', 'Rejected', 'Deferred'], 'auto_timestamp_key': 'decision_ts'},
    {'key': 'minutes_shared', 'label': 'Minutes shared', 'column': 23, 'role': 'SECRETARY', 'kind': 'dropdown', 'options': ['Yes', 'No'], 'auto_timestamp_key': 'minutes_shared_ts'},
    {'key': 'sanctions', 'label': 'Sanctions', 'column': 25, 'role': 'LOAN_APPROVER', 'kind': 'dropdown', 'options': ['Pending', 'Met', 'Not Met'], 'auto_timestamp_key': 'sanctions_ts'},
    {'key': 'bro_applied', 'label': 'BRO applied loan on system', 'column': 27, 'role': 'BRO', 'kind': 'dropdown', 'options': ['Pending', 'Met', 'Not Met'], 'auto_timestamp_key': 'bro_applied_ts'},
    {'key': 'disbursement_register', 'label': 'Business Admin disbursement register', 'column': 30, 'role': 'BUSINESS_ADMIN', 'kind': 'dropdown', 'options': ['10:00am', '1:00pm', '3:30pm'], 'auto_timestamp_key': 'register_ts'},
    {'key': 'register_approved', 'label': 'Register approved', 'column': 32, 'role': 'LOAN_APPROVER', 'kind': 'dropdown', 'options': ['Approved', 'Pending'], 'auto_timestamp_key': 'register_approved_ts'},
    {'key': 'disbursement', 'label': 'Finance disbursement', 'column': 33, 'role': 'FINANCE', 'kind': 'timestamp'},
]


def configure_global_register(apps, schema_editor):
    Config = apps.get_model('core', 'ProductTatConfiguration')
    Group = apps.get_model('core', 'GroupSheetConfiguration')
    Case = apps.get_model('core', 'TatTrackerCase')
    Capability = apps.get_model('core', 'WorkflowRoleCapability')
    tat_columns = [
        {
            'stage_key': stage['key'],
            'fallback_col': 39 + index,
            'aliases': [
                f"{stage['label']} TAT Minutes",
                f"{stage['label']} TAT",
                f"{stage['key']} TAT Minutes",
            ],
        }
        for index, stage in enumerate(GLOBAL_STAGES)
    ]
    for config in Config.objects.select_related('product_version__product'):
        config.sheet_name = 'TAT Register'
        config.remarks_col = 35
        config.status_col = 34
        config.tat_start_col = 36
        config.stage_columns = {
            'created': 8,
            'bm_response_ts': 16,
            'decision_ts': 22,
            'minutes_shared_ts': 24,
            'sanctions_ts': 26,
            'bro_applied_ts': 28,
            'final_loan_amount': 29,
            'register_ts': 31,
        }
        config.stages = GLOBAL_STAGES
        config.stage_tat_columns = tat_columns
        config.requires_valuation = config.product_version.product.code == 'logbook'
        config.hocc_threshold = Decimal('100000')
        config.save()
    for group in Group.objects.all():
        workflow = dict(group.workflow or {})
        if workflow.get('type') != 'tat_tracker':
            continue
        workflow['header_row'] = 1
        workflow['data_start_row'] = 2
        group.workflow = workflow
        group.sheet_name = 'TAT Register'
        group.save(update_fields=['workflow', 'sheet_name', 'updated_at'])
    Case.objects.filter(sheet_name='').update(sheet_name='TAT Register')
    Capability.objects.filter(
        workflow='tat_tracker', capability_key='tat.stage.bm_tat_request.update',
    ).delete()
    for role in ('BM', 'IT'):
        Capability.objects.get_or_create(
            workflow='tat_tracker', role=role,
            capability_key='tat.stage.bm_hocc_request.update',
            defaults={'enabled': True, 'effect': 'allow'},
        )
    from core.services.workflow_capabilities import capability_definitions
    capability_definitions.cache_clear()


class Migration(migrations.Migration):
    dependencies = [('core', '0168_database_catalog_comments_and_view')]

    operations = [
        migrations.AddField(
            model_name='tattrackercase',
            name='final_loan_amount',
            field=models.DecimalField(
                blank=True, decimal_places=2,
                db_comment='Final loan amount recorded by the BRO at system-application stage; the original requested amount remains the immutable route selector.',
                help_text='Final amount entered by the BRO when the loan is applied on the system. The original amount remains the immutable TAT routing amount.',
                max_digits=14, null=True,
            ),
        ),
        migrations.AddField(
            model_name='producttatconfiguration',
            name='requires_valuation',
            field=models.BooleanField(
                default=False,
                db_comment='Whether this product version includes the Logbook valuation stage in its frozen TAT path.',
                help_text='Include the Valuation ready stage for cases using this product version.',
            ),
        ),
        migrations.AddField(
            model_name='producttatconfiguration',
            name='hocc_threshold',
            field=models.DecimalField(
                decimal_places=2, default=Decimal('100000'),
                db_comment='Requested-amount threshold that selects the HOCC loan-cycle path.',
                help_text='Requested amount at or above which the frozen case path includes HOCC stages.',
                max_digits=14,
            ),
        ),
        migrations.RunPython(configure_global_register, migrations.RunPython.noop),
    ]
