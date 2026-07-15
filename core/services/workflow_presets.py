"""Workflow presets for simple group configuration.

Adding a new group workflow should usually mean adding one entry here, then
letting Django admin generate the JSON fields from the selected preset.
"""
from copy import deepcopy


MANUAL_PRESET = 'manual'


WORKFLOW_PRESETS = {
    MANUAL_PRESET: {
        'label': 'Manual JSON / custom workflow',
        'description': 'Use advanced JSON fields directly for any workflow.',
        'sheet_name': '',
        'workflow': None,
        'sheet_schema': None,
        'parser_rules': None,
        'admin_fields': {},
    },
    'case': {
        'label': 'Case / Complaints',
        'description': 'Default customer complaint intake and case update workflow.',
        'sheet_name': 'Complaints Register',
        'workflow': {
            'type': 'case',
            'header_row': 1,
        },
        'sheet_schema': {
            'header_row': 1,
            'field_headers': {},
        },
        'parser_rules': {},
        'admin_fields': {
            'header_row': {
                'initial': 1,
                'label': 'Complaint header row',
                'help_text': '1-based row number containing complaint register headers. Use 1 for TEST COMPLAINT MANAGEMENT REGISTER.xlsx.',
            },
            'field_headers': {
                'initial': {},
                'label': 'Complaint header mappings',
                'help_text': (
                    'Optional JSON mapping from canonical complaint fields to sheet headers, '
                    'for example {"complaint_id": "Complaint ID", "message_id": "message_id"}.'
                ),
            },
        },
    },
    'order_approval': {
        'label': 'Order Approval',
        'description': 'BRO order approval updates with Google Drive media.',
        'sheet_name': 'Orders',
        'workflow': {
            'type': 'order_approval',
            'match_field': 'id_number',
            'search_sheet_names': ['Orders'],
            'create_sheet_name': 'Orders',
            'media_field': 'media_urls',
            'record_id_prefix': 'JBL',
            'header_row': 2,
            'media_root_folder': '',
            'fca_master_sheet_id': '',
            'fca_master_sheet_name': 'Master Data',
            'fca_master_header_row': 3,
            'fca_master_data_start_row': 5,
        },
        'sheet_schema': {},
        'parser_rules': {},
        'admin_fields': {
            'search_tabs': {
                'label': 'Search tabs',
                'initial': 'Orders',
                'help_text': 'Comma-separated worksheet tabs searched by ID NUMBER.',
            },
            'match_field': {
                'label': 'Match field',
                'choices': [('id_number', 'ID NUMBER')],
                'initial': 'id_number',
                'help_text': 'Field used to find the existing approval row.',
            },
            'media_field': {
                'label': 'Media column',
                'choices': [('media_urls', 'Media URLs')],
                'initial': 'media_urls',
                'help_text': 'Column where Google Drive links are appended.',
            },
            'header_row': {
                'label': 'Header row',
                'initial': 2,
                'help_text': '1-based row number containing the bot-readable column headers.',
            },
            'media_root_folder': {
                'label': 'Drive group folder',
                'initial': '',
                'help_text': (
                    'Optional folder name under GOOGLE_DRIVE_MEDIA_FOLDER_ID. '
                    'Leave blank to use the group display name.'
                ),
            },
        },
    },
    'tat_tracker': {
        'label': 'TAT Tracker',
        'description': 'Role-based TAT case tracker with Mini App queues and Google Sheet mirroring.',
        'sheet_name': 'TRACKER-SME',
        'workflow': {
            'type': 'tat_tracker',
            'header_row': 2,
            'data_start_row': 5,
            'products': ['logbook', 'mjengo', 'kilimo', 'micro_asset', 'sme'],
            'branches': ['Biogas Unit', 'Embu', 'Nakuru', 'West Nairobi'],
            'allow_unconfigured_users': False,
            'default_roles': ['BRO'],
            'tat_targets_minutes': {
                'sme': {'total': 20160, 'stages': {}},
                'logbook': {'total': 20160, 'stages': {}},
                'mjengo': {'total': 20160, 'stages': {}},
                'kilimo': {'total': 20160, 'stages': {}},
                'micro_asset': {'total': 20160, 'stages': {}},
            },
            'staff': [],
        },
        'sheet_schema': {},
        'parser_rules': {},
        'admin_fields': {},
    },
    'spin_credit_analysis': {
        'label': 'SPIN / CRB Requests',
        'description': 'Imports or captures SPIN and CRB requests. Credit analysis is tracked as the outcome/status.',
        'sheet_name': 'Spin',
        'workflow': {
            'type': 'spin_credit_analysis',
            'header_row': 2,
            'field_headers': {},
            'branches': ['Biogas Unit', 'Embu', 'Nakuru', 'West Nairobi'],
        },
        'sheet_schema': {},
        'parser_rules': {},
        'admin_fields': {
            'header_row': {
                'initial': 2,
                'label': 'SPIN header row',
                'help_text': 'Row number containing the SPIN/CRB sheet headers. SPIN V_2 uses row 2.',
            },
            'legacy_batch_sheet_name': {
                'initial': 'SPIN Legacy Batch',
                'label': 'Legacy batch worksheet tab',
                'help_text': 'Worksheet tab used by /batch WhatsApp export imports. Keep separate from live Mini App requests.',
            },
        },
    },
    'jawabu_homebiogas': {
        'label': 'Jawabu HomeBiogas',
        'description': 'Imports Jawabu WhatsApp visit exports and flags customer identifier duplicates.',
        'sheet_name': 'Jawabu Visits',
        'workflow': {
            'type': 'jawabu_homebiogas',
            'header_row': 1,
            'import_start_date': '2026-05-01',
            'duplicate_key_fields': ['national_id', 'primary_phone'],
            'duplicate_policy': 'flag_for_review',
            'field_headers': {},
            'master_sync_enabled': False,
            'master_sheet_id': '',
            'master_sheet_name': 'Master Data',
            'master_header_row': 3,
            'master_data_start_row': 5,
            'fca_master_sheet_id': '',
            'fca_master_sheet_name': 'Master Data',
            'fca_master_header_row': 3,
            'fca_master_data_start_row': 5,
            'master_import_log_sheet_name': 'Farmers Upload Log',
            'internal_order_sync_enabled': False,
            'internal_order_sheet_id': '',
            'internal_order_sheet_name': 'Orders',
            'internal_order_header_row': 2,
            'internal_order_data_start_row': 3,
            'internal_order_record_id_prefix': 'JBL',
        },
        'sheet_schema': {},
        'parser_rules': {},
        'admin_fields': {
            'import_start_date': {
                'label': 'Import start date',
                'initial': '2026-05-01',
                'help_text': (
                    'Ignore WhatsApp visit messages before this date. '
                    'Use YYYY-MM-DD. Leave blank to import all dates.'
                ),
            },
            'master_sync_enabled': {
                'label': 'Sync reviewed Farmers uploads to Master Data',
                'initial': False,
                'help_text': (
                    'When enabled, committing /farmup review rows writes them '
                    'to the configured Master Data spreadsheet.'
                ),
            },
            'master_sheet_id': {
                'label': 'Master spreadsheet ID',
                'initial': '',
                'help_text': (
                    'Optional. Leave blank to use this group\'s spreadsheet ID.'
                ),
            },
            'master_sheet_name': {
                'label': 'Master data tab',
                'initial': 'Master Data',
                'help_text': 'Worksheet tab where reviewed farmer records are written.',
            },
            'master_header_row': {
                'label': 'Master header row',
                'initial': 3,
                'help_text': '1-based row number containing Master Data column headers.',
            },
            'master_data_start_row': {
                'label': 'Master data start row',
                'initial': 5,
                'help_text': '1-based row number where real Master Data records begin.',
            },
            'master_import_log_sheet_name': {
                'label': 'Farmers import log tab',
                'initial': 'Farmers Upload Log',
                'help_text': 'Optional audit tab for /farmup batch summaries.',
            },
            'internal_order_sync_enabled': {
                'label': 'Sync pipeline updates to internal Order Sheet',
                'initial': False,
                'help_text': 'When enabled, portal updates also create/update rows in the separate internal Order Sheet.',
            },
            'internal_order_sheet_id': {
                'label': 'Internal Order spreadsheet ID',
                'initial': '',
                'help_text': 'Separate Google Sheet document used by Head of Rural/order staff.',
            },
            'internal_order_sheet_name': {
                'label': 'Internal Order tab',
                'initial': 'Orders',
                'help_text': 'Worksheet tab in the internal Order Sheet.',
            },
            'internal_order_header_row': {
                'label': 'Internal Order header row',
                'initial': 2,
                'help_text': '1-based row containing internal Order Sheet headers.',
            },
            'internal_order_data_start_row': {
                'label': 'Internal Order data start row',
                'initial': 3,
                'help_text': '1-based first row where internal order records begin.',
            },
            'internal_order_record_id_prefix': {
                'label': 'Internal Order record ID prefix',
                'initial': 'JBL',
                'help_text': 'Prefix used when creating sequential ORDER RECORD ID values such as JBL-1.',
            },
        },
    },
}


