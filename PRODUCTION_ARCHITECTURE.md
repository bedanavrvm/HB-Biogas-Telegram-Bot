# PRODUCTION MVP ARCHITECTURE
## WhatsApp → Complaint Register Automation System

**Status**: Production-Ready  
**Schema Version**: 2.0 (21-column)  
**Last Updated**: 2026-04-25

---

## System Overview

This MVP integrates WhatsApp complaint data collection into an existing Google Sheets complaint management system. The system is **non-invasive** — it safely appends new rows while preserving all existing formulas, dropdowns, and human workflows.

### Core Principle
> **Automate data capture, not data resolution**
> 
> The bot captures structured complaint data. Humans analyze, decide, and resolve.

---

## Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Field Staff (WhatsApp Group)                                │
│ "Customer Alice has no gas, located in Nairobi, ID: ACC123"│
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ Manual Batch Forward (~2 hour intervals)                    │
│ Forward multiple messages as one batch                      │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ Telegram Bot (Webhook Ingestion)                            │
│ Receives batch message in private channel                   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ Django Message Processor                                    │
│ • Split batch into individual messages                      │
│ • Generate unique message_id (dedup key)                    │
│ • Calculate message fingerprint for dedup                   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ Parser Service (core/services/parser.py)                    │
│ • Detect complaint vs transaction intent                    │
│ • Extract structured fields: name, phone, category, etc.    │
│ • Clean & normalize text                                    │
│ • Extract metadata: GPS, images, source                     │
│ • High confidence scoring                                   │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ Storage & Deduplication Service                             │
│ • Save to DB: ParsedMessage with all fields                 │
│ • Check message_id against previous entries                 │
│ • Skip already-processed complaints                         │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ Google Sheets Service (core/services/sheets.py)             │
│ • Verify sheet structure hasn't changed                     │
│ • Map ParsedMessage → 21-column row                         │
│ • Write to safe columns only (bot-controlled)               │
│ • Append as new row (NEVER mutate existing)                 │
│ • Log sync status for audit trail                           │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│ Google Sheet: Complaints Register (Live)                    │
│ • New rows appended with bot-captured data                  │
│ • Staff continues manual workflow:                          │
│   - Review complaint & documentation                        │
│   - Assign loan status, risk level                          │
│   - Document resolution steps                               │
│   - Mark as resolved when complete                          │
│ • Formulas auto-calculate Days Open, etc.                   │
└─────────────────────────────────────────────────────────────┘
```

---

## Database Schema

### ParsedMessage Model

```python
class ParsedMessage:
    # System fields
    id                    UUID              Primary key
    message_id            CharField(128)    Unique dedup key ★ CRITICAL
    
    # Reference fields
    processed_message     FK                Link to ProcessedMessage
    created_at            DateTime          When record created
    
    # Temporal
    timestamp             DateTime          When message received
    
    # Complaint Intake (BOT WRITES)
    sender                CharField(255)    "Field Agent", "John", etc.
    customer_name         CharField(255)    Extracted from message
    customer_phone        CharField(255)    E.164 or local format
    customer_id           CharField(255)    Account/client reference
    branch_region         CharField(255)    Extracted or mapped
    complaint_category    CharField(255)    Classification (must match dropdown)
    complaint_description TextField         Cleaned complaint text
    
    # Raw Data / Audit Trail
    raw_message           TextField         Original parsed message text
    gps_link              URLField          GPS location if present
    image_flag            Boolean           True if images attached
    source                CharField(50)     "whatsapp_batch", "direct_api"
    
    # Transaction Fields (legacy - preserved for backward compat)
    item, quantity, price, etc.
    
    # Staff-filled Fields (stored but not written by bot)
    complaint_status      CharField         Status: Open/In Progress/Closed
    loan_status           CharField         "Active", "Suspended", etc.
    loan_at_risk          CharField         "Yes", "No", "Under Review"
    risk_level            CharField         "High", "Medium", "Low"
    resolution_details    TextField         Staff notes
    date_resolved         DateTime          When resolved
    days_open             Integer           Formula calculated
    
    # Sync Tracking
    synced_to_sheets      Boolean           True if appended to sheet
    synced_at             DateTime          When synced
    sync_attempts         Integer           Retry counter
    last_sync_error       TextField         Error message if failed
