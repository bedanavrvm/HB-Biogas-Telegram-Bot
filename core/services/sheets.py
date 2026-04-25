"""
Google Sheets Integration Service

Handles appending rows to a shared Google Sheet.
- NEVER overwrites existing rows (append-only)
- Uses message_id for idempotency
- Safe for concurrent staff edits

KEY FIXES (v2):
- GoogleSheetsService is now keyed per sheet_id (_instances dict)
  instead of a single global singleton.  Each group's sheet gets its
  own authenticated client, so multi-tenant writes go to the correct
  sheet.
- get_instance(sheet_id) / __init__(sheet_id) accept an explicit
  sheet_id; fall back to settings.GOOGLE_SHEET_ID when None.
- Module-level helpers (get_sheets_service, append_parsed_message_to_sheet,
  batch_append_messages) all accept an optional sheet_id parameter and
  forward it to the correct service instance.

Schema (FIXED — 21 columns):
  [0]  Complaint ID (formula — DO NOT WRITE)
  [1]  message_id
  [2]  Date Reported
  [3]  Customer Name
  [4]  Customer ID / Account
  [5]  Phone Number
  [6]  JBL Reported By
  [7]  Branch / Region
  [8]  Complaint Category
  [9]  Complaint Description
  [10] raw_message
  [11] gps_link
  [12] image_flag
  [13] source
  [14] Loan Status          ← HUMAN
  [15] Loan at Risk         ← HUMAN
  [16] Risk Level           ← HUMAN
  [17] Status               ← HUMAN
  [18] Resolution Details   ← HUMAN
  [19] Date Resolved        ← HUMAN
  [20] Days Open (formula — DO NOT WRITE)
"""
import logging
from typing import Optional
from django.conf import settings

logger = logging.getLogger(__name__)

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
        logger.warning(
            "googleapiclient not installed. "
            "Dropdown validation (API v4) will be disabled."
        )
except ImportError:
    logger.warning(
        "gspread not installed. Google Sheets features will be disabled."
    )


