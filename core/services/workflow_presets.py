"""Workflow presets for simple group configuration.

Adding a new group workflow should usually mean adding one entry here, then
letting Django admin generate the JSON fields from the selected preset.
"""
from copy import deepcopy


MANUAL_PRESET = 'manual'


WORKFLOW_PRESETS = {
    MANUAL_PRESET: {
        'label': 'Manual JSON / complaint workflow',
        'description': 'Use advanced JSON fields directly.',
        'sheet_name': 'Complaints Register',
        'workflow': None,
        'sheet_schema': None,
        'parser_rules': None,
        'admin_fields': {},
    },
    'order_approval': {
        'label': 'Order Approval',
        'description': 'BRO order approval updates with Google Drive media.',
        'sheet_name': 'Pending',
        'workflow': {
            'type': 'order_approval',
            'match_field': 'id_number',
            'search_sheet_names': ['Pending', '178', '179', '180', '181'],
            'media_field': 'media_urls',
        },
        'sheet_schema': {},
        'parser_rules': {},
        'admin_fields': {
            'search_tabs': {
                'label': 'Search tabs',
                'initial': 'Pending, 178, 179, 180, 181',
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

    if preset_key == 'order_approval':
        if overrides.get('search_sheet_names'):
            workflow['search_sheet_names'] = list(overrides['search_sheet_names'])
        if overrides.get('match_field'):
            workflow['match_field'] = overrides['match_field']
        if overrides.get('media_field'):
            workflow['media_field'] = overrides['media_field']

    return workflow


def defaults_for_preset(preset_key: str) -> dict:
    preset = get_preset(preset_key)
    return {
        'sheet_name': preset.get('sheet_name') or '',
        'workflow': deepcopy(preset.get('workflow')),
        'sheet_schema': deepcopy(preset.get('sheet_schema')),
        'parser_rules': deepcopy(preset.get('parser_rules')),
    }
