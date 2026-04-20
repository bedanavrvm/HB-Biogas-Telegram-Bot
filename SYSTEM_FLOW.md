# Complete System Flow - Visual Diagram

## 1. End-to-End Message Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│  WHATSAPP GROUP                                                     │
│                                                                     │
│  User sends: "Sold 3 bread 50 each to John"                         │
│  Or batch: "[15/04 10:30] John: Sold 3 bread                        │
│           [15/04 10:31] Mary: Paid 200 for 4 milk"                  │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           │ Staff forwards to Telegram group (every ~2hrs)
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  TELEGRAM BOT (@biogas_data_bot)                                    │
│                                                                     │
│  Receives message(s) in group                                       │
│  Extracts: sender, content, timestamp, image flag                   │
│  Sends webhook POST to Django backend                               │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           │ HTTPS POST
                           │ URL: https://your-app.onrender.com/api/webhook/telegram/
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│  DJANGO BACKEND (Render Cloud)                                      │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  1. INGESTION LAYER (api/views.py)                            │ │
│  │                                                               │ │
│  │  • Receive webhook payload                                    │ │
│  │  • Validate request                                           │ │
│  │  • Extract: telegram_message_id, sender, content, timestamp  │ │
│  │  • Detect batch format                                        │ │
│  │  • Split into individual messages (if batch)                  │ │
│  └───────────────────────────┬───────────────────────────────────┘ │
│                              │                                      │
│                              │ For each message:                    │
│                              ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  2. DEDUPLICATION SERVICE (services/deduplication.py)         │ │
│  │                                                               │ │
│  │  • Generate hash: SHA256(sender + content + time_window)     │ │
│  │  • Check ProcessedMessage table for existing hash             │ │
│  │  • If duplicate → SKIP (log & return)                         │ │
│  │  • If new → CONTINUE                                          │ │
│  └───────────────────────────┬───────────────────────────────────┘ │
│                              │                                      │
│                              │ New message only                     │
│                              ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  3. PARSING ENGINE (services/parser.py)                       │ │
│  │                                                               │ │
│  │  • Extract GPS URL (if present)                               │ │
│  │  • Extract timestamp (if present)                             │ │
│  │  • Extract sender name                                        │ │
│  │  • Match transaction patterns:                                │ │
│  │    - "Sold X item Y each"                                     │ │
│  │    - "X paid Y for Z item"                                    │ │
│  │    - "X bought Z item @ Y"                                    │ │
│  │  • Calculate confidence score (0.0 - 1.0)                     │ │
│  │  • Return ParsedResult object                                 │ │
│  └───────────────────────────┬───────────────────────────────────┘ │
│                              │                                      │
│                              │ ParsedResult                         │
│                              ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  4. STORAGE LAYER (services/storage.py)                       │ │
│  │     (Atomic Transaction)                                      │ │
│  │                                                               │ │
│  │  • Store RawMessage (immutable audit trail)                   │ │
│  │  • Create ProcessedMessage (dedup tracking)                   │ │
│  │  • Create ParsedMessage (structured data)                     │ │
│  │  • Generate unique message_id                                 │ │
│  │  • Commit transaction                                         │ │
│  └───────────────────────────┬───────────────────────────────────┘ │
│                              │                                      │
│                              │ ParsedMessage                        │
│                              ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  5. GOOGLE SHEETS SERVICE (services/sheets.py)                │ │
│  │                                                               │ │
│  │  • Authenticate with Google API (OAuth2)                      │ │
│  │  • Check if message_id exists in sheet (idempotency)          │ │
│  │  • If new → append_row()                                      │ │
│  │  • If exists → SKIP (already synced)                          │ │
│  │  • Update synced_to_sheets = True                             │ │
│  │  • Log success/failure                                        │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  DATABASE (PostgreSQL/SQLite)                                 │ │
│  │                                                               │ │
│  │  RawMessage (1) ←── ProcessedMessage (N) ←── ParsedMessage   │ │
│  │  - id                  - id                   - id            │ │
│  │  - telegram_message_id - message_hash         - message_id    │ │
│  │  - sender              - raw_message (FK)     - timestamp     │ │
│  │  - content             - status               - sender        │ │
│  │  - received_at         - processed_at         - item          │ │
│  │  - has_image                                  - quantity      │ │
│  │  - created_at                                 - price         │ │
│  │                                               - gps_link      │ │
│  │                                               - image_flag    │ │
│  │                                               - source        │ │
│  │                                               - synced_to_    │ │
│  │                                                 sheets        │ │
│  └───────────────────────────────────────────────────────────────┘ │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               │ Append-Only (NEVER overwrite)
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  GOOGLE SHEETS (Shared with Staff)                                  │
│                                                                     │
│  ┌────┬───────────┬────────┬─────────────┬──────┬──────┬─────┬────┐│
│  │ A  │ B         │ C      │ D           │ E    │ F    │ G   │... ││
│  ├────┼───────────┼────────┼─────────────┼──────┼──────┼─────┼────┤│
│  │mes │ timestamp │ sender │ raw_message │ item │ qty  │price│... ││
│  │sage│           │        │             │      │      │     │    ││
│  ├────┼───────────┼────────┼─────────────┼──────┼──────┼─────┼────┤│
│  │MSG │10:30      │ John   │Sold 3 bread│bread │ 3    │ 50  │... ││
│  │_001│           │        │50 each     │      │      │     │    ││
│  ├────┼───────────┼────────┼─────────────┼──────┼──────┼─────┼────┤│
│  │MSG │10:31      │ Mary   │Paid 200    │milk  │ 4    │ 200 │... ││
│  │_002│           │        │for 4 milk  │      │      │     │    ││
│  └────┴───────────┴────────┴─────────────┴──────┴──────┴─────┴────┘│
│                                                                     │
│  Staff can:                                                         │
│  ✓ View in real-time                                                │
│  ✓ Edit any cell (except message_id)                                │
│  ✓ Add notes, corrections                                           │
│  ✓ Sort, filter, analyze                                            │
│                                                                     │
│  System NEVER:                                                      │
│  ✗ Overwrites existing rows                                         │
│  ✗ Modifies schema                                                  │
│  ✗ Deletes data                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Deduplication Flow

