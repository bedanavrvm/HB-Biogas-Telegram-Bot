# Biogas Telegram Bot - Message to Structured Data Pipeline

A production-quality MVP system that extracts structured data from WhatsApp group messages (via manual batch forwarding), processes them, deduplicates, and automatically writes clean structured rows into a shared Google Sheet.

## 📐 Architecture

```
WhatsApp Group → Manual batch forward (every ~2hrs)
    → Telegram Bot (ingestion layer)
        → Django Backend (processing layer)
            → Deduplication + Parsing Engine
                → Google Sheets (shared with staff)
```

### Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    EXTERNAL SYSTEMS                         │
├──────────────────────┬──────────────────────────────────────┤
│  WhatsApp Group      │  Google Sheets (Staff Editable)      │
│  (Manual Forward)    │  - Shared with staff                 │
│  → Telegram Bot      │  - Append-only from our system       │
└──────────┬───────────┴──────────────┬───────────────────────┘
           │                          ▲
           │ Telegram Webhook         │ Append Rows
           ▼                          │
┌─────────────────────────────────────────────────────────────┐
│                    DJANGO BACKEND                           │
├─────────────────────────────────────────────────────────────┤
│  INGESTION → DEDUPLICATION → PARSING → STORAGE → SHEETS    │
└─────────────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- A Telegram Bot (create via @BotFather)
- Google Service Account credentials (for Google Sheets API)
- Google Sheet with predefined schema

### Local Development

1. **Clone and setup:**
```bash
cd biogas_bot
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Configure environment:**
```bash
cp .env.example .env
# Edit .env with your configuration
```

3. **Setup Google Sheets:**
   - Create a Google Service Account
   - Download credentials as `credentials.json`
   - Share your Google Sheet with the service account email
   - Add `GOOGLE_SHEET_ID` to `.env`

4. **Run migrations:**
```bash
python manage.py makemigrations
python manage.py migrate
```

5. **Create admin user:**
```bash
python manage.py createsuperuser
```

6. **Run development server:**
```bash
python manage.py runserver
```

7. **Test the system:**
```bash
python manage.py test
```

## 🔧 Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DJANGO_SECRET_KEY` | ✅ | Django secret key for cryptographic signing |
| `DEBUG` | ✅ | Set to `False` in production |
| `ALLOWED_HOSTS` | ✅ | Comma-separated list of allowed hosts |
| `DATABASE_URL` | ✅ | Database connection string (SQLite or PostgreSQL) |
| `TELEGRAM_BOT_TOKEN` | ✅ | Telegram bot token from @BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | ⚠️ | Optional webhook secret for validation |
| `GOOGLE_SHEET_ID` | ✅ | ID of your Google Sheet |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | ✅ | Path to service account credentials JSON |
| `GOOGLE_SHEET_TAB_NAME` | ✅ | Name of the worksheet/tab to write into |
| `DEDUPLICATION_WINDOW_MINUTES` | ❌ | Time window for deduplication (default: 5) |

### Google Sheet Schema (Production - 21 Columns)

Your Google Sheet MUST have this exact header row (Row 1) in the worksheet specified by `GOOGLE_SHEET_TAB_NAME`:

**Column Structure (Left → Right):**

```
[0]  Complaint ID (formula/sequence)
[1]  message_id (bot dedup key)
[2]  Date Reported (bot)
[3]  Customer Name (bot)
[4]  Customer ID / Account (bot)
[5]  Phone Number (bot)
[6]  Reported By (bot)
[7]  Branch / Region (bot)
[8]  Complaint Category (bot - must match dropdown)
[9]  Complaint Description (bot)
[10] raw_message (bot - audit trail)
[11] gps_link (bot - if present)
[12] image_flag (bot - "TRUE" or blank)
[13] source (bot - "whatsapp_batch" etc.)
[14] Loan Status (human - dropdown)
[15] Loan at Risk (human - dropdown)
[16] Risk Level (human - dropdown)
[17] Status (human - dropdown: Open/In Progress/Closed)
[18] Resolution Details (human)
[19] Date Resolved (human)
[20] Days Open (formula: =TODAY()-[Date Reported])
```

**Full Header Row (Copy-paste ready):**

```
Complaint ID,message_id,Date Reported,Customer Name,Customer ID / Account,Phone Number,Reported By,Branch / Region,Complaint Category,Complaint Description,raw_message,gps_link,image_flag,source,Loan Status,Loan at Risk,Risk Level,Status,Resolution Details,Date Resolved,Days Open
```

**Critical Rules:**

- ✅ **DO WRITE**: Columns [1-13] (message_id, bot intake, audit trail)
- ❌ **DO NOT WRITE**: Columns [0, 20] (formulas - will break if written to)
- ❌ **DO NOT WRITE**: Columns [14-19] (human workflow - let staff fill in)
- ✅ **MUST MATCH**: Complaint Category value must exactly match dropdown validation
- ✅ **APPEND ONLY**: Never modify existing rows, only add new rows at bottom
- ✅ **DEDUPLICATION**: message_id ensures duplicate messages produce single row