```

---

## Google Sheets Schema (21 Columns)

### Column Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ COLUMN GROUP 1: SYSTEM FIELDS (Formulas - DO NOT WRITE)                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ [0]  Complaint ID          ← AUTO SEQUENCE or FORMULA (bot uses message_id) │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ COLUMN GROUP 2: DEDUPLICATION KEY (Bot System)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ [1]  message_id            ← BOT WRITES (unique per message, for dedup)     │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ COLUMN GROUP 3: BOT INTAKE FIELDS (Automatically populated from WhatsApp)  │
├─────────────────────────────────────────────────────────────────────────────┤
│ [2]  Date Reported         ← BOT WRITES (when message received)             │
│ [3]  Customer Name         ← BOT WRITES (extracted from message)            │
│ [4]  Customer ID / Account ← BOT WRITES (extracted from message)            │
│ [5]  Phone Number          ← BOT WRITES (extracted from message)            │
│ [6]  Reported By           ← BOT WRITES (field agent/sender)                │
│ [7]  Branch / Region       ← BOT WRITES (extracted or best-effort)          │
│ [8]  Complaint Category    ← BOT WRITES (must match dropdown exactly!)      │
│ [9]  Complaint Description ← BOT WRITES (cleaned message text)              │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ COLUMN GROUP 4: RAW DATA / AUDIT TRAIL (For traceability & future AI)      │
├─────────────────────────────────────────────────────────────────────────────┤
│ [10] raw_message           ← BOT WRITES (original parsed message)           │
│ [11] gps_link              ← BOT WRITES (if present in message)             │
│ [12] image_flag            ← BOT WRITES ("TRUE" if images attached)         │
│ [13] source                ← BOT WRITES ("whatsapp_batch", "api", etc.)     │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ COLUMN GROUP 5: HUMAN WORKFLOW (Staff fills in - NEVER write as bot)       │
├─────────────────────────────────────────────────────────────────────────────┤
│ [14] Loan Status           ← HUMAN (dropdown: "Active", "Suspended", ...)   │
│ [15] Loan at Risk          ← HUMAN (dropdown: "Yes", "No", "Under Review")  │
│ [16] Risk Level            ← HUMAN (dropdown: "High", "Medium", "Low")      │
│ [17] Status                ← HUMAN (dropdown: "Open", "In Progress", ...)   │
│ [18] Resolution Details    ← HUMAN (free text notes)                        │
│ [19] Date Resolved         ← HUMAN (date when complaint resolved)           │
│ [20] Days Open             ← FORMULA (auto-calculated: =TODAY()-DateReported)│
└─────────────────────────────────────────────────────────────────────────────┘
```

### Why This Order?

1. **System fields first** → Keeps identifiers stable, preserves formula references
2. **Dedup key early** → Easy for scripts to find and verify
3. **Bot fields grouped** → Clean mapping from parser output
4. **Audit trail together** → For debugging + future AI improvements
5. **Human fields at end** → Staff sees decision fields in expected order
6. **Formulas at appropriate positions** → No interference with bot writes

---

## Core Safety Guarantees

### ✅ DO WRITE (Bot Safe Zone)

Columns [1-13]: `message_id`, `Date Reported`, `Customer Name`, `Customer ID`, `Phone Number`, `Reported By`, `Branch/Region`, `Complaint Category`, `Complaint Description`, `raw_message`, `gps_link`, `image_flag`, `source`

