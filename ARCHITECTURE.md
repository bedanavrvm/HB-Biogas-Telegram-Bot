# System Architecture - Biogas Telegram Bot

## 1. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         ACTORS                                   │
├────────────────────────────┬─────────────────────────────────────┤
│  WhatsApp Users            │  Staff Members                     │
│  - Send messages to group  │  - View/edit Google Sheet          │
│  - Forward to Telegram     │  - Monitor data quality            │
└────────────┬───────────────┴──────────────┬──────────────────────┘
             │                              │
             │ Manual Forward               │ Manual Edit
             ▼                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                    TELEGRAM BOT (Ingestion)                      │
│  - Receives forwarded messages                                   │
│  - Sends webhook to Django backend                               │
│  - Handles batch messages                                        │
└──────────────────────┬───────────────────────────────────────────┘
                       │ HTTPS Webhook
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    DJANGO BACKEND (Render)                       │
│                                                                  │
│  ┌────────────────┐   ┌──────────────┐   ┌─────────────────┐   │
│  │  Ingestion     │──▶│Deduplication │──▶│  Parsing Engine │   │
│  │  Layer         │   │  Service     │   │  (Regex)        │   │
│  └────────────────┘   └──────────────┘   └────────┬────────┘   │
│                                                    │            │
│  ┌────────────────┐   ┌──────────────┐            │            │
│  │  Google Sheets │◀──│  Storage     │◀───────────┘            │
│  │  Integration   │   │  Layer       │                         │
│  └────────────────┘   └──────────────┘                         │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              PostgreSQL / SQLite                         │   │
│  │  - RawMessage (audit trail)                              │   │
│  │  - ProcessedMessage (dedup tracking)                     │   │
│  │  - ParsedMessage (structured data)                       │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
                       │ Append-Only
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    GOOGLE SHEETS (Output)                        │
│  - Shared with all staff                                         │
│  - Staff can edit safely (append-only from our side)             │
│  - Fixed schema: 10 columns                                      │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. Data Flow Diagram

```
1. MESSAGE INGESTION
   WhatsApp Group 
     → User forwards to Telegram group
     → Telegram Bot receives message
     → Sends POST to /api/webhook/telegram/

2. BATCH SPLITTING
   Webhook handler receives update
     → Detects if batch (multiple messages)
     → Splits by timestamp+sender pattern
     → Creates individual message objects

3. DEDUPLICATION
   For each message:
     → Generate hash(sender + content + time_window)
     → Check ProcessedMessage table
     → If exists → SKIP (log duplicate)
     → If new → CONTINUE

4. PARSING
   For each new message:
     → Extract GPS URL (if present)
     → Extract timestamp (if present)
     → Extract sender name
     → Match transaction patterns:
       - "Sold X item Y each"
       - "X paid Y for Z item"
       - "X bought Z item @ Y"
     → Calculate confidence score

5. STORAGE
   Atomic transaction:
     → Store RawMessage (immutable)
     → Create ProcessedMessage (dedup key)
     → Create ParsedMessage (structured)

6. GOOGLE SHEETS SYNC
   For each ParsedMessage:
     → Check if message_id exists in sheet
     → If new → append_row()
     → Update synced_to_sheets = True
     → If fail → keep for retry

7. STAFF INTERACTION
   Staff can:
     → View Google Sheet in real-time
     → Edit any cell (except message_id)
     → Add notes, corrections
     → System never overwrites staff edits
```

---

## 3. Module Responsibilities

### 3.1 Ingestion Layer (`core/api/`)

**Files:**
- `views.py` - Webhook handlers, manual processing endpoints
- `urls.py` - API route definitions

**Responsibilities:**
- Receive Telegram webhook payloads
- Validate request authenticity
- Parse message metadata (sender, timestamp, image flag)
- Split batch messages into individual units
- Route to processing pipeline
- Return structured responses

**Key Endpoints:**
```
POST /api/webhook/telegram/   - Telegram webhook
POST /api/process/messages/   - Manual batch upload
POST /api/resync/unsynced/    - Retry failed syncs
GET  /api/health/             - Health check
```

---

### 3.2 Deduplication Service (`core/services/deduplication.py`)

**Responsibilities:**
- Generate deterministic hashes for messages
- Check for duplicate messages
- Track processed messages in database
- Provide batch deduplication checking