```
Message arrives
       │
       ▼
┌─────────────────────────────────────────┐
│ Generate Hash                           │
│                                         │
│ hash_input = "john|sold 3 bread 50|10:30│
│ message_hash = SHA256(hash_input)[:64]  │
│                                         │
│ Result: "a1b2c3d4e5f6..."               │
└───────────────┬─────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────┐
│ Check Database                          │
│                                         │
│ SELECT * FROM processedmessage          │
│ WHERE message_hash = 'a1b2c3d4...'      │
│                                         │
└───────┬──────────────────┬──────────────┘
        │                  │
     EXISTS            NOT EXISTS
        │                  │
        ▼                  ▼
   ┌────────┐        ┌──────────┐
   │ SKIP   │        │ PROCESS  │
   │        │        │          │
   │ Log:   │        │ Continue │
   │"Dupli- │        │ to parse │
   │ cate"  │        │          │
   └────────┘        └──────────┘
```

---

## 3. Parsing Engine Flow

```
Raw message text
       │
       ▼
┌──────────────────────────────┐
│ Step 1: Extract GPS URL      │
│                              │
│ Search for: https?://[^\s]+ │
│                              │
│ Found? → Store, remove from  │
│          text for cleaner    │
│          parsing             │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│ Step 2: Extract Timestamp    │
│                              │
│ Search for: [DD/MM/YYYY     │
│              HH:MM:SS]       │
│                              │
│ Found? → Parse to datetime   │
│ Not found? → Use received_at │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│ Step 3: Extract Sender       │
│                              │
│ Try patterns:                │
│ - "X paid..."                │
│ - "X bought..."              │
│ - "Sold... to X"             │
│                              │
│ Not found? → Use metadata    │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│ Step 4: Extract Transaction  │
│                              │
│ Try patterns in order:       │
│ 1. "Sold X item Y each"      │
│ 2. "Paid X for Y item"       │
│ 3. "Bought X item @ Y"       │
│                              │
│ Fallback: Extract individual │
│ fields separately            │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│ Step 5: Calculate Confidence │
│                              │
│ sender?    +0.25             │
│ item?      +0.25             │
│ quantity?  +0.25             │
│ price?     +0.25             │
│                              │
│ Total: 0.0 - 1.0             │
└──────────┬───────────────────┘
           │
           ▼
   ParsedResult object
```

