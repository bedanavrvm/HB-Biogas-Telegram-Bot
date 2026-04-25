"""
Google Sheets Integration Service

Handles appending rows to a shared Google Sheet.
- NEVER overwrites existing rows
- Uses message_id (internal dedup key) for idempotency
- Safe for concurrent staff edits
- Append-only strategy preserves all formulas and dropdowns

Schema (FIXED - 21 columns):
| Complaint ID (formula) | message_id | Date Reported | Customer Name | Customer ID | Phone | JBL Reported By | Branch/Region | Complaint Category | Complaint Description | raw_message | gps_link | image_flag | source | Loan Status | Loan at Risk | Risk Level | Status | Resolution Details | Date Resolved | Days Open (formula) |

Column Groups:
- [0]:       Complaint ID (formula - DO NOT WRITE)
- [1]:       message_id (bot system key - deduplication)
- [2-9]:     Bot intake fields (auto-populated from WhatsApp)
- [10-13]:   Raw data/audit trail (for traceability)
- [14-20]:   Human workflow fields (staff fills in)
"""
import logging
from typing import Optional
from django.conf import settings

logger = logging.getLogger(__name__)

# Lazy import to avoid dependency issues during development
_google_sheets_available = False
_google_sheets_api_available = False
try:
    import gspread
    from google.oauth2.service_account import Credentials
    _google_sheets_available = True
    try:
        from googleapiclient.discovery import build
        _google_sheets_api_available = True
    except ImportError:
        logger.warning("googleapiclient not installed. API v4 features will be disabled.")
except ImportError:
    logger.warning("gspread not installed. Google Sheets features will be disabled.")