**Hash Generation:**
```python
hash_input = f"{sender_norm}|{content_norm}|{time_window}"
message_hash = SHA256(hash_input)[:64]
```

**Deduplication Window:**
- Messages within N minutes (default: 5)
- Same sender + content = duplicate
- Different time window = new message

** Guarantees:**
- Idempotent processing
- Safe webhook retries
- No data loss on errors

---

### 3.3 Parsing Engine (`core/services/parser.py`)

**Responsibilities:**
- Extract structured fields from messy text
- Handle multiple message formats
- Calculate parsing confidence
- Split batch messages

**Supported Patterns:**

| Pattern | Regex | Example |
|---------|-------|---------|
| GPS URL | `https?://[^\s]+` | `📍 https://maps.app.goo.gl/abc` |
| Timestamp | `\[\d{2}/\d{2}/\d{4}.*?\]` | `[15/04/2026, 10:30:15]` |
| Sold | `sold (\d+) (.+) (\d+) each` | `Sold 3 bread 50 each` |
| Paid | `paid (\d+) for (\d+) (.+)` | `Paid 200 for 4 milk` |
| Bought | `bought (\d+) (.+) @ (\d+)` | `Bought 2 bags maize @ 100` |

**Confidence Scoring:**
```
1.00 = sender + item + quantity + price (all extracted)
0.75 = 3/4 fields extracted
0.50 = 2/4 fields extracted
0.25 = 1/4 fields extracted
0.00 = no fields extracted
```

**Error Handling:**
- Empty messages → confidence 0.0, warning logged
- Partial parses → store what's extracted, log missing fields
- Unknown formats → store raw_message, confidence 0.25

---

### 3.4 Storage Layer (`core/services/storage.py`)

**Responsibilities:**
- Atomic transaction management
- Raw message persistence (audit trail)
- Processed message tracking
- Parsed message storage
- Google Sheets sync coordination

**Database Models:**

```python
RawMessage
├── id (UUID, PK)
├── telegram_message_id (indexed)
├── sender
├── content (TEXT)
├── received_at
├── has_image (BOOLEAN)
└── created_at (auto)

ProcessedMessage
├── id (UUID, PK)
├── message_hash (UNIQUE, indexed)
├── raw_message (FK → RawMessage)
├── processed_at (auto)
├── status (success/failed/partial)
└── error_message (TEXT)

ParsedMessage
├── id (UUID, PK)
├── processed_message (FK → ProcessedMessage)
├── message_id (UNIQUE, indexed)
├── timestamp (nullable)
├── sender
├── raw_message (TEXT)
├── item (nullable)
├── quantity (DECIMAL, nullable)
├── price (DECIMAL, nullable)
├── gps_link (URL, nullable)
├── image_flag (BOOLEAN)
├── source (default: "whatsapp_telegram")
├── synced_to_sheets (BOOLEAN)
├── synced_at (nullable)
└── created_at (auto)
```

**Transaction Flow:**
```python
@transaction.atomic:
    1. store_raw_message()
    2. generate_hash()
    3. check_duplicate() → abort if duplicate
    4. mark_as_processed()
    5. parse_message()
    6. store_parsed_message()
    7. append_to_sheets()
    8. commit
```

---

### 3.5 Google Sheets Integration (`core/services/sheets.py`)

**Responsibilities:**
- Authenticate with Google API (OAuth2)
- Append rows to sheet (never overwrite)
- Check message_id for idempotency
- Handle sync failures gracefully

**Schema Enforcement:**
```python
COLUMNS = [
    'message_id',     # A - Unique identifier
    'timestamp',      # B - When transaction occurred
    'sender',         # C - Who sent the message
    'raw_message',    # D - Original text (traceability)
    'item',           # E - What was sold/bought
    'quantity',       # F - How many/much
    'price',          # G - Unit price or total
    'gps_link',       # H - Location URL (if present)
    'image_flag',     # I - TRUE/FALSE
    'source',         # J - Always "whatsapp_telegram"
]
```

**Safety Guarantees:**
- Append-only operations
- message_id uniqueness check before append
- Concurrent staff edits safe (we never modify existing rows)
- Failed syncs queued for retry

---

## 4. Failure Modes & Recovery

### 4.1 Webhook Delivery Failures

**Scenario:** Telegram webhook times out or fails

**Impact:** Message may be retried by Telegram

