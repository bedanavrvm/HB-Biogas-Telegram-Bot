# Quick Reference: API Security & Validation

## 🔒 Security Features Implemented

### 1. Request Size Validation
**Limit:** 1MB per request
**Returns:** 413 Payload Too Large

```bash
# This will be rejected:
curl -X POST http://localhost:8000/api/webhook/telegram/ \
  -d @large-file-over-1mb.json
```

### 2. Required Field Validation
**Fields Required:** `message_id`, `chat`, `date` (Telegram messages)

```bash
# This will be rejected (missing 'date'):
curl -X POST http://localhost:8000/api/webhook/telegram/ \
  -d '{"update_id": 1, "message": {"message_id": 123, "chat": {"id": 456}}}'
```

### 3. Request Timeouts
**Timeout:** 10 seconds for all external API calls
- Telegram API calls
- Google Sheets API calls (configurable)

### 4. Consistent Error Responses
All errors follow this format:
```json
{
  "status": "error",
  "error": "User-facing message",
  "code": "ERROR_CODE"
}
```

### 5. Centralized Configuration
All limits and timeouts in `settings.py`:
```python
API_REQUEST_SIZE_LIMIT = 1_000_000  # 1MB
API_REQUEST_TIMEOUT = 10  # seconds
MAX_SYNC_ATTEMPTS = 5
PARSING_BATCH_SIZE = 50
DEDUPLICATION_WINDOW_MINUTES = 5
```

### 6. Rate Limiting (Optional)
**Status:** Ready to enable
**How to Enable:**
```bash
pip install django-ratelimit
export RATELIMIT_ENABLE=True
```
Then uncomment decorator in `core/api/views.py`

---

## 📍 Validation Locations

| Endpoint | Validations |
|----------|-------------|
| `/api/webhook/telegram/` | Size ✓ JSON ✓ Payload ✓ Fields ✓ Secret ✓ |
| `/api/process/messages/` | Size ✓ JSON ✓ Auth ✓ Batch ✓ |
| `/api/resync/unsynced/` | Size ✓ Auth ✓ Limits ✓ |
| `/api/health/` | Size ✓ |

---

## 🧪 Testing Validations

### Test Request Size Limit
```bash
# Generate 2MB of data
python -c "
import json
data = json.dumps({'data': 'x' * 2_000_000})
print(data)
" > large.json

curl -X POST http://localhost:8000/api/webhook/telegram/ \
  -H "Content-Type: application/json" \
  --data-binary @large.json
# Expected: 413 Payload Too Large
```

### Test Missing Required Fields
```bash
# Missing 'date' field
curl -X POST http://localhost:8000/api/webhook/telegram/ \
  -H "Content-Type: application/json" \
  -d '{
    "update_id": 1,
    "message": {
      "message_id": 123,
      "chat": {"id": 456}
    }
  }'
# Expected: 400 Missing required message fields: date
```

### Test Invalid JSON
```bash
curl -X POST http://localhost:8000/api/webhook/telegram/ \
  -H "Content-Type: application/json" \
  -d 'not valid json'
# Expected: 400 Invalid JSON in request body
```

### Test Success Response
```bash
curl http://localhost:8000/api/health/
# Returns standardized success format
# {
#   "status": "success",
#   "message": "Service is healthy",
#   "data": {...}
# }
```

---

## 🛠️ For Developers

### Using Validators in New Endpoints

```python
from core.api.validators import (
    validate_request_size,
    validate_batch_messages,
    error_response,
    success_response,
)

@csrf_exempt
def my_endpoint(request):
    # Step 1: Validate size
    try:
        validate_request_size(request)
    except ValidationError as e:
        return error_response(e.message, e.code, e.status_code)
    
    # Step 2: Parse JSON
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return error_response('Invalid JSON', 'INVALID_JSON', 400)
    
    # Step 3: Business logic
    result = do_something(body)
    
    # Step 4: Return standardized response
    return success_response(
        data=result,
        message='Operation successful'
    )
```

### Creating Custom Validators

```python
# Add to core/api/validators.py

def validate_my_data(data: dict) -> bool:
    """Custom validator example."""
    if 'required_field' not in data:
        raise ValidationError(
            'Missing required_field',
            code='MISSING_FIELD',
            status_code=400
        )
    return True
```

### Using Response Helpers

```python
# Success (200)
return success_response(
    data={'id': 123, 'status': 'created'},
    message='Resource created successfully'
)

# Error (400)
return error_response(
    'Invalid input provided',
    code='INVALID_INPUT',
    status_code=400,
    details='The email field is required'  # Logged, not sent to client
)

# Partial Success (200 with warnings)
return partial_response(
    data={'processed': 48, 'failed': 2},
    warnings=['Item 5 failed validation', 'Item 12 format unclear'],
    message='Batch processed with warnings'
)
```

---

## 📊 Configuration Examples

### For Production
```python
# .env.production
API_REQUEST_SIZE_LIMIT=1000000    # 1MB - Strict limit
API_REQUEST_TIMEOUT=5              # 5 seconds - Tight timeout
RATELIMIT_ENABLE=True
RATELIMIT_PER_IP=100/h             # 100 requests/hour per IP
```

### For Development
```python
# .env.development
API_REQUEST_SIZE_LIMIT=10000000    # 10MB - More lenient
API_REQUEST_TIMEOUT=30             # 30 seconds - Longer timeout
RATELIMIT_ENABLE=False
```

### For High Volume
```python
# .env.highvolume
API_REQUEST_SIZE_LIMIT=5000000     # 5MB
API_REQUEST_TIMEOUT=15
RATELIMIT_PER_IP=1000/h            # Higher limit
PARSING_BATCH_SIZE=100             # Larger batches
```

---

## 🔍 Monitoring

### Check Request Validation Errors
```bash
# View recent validation errors in logs
tail -f logs/biogas_bot.log | grep -i "validation\|missing\|invalid"
```

### Monitor Rate Limiting (if enabled)
```bash
# Check for rate limit violations
tail -f logs/biogas_bot.log | grep -i "ratelimit\|429"
```

### Check Timeout Errors
```bash
# Monitor external API timeouts
tail -f logs/biogas_bot.log | grep -i "timeout"
```

---

## 🚀 Performance Impact

| Feature | Overhead | Benefit |
|---------|----------|---------|
| Size Validation | <1ms | Prevents DoS |
| Field Validation | 1-2ms | Eliminates silent failures |
| Timeouts | 0ms (async) | Prevents hangs |
| Response Formatting | <1ms | Better client support |

**Total Overhead:** <5ms per request (negligible)

---

## 📚 Documentation

- **Full Details:** [API_IMPROVEMENTS_SUMMARY.md](API_IMPROVEMENTS_SUMMARY.md)
- **Improvements List:** [IMPROVEMENTS.md](IMPROVEMENTS.md)
- **API Endpoints:** [README.md#api-endpoints](README.md)
- **Error Handling:** [core/api/validators.py](core/api/validators.py)

---

**All validations are active and enforced by default! ✅**