**Hidden Columns (Recommended):**

To keep the sheet clean for staff while preserving system integrity:
- Hide columns [1, 10, 11, 12, 13] (`message_id`, `raw_message`, `gps_link`, `image_flag`, `source`)
- These are bot-internal fields, not needed for staff workflow

**Example: How bot-generated row looks:**

```
MSG_20260425_001,MSG_20260425_001,2026-04-25,Alice Kipchoge,ACC_98765,0712345678,Field Agent,Nairobi,System Underperformance,No gas supply,CUSTOMER COMPLAINT: Alice...,https://maps.google.com/xyz,TRUE,whatsapp_batch,,,,,,,
```

Staff then fills in:
- Loan Status: "Active" (or leave blank if unknown)
- Status: "Open" → later "In Progress" → finally "Closed"
- Risk Level: "High", "Medium", or "Low"
- Resolution Details: "Contacted regional office..." etc.

For more details on the schema rationale, see [PRODUCTION_ARCHITECTURE.md](./PRODUCTION_ARCHITECTURE.md).

## 📡 API Endpoints

### Health Check
```
GET /api/health/
```

Returns system status and version.

### Telegram Webhook
```
POST /api/webhook/telegram/
```

Receives updates from Telegram Bot API. Configure this URL as your Telegram webhook.

In Telegram groups, the bot only processes a message when the configured bot username is tagged and there is actual message content after the tag. This prevents ordinary group chatter from being parsed and synced accidentally.

Example group messages:

```text
@hb_biogas_cases_bot CUSTOMER COMPLAIN
NAME: Jane Doe
TEL: 0712345678
ID: ACC123
NATURE OF THE PROBLEM: No gas supply
```

```text
@hb_biogas_cases_bot /last 5
```

The webhook can process multiple complaint cases from one tagged message when each case starts with its own `CUSTOMER COMPLAIN` heading.

For the complete read-only command reference, see [BOT_COMMANDS.md](./BOT_COMMANDS.md).

**Setup webhook:**
```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -d "url=https://your-app.onrender.com/api/webhook/telegram/"
```

### Manual Batch Processing
```
POST /api/process/messages/
Content-Type: application/json

{
  "messages": [
    {
      "telegram_message_id": "123",
      "content": "Sold 3 bread 50 each to John",
      "sender": "John Doe",
      "received_at": "2026-04-15T10:30:00Z",
      "has_image": false
    }
  ]
}
```

### Resync Unsynced Messages
```
POST /api/resync/unsynced/
Content-Type: application/json

{
  "limit": 100
}
```

## 🧪 Testing

Run the full test suite:

```bash
python manage.py test
```

Run with coverage:

```bash
coverage run manage.py test
coverage report -m
```

## 🚀 Deploy to Render

### Option 1: One-Click Deploy

1. Push code to GitHub
2. Connect to Render
3. Import `render.yaml` for automatic setup

### Option 2: Manual Deploy

1. **Create Web Service on Render:**
   - Build Command: `pip install -r requirements.txt && python manage.py collectstatic --noinput`
   - Start Command: `gunicorn config.wsgi:application --log-file -`

2. **Add Environment Variables:**
   - Copy all values from `.env.example`
   - Set them in Render dashboard

3. **Add Credentials File:**
   - Upload `credentials.json` as a Render Secret File
   - Mount to `/etc/secrets/credentials.json`

4. **Run Migrations:**
   Add to build command:
   ```bash
   python manage.py migrate --noinput
   ```

5. **Set Webhook:**
   ```bash
   curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
     -d "url=https://your-app-name.onrender.com/api/webhook/telegram/"
   ```

## 📊 System Behavior

### Deduplication Strategy

Each message generates a unique hash based on:
- Sender name (normalized, case-insensitive)
- Message content (normalized, whitespace-collapsed)
- Timestamp window (rounded to nearest N minutes)

**Example:**
- Message 1: "Sold 3 bread 50 each" at 10:30 → Hash A
- Message 2: "Sold 3 bread 50 each" at 10:32 → Hash A (duplicate!)
- Message 3: "Sold 3 bread 50 each" at 10:40 → Hash B (new, different window)

### Parsing Engine

Supports multiple WhatsApp message formats:

| Pattern | Example | Extracted Fields |
|---------|---------|------------------|
| Sold | "Sold 3 bread 50 each to John" | qty=3, item=bread, price=50 |
| Paid | "John paid 200 for 4 milk" | price=200, qty=4, item=milk |
| Bought | "Mary bought 2 bags maize @ 100" | qty=2, item=maize, price=100 |
| GPS | "📍 https://maps... Sold 2 bags" | gps_link=URL, qty=2, item=bags |

**Confidence Score:**
- 1.0 = All fields extracted (sender, item, quantity, price)
- 0.75 = 3/4 fields extracted
- 0.5 = 2/4 fields extracted
- 0.25 = 1/4 fields extracted
- 0.0 = No fields extracted

### Batch Processing

