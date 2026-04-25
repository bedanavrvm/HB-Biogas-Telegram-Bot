# Multi-Tenant Architecture

## Vision

**One bot. Multiple groups. Each group → different sheet.**

This system is designed as a **multi-tenant ingestion engine** driven by configuration:
- Single Telegram bot handles all groups
- Each group routes to its own Google Sheet
- Config-driven (no code changes to add groups)
- SOLID principles enforced throughout

---

## Core Design Principles

### 1. **SOLID Principles**
- **S**ingle Responsibility: Each service handles one concern
  - `parser.py` → message parsing
  - `sheets.py` → Google Sheets I/O
  - `storage.py` → database persistence
  - `group_config.py` → group routing

- **O**pen/Closed: System is open for extension (new groups, new parsers) without modifying core code

- **L**iskov Substitution: Services can be swapped (e.g., WhatsApp for Telegram, later)

- **I**nterface Segregation: Each service exposes only necessary methods

- **D**ependency Inversion: High-level modules depend on abstractions (config), not concrete implementations

### 2. **DRY (Don't Repeat Yourself)**
- Group-to-sheet mapping centralized in `GroupRegistry`
- Validation logic extracted to `validators.py`
- Response formatting in `api/validators.py`
- No hardcoded sheet IDs throughout codebase

### 3. **KISS (Keep It Simple, Stupid)**
- MVP starts with environment variable config
- Single source of truth: `settings.py`
- Fallback to legacy single-group mode for backwards compatibility
- No complex permission layers (v1.0)

### 4. **Config-Driven Behavior**
```python
# .env or settings.py

# Single-group mode (backward compatible)
GOOGLE_SHEET_ID = "1a2b3c..."

# Multi-group mode (future)
GROUP_MAPPING = {
    "-100123456789": {
        "sheet_id": "1a2b3c...",
        "sheet_name": "Complaints Register",
    },
    "-100987654321": {
        "sheet_id": "xyz789...",
        "sheet_name": "Support Tickets",
    },
}
```

---

## Multi-Tenant Flow

### Message Ingestion to Sheet Storage

```
1. Telegram Webhook
   ↓
2. Extract group_id from message['chat']['id']
   ↓
3. GroupRegistry.get_group(group_id)
   ├─ If not found → return error (group not configured)
   └─ If found → get sheet_id, sheet_name
   ↓
4. Process & Store
   ├─ Parse message
   ├─ Store in database with group_id
   └─ Associate with sheet_id
   ↓
5. Sync to Google Sheets
   ├─ Initialize GoogleSheetsService with sheet_id
   ├─ Validate sheet structure
   └─ Append row
   ↓
6. Update status
   ├─ If success → synced_to_sheets = True
   └─ If fail → partial status with error
```

### Code Flow

```python
# views.py
def telegram_webhook(request):
    message_data = request.message
    group_id = message_data['chat']['id']
    
    result = _process_telegram_message(message_data)
    # Internally extracts group_id and routes
    return success_response(result)

# api/views.py → _process_single_message()
sheet_id = get_sheet_id_for_group(group_id)  # ← Group routing
parsed_message = process_and_store_message(
    ...,
    group_id=group_id,
    sheet_id=sheet_id,
)

# storage.py → process_and_store_message()
# Stores group_id and sheet_id in database
parsed_message = ParsedMessage.objects.create(
    ...,
    group_id=group_id,
    sheet_id=sheet_id,
)

# sheets.py → append_parsed_message_to_sheet()
service = GoogleSheetsService(sheet_id=sheet_id)
# Uses group-specific sheet
```

---

## GroupRegistry: The Routing Hub

### Purpose
Centralized group-to-sheet mapping. Single source of truth.

