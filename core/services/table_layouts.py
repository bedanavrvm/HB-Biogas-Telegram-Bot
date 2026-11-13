"""Personal presentation only; table keys never authorize a data request."""
from core.services.workflow_capabilities import has_capability


COMPLAINT_COLUMNS = (
    'row_number', 'complaint_id', 'date_reported', 'status', 'customer_name',
    'customer_id', 'phone_number', 'secondary_phone_number', 'county', 'constituency', 'village',
    'branch_region', 'reported_by', 'complaint_category', 'complaint_description', 'gps_link',
    'resolution_details', 'resolution_comments', 'jbl_verification_comments', 'date_resolved',
    'days_open', 'resolution_hours', 'hb_response_hours', 'timing_note', 'resolution_history_count',
    'target_outcome', 'target_hours',
)
FARMUP_COLUMNS = ('row_number', 'selected', 'state', 'Source Row', 'Customer Name', 'National ID',
    'Primary Phone', 'Secondary Phone', 'Application Action', 'Additional Unit Reason', 'County',
    'HBG Visit Date', 'Deposit Paid to HB', 'HB Sales Person', 'validation_notes')
COMPLAINT_IMPORT_COLUMNS = ('source_row', 'approval', 'customer_name', 'status', 'clean_status',
    'date_reported', 'clean_date_reported', 'review', 'issues', 'customer_phone', 'customer_id',
    'complaint_description', 'reference')


def definitions(workflow):
    def table(key, label, columns, capability, numbering='row_number'):
        labels = {'row_number': '#', 'source_row': 'Row', 'selected': 'Select', 'approval': 'Approve',
                  'clean_status': 'Imported Status', 'clean_date_reported': 'Imported Reported Date'}
        return {'key': key, 'label': label, 'numbering': numbering, 'capability': capability,
                'columns': [{'id': key, 'label': labels.get(key, key.replace('_', ' ').title())} for key in columns]}
    if workflow == 'jawabu_portal':
        from core.services.portal_reporting import CURATED_REPORT_FIELDS, _field
        from core.services.sheet_publication import OPERATIONAL_FIELDS
        reports = [table('report.' + preset, label, ('row_number', *fields, 'data_origin'), 'portal.reports.view')
                   for preset, fields in CURATED_REPORT_FIELDS.items()
                   for label in ['Reports / ' + preset.title()]]
        for report in reports:
            for column in report['columns'][1:-1]:
                column['label'] = _field(column['id']).label
        legacy = ['source_row', 'approval', 'customer_name', 'review_state', 'national_id', 'primary_phone',
                  'secondary_phone', 'county', 'sub_county', 'village', 'workflow', 'issues', 'match', 'note']
        legacy += [f.name for f in OPERATIONAL_FIELDS['jawabu_master'] if f.name not in legacy]
        legacy += ['legacy_deposit_paid_jbl', 'legacy_sign_date', 'legacy_outcome', 'reviewer_notes', 'imported_case_id']
        return reports + [table('farmup', 'FarmUp Review', FARMUP_COLUMNS, 'portal.farmup.view'),
                          table('legacy', 'Legacy Import Review', list(dict.fromkeys(legacy)), 'portal.case.correct', 'source_row')]
    if workflow == 'complaint_cases':
        return [table('report', 'Complaint Reports', COMPLAINT_COLUMNS, 'complaint.reports.view'),
                table('legacy', 'Legacy Import Review', COMPLAINT_IMPORT_COLUMNS, 'complaint.legacy.manage', 'source_row')]
    return []


def catalogue(user, workflow, access=None):
    tables = []
    for definition in definitions(workflow):
        if not has_capability(user, workflow, definition['capability'], access=access):
            continue
        if definition['key'] == 'legacy':
            from core.models import AccessGrant
            if not user.is_superuser and not AccessGrant.objects.filter(
                user=user, workflow=workflow, role='IT', active=True, branch='', product='',
            ).exists():
                continue
        tables.append({key: value for key, value in definition.items() if key != 'capability'})
    return tables


def normalise_layouts(value, workflow):
    available = {item['key']: item for item in definitions(workflow)}
    if not isinstance(value, dict) or len(value) > len(available) or set(value) - set(available):
        raise ValueError('Choose a valid table layout for this Mini App.')
    result = {}
    for key, layout in value.items():
        if not isinstance(layout, dict) or set(layout) - {'order', 'freeze_through'}:
            raise ValueError('Review the table column order and frozen range.')
        order = layout.get('order', [])
        # Legacy bindings may contain source-only columns; they are display IDs, never ORM paths.
        if (not isinstance(order, list) or len(order) > 200
                or any(not isinstance(item, str) or not item or len(item) > 160
                       or any(ord(char) < 32 for char in item) for item in order)
                or len(set(order)) != len(order)):
            raise ValueError('Choose unique, valid table columns.')
        first = available[key]['numbering']
        order = [first, *[item for item in order if item != first]]
        frozen = layout.get('freeze_through', first)
        if frozen not in order:
            raise ValueError('Choose the last frozen column from the ordered columns.')
        result[key] = {'order': order, 'freeze_through': frozen}
    return result