class GoogleSheetsService:
    """
    Service for interacting with a specific Google Sheet.

    Instances are cached per sheet_id so that each tenant's sheet gets
    its own authenticated gspread client.  Use get_instance(sheet_id)
    rather than constructing directly.

    Safety guarantees
    -----------------
    • NEVER write to [0, 20]   — formula columns
    • NEVER write to [14-19]   — human workflow columns
    • ALWAYS write to [1-13]   — bot-controlled safe zone
    • ALWAYS append new rows   — never update existing rows
    """

    # ── Per-sheet instance cache ──────────────────────────────────────
    _instances: dict = {}

    SCOPES = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive',
    ]

    SHEET_COLUMNS = [
        'Complaint ID',                                   # [0]  formula
        'message_id',                                     # [1]  dedup key
        'Date Reported', 'Customer Name',                 # [2-3]
        'Customer ID / Account', 'Phone Number',          # [4-5]
        'JBL Reported By', 'Branch / Region',            # [6-7]
        'Complaint Category', 'Complaint Description',    # [8-9]
        'raw_message', 'gps_link',                        # [10-11]
        'image_flag', 'source',                           # [12-13]
        'Loan Status', 'Loan at Risk',                    # [14-15] human
        'Risk Level', 'Status',                           # [16-17] human
        'Resolution Details', 'Date Resolved',            # [18-19] human
        'Days Open',                                      # [20]  formula
    ]

    # ------------------------------------------------------------------
    # Construction / caching
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls, sheet_id: str = None) -> "GoogleSheetsService":
        """
        Return the cached service instance for *sheet_id*.

        If *sheet_id* is None, falls back to settings.GOOGLE_SHEET_ID.
        Creates a new instance on first call for a given sheet_id.
        """
        effective_id = sheet_id or getattr(settings, 'GOOGLE_SHEET_ID', '')
        if effective_id not in cls._instances:
            cls._instances[effective_id] = cls(sheet_id=effective_id)
        return cls._instances[effective_id]

    @classmethod
    def clear_instances(cls):
        """Flush the instance cache (useful in tests)."""
        cls._instances.clear()

    def __init__(self, sheet_id: str = None):
        """
        Initialise the service for a specific *sheet_id*.

        Prefer get_instance() over constructing directly.
        """
        if not _google_sheets_available:
            logger.warning("Google Sheets service unavailable (gspread not installed)")
            return

        self._initialized = False
        self._api_initialized = False
        self._sheet_id = sheet_id or getattr(settings, 'GOOGLE_SHEET_ID', '')
        self._sheet_name = getattr(settings, 'GOOGLE_SHEET_TAB_NAME', '')
        self._credentials_file = getattr(
            settings, 'GOOGLE_SERVICE_ACCOUNT_FILE', 'credentials.json'
        )
        self._sheets_api_service = None
        self._client = None
        self._sheet = None

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _initialize(self):
        """Lazy initialisation of the gspread client for this sheet."""
        if self._initialized:
            return

        if not _google_sheets_available:
            return

        if not self._sheet_id:
            logger.warning(
                "GoogleSheetsService: no sheet_id configured — skipping init"
            )
            return

        try:
            creds = Credentials.from_service_account_file(
                self._credentials_file,
                scopes=self.SCOPES,
            )
            self._client = gspread.authorize(creds)

            if self._sheet_name:
                self._sheet = (
                    self._client.open_by_key(self._sheet_id)
                    .worksheet(self._sheet_name)
                )
            else:
                self._sheet = self._client.open_by_key(self._sheet_id).sheet1

            # Smoke-test that the sheet is accessible
            self._sheet.get_all_values()

            # Optional: Google Sheets API v4 for dropdown metadata
            if _google_sheets_api_available:
                try:
                    self._sheets_api_service = build(
                        'sheets', 'v4', credentials=creds
                    )
                    self._api_initialized = True
                    logger.debug(
                        f"Sheets API v4 ready for sheet {self._sheet_id}"
                    )
                except Exception as exc:
                    logger.warning(
                        f"Could not init Sheets API v4 for {self._sheet_id}: {exc}"
                    )

            self._initialized = True
            logger.info(
                f"GoogleSheetsService initialised for sheet {self._sheet_id}"
            )

        except FileNotFoundError:
            logger.error(
                f"Credentials file not found: {self._credentials_file}"
            )
        except Exception as exc:
            logger.error(
                f"Failed to initialise Google Sheets ({self._sheet_id}): {exc}",
                exc_info=True,
            )

    def is_available(self) -> bool:
        """Return True if the service is ready to write."""
        if not _google_sheets_available:
            return False
        try:
            self._initialize()
            return self._initialized
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def validate_sheet_structure(self) -> tuple:
        """
        Validate that the Google Sheet has exactly the expected 21-column schema.

        Returns (is_valid: bool, error_message: str).
        ABORTS the append if invalid (fail-safe).
        """
        if not self.is_available():
            return False, "Google Sheets not available"

        try:
            actual_header = self._sheet.row_values(1)

            if len(actual_header) != len(self.SHEET_COLUMNS):
                error = (
                    f"Sheet {self._sheet_id} has {len(actual_header)} columns, "
                    f"expected {len(self.SHEET_COLUMNS)}. "
                    f"Actual[:5]: {actual_header[:5]}"
                )
                logger.error(f"Sheet structure mismatch: {error}")
                return False, error

            mismatches = [
                f"[{i}] {a!r} != {e!r}"
                for i, (a, e) in enumerate(
                    zip(actual_header, self.SHEET_COLUMNS)
                )
                if a.strip() != e.strip()
            ]

            if mismatches:
                error = (
                    "Column name mismatch(es): "
                    + ", ".join(mismatches[:3])
                    + ". Sheet schema may have been modified manually."
                )
                logger.error(f"Sheet structure validation failed: {error}")
                return False, error

            logger.debug(
                f"Sheet structure OK for sheet {self._sheet_id}"
            )
            return True, ""

        except Exception as exc:
            error = f"Failed to validate sheet structure: {exc}"
            logger.error(error, exc_info=True)
            return False, error

    def get_valid_complaint_categories(self) -> list:
        """
        Fetch valid Complaint Category values from the sheet's dropdown rules.
        Uses Google Sheets API v4 metadata.  Returns [] if unavailable.
        """
        if not self.is_available():
            return []

        if not getattr(self, '_api_initialized', False):
            logger.debug(
                "Sheets API v4 not initialised — skipping category validation"
            )
            return []

        try:
            metadata = (
                self._sheets_api_service.spreadsheets()
                .get(
                    spreadsheetId=self._sheet_id,
                    fields='sheets.data(rowData(values(dataValidation)))',
                )
                .execute()
            )

            valid_categories = []
            for sheet in metadata.get('sheets', []):
                title = sheet.get('properties', {}).get('title', '')
                if self._sheet_name and title != self._sheet_name:
                    continue

                for row_idx, row in enumerate(
                    sheet.get('data', [{}])[0].get('rowData', [])
                ):
                    if row_idx == 0:
                        continue  # skip header
                    values = row.get('values', [])
                    if len(values) > 8:
                        dv = values[8].get('dataValidation', {})
                        if dv.get('type') == 'LIST':
                            cats = dv.get('condition', {}).get('values', [])
                            if cats:
                                valid_categories.extend(cats)
                                return list(set(valid_categories))

            return valid_categories

        except Exception as exc:
            logger.warning(
                f"Error fetching complaint categories via API v4: {exc}",
                exc_info=True,
            )
            return []

    def validate_complaint_category(self, category: str) -> tuple:
        """
        Validate *category* against the sheet's dropdown list.
        Empty values are always allowed (staff fills in later).
        Returns (is_valid: bool, message: str).
        """
        if not category or not category.strip():
            return True, ""

        category = category.strip()
        valid = self.get_valid_complaint_categories()

        if valid and category not in valid:
            msg = (
                f"Complaint category {category!r} not in valid list: {valid}. "
                "May cause Google Sheets validation error."
            )
            logger.warning(msg)
            return False, msg

        return True, ""

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def append_row(
        self,
        row: list,
        message_id: str = None,
        skip_validation: bool = False,
    ) -> bool:
        """
        Append a single 21-column row to the sheet.

        Safety checks (in order):
        1. Sheet structure validation   — ABORT on mismatch
        2. Idempotency check            — skip if message_id already exists
        3. Row length validation        — ABORT if wrong length
        4. Category validation          — WARN and continue if invalid
        """
        if not self.is_available():
            logger.warning(
                f"Google Sheets unavailable for sheet {self._sheet_id}, "
                "skipping append"
            )
            return False

        try:
            # ── 1. Structure validation ───────────────────────────────
            if not skip_validation:
                is_valid, error_msg = self.validate_sheet_structure()
                if not is_valid:
                    logger.error(
                        f"ABORT: structure validation failed for sheet "
                        f"{self._sheet_id}: {error_msg}"
                    )
                    return False

            # ── 2. Idempotency ────────────────────────────────────────
            if message_id and self._message_exists(message_id):
                logger.info(
                    f"Message {message_id} already in sheet {self._sheet_id}, skipping"
                )
                return True

            # ── 3. Row length ─────────────────────────────────────────
            if len(row) != len(self.SHEET_COLUMNS):
                logger.error(
                    f"Row length mismatch for sheet {self._sheet_id}: "
                    f"expected {len(self.SHEET_COLUMNS)}, got {len(row)}"
                )
                return False

            # ── 4. Category validation (defensive — warn only) ────────
            complaint_category = row[8] if len(row) > 8 else ""
            cat_valid, cat_msg = self.validate_complaint_category(
                complaint_category
            )
            if not cat_valid:
                logger.warning(
                    f"Category validation warning for sheet {self._sheet_id}: "
                    f"{cat_msg}"
                )

            # ── 5. Write ──────────────────────────────────────────────
            self._sheet.append_row(row)
            logger.info(
                f"Appended row to sheet {self._sheet_id}: "
                f"message_id={message_id or 'unknown'}"
            )
            return True

        except Exception as exc:
            logger.error(
                f"Failed to append row to sheet {self._sheet_id}: {exc}",
                exc_info=True,
            )
            return False

    def append_rows(self, rows: list, message_ids: list = None) -> dict:
        """
        Append multiple rows to the sheet.

        Returns a dict with success_count, failed_count, errors,
        synced_message_ids, failure_details.
        """
        result = {
            'success_count': 0,
            'failed_count': 0,
            'errors': [],
            'synced_message_ids': [],
            'failure_details': {},
        }

        if not self.is_available():
            logger.warning(
                f"Google Sheets unavailable for sheet {self._sheet_id}"
            )
            result['failed_count'] = len(rows)
            result['errors'].append("Google Sheets service unavailable")
            return result

        existing = set()
        if message_ids:
            existing = self._get_existing_message_ids()

        for i, row in enumerate(rows):
            mid = message_ids[i] if message_ids and i < len(message_ids) else None

            if mid and mid in existing:
                logger.info(
                    f"Message {mid} already in sheet {self._sheet_id}, skipping"
                )
                result['success_count'] += 1
                result['synced_message_ids'].append(mid)
                continue

            if len(row) != len(self.SHEET_COLUMNS):
                logger.error(
                    f"Row {i+1} length mismatch for sheet {self._sheet_id}"
                )
                result['failed_count'] += 1
                result['errors'].append(f"Invalid row length for row {i + 1}")
                continue

            try:
                self._sheet.append_row(row)
                result['success_count'] += 1
                if mid:
                    existing.add(mid)
                    result['synced_message_ids'].append(mid)
            except Exception as exc:
                err = str(exc)
                logger.error(
                    f"Failed to append row {i+1} to sheet {self._sheet_id}: {err}",
                    exc_info=True,
                )
                result['failed_count'] += 1
                result['errors'].append(f"Failed to append row {i + 1}")
                if mid:
                    result['failure_details'][mid] = err

        logger.info(
            f"Batch append to {self._sheet_id}: "
            f"{result['success_count']} ok, {result['failed_count']} failed"
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _message_exists(self, message_id: str) -> bool:
        try:
            values = self._sheet.col_values(1)
            return message_id in values
        except Exception as exc:
            logger.error(f"Error checking message existence: {exc}")
            return False  # assume not exists to avoid data loss

    def _get_existing_message_ids(self) -> set:
        try:
            return set(self._sheet.col_values(1))
        except Exception as exc:
            logger.error(f"Error reading existing message IDs: {exc}")
            return set()

    def get_sheet_url(self) -> str:
        if self._sheet_id:
            return (
                f"https://docs.google.com/spreadsheets/d/{self._sheet_id}"
            )
        return ''


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def get_sheets_service(sheet_id: str = None) -> GoogleSheetsService:
    """
    Return the GoogleSheetsService instance for *sheet_id*.

    Falls back to settings.GOOGLE_SHEET_ID when sheet_id is None.
    """
    return GoogleSheetsService.get_instance(sheet_id=sheet_id)


def append_parsed_message_to_sheet(
    parsed_message, sheet_id: str = None
) -> bool:
    """
    Append a ParsedMessage to the correct Google Sheet.

    *sheet_id* should be the sheet belonging to the message's group.
    Falls back to settings.GOOGLE_SHEET_ID when None.
    """
    service = get_sheets_service(sheet_id=sheet_id)
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
        logger.error(
            f"Exception while appending row to sheet {sheet_id}: {error_message}",
            exc_info=True,
        )

    from django.utils import timezone as tz
    parsed_message.sync_attempts += 1
    parsed_message.last_sync_error = '' if success else (
        error_message or 'Google Sheets append failed'
    )

    if success:
        parsed_message.synced_to_sheets = True
        parsed_message.synced_at = tz.now()
        logger.info(
            f"Message {parsed_message.message_id} synced to sheet {sheet_id}"
        )
    else:
        logger.warning(
            f"Message {parsed_message.message_id} failed to sync to sheet {sheet_id}"
        )

    parsed_message.save(update_fields=[
        'synced_to_sheets', 'synced_at', 'sync_attempts', 'last_sync_error',
    ])
    return success


def batch_append_messages(
    parsed_messages: list, sheet_id: str = None
) -> dict:
    """
    Append multiple ParsedMessages to the correct Google Sheet.

    *sheet_id* should be the sheet belonging to the messages' group.
    """
    service = get_sheets_service(sheet_id=sheet_id)
    rows = [msg.to_sheet_row() for msg in parsed_messages]
    message_ids = [msg.message_id for msg in parsed_messages]

    result = service.append_rows(rows, message_ids)

    from django.utils import timezone as tz
    from core.models import ParsedMessage

    synced_ids = result.get('synced_message_ids', [])
    failure_details = result.get('failure_details', {})

    if synced_ids:
        ParsedMessage.objects.filter(message_id__in=synced_ids).update(
            synced_to_sheets=True,
            synced_at=tz.now(),
            last_sync_error='',
        )

    for msg in parsed_messages:
        if msg.message_id in failure_details:
            msg.sync_attempts += 1
            msg.last_sync_error = failure_details[msg.message_id]
            msg.save(update_fields=['sync_attempts', 'last_sync_error'])

    return result