**Rules**:
- Always append to NEW row (never update existing)
- Only write when all required fields extracted
- Leave blank if field cannot be extracted (don't skip columns!)
- Complaint Category MUST match dropdown validation exactly

### ❌ DO NOT WRITE (Protected Zones)

#### Formula Columns:
- **[0] Complaint ID** → Formula or auto-sequence (use message_id value as placeholder)
- **[20] Days Open** → Formula: `=TODAY()-DateReported`

#### Human-Controlled Columns:
- **[14-19] All workflow fields** → Staff fills in during resolution

**Consequence of violation**: Formulas break, staff loses auto-calculated fields, system becomes unreliable

### 🔍 Sheet Structure Detection

Before ANY append operation:

```python
def validate_sheet_structure():
    """
    1. Fetch actual header row from Google Sheet
    2. Verify each column name matches expected schema exactly
    3. Identify which columns are formulas (by inspection)
    4. Verify dropdown validations exist
    5. Return safe_mask: [bool, bool, ...] for each column
    
    If ANY mismatch detected:
    - ABORT append
    - Log detailed error with actual vs expected
    - Alert admin
    """
```

This prevents silent data corruption if sheet structure changes.

---

## Deduplication Strategy

### Message Fingerprinting

```python
def compute_fingerprint(message):
    """
    Hash = SHA256(sender + timestamp_hour + content_hash)
    
    Why this combination?
    - sender: Different agents reporting same complaint
    - timestamp_hour: Catch rapid-fire duplicates
    - content_hash: Detect message rewording
    
    Tolerance: ±15 minutes (handle batch forwarding lag)
    """
    
fingerprint = SHA256(
    sender="Agent John" + 
    hour="2026-04-25T14" + 
    content_hash=SHA256("Customer Alice no gas")
)
```

### Idempotent Operations

```
Duplicate Detection:
  If message_fingerprint in {previously_processed}:
    → Skip (return success without appending)
  
  Reason: Batch forwarding may re-send same message
  Result: Single row for complaint, even if forwarded twice
```

---

## Deployment Checklist

### Prerequisites
- [ ] Google Sheet created with exact 21-column header
- [ ] Dropdowns configured:
  - Complaint Category: [list your valid values]
  - Status: ["Open", "In Progress", "Closed"]
  - Loan Status: ["Active", "Suspended", "Restructured"]
  - Loan at Risk: ["Yes", "No", "Under Review"]
  - Risk Level: ["High", "Medium", "Low"]
- [ ] Formulas in place for Days Open (column 20)
- [ ] Google Service Account created with Sheets API access
- [ ] Render environment variables set

### Pre-Launch Validation
- [ ] Run test parser against sample WhatsApp messages
- [ ] Verify to_sheet_row() produces exactly 21 values
- [ ] Test write to staging Google Sheet
- [ ] Verify deduplication works (send duplicate message, confirm single row)
- [ ] Verify formulas still calculate after bot append
- [ ] Backup production sheet before first real deployment

### Post-Launch Monitoring
- [ ] Check first 5 manual appends for correctness
- [ ] Verify dropdown validation didn't break
- [ ] Monitor sync_attempts and last_sync_error for failures
- [ ] Spot-check Days Open formula calculations
- [ ] Review raw_message for any parsing artifacts

---

## Error Handling & Recovery

### If Append Fails

```python
# Automatic retry logic (in GoogleSheetsService)
if append_failed:
    for attempt in range(1, MAX_RETRIES):
        if attempt < 3:
            time.sleep(attempt ** 2)  # Exponential backoff
            retry_append()
        else:
            save_to_failed_queue()
            alert_admin()
            break
```

### If Sheet Structure Changes

```python
# Immediate detection
if SHEET_COLUMNS != actual_sheet_header:
    BLOCK all appends
    LOG detailed mismatch
    ALERT admin
    WAIT for manual intervention
```

Prevents silent writes to wrong columns.

---

## Future Extensibility

### Planned Enhancements (Priority Order)

1. **Replace Telegram with WhatsApp API** (Phase 2)
   - Direct WhatsApp → backend (no batch forwarding)
   - Real-time ingestion
   - Schema migration: Add `whatsapp_message_id` field

2. **AI Parsing Layer** (Phase 3)
   - Use raw_message column to train complaint classifier
   - Auto-detect category with confidence scoring
   - Flag low-confidence extractions for human review

3. **Dashboard & Reporting** (Phase 4)
   - Overview: New complaints, open count, SLA status
   - Metrics: Resolution time, category breakdown
   - Alerts: High-risk complaints, overdue items

4. **SLA Tracking** (Phase 4)
   - Target response times per category
   - Escalation rules
   - Dashboard alerts for breaches

5. **Mobile Staff App** (Future)
   - Direct complaint submission form
   - GPS capture at source
   - Photo attachments
   - Offline capability with sync

---

## Maintenance & Operations

### Regular Tasks

- **Weekly**: Review `last_sync_error` logs, fix any stuck messages
- **Monthly**: Spot-check raw complaint accuracy, identify parsing gaps
- **Monthly**: Verify formulas still calculating correctly
- **Quarterly**: Audit message deduplication effectiveness

### Potential Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| Blank customer_name | Parser didn't find "NAME:" pattern | Add alias patterns to regex |
| Category not matching dropdown | Typo in extraction | Review raw_message, adjust parser |
| Days Open showing error | Formula references shifted | Verify column structure hasn't changed |
| Duplicate rows appearing | Dedup logic failed | Check message_fingerprint calculation |
| Synced_to_sheets=False but no error | Network timeout (not logged) | Implement connection health checks |

---

## References & Documentation

- [Django Models](../core/models.py) - ParsedMessage schema
- [Parser Service](../core/services/parser.py) - Extraction logic
- [Sheets Service](../core/services/sheets.py) - Append logic
- [Tests](../core/tests.py) - Integration tests for schema
- [Configuration](../config/settings.py) - Google Sheets API setup