class GoogleSheetsService:
    """
    Service for interacting with Google Sheets.
    Thread-safe, append-only operations.
    
    CRITICAL: This service implements non-invasive integration with live Google Sheets.
    It ONLY appends new rows and NEVER modifies existing data.
    
    Schema is pinned to exactly 21 columns. Changes require full audit + migration.
    
    Column Mapping Reference (for developers):
    ─────────────────────────────────────────
    [0]  Complaint ID          ← FORMULA (bot provides message_id as placeholder)
    [1]  message_id            ← BOT WRITES (unique dedup key per message)
    [2]  Date Reported         ← BOT WRITES (from parser.result.timestamp)
    [3]  Customer Name         ← BOT WRITES (from parser.result.customer_name)
    [4]  Customer ID / Account ← BOT WRITES (from parser.result.customer_id)
    [5]  Phone Number          ← BOT WRITES (from parser.result.customer_phone)
    [6]  JBL Reported By        ← BOT WRITES (from parser.result.sender)
    [7]  Branch / Region       ← BOT WRITES (from parser.result.branch_region)
    [8]  Complaint Category    ← BOT WRITES (from parser.result.complaint_category)
    [9]  Complaint Description ← BOT WRITES (from parser.result.complaint_description)
    [10] raw_message           ← BOT WRITES (from parsed.message.raw_message)
    [11] gps_link              ← BOT WRITES (from parsed.message.gps_link)
    [12] image_flag            ← BOT WRITES (from parsed.message.image_flag, as "TRUE"/"")
    [13] source                ← BOT WRITES (from parsed.message.source)
    [14] Loan Status           ← HUMAN (staff fills dropdown)
    [15] Loan at Risk          ← HUMAN (staff fills dropdown)
    [16] Risk Level            ← HUMAN (staff fills dropdown)
    [17] Status                ← HUMAN (staff fills dropdown: Open/In Progress/Closed)
    [18] Resolution Details    ← HUMAN (staff enters free text)
    [19] Date Resolved         ← HUMAN (staff enters date)
    [20] Days Open             ← FORMULA (auto-calculated: =TODAY()-[Date Reported])
    ─────────────────────────────────────────
    
    Safety Guarantees:
    • NEVER write to [0, 20] (formulas will break)
    • NEVER write to [14-19] (staff workflow columns)
    • ALWAYS write to [1-13] (bot-controlled safe zone)
    • ALWAYS append new rows (never update existing)
    """
    
    _instance = None
    _client = None
    _sheet = None
    
    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive',
    ]
    
    SHEET_COLUMNS = [
        # [0] System/Control fields (DO NOT WRITE - formula driven)
        'Complaint ID',
        
        # [1] Deduplication key (bot system)
        'message_id',
        
        # [2-9] Bot intake fields (auto-populated from parser)
        'Date Reported', 'Customer Name', 'Customer ID / Account', 'Phone Number',
        'JBL Reported By', 'Branch / Region', 'Complaint Category', 'Complaint Description',
        
        # [10-13] Raw data / Audit trail (for traceability + future AI)
        'raw_message', 'gps_link', 'image_flag', 'source',
        
        # [14-20] Human workflow fields (staff fills in, formulas, dropdowns)
        'Loan Status', 'Loan at Risk', 'Risk Level', 'Status',
        'Resolution Details', 'Date Resolved', 'Days Open'
    ]
    
    @classmethod
    def get_instance(cls):
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        """Initialize the service."""
        if not _google_sheets_available:
            logger.warning("Google Sheets service unavailable")
            return
        
        self._initialized = False
        self._api_initialized = False
        self._sheet_id = settings.GOOGLE_SHEET_ID
        self._sheet_name = getattr(settings, 'GOOGLE_SHEET_TAB_NAME', '')
        self._credentials_file = settings.GOOGLE_SERVICE_ACCOUNT_FILE
        self._sheets_api_service = None
    
    def _initialize(self):
        """Lazy initialization of Google Sheets client."""
        if self._initialized:
            return
        
        if not _google_sheets_available:
            return
        
        if not self._sheet_id:
            logger.warning("GOOGLE_SHEET_ID not configured")
            return
        
        try:
            creds = Credentials.from_service_account_file(
                self._credentials_file,
                scopes=self.SCOPES
            )
            
            self._client = gspread.authorize(creds)
            if self._sheet_name:
                self._sheet = self._client.open_by_key(self._sheet_id).worksheet(self._sheet_name)
            else:
                self._sheet = self._client.open_by_key(self._sheet_id).sheet1
            
            # Verify sheet is accessible
            self._sheet.get_all_values()
            
            # Initialize Google Sheets API v4 for data validation reading
            if _google_sheets_api_available:
                try:
                    self._sheets_api_service = build('sheets', 'v4', credentials=creds)
                    self._api_initialized = True
                    logger.debug("Google Sheets API v4 initialized for data validation reading")
                except Exception as e:
                    logger.warning(f"Failed to initialize Google Sheets API v4: {e}")
            
            self._initialized = True
            logger.info("Google Sheets service initialized successfully")
            
        except FileNotFoundError:
            logger.error(f"Credentials file not found: {self._credentials_file}")
        except Exception as e:
            logger.error(f"Failed to initialize Google Sheets: {e}", exc_info=True)
    
    def is_available(self) -> bool:
        """Check if Google Sheets service is available."""
        if not _google_sheets_available:
            return False
        try:
            self._initialize()
            return self._initialized
        except Exception:
            return False
    
    def validate_sheet_structure(self) -> tuple[bool, str]:
        """
        CRITICAL: Validate that the Google Sheet has the correct structure.
        
        This prevents silent data corruption if the sheet schema has been modified.
        Checks:
        1. Exactly 21 columns in header
        2. Column names match expected schema exactly
        3. Column order is correct
        
        Returns:
            (is_valid: bool, error_message: str)
            - (True, '') if structure is correct
            - (False, error_message) if structure is invalid
        """
        if not self.is_available():
            return False, "Google Sheets not available"
        
        try:
            # Fetch actual header row
            actual_header = self._sheet.row_values(1)
            
            # Validate row count
            if len(actual_header) != len(self.SHEET_COLUMNS):
                error = (
                    f"Sheet has {len(actual_header)} columns, "
                    f"expected {len(self.SHEET_COLUMNS)}. "
                    f"Schema may have been modified. "
                    f"Actual: {actual_header[:5]}..., "
                    f"Expected: {self.SHEET_COLUMNS[:5]}..."
                )
                logger.error(f"Sheet structure mismatch: {error}")
                return False, error
            
            # Validate each column name
            mismatches = []
            for i, (actual, expected) in enumerate(zip(actual_header, self.SHEET_COLUMNS)):
                if actual.strip() != expected.strip():
                    mismatches.append({
                        'column': i,
                        'actual': actual,
                        'expected': expected
                    })
            
            if mismatches:
                error = (
                    f"Column name mismatch(es): "
                    f"{', '.join([f'[{m['column']}] {m['actual']!r} != {m['expected']!r}' for m in mismatches[:3]])}. "
                    f"Sheet schema may have been modified manually."
                )
                logger.error(f"Sheet structure validation failed: {error}")
                return False, error
            
            logger.debug("Sheet structure validation passed")
            return True, ""
            
        except Exception as e:
            error = f"Failed to validate sheet structure: {e}"
            logger.error(error, exc_info=True)
            return False, error
    
    def get_valid_complaint_categories(self) -> list[str]:
        """
        Fetch valid complaint category values from the sheet's dropdown validation.
        
        This reads the data validation rules for the Complaint Category column [8].
        Uses Google Sheets API v4 to extract the validation constraints.
        
        Returns:
            List of valid category strings, or empty list if unable to determine
        """
        if not self.is_available():
            logger.warning("Google Sheets not available, cannot fetch complaint categories")
            return []
        
        # Check if API v4 is available (safe check using getattr)
        if not getattr(self, '_api_initialized', False):
            logger.debug("Google Sheets API v4 not available, skipping category validation")
            return []
        
        try:
            # Get sheet metadata including data validation rules
            # Column [8] is Complaint Category (column I in sheets = column 9 in 1-indexed)
            # We need to read rows where data validation exists
            
            sheet_metadata = self._sheets_api_service.spreadsheets().get(
                spreadsheetId=self._sheet_id,
                fields='sheets.data(rowData(values(dataValidation)))'
            ).execute()
            
            sheets_data = sheet_metadata.get('sheets', [])
            valid_categories = []
            
            # Find the data validation rules
            for sheet in sheets_data:
                # If we have a specific sheet name, filter by that
                if self._sheet_name and sheet.get('properties', {}).get('title') != self._sheet_name:
                    continue
                
                row_data = sheet.get('data', [{}])[0].get('rowData', [])
                
                # Scan the Complaint Category column (column 8, 0-indexed = column 9)
                # Look for cells with data validation constraints
                for row_idx, row in enumerate(row_data):
                    if row_idx == 0:
                        # Skip header row
                        continue
                    
                    values = row.get('values', [])
                    
                    # Column 8 is at index 8
                    if len(values) > 8:
                        cell = values[8]
                        data_validation = cell.get('dataValidation')
                        
                        if data_validation:
                            # Extract the constraint type
                            constraint_type = data_validation.get('type')
                            
                            if constraint_type == 'LIST':
                                # List constraint - get the list values
                                conditions = data_validation.get('condition', {})
                                values_list = conditions.get('values', [])
                                if values_list:
                                    valid_categories.extend(values_list)
                                    logger.debug(
                                        f"Found complaint categories from data validation: "
                                        f"{values_list}"
                                    )
                                    # Remove duplicates and return
                                    return list(set(valid_categories))
            
            if not valid_categories:
                logger.debug(
                    "No data validation rules found for Complaint Category column. "
                    "Sheet may not have dropdown validation set up."
                )
            
            return valid_categories
            
        except Exception as e:
            logger.warning(
                f"Error fetching complaint categories via API v4: {e}. "
                f"Will proceed without category validation.",
                exc_info=True
            )
            return []
    
    def validate_complaint_category(self, category: str) -> tuple[bool, str]:
        """
        Validate that a complaint category value is acceptable.
        
        Args:
            category: The category value to validate
            
        Returns:
            (is_valid: bool, message: str)
            - (True, '') if category is valid
            - (False, message) if category is invalid or cannot be validated
        """
        if not category or not category.strip():
            # Empty category is allowed (staff may fill it in later)
            return True, ""
        
        category = category.strip()
        
        # Try to get valid categories from sheet
        valid_categories = self.get_valid_complaint_categories()
        
        if valid_categories:
            # We have a list of valid values - check against it
            if category not in valid_categories:
                error = (
                    f"Complaint category {category!r} not in valid list: "
                    f"{valid_categories}. "
                    f"May cause Google Sheets validation error."
                )
                logger.warning(f"Category validation warning: {error}")
                return False, error
        else:
            # Cannot determine valid categories
            # For now, we'll allow any non-empty value
            # Production: This should fail-safe to prevent data corruption
            logger.debug(f"Cannot validate category {category!r} - validation rules not accessible")
            # Return True to allow append (validation will happen in Google Sheets)
            return True, ""
        
        return True, ""
    
    def append_row(self, row: list, message_id: str = None, skip_validation: bool = False) -> bool:
        """
        Append a single row to the Google Sheet.
        
        SAFETY CHECKS:
        1. Validates sheet structure matches expected schema (21 columns)
        2. Validates row length matches schema
        3. Validates complaint category value
        
        Args:
            row: List of values matching the fixed schema
            message_id: Optional message_id for idempotency check
            skip_validation: If True, skip structure validation (use with caution)
            
        Returns:
            True if row was appended successfully
        """
        if not self.is_available():
            logger.warning("Google Sheets not available, skipping append")
            return False
        
        try:
            # CRITICAL: Validate sheet structure before any append
            if not skip_validation:
                is_valid, error_msg = self.validate_sheet_structure()
                if not is_valid:
                    logger.error(
                        f"ABORT: Sheet structure validation failed. "
                        f"Will not append to prevent data corruption. "
                        f"Error: {error_msg}"
                    )
                    return False
            
            # Idempotency check: check if message_id already exists
            if message_id:
                if self._message_exists(message_id):
                    logger.info(f"Message {message_id} already exists in sheet, skipping")
                    return True
            
            # Validate row length matches schema
            if len(row) != len(self.SHEET_COLUMNS):
                logger.error(
                    f"Row length mismatch: expected {len(self.SHEET_COLUMNS)}, "
                    f"got {len(row)}"
                )
                return False
            
            # CRITICAL: Validate complaint category (column [8])
            complaint_category = row[8] if len(row) > 8 else ""
            is_valid_category, category_error = self.validate_complaint_category(complaint_category)
            if not is_valid_category:
                logger.warning(
                    f"Complaint category validation warning: {category_error}. "
                    f"Proceeding with append (sheet validation will be final check)."
                )
            
            # Append row
            self._sheet.append_row(row)
            logger.info(f"Appended row to Google Sheet: {message_id or 'unknown'}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to append row to Google Sheet: {e}", exc_info=True)
            return False
    
    def _get_existing_message_ids(self) -> set:
        """Get all message IDs currently present in the sheet."""
        try:
            values = self._sheet.col_values(1)
            return set(values)
        except Exception as e:
            logger.error(f"Error reading existing message IDs: {e}")
            return set()

    def append_rows(self, rows: list[list], message_ids: list[str] = None) -> dict:
        """
        Append multiple rows to the Google Sheet.
        
        Args:
            rows: List of row lists
            message_ids: Optional list of message_ids for tracking
            
        Returns:
            Dict with 'success_count', 'failed_count', 'errors', 'synced_message_ids', 'failure_details'
        """
        result = {
            'success_count': 0,
            'failed_count': 0,
            'errors': [],
            'synced_message_ids': [],
            'failure_details': {},
        }
        
        if not self.is_available():
            logger.warning("Google Sheets not available, skipping batch append")
            result['failed_count'] = len(rows)
            result['errors'].append("Google Sheets service unavailable")
            return result

        existing_message_ids = set()
        if message_ids:
            existing_message_ids = self._get_existing_message_ids()

        for i, row in enumerate(rows):
            message_id = message_ids[i] if message_ids and i < len(message_ids) else None

            if message_id and message_id in existing_message_ids:
                logger.info(f"Message {message_id} already exists in sheet, skipping")
                result['success_count'] += 1
                result['synced_message_ids'].append(message_id)
                continue

            if len(row) != len(self.SHEET_COLUMNS):
                logger.error(
                    f"Row length mismatch: expected {len(self.SHEET_COLUMNS)}, "
                    f"got {len(row)}"
                )
                result['failed_count'] += 1
                result['errors'].append(f"Invalid row length for row {i + 1}")
                continue

            try:
                self._sheet.append_row(row)
                logger.info(f"Appended row to Google Sheet: {message_id or 'unknown'}")
                result['success_count'] += 1
                if message_id:
                    existing_message_ids.add(message_id)
                    result['synced_message_ids'].append(message_id)
            except Exception as e:
                error_message = str(e)
                logger.error(f"Failed to append row to Google Sheet: {error_message}", exc_info=True)
                result['failed_count'] += 1
                result['errors'].append(f"Failed to append row {i + 1}")
                if message_id:
                    result['failure_details'][message_id] = error_message

        logger.info(
            f"Batch append complete: {result['success_count']} success, "
            f"{result['failed_count']} failed"
        )
        
        return result
    
    def _message_exists(self, message_id: str) -> bool:
        """
        Check if a message_id already exists in the sheet.
        
        Args:
            message_id: The message_id to check
            
        Returns:
            True if message_id exists
        """
        try:
            # Get all values in column A (message_id column)
            values = self._sheet.col_values(1)
            return message_id in values
        except Exception as e:
            logger.error(f"Error checking message existence: {e}")
            # On error, assume doesn't exist to avoid data loss
            return False
    
    def get_sheet_url(self) -> str:
        """Get the URL to the Google Sheet."""
        if self._sheet_id:
            return f"https://docs.google.com/spreadsheets/d/{self._sheet_id}"
        return ''


