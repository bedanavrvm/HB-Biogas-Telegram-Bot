# Quick Start Guide - Biogas Telegram Bot

## 🎯 What This System Does

Converts messy WhatsApp messages into clean, structured Google Sheet rows automatically.

**Example:**
```
WhatsApp: "*CUSTOMER COMPLAIN* NAME: John Doe TEL: 0712345678 ID: A12345 NATURE OF THE PROBLEM: No gas supply at home"
     ↓
Google Sheet: Complaint ID | Date Reported | Customer Name | Customer ID / Account | Phone Number | JBL Reported By | Branch / Region | Complaint Category | Complaint Description | LOAN STATUS | LOAN AT RISK | Status | Resolution Details | Date Resolved | Days Open | RISK LEVEL | Internal Message ID | Parsed Timestamp
              MSG_12345  | 2026-04-15   | John Doe      | A12345               | 0712345678   | Agent            |             | System Underperformance | No gas supply at home |            |             | Open |     |             |    |    
```

---

## 📋 Setup Checklist (10 minutes)

### For Developers

- [ ] Clone repository
- [ ] Run `python setup.py` (installs dependencies)
- [ ] Copy `.env.example` to `.env`
- [ ] Edit `.env` with your settings
- [ ] Run `python manage.py migrate`
- [ ] Run `python manage.py test` (all should pass)
- [ ] Run `python manage.py runserver`

### For Team Leads

- [ ] Create Telegram bot via @BotFather
- [ ] Create Google Sheet with correct schema
- [ ] Setup Google Service Account
- [ ] Deploy to Render (see DEPLOYMENT.md)
- [ ] Set Telegram webhook URL
- [ ] Test with sample messages

---

## 🔧 Daily Operations

### For Staff Members

**1. Forward Messages (every ~2 hours):**
- Open WhatsApp group
- Select recent messages (batch select)
- Forward to Telegram group where bot is added

**2. Verify in Google Sheet:**
- Open shared Google Sheet
- Check that new rows appeared
- Verify data looks correct

**3. Manual Corrections (if needed):**
- Edit any cell in Google Sheet
- Add notes in empty columns
- **Never edit the `message_id` column**

### For Developers

**Check System Health:**
```bash
curl https://your-app.onrender.com/api/health/
```

**View Logs:**
- Render dashboard → Logs tab
- Or: `logs/biogas_bot.log` in development

**Resync Failed Messages:**
```bash
curl -X POST https://your-app.onrender.com/api/resync/unsynced/ \
  -H "Content-Type: application/json" \
  -d '{"limit": 100}'
```

---

## 📊 Google Sheet Setup

### Required Schema (Row 1 must be exactly this, in the `Complaints Register` worksheet):

| A | B | C | D | E | F | G | H | I | J | K | L | M | N | O | P | Q | R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Complaint ID | Date Reported | Customer Name | Customer ID / Account | Phone Number | JBL Reported By | Branch / Region | Complaint Category | Complaint Description | LOAN STATUS | LOAN AT RISK | Status | Resolution Details | Date Resolved | Days Open | RISK LEVEL | Internal Message ID | Parsed Timestamp |

### Sharing Settings:
- **Share with service account email** → Editor permission
- **Share with staff** → Editor permission
- **Protect column A** (Complaint ID) from staff edits (optional)

---

## 🧪 Testing

### Test Single Message
```
Send to Telegram group:
"Sold 3 bread 50 each to John"

Expected in Google Sheet:
- message_id: MSG_XXXXX
- sender: John
- item: bread
- quantity: 3
- price: 50
```

### Test Batch Messages
```
Send to Telegram group (all at once):
[15/04/2026, 10:30:15] John: Sold 3 bread 50 each
[15/04/2026, 10:31:20] Mary: Paid 200 for 4 milk

Expected in Google Sheet:
- Row 1: John, bread, 3, 50
- Row 2: Mary, milk, 4, 200
```

### Test GPS Link
```
Send to Telegram group:
"📍 https://maps.app.goo.gl/abc123 Sold 2 bags maize"

Expected in Google Sheet:
- gps_link: https://maps.app.goo.gl/abc123
- item: bags maize
- quantity: 2
```

### Test Image Flag
```
Send to Telegram group:
[Image with caption] "Sold 5 eggs"

Expected in Google Sheet:
- image_flag: TRUE
- item: eggs
- quantity: 5
```

---

## 🚨 Troubleshooting

### Messages Not Appearing in Sheet

**Check:**
1. Bot is in Telegram group ✓
2. Render app is running ✓
3. Google Sheet is shared with service account ✓
4. `GOOGLE_SHEET_ID` is correct in .env ✓

**Fix:**
- Check Render logs for errors
- Try resync endpoint
- Test health check endpoint

### Duplicate Messages in Sheet

**This should not happen!** System has deduplication.

**Possible causes:**
- Manual entry by staff
- Different time window (5+ minutes apart)

**Fix:**
- Check logs for "Duplicate message detected"
- Verify deduplication window setting

### Parsing Confidence Low

**Check:**
- Message format unknown to parser
- New message pattern not supported

**Fix:**
- Check `ParsedMessage.confidence` in database
- Add new regex patterns to `parser.py`
- Manual entry in sheet as fallback

---

## 📞 Support

### Documentation
- `README.md` - Full system documentation
- `DEPLOYMENT.md` - Step-by-step deploy guide
- `ARCHITECTURE.md` - Technical architecture
- This file - Quick reference

### Common Commands

```bash
# Run tests
python manage.py test

# Create admin user
python manage.py createsuperuser

# View admin dashboard
http://localhost:8000/admin/

# Check database
python manage.py dbshell

# Collect static files
python manage.py collectstatic

# Run with fresh logs
python manage.py runserver 0.0.0.0:8000
```

---

## 🎓 Key Concepts

### Deduplication
- Same sender + content + time window = duplicate
- Prevents double-processing of forwarded messages
- Uses SHA256 hash for comparison

### Parsing Confidence
- 1.0 = All fields extracted perfectly
- 0.75 = Most fields extracted
- 0.5 = Some fields extracted
- 0.25 = Minimal extraction
- 0.0 = Nothing extracted

### message_id
- Unique identifier for each message
- Format: `MSG_` + first 16 chars of hash
- Used for Google Sheets deduplication
- **Never edit this column**

### Append-Only
- System NEVER overwrites sheet rows
- Only appends new rows
- Staff can safely edit any other cell
- Full traceability maintained

---

## 📈 Success Metrics

### Week 1
- [ ] System deployed and running
- [ ] All team members forwarding messages
- [ ] Google Sheet updating automatically
- [ ] Zero duplicate rows

### Month 1
- [ ] > 90% parsing confidence (avg)
- [ ] < 5% sync failures
- [ ] Staff comfortable with workflow
- [ ] Manual corrections < 10% of rows

### Ongoing
- [ ] System stable, no downtime
- [ ] Message processing < 1 second
- [ ] Team saving hours vs manual entry
- [ ] Data quality improving over time

---

**Last Updated:** April 15, 2026  
**Version:** 1.0.0  
**Team:** Biogas Operations