---

## 4. Google Sheets Sync Flow

```
ParsedMessage created in database
            │
            │ synced_to_sheets = False
            │
            ▼
┌──────────────────────────────────────────┐
│ Google Sheets Service                    │
│                                          │
│ 1. Check availability                    │
│    - API credentials loaded?             │
│    - Sheet accessible?                   │
│                                          │
│ If no → Log warning, retry later         │
└───────────────┬──────────────────────────┘
                │
                │ Available
                ▼
┌──────────────────────────────────────────┐
│ Idempotency Check                        │
│                                          │
│ Get column A (message_id column)         │
│ Check if message_id exists               │
│                                          │
│ EXISTS → Skip (already synced)           │
└───────────────┬──────────────────────────┘
                │
                │ Not exists
                ▼
┌──────────────────────────────────────────┐
│ Append Row                               │
│                                          │
│ Convert ParsedMessage to row:            │
│ [message_id, timestamp, sender,          │
│  raw_message, item, quantity, price,     │
│  gps_link, image_flag, source]           │
│                                          │
│ sheet.append_row(row)                    │
└───────────────┬──────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────┐
│ Update Sync Status                       │
│                                          │
│ parsed_message.synced_to_sheets = True   │
│ parsed_message.synced_at = now()         │
│ parsed_message.save()                    │
│                                          │
│ Log: "Message synced to Google Sheets"   │
└──────────────────────────────────────────┘
```

---

## 5. Error Recovery Flow

```
Error occurs during processing
            │
            ▼
┌──────────────────────────────────────────┐
│ Error Type Detection                     │
└───────────┬──────────────────────────────┘
            │
    ┌───────┼──────────┬──────────┐
    │       │          │          │
    ▼       ▼          ▼          ▼
  Parse   Database   Google    Unknown
  Error    Error     Sheets
                     Error
    │       │          │          │
    │       │          │          │
    ▼       ▼          ▼          ▼
┌──────┐ ┌──────┐  ┌──────┐  ┌──────┐
│Store │ │Roll- │  │Log   │  │Log   │
│with  │ │back  │  │error,│  │error,│
│confi-│ │trans-│  │mark  │  │mark  │
│dence │ │action│  │unsyn-│  │failed│
│0.0   │ │      │  │ced   │  │      │
└──┬───┘ └──┬───┘  └──┬───┘  └──┬───┘
   │        │         │         │
   │        │         │         │
   ▼        ▼         ▼         ▼
Message stored in DB, raw_message preserved

Manual resync available:
POST /api/resync/unsynced/
```

---

## 6. Batch Processing Flow

```
Batch message arrives (multiple messages forwarded at once)
            │
            ▼
┌──────────────────────────────────────────────┐
│ Detect Batch Format                          │
│                                              │
│ Look for patterns:                           │
│ [DD/MM/YYYY, HH:MM:SS] Sender: message       │
│                                              │
│ Found multiple? → YES                        │
└───────────────┬──────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────┐
│ Split Batch                                  │
│                                              │
│ Input:                                       │
│ "[10:30] John: Sold 3 bread                  │
│  [10:31] Mary: Paid 200 for 4 milk           │
│  [10:32] Peter: Bought 2 bags @ 100"         │
│                                              │
│ Output:                                      │
│ [                                            │
│   {sender: "John", content: "Sold 3 bread"},│
│   {sender: "Mary", content: "Paid 200..."}, │
│   {sender: "Peter", content: "Bought 2..."} │
│ ]                                            │
└───────────────┬──────────────────────────────┘
                │
                │ For each message in batch (parallel-safe)
                ▼
┌──────────────────────────────────────────────┐
│ Process Each Individually                    │
│                                              │
│ 1. Deduplication check                       │
│ 2. Parse message                             │
│ 3. Store in database                         │
│ 4. Sync to Google Sheets                     │
│                                              │
│ Each message independent                     │
└───────────────┬──────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────┐
│ Aggregate Results                            │
│                                              │
│ {                                            │
│   "status": "batch_processed",              │
│   "total": 3,                                │
│   "success": 2,                              │
│   "duplicates": 1,                           │
│   "results": [...]                           │
│ }                                            │
└──────────────────────────────────────────────┘
```

