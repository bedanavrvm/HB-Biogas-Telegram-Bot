"""Telegram native command menu definitions."""

CASE_BOT_COMMANDS = [
    {'command': 'last', 'description': 'Show latest cases'},
    {'command': 'recent', 'description': 'Show recent cases'},
    {'command': 'case', 'description': 'Show one case by case ID'},
    {'command': 'update', 'description': 'Update a case status'},
    {'command': 'search', 'description': 'Search cases'},
    {'command': 'today', 'description': "Show today's cases"},
    {'command': 'week', 'description': "Show this week's cases"},
    {'command': 'unsynced', 'description': 'Show cases not synced to Sheets'},
    {'command': 'phone', 'description': 'Search cases by phone number'},
    {'command': 'id', 'description': 'Search cases by customer ID'},
    {'command': 'open', 'description': 'Show cases not marked closed'},
    {'command': 'pending', 'description': 'Show cases with no status'},
    {'command': 'closed', 'description': 'Show closed cases'},
    {'command': 'stale', 'description': 'Show old open cases'},
    {'command': 'errors', 'description': 'Show cases with sync errors'},
    {'command': 'missing', 'description': 'Show cases missing key fields'},
    {'command': 'lowconfidence', 'description': 'Show partial or incomplete cases'},
    {'command': 'risk', 'description': 'Show cases by risk level'},
    {'command': 'duplicates', 'description': 'Show repeated phone or customer IDs'},
    {'command': 'top', 'description': 'Show top regions or issue categories'},
    {'command': 'summary', 'description': 'Show status and sync totals'},
    {'command': 'batch', 'description': 'Import a WhatsApp .txt chat export'},
    {'command': 'sync', 'description': 'Refresh cases from Google Sheets'},
]

SHARED_GROUP_BOT_COMMANDS = [
    {'command': 'group', 'description': "Show this chat's sheet routing"},
    {'command': 'health', 'description': 'Show database and group status'},
    {'command': 'help', 'description': 'Show command help'},
]

ORDER_APPROVAL_BOT_COMMANDS = [
    {'command': 'order', 'description': 'Open the order approval form'},
    {'command': 'form', 'description': 'Open the order approval form'},
]

JAWABU_BOT_COMMANDS = [
    {'command': 'batch', 'description': 'Import a Jawabu WhatsApp export'},
]

PRIVATE_BOT_COMMANDS = (
    ORDER_APPROVAL_BOT_COMMANDS
    + JAWABU_BOT_COMMANDS
    + CASE_BOT_COMMANDS
    + SHARED_GROUP_BOT_COMMANDS
)


def bot_commands_for_workflow(workflow_type: str = '') -> list[dict]:
    if workflow_type == 'order_approval':
        return ORDER_APPROVAL_BOT_COMMANDS + SHARED_GROUP_BOT_COMMANDS
    if workflow_type == 'jawabu_homebiogas':
        return JAWABU_BOT_COMMANDS + SHARED_GROUP_BOT_COMMANDS
    return CASE_BOT_COMMANDS + SHARED_GROUP_BOT_COMMANDS


def private_chat_bot_commands() -> list[dict]:
    return list(PRIVATE_BOT_COMMANDS)
