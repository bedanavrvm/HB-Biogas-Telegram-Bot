# Google Sheets Validation Implementation

## Overview

This document describes the Sheet Structure Detection and Dropdown Validation safety features implemented in the biogas_bot system. These features prevent data corruption by validating the Google Sheet schema before appending new complaint rows.

## Features Implemented

### 1. Sheet Structure Detection (`validate_sheet_structure()`)

**Purpose**: Validate that the Google Sheet has exactly the correct schema before appending any data.

**Implementation Details**:
- Fetches the header row from the Google Sheet using gspread
- Validates that the sheet has exactly 21 columns (required schema length)
- Validates that each column name matches the expected schema exactly
- Performs case-sensitive comparison with whitespace trimming
- Returns detailed error messages if validation fails

**Code Location**: [core/services/sheets.py](core/services/sheets.py#L200-L245)

**Return Value**:
```python
(is_valid: bool, error_message: str)
# Success: (True, '')
# Failure: (False, 'Column name mismatch(es): [8] 'Wrong Category' != 'Complaint Category'...')
```

**Usage**:
```python
is_valid, error_msg = sheets_service.validate_sheet_structure()
if not is_valid:
    logger.error(f"Sheet validation failed: {error_msg}")
    return False  # Abort append operation
```

### 2. Dropdown Validation (`validate_complaint_category()`)

**Purpose**: Pre-validate complaint category values against Google Sheet dropdown rules before attempting to write.

**Implementation Details**:
- Calls `get_valid_complaint_categories()` to retrieve the list of valid values
- Compares the provided category value against the valid list
- Allows empty/whitespace values (staff may fill in later)
- Returns warning if validation fails but allows append to proceed (defensive approach)

**Code Location**: [core/services/sheets.py](core/services/sheets.py#L350-L375)

**Return Value**:
```python
(is_valid: bool, message: str)
# Success: (True, '')
# Warning: (False, "Category 'Invalid' not in valid list: ['Billing', 'Service Quality', ...]")
```

### 3. Google Sheets API v4 Integration (`get_valid_complaint_categories()`)

**Purpose**: Extract dropdown validation rules from the Google Sheet using the Google Sheets API v4 metadata.

**Implementation Details**:
- Initializes Google Sheets API v4 client during service initialization
- Fetches sheet metadata using `sheets_api_service.spreadsheets().get()`
- Reads data validation rules for column [8] (Complaint Category)
- Extracts LIST constraint values from `dataValidation.condition.values`
- Returns empty list if API v4 is unavailable (graceful degradation)

**Code Location**: [core/services/sheets.py](core/services/sheets.py#L255-L320)

**Return Value**:
```python
valid_categories: list[str]
# Example: ['Billing', 'Service Quality', 'Technical Issue', 'Refund Request']
# If unavailable: []
```

**Initialization**:
The API v4 service is initialized in the `_initialize()` method:
```python
if _google_sheets_api_available:
    try:
        self._sheets_api_service = build('sheets', 'v4', credentials=creds)
        self._api_initialized = True
    except Exception as e:
        logger.warning(f"Failed to initialize Google Sheets API v4: {e}")
```

### 4. Enhanced `append_row()` Method

**Purpose**: Integrate validation checks into the append workflow to prevent data corruption.

**Safety Checks** (in order):
1. **Structure Validation**: Validates sheet has correct 21-column schema
   - Aborts with ABORT log if structure doesn't match
   - Prevents appending to wrong sheet structure
   
2. **Idempotency Check**: Checks if message_id already exists
   - Prevents duplicate messages
   - Returns success if already processed
   
3. **Row Length Validation**: Validates row has exactly 21 columns
   - Prevents malformed data
   
4. **Category Validation**: Validates complaint category value
   - Warns if category not in dropdown list
   - Allows append to proceed (Google Sheets validation is final check)

**Code Location**: [core/services/sheets.py](core/services/sheets.py#L376-L440)

**Signature**:
```python
def append_row(self, row: list, message_id: str = None, skip_validation: bool = False) -> bool:
```

**Parameters**:
- `row`: List of 21 values matching schema
- `message_id`: Optional message ID for deduplication and logging
- `skip_validation`: If True, skip structure validation (use with extreme caution)

**Usage Example**:
```python
success = sheets_service.append_row(
    row=parsed_message.to_sheet_row(),
    message_id=parsed_message.message_id
)
if not success:
    logger.error("Failed to append row to Google Sheet")
    # Handle error - don't proceed with storage
```

## Error Handling

### Structure Validation Failures

When `validate_sheet_structure()` detects a mismatch:
- Logs ERROR with: "ABORT: Sheet structure validation failed"
- Detailed error includes: column number, actual value, expected value
- Append operation is **aborted** (return False)
- No data is written to Google Sheets

**Example Error Message**:
```
Column name mismatch(es): [8] 'Wrong Category' != 'Complaint Category'. 
Sheet schema may have been modified manually.
```

### Category Validation Failures

When `validate_complaint_category()` detects an invalid value:
- Logs WARNING with: "Category validation warning"
- Detailed message includes: provided value, list of valid values
- Append operation **proceeds** (defensive approach)
- Google Sheets validation will be final check

**Example Warning Message**:
```
Complaint category 'Invalid Category' not in valid list: 
['Billing', 'Service Quality', 'Technical Issue', 'Refund Request']. 
May cause Google Sheets validation error.
```

### API v4 Unavailability

If Google Sheets API v4 is not available:
- Logs DEBUG: "Google Sheets API v4 not available, skipping category validation"
- Graceful degradation: continues with append
- Validation is skipped, not enforced

## Schema Validation Rules

### Expected Schema (21 Columns)

The validation expects exactly these 21 columns in exact order:

```
[0]  Complaint ID          (formula)
[1]  message_id            (bot writes)
[2]  Date Reported         (bot writes)
[3]  Customer Name         (bot writes)
[4]  Customer ID / Account (bot writes)
[5]  Phone Number          (bot writes)
[6]  Reported By           (bot writes)
[7]  Branch / Region       (bot writes)
[8]  Complaint Category    (bot writes)
[9]  Complaint Description (bot writes)
[10] raw_message           (bot writes)
[11] gps_link              (bot writes)
[12] image_flag            (bot writes)
[13] source                (bot writes)
[14] Loan Status           (human fills)
[15] Loan at Risk          (human fills)
[16] Risk Level            (human fills)
[17] Status                (human fills)
[18] Resolution Details    (human fills)
[19] Date Resolved         (human fills)
[20] Days Open             (formula)
```

### Column Write Protection

- **Never write to [0, 20]**: These contain formulas. Writing will break them.
- **Never write to [14-19]**: These are staff workflow fields. Bot must not touch.
- **Always write to [1-13]**: Bot-controlled safe zone.

## Testing

### Test Suite: `core/tests_sheets_validation.py`

Comprehensive test coverage for both validation methods:

**GoogleSheetsValidationTests**:
- `test_validate_sheet_structure_success()`: Validates correct schema
- `test_validate_sheet_structure_wrong_column_count()`: Detects column count mismatch
- `test_validate_sheet_structure_wrong_column_name()`: Detects column name mismatch
- `test_validate_complaint_category_empty()`: Allows empty categories
- `test_validate_complaint_category_valid()`: Validates against list
- `test_validate_complaint_category_invalid()`: Rejects invalid categories
- `test_append_row_with_structure_validation()`: Validates structure before append
- `test_append_row_aborts_on_structure_mismatch()`: Aborts on structure failure
- `test_append_row_skip_validation_parameter()`: Skip validation parameter works

**ParsedMessageToSheetRowTests**:
- `test_to_sheet_row_returns_21_columns()`: Validates output length
- `test_to_sheet_row_column_order()`: Validates column positions
- `test_to_sheet_row_image_flag_formatting()`: Validates value formatting

### Running Tests

```bash
cd "c:\Users\be\Biogas Telegram Bot\biogas_bot"
python manage.py test core.tests_sheets_validation --verbosity=2
```

## Dependencies

### Required Packages

```
gspread              # Google Sheets API v3 client
google-api-python-client  # Google Sheets API v4
google-auth-httplib2      # Authentication
```

### Optional Features

- If `gspread` is not installed: All Google Sheets features disabled with warning
- If `google-api-python-client` not installed: API v4 features disabled, v3 still works
- If credentials file not configured: Service gracefully degrades to unavailable

## Safety Guarantees

### Data Integrity

1. **Schema Validation**: Prevents appending to modified Google Sheets
2. **Write Protection**: Never writes to formula or staff workflow columns
3. **Append-Only**: Never modifies existing rows, only appends new ones
4. **Deduplication**: Skips messages that already exist (idempotency)

### Error Handling

1. **Structure Mismatch**: ABORTS append (fail-safe)
2. **Category Invalid**: WARNS and continues (defensive approach)
3. **API Unavailable**: Logs and continues (graceful degradation)
4. **Row Malformed**: ABORTS append (fail-safe)

## Configuration

### Required Settings (Django settings.py)

```python
GOOGLE_SHEET_ID = "your-sheet-id"
GOOGLE_SERVICE_ACCOUNT_FILE = "/path/to/service-account.json"
GOOGLE_SHEET_TAB_NAME = "Complaints"  # Optional, defaults to Sheet1
```

### Service Credentials

The service requires a Google Service Account with:
- Scopes: `spreadsheets`, `drive`
- Permissions to: Read metadata, Append rows

## Future Enhancements

### Phase 2 Improvements

1. **Stricter Dropdown Validation**: Currently warns on failure. Could enforce fail-safe.
2. **Schema Caching**: Cache schema and only re-validate periodically (performance)
3. **Batch Validation**: Validate multiple rows before append for efficiency
4. **Custom Dropdowns**: Support reading multiple dropdown columns (not just category)
5. **Audit Trail**: Log all validation checks to database for compliance

### Production Deployment Checklist

- [ ] Test with real Google Sheet containing dropdown validation
- [ ] Verify Google Sheets API v4 is available and working
- [ ] Test structure validation with intentionally modified sheet
- [ ] Verify error logging is captured in production system
- [ ] Set up monitoring/alerts for structure validation failures
- [ ] Document recovery procedure if sheet structure is accidentally modified
- [ ] Train staff on schema protection rules

## Troubleshooting

### "Sheet structure validation failed"

**Causes**:
- Column was deleted from sheet
- Column was renamed
- Columns were reordered
- Wrong sheet is selected (if multiple tabs)

**Solution**:
1. Verify the sheet structure matches the expected schema
2. Use the header row provided in README.md to reset
3. Re-run validation after fix

### "Google Sheets API v4 not available"

**Causes**:
- `google-api-python-client` not installed
- Authentication failed
- Credentials don't have required scopes

**Solution**:
1. Install: `pip install google-api-python-client`
2. Verify credentials have `spreadsheets` scope
3. Check logs for detailed error message

### Dropdown validation returns empty list

**Causes**:
- Google Sheet doesn't have dropdown validation configured on column [8]
- API v4 not available (see above)
- Data validation is configured differently (not as LIST constraint)

**Solution**:
1. Verify dropdown is set up on column [8]
2. Right-click column → Data validation → Should be "List from a range" or "List of items"
3. Check logs to confirm API v4 initialization

## References

- [Google Sheets API v4 Documentation](https://developers.google.com/sheets/api)
- [gspread Documentation](https://docs.gspread.org/)
- [Django Logging Documentation](https://docs.djangoproject.com/en/6.0/topics/logging/)
- [Core Schema Documentation](PRODUCTION_ARCHITECTURE.md)

## Author Notes

This implementation prioritizes **data integrity** over convenience:
- Structure validation uses FAIL-SAFE: aborts on any mismatch
- Category validation uses DEFENSIVE approach: warns but continues
- API v4 gracefully degrades if unavailable
- All operations are logged for audit trail

The philosophy is: **Better to miss a complaint than to corrupt the register with invalid data.**