def preset_choices() -> list[tuple[str, str]]:
    return [
        (key, preset['label'])
        for key, preset in WORKFLOW_PRESETS.items()
    ]


def get_preset(preset_key: str) -> dict:
    return WORKFLOW_PRESETS.get(preset_key or MANUAL_PRESET, WORKFLOW_PRESETS[MANUAL_PRESET])


def preset_for_workflow(workflow: dict) -> str:
    workflow_type = (workflow or {}).get('type')
    if workflow_type and workflow_type in WORKFLOW_PRESETS:
        return workflow_type
    if not workflow:
        return 'case'
    return MANUAL_PRESET


def build_workflow_from_preset(
    preset_key: str,
    overrides: dict = None,
) -> dict | None:
    preset = get_preset(preset_key)
    workflow = preset.get('workflow')
    if workflow is None:
        return None

    workflow = deepcopy(workflow)
    overrides = overrides or {}

    if preset_key == 'case':
        header_row = overrides.get('case_header_row') or overrides.get('header_row')
        if header_row:
            try:
                workflow['header_row'] = max(int(header_row), 1)
            except (TypeError, ValueError):
                pass

    if preset_key == 'jawabu_homebiogas':
        if 'import_start_date' in overrides:
            value = overrides.get('import_start_date')
            if value:
                workflow['import_start_date'] = str(value)
            else:
                workflow.pop('import_start_date', None)
        if 'master_sync_enabled' in overrides:
            workflow['master_sync_enabled'] = bool(overrides.get('master_sync_enabled'))
        if 'internal_order_sync_enabled' in overrides:
            workflow['internal_order_sync_enabled'] = bool(overrides.get('internal_order_sync_enabled'))
        for key in ('master_sheet_id', 'master_sheet_name', 'master_import_log_sheet_name', 'internal_order_sheet_id', 'internal_order_sheet_name', 'internal_order_record_id_prefix'):
            if key in overrides:
                workflow[key] = str(overrides.get(key) or '').strip()
        for key in ('master_header_row', 'master_data_start_row', 'internal_order_header_row', 'internal_order_data_start_row'):
            if key in overrides and overrides.get(key):
                try:
                    workflow[key] = max(int(overrides[key]), 1)
                except (TypeError, ValueError):
                    pass

    if preset_key == 'spin_credit_analysis':
        header_row = overrides.get('spin_header_row') or overrides.get('header_row')
        if header_row:
            try:
                workflow['header_row'] = max(int(header_row), 1)
            except (TypeError, ValueError):
                pass
        legacy_batch_sheet_name = str(overrides.get('legacy_batch_sheet_name') or '').strip()
        if legacy_batch_sheet_name:
            workflow['legacy_batch_sheet_name'] = legacy_batch_sheet_name

    if preset_key == 'order_approval':
        if overrides.get('search_sheet_names'):
            search_sheet_names = list(overrides['search_sheet_names'])
            workflow['search_sheet_names'] = search_sheet_names
            workflow['create_sheet_name'] = search_sheet_names[0]
        if overrides.get('match_field'):
            workflow['match_field'] = overrides['match_field']
        if overrides.get('media_field'):
            workflow['media_field'] = overrides['media_field']
        if overrides.get('header_row'):
            try:
                workflow['header_row'] = max(int(overrides['header_row']), 1)
            except (TypeError, ValueError):
                pass
        media_root_folder = str(overrides.get('media_root_folder') or '').strip()
        if media_root_folder:
            workflow['media_root_folder'] = media_root_folder

    if preset_key == 'tat_tracker':
        existing_workflow = overrides.get('existing_workflow')
        if isinstance(existing_workflow, dict) and existing_workflow.get('type') == 'tat_tracker':
            workflow.update(deepcopy(existing_workflow))
        tat_targets_minutes = overrides.get('tat_targets_minutes')
        if tat_targets_minutes:
            workflow['tat_targets_minutes'] = tat_targets_minutes

    return workflow


def defaults_for_preset(preset_key: str) -> dict:
    preset = get_preset(preset_key)
    return {
        'sheet_name': preset.get('sheet_name') or '',
        'workflow': deepcopy(preset.get('workflow')),
        'sheet_schema': deepcopy(preset.get('sheet_schema')),
        'parser_rules': deepcopy(preset.get('parser_rules')),
    }
