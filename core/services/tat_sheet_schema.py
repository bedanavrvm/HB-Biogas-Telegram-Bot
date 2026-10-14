"""Named bindings for current and historical TAT register projections."""
from core.services.sheet_columns import NamedColumns

REMARK_HEADERS = ('Remarks / Delays', 'Remarks')


STAGE_HEADERS = {
    'mpesa_to_admin': ('MPESA Sent to Admin',),
    'bm_analysis_approval': ('BM analysis approval',),
    'mpesa_verified': ('MPESA Verified and Sent to CA',),
    'ca_analysis_sent': ('Credit Analysis Sent',),
    'bro_response': ('BRO Response to CA',),
    'bm_response': ('BM Response to CA',),
    'valuation_ready': ('Valuation Ready',),
    'bm_hocc_request': ('BM HOCC Request',),
    'bm_tat_request': ('BM TAT Request',),
    'tat_scheduled': ('HOCC Scheduled', 'TAT Scheduled'),
    'tat_held': ('HOCC Held', 'TAT Held'),
    'decision': ('Decision',),
    'minutes_shared': ('Minutes Shared',),
    'sanctions': ('Sanctions',),
    'bro_applied': ('BRO Applied on System',),
    'disbursement_register': ('Disbursement Register',),
    'register_approved': ('Register Approved',),
    'disbursement': ('Finance Disbursement', 'Disbursement'),
}

TIMESTAMP_HEADERS = {
    'bm_analysis_approval_ts': ('BM analysis approval timestamp',),
    'bm_response_ts': ('BM Response Timestamp',),
    'decision_ts': ('Decision Timestamp',),
    'minutes_shared_ts': ('Minutes Shared Timestamp',),
    'sanctions_ts': ('Sanctions Timestamp',),
    'bro_applied_ts': ('BRO Applied Timestamp',),
    'register_ts': ('Register Timestamp',),
}


def stage_names(stage) -> tuple[str, ...]:
    if getattr(stage, 'sheet_header', ''):
        return (stage.sheet_header,)
    return tuple(dict.fromkeys((*STAGE_HEADERS.get(stage.key, ()), stage.label)))


def stage_minute_names(stage, product=None) -> tuple[str, ...]:
    configured = next((column.aliases for column in product.stage_tat_columns
                       if column.stage_key == stage.key), ()) if product else ()
    return tuple(dict.fromkeys(
        [*configured, *[f'{name} TAT Minutes' for name in stage_names(stage)]]
        + [f'{stage.label} TAT', f'{stage.key} TAT Minutes']
    ))


def timestamp_names(stage) -> tuple[str, ...]:
    return TIMESTAMP_HEADERS.get(stage.auto_timestamp_key, (f'{stage.label} timestamp',))


def stage_binding(columns: NamedColumns, stage, *, required=True):
    return columns.column(*stage_names(stage), required=required)


def case_row(case, product, headers, existing_values=None):
    from core.services.tat_tracker import (
        StageConfig, TAT_GLOBAL_SHEET_NAME, calculated_tat_minutes,
        calculated_tat_hours, calculated_tat_days, sheet_datetime,
        sheet_value_for_stage, stage_tat_minutes,
    )
    columns = NamedColumns(headers, sheet_name=product.sheet_name)
    fields = {'case_id': ('Case ID',), 'status': ('Status',),
              'created': ('Case Created', 'Created'), 'hours': ('TAT Hours',), 'days': ('TAT Days',)}
    for stage in product.stages:
        fields[f'stage:{stage.key}'] = stage_names(stage)
        fields[f'minutes:{stage.key}'] = stage_minute_names(stage, product)
        if stage.auto_timestamp_key:
            fields[f'timestamp:{stage.key}'] = timestamp_names(stage)
    columns.bindings(fields)
    row = list(existing_values or [])
    row.extend([''] * max(0, len(headers) - len(row)))

    def put(value, *names, required=True):
        column = columns.column(*names, required=required)
        if column:
            row[column - 1] = value if value is not None else ''

    put(case.case_id, 'Case ID')
    put(case.client_name, 'Client Name', 'Customer Name')
    put(case.national_id, 'ID NUMBER', 'National ID')
    put(case.primary_phone, 'PHONE NUMBER', 'Primary Phone')
    put(case.branch, 'Branch')
    put(case.bro_name, 'BRO Name')
    put(str(case.amount) if case.amount is not None else '', 'Requested Amount', 'Amount')
    put(sheet_datetime((case.stage_values or {}).get('created')), 'Case Created', 'Created')
    for stage in product.stages:
        row[stage_binding(columns, stage) - 1] = sheet_value_for_stage(stage, (case.stage_values or {}).get(stage.key, ''))
        if stage.auto_timestamp_key:
            put(sheet_datetime((case.stage_values or {}).get(stage.auto_timestamp_key)), *timestamp_names(stage))
        minutes = stage_tat_minutes(case, stage)
        put(float(minutes) if minutes is not None else '', *stage_minute_names(stage, product))
    if product.sheet_name == TAT_GLOBAL_SHEET_NAME:
        from core.services.tat_configuration import GLOBAL_TAT_STAGES
        applicable = {stage.key for stage in product.stages}
        for definition in GLOBAL_TAT_STAGES:
            if definition['key'] in applicable:
                continue
            stage = StageConfig(key=definition['key'], label=definition['label'], column=0,
                                role=definition['role'], auto_timestamp_key=definition.get('auto_timestamp_key', ''))
            column = stage_binding(columns, stage, required=False)
            if column:
                row[column - 1] = ''
            put('', *stage_minute_names(stage), required=False)
            if stage.auto_timestamp_key:
                put('', *timestamp_names(stage), required=False)
    put(case.status, 'Status')
    put(case.remarks, *REMARK_HEADERS)
    minutes = calculated_tat_minutes(case)
    put(float(calculated_tat_hours(case)) if minutes is not None else '', 'TAT Hours')
    put(float(calculated_tat_days(case)) if minutes is not None else '', 'TAT Days')
    put(float(minutes) if minutes is not None else '', 'Total TAT Minutes', 'TAT Minutes', 'Case TAT Minutes', required=False)
    put(case.product_label or product.label, 'Product', 'Product Name', required=False)
    put(case.product_key or product.key, 'Product Key', required=False)
    put(product.workflow_path, 'Loan Cycle Path', 'Workflow Path', required=False)
    put(str(case.final_loan_amount) if case.final_loan_amount is not None else '', 'Final Loan Amount', required=False)
    put(case.current_stage, 'Current Stage', required=False)
    put(sheet_datetime(case.created_at), 'Created At', required=False)
    put(sheet_datetime(case.updated_at), 'Last Updated At', required=False)
    put(case.last_updated_by, 'Last Updated By', required=False)
    return row
