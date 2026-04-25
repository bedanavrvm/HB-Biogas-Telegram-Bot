"""
Google Sheets Integration Service

Handles appending rows to a shared Google Sheet.
- NEVER overwrites existing rows
- Uses message_id (internal dedup key) for idempotency
- Safe for concurrent staff edits
- Append-only strategy preserves all formulas and dropdowns

Schema (FIXED - 21 columns):
| Complaint ID (formula) | message_id | Date Reported | Customer Name | Customer ID | Phone | Reported By | Branch/Region | Complaint Category | Complaint Description | raw_message | gps_link | image_flag | source | Loan Status | Loan at Risk | Risk Level | Status | Resolution Details | Date Resolved | Days Open (formula) |

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
try:
    import gspread
    from google.oauth2.service_account import Credentials
    _google_sheets_available = True
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
    [6]  Reported By           ← BOT WRITES (from parser.result.sender)
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
        'Reported By', 'Branch / Region', 'Complaint Category', 'Complaint Description',
        
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
        self._sheet_id = settings.GOOGLE_SHEET_ID
        self._sheet_name = getattr(settings, 'GOOGLE_SHEET_TAB_NAME', '')
        self._credentials_file = settings.GOOGLE_SERVICE_ACCOUNT_FILE
    
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
    
    def append_row(self, row: list, message_id: str = None) -> bool:
        """
        Append a single row to the Google Sheet.
        
        Args:
            row: List of values matching the fixed schema
            message_id: Optional message_id for idempotency check
            
        Returns:
            True if row was appended successfully
        """
        if not self.is_available():
            logger.warning("Google Sheets not available, skipping append")
            return False
        
        try:
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