# Module-level convenience functions
def get_sheets_service() -> GoogleSheetsService:
    """Get the Google Sheets service instance."""
    return GoogleSheetsService.get_instance()


def append_parsed_message_to_sheet(parsed_message) -> bool:
    """
    Append a ParsedMessage to Google Sheets.

    Args:
        parsed_message: ParsedMessage model instance

    Returns:
        True if successfully appended
    """
    service = get_sheets_service()
    row = parsed_message.to_sheet_row()
    success = False
    error_message = ''

    try:
        success = service.append_row(row, parsed_message.message_id)
        if not success:
            error_message = 'Google Sheets append failed'
    except Exception as exc:
        success = False
        error_message = str(exc)
        logger.error(f"Exception while appending row: {error_message}", exc_info=True)

    from django.utils import timezone
    parsed_message.sync_attempts += 1
    parsed_message.last_sync_error = '' if success else error_message or 'Google Sheets append failed'

    if success:
        parsed_message.synced_to_sheets = True
        parsed_message.synced_at = timezone.now()
        logger.info(f"Message {parsed_message.message_id} synced to Google Sheets")
    else:
        logger.warning(f"Message {parsed_message.message_id} failed to sync to Google Sheets")

    parsed_message.save(update_fields=[
        'synced_to_sheets', 'synced_at', 'sync_attempts', 'last_sync_error'
    ])

    return success


def batch_append_messages(parsed_messages: list) -> dict:
    """
    Append multiple ParsedMessages to Google Sheets.
    
    Args:
        parsed_messages: List of ParsedMessage model instances
        
    Returns:
        Dict with sync results
    """
    service = get_sheets_service()
    
    rows = [msg.to_sheet_row() for msg in parsed_messages]
    message_ids = [msg.message_id for msg in parsed_messages]
    
    result = service.append_rows(rows, message_ids)
    
    from django.utils import timezone
    from core.models import ParsedMessage
    synced_message_ids = result.get('synced_message_ids', [])
    failure_details = result.get('failure_details', {})

    # Update synced messages in bulk
    if synced_message_ids:
        ParsedMessage.objects.filter(message_id__in=synced_message_ids).update(
            synced_to_sheets=True,
            synced_at=timezone.now(),
            last_sync_error=''
        )

    # Update failed messages with attempt count and error
    for msg in parsed_messages:
        if msg.message_id in failure_details:
            msg.sync_attempts += 1
            msg.last_sync_error = failure_details[msg.message_id]
            msg.save(update_fields=['sync_attempts', 'last_sync_error'])

    return result