### Usage
```python
from core.services.group_config import (
    GroupRegistry,
    get_sheet_id_for_group,
    get_sheet_name_for_group,
)

# Get config for a group
registry = GroupRegistry.get_instance()
config = registry.get_group("-100123456789")
print(config.sheet_id)

# Utility functions for common operations
sheet_id = get_sheet_id_for_group(group_id)
sheet_name = get_sheet_name_for_group(group_id)

# List all groups
all_groups = registry.list_groups()

# Reload from settings (for dynamic config)
registry.reload()
```

### Implementation
- Singleton pattern (one registry per process)
- Lazy-loaded at startup from `settings.GROUP_MAPPING`
- Fallback to legacy `GOOGLE_SHEET_ID` if no mapping provided
- Validation at load time (warns if group missing sheet_id)

---

## Future Extensibility

### Phase 1: Current (MVP)
- ✅ Single bot, multiple groups
- ✅ Config-driven routing
- ✅ Group identification by Telegram chat_id
- ✅ Per-group sheet storage

### Phase 2: Dashboard & Queuing (Q2 2026)
- Per-group activity dashboard
- Async task queue for sheet syncs
- Retry logic with exponential backoff
- Webhook delivery guarantees

### Phase 3: Advanced Tenancy (Q3 2026)
- Per-group permissions/users
- Per-group parsing rules (swap `complaint_parser` for `transaction_parser`, etc.)
- Per-group data models (extensible schema)
- API keys per group

### Phase 4: Multi-Channel (Q4 2026)
- Replace Telegram with WhatsApp API (same routing logic)
- Discord bot support
- Email ingestion
- Single backend, multiple frontends

### Phase 5: AI & Analytics (2027+)
- AI-powered intent detection (complaint vs. sales vs. support ticket)
- Per-group analytics dashboard
- Anomaly detection
- Predictive categorization

---

## Data Isolation

### Database Level
- All messages have `group_id` field (indexed)
- Queries ALWAYS filter by group_id (future: enforce in ORM)
  ```python
  # Correct
  messages = ParsedMessage.objects.filter(group_id=group_id)
  
  # Wrong (returns data from all groups!)
  messages = ParsedMessage.objects.all()
  ```

### Sheet Level
- Each group gets its own Google Sheet (configured in GROUP_MAPPING)
- No sheet is shared between groups
- Validation prevents appending to wrong sheet

### Logging
- All logs include group_id for tracing
  ```python
  logger.info(f"Group {group_id}: Message appended to sheet")
  ```

---

## Configuration Examples

### Single Group (MVP)
```env
GOOGLE_SHEET_ID=1a2b3c...
GOOGLE_SHEET_TAB_NAME=Complaints Register
```
Fallback mode: all messages go to one sheet.

### Two Groups (Common)
```python
# settings.py
GROUP_MAPPING = {
    "-100123456789": {  # Group 1 (complaints)
        "sheet_id": "1a2b3c...",
        "sheet_name": "Complaints Register",
    },
    "-100987654321": {  # Group 2 (support tickets)
        "sheet_id": "xyz789...",
        "sheet_name": "Support Tickets",
    },
}
```

### Dynamic Loading from JSON
```python
# settings.py
import json
GROUP_MAPPING = json.loads(config('GROUP_MAPPING_JSON', default='{}'))
```

Then in `.env`:
```
GROUP_MAPPING_JSON='{"100123456789": {"sheet_id": "1a2b3c...", ...}}'
```

---

## Testing Multi-Group

### Unit Tests
```python
def test_unknown_group_rejected():
    """Unknown groups should return error."""
    config = GroupRegistry.get_group("-999999999")
    assert config is None

def test_disabled_group_rejected():
    """Disabled groups should not be routable."""
    # (in settings.py, set enabled=False)
    config = GroupRegistry.get_group(disabled_group_id)
    assert config is None

def test_message_stored_with_group_id():
    """Messages should preserve group_id in database."""
    msg = process_and_store_message(..., group_id="-100123456789")
    assert msg.group_id == "-100123456789"
```