**Recovery:**
- Deduplication handles retries automatically
- message_id ensures idempotency
- Logs show retry attempts

---

### 4.2 Parsing Failures

**Scenario:** Message format unknown

**Impact:** Partial or no structured data extracted

**Recovery:**
- Raw message always stored
- Confidence score logged
- Can add new regex patterns later
- Staff can manually enter data in sheet

---

### 4.3 Google Sheets API Failures

**Scenario:** API rate limit, auth error, network issue

**Impact:** Data stored in DB but not synced to sheet

**Recovery:**
- `synced_to_sheets = False` flags unsynced messages
- Manual resync endpoint: `POST /api/resync/unsynced/`
- Retry logic on next successful request
- Alerts on prolonged failures

---

### 4.4 Database Corruption

**Scenario:** SQLite file corruption (MVP)

**Impact:** Data loss possible

**Recovery:**
- Regular backups (manual for MVP)
- Migrate to PostgreSQL for production
- Render provides automated backups

---

## 5. Security Considerations

### 5.1 Data Protection

- **Environment variables:** All secrets in `.env` (never committed)
- **Credentials:** `credentials.json` gitignored
- **Webhook secret:** Optional validation header
- **Database:** Encrypted at rest (Render manages this)

### 5.2 Access Control

- **Telegram bot:** Only receives messages from group
- **Google Sheets:** Service account has Editor access to sheet only
- **Django admin:** Protected by authentication
- **API endpoints:** No auth in MVP (webhook is public)

### 5.3 Audit Trail

- **RawMessage:** Immutable, stores original text
- **ProcessedMessage:** Tracks all processing attempts
- **Logging:** All pipeline steps logged
- **Google Sheet:** Staff edits tracked by Google's version history

---

## 6. Performance Characteristics

### 6.1 Expected Load

- **Messages per day:** 50-200 (MVP)
- **Batch size:** 5-20 messages
- **Processing time:** < 500ms per message
- **Sheet updates:** Real-time (append takes ~1s)

### 6.2 Bottlenecks

1. **Google Sheets API** - Rate limited (~100 req/100s)
2. **Database queries** - Deduplication checks
3. **Regex parsing** - Multiple pattern matches

### 6.3 Optimizations (Future)

- Redis cache for deduplication (faster than DB)
- Batch sheet appends (multiple rows at once)
- Compiled regex patterns (pre-compile once)
- Async processing (Celery + Redis)

---

## 7. Monitoring & Observability

### 7.1 Metrics to Track

- Messages processed per hour
- Deduplication rate (% of messages are duplicates)
- Parsing confidence distribution
- Google Sheets sync success rate
- Average processing time per message

### 7.2 Alerting (Future)

- Processing errors > 5% of messages
- Google Sheets sync failures > 10 minutes
- Parsing confidence < 0.5 for > 20% of messages
- Webhook delivery failures

### 7.3 Logs

All logs written to:
- Console (stdout) - visible in Render dashboard
- `logs/biogas_bot.log` - file-based logging

**Log levels:**
```
DEBUG   - Detailed parsing steps, regex matches
INFO    - Processing status, dedup results, sync status
WARNING - Partial parses, missing fields, retry attempts
ERROR   - Processing failures, API errors, DB errors
```

---

## 8. Extensibility Points

### 8.1 Easy Extensions

1. **Add new parsing patterns**
   - Modify `services/parser.py`
   - Add new regex patterns
   - No schema changes required

2. **Add new output destinations**
   - Implement new sync service in `services/`
   - Call from `storage.py` after parsing

3. **Add message filtering**
   - Filter by sender, content, confidence
   - Modify ingestion layer

### 8.2 Medium Extensions

1. **Multi-sheet routing**
   - Route different message types to different sheets
   - Add routing rules configuration

2. **AI-powered parsing**
   - Replace regex with ML model
   - Keep same ParsedResult interface

3. **Dashboard UI**
   - Django admin customization
   - Real-time statistics views

### 8.3 Hard Extensions

1. **WhatsApp Business API**
   - Replace Telegram ingestion layer
   - Direct API integration
   - Real-time message streaming

2. **Multi-tenant support**
   - Separate data per organization
   - User authentication & authorization
   - Role-based access control

---

**Document Version:** 1.0.0  
**Last Updated:** April 15, 2026  
**Author:** AI Systems Architect