---

## 7. Complete System Architecture (Technical)

```
┌──────────────────────────────────────────────────────────────────┐
│                        CLIENT LAYER                              │
│                                                                  │
│  WhatsApp Users ──→ Telegram Group ←── Staff Members             │
│                                                                  │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                    PRESENTATION LAYER                            │
│                                                                  │
│  Telegram Bot API ───────────→ Django Admin Interface            │
│  (Webhook)                     (Staff view/edit)                 │
│                                                                  │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                     APPLICATION LAYER                            │
│                                                                  │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────────────┐    │
│  │ API Views  │  │ URL Routing  │  │ Middleware           │    │
│  │            │  │              │  │ - Security           │    │
│  │ - webhook  │  │ - /api/*     │  │ - Session            │    │
│  │ - process  │  │ - /admin/*   │  │ - CSRF               │    │
│  │ - resync   │  │ - /health    │  │ - Logging            │    │
│  └─────┬──────┘  └──────────────┘  └──────────────────────┘    │
│        │                                                         │
│        ▼                                                         │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   SERVICE LAYER                          │   │
│  │                                                          │   │
│  │  Deduplication  →  Parser  →  Storage  →  GoogleSheets  │   │
│  │  Service          Engine     Service      Service        │   │
│  │                                                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                      DATA LAYER                                  │
│                                                                  │
│  ┌──────────────────┐          ┌──────────────────────┐         │
│  │  PostgreSQL/     │          │  Google Sheets API   │         │
│  │  SQLite          │          │  (External)          │         │
│  │                  │          │                      │         │
│  │  RawMessage      │──────→   │  Append-only rows    │         │
│  │  ProcessedMsg    │          │  Staff editable      │         │
│  │  ParsedMessage   │          │                      │         │
│  └──────────────────┘          └──────────────────────┘         │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 8. Deployment Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    RENDER CLOUD PLATFORM                     │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Web Service: biogas-telegram-bot                      │ │
│  │                                                        │ │
│  │  Container:                                            │ │
│  │  ┌──────────────────────────────────────────────────┐ │ │
│  │  │  Gunicorn (WSGI Server)                          │ │ │
│  │  │    ↓                                             │ │ │
│  │  │  Django Application                              │ │ │
│  │  │    ├─ Ingestion Layer                            │ │ │
│  │  │    ├─ Deduplication Service                      │ │ │
│  │  │    ├─ Parsing Engine                             │ │ │
│  │  │    ├─ Storage Service                            │ │ │
│  │  │    └─ Google Sheets Integration                  │ │ │
│  │  └──────────────────────────────────────────────────┘ │ │
│  │                                                        │ │
│  │  Environment Variables:                                │ │
│  │  - DJANGO_SECRET_KEY                                   │ │
│  │  - TELEGRAM_BOT_TOKEN                                  │ │
│  │  - GOOGLE_SHEET_ID                                     │ │
│  │  - DATABASE_URL                                        │ │
│  │  - ...                                                 │ │
│  │                                                        │ │
│  │  Secret Files:                                         │ │
│  │  - /etc/secrets/credentials.json                       │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Managed Database (PostgreSQL - optional)              │ │
│  │                                                        │ │
│  │  - Automated backups                                   │ │
│  │  - Connection pooling                                  │ │
│  │  - Encrypted at rest                                   │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  Static Files (Whitenoise)                             │ │
│  │                                                        │ │
│  │  - Compressed                                          │ │
│  │  - Cached                                              │ │
│  │  - Served directly                                     │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│                    EXTERNAL SERVICES                         │
│                                                              │
│  Telegram Bot API ◄── Webhook ──► Render Web Service         │
│                                                              │
│  Google Sheets API ◄── OAuth2 ──► Render Web Service         │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

**All diagrams represent the complete Biogas Telegram Bot MVP system**  
**Version:** 1.0.0 | **Date:** April 15, 2026
