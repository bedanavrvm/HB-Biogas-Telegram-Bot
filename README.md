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

### Google Sheet Schema

Your Google Sheet MUST have this exact header row (Row 1), using the `Complaints Register` worksheet:

```
Complaint ID | Date Reported | Customer Name | Customer ID / Account | Phone Number | JBL Reported By | Branch / Region | Complaint Category | Complaint Description | LOAN STATUS | LOAN AT RISK | Status | Resolution Details | Date Resolved | Days Open | RISK LEVEL | Internal Message ID | Parsed Timestamp
```

**Rules:**
- NEVER modify the schema dynamically
- ONLY append rows
- `Complaint ID` is used for deduplication
- Staff can safely edit any cell except `Complaint ID`, `Internal Message ID`, and `Parsed Timestamp`

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

## 📁 Project Structure

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
