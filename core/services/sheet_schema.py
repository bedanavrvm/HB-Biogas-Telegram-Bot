"""Configurable Google Sheet schema support.

The application stores cases in one canonical Django model, but different
Telegram groups may mirror those cases to different spreadsheet layouts. This
module maps canonical case fields to each group's sheet headers.
"""
import json

from django.conf import settings


DEFAULT_FIELD_HEADERS = {
    'complaint_id': 'Complaint ID',
    'message_id': 'message_id',
    'date_reported': 'Date Reported',
    'customer_name': 'Customer Name',
    'customer_id': 'Customer ID / Account',
    'customer_phone': 'Phone Number',
    'reported_by': 'JBL Reported By',
    'branch_region': 'Branch / Region',
    'complaint_category': 'Complaint Category',
    'complaint_description': 'Complaint Description',
    'raw_message': 'raw_message',
    'gps_link': 'gps_link',
    'image_flag': 'image_flag',
    'source': 'source',
    'loan_status': 'Loan Status',
    'loan_at_risk': 'Loan at Risk',
    'risk_level': 'Risk Level',
    'status': 'Status',
    'resolution_details': 'Resolution Details',
    'date_resolved': 'Date Resolved',
    'days_open': 'Days Open',
}

DEFAULT_FIELD_ORDER = list(DEFAULT_FIELD_HEADERS.keys())
DEFAULT_FORMULA_FIELDS = {'complaint_id', 'days_open'}
DEFAULT_DATE_FIELDS = {'date_reported', 'date_resolved'}
DEFAULT_BOT_WRITABLE_FIELDS = {
    'message_id',
    'date_reported',
    'customer_name',
    'customer_id',
    'customer_phone',
    'reported_by',
    'branch_region',
    'complaint_description',
    'raw_message',
    'gps_link',
    'image_flag',
    'source',
}
DEFAULT_CASE_UPDATE_FIELDS = {
    'status',
    'resolution_details',
    'date_resolved',
    'risk_level',
    'loan_at_risk',
    'gps_link',
}


class SheetSchema:
    """Canonical case-field to spreadsheet-header mapping."""

    def __init__(
        self,
        field_headers: dict = None,
        columns: list = None,
        formula_fields: list = None,
        bot_writable_fields: list = None,
        case_update_fields: list = None,
        date_fields: list = None,
        header_row: int = None,
    ):
        self.field_headers = dict(DEFAULT_FIELD_HEADERS)
        self.field_headers.update(field_headers or {})

        self.columns = columns or [
            self.field_headers[field]
            for field in DEFAULT_FIELD_ORDER
            if field in self.field_headers
        ]
        self.formula_fields = set(formula_fields or DEFAULT_FORMULA_FIELDS)
        self.bot_writable_fields = set(
            bot_writable_fields or DEFAULT_BOT_WRITABLE_FIELDS
        )
        self.case_update_fields = set(
            case_update_fields or DEFAULT_CASE_UPDATE_FIELDS
        )
        self.date_fields = set(date_fields or DEFAULT_DATE_FIELDS)
        try:
            self.header_row = max(int(header_row or 1), 1)
        except (TypeError, ValueError):
            self.header_row = 1

    @classmethod
    def from_config(cls, config: dict = None) -> "SheetSchema":
        config = config or {}
        return cls(
            field_headers=config.get('field_headers') or config.get('headers'),
            columns=config.get('columns'),
            formula_fields=config.get('formula_fields'),
            bot_writable_fields=config.get('bot_writable_fields'),
            case_update_fields=config.get('case_update_fields'),
            date_fields=config.get('date_fields'),
            header_row=config.get('header_row'),
        )

    @staticmethod
    def fingerprint(config: dict = None) -> str:
        return json.dumps(config or {}, sort_keys=True)

    @staticmethod
    def normalize(value: str) -> str:
        return " ".join(str(value or "").strip().lower().split())

    def header(self, field: str) -> str:
        return self.field_headers.get(field, field)

    def headers_for_fields(self, fields: set) -> set:
        return {self.header(field) for field in fields}

    @property
    def formula_headers(self) -> set:
        return self.headers_for_fields(self.formula_fields)

    @property
    def bot_writable_headers(self) -> set:
        return self.headers_for_fields(self.bot_writable_fields)

    @property
    def case_update_headers(self) -> set:
        return self.headers_for_fields(self.case_update_fields)

    @property
    def date_headers(self) -> set:
        return self.headers_for_fields(self.date_fields)

    def value(self, values_by_header: dict, field: str) -> str:
        key = self.normalize(self.header(field))
        return str(values_by_header.get(key, '') or '').strip()

    def row_for_message(self, parsed_message) -> list:
        values = self.values_for_message(parsed_message)
        return [
            values.get(self.normalize(header), '')
            for header in self.columns
        ]

    def values_for_message(self, parsed_message) -> dict:
        field_values = {
            'complaint_id': '',
            'message_id': parsed_message.message_id,
            'date_reported': parsed_message._format_sheet_date(
                parsed_message.timestamp
            ),
            'customer_name': (
                parsed_message.customer_name.upper()
                if parsed_message.customer_name else ''
            ),
            'customer_id': parsed_message.customer_id,
            'customer_phone': parsed_message.customer_phone,
            'reported_by': (
                parsed_message.sender
                or getattr(settings, 'TELEGRAM_BOT_DISPLAY_NAME', 'Telegram Bot')
            ),
            'branch_region': parsed_message.branch_region,
            'complaint_category': parsed_message.complaint_category,
            'complaint_description': parsed_message.complaint_description,
            'raw_message': parsed_message.raw_message,
            'gps_link': parsed_message.gps_link,
            'image_flag': 'TRUE' if parsed_message.image_flag else '',
            'source': parsed_message.source,
            'loan_status': parsed_message.loan_status,
            'loan_at_risk': parsed_message.loan_at_risk,
            'risk_level': parsed_message.risk_level,
            'status': parsed_message.complaint_status,
            'resolution_details': parsed_message.resolution_details,
            'date_resolved': parsed_message._format_sheet_date(
                parsed_message.date_resolved
            ),
            'days_open': (
                str(parsed_message.days_open)
                if parsed_message.days_open is not None else ''
            ),
        }
        return {
            self.normalize(self.header(field)): value
            for field, value in field_values.items()
        }

    def update_values_by_header(self, updates: dict) -> dict:
        """Accept canonical field keys or actual sheet header names."""
        values = {}
        normalized_field_lookup = {
            self.normalize(field): field
            for field in self.field_headers
        }
        normalized_header_lookup = {
            self.normalize(header): field
            for field, header in self.field_headers.items()
        }

        for key, value in (updates or {}).items():
            normalized = self.normalize(key)
            field = (
                normalized_field_lookup.get(normalized)
                or normalized_header_lookup.get(normalized)
            )
            header = self.header(field) if field else key
            values[self.normalize(header)] = value
        return values