When multiple messages are forwarded at once, the system:
1. Detects batch format (timestamps + sender names)
2. Splits into individual messages
3. Processes each independently
4. Returns batch processing results

## 🔐 Data Integrity Rules

1. **NEVER overwrite Google Sheet rows** - Append only
2. **ALWAYS store raw_message** - Full traceability
3. **message_id guarantees idempotency** - Safe retries
4. **Atomic transactions** - All-or-nothing processing
5. **Comprehensive logging** - All pipeline steps logged

## � Data Validation & Safety

The system implements critical safety features to prevent data corruption:

### Sheet Structure Detection
- **Purpose**: Validate Google Sheet has correct schema before appending
- **Check**: Exactly 21 columns with correct names in correct order
- **Behavior**: ABORTS append if structure doesn't match
- **Benefit**: Prevents silent data corruption if sheet is accidentally modified

### Dropdown Validation  
- **Purpose**: Validate complaint category value before writing
- **Check**: Category value matches Google Sheet dropdown rules
- **Behavior**: WARNS if validation fails but allows append (Google Sheets is final check)
- **Benefit**: Prevents invalid values that would violate sheet validation

### Implementation Details
- Uses Google Sheets API v4 to extract dropdown validation rules from sheet metadata
- Reads data validation constraints for column [8] (Complaint Category)
- Graceful degradation if API unavailable (validation disabled, not enforced)

**See [GOOGLE_SHEETS_VALIDATION.md](GOOGLE_SHEETS_VALIDATION.md) for complete documentation.**

## �📁 Project Structure

```
biogas_bot/
├── config/                  # Django configuration
│   ├── __init__.py
│   ├── settings.py         # Main settings
│   ├── urls.py             # Root URL routing
│   └── wsgi.py             # WSGI application
├── core/                   # Main application
│   ├── api/                # API layer
│   │   ├── __init__.py
│   │   ├── urls.py         # API routes
│   │   └── views.py        # Webhook handlers
│   ├── services/           # Business logic
│   │   ├── __init__.py
│   │   ├── deduplication.py # Hash-based dedup
│   │   ├── parser.py       # Regex message parser
│   │   ├── sheets.py       # Google Sheets integration
│   │   └── storage.py      # Database operations
│   ├── templates/          # HTML templates (if needed)
│   ├── static/             # Static files
│   ├── __init__.py
│   ├── admin.py            # Django admin config
│   ├── apps.py             # App configuration
│   ├── models.py           # Database models
│   └── tests.py            # Test suite
├── logs/                   # Application logs (gitignored)
├── credentials.json        # Google credentials (gitignored)
├── .env.example            # Environment template
├── .gitignore
├── Procfile                # Render/Heroku process file
├── render.yaml             # Render deployment config
├── requirements.txt        # Python dependencies
├── runtime.txt             # Python version
└── manage.py               # Django management script
```

## 🔄 Data Flow

```
1. User forwards WhatsApp messages to Telegram bot
2. Telegram sends webhook to Django /api/webhook/telegram/
3. Ingestion layer splits batch into individual messages
4. Deduplication layer filters out already-processed messages
5. Parsing engine extracts structured fields
6. Storage layer persists raw + parsed data
7. Google Sheets service appends clean rows
8. Staff can view/edit sheet safely
```

## ⚠️ Failure Modes & Mitigation

| Failure Mode | Mitigation |
|-------------|------------|
| Duplicate webhook delivery | Idempotent processing via message_id hash |
| Malformed message | Best-effort parsing, store raw, log warning |
| Google Sheets API down | Queue for retry, log error, don't block processing |
| Missing fields | Nullable fields, log partial parse |
| Concurrent sheet edits | Append-only, never modify existing rows |
| Telegram API rate limit | Batch processing, exponential backoff |

## 🔍 Logging

All pipeline steps are logged to:
- Console (stdout)
- `logs/biogas_bot.log` file

**Log levels:**
- `DEBUG` - Detailed parsing steps
- `INFO` - Processing status, deduplication results
- `WARNING` - Partial parses, missing fields
- `ERROR` - Processing failures, API errors

## 🧩 Extensibility

### Future Enhancements

1. **WhatsApp Business API Integration**
   - Replace manual forwarding with direct API connection
   - Real-time message ingestion

2. **AI-Powered Parsing**
   - Replace regex with ML model for better accuracy
   - Handle more complex message formats

3. **Dashboard & Analytics**
   - Real-time message statistics
   - Parsing confidence monitoring
   - Error rate tracking

4. **Multi-Sheet Support**
   - Route different message types to different sheets
   - Automatic sheet creation

5. **Alerting**
   - Slack/Discord notifications for processing failures
   - Daily summary reports

## 📝 License

Internal use only - Biogas Operations Team

## 👥 Support

For issues or questions:
1. Check logs in `logs/biogas_bot.log`
2. Review API responses for error details
3. Contact development team

---

**Built with:** Django 5.0, Python 3.11, Google Sheets API, Telegram Bot API  
**Deployed on:** Render (free tier)  
**Database:** SQLite (MVP) → PostgreSQL (production)