### Integration Tests
```python
def test_group_1_routes_to_sheet_1():
    """Group 1 messages go to Sheet 1."""
    send_to_telegram_group("-100123456789", "test message")
    
    assert_sheet_has_message("sheet_1_id", "test message")
    assert_sheet_not_has_message("sheet_2_id", "test message")

def test_group_2_routes_to_sheet_2():
    """Group 2 messages go to Sheet 2."""
    send_to_telegram_group("-100987654321", "another message")
    
    assert_sheet_has_message("sheet_2_id", "another message")
    assert_sheet_not_has_message("sheet_1_id", "another message")
```

---

## Logging Strategy

### Per-Group Tracing
```python
logger.info(
    f"[Group {group_id}] Message stored: {message_id}",
    extra={
        'group_id': group_id,
        'sheet_id': sheet_id,
        'message_id': message_id,
    }
)
```

### Failure Scenarios
```python
# Group not found
logger.error(f"Message {msg_id} belongs to unknown group {group_id}")

# Sheet sync failed
logger.warning(
    f"[Group {group_id}] Sheet sync failed (message stored): {error}",
    extra={'group_id': group_id, 'error': error}
)

# Permission denied (future)
logger.error(f"[Group {group_id}] Permission denied: {reason}")
```

---

## Success Criteria

✅ **One bot handles all groups**
- Telegram webhook receives messages from any group
- No separate bot instances needed

✅ **Each group routes to correct sheet**
- GroupRegistry provides correct sheet_id for each group
- Validation prevents cross-group contamination

✅ **No spreadsheet logic is broken**
- All formulas, dropdowns, formatting preserved
- Append-only strategy maintained

✅ **No duplicate records**
- Deduplication key (`message_hash`) unique
- Idempotent sheet writes (message_id de-duping)

✅ **System is clean, modular, and scalable**
- SOLID principles enforced
- Config-driven extensibility
- Ready for Phase 2+

---

## Migration Guide

### From Single-Group to Multi-Group

1. **Backup data** (both database and Google Sheets)

2. **Add migration**
   ```bash
   python manage.py migrate core 0005_multi_group_support
   ```
   Adds `group_id` and `sheet_id` fields to ParsedMessage

3. **Update settings.py**
   ```python
   GROUP_MAPPING = {
       "-100123456789": {
           "sheet_id": "your_existing_sheet_id",
           "sheet_name": "Complaints Register",
       },
   }
   ```

4. **No code changes needed** – routed automatically via chat_id

5. **Backfill group_id (optional)**
   ```python
   # Set all existing messages to default group
   DEFAULT_GROUP_ID = "-100123456789"
   ParsedMessage.objects.filter(group_id='').update(group_id=DEFAULT_GROUP_ID)
   ```

---

## Deployment Considerations

### Render / Free-Tier Hosting
- Group registry loads once at startup (memory efficient)
- No per-request lookups to external config store
- Scales well: 10 groups ~ 100KB memory

### Environment Variables Limit
- `GROUP_MAPPING` JSON can be complex
- If too large, load from JSON file in static storage
  ```python
  import json
  with open('groups.json') as f:
      GROUP_MAPPING = json.load(f)
  ```

### Zero-Downtime Updates
```bash
# Update GROUP_MAPPING in .env
# Trigger health check: GET /api/health/
# Registry reloads on next request/startup
```

---

## Open Questions / Future Decisions

1. **Database per group?** (Currently: shared DB, filtered by group_id)
   - Pro: Maximum isolation
   - Con: Deployment complexity, migration overhead
   - Decision: Start shared, migrate to per-group if scale demands

2. **Custom parsers per group?** (Currently: single parser for all)
   - Pro: Group-specific extraction rules
   - Con: Maintenance overhead
   - Decision: v2.0 feature

3. **Group-level API keys?** (Currently: single API_AUTH_TOKEN)
   - Pro: Secure group isolation, multi-org support
   - Con: Key rotation complexity
   - Decision: v2.0 feature

